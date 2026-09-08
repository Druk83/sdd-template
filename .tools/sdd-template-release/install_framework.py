#!/usr/bin/env python3
"""Установить выбранный релиз SDD Framework в проект-потребитель."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import build_release


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
        choices=("ask", "keep", "move", "delete"),
        default="ask",
        help="Действие со старым релизом после подтверждения пользователя.",
    )
    parser.add_argument(
        "--cleanup-action",
        choices=("keep", "delete"),
        help="Завершить отдельное подтверждение очистки клона: оставить или удалить.",
    )
    parser.add_argument(
        "--agents-action",
        choices=("ask", "keep", "replace-legacy", "replace-managed"),
        default="ask",
        help="Разрешение расхождений AGENTS.md после подтверждения пользователя.",
    )
    parser.add_argument(
        "--project-structure-action",
        choices=("ask", "keep", "replace"),
        default="ask",
        help="Разрешение расхождений корневого .project-structure.json.",
    )
    parser.add_argument("--write", action="store_true", help="Выполнить изменения; без флага только показать план.")
    return parser.parse_args()


def version_key(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def installed_release(target_root: Path) -> tuple[str | None, Path | None]:
    agents_dir = target_root / ".agents"
    if not agents_dir.is_dir():
        return None, None
    releases = build_release.direct_release_dirs(agents_dir)
    unknown = [
        child for child in agents_dir.iterdir()
        if child.is_dir() and child.name.startswith("sdd") and child not in releases
    ]
    if unknown:
        names = ", ".join(path.name for path in unknown)
        raise build_release.BuildError(f"В .agents обнаружены неизвестные каталоги SDD: {names}")
    if len(releases) > 1:
        names = ", ".join(path.name for path in releases)
        raise build_release.BuildError(f"В .agents должно быть не более одной папки SDD Framework: {names}")
    if not releases:
        return None, None
    match = build_release.RELEASE_PATTERN.fullmatch(releases[0].name)
    if match is None:
        raise build_release.BuildError(f"Некорректное имя установленного релиза: {releases[0].name}")
    return match.group(1), releases[0]


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
LEGACY_AGENTS_SIGNATURES = (
    "# Rules and Constraints for Codex (H0)",
    "### H1.1.",
    "### H1.3.",
    "## H1.8.",
    "## H1.10",
)


def agents_managed_block(source_root: Path) -> str:
    """Сформировать управляемый блок из канонических инструкций Framework."""
    source = source_root / "AGENTS.md"
    if not source.is_file():
        raise build_release.BuildError(f"В чистом источнике отсутствует канонический AGENTS.md: {source}")
    try:
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно прочитать канонический AGENTS.md: {error}") from error
    if not content.strip():
        raise build_release.BuildError("Канонический AGENTS.md не должен быть пустым.")
    if AGENTS_MANAGED_BEGIN in content or AGENTS_MANAGED_END in content:
        raise build_release.BuildError("Канонический AGENTS.md не должен содержать управляемые маркеры.")
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


def inspect_agents_instructions(target_root: Path, source_root: Path, version: str) -> dict[str, object]:
    """Проверить AGENTS.md до записи и сформировать объяснение расхождений."""
    expected_block = agents_managed_block(source_root)
    destination = target_root / "AGENTS.md"
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
        content = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно прочитать AGENTS.md: {error}") from error

    conflicts = detect_agents_conflicts(content, version)
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
    destination = target_root / "AGENTS.md"
    conflicts = review.get("conflicts")
    if not isinstance(conflicts, list):
        conflicts = []
    if conflicts:
        if agents_action == "ask":
            return review
        if agents_action == "keep":
            return {**review, "status": "kept"}
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
                content = destination.read_text(encoding="utf-8")
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
                    destination.write_text(
                        prefix + expected_block.rstrip("\n") + suffix,
                        encoding="utf-8",
                        newline="\n",
                    )
                else:
                    destination.write_text(expected_block, encoding="utf-8", newline="\n")
            else:
                content = destination.read_text(encoding="utf-8")
                begin = content.index(AGENTS_MANAGED_BEGIN)
                end = content.index(AGENTS_MANAGED_END, begin)
                new_content = content[:begin] + expected_block.rstrip("\n") + content[end + len(AGENTS_MANAGED_END) :]
                destination.write_text(new_content, encoding="utf-8", newline="\n")
        except (OSError, ValueError) as error:
            raise build_release.BuildError(f"Невозможно разрешить расхождение AGENTS.md: {error}") from error
        return {**review, "status": "replaced"}

    if review.get("status") == "absent":
        try:
            destination.write_text(agents_managed_block(source_root), encoding="utf-8", newline="\n")
        except OSError as error:
            raise build_release.BuildError(f"Невозможно создать AGENTS.md: {error}") from error
        return {**review, "status": "created"}

    try:
        content = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise build_release.BuildError(f"Невозможно перечитать AGENTS.md: {error}") from error
    if AGENTS_MANAGED_BEGIN not in content:
        separator = "" if not content or content.endswith(("\n", "\r")) else "\n"
        try:
            destination.write_text(
                content + separator + "\n" + agents_managed_block(source_root),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as error:
            raise build_release.BuildError(f"Невозможно дополнить AGENTS.md: {error}") from error
        return {**review, "status": "updated"}
    return {**review, "status": "unchanged"}


def ensure_project_gitignore(target_root: Path, source_root: Path) -> str:
    project_templates = source_root / ".tools" / "sdd-template-release" / "templates" / "project-root"
    source = project_templates / ".gitignore"
    destination = target_root / ".gitignore"
    if not destination.exists():
        if not source.is_file():
            raise build_release.BuildError(f"В чистом источнике отсутствует шаблон .gitignore: {source}")
        shutil.copy2(source, destination)
        return "created"

    try:
        content = destination.read_text(encoding="utf-8")
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
        destination.write_text(content + managed_block, encoding="utf-8", newline="\n")
    except OSError as error:
        raise build_release.BuildError(f"Невозможно дополнить существующий .gitignore: {error}") from error
    return "updated"


def consumer_project_structure(version: str) -> dict[str, object]:
    """Сформировать структуру проекта-потребителя, а не мета-репозитория."""
    framework_root = f".agents/sdd-template-{version}"
    return {
        "version": "1.0",
        "description": "Project structure for a consumer repository using SDD Framework.",
        "framework_root": framework_root,
        "folders": [
            {"name": "SDD Framework", "path": framework_root, "description": "Installed SDD Framework release.", "required": True},
            {"name": ".tasks", "path": ".tasks", "description": "Project tasks and PDD registry.", "required": True},
            {"name": ".issues", "path": ".issues", "description": "Project issues and incidents.", "required": False},
            {"name": ".source", "path": ".source", "description": "Project source materials.", "required": False},
            {"name": "docs", "path": "docs", "description": "Project documentation.", "required": False},
        ],
        "tools": {
            "registry_path": f"{framework_root}/.tools/registry.json",
            "preferred_invocation": f"{framework_root}/.tools/<tool> [args]",
        },
        "templates": {
            "task_template": f"{framework_root}/.manifest/taskmanifest.md",
            "pdd_manifest": f"{framework_root}/.manifest/pddmanifest.md",
        },
    }


def normalized_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def inspect_project_structure(target_root: Path, source_root: Path, version: str) -> dict[str, object]:
    """Проверить, не перенесена ли структура мета-репозитория в корень потребителя."""
    destination = target_root / ".project-structure.json"
    if not destination.exists():
        return {"status": "absent", "path": ".project-structure.json", "conflicts": [], "differences": [], "can_replace": False}
    if not destination.is_file():
        raise build_release.BuildError(f".project-structure.json существует, но не является файлом: {destination}")
    current = normalized_json(destination)
    if not isinstance(current, dict):
        return {
            "status": "conflict",
            "path": ".project-structure.json",
            "conflicts": ["корневой .project-structure.json не является корректным JSON-объектом"],
            "differences": [{"code": "invalid_json", "message": "Файл нельзя безопасно сравнить.", "actions": ["keep"]}],
            "can_replace": False,
        }
    template = source_root / ".tools" / "sdd-template-release" / "templates" / "project-structure.json"
    template_value = normalized_json(template) if template.is_file() else None
    folders = current.get("folders")
    folder_paths: set[str] = set()
    if isinstance(folders, list):
        for item in folders:
            if isinstance(item, dict):
                path_value = item.get("path")
                if isinstance(path_value, str):
                    folder_paths.add(path_value)
    meta_paths = {".manifest", ".requirements", ".tools"}
    missing_meta_paths = sorted(
        path for path in meta_paths
        if path in folder_paths and not (target_root / path).exists()
    )
    is_meta_template = template_value is not None and current == template_value
    if not is_meta_template and not missing_meta_paths:
        return {"status": "clear", "path": ".project-structure.json", "conflicts": [], "differences": [], "can_replace": False}
    if is_meta_template:
        message = (
            "корневой .project-structure.json является структурой мета-репозитория; "
            "для проекта-потребителя нужны пути через FRAMEWORK_ROOT"
        )
        code = "meta_project_structure"
    else:
        message = (
            "корневой .project-structure.json требует отсутствующие корневые каталоги: "
            + ", ".join(missing_meta_paths)
        )
        code = "missing_meta_paths"
    return {
        "status": "conflict",
        "path": ".project-structure.json",
        "conflicts": [message],
        "differences": [{
            "code": code,
            "message": message,
            "missing_paths": missing_meta_paths,
            "actions": ["replace", "keep"] if is_meta_template else ["keep"],
        }],
        "can_replace": is_meta_template,
    }


def ensure_project_structure(
    target_root: Path,
    source_root: Path,
    version: str,
    project_structure_action: str = "ask",
) -> dict[str, object]:
    review = inspect_project_structure(target_root, source_root, version)
    destination = target_root / ".project-structure.json"
    conflicts = review.get("conflicts")
    if not isinstance(conflicts, list):
        conflicts = []
    if conflicts:
        if project_structure_action == "ask":
            return review
        if project_structure_action == "keep":
            return {**review, "status": "kept"}
        if project_structure_action != "replace" or review.get("can_replace") is not True:
            raise build_release.BuildError(
                "Корневой .project-structure.json нельзя заменить автоматически: "
                "разрешена только безопасная замена известного шаблона мета-репозитория."
            )
    if review.get("status") == "absent" or project_structure_action == "replace":
        try:
            destination.write_text(
                json.dumps(consumer_project_structure(version), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
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
        destination = target_root / relative
        if destination.exists():
            if not destination.is_file():
                raise build_release.BuildError(f"Ожидался файл, но найден другой объект: {destination}")
            scaffold[relative.as_posix()] = "preserved"
            continue
        if not source.is_file():
            raise build_release.BuildError(f"В чистом источнике отсутствует шаблон корня проекта: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        scaffold[relative.as_posix()] = "created"

    docs_dir = target_root / "docs"
    requirements_dir = target_root / "docs" / "requirements"
    if requirements_dir.exists():
        if not requirements_dir.is_dir():
            raise build_release.BuildError(f"Путь docs/requirements существует, но не является каталогом: {requirements_dir}")
        result["docs_requirements"] = "preserved"
    else:
        if docs_dir.exists() and not docs_dir.is_dir():
            raise build_release.BuildError(f"Путь docs существует, но не является каталогом: {docs_dir}")
        requirements_dir.mkdir(parents=True)
        (requirements_dir / ".gitkeep").write_text("", encoding="utf-8", newline="\n")
        result["docs_requirements"] = "created"

    files = {
        ".editorconfig": None,
        ".gitattributes": None,
        "README.md": None,
    }
    defaults = {
        ".editorconfig": "root = true\n\n[*]\ncharset = utf-8\nend_of_line = lf\ninsert_final_newline = true\n",
        ".gitattributes": "* text=auto eol=lf\n",
        "README.md": "",
    }
    for name, source in files.items():
        destination = target_root / name
        if destination.exists():
            continue
        if source is not None:
            shutil.copy2(source, destination)
        else:
            destination.write_text(defaults[name], encoding="utf-8", newline="\n")
    return result


def cleanup_source_clone(target_root: Path, source_root: Path, cleanup_action: str) -> dict[str, str]:
    """Оставить или удалить только созданный клон внутри target-root/tmp."""
    if source_root.is_symlink():
        raise build_release.BuildError(f"Каталог клона не должен быть символьной ссылкой: {source_root}")
    tmp_root = (target_root / "tmp").resolve()
    source_root = source_root.resolve()
    if source_root.parent != tmp_root or not source_root.name.startswith("sdd-template-source-"):
        raise build_release.BuildError(
            "Очистка разрешена только для непосредственного клона "
            "<target-root>/tmp/sdd-template-source-X.Y.Z-<short-commit>."
        )
    if not source_root.is_dir():
        raise build_release.BuildError(f"Каталог клона не найден или является ссылкой: {source_root}")
    try:
        relative_path = source_root.relative_to(target_root).as_posix()
    except ValueError as error:
        raise build_release.BuildError("Каталог клона должен находиться внутри корня проекта.") from error
    if cleanup_action == "delete":
        shutil.rmtree(source_root)
        status = "deleted"
    else:
        status = "kept"
    return {
        "status": status,
        "path": relative_path,
        "scope": "source_clone_and_nested_staging",
    }


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
        "Повторите установку с --agents-action replace-legacy, "
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
        "Повторите установку с --project-structure-action replace или "
        "--project-structure-action keep после решения пользователя."
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    target_root = args.target_root.resolve()
    if args.cleanup_action is not None:
        if args.source_root is None or args.action is not None or args.version is not None or args.old_action != "ask" or args.write:
            raise build_release.BuildError(
                "Для --cleanup-action укажите только --source-root, --target-root и действие очистки."
            )
        cleanup = cleanup_source_clone(target_root, args.source_root, args.cleanup_action)
        print(json.dumps({"status": "cleanup_completed", "cleanup": cleanup}, ensure_ascii=False, indent=2))
        return 0

    if args.source_root is None or args.action is None:
        raise build_release.BuildError("Для установки необходимо указать --source-root и --action.")
    source_root = args.source_root.resolve()
    if source_root == target_root:
        raise build_release.BuildError("Исходная копия и проект-потребитель должны находиться в разных каталогах.")
    expected_tmp_root = target_root / "tmp"
    if source_root.parent != expected_tmp_root or not source_root.name.startswith("sdd-template-source-"):
        raise build_release.BuildError(
            "--source-root должен указывать на единственный клон "
            "<target-root>/tmp/sdd-template-source-X.Y.Z-<short-commit>."
        )

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

    current_version, current_path = installed_release(target_root)
    if args.action == "init" and current_version is not None:
        raise build_release.BuildError(
            f"Инициализация невозможна: уже установлен релиз {current_version}. Используйте update или use."
        )
    agents_review = inspect_agents_instructions(target_root, source_root, version)
    project_structure_review = inspect_project_structure(target_root, source_root, version)
    agents_conflicts = agents_review.get("conflicts")
    project_structure_conflicts = project_structure_review.get("conflicts")
    agents_requires_confirmation = (
        args.agents_action == "ask" and isinstance(agents_conflicts, list) and bool(agents_conflicts)
    )
    project_structure_requires_confirmation = (
        args.project_structure_action == "ask"
        and isinstance(project_structure_conflicts, list)
        and bool(project_structure_conflicts)
    )
    if args.write and (agents_requires_confirmation or project_structure_requires_confirmation):
        messages = []
        if agents_requires_confirmation:
            messages.append(agents_confirmation_message(agents_review))
        if project_structure_requires_confirmation:
            messages.append(project_structure_confirmation_message(project_structure_review))
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
            "next_action": {
                "type": "user_confirmation",
                "required": True,
                "message": confirmation_message,
            },
        }
        print(confirmation_message, file=sys.stderr)
        print(json.dumps(review_plan, ensure_ascii=False, indent=2))
        return 0
    if current_version == version:
        if not args.write:
            result = {
                "status": "unchanged",
                "action": args.action,
                "version": version,
                "install_path": install_path,
                "source_ref": source_ref,
                "write": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if current_path is None:
            raise build_release.BuildError("Установленная версия определена без пути релиза.")
        project_root = initialize_project_root(
            target_root,
            current_path,
            source_root,
            version,
            args.project_structure_action,
        )
        agents_result = ensure_agents_instructions(target_root, source_root, version, args.agents_action)
        conflicts = agents_result.get("conflicts")
        plan = {
            "status": "installed_pending_cleanup",
            "action": args.action,
            "current_version": current_version,
            "target_version": version,
            "source_ref": source_ref,
            "install_path": install_path,
            "write": True,
            "project_root": project_root,
            "agents": agents_result,
            "post_install_review": {
                "status": "required" if isinstance(conflicts, list) and conflicts else "clear",
                "conflicts": conflicts if isinstance(conflicts, list) else [],
            },
        }
        try:
            cleanup_path = source_root.relative_to(target_root).as_posix()
        except ValueError:
            cleanup_path = source_root.as_posix()
        cleanup_question = f"Удалить каталог {cleanup_path} после проверки? Ответьте «да» или «нет»."
        plan["cleanup"] = {
            "status": "awaiting_user_confirmation",
            "path": cleanup_path,
            "scope": "source_clone_and_nested_staging",
            "confirmation_required": True,
            "question": cleanup_question,
        }
        plan["next_action"] = {
            "type": "user_confirmation",
            "required": True,
            "message": cleanup_question,
        }
        print(
            f"Требуется подтверждение пользователя: удалить {cleanup_path} после проверки? Ответьте «да» или «нет».",
            file=sys.stderr,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.action == "update" and current_version is not None and version_key(current_version) > version_key(version):
        raise build_release.BuildError(
            f"Установлена более новая версия {current_version}; для возврата используйте действие use."
        )

    plan = {
        "status": "planned" if not args.write else "writing",
        "action": args.action,
        "current_version": current_version,
        "target_version": version,
        "source_ref": source_ref,
        "install_path": install_path,
        "old_action": args.old_action,
        "write": args.write,
    }
    if not args.write:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    if current_path is not None:
        if args.old_action == "ask":
            raise build_release.BuildError(
                f"Требуется подтверждение действия со старым релизом {current_version}: "
                "используйте --old-action keep, move или delete."
            )
        if args.old_action == "keep":
            plan["status"] = "kept"
            plan["write"] = False
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.old_action == "move":
            backup = free_backup_path(target_root, current_version or "unknown")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current_path), str(backup))
            plan["old_path"] = backup.relative_to(target_root).as_posix()
        elif args.old_action == "delete":
            shutil.rmtree(current_path)

    stage_root = source_root / "tmp" / f"sdd-template-build-{version}"
    resume_stage = stage_root.exists()
    result = build_release.build_release(
        source_root,
        target_root,
        source_ref=source_ref,
        write=True,
        stage_root=stage_root,
        resume_stage=resume_stage,
    )
    release_dir = result.get("release_dir")
    if not isinstance(release_dir, str):
        raise build_release.BuildError("Сборщик не вернул корректный путь релизного пакета.")
    package_dir = target_root / Path(install_path)
    if package_dir != target_root / Path(release_dir):
        raise build_release.BuildError("Путь установленного пакета не совпадает с install_path реестра.")
    plan["project_root"] = initialize_project_root(
        target_root,
        package_dir,
        source_root,
        version,
        args.project_structure_action,
    )
    agents_result = ensure_agents_instructions(target_root, source_root, version, args.agents_action)
    plan["agents"] = agents_result
    conflicts = agents_result.get("conflicts")
    plan["post_install_review"] = {
        "status": "required" if isinstance(conflicts, list) and conflicts else "clear",
        "conflicts": conflicts if isinstance(conflicts, list) else [],
    }
    plan.update(result)
    plan["status"] = "installed_pending_cleanup"
    try:
        cleanup_path = source_root.relative_to(target_root).as_posix()
    except ValueError:
        cleanup_path = source_root.as_posix()
    cleanup_question = f"Удалить каталог {cleanup_path} после проверки? Ответьте «да» или «нет»."
    plan["cleanup"] = {
        "status": "awaiting_user_confirmation",
        "path": cleanup_path,
        "scope": "source_clone_and_nested_staging",
        "confirmation_required": True,
        "question": cleanup_question,
    }
    plan["next_action"] = {
        "type": "user_confirmation",
        "required": True,
        "message": cleanup_question,
    }
    print(
        f"Требуется подтверждение пользователя: удалить {cleanup_path} после проверки? Ответьте «да» или «нет».",
        file=sys.stderr,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except build_release.BuildError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
