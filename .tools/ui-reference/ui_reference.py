"""Валидация UI-пакетов и безопасная миграция legacy reference artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


SOURCE_URL = "https://github.com/Druk83/ui-patterns.git"
VALID_STATUSES = {
    "proposed",
    "confirmed",
    "rejected",
    "gap",
    "superseded",
    "not_applicable",
}
PACKAGE_REQUIRED_FILES = (
    "README.md",
    "манифест-спецификации-интерфейса.json",
    "пул-экранов.json",
)
PACKAGE_REQUIRED_DIRECTORIES = ("screens", "references")
APPLIED_REFERENCE_STATUSES = {"candidate", "not_selectable"}
REFERENCE_ALLOWED_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".ttf", ".otf"}


class UiReferenceError(RuntimeError):
    """Ошибка контракта UI или безопасной миграции."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiReferenceError(f"Невозможно прочитать JSON {path}: {error}") from error


def relative_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise UiReferenceError(f"Каталог не найден: {root}")
    return sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())


def inventory(root: Path) -> dict[str, Any]:
    entries = []
    for path in relative_files(root):
        relative = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "type": "file",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    fingerprint_data = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "source": str(root),
        "entries": entries,
        "file_count": len(entries),
        "fingerprint": hashlib.sha256(fingerprint_data).hexdigest(),
    }


def safe_roots(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise UiReferenceError("Источник и target должны быть независимыми каталогами.")


def migrate(source: Path, target: Path, write: bool) -> dict[str, Any]:
    safe_roots(source, target)
    source_inventory = inventory(source)
    conflicts: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []

    for entry in source_inventory["entries"]:
        relative = Path(str(entry["path"]))
        destination = target / relative
        if destination.exists():
            if not destination.is_file() or sha256_file(destination) != entry["sha256"]:
                conflicts.append(relative.as_posix())
            else:
                skipped.append(relative.as_posix())
            continue
        copied.append(relative.as_posix())
        if write:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)

    return {
        "operation": "migrate",
        "status": "conflicts" if conflicts else ("written" if write else "dry-run"),
        "source": str(source.resolve()),
        "target": str(target.resolve()),
        "source_fingerprint": source_inventory["fingerprint"],
        "source_file_count": source_inventory["file_count"],
        "copied": copied,
        "skipped_identical": skipped,
        "conflicts": conflicts,
        "deletion_performed": False,
        "overwrite_performed": False,
    }


def require_string(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} должен быть непустой строкой")


