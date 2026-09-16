"""Локальная проверка сборки кандидата релиза SDD Framework."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from build_release import (
    BuildError,
    build_release,
    ensure_version_registered,
    git_value,
    release_entry,
    registry_releases,
    read_release_registry,
    read_version,
    repository_root,
    validate_stage,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and validate a release candidate in a temporary directory."
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Корень мета-репозитория; по умолчанию определяется по расположению инструмента.",
    )
    parser.add_argument(
        "--published",
        action="store_true",
        help="Проверить опубликованные refs и соответствие текущего commit релизу.",
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Проверить локальный release candidate, который ещё не опубликован.",
    )
    return parser.parse_args()


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Невозможно прочитать JSON-файл {path}: {error}") from error


def validate_package(package: Path, version: str, allow_candidate: bool = False) -> int:
    validate_stage(package, version)
    manifest = read_json(package / "release-manifest.json")
    if not isinstance(manifest, dict):
        raise BuildError("release-manifest.json должен содержать JSON-объект.")

    records = manifest.get("files")
    if not isinstance(records, list):
        raise BuildError("В release-manifest.json отсутствует массив files.")

    expected: dict[str, tuple[int, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise BuildError("Каждая запись files должна быть JSON-объектом.")
        relative = record.get("path")
        size = record.get("size")
        sha256 = record.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(size, int)
            or not isinstance(sha256, str)
            or not relative
            or relative in expected
        ):
            raise BuildError("В release-manifest.json обнаружена некорректная или повторная запись files.")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise BuildError(f"Недопустимый путь в release-manifest.json: {relative}")
        expected[relative] = (size, sha256)

    actual: dict[str, Path] = {}
    for path in package.rglob("*"):
        if not path.is_file() or path.name == "release-manifest.json":
            continue
        relative = path.relative_to(package).as_posix()
        actual[relative] = path

    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise BuildError(
            "Состав пакета не совпадает с release-manifest.json: "
            f"missing={missing}, unexpected={unexpected}."
        )

    for relative, path in actual.items():
        expected_size, expected_sha256 = expected[relative]
        data = path.read_bytes()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or actual_sha256 != expected_sha256:
            raise BuildError(f"Проверка хеша или размера не пройдена: {relative}")

    registry = read_release_registry(package)
    selected = release_entry(registry, version, allow_candidate=True) if allow_candidate else None
    if registry.get("default_version") != version and not (
        selected is not None and selected.get("status") == "candidate"
    ):
        raise BuildError("Копия release-registry.json в пакете указывает другую default_version.")
    selected = selected or release_entry(registry, version)
    if selected.get("install_path") != f".agents/sdd-template-{version}":
        raise BuildError(f"Для релиза {version} указан неверный install_path.")

    required_files = (
        "README.md",
        "sdd-template.instructions.md",
        "release-registry.json",
        ".project-structure.json",
        ".tools/registry.json",
        ".tools/pdd/manifest-validator.py",
    )
    missing_required = [relative for relative in required_files if not (package / relative).is_file()]
    if missing_required:
        raise BuildError(f"В релизном пакете отсутствуют обязательные файлы: {missing_required}")

    return len(actual)


def validate_published_registry(root: Path, registry: dict[str, object], version: str) -> None:
    """Проверить, что поддерживаемые релизы опубликованы на неизменяемых refs."""
    head = git_value(root, ["rev-parse", "HEAD"], "")
    if not head:
        raise BuildError("Невозможно определить commit текущего релиза.")

    for release in registry_releases(registry):
        if release.get("status") != "supported":
            continue
        release_version = release.get("version")
        ref_type = release.get("ref_type")
        ref = release.get("ref")
        if not isinstance(release_version, str) or not isinstance(ref, str):
            raise BuildError("В supported-записи отсутствуют version или ref.")

        if ref_type == "tag":
            tag = release.get("tag")
            if tag != ref:
                raise BuildError(f"Для релиза {release_version} поля tag и ref должны совпадать.")
            resolved = git_value(
                root,
                ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
                "",
            )
        else:
            resolved = git_value(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"], "")

        if not resolved:
            raise BuildError(
                f"Поддерживаемый релиз {release_version} ссылается на недоступный {ref_type}: {ref}."
            )
        registered_commit = release.get("commit")
        if registered_commit is not None and registered_commit != resolved:
            raise BuildError(f"Поле commit релиза {release_version} не совпадает с разрешённым ref.")
        if release_version == version and resolved != head:
            raise BuildError(
                f"Текущий commit {head} не совпадает с ref релиза {version}: {ref} -> {resolved}."
            )


def main() -> int:
    args = parse_args()
    root = (args.root or repository_root()).resolve()
    version = read_version(root)
    registry = read_release_registry(root)
    ensure_version_registered(registry, version, allow_candidate=args.candidate)
    if args.published:
        validate_published_registry(root, registry, version)

    with tempfile.TemporaryDirectory(prefix="sdd-template-release-verify-") as temporary:
        workspace = Path(temporary)
        output_root = workspace / "output"
        result = build_release(
            root,
            output_root,
            write=True,
            stage_root=workspace / "staging",
            allow_candidate=args.candidate,
        )
        package = output_root / ".agents" / f"sdd-template-{version}"
        file_count = validate_package(package, version, allow_candidate=args.candidate)
        manifest = read_json(package / "release-manifest.json")
        source_dirty = manifest.get("source_dirty") if isinstance(manifest, dict) else None

    print(
        json.dumps(
            {
                "status": "pass",
                "version": version,
                "files": file_count,
                "source_dirty": source_dirty,
                "temporary_build": True,
                "build": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
