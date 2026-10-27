#!/usr/bin/env python3
"""Установить выбранный релиз SDD Framework в проект-потребитель."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, unquote

import build_release
import fs_boundary


def _read_text(path: Path) -> str:
    return fs_boundary.read_bytes(path).decode("utf-8")


def _write_text(path: Path, content: str, *, expected: str | None = None, create_only: bool = False) -> None:
    data = content.encode("utf-8")
    if expected is not None:
        fs_boundary.replace_if_same(path, expected.encode("utf-8"), data)
    else:
        fs_boundary.write_bytes(path, data, create_only=create_only)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install, update, or switch an SDD Framework release from release-registry.json."
    )
    parser.add_argument("--source-root", type=Path, help="Корень чистой копии исходного репозитория.")
    parser.add_argument("--target-root", type=Path, default=Path("."), help="Корень проекта-потребителя.")
    parser.add_argument(
        "--action",
        choices=("init", "update", "use"),
        help="Операция: первичная установка, обновление или установка указанной версии.",
    )
    parser.add_argument("--version", help="Точная версия для действия use.")
    parser.add_argument(
        "--old-action",
        choices=("auto", "ask", "keep", "move", "delete"),
        default="auto",
        help="Действие со старым релизом после подтверждения пользователя.",
    )
    parser.add_argument(
        "--cleanup-action",
        choices=("keep", "delete"),
        help="Завершить отдельное подтверждение очистки клона: оставить или удалить.",
    )
    parser.add_argument(
        "--cleanup-fingerprint",
        help="Fingerprint inventory, явно подтверждённый пользователем для удаления source clone.",
    )
    parser.add_argument(
        "--old-confirmation",
        help="Fingerprint inventory старого release, явно подтверждённый пользователем для move/delete.",
    )
    parser.add_argument(
        "--agents-action",
        choices=("ask", "keep", "migrate", "replace-legacy", "replace-managed"),
        default="ask",
        help="Разрешение расхождений AGENTS.md после подтверждения пользователя.",
    )
    parser.add_argument(
        "--project-structure-action",
        choices=("ask", "keep", "migrate", "replace"),
        default="ask",
        help="Разрешение расхождений корневого .project-structure.json.",
    )
    parser.add_argument("--write", action="store_true", help="Выполнить изменения; без флага только показать план.")
    parser.add_argument(
        "--report", choices=("compact", "full"), default="compact",
        help="Краткий отчёт для обычного запуска или полный отчёт для диагностики.",
    )
    return parser.parse_args()


def version_key(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def installed_release(target_root: Path) -> tuple[str | None, Path | None]:
    agents_dir = target_root / ".agents"
    build_release.ensure_path_without_symlinks(target_root, agents_dir, "каталог релизов")
    if not agents_dir.is_dir():
        return None, None
    releases = build_release.direct_release_dirs(agents_dir, allow_alias=True)
    unknown = [
        child for child, kind in fs_boundary.list_children(agents_dir)
        if kind == "directory" and child.name.startswith("sdd") and child not in releases
    ]
    if unknown:
        names = ", ".join(path.name for path in unknown)
        raise build_release.BuildError(f"В .agents обнаружены неизвестные каталоги SDD: {names}")
    if not releases:
        return None, None
    if len(releases) > 1:
        structure = normalized_json(target_root / ".project-structure.json")
        framework = structure.get("framework") if isinstance(structure, dict) else None
        selected = framework.get("release_dir") if isinstance(framework, dict) else None
        matches = [path for path in releases if path.relative_to(target_root).as_posix() == selected]
        if len(matches) != 1:
            names = ", ".join(path.name for path in releases)
            raise build_release.BuildError(
                f"Несколько релизов в .agents без единственного проверяемого указателя: {names}"
            )
        release = matches[0]
    else:
        release = releases[0]
    match = build_release.RELEASE_PATTERN.fullmatch(release.name)
    if match is None:
        raise build_release.BuildError(f"Некорректное имя установленного релиза: {release.name}")
    if os.path.lexists(_framework_alias(target_root)):
        _verify_active_alias(target_root, match.group(1), allow_other_version=True)
    return match.group(1), release


def choose_version(registry: dict[str, object], action: str, requested: str | None) -> str:
    if action == "use":
        if requested is None or not build_release.VERSION_NUMBER_PATTERN.fullmatch(requested):
            raise build_release.BuildError("Для действия use требуется корректная версия X.Y.Z.")
        return requested
    if requested is not None:
        raise build_release.BuildError("Параметр --version разрешён только для действия use.")
    default_version = registry.get("default_version")
    if not isinstance(default_version, str):
        raise build_release.BuildError("В реестре отсутствует default_version.")
    return default_version


def free_backup_path(target_root: Path, version: str) -> Path:
    tmp_dir = target_root / "tmp"
    build_release.ensure_path_without_symlinks(target_root, tmp_dir, "каталог резервных копий")
    candidate = tmp_dir / f"sdd-template-old-{version}"
    number = 2
    while candidate.exists():
        candidate = tmp_dir / f"sdd-template-old-{version}-{number}"
        number += 1
    return candidate


def validate_source_clone_name(source_root: Path, version: str) -> None:
    """Проверить, что имя клона соответствует фактическому commit выбранного релиза."""
    source_commit = build_release.git_value(source_root, ["rev-parse", "HEAD"], "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise build_release.BuildError("Невозможно определить commit чистой копии исходного репозитория.")
    expected_name = f"sdd-template-source-{version}-{source_commit[:8]}"
    if source_root.name != expected_name:
        raise build_release.BuildError(
            f"Имя клона {source_root.name} не соответствует фактическому commit. "
            f"Ожидалось {expected_name}. Не используйте предварительный или переименованный клон."
        )


def is_external_source_clone(target_root: Path, source_root: Path) -> bool:
    """Проверить, что клон находится в отдельном каталоге временного workspace."""
    temp_root = Path(tempfile.gettempdir()).resolve()
    source_root = Path(os.path.abspath(source_root))
    parent = source_root.parent
    if parent.parent != temp_root or re.fullmatch(r"sdd-template-update-[0-9a-f]{32}", parent.name) is None:
        return False
    build_release.ensure_path_without_symlinks(temp_root, parent, "временный workspace установщика")
    build_release.ensure_path_without_symlinks(parent, source_root, "source clone установщика")
    return source_root != Path(os.path.abspath(target_root))


def validate_source_location(target_root: Path, source_root: Path) -> None:
    """Разрешить старый project/tmp-контур и изолированный OS-temp workspace."""
    target_root = Path(os.path.abspath(target_root))
    source_root = Path(os.path.abspath(source_root))
    local_tmp = target_root / "tmp"
    local = source_root.parent == local_tmp and source_root.name.startswith("sdd-template-source-")
    if local:
        build_release.ensure_path_without_symlinks(target_root, local_tmp, "каталог временных файлов проекта")
        build_release.ensure_path_without_symlinks(local_tmp, source_root, "source clone Framework")
        return
    if is_external_source_clone(target_root, source_root):
        return
    raise build_release.BuildError(
        "Source clone должен быть непосредственным каталогом tmp/sdd-template-source-* проекта "
        "или отдельным sdd-template-update-<uuid> в OS temp."
    )


def verify_install_source(source_root: Path, entry: Mapping[str, object], inventory: dict[str, object]) -> None:
    """Проверить неизменяемый ref и чистоту клона перед записью пакета."""
    if inventory.get("safe_to_delete") is not True:
        raise build_release.BuildError(
            "Source clone содержит изменения или неизвестные файлы; установка из него заблокирована."
        )
    git_report = inventory.get("git")
    statuses = git_report.get("status_entries") if isinstance(git_report, dict) else None
    if not isinstance(statuses, dict) or any(
        not isinstance(path, str) or not (path == "tmp" or path.startswith("tmp/sdd-template-build-"))
        for path in statuses
    ):
        raise build_release.BuildError("Git status source clone изменился; установка заблокирована.")
    head = build_release.git_value(source_root, ["rev-parse", "HEAD"], "")
    ref = entry.get("ref")
    ref_type = entry.get("ref_type")
    registered_commit = entry.get("commit")
    if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise build_release.BuildError("Невозможно проверить commit source clone.")
    if ref_type == "tag" and entry.get("tag") == ref:
        resolved = build_release.git_value(
            source_root, ["rev-parse", "--verify", f"refs/tags/{ref}^{{commit}}"], ""
        )
    elif ref_type == "commit" and re.fullmatch(r"[0-9a-f]{40}", ref):
        resolved = ref
    else:
        raise build_release.BuildError("Реестр не задаёт корректный неизменяемый ref.")
    if resolved != head or (registered_commit is not None and registered_commit != head):
        raise build_release.BuildError("Commit source clone не совпадает с immutable ref реестра.")


PROJECT_ROOT_TEMPLATES = (
    Path(".source") / "README.md",
    Path(".tasks") / "README.md",
    Path(".tasks") / "done" / ".gitkeep",
    Path(".tasks") / "pdd" / "@todoregistry.md",
    Path(".issues") / "README.md",
    Path(".issues") / "done" / ".gitkeep",
)

GITIGNORE_RULES = (
    ".project-structure.json",
    "tmp/",
    ".source/",
    ".tasks/done/",
    ".issues/done/",
    ".agents/sdd-template-*/",
)

AGENTS_MANAGED_BEGIN = "<!-- SDD Framework: managed section begin -->"
AGENTS_MANAGED_END = "<!-- SDD Framework: managed section end -->"
AGENTS_VERSION_PATTERN = re.compile(r"\.agents[/\\]sdd-template-([0-9]+\.[0-9]+\.[0-9]+)")
FRAMEWORK_ROOT_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.\-/])\.agents[/\\]sdd-template-(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"
    r"(?:[/\\][^\s`'\"<>),;]+)?"
)
LEGACY_FRAMEWORK_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.\-/])\.(?P<root>manifest|requirements|tools|approach|chatlog)"
    r"(?:[/\\][^\s`'\"<>),;]+)?"
)
FRAMEWORK_ROOTS = {".manifest", ".requirements", ".tools", ".approach", ".chatlog"}
POST_INSTALL_SCAN_ROOTS = (
    "AGENTS.md",
    ".project-structure.json",
    ".approach",
    ".catalog",
    ".issues",
    ".requirements",
    ".source",
    ".tasks",
    "docs",
)
POST_INSTALL_TEXT_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml"}
LEGACY_AGENTS_SIGNATURES = (
    "# Rules and Constraints for Codex (H0)",
    "### H1.1.",
    "### H1.3.",
    "## H1.8.",
    "## H1.10",
)


def _clean_framework_path(value: str) -> str:
    """Нормализовать найденный путь, не меняя содержимое исходного документа."""
    return value.rstrip(".,:;!?)]}>")


def _match_position(match: dict[str, object], key: str) -> int:
    value = match.get(key)
    return value if isinstance(value, int) else 0


def _framework_path_matches(value: str) -> list[dict[str, object]]:
    """Найти конкретные versioned и legacy пути Framework в строке."""
    matches: list[dict[str, object]] = []
    for match in FRAMEWORK_ROOT_PATH_PATTERN.finditer(value):
        path = _clean_framework_path(match.group(0))
        matches.append(
            {
                "path": path,
                "start": match.start(),
                "end": match.start() + len(path),
                "kind": "versioned",
                "version": match.group("version"),
            }
        )
    for match in LEGACY_FRAMEWORK_PATH_PATTERN.finditer(value):
        path = _clean_framework_path(match.group(0))
        matches.append(
            {
                "path": path,
                "start": match.start(),
                "end": match.start() + len(path),
                "kind": "legacy-root",
                "root": "." + match.group("root"),
            }
        )
    return sorted(matches, key=lambda item: (_match_position(item, "start"), _match_position(item, "end")))


def _framework_root(version: str) -> str:
    return f".agents/sdd-template-{version}"


def _framework_alias(target_root: Path) -> Path:
    return target_root / ".agents" / "sdd-template-current"


def _alias_required(version: str) -> bool:
    return False


def _verify_active_alias(
    target_root: Path, version: str, *, allow_other_version: bool = False
) -> tuple[str, Path]:
    alias = _framework_alias(target_root)
    agents_root = (target_root / ".agents").resolve(strict=True)
    resolved = alias.resolve(strict=True)
    if resolved.parent != agents_root:
        raise build_release.BuildError("Постоянный адрес Framework выходит за пределы .agents/.")
    match = build_release.RELEASE_PATTERN.fullmatch(resolved.name)
    if match is None:
        raise build_release.BuildError("Постоянный адрес Framework ведёт не на каталог версии.")
    alias_version = match.group(1)
    if not allow_other_version and alias_version != version:
        raise build_release.BuildError("Постоянный адрес Framework указывает на другую версию.")
    fs_boundary.verify_directory_alias(alias, resolved)
    return alias_version, resolved


def _begin_alias_switch(target_root: Path, current_version: str | None, version: str) -> None:
    alias = _framework_alias(target_root)
    if not os.path.lexists(alias):
        return
    if current_version is None:
        raise build_release.BuildError(f"Неизвестный постоянный адрес Framework: {alias}")
    _verify_active_alias(target_root, current_version)
    if current_version != version:
        fs_boundary.remove_directory_alias(alias, target_root / Path(_framework_root(current_version)))


def _finish_alias_switch(target_root: Path, version: str) -> None:
    alias = _framework_alias(target_root)
    if os.path.lexists(alias):
        _, resolved = _verify_active_alias(target_root, version, allow_other_version=True)
        fs_boundary.remove_directory_alias(alias, resolved)


def _verify_old_release_before_action(path: Path, expected_fingerprint: object) -> None:
    current = inventory_release(path)
    if current.get("errors") or current.get("fingerprint") != expected_fingerprint:
        raise build_release.BuildError(
            "Inventory старого релиза изменился после подтверждения; перенос или удаление заблокированы."
        )


def _rewrite_framework_paths(value: str, version: str) -> str:
    """Перевести только известные корневые пути Framework на текущий release."""
    current_root = _framework_root(version)
    matches = _framework_path_matches(value)
    if not matches:
        return value
    rewritten: list[str] = []
    cursor = 0
    for item in matches:
        start = _match_position(item, "start")
        end = _match_position(item, "end")
        path = str(item["path"])
        if start < cursor:
            continue
        rewritten.append(value[cursor:start])
        if item["kind"] == "versioned":
            normalized_path = path.replace("\\", "/")
            old_root = f".agents/sdd-template-{item['version']}"
            suffix = normalized_path[len(old_root) :].lstrip("/")
            replacement = f"{current_root}/{suffix}" if suffix else current_root
        else:
            root = str(item["root"])
            suffix = path[len(root) :].lstrip("/\\")
            replacement = f"{current_root}/{root}"
            if suffix:
                replacement += f"/{suffix}"
        rewritten.append(replacement)
        cursor = end
    rewritten.append(value[cursor:])
    return "".join(rewritten)


def agents_managed_block(source_root: Path) -> str:
    """Сформировать краткий managed-блок для использования Framework в проекте."""
    source = source_root / ".tools" / "sdd-template-release" / "templates" / "consumer-agents.md"
    if not source.is_file():
        raise build_release.BuildError(f"В источнике отсутствует шаблон инструкций проекта-потребителя: {source}")
    try:
        content = _read_text(source)
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно прочитать шаблон инструкций проекта-потребителя: {error}") from error
    if not content.strip():
        raise build_release.BuildError("Шаблон инструкций проекта-потребителя не должен быть пустым.")
    if AGENTS_MANAGED_BEGIN in content or AGENTS_MANAGED_END in content:
        raise build_release.BuildError("Шаблон инструкций проекта-потребителя не должен содержать управляемые маркеры.")
    return f"{AGENTS_MANAGED_BEGIN}\n{content.rstrip(chr(13) + chr(10))}\n{AGENTS_MANAGED_END}\n"


def detect_agents_conflicts(content: str, version: str) -> list[str]:
    conflicts: list[str] = []
    for line in content.splitlines():
        normalized = line.lower()
        prohibits_agents = re.search(r"не\s+(?:измен|редакт|добав)[^\n]*agents\.md", normalized)
        prohibits_agents_after_name = re.search(r"agents\.md[^\n]*(?:не\s+измен|не\s+редакт|не\s+добав)", normalized)
        qualified_exception = "вне управляемого раздела" in normalized or "кроме управляемого раздела" in normalized
        if (prohibits_agents or prohibits_agents_after_name) and not qualified_exception:
            conflicts.append("существующее правило запрещает изменение AGENTS.md")
            break
    if re.search(r"(?i)(?:не\s+создавать|не\s+использовать|запрещено[^\n]*использовать)[^\n]*\.agents", content):
        conflicts.append("существующее правило запрещает использование каталога .agents")
    referenced_versions = sorted(set(AGENTS_VERSION_PATTERN.findall(content)))
    for referenced in referenced_versions:
        if referenced != version:
            conflicts.append(
                f"AGENTS.md содержит ссылку на другой релиз .agents/sdd-template-{referenced}"
            )
    return conflicts


def looks_like_legacy_framework_agents(content: str) -> bool:
    """Распознать старые инструкции Framework без управляемых маркеров."""
    if AGENTS_MANAGED_BEGIN in content or AGENTS_MANAGED_END in content:
        return False
    normalized = content.lower()
    signatures = sum(signature.lower() in normalized for signature in LEGACY_AGENTS_SIGNATURES)
    return signatures >= 4


def is_legacy_framework_only(content: str) -> bool:
    """Разрешить замену только явно framework-only файла."""
    return (
        content.lstrip().startswith("# Rules and Constraints for Codex (H0)")
        and looks_like_legacy_framework_agents(content)
    )


def agents_path_references(content: str, version: str) -> list[dict[str, object]]:
    """Классифицировать Framework-ссылки с учётом managed-границ документа."""
    begin = content.find(AGENTS_MANAGED_BEGIN)
    end = content.find(AGENTS_MANAGED_END, begin + len(AGENTS_MANAGED_BEGIN)) if begin >= 0 else -1
    references: list[dict[str, object]] = []
    for match in _framework_path_matches(content):
        start = _match_position(match, "start")
        path = str(match["path"])
        in_managed = begin >= 0 and end >= 0 and begin <= start < end + len(AGENTS_MANAGED_END)
        if match["kind"] == "versioned":
            referenced_version = str(match["version"])
            classification = "valid" if referenced_version == version else "stale"
            replacement = None if classification == "valid" else _rewrite_framework_paths(path, version)
            reason = (
                "Ссылка указывает на текущий Framework root."
                if classification == "valid"
                else "Ссылка указывает на другой release Framework."
            )
        elif in_managed or is_legacy_framework_only(content):
            classification = "stale"
            replacement = _rewrite_framework_paths(path, version)
            reason = "Legacy-ссылка находится в части документа, принадлежащей Framework."
        else:
            classification = "ambiguous"
            replacement = None
            reason = "Нельзя доказать, что ссылка принадлежит Framework, а не пользователю."
        references.append(
            {
                "path": path,
                "classification": classification,
                "replacement": replacement,
                "location": "managed" if in_managed else "outside-managed",
                "reason": reason,
            }
        )
    return references


def inspect_agents_instructions(target_root: Path, source_root: Path, version: str) -> dict[str, object]:
    """Проверить AGENTS.md до записи и сформировать объяснение расхождений."""
    expected_block = agents_managed_block(source_root)
    destination = build_release.ensure_path_without_symlinks(
        target_root, target_root / "AGENTS.md", "путь AGENTS.md"
    )
    if not destination.exists():
        return {
            "status": "absent",
            "path": "AGENTS.md",
            "source": "AGENTS.md",
            "conflicts": [],
            "differences": [],
            "can_replace_legacy": False,
            "can_replace_managed": False,
        }
    if not destination.is_file():
        raise build_release.BuildError(f"AGENTS.md существует, но не является файлом: {destination}")
    try:
        content = _read_text(destination)
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно прочитать AGENTS.md: {error}") from error

    conflicts = detect_agents_conflicts(content, version)
    path_references = agents_path_references(content, version)
    path_differences = [
        reference for reference in path_references
        if reference.get("classification") == "stale" and isinstance(reference.get("replacement"), str)
    ]
    ambiguous_paths = [
        reference for reference in path_references
        if reference.get("classification") == "ambiguous"
    ]
    for reference in path_references:
        if reference.get("classification") == "ambiguous":
            conflicts.append(
                f"AGENTS.md содержит неоднозначную Framework-ссылку: {reference.get('path')}"
            )
        elif reference.get("classification") == "stale" and reference.get("location") == "outside-managed":
            conflicts.append(
                f"AGENTS.md содержит устаревшую Framework-ссылку вне managed-раздела: {reference.get('path')}"
            )
    differences: list[dict[str, object]] = []
    can_replace_legacy = False
    can_replace_managed = False
    begin_positions = [match.start() for match in re.finditer(re.escape(AGENTS_MANAGED_BEGIN), content)]
    end_positions = [match.start() for match in re.finditer(re.escape(AGENTS_MANAGED_END), content)]
    if len(begin_positions) > 1 or len(end_positions) > 1:
        conflicts.append("AGENTS.md содержит несколько управляемых разделов SDD Framework")
        differences.append({
            "code": "multiple_managed_sections",
            "message": "Найдено несколько управляемых разделов; автоматическое объединение запрещено.",
            "actions": ["keep"],
        })
    elif len(begin_positions) != len(end_positions):
        conflicts.append("AGENTS.md содержит неполные маркеры управляемого раздела SDD Framework")
        differences.append({
            "code": "incomplete_managed_section",
            "message": "Найдена только часть маркеров управляемого раздела.",
            "actions": ["keep"],
        })
    elif begin_positions:
        begin = begin_positions[0]
        end = end_positions[0]
        if end < begin:
            conflicts.append("маркеры управляемого раздела SDD Framework расположены в неверном порядке")
            differences.append({
                "code": "invalid_managed_section_order",
                "message": "Начальный и конечный маркеры расположены в неверном порядке.",
                "actions": ["keep"],
            })
        else:
            current_block = content[begin : end + len(AGENTS_MANAGED_END)]
            if current_block != expected_block.rstrip("\n"):
                conflicts.append("управляемый раздел AGENTS.md отличается от текущих инструкций Framework")
                differences.append({
                    "code": "managed_section_differs",
                    "message": "Содержимое между маркерами отличается; внешний текст будет сохранён.",
                    "actions": ["replace-managed", "keep"],
                })
                can_replace_managed = True
            prefix = content[:begin]
            suffix = content[end + len(AGENTS_MANAGED_END) :]
            legacy_prefix = is_legacy_framework_only(prefix)
            legacy_suffix = is_legacy_framework_only(suffix)
            if legacy_prefix or legacy_suffix:
                conflict_message = (
                    "AGENTS.md содержит старые полные инструкции Framework вне managed-раздела; "
                    "их сохранение создаёт дублирование."
                )
                conflicts.append(conflict_message)
                differences.append({
                    "code": "legacy_framework_duplicate",
                    "message": conflict_message,
                    "actions": ["replace-legacy", "keep"],
                })
                can_replace_legacy = True
    elif looks_like_legacy_framework_agents(content):
        if is_legacy_framework_only(content):
            conflict_message = (
                "AGENTS.md содержит старые полные инструкции Framework без маркеров; "
                "добавление нового блока создаст дублирование."
            )
            can_replace_legacy = True
            actions = ["replace-legacy", "keep"]
            code = "legacy_framework_only"
        else:
            conflict_message = (
                "AGENTS.md содержит старые инструкции Framework без маркеров вместе с пользовательским текстом; "
                "границы старого блока нельзя определить безопасно."
            )
            actions = ["keep"]
            code = "legacy_framework_with_user_text"
        conflicts.append(conflict_message)
        differences.append({"code": code, "message": conflict_message, "actions": actions})

    return {
        "status": "conflict" if conflicts else "clear",
        "path": "AGENTS.md",
        "source": "AGENTS.md",
        "conflicts": conflicts,
        "differences": differences,
        "can_replace_legacy": can_replace_legacy,
        "can_replace_managed": can_replace_managed,
        "path_references": path_references,
        "path_differences": path_differences,
        "can_migrate": bool(path_differences) and not ambiguous_paths,
        "legacy_outside_managed": (
            bool(begin_positions)
            and (
                is_legacy_framework_only(content[:begin_positions[0]])
                or is_legacy_framework_only(content[end_positions[0] + len(AGENTS_MANAGED_END) :])
                if end_positions
                else False
            )
        ),
    }


def ensure_agents_instructions(
    target_root: Path,
    source_root: Path,
    version: str,
    agents_action: str = "ask",
) -> dict[str, object]:
    """Добавить управляемый раздел только после разрешения расхождений."""
    review = inspect_agents_instructions(target_root, source_root, version)
    destination = build_release.ensure_path_without_symlinks(
        target_root, target_root / "AGENTS.md", "путь AGENTS.md"
    )
    conflicts = review.get("conflicts")
    if not isinstance(conflicts, list):
        conflicts = []
    if conflicts:
        if agents_action == "ask":
            return review
        if agents_action == "keep":
            return {**review, "status": "kept"}
        if agents_action == "migrate":
            if review.get("can_migrate") is not True:
                return {**review, "status": "awaiting_user_confirmation"}
            agents_action = "replace-managed" if AGENTS_MANAGED_BEGIN in _read_text(destination) else "replace-legacy"
        can_replace = (
            agents_action == "replace-legacy" and review.get("can_replace_legacy") is True
        ) or (
            agents_action == "replace-managed" and review.get("can_replace_managed") is True
        )
        if not can_replace:
            raise build_release.BuildError(
                "Выбранное действие AGENTS.md не соответствует обнаруженному расхождению. "
                "Повторите установку с корректным --agents-action."
            )
        expected_block = agents_managed_block(source_root)
        try:
            if agents_action == "replace-legacy":
                content = _read_text(destination)
                begin_positions = [match.start() for match in re.finditer(re.escape(AGENTS_MANAGED_BEGIN), content)]
                end_positions = [match.start() for match in re.finditer(re.escape(AGENTS_MANAGED_END), content)]
                if review.get("legacy_outside_managed") is True and begin_positions and end_positions:
                    begin = begin_positions[0]
                    end = end_positions[0]
                    prefix = content[:begin]
                    suffix = content[end + len(AGENTS_MANAGED_END) :]
                    if is_legacy_framework_only(prefix):
                        prefix = ""
                    if is_legacy_framework_only(suffix):
                        suffix = ""
                    destination = build_release.ensure_path_without_symlinks(
                        target_root, destination, "путь AGENTS.md"
                    )
                    _write_text(destination, prefix + expected_block.rstrip("\n") + suffix, expected=content)
                else:
                    destination = build_release.ensure_path_without_symlinks(
                        target_root, destination, "путь AGENTS.md"
                    )
                    _write_text(destination, expected_block, expected=content)
            else:
                content = _read_text(destination)
                begin = content.index(AGENTS_MANAGED_BEGIN)
                end = content.index(AGENTS_MANAGED_END, begin)
                new_content = content[:begin] + expected_block.rstrip("\n") + content[end + len(AGENTS_MANAGED_END) :]
                destination = build_release.ensure_path_without_symlinks(
                    target_root, destination, "путь AGENTS.md"
                )
                _write_text(destination, new_content, expected=content)
        except (OSError, ValueError) as error:
            raise build_release.BuildError(f"Невозможно разрешить расхождение AGENTS.md: {error}") from error
        return {**review, "status": "replaced"}

    if review.get("status") == "absent":
        try:
            destination = build_release.ensure_path_without_symlinks(
                target_root, destination, "путь AGENTS.md"
            )
            _write_text(destination, agents_managed_block(source_root), create_only=True)
        except OSError as error:
            raise build_release.BuildError(f"Невозможно создать AGENTS.md: {error}") from error
        return {**review, "status": "created"}

    try:
        content = _read_text(destination)
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно перечитать AGENTS.md: {error}") from error
    if AGENTS_MANAGED_BEGIN not in content:
        separator = "" if not content or content.endswith(("\n", "\r")) else "\n"
        try:
            destination = build_release.ensure_path_without_symlinks(
                target_root, destination, "путь AGENTS.md"
            )
            _write_text(
                destination, content + separator + "\n" + agents_managed_block(source_root), expected=content
            )
        except OSError as error:
            raise build_release.BuildError(f"Невозможно дополнить AGENTS.md: {error}") from error
        return {**review, "status": "updated"}
    return {**review, "status": "unchanged"}


def ensure_project_gitignore(target_root: Path, source_root: Path) -> str:
    project_templates = source_root / ".tools" / "sdd-template-release" / "templates" / "project-root"
    source = project_templates / ".gitignore"
    destination = build_release.ensure_path_without_symlinks(
        target_root, target_root / ".gitignore", "путь .gitignore"
    )
    if not destination.exists():
        if not source.is_file():
            raise build_release.BuildError(f"В чистом источнике отсутствует шаблон .gitignore: {source}")
        build_release.ensure_path_without_symlinks(source_root, source, "шаблон .gitignore")
        destination = build_release.ensure_path_without_symlinks(
            target_root, destination, "путь .gitignore"
        )
        fs_boundary.copy_file(source, destination, source_root=source_root)
        return "created"

    try:
        content = _read_text(destination)
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно прочитать существующий .gitignore: {error}") from error
    existing_rules = {line.strip() for line in content.splitlines()}
    missing_rules = [rule for rule in GITIGNORE_RULES if rule not in existing_rules]
    if not missing_rules:
        return "unchanged"
    separator = "" if not content or content.endswith(("\n", "\r")) else "\n"
    managed_block = (
        f"{separator}\n# SDD Framework: managed ignore entries\n"
        + "\n".join(missing_rules)
        + "\n"
    )
    try:
        destination = build_release.ensure_path_without_symlinks(
            target_root, destination, "путь .gitignore"
        )
        _write_text(destination, content + managed_block, expected=content)
    except OSError as error:
        raise build_release.BuildError(f"Невозможно дополнить существующий .gitignore: {error}") from error
    return "updated"


def consumer_project_structure(version: str) -> dict[str, object]:
    """Сформировать структуру проекта-потребителя, а не мета-репозитория."""
    framework_root = f".agents/sdd-template-{version}"
    return {
        "version": "1.0",
        "description": "Project structure for a consumer repository using SDD Framework.",
        "framework": {"package_id": "sdd-template", "release_dir": framework_root},
        "folders": [
            {"name": ".agents", "path": ".agents", "description": "Installed agent packages.", "required": True},
            {"name": ".tasks", "path": ".tasks", "description": "Project tasks and PDD registry.", "required": True},
            {"name": ".issues", "path": ".issues", "description": "Project issues and incidents.", "required": False},
            {"name": ".source", "path": ".source", "description": "Project source materials.", "required": False},
            {"name": "docs", "path": "docs", "description": "Project documentation.", "required": False},
        ],
    }


def normalized_json(path: Path) -> object | None:
    try:
        return json.loads(_read_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


FRAMEWORK_STRUCTURE_PATHS = {
    ("framework_root",),
    ("framework", "release_dir"),
    ("framework", "tools_registry"),
    ("framework", "chatlog_dir"),
    ("tools", "registry_path"),
    ("tools", "preferred_invocation"),
    ("templates", "task_template"),
    ("templates", "pdd_manifest"),
}


def _json_pointer_part(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    return str(value).replace("~", "~0").replace("/", "~1")


def _iter_json_strings(value: object, path: tuple[object, ...] = ()) -> list[tuple[tuple[object, ...], str]]:
    if isinstance(value, dict):
        result: list[tuple[tuple[object, ...], str]] = []
        for key, nested in value.items():
            result.extend(_iter_json_strings(nested, path + (key,)))
        return result
    if isinstance(value, list):
        result = []
        for index, nested in enumerate(value):
            result.extend(_iter_json_strings(nested, path + (index,)))
        return result
    if isinstance(value, str):
        return [(path, value)]
    return []


def _is_framework_structure_field(path: tuple[object, ...], value: str, data: object) -> bool:
    if path in FRAMEWORK_STRUCTURE_PATHS:
        return True
    if len(path) == 3 and path[0] == "folders" and isinstance(path[1], int) and path[2] == "path":
        if not isinstance(data, dict) or not isinstance(data.get("folders"), list):
            return False
        folders = data["folders"]
        if path[1] >= len(folders) or not isinstance(folders[path[1]], dict):
            return False
        if folders[path[1]].get("name") != "SDD Framework":
            return False
        normalized = value.replace("\\", "/")
        return normalized == ".agents" or normalized.startswith(".agents/") or normalized in FRAMEWORK_ROOTS or any(
            normalized.startswith(root + "/") for root in FRAMEWORK_ROOTS
        )
    return False


def _is_external_reference(value: str) -> bool:
    normalized = value.strip()
    return bool(
        re.match(r"(?i)^(?:https?|file)://", normalized)
        or re.match(r"^[A-Za-z]:[/\\]", normalized)
        or normalized.startswith(("/", "\\\\"))
    )


def project_structure_references(
    data: object,
    target_root: Path,
    version: str,
) -> list[dict[str, object]]:
    """Собрать Framework-ссылки в project structure до изменения файла."""
    references: list[dict[str, object]] = []
    for path, value in _iter_json_strings(data):
        if path == ("framework", "release_dir") and not AGENTS_VERSION_PATTERN.fullmatch(value):
            references.append(
                {
                    "json_path": "/framework/release_dir",
                    "value": value,
                    "classification": "ambiguous",
                    "replacement": None,
                    "reason": "Действующий каталог Framework должен иметь вид .agents/sdd-template-X.Y.Z.",
                }
            )
            continue
        matches = _framework_path_matches(value)
        if not matches and _is_framework_structure_field(path, value, data) and _is_external_reference(value):
            references.append(
                {
                    "json_path": "/" + "/".join(_json_pointer_part(item) for item in path),
                    "value": value,
                    "classification": "external",
                    "reason": "Внешний абсолютный путь не является локальной Framework-ссылкой.",
                }
            )
            continue
        for match in matches:
            reference_path = str(match["path"])
            classification = "valid"
            replacement: str | None = None
            if match["kind"] == "versioned":
                referenced_version = str(match["version"])
                if referenced_version != version:
                    if _is_framework_structure_field(path, value, data):
                        classification = "stale"
                        replacement = _rewrite_framework_paths(reference_path, version)
                    else:
                        classification = "ambiguous"
                elif not (target_root / Path(reference_path)).exists():
                    classification = "missing"
            elif _is_framework_structure_field(path, value, data):
                classification = "stale"
                replacement = _rewrite_framework_paths(reference_path, version)
            else:
                classification = "ambiguous"
            references.append(
                {
                    "json_path": "/" + "/".join(_json_pointer_part(item) for item in path),
                    "value": reference_path,
                    "classification": classification,
                    "replacement": replacement,
                    "reason": (
                        "Ссылка использует старый Framework root."
                        if classification == "stale"
                        else "Целевой путь текущего Framework отсутствует."
                        if classification == "missing"
                        else "Невозможно доказать принадлежность ссылки Framework."
                        if classification == "ambiguous"
                        else "Ссылка указывает на текущий Framework root."
                    ),
                }
            )
    return references


def _json_value_at(data: object, path: tuple[object, ...]) -> object:
    current = data
    for part in path:
        if isinstance(part, int) and isinstance(current, list):
            current = current[part]
        elif isinstance(part, str) and isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _set_json_value(data: object, path: tuple[object, ...], value: object) -> None:
    if not path:
        raise KeyError("Нельзя заменить корневой JSON-объект этим способом.")
    parent = _json_value_at(data, path[:-1])
    last = path[-1]
    if isinstance(last, int) and isinstance(parent, list):
        parent[last] = value
    elif isinstance(last, str) and isinstance(parent, dict):
        parent[last] = value
    else:
        raise KeyError(path)


def migrate_project_structure(
    data: object,
    version: str,
) -> tuple[object, list[dict[str, object]]]:
    """Создать копию структуры с точечными Framework-owned заменами."""
    migrated = json.loads(json.dumps(data, ensure_ascii=False))
    changes: list[dict[str, object]] = []
    framework_value = data.get("framework") if isinstance(data, dict) else None
    flat_root = data.get("framework_root") if isinstance(data, dict) else None
    canonicalize = (
        isinstance(framework_value, dict)
        and (
            framework_value.get("package_id") == "sdd-template"
            or (
                "package_id" not in framework_value
                and isinstance(framework_value.get("release_dir"), str)
                and AGENTS_VERSION_PATTERN.fullmatch(framework_value["release_dir"]) is not None
            )
        )
    ) or (isinstance(flat_root, str) and AGENTS_VERSION_PATTERN.fullmatch(flat_root) is not None)
    redundant_paths = {
        ("framework_root",), ("framework", "tools_registry"), ("framework", "chatlog_dir"),
        ("tools", "registry_path"), ("tools", "preferred_invocation"),
        ("templates", "task_template"), ("templates", "pdd_manifest"),
    }
    for path, value in _iter_json_strings(data):
        if not _is_framework_structure_field(path, value, data):
            continue
        if canonicalize and path in redundant_paths:
            continue
        if canonicalize and len(path) == 3 and path[0] == "folders" and path[2] == "path":
            continue
        rewritten = _rewrite_framework_paths(value, version)
        if rewritten == value:
            continue
        _set_json_value(migrated, path, rewritten)
        changes.append(
            {
                "json_path": "/" + "/".join(_json_pointer_part(item) for item in path),
                "old": value,
                "new": rewritten,
                "classification": "framework-owned",
            }
        )
    if not isinstance(migrated, dict):
        return migrated, changes
    framework = migrated.get("framework")
    if framework is None:
        old_root = migrated.get("framework_root")
        if isinstance(old_root, str) and AGENTS_VERSION_PATTERN.fullmatch(old_root):
            framework = {"package_id": "sdd-template", "release_dir": _framework_root(version)}
            migrated["framework"] = framework
            changes.append({"json_path": "/framework", "old": None, "new": framework, "classification": "framework-owned"})
    if not isinstance(framework, dict):
        return migrated, changes
    if "package_id" not in framework and isinstance(framework.get("release_dir"), str):
        if AGENTS_VERSION_PATTERN.fullmatch(str(framework["release_dir"])):
            framework["package_id"] = "sdd-template"
            changes.append({"json_path": "/framework/package_id", "old": None, "new": "sdd-template", "classification": "framework-owned"})
    if framework.get("package_id") != "sdd-template":
        return migrated, changes
    if "release_dir" not in framework:
        framework["release_dir"] = _framework_root(version)
        changes.append({"json_path": "/framework/release_dir", "old": None, "new": _framework_root(version), "classification": "framework-owned"})
    for parent_key, field_key in (
        (None, "framework_root"),
        ("framework", "tools_registry"),
        ("framework", "chatlog_dir"),
        ("tools", "registry_path"),
        ("tools", "preferred_invocation"),
        ("templates", "task_template"),
        ("templates", "pdd_manifest"),
    ):
        parent = migrated if parent_key is None else migrated.get(parent_key)
        if not isinstance(parent, dict):
            continue
        value = parent.get(field_key)
        if not isinstance(value, str) or not _framework_path_matches(value):
            continue
        del parent[field_key]
        pointer = f"/{parent_key}/{field_key}" if parent_key else f"/{field_key}"
        changes.append({"json_path": pointer, "old": value, "new": None, "classification": "framework-owned"})
    folders = migrated.get("folders")
    if isinstance(folders, list):
        for index, folder in enumerate(folders):
            if not isinstance(folder, dict) or folder.get("name") != "SDD Framework":
                continue
            value = folder.get("path")
            if not isinstance(value, str) or not _framework_path_matches(value):
                continue
            folder["name"] = ".agents"
            folder["path"] = ".agents"
            folder["description"] = "Installed agent packages."
            changes.append({"json_path": f"/folders/{index}", "old": value, "new": ".agents", "classification": "framework-owned"})
    return migrated, changes


def inspect_project_structure(target_root: Path, source_root: Path, version: str) -> dict[str, object]:
    """Проверить структуру потребителя и подготовить точечную миграцию путей."""
    destination = build_release.ensure_path_without_symlinks(
        target_root, target_root / ".project-structure.json", "путь .project-structure.json"
    )
    if not destination.exists():
        return {"status": "absent", "path": ".project-structure.json", "conflicts": [], "differences": [], "can_replace": False}
    if not destination.is_file():
        raise build_release.BuildError(f".project-structure.json существует, но не является файлом: {destination}")
    try:
        current_raw = _read_text(destination)
        current = json.loads(current_raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        current_raw = None
        current = None
    if current_raw is None or not isinstance(current, dict):
        return {
            "status": "conflict",
            "path": ".project-structure.json",
            "conflicts": ["корневой .project-structure.json не является корректным JSON-объектом"],
            "differences": [{"code": "invalid_json", "message": "Файл нельзя безопасно сравнить.", "actions": ["keep"]}],
            "can_replace": False,
        }
    references = project_structure_references(current, target_root, version)
    unresolved = [
        reference for reference in references
        if reference.get("classification") in {"stale", "missing", "ambiguous"}
    ]
    _, migration_changes = migrate_project_structure(current, version)
    template = source_root / ".tools" / "sdd-template-release" / "templates" / "project-structure.json"
    template_value = normalized_json(template) if template.is_file() else None
    is_meta_template = template_value is not None and current == template_value
    if not is_meta_template and not unresolved and not migration_changes:
        return {
            "status": "clear",
            "path": ".project-structure.json",
            "conflicts": [],
            "differences": [],
            "references": references,
            "migration_changes": [],
            "fingerprint": hashlib.sha256(current_raw.encode("utf-8")).hexdigest(),
            "can_replace": False,
            "can_migrate": False,
        }
    if is_meta_template:
        message = (
            "корневой .project-structure.json является структурой мета-репозитория; "
            "для проекта-потребителя нужны пути через FRAMEWORK_ROOT"
        )
        code = "meta_project_structure"
    else:
        message = "корневой .project-structure.json содержит устаревшие или дублирующие Framework-пути"
        code = "framework_path_references"
    differences: list[dict[str, object]] = [
        {
            "code": code,
            "message": message,
            "references": references,
            "actions": ["migrate", "replace", "keep"] if is_meta_template else ["migrate", "keep"],
        }
    ]
    can_migrate = bool(migration_changes) and not any(
        reference.get("classification") == "ambiguous" for reference in unresolved
    )
    return {
        "status": "conflict",
        "path": ".project-structure.json",
        "conflicts": [message],
        "differences": differences,
        "references": references,
        "migration_changes": migration_changes,
        "fingerprint": hashlib.sha256(current_raw.encode("utf-8")).hexdigest(),
        "can_migrate": can_migrate,
        "can_replace": is_meta_template,
    }


def ensure_project_structure(
    target_root: Path,
    source_root: Path,
    version: str,
    project_structure_action: str = "ask",
) -> dict[str, object]:
    destination = build_release.ensure_path_without_symlinks(
        target_root, target_root / ".project-structure.json", "путь .project-structure.json"
    )
    review = inspect_project_structure(target_root, source_root, version)
    reviewed_raw: str | None = None
    conflicts = review.get("conflicts")
    if not isinstance(conflicts, list):
        conflicts = []
    if conflicts:
        if project_structure_action == "ask":
            return review
        if project_structure_action == "keep":
            return {**review, "status": "kept"}
        reviewed_fingerprint = review.get("fingerprint")
        if isinstance(reviewed_fingerprint, str):
            reviewed_raw = _read_text(destination)
            if hashlib.sha256(reviewed_raw.encode("utf-8")).hexdigest() != reviewed_fingerprint:
                raise build_release.BuildError(".project-structure.json изменился после проверки; повторите действие.")
        if project_structure_action == "migrate":
            if review.get("can_migrate") is not True:
                return {**review, "status": "awaiting_user_confirmation"}
            current = json.loads(reviewed_raw) if reviewed_raw is not None else None
            if not isinstance(current, dict):
                return {**review, "status": "awaiting_user_confirmation"}
            migrated, changes = migrate_project_structure(
                current,
                version,
            )
            if not isinstance(migrated, dict):
                raise build_release.BuildError("Миграция .project-structure.json не вернула JSON-объект.")
            try:
                destination = build_release.ensure_path_without_symlinks(
                    target_root, destination, "путь .project-structure.json"
                )
                _write_text(
                    destination, json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
                    expected=reviewed_raw,
                )
            except OSError as error:
                raise build_release.BuildError(f"Невозможно записать мигрированный .project-structure.json: {error}") from error
            return {**review, "status": "migrated", "migration": {"changes": changes}}
        if project_structure_action != "replace" or review.get("can_replace") is not True:
            raise build_release.BuildError(
                "Корневой .project-structure.json нельзя заменить автоматически: "
                "разрешена только безопасная замена известного шаблона мета-репозитория."
            )
    if review.get("status") == "absent":
        expected_raw = None
        create_only = True
    elif project_structure_action == "replace":
        if review.get("can_replace") is not True or reviewed_raw is None:
            raise build_release.BuildError(
                "Замена .project-structure.json разрешена только для проверенного шаблона мета-репозитория."
            )
        expected_raw = reviewed_raw
        create_only = False
    else:
        return {**review, "status": "preserved"}

    if review.get("status") == "absent" or project_structure_action == "replace":
        try:
            destination = build_release.ensure_path_without_symlinks(
                target_root, destination, "путь .project-structure.json"
            )
            _write_text(
                destination, json.dumps(consumer_project_structure(version), ensure_ascii=False, indent=2) + "\n",
                expected=expected_raw,
                create_only=create_only,
            )
        except OSError as error:
            raise build_release.BuildError(f"Невозможно записать .project-structure.json: {error}") from error
        return {**review, "status": "created" if review.get("status") == "absent" else "replaced"}
    return {**review, "status": "preserved"}


def initialize_project_root(
    target_root: Path,
    package_dir: Path,
    source_root: Path,
    version: str,
    project_structure_action: str = "ask",
) -> dict[str, object]:
    scaffold: dict[str, str] = {}
    result: dict[str, object] = {
        "gitignore": ensure_project_gitignore(target_root, source_root),
        "scaffold": scaffold,
        "project_structure": ensure_project_structure(target_root, source_root, version, project_structure_action),
    }
    project_templates = source_root / ".tools" / "sdd-template-release" / "templates" / "project-root"
    for relative in PROJECT_ROOT_TEMPLATES:
        source = project_templates / relative
        destination = build_release.ensure_path_without_symlinks(
            target_root, target_root / relative, f"путь {relative.as_posix()}"
        )
        if destination.exists():
            if not destination.is_file():
                raise build_release.BuildError(f"Ожидался файл, но найден другой объект: {destination}")
            scaffold[relative.as_posix()] = "preserved"
            continue
        if not source.is_file():
            raise build_release.BuildError(f"В чистом источнике отсутствует шаблон корня проекта: {source}")
        build_release.ensure_path_without_symlinks(source_root, source, "шаблон корня проекта")
        destination = build_release.ensure_path_without_symlinks(
            target_root, destination, f"путь {relative.as_posix()}"
        )
        fs_boundary.copy_file(source, destination, source_root=source_root)
        scaffold[relative.as_posix()] = "created"

    docs_dir = target_root / "docs"
    requirements_dir = target_root / "docs" / "requirements"
    build_release.ensure_path_without_symlinks(target_root, docs_dir, "каталог docs")
    build_release.ensure_path_without_symlinks(target_root, requirements_dir, "каталог docs/requirements")
    if requirements_dir.exists():
        if not requirements_dir.is_dir():
            raise build_release.BuildError(f"Путь docs/requirements существует, но не является каталогом: {requirements_dir}")
        result["docs_requirements"] = "preserved"
    else:
        if docs_dir.exists() and not docs_dir.is_dir():
            raise build_release.BuildError(f"Путь docs существует, но не является каталогом: {docs_dir}")
        fs_boundary.mkdirs(requirements_dir)
        gitkeep = build_release.ensure_path_without_symlinks(
            target_root, requirements_dir / ".gitkeep", "путь docs/requirements/.gitkeep"
        )
        _write_text(gitkeep, "", create_only=True)
        result["docs_requirements"] = "created"

    files: dict[str, Path | None] = {
        ".editorconfig": None,
        ".gitattributes": None,
        "README.md": None,
    }
    defaults = {
        ".editorconfig": "root = true\n\n[*]\ncharset = utf-8\nend_of_line = lf\ninsert_final_newline = true\n",
        ".gitattributes": "* text=auto eol=lf\n",
        "README.md": "",
    }
    for name, default_source in files.items():
        destination = build_release.ensure_path_without_symlinks(
            target_root, target_root / name, f"путь {name}"
        )
        if destination.exists():
            continue
        if default_source is not None:
            build_release.ensure_path_without_symlinks(source_root, default_source, f"шаблон {name}")
            destination = build_release.ensure_path_without_symlinks(
                target_root, destination, f"путь {name}"
            )
            fs_boundary.copy_file(default_source, destination, source_root=source_root)
        else:
            destination = build_release.ensure_path_without_symlinks(
                target_root, destination, f"путь {name}"
            )
            _write_text(destination, defaults[name], create_only=True)
    return result


INVENTORY_SCHEMA_VERSION = "1"


def _safe_manifest_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with fs_boundary.open_regular(path) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_entries(root: Path, skip_directories: set[str] | None = None) -> tuple[list[dict[str, object]], list[str]]:
    entries: list[dict[str, object]] = []
    skipped: list[str] = []
    skip_directories = skip_directories or set()

    def visit(directory: Path, relative_directory: str = "") -> None:
        guard_stack = contextlib.ExitStack()
        try:
            checked_directory, descriptor = guard_stack.enter_context(fs_boundary.locked_directory(directory))
            with os.scandir(checked_directory if os.name == "nt" else descriptor) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            guard_stack.close()
            raise build_release.BuildError(f"Невозможно прочитать каталог inventory: {directory}: {error}") from error
        try:
            for child in children:
                relative = f"{relative_directory}/{child.name}".strip("/")
                try:
                    stat_result = (
                        child.stat(follow_symlinks=False) if os.name == "nt"
                        else os.stat(child.name, dir_fd=descriptor, follow_symlinks=False)
                    )
                except OSError as error:
                    raise build_release.BuildError(f"Невозможно получить метаданные inventory: {child.path}: {error}") from error
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                is_symlink = stat.S_ISLNK(stat_result.st_mode)
                is_reparse = bool(getattr(stat_result, "st_file_attributes", 0) & reparse_flag)
                if is_symlink or is_reparse:
                    try:
                        link_target = (
                            os.readlink(child.path) if os.name == "nt"
                            else os.readlink(child.name, dir_fd=descriptor)
                        )
                    except OSError:
                        link_target = None
                    entries.append(
                        {
                            "path": relative,
                            "type": "symlink" if is_symlink else "reparse",
                            "size": stat_result.st_size,
                            "target": link_target,
                        }
                    )
                    continue
                if stat.S_ISDIR(stat_result.st_mode):
                    entries.append({"path": relative, "type": "directory", "size": 0})
                    if child.name in skip_directories:
                        skipped.append(relative)
                        continue
                    visit(directory / child.name, relative)
                    continue
                if stat.S_ISREG(stat_result.st_mode):
                    file_path = directory / child.name
                    entries.append(
                        {
                            "path": relative,
                            "type": "file",
                            "size": stat_result.st_size,
                            "sha256": _sha256(file_path),
                        }
                    )
        finally:
            guard_stack.close()

    visit(root)
    return entries, skipped


def _inventory_fingerprint(entries: list[dict[str, object]], errors: list[str]) -> str:
    payload = json.dumps(
        {"entries": entries, "errors": errors},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _size_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _finalize_inventory(
    entries: list[dict[str, object]],
    errors: list[str],
    scope: str,
    skipped: list[str] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    entries = sorted(entries, key=lambda item: str(item.get("path", "")))
    nonstandard = [
        item for item in entries
        if item.get("classification") == "user_data"
    ]
    top_level = sorted({str(item["path"]).split("/", 1)[0] for item in nonstandard})
    summary = {
        "entries": len(entries),
        "files": sum(item.get("type") == "file" for item in entries),
        "directories": sum(item.get("type") == "directory" for item in entries),
        "symlinks": sum(item.get("type") == "symlink" for item in entries),
        "bytes": sum(_size_value(item.get("size")) for item in entries if item.get("type") == "file"),
        "user_data_entries": len(nonstandard),
        "user_data_bytes": sum(
            _size_value(item.get("size")) for item in nonstandard if item.get("type") == "file"
        ),
        "classifications": {
            classification: sum(item.get("classification") == classification for item in entries)
            for classification in ("framework", "generated", "user_data")
        },
        "statuses": {
            status: sum(item.get("status") == status for item in entries)
            for status in ("tracked", "modified", "untracked", "ignored", "generated", "unknown", "service")
        },
    }
    result: dict[str, object] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "scope": scope,
        "status": "complete" if not errors else "incomplete",
        "safe_to_delete": not errors and not nonstandard,
        "user_data_detected": bool(nonstandard),
        "deletion_blocked": bool(errors or nonstandard),
        "requires_confirmation": True,
        "fingerprint": _inventory_fingerprint(entries, errors),
        "entries": entries,
        "nonstandard_paths": [str(item["path"]) for item in nonstandard],
        "top_level_nonstandard": top_level,
        "summary": summary,
        "errors": errors,
        "skipped_service_paths": sorted(skipped or []),
    }
    if extra:
        result.update(extra)
    return result


def inventory_release(release_path: Path, expected_version: str | None = None) -> dict[str, object]:
    """Сравнить содержимое release с его release-manifest.json."""
    if not release_path.is_dir() or build_release.is_link_or_reparse_point(release_path):
        raise build_release.BuildError(f"Каталог release не найден или является ссылкой: {release_path}")
    errors: list[str] = []
    expected: dict[str, dict[str, object]] = {}
    manifest_path = release_path / "release-manifest.json"
    try:
        if build_release.is_link_or_reparse_point(manifest_path):
            raise ValueError("release-manifest.json является ссылкой или reparse point")
        manifest = json.loads(_read_text(manifest_path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"Невозможно прочитать release-manifest.json: {error}")
        manifest = {}
    if expected_version is not None:
        expected_release_dir = f".agents/{build_release.release_name(expected_version)}"
        if (
            not isinstance(manifest, dict)
            or manifest.get("package_id") != build_release.PACKAGE_ID
            or manifest.get("version") != expected_version
            or manifest.get("release_dir") != expected_release_dir
        ):
            errors.append("Идентичность release-manifest.json не совпадает с проверяемым релизом.")
    if isinstance(manifest, dict) and isinstance(manifest.get("files"), list):
        for record in manifest["files"]:
            if not isinstance(record, dict):
                errors.append("В release-manifest.json обнаружена запись files не-объект.")
                continue
            relative = _safe_manifest_path(record.get("path"))
            if relative is None or relative in expected:
                errors.append("В release-manifest.json обнаружен некорректный или повторный путь files.")
                continue
            expected[relative] = record
    else:
        errors.append("В release-manifest.json отсутствует массив files.")
    expected["release-manifest.json"] = {"path": "release-manifest.json"}
    canonical_directories: set[str] = set()
    for relative in expected:
        path = Path(relative)
        canonical_directories.update(
            parent.as_posix() for parent in path.parents if parent.as_posix() != "."
        )
    entries, skipped = _collect_entries(release_path)
    actual_paths = {str(item["path"]): item for item in entries}
    for relative in expected:
        if relative not in actual_paths:
            errors.append(f"В release отсутствует канонический путь: {relative}")
    for item in entries:
        relative = str(item["path"])
        item["status"] = "tracked"
        if item.get("type") in {"symlink", "reparse"}:
            errors.append(f"В release обнаружена ссылка или reparse point: {relative}")
        if (
            relative == ".chatlog" and item.get("type") == "directory"
        ) or (
            relative == ".chatlog/session.md" and item.get("type") == "file"
        ):
            item["classification"] = "framework"
            item["status"] = "runtime"
            continue
        if item.get("type") == "directory":
            item["classification"] = "framework" if relative in canonical_directories else "user_data"
            if item["classification"] == "user_data":
                item["status"] = "unknown"
            continue
        record = expected.get(relative)
        if record is None:
            item["classification"] = "user_data"
            item["status"] = "unknown"
            continue
        if relative == "release-manifest.json":
            item["classification"] = "framework"
            item["status"] = "service"
            continue
        expected_size = record.get("size")
        expected_sha256 = record.get("sha256")
        if (
            item.get("type") != "file"
            or not isinstance(expected_size, int)
            or item.get("size") != expected_size
            or not isinstance(expected_sha256, str)
            or item.get("sha256") != expected_sha256
        ):
            item["classification"] = "user_data"
            item["status"] = "modified"
        else:
            item["classification"] = "framework"
    return _finalize_inventory(entries, errors, "installed_release", skipped)


def preserve_runtime_data(source_release: Path, target_release: Path) -> dict[str, object]:
    """Перенести только разрешённый журнал Framework, не перезаписывая существующий файл."""
    source = source_release / ".chatlog" / "session.md"
    if not os.path.lexists(source):
        return {"status": "absent", "path": source.name}
    build_release.ensure_path_without_symlinks(source_release, source, "журнал Framework")
    if not source.is_file() or build_release.is_link_or_reparse_point(source):
        raise build_release.BuildError("Файл журнала Framework не является обычным файлом.")
    data = fs_boundary.read_bytes(source)
    destination = target_release / ".chatlog" / "session.md"
    if os.path.lexists(destination):
        build_release.ensure_path_without_symlinks(target_release, destination, "целевой журнал Framework")
        if not destination.is_file() or fs_boundary.read_bytes(destination) != data:
            raise build_release.BuildError(
                "Журнал Framework уже существует и отличается; оба файла сохранены, автоматическая замена остановлена."
            )
        return {"status": "already_preserved", "path": destination.as_posix()}
    fs_boundary.mkdirs(destination.parent)
    fs_boundary.write_bytes(destination, data, create_only=True)
    return {"status": "preserved", "path": destination.as_posix(), "sha256": hashlib.sha256(data).hexdigest()}


EXTERNAL_FRAMEWORK_REFERENCE_PATTERN = re.compile(
    r"(?P<path>(?:https?://|file://|[A-Za-z]:[/\\]|\\\\)[^\s`'\"<>),;]*"
    r"(?:\.agents[/\\]sdd-template-|\.manifest|\.requirements|\.tools|\.approach|\.chatlog)"
    r"[^\s`'\"<>),;]*)",
    re.IGNORECASE,
)
MARKDOWN_FRAMEWORK_URL_PATTERN = re.compile(
    r"\]\((?P<path>(?:\.\.?/)*\.agents/(?:sdd-template-current|sdd-template-[0-9]+\.[0-9]+\.[0-9]+)(?:/[^)\s]*)?)\)"
)


def _post_install_files(target_root: Path) -> list[Path]:
    """Получить allowlist текстовых project-документов для post-install проверки."""
    files: dict[str, Path] = {}
    ignored_parts = {".git", ".agents", "tmp", "node_modules", "__pycache__"}
    for relative_root in POST_INSTALL_SCAN_ROOTS:
        candidate = target_root / relative_root
        if build_release.is_link_or_reparse_point(candidate):
            raise build_release.BuildError(f"Проверяемый путь является symlink или junction: {relative_root}")
        if candidate.is_file():
            if candidate.suffix.lower() in POST_INSTALL_TEXT_SUFFIXES or candidate.name in {"AGENTS.md", ".project-structure.json"}:
                files[candidate.as_posix()] = candidate
            continue
        if not candidate.is_dir():
            continue
        try:
            candidate_files = fs_boundary.list_files(candidate)
        except fs_boundary.BoundaryError as error:
            raise build_release.BuildError(f"Проверяемый путь содержит symlink или junction: {error}") from error
        for path in candidate_files:
            if path.suffix.lower() not in POST_INSTALL_TEXT_SUFFIXES:
                continue
            relative_parts = path.relative_to(target_root).parts
            if any(part in ignored_parts for part in relative_parts):
                continue
            files[path.as_posix()] = path
    return [files[key] for key in sorted(files)]


def _post_install_file_fingerprint(files: list[Path], target_root: Path) -> str:
    records: list[dict[str, object]] = []
    for path in files:
        try:
            data = fs_boundary.read_bytes(path)
        except OSError as error:
            raise build_release.BuildError(
                f"Невозможно вычислить fingerprint {path.relative_to(target_root).as_posix()}: {error}"
            ) from error
        records.append(
            {
                "path": path.relative_to(target_root).as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return _inventory_fingerprint(records, [])


def _reference_validation_cache_path(target_root: Path) -> Path:
    project_key = hashlib.sha256(
        os.path.normcase(os.path.abspath(target_root)).encode("utf-8")
    ).hexdigest()
    return Path(tempfile.gettempdir()) / "sdd-template-reference-cache" / f"{project_key}.json"


def _load_reference_validation_cache(
    cache_path: Path, version: str, framework_fingerprint: str, files_fingerprint: str
) -> dict[str, int] | None:
    try:
        cached = json.loads(fs_boundary.read_bytes(cache_path).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(cached, dict)
        or cached.get("schema_version") != 1
        or cached.get("status") != "pass"
        or cached.get("version") != version
        or cached.get("framework_fingerprint") != framework_fingerprint
        or cached.get("files_fingerprint") != files_fingerprint
    ):
        return None
    summary_value = cached.get("summary")
    summary_keys = ("valid", "historical", "project", "stale", "missing", "ambiguous", "external")
    if not isinstance(summary_value, dict):
        return None
    summary: dict[str, int] = {}
    for key in summary_keys:
        value = summary_value.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        summary[key] = value
    if any(summary[key] for key in ("historical", "project", "stale", "missing", "ambiguous")):
        return None
    return summary


def _store_reference_validation_cache(
    cache_path: Path,
    version: str,
    framework_fingerprint: str,
    files_fingerprint: str,
    summary: dict[str, int],
) -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "status": "pass",
            "version": version,
            "framework_fingerprint": framework_fingerprint,
            "files_fingerprint": files_fingerprint,
            "summary": summary,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fs_boundary.mkdirs(cache_path.parent)
    try:
        existing = fs_boundary.read_bytes(cache_path)
    except OSError:
        fs_boundary.write_bytes(cache_path, payload, create_only=True)
    else:
        fs_boundary.replace_if_same(cache_path, existing, payload)


def _post_install_reference_records(path: Path, target_root: Path, version: str) -> list[dict[str, object]]:
    try:
        content = _read_text(path)
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(
            f"Невозможно проверить ссылки в {path.relative_to(target_root).as_posix()}: {error}"
        ) from error
    references: list[dict[str, object]] = []
    relative_file = path.relative_to(target_root).as_posix()
    historical_file = (
        relative_file.startswith((".tasks/done/", ".issues/done/"))
        or relative_file in {"docs/CHANGELOG.md", "CHANGELOG.md"}
    )
    matches: list[tuple[int, int, str, str]] = []
    markdown_spans: list[tuple[int, int]] = []
    for markdown_match in MARKDOWN_FRAMEWORK_URL_PATTERN.finditer(content):
        start = markdown_match.start("path")
        end = markdown_match.end("path")
        markdown_spans.append((start, end))
        matches.append((start, end, markdown_match.group("path"), "markdown"))
    for framework_match in _framework_path_matches(content):
        start = _match_position(framework_match, "start")
        end = _match_position(framework_match, "end")
        if any(start < markdown_end and end > markdown_start for markdown_start, markdown_end in markdown_spans):
            continue
        matches.append(
            (
                start,
                end,
                str(framework_match["path"]),
                "local",
            )
        )
    for external_match in EXTERNAL_FRAMEWORK_REFERENCE_PATTERN.finditer(content):
        path_value = _clean_framework_path(external_match.group("path"))
        matches.append(
            (
                external_match.start("path"),
                external_match.start("path") + len(path_value),
                path_value,
                "external",
            )
        )
    for start, end, reference, source_kind in sorted(matches, key=lambda item: (item[0], item[1])):
        line = content.count("\n", 0, start) + 1
        line_start = content.rfind("\n", 0, start) + 1
        column = start - line_start + 1
        replacement: str | None = None
        if source_kind == "external":
            classification = "external"
            reason = "Внешняя ссылка не является локальной ошибкой Framework-путей."
        elif source_kind == "markdown":
            url_path = unquote(reference.split("#", 1)[0].split("?", 1)[0])
            resolved_target = Path(os.path.normpath(path.parent / Path(url_path)))
            alias_path = _framework_alias(target_root)
            try:
                if "sdd-template-current" in reference:
                    suffix = resolved_target.relative_to(alias_path)
                    target = target_root / Path(_framework_root(version)) / suffix
                    build_release.ensure_path_without_symlinks(target_root, target, "цель постоянной ссылки")
                    if os.path.lexists(alias_path):
                        _verify_active_alias(target_root, version, allow_other_version=True)
                    classification = "stale" if target.exists() else "missing"
                    if classification == "stale":
                        replacement_path = target
                        replacement = quote(
                            os.path.relpath(replacement_path, path.parent).replace("\\", "/"), safe="/"
                        )
                    reason = "Ссылка через прежний symlink/junction должна перейти на проверенный путь версии."
                else:
                    referenced_version_match = AGENTS_VERSION_PATTERN.search(reference)
                    if referenced_version_match is None:
                        raise ValueError("Versioned Markdown reference without version")
                    referenced_version = referenced_version_match.group(1)
                    old_root = target_root / Path(_framework_root(referenced_version))
                    suffix = resolved_target.relative_to(old_root)
                    build_release.ensure_path_without_symlinks(target_root, resolved_target, "Markdown-ссылка Framework")
                    target = target_root / Path(_framework_root(version)) / suffix
                    build_release.ensure_path_without_symlinks(target_root, target, "цель миграции Markdown-ссылки")
                    if historical_file:
                        classification = "historical" if resolved_target.exists() else "missing"
                        reason = "Архивная Markdown-ссылка сохраняет исходную версию Framework."
                    elif _alias_required(version):
                        classification = "stale" if resolved_target.exists() and target.exists() else "missing"
                        replacement_path = alias_path / suffix
                        replacement = quote(
                            os.path.relpath(replacement_path, path.parent).replace("\\", "/"), safe="/"
                        ) if classification == "stale" else None
                        reason = "Действующая Markdown-ссылка требует постоянного адреса Framework."
                    elif referenced_version != version:
                        classification = "stale" if target.exists() else "missing"
                        if classification == "stale":
                            replacement = quote(
                                os.path.relpath(target, path.parent).replace("\\", "/"), safe="/"
                            )
                        reason = "Markdown-ссылка указывает на другой release Framework."
                    else:
                        classification = "valid" if resolved_target.exists() else "missing"
                        reason = "Markdown-ссылка разрешается к текущему Framework."
            except (ValueError, OSError, build_release.BuildError):
                classification = "ambiguous"
                reason = "Markdown-ссылка выходит за разрешённый корень или проходит через непроверенный путь."
        elif reference.replace("\\", "/").startswith(".agents/sdd-template-"):
            referenced_version_match = AGENTS_VERSION_PATTERN.search(reference)
            referenced_version = referenced_version_match.group(1) if referenced_version_match else None
            if referenced_version != version:
                if historical_file:
                    classification = "historical"
                    reason = "Архивный документ сохраняет указание на исходную версию Framework."
                else:
                    classification = "stale"
                    replacement = _rewrite_framework_paths(reference, version)
                    reason = "Ссылка указывает на другой release Framework."
            else:
                target = target_root / Path(reference.replace("\\", "/"))
                classification = "stale" if _alias_required(version) and not historical_file and relative_file != ".project-structure.json" else (
                    "valid" if target.exists() else "missing"
                )
                if classification == "stale":
                    replacement = "FRAMEWORK_ROOT" + reference.replace("\\", "/")[len(_framework_root(version)):]
                reason = (
                    "Ссылка указывает на текущий Framework root."
                    if classification == "valid"
                    else "Целевой путь текущего Framework отсутствует."
                )
        else:
            relative_reference = Path(reference.replace("\\", "/"))
            project_target = target_root / relative_reference
            package_target = target_root / Path(_framework_root(version)) / relative_reference
            try:
                build_release.ensure_path_without_symlinks(target_root, project_target, "проектная ссылка")
                build_release.ensure_path_without_symlinks(target_root, package_target, "ссылка Framework")
                project_exists = project_target.exists()
                package_exists = package_target.exists()
            except build_release.BuildError:
                project_exists = package_exists = False
            if package_exists and not project_exists:
                classification = "stale"
                replacement = _rewrite_framework_paths(reference, version)
                reason = "Ресурс найден только в установленном Framework."
            elif project_exists and not package_exists:
                classification = "project"
                reason = "Ресурс принадлежит проекту-потребителю."
            else:
                classification = "ambiguous"
                reason = "Принадлежность legacy-пути Framework не доказана."
        references.append(
            {
                "file": relative_file,
                "line": line,
                "column": column,
                "value": reference,
                "classification": classification,
                "replacement": replacement,
                "reason": reason,
                "source": source_kind,
            }
        )
    return references


def post_install_validate(
    target_root: Path,
    version: str,
    release_path: Path | None = None,
) -> dict[str, object]:
    """Проверить согласованность ссылок consumer-проекта после установки."""
    framework_root = _framework_root(version)
    package_path = release_path or target_root / Path(framework_root)
    errors: list[str] = []
    framework_fingerprint: str | None = None
    structure_path = target_root / ".project-structure.json"
    try:
        build_release.ensure_path_without_symlinks(target_root, structure_path, "структура проекта")
        structure = normalized_json(structure_path) if structure_path.is_file() else None
    except (build_release.BuildError, OSError) as error:
        errors.append(str(error))
        structure = None
    if not isinstance(structure, dict):
        errors.append("Отсутствует или повреждён корневой .project-structure.json.")
    else:
        framework = structure.get("framework")
        if not isinstance(framework, dict) or framework.get("package_id") != "sdd-template":
            errors.append("В .project-structure.json отсутствует Framework package_id.")
        elif framework.get("release_dir") != framework_root:
            errors.append("framework.release_dir не совпадает с проверяемым релизом.")
    if os.path.lexists(_framework_alias(target_root)):
        try:
            _verify_active_alias(target_root, version)
        except (OSError, build_release.BuildError) as error:
            errors.append(f"Постоянный адрес Framework не совпадает с релизом: {error}")
    if not package_path.is_dir():
        errors.append(f"Не найден установленный Framework root: {framework_root}")
    else:
        try:
            package_inventory = inventory_release(package_path, expected_version=version)
            fingerprint = package_inventory.get("fingerprint")
            if isinstance(fingerprint, str):
                framework_fingerprint = fingerprint
            inventory_errors = package_inventory.get("errors")
            if isinstance(inventory_errors, list):
                errors.extend(str(item) for item in inventory_errors)
            nonstandard_paths = package_inventory.get("nonstandard_paths")
            if isinstance(nonstandard_paths, list) and nonstandard_paths:
                errors.append(
                    "Установленный Framework отличается от release-manifest.json: "
                    + ", ".join(str(item) for item in nonstandard_paths)
                )
        except build_release.BuildError as error:
            errors.append(str(error))
    try:
        files = _post_install_files(target_root)
    except build_release.BuildError as error:
        errors.append(str(error))
        files = []
    try:
        file_fingerprint = _post_install_file_fingerprint(files, target_root)
    except build_release.BuildError as error:
        errors.append(str(error))
        file_fingerprint = None
    cached_summary = None
    if not errors and framework_fingerprint and file_fingerprint:
        cached_summary = _load_reference_validation_cache(
            _reference_validation_cache_path(target_root),
            version,
            framework_fingerprint,
            file_fingerprint,
        )
    references: list[dict[str, object]] = []
    if cached_summary is None:
        for path in files:
            try:
                references.extend(_post_install_reference_records(path, target_root, version))
            except build_release.BuildError as error:
                errors.append(str(error))
    unresolved = [
        reference
        for reference in references
        if reference.get("classification") in {"stale", "missing", "ambiguous"}
    ]
    summary = cached_summary or {
        classification: sum(reference.get("classification") == classification for reference in references)
        for classification in ("valid", "historical", "project", "stale", "missing", "ambiguous", "external")
    }
    blocked = bool(errors or unresolved)
    result: dict[str, object] = {
        "schema_version": "1",
        "status": "blocked" if blocked else "pass",
        "framework_root": framework_root,
        "framework_root_fingerprint": framework_fingerprint,
        "checked_files_fingerprint": file_fingerprint,
        "checked_files": [path.relative_to(target_root).as_posix() for path in files],
        "references": references,
        "unresolved": unresolved,
        "summary": summary,
        "errors": errors,
    }
    if cached_summary is not None:
        result["reference_scan_cached"] = True
    elif (
        not blocked
        and not summary.get("historical")
        and not summary.get("project")
        and framework_fingerprint
        and file_fingerprint
    ):
        try:
            _store_reference_validation_cache(
                _reference_validation_cache_path(target_root),
                version,
                framework_fingerprint,
                file_fingerprint,
                summary,
            )
        except OSError:
            pass
    if blocked:
        result["next_action"] = {
            "type": "resolve_framework_paths",
            "required": True,
            "message": (
                "Исправьте stale/missing Framework-ссылки через явную миграцию "
                "или подтвердите ручное решение; external-ссылки не блокируют установку."
            ),
        }
    return result


def plan_text_reference_migration(
    target_root: Path, version: str, review: dict[str, object]
) -> dict[str, object]:
    """Построить точечный план текстовых замен без изменения документов."""
    if review.get("errors"):
        return {
            "status": "blocked",
            "changes": [],
            "errors": ["Post-install проверка содержит ошибки; сначала устраните их."],
        }
    errors: list[str] = []
    try:
        files = _post_install_files(target_root)
        current_fingerprint = _post_install_file_fingerprint(files, target_root)
    except build_release.BuildError as error:
        return {"status": "blocked", "changes": [], "errors": [str(error)]}
    expected_fingerprint = review.get("checked_files_fingerprint")
    if not isinstance(expected_fingerprint, str) or current_fingerprint != expected_fingerprint:
        return {
            "status": "blocked",
            "changes": [],
            "errors": ["Документы изменились после post-install проверки; постройте новый план."],
            "checked_files_fingerprint": current_fingerprint,
        }
    indexed_files = {path.relative_to(target_root).as_posix(): path for path in files}
    content_cache: dict[str, tuple[str, str]] = {}
    changes: list[dict[str, object]] = []
    blocked_references: list[dict[str, object]] = []
    references = review.get("unresolved")
    for item in references if isinstance(references, list) else []:
        if not isinstance(item, dict):
            continue
        relative = item.get("file")
        old_value = item.get("value")
        current_value = item.get("replacement")
        if (
            item.get("classification") != "stale"
            or item.get("source") not in {"local", "markdown"}
            or relative == ".project-structure.json"
            or not isinstance(relative, str)
            or not isinstance(old_value, str)
            or not isinstance(current_value, str)
        ):
            blocked_references.append(item)
            continue
        path = indexed_files.get(relative)
        if path is None:
            blocked_references.append(item)
            continue
        try:
            if item.get("source") == "markdown":
                old_decoded = unquote(old_value.split("#", 1)[0].split("?", 1)[0])
                old_resolved = Path(os.path.normpath(path.parent / Path(old_decoded)))
                old_resolved.relative_to(target_root)
                build_release.ensure_path_without_symlinks(
                    target_root, old_resolved, "исходная цель Markdown-ссылки"
                )
                is_legacy_alias = "sdd-template-current" in old_decoded.replace("\\", "/")
                if not is_legacy_alias and not old_resolved.exists():
                    blocked_references.append(item)
                    continue
                decoded = unquote(current_value.split("#", 1)[0].split("?", 1)[0])
                resolved = Path(os.path.normpath(path.parent / Path(decoded)))
                target_path = target_root / Path(_framework_root(version))
                suffix = resolved.relative_to(target_path)
                target_path = target_path / suffix
                replacement = current_value
            else:
                normalized = current_value.replace("\\", "/")
                if normalized == "FRAMEWORK_ROOT" or normalized.startswith("FRAMEWORK_ROOT/"):
                    suffix_text = normalized[len("FRAMEWORK_ROOT"):].lstrip("/")
                    replacement = normalized
                elif normalized == _framework_root(version) or normalized.startswith(_framework_root(version) + "/"):
                    suffix_text = normalized[len(_framework_root(version)):].lstrip("/")
                    replacement = "FRAMEWORK_ROOT" + normalized[len(_framework_root(version)):]
                else:
                    raise ValueError("Unrecognized migration target")
                target_path = target_root / Path(_framework_root(version)) / suffix_text
            build_release.ensure_path_without_symlinks(target_root, target_path, "цель миграции ссылки")
        except (ValueError, OSError) as error:
            errors.append(str(error))
            blocked_references.append(item)
            continue
        if not target_path.exists():
            blocked_references.append(item)
            continue
        if relative not in content_cache:
            try:
                raw = fs_boundary.read_bytes(path)
                content_cache[relative] = (raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
            except (OSError, UnicodeError) as error:
                errors.append(f"Невозможно прочитать {relative} для плана миграции: {error}")
                blocked_references.append(item)
                continue
        content, file_sha256 = content_cache[relative]
        line = item.get("line")
        column = item.get("column")
        lines = content.splitlines(keepends=True)
        if (
            not isinstance(line, int) or not isinstance(column, int)
            or line < 1 or line > len(lines) or column < 1
            or column - 1 + len(old_value) > len(lines[line - 1])
        ):
            blocked_references.append(item)
            continue
        start = sum(len(value) for value in lines[:line - 1]) + column - 1
        end = start + len(old_value)
        if content[start:end] != old_value:
            blocked_references.append(item)
            continue
        changes.append({
            "file": relative,
            "line": line,
            "column": column,
            "start": start,
            "end": end,
            "old": old_value,
            "new": replacement,
            "file_sha256": file_sha256,
        })
    return {
        "status": "blocked" if errors or blocked_references else "planned",
        "version": version,
        "framework_root_fingerprint": review.get("framework_root_fingerprint"),
        "checked_files_fingerprint": current_fingerprint,
        "changes": changes,
        "blocked_references": blocked_references,
        "errors": errors,
    }


def apply_reference_migration(
    target_root: Path, version: str, plan: dict[str, object]
) -> dict[str, object]:
    """Применить только точные замены из неизменённого проверенного плана."""
    if plan.get("status") != "planned" or plan.get("version") != version:
        raise build_release.BuildError("План миграции ссылок не готов к применению.")
    active_version, active_path = installed_release(target_root)
    if active_version != version or active_path is None:
        raise build_release.BuildError("Активный релиз изменился после плана миграции ссылок.")
    if os.path.lexists(_framework_alias(target_root)):
        _verify_active_alias(target_root, version)
    package_inventory = inventory_release(active_path, expected_version=version)
    if (
        package_inventory.get("errors") or package_inventory.get("nonstandard_paths")
        or package_inventory.get("fingerprint") != plan.get("framework_root_fingerprint")
    ):
        raise build_release.BuildError("Пакет Framework изменился после плана миграции ссылок.")
    files = _post_install_files(target_root)
    current_fingerprint = _post_install_file_fingerprint(files, target_root)
    if current_fingerprint != plan.get("checked_files_fingerprint"):
        raise build_release.BuildError("Документы изменились после плана миграции ссылок.")
    indexed_files = {path.relative_to(target_root).as_posix(): path for path in files}
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise build_release.BuildError("План миграции не содержит корректных изменений.")
    by_file: dict[str, list[dict[str, object]]] = {}
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get("file"), str):
            raise build_release.BuildError("Некорректная запись замены ссылки.")
        by_file.setdefault(change["file"], []).append(change)
    replacements: list[tuple[Path, bytes, bytes]] = []
    for relative, file_changes in sorted(by_file.items()):
        path = indexed_files.get(relative)
        if path is None:
            raise build_release.BuildError(f"Файл миграции не входит в проверенный набор: {relative}")
        original = fs_boundary.read_bytes(path)
        content = original.decode("utf-8")
        digest = hashlib.sha256(original).hexdigest()
        previous_end = 0
        rewritten: list[str] = []
        for change in sorted(file_changes, key=_reference_change_start):
            start, end = change.get("start"), change.get("end")
            old, new = change.get("old"), change.get("new")
            if (
                not isinstance(start, int) or not isinstance(end, int)
                or not isinstance(old, str) or not isinstance(new, str)
                or start < previous_end or end < start
                or content[start:end] != old or change.get("file_sha256") != digest
            ):
                raise build_release.BuildError(f"Исходный фрагмент изменился: {relative}")
            rewritten.extend((content[previous_end:start], new))
            previous_end = end
        rewritten.append(content[previous_end:])
        replacements.append((path, original, "".join(rewritten).encode("utf-8")))
    for path, original, replacement in replacements:
        fs_boundary.replace_if_same(path, original, replacement)
    review = post_install_validate(target_root, version)
    return {
        "status": "applied" if review.get("status") == "pass" else "applied_pending_review",
        "files_changed": len(replacements),
        "post_install_review": review,
    }


def _reference_change_start(change: dict[str, object]) -> int:
    start = change.get("start")
    return start if isinstance(start, int) else -1


def _git_status(source_root: Path) -> tuple[bool, dict[str, str], str | None]:
    command = [
        "git",
        "-C",
        str(source_root),
        "-c",
        f"safe.directory={source_root.as_posix()}",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as error:
        return False, {}, str(error)
    if result.returncode != 0:
        return False, {}, result.stderr.strip() or "git status завершился с ошибкой"
    statuses: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        relative = line[3:]
        if " -> " in relative and code[0] in {"R", "C"}:
            relative = relative.rsplit(" -> ", 1)[1]
        relative = relative.replace("\\", "/").rstrip("/")
        if code == "!!":
            statuses[relative] = "ignored"
        elif code == "??":
            statuses[relative] = "untracked"
        else:
            statuses[relative] = "modified"
    return True, statuses, None


def _status_for_path(relative: str, statuses: dict[str, str]) -> str | None:
    matches = [
        (candidate, status)
        for candidate, status in statuses.items()
        if relative == candidate or relative.startswith(candidate + "/")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def _stage_expected_paths(
    source_root: Path,
) -> tuple[dict[str, dict[str, dict[str, object]]], list[str]]:
    expected_by_root: dict[str, dict[str, dict[str, object]]] = {}
    errors: list[str] = []
    tmp_root = source_root / "tmp"
    if not tmp_root.is_dir():
        return expected_by_root, errors
    for stage in sorted(tmp_root.iterdir(), key=lambda path: path.name):
        if not stage.is_dir() or build_release.is_link_or_reparse_point(stage) or not stage.name.startswith("sdd-template-build-"):
            continue
        root_relative = stage.relative_to(source_root).as_posix()
        manifest_path = stage / "release-manifest.json"
        try:
            if build_release.is_link_or_reparse_point(manifest_path):
                raise ValueError("release-manifest.json является ссылкой или reparse point")
            manifest = json.loads(_read_text(manifest_path))
            records = manifest.get("files") if isinstance(manifest, dict) else None
            if not isinstance(records, list):
                raise ValueError("отсутствует массив files")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"Невозможно определить канонический staging {root_relative}: {error}")
            expected_by_root[root_relative] = {root_relative: {"type": "directory"}}
            continue
        expected: dict[str, dict[str, object]] = {
            root_relative: {"type": "directory"},
            f"{root_relative}/release-manifest.json": {"type": "file"},
        }
        for record in records:
            if not isinstance(record, dict):
                errors.append(f"В staging {root_relative} обнаружена некорректная запись files.")
                continue
            relative = _safe_manifest_path(record.get("path"))
            if relative is None or relative == "release-manifest.json":
                errors.append(f"В staging {root_relative} обнаружен некорректный путь files.")
                continue
            full_relative = f"{root_relative}/{relative}"
            if full_relative in expected:
                errors.append(f"В staging {root_relative} обнаружен повторный путь files: {relative}.")
                continue
            size = record.get("size")
            sha256 = record.get("sha256")
            if type(size) is not int or size < 0 or not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
                errors.append(f"В staging {root_relative} обнаружены некорректные size или sha256: {relative}.")
                continue
            expected[full_relative] = {"type": "file", "size": size, "sha256": sha256}
            for parent in Path(relative).parents:
                if parent.as_posix() != ".":
                    expected.setdefault(f"{root_relative}/{parent.as_posix()}", {"type": "directory"})
        expected_by_root[root_relative] = expected
    return expected_by_root, errors


def inventory_source_clone(source_root: Path) -> dict[str, object]:
    """Проверить source clone, его staging и пользовательские изменения."""
    if not source_root.is_dir() or build_release.is_link_or_reparse_point(source_root):
        raise build_release.BuildError(f"Каталог source clone не найден или является ссылкой: {source_root}")
    git_available, git_status, git_error = _git_status(source_root)
    entries, skipped = _collect_entries(source_root, skip_directories={".git"})
    stage_expected, stage_errors = _stage_expected_paths(source_root)
    errors = list(stage_errors)
    if not git_available:
        errors.append(f"Невозможно проверить git status source clone: {git_error or 'неизвестная ошибка'}")
    for item in entries:
        relative = str(item["path"])
        status = _status_for_path(relative, git_status)
        item["status"] = status or "tracked"
        if item.get("type") in {"symlink", "reparse"}:
            item["classification"] = "user_data"
            item["status"] = "unsafe_link"
            errors.append(f"В source clone обнаружена ссылка или reparse point: {relative}")
            continue
        if relative == ".git":
            item["classification"] = "framework"
            item["status"] = "service"
            continue
        if relative == "tmp" and item.get("type") == "directory":
            item["classification"] = "framework"
            item["status"] = "service"
            continue
        generated = any(
            relative == root_relative or relative.startswith(root_relative + "/")
            for root_relative in stage_expected
        )
        if generated:
            stage_root, expected = next(
                (root_relative, expected) for root_relative, expected in stage_expected.items()
                if relative == root_relative or relative.startswith(root_relative + "/")
            )
            record = expected.get(relative)
            if record is None:
                item["classification"] = "user_data"
                item["status"] = status or "unknown"
            elif record.get("type") == "directory":
                item["classification"] = "generated" if item.get("type") == "directory" else "user_data"
                item["status"] = "generated" if item.get("type") == "directory" else "modified"
            elif relative == f"{stage_root}/release-manifest.json":
                item["classification"] = "generated" if item.get("type") == "file" else "user_data"
                item["status"] = "generated" if item.get("type") == "file" else "modified"
            elif (
                item.get("type") == "file"
                and isinstance(record.get("size"), int)
                and item.get("size") == record["size"]
                and isinstance(record.get("sha256"), str)
                and item.get("sha256") == record["sha256"]
            ):
                item["classification"] = "generated"
                item["status"] = "generated"
            else:
                item["classification"] = "user_data"
                item["status"] = "modified"
                errors.append(f"Содержимое staging не совпадает с release-manifest.json: {relative}")
        elif status:
            item["classification"] = "user_data"
        elif git_available:
            item["classification"] = "framework"
        else:
            item["classification"] = "user_data"
            item["status"] = "unknown"
    actual_paths = {str(item["path"]) for item in entries}
    for relative, status in git_status.items():
        if status == "modified" and relative not in actual_paths:
            errors.append(f"Отсутствует изменённый tracked-путь source clone: {relative}")
    for expected in stage_expected.values():
        for relative in expected.keys() - actual_paths:
            errors.append(f"В staging отсутствует канонический путь: {relative}")
    user_data_paths = {
        str(item["path"])
        for item in entries
        if item.get("classification") == "user_data"
    }
    for item in entries:
        if item.get("type") != "directory" or item.get("classification") == "user_data":
            continue
        relative = str(item["path"])
        if any(path.startswith(relative + "/") for path in user_data_paths):
            item["classification"] = "user_data"
            item["status"] = "contains_user_data"
    git_report: dict[str, object] = {
        "available": git_available,
        "head": build_release.git_value(source_root, ["rev-parse", "HEAD"], "") if git_available else None,
        "status_entries": git_status,
    }
    extra: dict[str, object] = {"git": git_report}
    if git_error:
        git_report["error"] = git_error
    inventory = _finalize_inventory(
        entries,
        errors,
        "source_clone_and_nested_staging",
        skipped,
        extra,
    )
    source_entries = [
        item for item in entries
        if item.get("path") != "tmp"
        and not str(item.get("path", "")).startswith("tmp/sdd-template-build-")
    ]
    source_payload = json.dumps(
        {"head": git_report["head"], "entries": source_entries},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    inventory["source_fingerprint"] = hashlib.sha256(source_payload).hexdigest()
    return inventory


def inventory_message(inventory: dict[str, object], title: str) -> str:
    summary_value = inventory.get("summary")
    summary: dict[str, object] = summary_value if isinstance(summary_value, dict) else {}
    lines = [
        title,
        f"Fingerprint inventory: {inventory.get('fingerprint')}",
        f"Объектов: {summary.get('entries', 0)}, файлов: {summary.get('files', 0)}, "
        f"размер файлов: {summary.get('bytes', 0)} байт.",
    ]
    errors = inventory.get("errors")
    if isinstance(errors, list) and errors:
        lines.append("Ошибки проверки:")
        lines.extend(f"- {error}" for error in errors)
    top_level = inventory.get("top_level_nonstandard")
    if isinstance(top_level, list) and top_level:
        lines.append("Нестандартные top-level пути:")
        lines.extend(f"- {path}" for path in top_level)
    else:
        lines.append("Нестандартные пользовательские данные не обнаружены.")
    paths = inventory.get("nonstandard_paths")
    if isinstance(paths, list) and paths:
        lines.append("Полный список нестандартных путей:")
        lines.extend(f"- {path}" for path in paths)
        lines.append(
            "Данные пользователя не удаляются автоматически; сохраните или перенесите их "
            "либо передайте явное подтверждение по fingerprint."
        )
    return "\n".join(lines)


def validate_cleanup_target(target_root: Path, source_root: Path) -> tuple[Path, str]:
    """Проверить, что cleanup target — непосредственный source clone в tmp/."""
    if source_root.is_symlink():
        raise build_release.BuildError(f"Каталог клона не должен быть символьной ссылкой: {source_root}")
    source_root = Path(os.path.abspath(source_root))
    if is_external_source_clone(target_root, source_root):
        return source_root, f"OS-temp/{source_root.parent.name}/{source_root.name}"
    resolved_target_root = Path(os.path.abspath(target_root))
    tmp_candidate = resolved_target_root / "tmp"
    build_release.ensure_path_without_symlinks(
        resolved_target_root, tmp_candidate, "каталог временных файлов проекта"
    )
    tmp_root = Path(os.path.abspath(tmp_candidate))
    build_release.ensure_path_without_symlinks(
        tmp_root, source_root, "каталог удаляемого клона"
    )
    if source_root.parent != tmp_root or not source_root.name.startswith("sdd-template-source-"):
        raise build_release.BuildError(
            "Очистка разрешена только для непосредственного клона "
            "<target-root>/tmp/sdd-template-source-X.Y.Z-<short-commit>."
        )
    if not source_root.is_dir():
        raise build_release.BuildError(f"Каталог клона не найден или является ссылкой: {source_root}")
    try:
        relative_path = source_root.relative_to(Path(os.path.abspath(target_root))).as_posix()
    except ValueError as error:
        raise build_release.BuildError("Каталог клона должен находиться внутри корня проекта.") from error
    return source_root, relative_path


def cleanup_plan(target_root: Path, source_root: Path) -> dict[str, object]:
    source_root, relative_path = validate_cleanup_target(target_root, source_root)
    inventory = inventory_source_clone(source_root)
    question = (
        f"Удалить каталог {relative_path} после проверки inventory? "
        "Ответьте «да» или «нет» и передайте fingerprint только для подтверждённого удаления."
    )
    return {
        "status": "awaiting_user_confirmation",
        "path": relative_path,
        "scope": "source_clone_and_nested_staging",
        "confirmation_required": True,
        "question": question,
        "inventory": inventory,
        "next_action": {
            "type": "user_confirmation",
            "required": True,
            "message": question,
            "fingerprint": inventory.get("fingerprint"),
        },
    }


def cleanup_source_clone(
    target_root: Path,
    source_root: Path,
    cleanup_action: str,
    expected_fingerprint: str | None = None,
    report_mode: str = "full",
) -> dict[str, object]:
    """Проверить inventory и оставить или удалить только подтверждённый source clone."""
    source_root, relative_path = validate_cleanup_target(target_root, source_root)
    inventory = inventory_source_clone(source_root)
    current_fingerprint = inventory.get("fingerprint")
    if cleanup_action == "delete":
        if not expected_fingerprint:
            plan = cleanup_plan(target_root, source_root)
            print_detail(inventory_message(inventory, "Требуется отдельное подтверждение очистки."), report_mode)
            return plan
        if expected_fingerprint != current_fingerprint:
            raise build_release.BuildError(
                "Inventory source clone изменился после подтверждения; удаление заблокировано. "
                f"Текущий fingerprint: {current_fingerprint}."
            )
        if inventory.get("errors"):
            raise build_release.BuildError(
                "Inventory source clone содержит ошибки; удаление заблокировано до повторной проверки."
            )
        external_workspace = is_external_source_clone(target_root, source_root)
        fs_boundary.remove_tree(source_root)
        if external_workspace:
            try:
                source_root.parent.rmdir()
            except OSError:
                pass
        status = "deleted"
    else:
        status = "kept"
    return {
        "status": status,
        "path": relative_path,
        "scope": "source_clone_and_nested_staging",
        "inventory": inventory,
        "confirmed_fingerprint": expected_fingerprint,
        "confirmation_required": False,
    }


def old_release_confirmation_plan(
    target_root: Path,
    current_version: str,
    current_path: Path,
    target_version: str,
    action: str,
    inventory: dict[str, object],
) -> dict[str, object]:
    relative_path = current_path.relative_to(target_root).as_posix()
    question = (
        f"Обнаружен старый release {current_version} в {relative_path}. "
        f"Подтвердите действие {action} после проверки inventory. "
        "Для удаления или переноса передайте fingerprint отдельным вызовом."
    )
    result: dict[str, object] = {
        "status": "awaiting_user_confirmation",
        "current_version": current_version,
        "target_version": target_version,
        "old_action": action,
        "old_release": {
            "path": relative_path,
            "inventory": inventory,
        },
        "next_action": {
            "type": "user_confirmation",
            "required": True,
            "message": question,
            "fingerprint": inventory.get("fingerprint"),
        },
    }
    tmp_root = target_root / "tmp"
    source_candidates = sorted(
        (
            child
            for child in tmp_root.iterdir()
            if child.is_dir() and not child.is_symlink() and child.name.startswith("sdd-template-source-")
        ),
        key=lambda path: path.name,
    ) if tmp_root.is_dir() else []
    if len(source_candidates) == 1:
        source_cleanup = cleanup_plan(target_root, source_candidates[0])
        result["source_cleanup"] = source_cleanup
        result["next_actions"] = [result["next_action"], source_cleanup["next_action"]]
    return result


def settle_source_cleanup(
    target_root: Path, source_root: Path, action: str | None,
    source_fingerprint: str | None, report_mode: str,
) -> dict[str, object]:
    if action is None:
        action = "delete"
    if action == "keep":
        return cleanup_source_clone(target_root, source_root, "keep", report_mode=report_mode)
    inventory = inventory_source_clone(source_root)
    if (
        not source_fingerprint or inventory.get("source_fingerprint") != source_fingerprint
        or inventory.get("safe_to_delete") is not True
    ):
        return {
            "status": "blocked",
            "inventory": inventory,
            "reason": "Source clone изменился или содержит нестандартные данные; очистка отменена.",
        }
    return cleanup_source_clone(
        target_root, source_root, "delete", str(inventory["fingerprint"]), report_mode
    )


def _source_fingerprint_value(inventory: dict[str, object]) -> str | None:
    value = inventory.get("source_fingerprint")
    return value if isinstance(value, str) else None


def agents_confirmation_message(review: dict[str, object]) -> str:
    """Сформировать понятный запрос решения по расхождениям AGENTS.md."""
    conflicts_value = review.get("conflicts")
    conflict_messages: list[str] = []
    if isinstance(conflicts_value, list):
        conflict_messages = [item for item in conflicts_value if isinstance(item, str)]
    differences = review.get("differences")
    lines = ["Обнаружены расхождения в AGENTS.md:"]
    lines.extend(f"- {item}" for item in conflict_messages)
    if isinstance(differences, list):
        for difference in differences:
            if isinstance(difference, dict):
                message = difference.get("message")
                if isinstance(message, str) and message not in conflict_messages:
                    lines.append(f"- {message}")
    lines.append(
        "Повторите установку с --agents-action migrate, --agents-action replace-legacy, "
        "--agents-action replace-managed или --agents-action keep после решения пользователя."
    )
    return "\n".join(lines)


def project_structure_confirmation_message(review: dict[str, object]) -> str:
    """Сформировать запрос решения по корневому project-structure."""
    conflicts = review.get("conflicts")
    lines = ["Обнаружены расхождения в .project-structure.json:"]
    if isinstance(conflicts, list):
        lines.extend(f"- {item}" for item in conflicts if isinstance(item, str))
    lines.append(
        "Повторите установку с --project-structure-action migrate, "
        "--project-structure-action replace или "
        "--project-structure-action keep после решения пользователя."
    )
    return "\n".join(lines)


def compact_report(value: object) -> object:
    """Убрать штатные перечни файлов, сохранив блокировки и fingerprints."""
    if isinstance(value, list):
        return [compact_report(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "changes" in value and "blocked_references" in value and "checked_files_fingerprint" in value:
        return {
            key: compact_report(item)
            for key, item in {**value, "changes_count": len(value.get("changes", []))}.items()
            if key != "changes"
        }
    if "checked_files" in value and "post_install_review" not in value:
        return {
            key: compact_report(item)
            for key, item in {**value, "checked_files_count": len(value.get("checked_files", []))}.items()
            if key not in {"checked_files", "references"}
        }
    if "fingerprint" in value and "entries" in value and "nonstandard_paths" in value:
        compact = {
            key: compact_report(item)
            for key, item in value.items()
            if key not in {"entries", "skipped_service_paths", "git"}
        }
        compact["skipped_service_paths_count"] = len(value.get("skipped_service_paths", []))
        git_report = value.get("git")
        if isinstance(git_report, dict):
            status_entries = git_report.get("status_entries", {})
            compact["git"] = {
                key: item for key, item in git_report.items() if key != "status_entries"
            }
            compact["git"]["status_entries_count"] = len(status_entries)
        return compact
    if "references" in value and isinstance(value["references"], list):
        compact = {key: compact_report(item) for key, item in value.items() if key != "references"}
        compact["references_count"] = len(value["references"])
        compact["unresolved_references"] = [
            compact_report(item) for item in value["references"]
            if isinstance(item, dict) and item.get("classification") in {"stale", "missing", "ambiguous"}
        ]
        return compact
    return {key: compact_report(item) for key, item in value.items()}


def print_report(value: object, mode: str) -> None:
    report = value if mode == "full" else compact_report(value)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def print_detail(message: str, mode: str) -> None:
    if mode == "full":
        print(message, file=sys.stderr)


def migrate_reviewed_references(
    target_root: Path, version: str, review: dict[str, object]
) -> tuple[dict[str, object], dict[str, object] | None]:
    if review.get("status") == "pass":
        return review, None
    migration = plan_text_reference_migration(target_root, version, review)
    if migration.get("status") == "planned" and migration.get("changes"):
        applied = apply_reference_migration(target_root, version, migration)
        post_review = applied.get("post_install_review")
        if isinstance(post_review, dict):
            return post_review, applied
    return review, migration


def historical_links_to_release(review: dict[str, object], version: str) -> list[dict[str, object]]:
    references = review.get("references")
    found: list[dict[str, object]] = []
    for item in references if isinstance(references, list) else []:
        if not isinstance(item, dict) or item.get("classification") != "historical" or item.get("source") != "markdown":
            continue
        value = item.get("value")
        match = AGENTS_VERSION_PATTERN.search(value) if isinstance(value, str) else None
        if match is not None and match.group(1) == version:
            found.append(item)
    return found


def historical_link_block(links: list[dict[str, object]], version: str) -> dict[str, object]:
    return {
        "status": "installed_pending_review",
        "historical_links": links,
        "next_action": {
            "type": "resolve_historical_links",
            "required": True,
            "message": (
                f"Архивные локальные Markdown-ссылки ведут в release {version}. "
                "Перед переносом или удалением пакета переведите их на проверенный неизменяемый источник."
            ),
        },
    }


def automatic_agents_action(review: dict[str, object]) -> str | None:
    """Выбрать безопасное обновление только явно управляемого содержимого AGENTS.md."""
    conflicts = review.get("conflicts")
    if not isinstance(conflicts, list) or not conflicts:
        return None
    references = review.get("path_references")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                return None
            classification = reference.get("classification")
            location = reference.get("location")
            if classification in {"ambiguous", "missing"}:
                return None
            if classification == "stale" and location != "managed":
                return None
    if review.get("can_migrate") is True:
        return "migrate"
    differences = review.get("differences")
    codes = {
        item.get("code") for item in differences
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    } if isinstance(differences, list) else set()
    if review.get("can_replace_managed") is True and codes == {"managed_section_differs"}:
        return "replace-managed"
    return None


def automatic_project_structure_action(review: dict[str, object]) -> str | None:
    """Разрешить миграцию только когда все пути структуры однозначны."""
    conflicts = review.get("conflicts")
    if isinstance(conflicts, list) and conflicts and review.get("can_migrate") is True:
        return "migrate"
    return None


def main() -> int:
    args = parse_args()
    target_root = Path(os.path.abspath(args.target_root))
    if args.cleanup_action is not None and args.action is None:
        if (
            args.source_root is None
            or args.action is not None
            or args.version is not None
            or args.old_action not in {"ask", "auto"}
            or args.old_confirmation is not None
            or args.write
        ):
            raise build_release.BuildError(
                "Для --cleanup-action укажите только --source-root, --target-root, "
                "--cleanup-action и при необходимости --cleanup-fingerprint."
            )
        if args.cleanup_action == "delete" and args.cleanup_fingerprint:
            source_version = build_release.read_version(args.source_root)
            current_version, current_path = installed_release(target_root)
            if current_version != source_version or current_path is None:
                raise build_release.BuildError(
                    "Очистка source clone разрешена только после установки проверяемого релиза."
                )
            if len(build_release.direct_release_dirs(target_root / ".agents", allow_alias=True)) != 1:
                raise build_release.BuildError(
                    "Очистка source clone разрешена только после завершения действия со старым релизом."
                )
            review = post_install_validate(target_root, source_version, current_path)
            if review.get("status") != "pass":
                raise build_release.BuildError(
                    "Post-install проверка не прошла; очистка source clone заблокирована."
                )
        cleanup = cleanup_source_clone(
            target_root,
            args.source_root,
            args.cleanup_action,
            args.cleanup_fingerprint,
            args.report,
        )
        top_status = "cleanup_completed" if cleanup.get("status") in {"deleted", "kept"} else "awaiting_user_confirmation"
        print_report({"status": top_status, "cleanup": cleanup}, args.report)
        return 0
    if args.cleanup_fingerprint is not None and args.cleanup_action is None:
        raise build_release.BuildError("--cleanup-fingerprint разрешён только вместе с --cleanup-action.")

    if args.source_root is None or args.action is None:
        raise build_release.BuildError("Для установки необходимо указать --source-root и --action.")
    source_root = Path(os.path.abspath(args.source_root))
    if source_root == target_root:
        raise build_release.BuildError("Исходная копия и проект-потребитель должны находиться в разных каталогах.")
    validate_source_location(target_root, source_root)

    registry = build_release.read_release_registry(source_root)
    version = choose_version(registry, args.action, args.version)
    entry = build_release.release_entry(registry, version)
    source_ref = entry.get("ref")
    install_path = entry.get("install_path")
    if not isinstance(source_ref, str) or not isinstance(install_path, str):
        raise build_release.BuildError(f"В реестре отсутствуют корректные ref или install_path для версии {version}.")
    source_version = build_release.read_version(source_root)
    if source_version != version:
        raise build_release.BuildError(
            f"Версия исходной копии {source_version} не совпадает с выбранной версией {version}. "
            "Клонируйте источник по ref из записи реестра."
        )
    validate_source_clone_name(source_root, version)
    source_inventory = inventory_source_clone(source_root)
    cleanup_requires_confirmation = (
        args.cleanup_action == "delete" and (
            not args.cleanup_fingerprint
            or source_inventory.get("source_fingerprint") != args.cleanup_fingerprint
            or source_inventory.get("safe_to_delete") is not True
        )
    )

    current_version, current_path = installed_release(target_root)
    if args.action == "init" and current_version is not None:
        raise build_release.BuildError(
            f"Инициализация невозможна: уже установлен релиз {current_version}. Используйте update или use."
        )
    if args.old_confirmation is not None and current_path is None:
        raise build_release.BuildError("--old-confirmation нельзя использовать без установленного старого release.")
    if args.action == "update" and current_version is not None and version_key(current_version) > version_key(version):
        raise build_release.BuildError(
            f"Установлена более новая версия {current_version}; для возврата используйте действие use."
        )
    old_inventory: dict[str, object] | None = None
    replacing_old_release = current_path is not None and current_version != version
    if replacing_old_release and current_path is not None:
        current_path = build_release.ensure_path_without_symlinks(
            target_root, current_path, "путь старого релиза"
        )
        old_inventory = inventory_release(current_path)
    preflight_review = (
        post_install_validate(target_root, current_version, current_path)
        if current_version is not None and current_path is not None else None
    )
    historical_preflight = (
        historical_links_to_release(preflight_review, current_version)
        if isinstance(preflight_review, dict) and current_version is not None else []
    )
    agents_review = inspect_agents_instructions(target_root, source_root, version)
    project_structure_review = inspect_project_structure(target_root, source_root, version)
    agents_auto_action = automatic_agents_action(agents_review)
    project_structure_auto_action = automatic_project_structure_action(project_structure_review)
    effective_agents_action = (
        agents_auto_action if args.agents_action == "ask" and agents_auto_action is not None
        else args.agents_action
    )
    effective_project_structure_action = (
        project_structure_auto_action
        if args.project_structure_action == "ask" and project_structure_auto_action is not None
        else args.project_structure_action
    )
    agents_conflicts = agents_review.get("conflicts")
    project_structure_conflicts = project_structure_review.get("conflicts")
    agents_requires_confirmation = (
        args.agents_action == "ask" and isinstance(agents_conflicts, list) and bool(agents_conflicts)
        and agents_auto_action is None
    )
    project_structure_requires_confirmation = (
        args.project_structure_action == "ask"
        and isinstance(project_structure_conflicts, list)
        and bool(project_structure_conflicts)
        and project_structure_auto_action is None
    )
    agents_migration_requires_confirmation = (
        args.agents_action == "migrate"
        and isinstance(agents_conflicts, list)
        and bool(agents_conflicts)
        and agents_review.get("can_migrate") is not True
    )
    project_structure_migration_requires_confirmation = (
        args.project_structure_action == "migrate"
        and isinstance(project_structure_conflicts, list)
        and bool(project_structure_conflicts)
        and project_structure_review.get("can_migrate") is not True
    )
    if args.write and (
        agents_requires_confirmation
        or project_structure_requires_confirmation
        or agents_migration_requires_confirmation
        or project_structure_migration_requires_confirmation
        or cleanup_requires_confirmation
        or (bool(historical_preflight) and args.old_action in {"move", "delete"})
    ):
        messages = []
        if agents_requires_confirmation or agents_migration_requires_confirmation:
            messages.append(agents_confirmation_message(agents_review))
        if project_structure_requires_confirmation or project_structure_migration_requires_confirmation:
            messages.append(project_structure_confirmation_message(project_structure_review))
        if old_inventory is not None and current_path is not None and (
            args.old_action == "ask" or args.old_confirmation != old_inventory.get("fingerprint")
        ):
            choices = "keep, move или delete" if args.old_action == "ask" else args.old_action
            messages.append(
                f"Выберите действие со старым release: {choices}. "
                f"Fingerprint inventory: {old_inventory.get('fingerprint')}. "
                "Для move/delete передайте подтверждённый fingerprint через --old-confirmation."
            )
        if cleanup_requires_confirmation:
            messages.append(
                "Очистка source clone требует чистого inventory и подтверждённого "
                f"source fingerprint: {source_inventory.get('source_fingerprint')}."
            )
        if historical_preflight and args.old_action in {"move", "delete"}:
            next_action = historical_link_block(historical_preflight, current_version or "").get("next_action")
            message = next_action.get("message") if isinstance(next_action, dict) else None
            if not isinstance(message, str):
                raise build_release.BuildError("Не удалось сформировать сообщение о локальных исторических ссылках.")
            messages.append(message)
        confirmation_message = "\n\n".join(messages)
        review_plan = {
            "status": "awaiting_user_confirmation",
            "action": args.action,
            "current_version": current_version,
            "target_version": version,
            "source_ref": source_ref,
            "install_path": install_path,
            "agents": agents_review,
            "project_structure": project_structure_review,
            "source_cleanup": {
                "action": args.cleanup_action,
                "source_fingerprint": source_inventory.get("source_fingerprint"),
                "inventory": source_inventory,
            },
            "preflight_review": preflight_review,
            "historical_links": historical_preflight,
            "next_action": {
                "type": "user_confirmation",
                "required": True,
                "message": confirmation_message,
            },
        }
        if old_inventory is not None and current_path is not None:
            review_plan["old_release"] = {
                "path": current_path.relative_to(target_root).as_posix(),
                "inventory": old_inventory,
            }
        print_detail(confirmation_message, args.report)
        if old_inventory is not None:
            print_detail(inventory_message(old_inventory, "Inventory старого release."), args.report)
        print_report(review_plan, args.report)
        return 0
    if current_version == version:
        if not args.write:
            result = {
                "status": "planned",
                "action": args.action,
                "version": version,
                "install_path": install_path,
                "source_ref": source_ref,
                "source_cleanup": {
                    "action": args.cleanup_action,
                    "source_fingerprint": source_inventory.get("source_fingerprint"),
                    "inventory": source_inventory,
                },
                "write": False,
            }
            if current_path is not None:
                pending = [
                    candidate for candidate in build_release.direct_release_dirs(
                        target_root / ".agents", allow_alias=True
                    ) if candidate != current_path
                ]
                if len(pending) == 1:
                    result["old_release"] = {
                        "path": pending[0].relative_to(target_root).as_posix(),
                        "inventory": inventory_release(pending[0]),
                    }
                elif len(pending) > 1:
                    result["previous_releases"] = [
                        item.relative_to(target_root).as_posix() for item in pending
                    ]
            print_report(result, args.report)
            return 0
        if current_path is None:
            raise build_release.BuildError("Установленная версия определена без пути релиза.")
        verify_install_source(source_root, entry, source_inventory)
        project_root = initialize_project_root(
            target_root,
            current_path,
            source_root,
            version,
            effective_project_structure_action,
        )
        agents_result = ensure_agents_instructions(target_root, source_root, version, effective_agents_action)
        post_install_review = post_install_validate(target_root, version, current_path)
        post_install_review, reference_migration = migrate_reviewed_references(
            target_root, version, post_install_review
        )
        if post_install_review.get("status") == "pass":
            _finish_alias_switch(target_root, version)
        cleanup = cleanup_plan(target_root, source_root)
        post_install_blocked = post_install_review.get("status") != "pass"
        plan = {
            "status": "installed_pending_review" if post_install_blocked else "installed_pending_cleanup",
            "action": args.action,
            "current_version": current_version,
            "target_version": version,
            "source_ref": source_ref,
            "install_path": install_path,
            "write": True,
            "project_root": project_root,
            "agents": agents_result,
            "post_install_review": post_install_review,
            "cleanup": cleanup,
            "next_action": cleanup["next_action"],
        }
        pending_old = [
            candidate for candidate in build_release.direct_release_dirs(target_root / ".agents", allow_alias=True)
            if candidate != current_path
        ]
        if pending_old and args.old_action == "auto":
            retained_releases: list[dict[str, object]] = []
            for old_path in pending_old:
                old_match = build_release.RELEASE_PATTERN.fullmatch(old_path.name)
                if old_match is None:
                    raise build_release.BuildError(f"Неизвестный старый релиз: {old_path}")
                old_version = old_match.group(1)
                pending_inventory = inventory_release(old_path, expected_version=old_version)
                historical_links = historical_links_to_release(post_install_review, old_version)
                if (
                    not post_install_blocked
                    and pending_inventory.get("safe_to_delete") is True
                    and not pending_inventory.get("errors")
                    and not historical_links
                ):
                    _verify_old_release_before_action(old_path, pending_inventory.get("fingerprint"))
                    fs_boundary.remove_tree(old_path)
                else:
                    retained_releases.append({
                        "path": old_path.relative_to(target_root).as_posix(),
                        "version": old_version,
                        "reason": "user_data_or_historical_links_preserved",
                        "inventory": pending_inventory,
                        "historical_links": historical_links,
                    })
            if retained_releases:
                plan["previous_releases_retained"] = retained_releases
        elif len(pending_old) > 1:
            raise build_release.BuildError("Несколько старых релизов требуют отдельного решения об очистке.")
        elif pending_old:
            old_path = pending_old[0]
            old_match = build_release.RELEASE_PATTERN.fullmatch(old_path.name)
            if old_match is None:
                raise build_release.BuildError(f"Неизвестный старый релиз: {old_path}")
            old_version = old_match.group(1)
            pending_inventory = inventory_release(old_path, expected_version=old_version)
            plan["old_release"] = {
                "path": old_path.relative_to(target_root).as_posix(),
                "inventory": pending_inventory,
            }
            if args.old_action in {"move", "delete"}:
                historical_links = historical_links_to_release(post_install_review, old_version)
                if historical_links:
                    plan.update(historical_link_block(historical_links, old_version))
                    print_report(plan, args.report)
                    return 0
            if (
                post_install_blocked or args.old_action not in {"move", "delete"}
                or pending_inventory.get("errors")
                or args.old_confirmation != pending_inventory.get("fingerprint")
            ):
                confirmation = old_release_confirmation_plan(
                    target_root, old_version, old_path, version,
                    args.old_action if args.old_action != "ask" else "move или delete",
                    pending_inventory,
                )
                plan.update(confirmation)
                plan["status"] = "installed_pending_review" if post_install_blocked else "awaiting_user_confirmation"
                print_report(plan, args.report)
                return 0
            if args.old_action == "move":
                _verify_old_release_before_action(old_path, pending_inventory.get("fingerprint"))
                backup = free_backup_path(target_root, old_version)
                fs_boundary.mkdirs(backup.parent)
                fs_boundary.move_directory(old_path, backup)
                plan["old_path"] = backup.relative_to(target_root).as_posix()
            else:
                _verify_old_release_before_action(old_path, pending_inventory.get("fingerprint"))
                fs_boundary.remove_tree(old_path)
        if not post_install_blocked:
            cleanup = settle_source_cleanup(
                target_root, source_root, args.cleanup_action,
                _source_fingerprint_value(source_inventory)
                if args.cleanup_fingerprint is None else args.cleanup_fingerprint,
                args.report,
            )
            plan["cleanup"] = cleanup
            if cleanup.get("status") in {"deleted", "kept"}:
                plan["status"] = "completed"
                plan.pop("next_action", None)
            elif cleanup.get("status") == "blocked":
                plan["status"] = "installed_pending_cleanup"
                plan["next_action"] = {
                    "type": "review_source_cleanup", "required": True,
                    "message": str(cleanup.get("reason")),
                }
        if reference_migration is not None:
            plan["reference_migration"] = reference_migration
        if post_install_blocked and isinstance(post_install_review.get("next_action"), dict):
            plan["next_actions"] = [post_install_review["next_action"], cleanup["next_action"]]
        cleanup_inventory = cleanup.get("inventory")
        print_detail(
            inventory_message(
                cleanup_inventory if isinstance(cleanup_inventory, dict) else {},
                "Требуется подтверждение очистки source clone.",
            ),
            args.report,
        )
        print_report(plan, args.report)
        return 0
    plan = {
        "status": "planned" if not args.write else "writing",
        "action": args.action,
        "current_version": current_version,
        "target_version": version,
        "source_ref": source_ref,
        "install_path": install_path,
        "old_action": args.old_action,
        "write": args.write,
        "source_cleanup": {
            "action": args.cleanup_action,
            "source_fingerprint": source_inventory.get("source_fingerprint"),
            "inventory": source_inventory,
        },
    }
    if preflight_review is not None:
        plan["preflight_review"] = preflight_review
    if historical_preflight:
        plan["historical_links"] = historical_preflight
    if not args.write:
        plan["agents"] = agents_review
        plan["project_structure"] = project_structure_review
    if old_inventory is not None and current_path is not None:
        plan["old_release"] = {
            "path": current_path.relative_to(target_root).as_posix(),
            "inventory": old_inventory,
        }
    if not args.write:
        print_report(plan, args.report)
        return 0

    if current_path is not None and args.old_action != "auto":
        if args.old_action == "ask":
            confirmation = old_release_confirmation_plan(
                target_root,
                current_version or "unknown",
                current_path,
                version,
                "keep, move или delete",
                old_inventory or {},
            )
            print_detail(inventory_message(old_inventory or {}, "Требуется решение по старому release."), args.report)
            print_report({**plan, **confirmation}, args.report)
            return 0
        if args.old_action == "keep":
            plan["status"] = "kept"
            plan["write"] = False
            print_report(plan, args.report)
            return 0
        if args.old_action not in {"move", "delete"}:
            raise build_release.BuildError(f"Неизвестное действие со старым release: {args.old_action}")
        if old_inventory is None or old_inventory.get("errors"):
            confirmation = old_release_confirmation_plan(
                target_root,
                current_version or "unknown",
                current_path,
                version,
                args.old_action,
                old_inventory or {},
            )
            print_detail(inventory_message(old_inventory or {}, "Удаление или перенос старого release заблокированы."), args.report)
            print_report({**plan, **confirmation}, args.report)
            return 0
        if args.old_confirmation != old_inventory.get("fingerprint"):
            confirmation = old_release_confirmation_plan(
                target_root,
                current_version or "unknown",
                current_path,
                version,
                args.old_action,
                old_inventory,
            )
            print_detail(inventory_message(old_inventory, "Требуется подтверждение inventory старого release."), args.report)
            print_report({**plan, **confirmation}, args.report)
            return 0

    package_dir = target_root / Path(install_path)
    verify_install_source(source_root, entry, source_inventory)
    if package_dir.exists():
        existing_inventory = inventory_release(package_dir, expected_version=version)
        manifest = json.loads(_read_text(package_dir / "release-manifest.json"))
        source_commit = build_release.git_value(source_root, ["rev-parse", "HEAD"], "")
        if (
            existing_inventory.get("errors") or existing_inventory.get("nonstandard_paths")
            or manifest.get("source_repo") != build_release.SOURCE_REPOSITORY
            or manifest.get("source_ref") != source_ref
            or manifest.get("source_commit") != source_commit
        ):
            raise build_release.BuildError("Незавершённый пакет не совпадает с проверенным источником.")
        result = build_release.report(target_root, version, package_dir, source_root / "tmp", True)
        result["status"] = "reused_verified_package"
    else:
        stage_root = source_root / "tmp" / f"sdd-template-build-{version}"
        resume_stage = stage_root.exists()
        result = build_release.build_release(
            source_root,
            target_root,
            source_ref=source_ref,
            write=True,
            stage_root=stage_root,
            resume_stage=resume_stage,
            allow_existing_releases=True,
        )
    release_dir = result.get("release_dir")
    if not isinstance(release_dir, str):
        raise build_release.BuildError("Сборщик не вернул корректный путь релизного пакета.")
    if package_dir != target_root / Path(release_dir):
        raise build_release.BuildError("Путь установленного пакета не совпадает с install_path реестра.")
    runtime_data_result: dict[str, object] | None = None
    if current_path is not None and current_path != package_dir:
        runtime_data_result = preserve_runtime_data(current_path, package_dir)
    _begin_alias_switch(target_root, current_version, version)
    plan["project_root"] = initialize_project_root(
        target_root,
        package_dir,
        source_root,
        version,
        effective_project_structure_action,
    )
    agents_result = ensure_agents_instructions(target_root, source_root, version, effective_agents_action)
    plan["agents"] = agents_result
    post_install_review = post_install_validate(target_root, version, package_dir)
    post_install_review, reference_migration = migrate_reviewed_references(
        target_root, version, post_install_review
    )
    if post_install_review.get("status") == "pass":
        _finish_alias_switch(target_root, version)
    plan["post_install_review"] = post_install_review
    cleanup = cleanup_plan(target_root, source_root)
    post_install_blocked = post_install_review.get("status") != "pass"
    if reference_migration is not None:
        plan["reference_migration"] = reference_migration
    if not post_install_blocked and current_path is not None:
        historical_links = historical_links_to_release(post_install_review, current_version or "")
        if args.old_action in {"move", "delete"} and historical_links:
            plan.update(result)
            plan.update(historical_link_block(historical_links, current_version or ""))
            print_report(plan, args.report)
            return 0
        if args.old_action == "auto":
            if (
                old_inventory is not None
                and old_inventory.get("safe_to_delete") is True
                and not old_inventory.get("errors")
                and not historical_links
            ):
                _verify_old_release_before_action(current_path, old_inventory.get("fingerprint"))
                current_path = build_release.ensure_path_without_symlinks(
                    target_root, current_path, "путь старого релиза"
                )
                fs_boundary.remove_tree(current_path)
                plan["old_release_cleanup"] = {"status": "deleted", "version": current_version}
            else:
                plan["previous_releases_retained"] = [{
                    "path": current_path.relative_to(target_root).as_posix(),
                    "version": current_version,
                    "reason": "user_data_or_historical_links_preserved",
                    "inventory": old_inventory or {},
                    "historical_links": historical_links,
                }]
        elif args.old_action == "move":
            _verify_old_release_before_action(current_path, old_inventory.get("fingerprint") if old_inventory else None)
            backup = free_backup_path(target_root, current_version or "unknown")
            current_path = build_release.ensure_path_without_symlinks(
                target_root, current_path, "путь старого релиза"
            )
            backup = build_release.ensure_path_without_symlinks(
                target_root, backup, "путь резервной копии релиза"
            )
            fs_boundary.mkdirs(backup.parent)
            fs_boundary.move_directory(current_path, backup)
            plan["old_path"] = backup.relative_to(target_root).as_posix()
        elif args.old_action == "delete":
            _verify_old_release_before_action(current_path, old_inventory.get("fingerprint") if old_inventory else None)
            current_path = build_release.ensure_path_without_symlinks(
                target_root, current_path, "путь старого релиза"
            )
            fs_boundary.remove_tree(current_path)
    if not post_install_blocked:
        cleanup = settle_source_cleanup(
            target_root, source_root, args.cleanup_action,
            _source_fingerprint_value(source_inventory)
            if args.cleanup_fingerprint is None else args.cleanup_fingerprint,
            args.report,
        )
    plan.update(result)
    if runtime_data_result is not None:
        plan["runtime_data"] = runtime_data_result
    plan["status"] = (
        "installed_pending_review" if post_install_blocked
        else "completed" if cleanup.get("status") in {"deleted", "kept"}
        else "installed_pending_cleanup"
    )
    plan["cleanup"] = cleanup
    if isinstance(cleanup.get("next_action"), dict):
        plan["next_action"] = cleanup["next_action"]
    elif cleanup.get("status") == "blocked":
        plan["next_action"] = {
            "type": "review_source_cleanup", "required": True,
            "message": str(cleanup.get("reason")),
        }
    if post_install_blocked and isinstance(post_install_review.get("next_action"), dict):
        plan["next_actions"] = [post_install_review["next_action"], cleanup["next_action"]]
    cleanup_inventory = cleanup.get("inventory")
    print_detail(
        inventory_message(
            cleanup_inventory if isinstance(cleanup_inventory, dict) else {},
            "Требуется подтверждение очистки source clone.",
        ),
        args.report,
    )
    print_report(plan, args.report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (build_release.BuildError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
