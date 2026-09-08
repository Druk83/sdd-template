#!/usr/bin/env python3
"""Сборка и проверка экспортного релиза SDD Framework."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGE_ID = "sdd-template"
SOURCE_REPOSITORY = "Druk83/sdd-template.git"
RELEASE_REGISTRY_NAME = "release-registry.json"
MIN_SUPPORTED_VERSION = (1, 9, 0)
VERSION_PATTERN = re.compile(r"^>\s*\*\*Версия:\*\*\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE)
VERSION_NUMBER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_PATTERN = re.compile(r"^sdd-template-([0-9]+\.[0-9]+\.[0-9]+)$")
DENIED_NAMES = {".git", ".runtime", "__pycache__"}
DENIED_SUFFIXES = {".pyc", ".pyo", ".env"}
PORTABLE_TOOLS = ("check-encoding", "pdd", "plantuml-render")
DIAGRAM_REFERENCE_FILES = (
    Path("example AL.plantuml"),
    Path("example BL.plantuml"),
    Path("example TL.plantuml"),
    Path("последовательность событий.plantuml"),
)
PACKAGE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_./\\-])\.(tools|manifest|requirements|approach)([/\\])"
)


class BuildError(RuntimeError):
    """Ошибка проверки или сборки релиза."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate an SDD Framework release package.")
    parser.add_argument("--root", type=Path, help="Корень мета-репозитория.")
    parser.add_argument("--write", action="store_true", help="Создать staging и релизный пакет.")
    parser.add_argument(
        "--resume-stage",
        action="store_true",
        help="Использовать существующую staging-папку после прерванной записи.",
    )
    parser.add_argument(
        "--source-ref",
        help="Указать выбранный commit или tag в метаданных релиза.",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        help="Корень проекта-потребителя, куда устанавливается пакет.",
    )
    return parser.parse_args()


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_version(root: Path) -> str:
    readme = root / "README.md"
    if not readme.is_file():
        raise BuildError(f"Не найден корневой README: {readme}")
    matches = VERSION_PATTERN.findall(readme.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise BuildError("В корневом README должна быть ровно одна строка версии.")
    version = matches[0]
    if tuple(int(part) for part in version.split(".")) < MIN_SUPPORTED_VERSION:
        raise BuildError("Версия SDD Framework ниже 1.9.0 не поддерживается сборщиком.")
    return version


def read_release_registry(root: Path) -> dict[str, object]:
    registry_path = root / RELEASE_REGISTRY_NAME
    if not registry_path.is_file():
        raise BuildError(f"Не найден официальный реестр релизов: {registry_path}")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Невозможно прочитать реестр релизов: {error}") from error
    if not isinstance(registry, dict) or registry.get("package_id") != PACKAGE_ID:
        raise BuildError("Реестр релизов имеет неверный package_id.")
    if registry.get("source_repository") != SOURCE_REPOSITORY:
        raise BuildError("Реестр релизов имеет неверный источник.")
    minimum = registry.get("minimum_supported_version")
    if minimum != ".".join(str(part) for part in MIN_SUPPORTED_VERSION):
        raise BuildError("Реестр релизов имеет неверную минимальную поддерживаемую версию.")
    releases = registry.get("releases")
    if not isinstance(releases, list) or not releases:
        raise BuildError("В реестре релизов отсутствует непустой список releases.")
    default_version = registry.get("default_version")
    if not isinstance(default_version, str) or not VERSION_NUMBER_PATTERN.fullmatch(default_version):
        raise BuildError("В реестре отсутствует корректная default_version.")
    versions: set[str] = set()
    for release in releases:
        if not isinstance(release, dict):
            raise BuildError("Каждая запись реестра релизов должна быть объектом.")
        version = release.get("version")
        ref = release.get("ref")
        ref_type = release.get("ref_type")
        status = release.get("status")
        if not isinstance(version, str) or not VERSION_NUMBER_PATTERN.fullmatch(version):
            raise BuildError("В реестре обнаружена некорректная версия релиза.")
        if version in versions:
            raise BuildError(f"В реестре обнаружена дублирующаяся версия: {version}")
        versions.add(version)
        if tuple(int(part) for part in version.split(".")) < MIN_SUPPORTED_VERSION and status == "supported":
            raise BuildError(f"Версия {version} не может иметь статус supported.")
        if not isinstance(ref, str) or not ref or ref_type not in {"commit", "tag"}:
            raise BuildError("В реестре обнаружена неполная запись релиза.")
        commit = release.get("commit")
        if commit is not None and (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)):
            raise BuildError(f"В реестре указан некорректный commit для версии {version}.")
        if ref_type == "commit" and commit != ref:
            raise BuildError(f"Для записи commit реестр должен содержать тот же hash в поле commit: {version}")
        install_path = release.get("install_path")
        expected_path = f".agents/{release_name(version)}"
        if not isinstance(install_path, str) or install_path.replace("\\", "/") != expected_path:
            raise BuildError(f"В реестре указан некорректный install_path для версии {version}.")
        if ref_type == "commit" and not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise BuildError(f"В реестре указан некорректный commit для версии {version}.")
        if status not in {"supported", "unsupported"}:
            raise BuildError("В реестре обнаружен некорректный статус релиза.")
    default_entries = [
        release for release in releases
        if isinstance(release, dict) and release.get("version") == default_version
    ]
    if len(default_entries) != 1 or default_entries[0].get("status") != "supported":
        raise BuildError("default_version должна указывать на единственный поддерживаемый релиз.")
    return registry