def validate_pool(path: Path, errors: list[str]) -> None:
    data = read_json(path)
    if not isinstance(data, dict):
        errors.append("screen pool должен быть JSON-объектом")
        return
    if data.get("schema_version") not in {"1", "1.0", 1}:
        errors.append("screen pool содержит неподдерживаемую schema_version")
    screens = data.get("screens")
    if not isinstance(screens, list):
        errors.append("screen pool должен содержать массив screens")
        return
    ids: set[str] = set()
    required = (
        "screen_id",
        "title",
        "screen_type",
        "purpose",
        "user_roles",
        "user_task",
        "pattern_candidates",
        "states",
        "transitions",
        "viewport_candidates",
        "source_refs",
        "status",
    )
    for index, screen in enumerate(screens):
        prefix = f"screens[{index}]"
        if not isinstance(screen, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        for field in required:
            if field not in screen:
                errors.append(f"{prefix}.{field} отсутствует")
        screen_id = screen.get("screen_id")
        if isinstance(screen_id, str):
            if screen_id in ids:
                errors.append(f"Дублирующийся screen_id: {screen_id}")
            ids.add(screen_id)
        if screen.get("status") not in VALID_STATUSES:
            errors.append(f"{prefix}.status имеет недопустимое значение: {screen.get('status')}")


def validate_manifest(path: Path, errors: list[str]) -> None:
    data = read_json(path)
    if not isinstance(data, dict):
        errors.append("UI manifest должен быть JSON-объектом")
        return
    if data.get("schema_version") not in {"1", "1.0", 1}:
        errors.append("UI manifest содержит неподдерживаемую schema_version")
    require_string(data.get("template_set_version"), "template_set_version", errors)
    require_string(data.get("revision"), "revision", errors)
    require_string(data.get("contract_version"), "contract_version", errors)
    if data.get("source_url") != SOURCE_URL:
        errors.append("source_url не совпадает с официальным URL ui-patterns")
    if data.get("status") not in VALID_STATUSES:
        errors.append("UI manifest содержит недопустимый status")


def validate_reference_set(root: Path, errors: list[str]) -> None:
    manifest_path = root / "screen-manifest.json"
    if not manifest_path.is_file():
        errors.append("В reference-set отсутствует screen-manifest.json")
        return
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("screens"), list):
        errors.append("screen-manifest.json должен содержать массив screens")
        return
    root_resolved = root.resolve()
    for index, screen in enumerate(manifest["screens"]):
        if not isinstance(screen, dict):
            errors.append(f"screen-manifest.screens[{index}] должен быть объектом")
            continue
        file_value = screen.get("file")
        if not isinstance(file_value, str) or not file_value:
            errors.append(f"screen-manifest.screens[{index}].file отсутствует")
            continue
        file_path = (root / file_value).resolve()
        if root_resolved not in file_path.parents or not file_path.is_file():
            errors.append(f"Отсутствует screen artifact: {file_value}")
        viewport = screen.get("viewport")
        if (
            not isinstance(viewport, dict)
            or not isinstance(viewport.get("width"), int)
            or not isinstance(viewport.get("height"), int)
        ):
            errors.append(f"Некорректный viewport для screen-manifest.screens[{index}]")

    viewport_dirs = [path for path in root.iterdir() if path.is_dir()]
    if not viewport_dirs:
        errors.append("reference-set не содержит viewport/orientation каталогов")
    for viewport_dir in viewport_dirs:
        for required in ("index.html", "reference-manifest.json", "README.md"):
            if not (viewport_dir / required).is_file():
                errors.append(f"{viewport_dir.name}: отсутствует {required}")


def _safe_relative_path(value: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} должен быть непустым относительным путём")
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        errors.append(f"{field} выходит за границы UI-пакета: {value}")
        return None
    return candidate


def _path_inside(root: Path, relative: Path) -> Path | None:
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        return None
    return target


def _id_value(value: Any, field: str, errors: list[str]) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        for key in ("id", "pattern_id", "template_id", "screen_id"):
            identifier = value.get(key)
            if isinstance(identifier, str) and identifier.strip():
                return identifier
    errors.append(f"{field} должен содержать идентификатор")
    return None


def _reference_status(value: Any) -> str | None:
    return value.get("status") if isinstance(value, dict) and isinstance(value.get("status"), str) else None