def registry_releases(registry: dict[str, object]) -> list[dict[str, object]]:
    releases = registry.get("releases")
    if not isinstance(releases, list):
        raise BuildError("В реестре релизов отсутствует список releases.")
    entries = [release for release in releases if isinstance(release, dict)]
    if len(entries) != len(releases):
        raise BuildError("Каждая запись реестра релизов должна быть объектом.")
    return entries


def ensure_version_registered(registry: dict[str, object], version: str) -> None:
    releases = registry_releases(registry)
    matching = [
        release for release in releases
        if release.get("version") == version
    ]
    if len(matching) != 1 or matching[0].get("status") != "supported":
        raise BuildError(f"Версия {version} отсутствует среди поддерживаемых релизов.")


def release_entry(registry: dict[str, object], version: str) -> dict[str, object]:
    releases = registry_releases(registry)
    matching = [
        release for release in releases
        if release.get("version") == version
    ]
    if len(matching) != 1 or matching[0].get("status") != "supported":
        raise BuildError(f"Версия {version} отсутствует среди поддерживаемых релизов.")
    return matching[0]


def release_name(version: str) -> str:
    return f"{PACKAGE_ID}-{version}"


def direct_release_dirs(agents_dir: Path) -> list[Path]:
    if not agents_dir.is_dir():
        return []
    return sorted(
        child
        for child in agents_dir.iterdir()
        if child.is_dir() and RELEASE_PATTERN.fullmatch(child.name)
    )


def conflicting_dirs(agents_dir: Path, expected_name: str) -> list[Path]:
    if not agents_dir.is_dir():
        return []
    return sorted(
        child
        for child in agents_dir.iterdir()
        if child.is_dir() and child.name.startswith("sdd") and child.name != expected_name
    )


def ensure_source_state(root: Path, version: str) -> tuple[Path, list[Path]]:
    agents_dir = root / ".agents"
    expected = agents_dir / release_name(version)
    existing = direct_release_dirs(agents_dir)
    conflicts = conflicting_dirs(agents_dir, expected.name)
    if conflicts:
        names = ", ".join(path.name for path in conflicts)
        raise BuildError(f"В .agents обнаружены старые или неизвестные каталоги: {names}")
    if len(existing) > 1:
        names = ", ".join(path.name for path in existing)
        raise BuildError(f"В .agents должно быть не более одной папки SDD Framework: {names}")
    if existing and existing[0] != expected:
        raise BuildError(
            f"Существует старый релиз {existing[0].name}. "
            "Удалите или переместите его после подтверждения пользователя."
        )
    if expected.exists():
        raise BuildError(f"Целевая папка уже существует и не будет перезаписана: {expected}")
    return expected, existing


def is_denied(relative_path: Path, deny_tests: bool = False) -> bool:
    parts = set(relative_path.parts)
    if parts.intersection(DENIED_NAMES):
        return True
    if deny_tests and "tests" in parts:
        return True
    if relative_path.name in {".env", "settings.local.json"}:
        return True
    return relative_path.suffix in DENIED_SUFFIXES