def _candidate_map(screens: list[Any], key: str, errors: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, screen in enumerate(screens):
        if not isinstance(screen, dict):
            continue
        candidates = screen.get(key, [])
        if not isinstance(candidates, list):
            errors.append(f"screens[{index}].{key} должен быть массивом")
            continue
        for candidate_index, candidate in enumerate(candidates):
            identifier = _id_value(candidate, f"screens[{index}].{key}[{candidate_index}]", errors)
            if identifier is None:
                continue
            if identifier in result:
                errors.append(f"Дублирующийся {key} identifier: {identifier}")
            result[identifier] = _reference_status(candidate) or "candidate"
    return result


def _validate_reference_ids(
    values: Any,
    field: str,
    candidates: dict[str, str],
    errors: list[str],
) -> None:
    if not isinstance(values, list):
        errors.append(f"{field} должен быть массивом")
        return
    for index, value in enumerate(values):
        identifier = _id_value(value, f"{field}[{index}]", errors)
        if identifier is None:
            continue
        status = _reference_status(value) or candidates.get(identifier)
        if identifier not in candidates:
            errors.append(f"{field}[{index}] содержит неизвестный identifier: {identifier}")
        if status in APPLIED_REFERENCE_STATUSES:
            errors.append(f"{field}[{index}] с status={status} нельзя применять как выбранный reference")


def _validate_traceability(value: Any, screen_ids: set[str], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("traceability должен быть массивом")
        return
    for index, record in enumerate(value):
        prefix = f"traceability[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        screen_id = record.get("screen_id")
        if not isinstance(screen_id, str) or screen_id not in screen_ids:
            errors.append(f"{prefix}.screen_id не связан с UI-экраном")
        for field in ("requirement_refs", "scenario_refs", "acceptance_criteria"):
            refs = record.get(field)
            if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item.strip() for item in refs):
                errors.append(f"{prefix}.{field} должен содержать непустые ссылки")


def _validate_gaps(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("gaps должен быть массивом")
        return
    for index, gap in enumerate(value):
        prefix = f"gaps[{index}]"
        if not isinstance(gap, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        for field in ("gap_id", "owner", "blocking_condition"):
            if not isinstance(gap.get(field), str) or not gap[field].strip():
                errors.append(f"{prefix}.{field} обязателен")
        if gap.get("status") in {"closed", "resolved"} and not isinstance(gap.get("closure_evidence"), str):
            errors.append(f"{prefix}.closure_evidence обязателен для закрытого GAP")


def validate_package(root: Path, errors: list[str]) -> dict[str, Any]:
    """Проверить полный UI-пакет и его cross-artifact traceability."""
    if not root.is_dir() or root.is_symlink():
        errors.append(f"UI-пакет не найден или является ссылкой: {root}")
        return {"package": str(root), "status": "fail"}
    for required_file in PACKAGE_REQUIRED_FILES:
        if not (root / required_file).is_file():
            errors.append(f"В UI-пакете отсутствует обязательный файл: {required_file}")
    for required_directory in PACKAGE_REQUIRED_DIRECTORIES:
        if not (root / required_directory).is_dir() or (root / required_directory).is_symlink():
            errors.append(f"В UI-пакете отсутствует обязательный каталог: {required_directory}")
    manifest_path = root / "манифест-спецификации-интерфейса.json"
    pool_path = root / "пул-экранов.json"
    if not manifest_path.is_file() or not pool_path.is_file():
        return {"package": str(root), "status": "fail"}
    manifest = read_json(manifest_path)
    pool = read_json(pool_path)
    if not isinstance(manifest, dict):
        errors.append("UI manifest должен быть JSON-объектом")
        return {"package": str(root), "status": "fail"}
    if not isinstance(pool, dict):
        errors.append("screen pool должен быть JSON-объектом")
        return {"package": str(root), "status": "fail"}
    validate_manifest(manifest_path, errors)
    validate_pool(pool_path, errors)
    screens_value = pool.get("screens")
    screens: list[Any] = screens_value if isinstance(screens_value, list) else []
    pool_screen_ids = {
        screen.get("screen_id") for screen in screens
        if isinstance(screen, dict) and isinstance(screen.get("screen_id"), str)
    }
    pattern_candidates = _candidate_map(screens, "pattern_candidates", errors)
    template_candidates = _candidate_map(screens, "template_candidates", errors)
    manifest_screens = manifest.get("screens")
    if not isinstance(manifest_screens, list):
        errors.append("UI manifest должен содержать массив screens")
        manifest_screens = []
    manifest_screen_ids: set[str] = set()
    for index, screen in enumerate(manifest_screens):
        prefix = f"manifest.screens[{index}]"
        if not isinstance(screen, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        screen_id = screen.get("screen_id")
        if not isinstance(screen_id, str) or not screen_id.strip():
            errors.append(f"{prefix}.screen_id обязателен")
            continue
        if screen_id in manifest_screen_ids:
            errors.append(f"Дублирующийся manifest screen_id: {screen_id}")
        manifest_screen_ids.add(screen_id)
        if screen_id not in pool_screen_ids:
            errors.append(f"{prefix}.screen_id отсутствует в screen pool: {screen_id}")
        specification_path = _safe_relative_path(screen.get("specification"), f"{prefix}.specification", errors)
        if specification_path is not None:
            if specification_path.parts[:1] != ("screens",):
                errors.append(f"{prefix}.specification должен находиться в screens/")
            elif _path_inside(root, specification_path) is None or not (root / specification_path).is_file():
                errors.append(f"Отсутствует screen specification: {specification_path.as_posix()}")
        if screen.get("status") not in VALID_STATUSES:
            errors.append(f"{prefix}.status имеет недопустимое значение: {screen.get('status')}")
        _validate_reference_ids(screen.get("pattern_refs"), f"{prefix}.pattern_refs", pattern_candidates, errors)
        _validate_reference_ids(screen.get("template_refs"), f"{prefix}.template_refs", template_candidates, errors)
        artifacts = screen.get("reference_artifacts", [])
        if not isinstance(artifacts, list):
            errors.append(f"{prefix}.reference_artifacts должен быть массивом")
        else:
            for artifact_index, artifact in enumerate(artifacts):
                artifact_path = artifact.get("path") if isinstance(artifact, dict) else artifact
                artifact_relative = _safe_relative_path(artifact_path, f"{prefix}.reference_artifacts[{artifact_index}]", errors)
                if artifact_relative is not None:
                    if artifact_relative.parts[:1] != ("references",) or _path_inside(root, artifact_relative) is None or not (root / artifact_relative).is_file():
                        errors.append(f"Некорректный или отсутствующий reference artifact: {artifact_relative.as_posix()}")
    if manifest.get("screen_pool") != "пул-экранов.json":
        errors.append("UI manifest должен ссылаться на пул-экранов.json")
    _validate_traceability(manifest.get("traceability"), manifest_screen_ids, errors)
    _validate_gaps(manifest.get("gaps"), errors)
    reference_sets = manifest.get("reference_sets")
    if not isinstance(reference_sets, list):
        errors.append("reference_sets должен быть массивом")
    else:
        for index, reference_set in enumerate(reference_sets):
            prefix = f"reference_sets[{index}]"
            if not isinstance(reference_set, dict):
                errors.append(f"{prefix} должен быть объектом")
                continue
            reference_set_path = _safe_relative_path(reference_set.get("path"), f"{prefix}.path", errors)
            if reference_set_path is None:
                continue
            if reference_set_path.parts[:1] != ("references",) or _path_inside(root, reference_set_path) is None or not (root / reference_set_path).is_dir():
                errors.append(f"Некорректный reference set: {reference_set_path.as_posix()}")
            else:
                validate_reference_set(root / reference_set_path, errors)
    return {
        "package": str(root),
        "status": "pass" if not errors else "fail",
        "screen_count": len(manifest_screen_ids),
        "reference_set_count": len(reference_sets) if isinstance(reference_sets, list) else 0,
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    package_report: dict[str, Any] | None = None
    if args.package:
        package_report = validate_package(args.package.resolve(), errors)
    if args.pool:
        validate_pool(args.pool.resolve(), errors)
    if args.manifest:
        validate_manifest(args.manifest.resolve(), errors)
    if args.reference_set:
        validate_reference_set(args.reference_set.resolve(), errors)
    report: dict[str, Any] = {"status": "pass" if not errors else "fail", "errors": errors}
    if package_report is not None:
        report["package"] = package_report
    if errors:
        raise UiReferenceError(json.dumps(report, ensure_ascii=False))
    return report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Проверка и безопасная миграция UI reference artifacts")
    subparsers = root.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--source", type=Path, required=True)
    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--source", type=Path, required=True)
    migrate_parser.add_argument("--target", type=Path, required=True)
    migrate_parser.add_argument("--write", action="store_true")
    migrate_parser.add_argument("--report", type=Path)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--pool", type=Path)
    validate_parser.add_argument("--manifest", type=Path)
    validate_parser.add_argument("--reference-set", type=Path)
    validate_parser.add_argument("--package", type=Path)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "inventory":
        result = inventory(args.source.resolve())
    elif args.command == "migrate":
        result = migrate(args.source.resolve(), args.target.resolve(), args.write)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        result = validate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UiReferenceError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