def copy_tree(source: Path, target: Path, deny_tests: bool = False) -> None:
    if not source.is_dir():
        raise BuildError(f"Не найден обязательный каталог: {source}")
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if is_denied(relative, deny_tests):
            continue
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise BuildError(f"Не найден обязательный файл: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def render_template(source: Path, target: Path, values: dict[str, str]) -> None:
    content = source.read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def qualify_package_paths(content: str, release_dir: str) -> str:
    """Добавить путь установленного пакета к путям фреймворка в кодовых фрагментах."""
    def replace_code_fragment(match: re.Match[str]) -> str:
        fragment = match.group(0)

        def replace_path(path_match: re.Match[str]) -> str:
            separator = path_match.group(2)
            prefix = f".agents{separator}{release_dir}{separator}"
            return f"{prefix}.{path_match.group(1)}{separator}"

        return PACKAGE_PATH_PATTERN.sub(replace_path, fragment)

    code_fragment_pattern = re.compile(r"```[\s\S]*?```|`[^`\n]*`")
    return code_fragment_pattern.sub(replace_code_fragment, content)


def qualify_package_markdown_paths(stage: Path, release_dir: str) -> None:
    for path in stage.rglob("*.md"):
        content = path.read_text(encoding="utf-8")
        path.write_text(qualify_package_paths(content, release_dir), encoding="utf-8", newline="\n")


def refresh_agent_logic_manifest(stage: Path) -> None:
    """Обновить контрольные суммы полного встроенного инструмента после сборки."""
    tool_dir = stage / ".tools" / "agent-logic"
    manifest_path = tool_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Невозможно прочитать manifest agent-logic: {error}") from error
    files = manifest.get("files_sha256")
    if not isinstance(files, dict):
        raise BuildError("В manifest agent-logic отсутствует files_sha256.")
    for relative in files:
        path = tool_dir / Path(relative)
        if not path.is_file():
            raise BuildError(f"Файл из manifest agent-logic отсутствует в пакете: {relative}")
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def git_value(root: Path, args: list[str], fallback: str) -> str:
    command = ["git", "-C", str(root), "-c", f"safe.directory={root}", *args]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return result.stdout.strip() or fallback


def source_metadata(root: Path, source_ref: str | None = None) -> dict[str, object]:
    dirty = bool(git_value(root, ["status", "--porcelain", "--untracked-files=no"], ""))
    if not source_ref:
        source_ref = git_value(root, ["symbolic-ref", "--short", "HEAD"], "")
    if not source_ref:
        source_ref = git_value(root, ["describe", "--tags", "--exact-match", "HEAD"], "")
    if not source_ref:
        source_ref = "detached"
    return {
        "source_repo": SOURCE_REPOSITORY,
        "source_ref": source_ref,
        "source_commit": git_value(root, ["rev-parse", "HEAD"], "unknown"),
        "source_dirty": dirty,
    }


def portable_registry(root: Path, version: str) -> list[dict[str, object]]:
    registry_path = root / ".tools" / "registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Невозможно прочитать registry инструментов: {error}") from error
    if not isinstance(registry, list):
        raise BuildError("Корневой registry инструментов должен быть JSON-массивом.")
    package_prefix = f".agents/{release_name(version)}/"
    portable = []
    for entry in registry:
        if entry.get("name") == "sdd-template-release":
            continue
        rewritten = dict(entry)
        for key in ("path", "entry", "entry_win", "entry_unix", "instructions", "install_manifest"):
            value = rewritten.get(key)
            if isinstance(value, str):
                rewritten[key] = value.replace(".tools/", f"{package_prefix}.tools/")
                if entry.get("name") == "check-encoding":
                    rewritten[key] = re.sub(
                        r"(?<![A-Za-z0-9_./\\-])(\.manifest|\.requirements)(?=(?:\s|$))",
                        lambda match: f"{package_prefix}{match.group(1)}",
                        rewritten[key],
                    )
        portable.append(rewritten)
    return portable


def file_records(stage: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        relative = path.relative_to(stage).as_posix()
        if relative == "release-manifest.json":
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return records


def validate_stage(
    stage: Path,
    version: str,
    source_root: Path | None = None,
    source_ref: str | None = None,
) -> None:
    manifest_path = stage / "release-manifest.json"
    if not manifest_path.is_file():
        raise BuildError(f"В staging отсутствует release-manifest.json: {stage}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Невозможно прочитать release-manifest.json: {error}") from error
    if manifest.get("package_id") != PACKAGE_ID or manifest.get("version") != version:
        raise BuildError("Версия или package_id существующей staging-папки не совпадают с исходными.")
    expected_release_dir = f".agents/{release_name(version)}"
    if manifest.get("release_dir") != expected_release_dir:
        raise BuildError("Существующая staging-папка содержит неверный путь релиза.")
    if source_root is not None:
        expected_commit = git_value(source_root, ["rev-parse", "HEAD"], "")
        if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
            raise BuildError("Невозможно проверить commit исходной копии для продолжения staging.")
        if manifest.get("source_commit") != expected_commit:
            raise BuildError("Staging создана из другого commit и не может быть продолжена.")
    if source_ref is not None and manifest.get("source_ref") != source_ref:
        raise BuildError("Staging создана из другого ref и не может быть продолжена.")
    if not (stage / "README.md").is_file() or not (stage / "sdd-template.instructions.md").is_file():
        raise BuildError("В существующей staging-папке отсутствует обязательный README или инструкция.")


def build_stage(root: Path, version: str, stage: Path, source_ref: str | None = None) -> None:
    templates = root / ".tools" / "sdd-template-release" / "templates"
    stage.mkdir(parents=True, exist_ok=False)
    render_template(
        templates / "README.md",
        stage / "README.md",
        {"VERSION": version, "RELEASE_DIR": release_name(version)},
    )
    copy_file(templates / "package.gitignore", stage / ".gitignore")
    copy_file(root / RELEASE_REGISTRY_NAME, stage / RELEASE_REGISTRY_NAME)
    render_template(
        templates / "project-structure.json",
        stage / ".project-structure.json",
        {"VERSION": version, "RELEASE_DIR": release_name(version)},
    )
    copy_file(templates / "chatlog.gitkeep", stage / ".chatlog" / ".gitkeep")
    render_template(
        templates / "sdd-template.instructions.md",
        stage / "sdd-template.instructions.md",
        {
            "VERSION": version,
            "MIN_SUPPORTED_VERSION": ".".join(str(part) for part in MIN_SUPPORTED_VERSION),
        },
    )
    for directory in (".manifest", ".requirements", ".approach"):
        copy_tree(root / directory, stage / directory)
    for relative in DIAGRAM_REFERENCE_FILES:
        copy_file(root / ".diagrams" / relative, stage / ".diagrams" / relative)
    render_template(
        templates / "tools-README.md",
        stage / ".tools" / "README.md",
        {"VERSION": version, "RELEASE_DIR": release_name(version)},
    )
    (stage / ".tools" / "registry.json").write_text(
        json.dumps(portable_registry(root, version), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for tool_name in PORTABLE_TOOLS:
        copy_tree(root / ".tools" / tool_name, stage / ".tools" / tool_name, deny_tests=True)
    agent_logic_source = root / ".tools" / "agent-logic"
    copy_tree(agent_logic_source, stage / ".tools" / "agent-logic", deny_tests=True)
    qualify_package_markdown_paths(stage, release_name(version))
    refresh_agent_logic_manifest(stage)
    manifest = {
        "schema_version": "1.0",
        "package_id": PACKAGE_ID,
        "version": version,
        "release_dir": f".agents/{release_name(version)}",
        **source_metadata(root, source_ref),
        "export_profile": "sdd-framework-consumer",
        "instructions": "sdd-template.instructions.md",
        "readme": "README.md",
        "files": file_records(stage),
    }
    (stage / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def report(output_root: Path, version: str, target: Path, stage: Path, write: bool) -> dict[str, object]:
    try:
        staging_dir = stage.relative_to(output_root).as_posix()
    except ValueError:
        staging_dir = f"<source-root>/{stage.name}"
    return {
        "status": "written" if write else "dry-run",
        "package_id": PACKAGE_ID,
        "version": version,
        "release_dir": target.relative_to(output_root).as_posix(),
        "staging_dir": staging_dir,
        "source_repo": SOURCE_REPOSITORY,
        "write": write,
    }


def build_release(
    root: Path,
    output_root: Path,
    source_ref: str | None = None,
    write: bool = False,
    resume_stage: bool = False,
    stage_root: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    output_root = output_root.resolve()
    registry = read_release_registry(root)
    version = read_version(root)
    ensure_version_registered(registry, version)
    target, _ = ensure_source_state(output_root, version)
    stage = (stage_root or output_root / "tmp" / f"sdd-template-build-{version}").resolve()
    if stage.exists() and not resume_stage:
        raise BuildError(
            f"Временная папка уже существует и не будет перезаписана: {stage}. "
            "Если это staging прерванной установки, используйте --resume-stage."
        )
    if write:
        if resume_stage:
            validate_stage(stage, version, source_root=root, source_ref=source_ref)
        else:
            build_stage(root, version, stage, source_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(stage, target)
        except OSError as error:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            raise BuildError(f"Невозможно записать релизный пакет в {target}: {error}") from error
    return report(output_root, version, target, stage, write)


def main() -> int:
    args = parse_args()
    root = (args.root or repository_root()).resolve()
    output_root = (args.target_root or root).resolve()
    result = build_release(
        root,
        output_root,
        source_ref=args.source_ref,
        write=args.write,
        resume_stage=args.resume_stage,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
