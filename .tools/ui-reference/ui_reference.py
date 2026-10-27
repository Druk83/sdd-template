"""Валидация UI-пакетов и безопасная миграция legacy reference artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdd_runtime import fs_boundary  # noqa: E402


SOURCE_URL = "https://github.com/Druk83/ui-patterns.git"
FRAMEWORK_URL = "https://github.com/Druk83/sdd-template.git"
VALID_STATUSES = {
    "proposed",
    "confirmed",
    "rejected",
    "gap",
    "superseded",
    "not_applicable",
}
VALID_CANDIDATE_STATUSES = {"proposed", "selected", "rejected", "gap", "not_applicable"}
VALID_VIEWPORT_STATUSES = {"proposed", "confirmed", "rejected", "gap", "not_applicable"}
WORKFLOW_MODES = {"early-prototype", "track-integrated"}
LEGACY_CONTRACT_VERSION = "1"
CURRENT_CONTRACT_VERSION = "2"
SHELL_INTEGRATION_CONTRACT_VERSION = (0, 3, 1)
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


def _is_regular(path: Path) -> bool:
    try:
        with fs_boundary.open_regular(path):
            return True
    except OSError:
        return False


def _is_directory(path: Path) -> bool:
    try:
        with fs_boundary.locked_directory(path):
            return True
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with fs_boundary.open_regular(path) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(fs_boundary.read_bytes(path).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UiReferenceError(f"Невозможно прочитать JSON {path}: {error}") from error


def relative_files(root: Path) -> list[Path]:
    try:
        return fs_boundary.list_files(root)
    except OSError as error:
        raise UiReferenceError(f"Невозможно прочитать каталог {root}: {error}") from error


def inventory(root: Path) -> dict[str, Any]:
    entries = []
    for path in relative_files(root):
        relative = path.relative_to(root).as_posix()
        with fs_boundary.open_regular(path) as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        entries.append(
            {
                "path": relative,
                "type": "file",
                "size": size,
                "sha256": digest.hexdigest(),
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


def safe_destination(target: Path, destination: Path) -> Path:
    """Проверить путь назначения миграции до обращения к файловой системе."""
    target_path = target.absolute()
    resolved_target = target.resolve()
    try:
        relative = destination.absolute().relative_to(target_path)
    except ValueError as error:
        raise UiReferenceError(f"Путь назначения выходит за target: {destination}") from error

    current = target_path
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            metadata = None
        if metadata is not None:
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(metadata.st_mode) or (
                reparse_flag and getattr(metadata, "st_file_attributes", 0) & reparse_flag
            ):
                raise UiReferenceError(f"Путь назначения содержит символическую ссылку: {current}")
        try:
            resolved = current.resolve(strict=False)
        except OSError as error:
            raise UiReferenceError(f"Невозможно проверить путь назначения: {current}") from error
        if not resolved.is_relative_to(resolved_target):
            raise UiReferenceError(f"Путь назначения выходит за target: {current}")
    return current


def migrate(source: Path, target: Path, write: bool) -> dict[str, Any]:
    safe_roots(source, target)
    source_inventory = inventory(source)
    conflicts: list[str] = []
    copied: list[str] = []
    skipped: list[str] = []

    for entry in source_inventory["entries"]:
        relative = Path(str(entry["path"]))
        try:
            destination = safe_destination(target, target / relative)
        except UiReferenceError:
            conflicts.append(relative.as_posix())
            continue
        if destination.exists():
            if not _is_regular(destination) or sha256_file(destination) != entry["sha256"]:
                conflicts.append(relative.as_posix())
            else:
                skipped.append(relative.as_posix())
            continue
        copied.append(relative.as_posix())
        if write:
            try:
                data = fs_boundary.read_bytes(source / relative)
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise UiReferenceError(f"Источник изменился после inventory: {relative}")
                fs_boundary.mkdirs(destination.parent)
                fs_boundary.write_bytes(destination, data, create_only=True)
            except (OSError, UiReferenceError):
                copied.pop()
                conflicts.append(relative.as_posix())

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


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_one_of(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _string_list(value: Any, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(f"{field} должен быть массивом непустых строк")
        return []
    return value


def _reject_unknown_fields(value: Any, allowed: set[str], field: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        return
    for name in sorted(set(value) - allowed):
        errors.append(f"{field} содержит неизвестное поле: {name}")


def _version_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def _requires_shell_integration(template_set_version: Any) -> bool:
    version = _version_tuple(template_set_version)
    return version is not None and version >= SHELL_INTEGRATION_CONTRACT_VERSION


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _validate_local_shell(
    value: dict[str, Any],
    prefix: str,
    errors: list[str],
    framework_root: Path | None,
) -> None:
    if value.get("catalog_url") != FRAMEWORK_URL:
        return
    root = (framework_root or _framework_root()).absolute()
    release_path = root / "release-manifest.json"
    library_path = root / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
    if not _is_regular(release_path) or not _is_regular(library_path):
        errors.append(f"{prefix}: локальная библиотека оболочек или release-manifest.json Framework отсутствует")
        return
    try:
        release = read_json(release_path)
        library = read_json(library_path)
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{prefix}: не удалось прочитать каталог Framework: {error}")
        return
    if not isinstance(release, dict) or not isinstance(library, dict):
        errors.append(f"{prefix}: каталог Framework должен содержать JSON-объекты")
        return
    source_commit = release.get("source_commit")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        errors.append(f"{prefix}: release-manifest.json не содержит точный source_commit")
    elif value.get("catalog_revision") != source_commit:
        errors.append(f"{prefix}.catalog_revision не совпадает с Framework release-manifest.source_commit")
    shells = library.get("shells")
    if not isinstance(shells, list):
        errors.append(f"{prefix}: shell-library.json.shells должен быть массивом")
        return
    shell_id = value.get("shell_id")
    matches = [item for item in shells if isinstance(item, dict) and item.get("shell_id") == shell_id]
    if len(matches) != 1:
        errors.append(f"{prefix}.shell_id отсутствует или повторяется в библиотеке Framework")
        return
    shell = matches[0]
    for field in ("shell_version", "viewport_id"):
        if value.get(field) != shell.get(field):
            errors.append(f"{prefix}.{field} не совпадает с библиотекой Framework")
    shell_viewport = value.get("shell_viewport")
    if isinstance(shell_viewport, dict):
        for field in ("width", "height", "unit", "orientation"):
            if shell_viewport.get(field) != shell.get(field):
                errors.append(f"{prefix}.shell_viewport.{field} не совпадает с библиотекой Framework")


def _validate_shell_binding(
    artifact: dict[str, Any],
    prefix: str,
    errors: list[str],
    required: bool,
    framework_root: Path | None = None,
) -> None:
    if "shell_binding" not in artifact:
        if required:
            errors.append(f"{prefix}.shell_binding обязателен для ui-patterns 0.3.1 и новее")
        return

    binding = artifact.get("shell_binding")
    if not isinstance(binding, dict):
        errors.append(f"{prefix}.shell_binding должен быть объектом")
        return

    allowed = {
        "status", "catalog_url", "catalog_revision", "shell_id", "shell_version", "viewport_id",
        "shell_viewport", "rationale", "reason", "decision_needed",
    }
    _reject_unknown_fields(binding, allowed, f"{prefix}.shell_binding", errors)
    status = binding.get("status")
    if not _is_one_of(status, {"selected", "proposed", "gap", "not_applicable"}):
        errors.append(f"{prefix}.shell_binding.status имеет недопустимое значение")
        return

    if status in {"selected", "proposed"}:
        required_fields = [
            "catalog_url", "catalog_revision", "shell_id", "shell_version", "viewport_id", "shell_viewport"
        ]
        if status == "proposed":
            required_fields.append("rationale")
        for field in required_fields:
            if field not in binding:
                errors.append(f"{prefix}.shell_binding.{field} обязателен для status={status}")
        for field in ("catalog_url", "catalog_revision", "shell_id", "shell_version", "viewport_id"):
            if field in binding:
                require_string(binding.get(field), f"{prefix}.shell_binding.{field}", errors)
        shell_version = binding.get("shell_version")
        if isinstance(shell_version, str) and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", shell_version):
            errors.append(f"{prefix}.shell_binding.shell_version должен иметь формат X.Y.Z")

        catalog_url = binding.get("catalog_url")
        if isinstance(catalog_url, str):
            try:
                parsed_url = urlsplit(catalog_url)
            except ValueError:
                parsed_url = None
            if parsed_url is None or parsed_url.scheme != "https" or not parsed_url.netloc:
                errors.append(f"{prefix}.shell_binding.catalog_url должен быть абсолютным HTTPS URL")

        catalog_revision = binding.get("catalog_revision")
        if isinstance(catalog_revision, str) and (
            catalog_revision.casefold() in {"main", "master", "head", "latest"}
            or catalog_revision.casefold().startswith("refs/heads/")
        ):
            errors.append(f"{prefix}.shell_binding.catalog_revision должен быть закреплённой ревизией, не веткой")

        shell_viewport = binding.get("shell_viewport")
        artifact_viewport = artifact.get("viewport")
        if not isinstance(shell_viewport, dict):
            errors.append(f"{prefix}.shell_binding.shell_viewport должен быть объектом")
        else:
            _reject_unknown_fields(
                shell_viewport,
                {"width", "height", "unit", "orientation"},
                f"{prefix}.shell_binding.shell_viewport",
                errors,
            )
            for dimension in ("width", "height"):
                if not _positive_integer(shell_viewport.get(dimension)):
                    errors.append(
                        f"{prefix}.shell_binding.shell_viewport.{dimension} должен быть положительным целым числом"
                    )
            if shell_viewport.get("unit") != "css-px":
                errors.append(f"{prefix}.shell_binding.shell_viewport.unit должен быть css-px")
            if not _is_one_of(shell_viewport.get("orientation"), {"portrait", "landscape", "any"}):
                errors.append(f"{prefix}.shell_binding.shell_viewport.orientation имеет недопустимое значение")
            if isinstance(artifact_viewport, dict):
                for field in ("width", "height", "unit", "orientation"):
                    if shell_viewport.get(field) != artifact_viewport.get(field):
                        errors.append(
                            f"{prefix}.shell_binding.shell_viewport.{field} не совпадает с artifact viewport"
                        )
        if binding.get("viewport_id") != (
            artifact_viewport.get("viewport_id") if isinstance(artifact_viewport, dict) else None
        ):
            errors.append(f"{prefix}.shell_binding.viewport_id не совпадает с artifact viewport")
        if status == "proposed":
            require_string(binding.get("rationale"), f"{prefix}.shell_binding.rationale", errors)
        _validate_local_shell(binding, f"{prefix}.shell_binding", errors, framework_root)
        return

    if status == "gap":
        for field in ("viewport_id", "reason", "decision_needed"):
            if field not in binding:
                errors.append(f"{prefix}.shell_binding.{field} обязателен для status=gap")
            else:
                require_string(binding.get(field), f"{prefix}.shell_binding.{field}", errors)
        artifact_viewport = artifact.get("viewport")
        if binding.get("viewport_id") != (
            artifact_viewport.get("viewport_id") if isinstance(artifact_viewport, dict) else None
        ):
            errors.append(f"{prefix}.shell_binding.viewport_id не совпадает с artifact viewport")
        return

    require_string(binding.get("rationale"), f"{prefix}.shell_binding.rationale", errors)


def _validate_shell_candidates(
    viewport: dict[str, Any],
    prefix: str,
    errors: list[str],
    required: bool,
    framework_root: Path | None = None,
) -> None:
    if "screen_shell_candidates" not in viewport:
        if required:
            errors.append(f"{prefix}.screen_shell_candidates обязателен для ui-patterns 0.3.1 и новее")
        return

    candidates = viewport.get("screen_shell_candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append(f"{prefix}.screen_shell_candidates должен быть непустым массивом")
        return

    selected_count = 0
    parent_status = viewport.get("status")
    for index, candidate in enumerate(candidates):
        candidate_prefix = f"{prefix}.screen_shell_candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{candidate_prefix} должен быть объектом")
            continue
        _reject_unknown_fields(
            candidate,
            {
                "status", "catalog_url", "catalog_revision", "shell_id", "shell_version", "shell_viewport",
                "rationale", "reason", "decision_needed",
            },
            candidate_prefix,
            errors,
        )
        status = candidate.get("status")
        if not _is_one_of(status, {"selected", "proposed", "rejected", "gap", "not_applicable"}):
            errors.append(f"{candidate_prefix}.status имеет недопустимое значение")
            continue

        if status in {"selected", "proposed", "rejected"}:
            for field in ("catalog_url", "catalog_revision", "shell_id", "shell_viewport", "rationale"):
                if field not in candidate:
                    errors.append(f"{candidate_prefix}.{field} обязателен для status={status}")
            for field in ("catalog_url", "catalog_revision", "shell_id", "shell_version", "rationale"):
                if field in candidate:
                    require_string(candidate.get(field), f"{candidate_prefix}.{field}", errors)
            shell_version = candidate.get("shell_version")
            if isinstance(shell_version, str) and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", shell_version):
                errors.append(f"{candidate_prefix}.shell_version должен иметь формат X.Y.Z")

            catalog_url = candidate.get("catalog_url")
            if isinstance(catalog_url, str):
                try:
                    parsed_url = urlsplit(catalog_url)
                except ValueError:
                    parsed_url = None
                if parsed_url is None or parsed_url.scheme != "https" or not parsed_url.netloc:
                    errors.append(f"{candidate_prefix}.catalog_url должен быть абсолютным HTTPS URL")

            catalog_revision = candidate.get("catalog_revision")
            if isinstance(catalog_revision, str) and (
                catalog_revision.casefold() in {"main", "master", "head", "latest"}
                or catalog_revision.casefold().startswith("refs/heads/")
            ):
                errors.append(f"{candidate_prefix}.catalog_revision должен быть закреплённой ревизией, не веткой")

            shell_viewport = candidate.get("shell_viewport")
            if not isinstance(shell_viewport, dict):
                errors.append(f"{candidate_prefix}.shell_viewport должен быть объектом")
            else:
                _reject_unknown_fields(
                    shell_viewport,
                    {"width", "height", "unit", "orientation"},
                    f"{candidate_prefix}.shell_viewport",
                    errors,
                )
                for dimension in ("width", "height"):
                    if not _positive_integer(shell_viewport.get(dimension)):
                        errors.append(f"{candidate_prefix}.shell_viewport.{dimension} должен быть положительным целым числом")
                if shell_viewport.get("unit") != "css-px":
                    errors.append(f"{candidate_prefix}.shell_viewport.unit должен быть css-px")
                if not _is_one_of(shell_viewport.get("orientation"), {"portrait", "landscape", "any"}):
                    errors.append(f"{candidate_prefix}.shell_viewport.orientation имеет недопустимое значение")
                for field in ("width", "height", "unit", "orientation"):
                    if field not in viewport:
                        errors.append(f"{candidate_prefix}: точную оболочку нельзя связать с viewport без {field}")
                    elif shell_viewport.get(field) != viewport.get(field):
                            errors.append(f"{candidate_prefix}.shell_viewport.{field} не совпадает с viewport-кандидатом")
            local_candidate = {**candidate, "viewport_id": viewport.get("viewport_id")}
            _validate_local_shell(local_candidate, candidate_prefix, errors, framework_root)

            if status == "selected":
                selected_count += 1
                if parent_status != "confirmed":
                    errors.append(f"{candidate_prefix}: selected допускается только для confirmed viewport")
        elif status == "gap":
            for field in ("reason", "decision_needed"):
                if field not in candidate:
                    errors.append(f"{candidate_prefix}.{field} обязателен для status=gap")
                else:
                    require_string(candidate.get(field), f"{candidate_prefix}.{field}", errors)
        else:
            require_string(candidate.get("rationale"), f"{candidate_prefix}.rationale", errors)

    if selected_count > 1:
        errors.append(f"{prefix}.screen_shell_candidates допускает не более одной оболочки со статусом selected")


def validate_pool(
    path: Path,
    errors: list[str],
    contract_version: str | None = None,
    require_shell_candidates: bool = False,
    framework_root: Path | None = None,
) -> dict[str, Any] | None:
    data = read_json(path)
    if not isinstance(data, dict):
        errors.append("screen pool должен быть JSON-объектом")
        return None
    schema_version = data.get("schema_version")
    if contract_version == CURRENT_CONTRACT_VERSION and schema_version != "2.0":
        errors.append("screen pool schema_version не соответствует contract_version")
    elif contract_version == LEGACY_CONTRACT_VERSION and schema_version not in ("1", "1.0", 1):
        errors.append("Legacy screen pool содержит неподдерживаемую schema_version")
    elif contract_version is None and schema_version not in ("1", "1.0", 1, "2.0"):
        errors.append("screen pool содержит неподдерживаемую schema_version")
    if contract_version == CURRENT_CONTRACT_VERSION:
        _reject_unknown_fields(
            data,
            {
                "schema_version", "contract_version", "workflow_mode", "template_set_version",
                "status", "source_refs", "screens",
            },
            "screen pool",
            errors,
        )
        if data.get("contract_version") != CURRENT_CONTRACT_VERSION:
            errors.append("screen pool contract_version не совпадает с UI manifest")
        if not _is_one_of(data.get("workflow_mode"), WORKFLOW_MODES):
            errors.append("screen pool содержит недопустимый workflow_mode")
        if not _is_one_of(data.get("status"), VALID_STATUSES):
            errors.append("screen pool содержит недопустимый status")
        if data.get("workflow_mode") == "early-prototype" and data.get("status") != "proposed":
            errors.append("screen pool в режиме early-prototype должен иметь status=proposed")
        _string_list(data.get("source_refs"), "screen pool source_refs", errors)
        pool_template_set_version = data.get("template_set_version")
        if pool_template_set_version is not None and _version_tuple(pool_template_set_version) is None:
            errors.append("screen pool template_set_version должен иметь формат X.Y.Z")
        require_shell_candidates = require_shell_candidates or _requires_shell_integration(
            pool_template_set_version
        )
    screens = data.get("screens")
    if not isinstance(screens, list):
        errors.append("screen pool должен содержать массив screens")
        return data
    ids: set[str] = set()
    required = (
        "screen_id",
        "title",
        "screen_type",
        "purpose",
        "user_roles",
        "user_task",
        "pattern_candidates",
        "template_candidates",
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
        if isinstance(screen_id, str) and screen_id.strip():
            if screen_id in ids:
                errors.append(f"Дублирующийся screen_id: {screen_id}")
            ids.add(screen_id)
        elif contract_version == CURRENT_CONTRACT_VERSION:
            errors.append(f"{prefix}.screen_id должен быть непустой строкой")
        if not _is_one_of(screen.get("status"), VALID_STATUSES):
            errors.append(f"{prefix}.status имеет недопустимое значение: {screen.get('status')}")
        if contract_version == CURRENT_CONTRACT_VERSION:
            for field in ("title", "screen_type", "purpose", "user_task"):
                require_string(screen.get(field), f"{prefix}.{field}", errors)
            for field in ("route", "entry_point"):
                if field in screen and not isinstance(screen[field], str):
                    errors.append(f"{prefix}.{field} должен быть строкой")
            roles = _string_list(screen.get("user_roles"), f"{prefix}.user_roles", errors)
            states = _string_list(screen.get("states"), f"{prefix}.states", errors)
            _string_list(screen.get("source_refs"), f"{prefix}.source_refs", errors)
            if not isinstance(screen.get("transitions"), list):
                errors.append(f"{prefix}.transitions должен быть массивом")
            for key, identifier_field in (("pattern_candidates", "pattern_id"), ("template_candidates", "template_id")):
                candidates = screen.get(key)
                if not isinstance(candidates, list):
                    errors.append(f"{prefix}.{key} должен быть массивом")
                    continue
                if not candidates:
                    errors.append(f"{prefix}.{key} должен содержать кандидата либо явный GAP/not_applicable")
                candidate_ids: set[str] = set()
                for candidate_index, candidate in enumerate(candidates):
                    candidate_prefix = f"{prefix}.{key}[{candidate_index}]"
                    if not isinstance(candidate, dict):
                        errors.append(f"{candidate_prefix} должен быть объектом")
                        continue
                    status = candidate.get("status")
                    if not _is_one_of(status, VALID_CANDIDATE_STATUSES):
                        errors.append(f"{candidate_prefix}.status имеет недопустимое значение")
                    other_identifier_field = "template_id" if identifier_field == "pattern_id" else "pattern_id"
                    _reject_unknown_fields(
                        candidate,
                        {identifier_field, "status", "rationale", "source_refs"},
                        candidate_prefix,
                        errors,
                    )
                    if other_identifier_field in candidate:
                        errors.append(f"{candidate_prefix} содержит поле {other_identifier_field} не своего типа")
                    rationale = candidate.get("rationale")
                    require_string(rationale, f"{candidate_prefix}.rationale", errors)
                    identifier = candidate.get(identifier_field)
                    if _is_one_of(status, {"gap", "not_applicable"}) and identifier is None:
                        continue
                    if not isinstance(identifier, str) or not identifier.strip():
                        errors.append(f"{candidate_prefix}.{identifier_field} обязателен")
                        continue
                    if identifier in candidate_ids:
                        errors.append(f"{candidate_prefix}: повторный {identifier_field} внутри одного экрана: {identifier}")
                    candidate_ids.add(identifier)
                    _string_list(candidate.get("source_refs", []), f"{candidate_prefix}.source_refs", errors)
            viewports = screen.get("viewport_candidates")
            if not isinstance(viewports, list) or not viewports:
                errors.append(f"{prefix}.viewport_candidates должен содержать область просмотра или явный GAP")
                viewports = []
            viewport_ids: set[str] = set()
            for viewport_index, viewport in enumerate(viewports):
                viewport_prefix = f"{prefix}.viewport_candidates[{viewport_index}]"
                if not isinstance(viewport, dict):
                    errors.append(f"{viewport_prefix} должен быть объектом")
                    continue
                _reject_unknown_fields(
                    viewport,
                    {
                        "viewport_id", "width", "height", "unit", "orientation",
                        "responsive_profile", "breakpoint_conditions", "purpose", "source",
                        "screen_shell_candidates", "status", "rationale", "source_refs",
                    },
                    viewport_prefix,
                    errors,
                )
                viewport_id = viewport.get("viewport_id")
                if not isinstance(viewport_id, str) or not viewport_id.strip():
                    errors.append(f"{viewport_prefix}.viewport_id обязателен")
                elif viewport_id in viewport_ids:
                    errors.append(f"{viewport_prefix}: повторный viewport_id: {viewport_id}")
                else:
                    viewport_ids.add(viewport_id)
                status = viewport.get("status")
                if not _is_one_of(status, VALID_VIEWPORT_STATUSES):
                    errors.append(f"{viewport_prefix}.status имеет недопустимое значение")
                require_string(viewport.get("rationale"), f"{viewport_prefix}.rationale", errors)
                if "responsive_profile" in viewport:
                    require_string(viewport["responsive_profile"], f"{viewport_prefix}.responsive_profile", errors)
                for field in ("breakpoint_conditions", "purpose", "source"):
                    if field in viewport:
                        require_string(viewport[field], f"{viewport_prefix}.{field}", errors)
                if "purpose" in viewport and not _is_one_of(
                    viewport.get("purpose"), {"reference", "supported", "minimum", "maximum", "stress"}
                ):
                    errors.append(f"{viewport_prefix}.purpose имеет недопустимое значение")
                _string_list(viewport.get("source_refs", []), f"{viewport_prefix}.source_refs", errors)
                _validate_shell_candidates(
                    viewport,
                    viewport_prefix,
                    errors,
                    required=require_shell_candidates,
                    framework_root=framework_root,
                )
                if _is_one_of(status, {"gap", "not_applicable"}):
                    if any(field in viewport for field in ("width", "height", "unit", "orientation")):
                        errors.append(f"{viewport_prefix}: статус {status} не должен содержать параметры viewport")
                    continue
                dimensions = ("width", "height", "unit", "orientation")
                present_dimensions = [field in viewport for field in dimensions]
                if _is_one_of(status, {"proposed", "confirmed"}) or any(present_dimensions):
                    width, height = viewport.get("width"), viewport.get("height")
                    if not _positive_integer(width) or not _positive_integer(height):
                        errors.append(f"{viewport_prefix}: width и height должны быть положительными целыми числами")
                    if viewport.get("unit") != "css-px":
                        errors.append(f"{viewport_prefix}.unit должен быть css-px")
                    if not _is_one_of(viewport.get("orientation"), {"portrait", "landscape", "any"}):
                        errors.append(f"{viewport_prefix}.orientation имеет недопустимое значение")
                    if require_shell_candidates:
                        for field in (
                            "responsive_profile", "breakpoint_conditions", "purpose", "source",
                        ):
                            require_string(
                                viewport.get(field),
                                f"{viewport_prefix}.{field}",
                                errors,
                            )
            if not isinstance(roles, list) or not isinstance(states, list):
                continue
    return data


def validate_manifest(path: Path, errors: list[str]) -> str | None:
    data = read_json(path)
    if not isinstance(data, dict):
        errors.append("UI manifest должен быть JSON-объектом")
        return None
    contract_version = data.get("contract_version")
    if not isinstance(contract_version, str) or contract_version not in (
        LEGACY_CONTRACT_VERSION, CURRENT_CONTRACT_VERSION
    ):
        errors.append("UI manifest содержит неподдерживаемую contract_version")
        return None
    expected_schema_version = "2.0" if contract_version == CURRENT_CONTRACT_VERSION else None
    if expected_schema_version is not None:
        _reject_unknown_fields(
            data,
            {
                "schema_version", "contract_version", "workflow_mode", "template_set_version",
                "source_url", "revision", "status", "screen_pool", "screens", "reference_sets",
                "traceability", "gaps",
            },
            "UI manifest",
            errors,
        )
        if data.get("schema_version") != expected_schema_version:
            errors.append("UI manifest schema_version не соответствует contract_version")
        if not _is_one_of(data.get("workflow_mode"), WORKFLOW_MODES):
            errors.append("UI manifest содержит недопустимый workflow_mode")
    elif data.get("schema_version") not in ("1", "1.0", 1):
        errors.append("UI manifest содержит неподдерживаемую schema_version")
    require_string(data.get("template_set_version"), "template_set_version", errors)
    if contract_version == CURRENT_CONTRACT_VERSION and _version_tuple(data.get("template_set_version")) is None:
        errors.append("template_set_version должен иметь формат X.Y.Z")
    require_string(data.get("revision"), "revision", errors)
    require_string(data.get("contract_version"), "contract_version", errors)
    if data.get("source_url") != SOURCE_URL:
        errors.append("source_url не совпадает с официальным URL ui-patterns")
    if not _is_one_of(data.get("status"), VALID_STATUSES):
        errors.append("UI manifest содержит недопустимый status")
    if data.get("workflow_mode") == "early-prototype" and data.get("status") != "proposed":
        errors.append("UI manifest в режиме early-prototype должен иметь status=proposed")
    return contract_version


def validate_reference_set(
    root: Path,
    errors: list[str],
    contract_version: str | None = None,
    expected_id: str | None = None,
    require_shell_binding: bool = False,
    framework_root: Path | None = None,
    ui_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    manifest_path = root / "screen-manifest.json"
    if not _is_regular(manifest_path):
        errors.append("В reference-set отсутствует screen-manifest.json")
        return []
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("screens"), list):
        if contract_version != CURRENT_CONTRACT_VERSION or not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
            errors.append("screen-manifest.json должен содержать массив screens (legacy) или artifacts")
            return []
    if contract_version != CURRENT_CONTRACT_VERSION:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("screens"), list):
            errors.append("Legacy screen-manifest.json должен содержать массив screens")
            return []
        root_resolved = root.resolve()
        for index, screen in enumerate(manifest["screens"]):
            if not isinstance(screen, dict):
                errors.append(f"screen-manifest.screens[{index}] должен быть объектом")
                continue
            file_value = screen.get("file")
            if not isinstance(file_value, str) or not file_value:
                errors.append(f"screen-manifest.screens[{index}].file отсутствует")
                continue
            file_path = (root / file_value).absolute()
            if root_resolved not in file_path.resolve().parents or not _is_regular(file_path):
                errors.append(f"Отсутствует screen artifact: {file_value}")
            viewport = screen.get("viewport")
            if (
                not isinstance(viewport, dict)
                or not _positive_integer(viewport.get("width"))
                or not _positive_integer(viewport.get("height"))
            ):
                errors.append(f"Некорректный viewport для screen-manifest.screens[{index}]")
        _validate_viewport_directories(root, errors)
        return []

    if manifest.get("schema_version") != "2.0" or manifest.get("contract_version") != CURRENT_CONTRACT_VERSION:
        errors.append("screen-manifest.json содержит неподдерживаемую версию контракта")
    _reject_unknown_fields(
        manifest,
        {
            "schema_version", "contract_version", "reference_set_id", "template_set_version",
            "source_url", "revision", "artifacts",
        },
        "screen-manifest",
        errors,
    )
    reference_set_id = manifest.get("reference_set_id")
    require_string(reference_set_id, "screen-manifest.reference_set_id", errors)
    if expected_id is not None and reference_set_id != expected_id:
        errors.append("reference_set_id не совпадает с записью UI manifest")
    if ui_manifest is not None:
        for field in ("template_set_version", "source_url", "revision"):
            recorded = manifest.get(field)
            expected = ui_manifest.get(field)
            if require_shell_binding and recorded != expected:
                errors.append(f"screen-manifest.{field} не совпадает с корневым UI manifest")
            elif recorded is not None and recorded != expected:
                errors.append(f"screen-manifest.{field} расходится с корневым UI manifest")
    elif require_shell_binding:
        for field in ("template_set_version", "source_url", "revision"):
            if field not in manifest:
                errors.append(f"screen-manifest.{field} обязателен для ui-patterns 0.3.1 и новее")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("screen-manifest.artifacts должен быть массивом")
        return []
    root_resolved = root.resolve()
    result: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    shared_paths: dict[str, list[dict[str, Any]]] = {}
    for index, artifact in enumerate(artifacts):
        prefix = f"screen-manifest.artifacts[{index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        _reject_unknown_fields(
            artifact,
            {
                "artifact_id", "screen_id", "role", "state", "viewport", "path", "pattern_refs",
                "template_refs", "target", "shell_binding",
            },
            prefix,
            errors,
        )
        artifact_id = artifact.get("artifact_id")
        screen_id = artifact.get("screen_id")
        role = artifact.get("role")
        state = artifact.get("state")
        for field, value in (("artifact_id", artifact_id), ("screen_id", screen_id), ("role", role), ("state", state)):
            require_string(value, f"{prefix}.{field}", errors)
        if isinstance(artifact_id, str):
            if artifact_id in artifact_ids:
                errors.append(f"{prefix}: повторный artifact_id: {artifact_id}")
            artifact_ids.add(artifact_id)
        viewport = artifact.get("viewport")
        if not isinstance(viewport, dict):
            errors.append(f"{prefix}.viewport должен быть объектом")
        else:
            _reject_unknown_fields(
                viewport,
                {"viewport_id", "width", "height", "unit", "orientation"},
                f"{prefix}.viewport",
                errors,
            )
            require_string(viewport.get("viewport_id"), f"{prefix}.viewport.viewport_id", errors)
            for dimension in ("width", "height"):
                value = viewport.get(dimension)
                if not _positive_integer(value):
                    errors.append(f"{prefix}.viewport.{dimension} должен быть положительным целым числом")
            if viewport.get("unit") != "css-px":
                errors.append(f"{prefix}.viewport.unit должен быть css-px")
            if not _is_one_of(viewport.get("orientation"), {"portrait", "landscape", "any"}):
                errors.append(f"{prefix}.viewport.orientation имеет недопустимое значение")
        _validate_shell_binding(artifact, prefix, errors, require_shell_binding, framework_root)
        relative = _safe_relative_path(artifact.get("path"), f"{prefix}.path", errors)
        if relative is None:
            continue
        file_path = _path_inside(root, relative)
        if file_path is None or not _is_regular(file_path):
            errors.append(f"Отсутствует или небезопасен screen artifact: {relative.as_posix()}")
        if viewport and isinstance(viewport.get("viewport_id"), str):
            if relative.parts[:1] == ("screens",):
                if relative.parts[:3] != ("screens", screen_id, viewport["viewport_id"]):
                    errors.append(f"{prefix}.path должен иметь вид screens/<screen_id>/<viewport_id>/...")
            elif relative.parts[0] != viewport["viewport_id"]:
                errors.append(f"{prefix}.path должен находиться в каталоге своего viewport_id")
        target = artifact.get("target")
        if target is not None:
            _reject_unknown_fields(target, {"kind", "value"}, f"{prefix}.target", errors)
            if not isinstance(target, dict) or not _is_one_of(
                target.get("kind"), {"route", "selector", "anchor", "view-id"}
            ):
                errors.append(f"{prefix}.target имеет недопустимую структуру")
            elif not isinstance(target.get("value"), str) or not target["value"].strip():
                errors.append(f"{prefix}.target.value обязателен")
        if isinstance(artifact_id, str) and isinstance(screen_id, str):
            entry = {**artifact, "_resolved_path": str(file_path) if file_path else None}
            result.append(entry)
            shared_paths.setdefault(relative.as_posix(), []).append(entry)

    for relative_path, entries in shared_paths.items():
        identities = {(entry.get("screen_id"), entry.get("role"), entry.get("state")) for entry in entries}
        if len(identities) > 1:
            targets = []
            for entry in entries:
                target = entry.get("target")
                if not isinstance(target, dict):
                    errors.append(f"Общий артефакт {relative_path} требует target для каждой связи")
                    break
                targets.append((target.get("kind"), target.get("value")))
            if len(targets) == len(entries) and len(set(targets)) != len(targets):
                errors.append(f"Общий артефакт {relative_path} должен иметь уникальные target")

    _validate_viewport_directories(root, errors, result)
    return result


def _validate_viewport_directories(
    root: Path,
    errors: list[str],
    artifacts: list[dict[str, Any]] | None = None,
) -> None:
    if not _is_directory(root):
        return

    if artifacts is not None:
        checked: set[Path] = set()
        for artifact in artifacts:
            value = artifact.get("path")
            if not isinstance(value, str):
                continue
            relative = Path(value.replace("\\", "/"))
            if relative.parts[:1] == ("screens",) and len(relative.parts) >= 4:
                directory = root.joinpath(*relative.parts[:3])
            elif relative.parts:
                directory = root / relative.parts[0]
            else:
                continue
            if directory in checked:
                continue
            checked.add(directory)
            for required in ("index.html", "reference-manifest.json", "README.md"):
                if not _is_regular(directory / required):
                    errors.append(f"{directory.relative_to(root).as_posix()}: отсутствует {required}")
        if not checked:
            errors.append("reference-set не содержит viewport/orientation каталогов")
        return

    try:
        viewport_dirs = [path for path in fs_boundary.list_tree(root)[0] if path.parent == root]
    except OSError as error:
        errors.append(f"Невозможно проверить каталоги reference-set: {error}")
        return
    if not viewport_dirs:
        errors.append("reference-set не содержит viewport/orientation каталогов")
    for viewport_dir in viewport_dirs:
        for required in ("index.html", "reference-manifest.json", "README.md"):
            if not _is_regular(viewport_dir / required):
                errors.append(f"{viewport_dir.name}: отсутствует {required}")


def _safe_relative_path(value: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} должен быть непустым относительным путём")
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        errors.append(f"{field} выходит за границы UI-пакета: {value}")
        return None
    return candidate


def _path_inside(root: Path, relative: Path) -> Path | None:
    target = (root / relative).absolute()
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
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


def _candidate_map(screens: list[Any], key: str, errors: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for index, screen in enumerate(screens):
        if not isinstance(screen, dict):
            continue
        screen_id = screen.get("screen_id")
        if not isinstance(screen_id, str) or not screen_id.strip():
            continue
        screen_candidates = result.setdefault(screen_id, {})
        candidates = screen.get(key, [])
        if not isinstance(candidates, list):
            errors.append(f"screens[{index}].{key} должен быть массивом")
            continue
        for candidate_index, candidate in enumerate(candidates):
            status = _reference_status(candidate)
            if _is_one_of(status, {"gap", "not_applicable"}) and _id_value(
                candidate, f"screens[{index}].{key}[{candidate_index}]", []
            ) is None:
                continue
            identifier = _id_value(candidate, f"screens[{index}].{key}[{candidate_index}]", errors)
            if identifier is None:
                continue
            if identifier in screen_candidates:
                errors.append(f"Дублирующийся {key} identifier внутри экрана {screen_id}: {identifier}")
            screen_candidates[identifier] = status or "candidate"
    return result


def _validate_reference_ids(
    values: Any,
    field: str,
    screen_id: str,
    candidates_by_screen: dict[str, dict[str, str]],
    errors: list[str],
    workflow_mode: str | None = None,
) -> None:
    if not isinstance(values, list):
        errors.append(f"{field} должен быть массивом")
        return
    candidates = candidates_by_screen.get(screen_id, {})
    seen: set[str] = set()
    for index, value in enumerate(values):
        identifier = _id_value(value, f"{field}[{index}]", errors)
        if identifier is None:
            continue
        if identifier in seen:
            errors.append(f"{field} содержит повторный identifier: {identifier}")
        seen.add(identifier)
        status = _reference_status(value) or candidates.get(identifier)
        if identifier not in candidates:
            errors.append(f"{field}[{index}] содержит identifier, не заявленный для экрана {screen_id}: {identifier}")
        if workflow_mode == "track-integrated" and status != "selected":
            errors.append(f"{field}[{index}] должен ссылаться на выбранный candidate в track-integrated")
        elif workflow_mode == "early-prototype" and not _is_one_of(status, {"proposed", "selected"}):
            errors.append(f"{field}[{index}] с status={status} нельзя использовать в early-prototype")
        elif workflow_mode is None and status in APPLIED_REFERENCE_STATUSES:
            errors.append(f"{field}[{index}] с status={status} нельзя применять как выбранный reference")


def _validate_traceability(
    value: Any,
    screen_ids: set[str],
    errors: list[str],
    required_screen_ids: set[str] | None = None,
) -> None:
    if not isinstance(value, list):
        errors.append("traceability должен быть массивом")
        return
    required_screen_ids = required_screen_ids or set()
    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(value):
        prefix = f"traceability[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        _reject_unknown_fields(
            record,
            {"screen_id", "requirement_refs", "scenario_refs", "acceptance_criteria"},
            prefix,
            errors,
        )
        screen_id = record.get("screen_id")
        if not isinstance(screen_id, str) or screen_id not in screen_ids:
            errors.append(f"{prefix}.screen_id не связан с UI-экраном")
            continue
        if screen_id in records:
            errors.append(f"traceability содержит повторную запись для screen_id={screen_id}")
        records[screen_id] = record
        for field in ("requirement_refs", "scenario_refs", "acceptance_criteria"):
            if field not in record:
                if screen_id in required_screen_ids:
                    errors.append(f"{prefix}.{field} должен содержать непустые ссылки")
                continue
            refs = record[field]
            if not isinstance(refs, list) or not all(isinstance(item, str) and item.strip() for item in refs):
                errors.append(f"{prefix}.{field} должен быть массивом непустых строк")
            elif screen_id in required_screen_ids and not refs:
                errors.append(f"{prefix}.{field} должен содержать непустые ссылки")
    for screen_id in sorted(required_screen_ids - records.keys()):
        errors.append(f"Для подтверждённого экрана {screen_id} отсутствует запись traceability")


def _validate_gaps(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("gaps должен быть массивом")
        return
    for index, gap in enumerate(value):
        prefix = f"gaps[{index}]"
        if not isinstance(gap, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        _reject_unknown_fields(
            gap,
            {"gap_id", "screen_id", "area", "owner", "blocking_condition", "status", "closure_evidence"},
            prefix,
            errors,
        )
        for field in ("gap_id", "owner", "blocking_condition"):
            if not isinstance(gap.get(field), str) or not gap[field].strip():
                errors.append(f"{prefix}.{field} обязателен")
        require_string(gap.get("status"), f"{prefix}.status", errors)
        if "closure_evidence" in gap and not isinstance(gap["closure_evidence"], str):
            errors.append(f"{prefix}.closure_evidence должен быть строкой")
        if _is_one_of(gap.get("status"), {"closed", "resolved"}) and not isinstance(gap.get("closure_evidence"), str):
            errors.append(f"{prefix}.closure_evidence обязателен для закрытого GAP")


def _validate_v2_artifact_links(
    manifest_screens: dict[str, dict[str, Any]],
    pool_screens: dict[str, dict[str, Any]],
    artifacts: list[dict[str, Any]],
    workflow_mode: str | None,
    require_shell_binding: bool,
    errors: list[str],
) -> None:
    artifact_by_id: dict[str, dict[str, Any]] = {}
    linked_artifacts: dict[str, str] = {}

    for screen_id, screen in manifest_screens.items():
        refs = screen.get("reference_artifacts")
        if not isinstance(refs, list):
            errors.append(f"manifest.screens[{screen_id}].reference_artifacts должен быть массивом artifact_id")
            continue
        if workflow_mode == "track-integrated" and screen.get("status") == "confirmed" and not refs:
            errors.append(f"Подтверждённый экран {screen_id} должен ссылаться на визуальный артефакт")
        for index, artifact_id in enumerate(refs):
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                errors.append(f"manifest.screens[{screen_id}].reference_artifacts[{index}] должен быть artifact_id")
                continue
            if artifact_id in linked_artifacts:
                errors.append(f"artifact_id {artifact_id} повторно указан в manifest.screens")
            linked_artifacts[artifact_id] = screen_id

    for artifact in artifacts:
        artifact_id = artifact.get("artifact_id")
        screen_id = artifact.get("screen_id")
        if not isinstance(artifact_id, str) or not isinstance(screen_id, str):
            continue
        if artifact_id in artifact_by_id:
            errors.append(f"Повторный artifact_id между reference-set: {artifact_id}")
        artifact_by_id[artifact_id] = artifact
        if screen_id not in manifest_screens:
            errors.append(f"Artifact {artifact_id} ссылается на неизвестный экран: {screen_id}")
            continue
        if screen_id not in pool_screens:
            errors.append(f"Artifact {artifact_id} отсутствует в screen pool: {screen_id}")
            continue
        if linked_artifacts.get(artifact_id) != screen_id:
            errors.append(f"Artifact {artifact_id} не связан с тем же экраном в manifest.screens")
        if require_shell_binding:
            for field in ("pattern_refs", "template_refs"):
                _string_list(artifact.get(field), f"Artifact {artifact_id}.{field}", errors)
                if artifact.get(field) != manifest_screens[screen_id].get(field):
                    errors.append(
                        f"Artifact {artifact_id}.{field} должен совпадать со ссылками экрана в UI manifest"
                    )

        pool_screen = pool_screens[screen_id]
        shell_binding = artifact.get("shell_binding")
        if (
            require_shell_binding
            and workflow_mode == "track-integrated"
            and manifest_screens[screen_id].get("status") == "confirmed"
            and isinstance(shell_binding, dict)
            and shell_binding.get("status") not in {"selected", "not_applicable"}
        ):
            errors.append(
                f"Artifact {artifact_id}: подтверждённый track-integrated экран требует "
                "selected shell_binding или обоснованный not_applicable"
            )
        role = artifact.get("role")
        state = artifact.get("state")
        user_roles = pool_screen.get("user_roles")
        states = pool_screen.get("states")
        if not isinstance(user_roles, list) or role not in user_roles:
            errors.append(f"Artifact {artifact_id}: роль {role!r} отсутствует в screen pool для {screen_id}")
        if not isinstance(states, list) or state not in states:
            errors.append(f"Artifact {artifact_id}: состояние {state!r} отсутствует в screen pool для {screen_id}")

        viewport = artifact.get("viewport")
        if not isinstance(viewport, dict):
            continue
        viewport_id = viewport.get("viewport_id")
        candidates = pool_screen.get("viewport_candidates", [])
        matching = [
            item for item in candidates
            if isinstance(item, dict) and item.get("viewport_id") == viewport_id
        ] if isinstance(candidates, list) else []
        if not matching:
            errors.append(f"Artifact {artifact_id}: viewport {viewport_id!r} отсутствует в screen pool для {screen_id}")
            continue
        candidate = matching[0]
        if not _is_one_of(candidate.get("status"), {"proposed", "confirmed"}):
            errors.append(f"Artifact {artifact_id}: viewport {viewport_id!r} имеет неприменимый status")
        manifest_screen = manifest_screens[screen_id]
        if (
            workflow_mode == "track-integrated"
            and manifest_screen.get("status") == "confirmed"
            and candidate.get("status") != "confirmed"
        ):
            errors.append(f"Artifact {artifact_id}: подтверждённый экран использует неподтверждённый viewport")
        for field in ("width", "height", "unit", "orientation"):
            if candidate.get(field) != viewport.get(field):
                errors.append(f"Artifact {artifact_id}: viewport.{field} не совпадает с screen pool")
        if require_shell_binding:
            _validate_binding_against_candidates(
                shell_binding,
                candidate,
                f"Artifact {artifact_id}.shell_binding",
                errors,
            )

    for artifact_id, screen_id in linked_artifacts.items():
        artifact = artifact_by_id.get(artifact_id)
        if artifact is None:
            errors.append(f"manifest.screens[{screen_id}] ссылается на отсутствующий artifact_id: {artifact_id}")
        elif artifact.get("screen_id") != screen_id:
            errors.append(f"artifact_id {artifact_id} связан с другим screen_id")


def _validate_binding_against_candidates(
    binding: Any,
    viewport: dict[str, Any],
    prefix: str,
    errors: list[str],
) -> None:
    if not isinstance(binding, dict):
        return
    candidates = viewport.get("screen_shell_candidates")
    if not isinstance(candidates, list):
        return
    status = binding.get("status")
    matching_status = [
        candidate for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("status") == status
    ]
    if not matching_status:
        errors.append(f"{prefix} не соответствует кандидату оболочки того же viewport в screen pool")
        return

    if status in {"selected", "proposed"}:
        binding_fields = ["catalog_url", "catalog_revision", "shell_id", "shell_version", "shell_viewport"]
        if status == "proposed":
            binding_fields.append("rationale")
        if not any(
            all(candidate.get(field) == binding.get(field) for field in binding_fields)
            for candidate in matching_status
        ):
            errors.append(f"{prefix} не совпадает с кандидатом {status} в screen_shell_candidates")
    elif status == "gap":
        if not any(
            candidate.get("reason") == binding.get("reason")
            and candidate.get("decision_needed") == binding.get("decision_needed")
            for candidate in matching_status
        ):
            errors.append(f"{prefix} не совпадает с GAP-кандидатом в screen_shell_candidates")
    elif status == "not_applicable" and not any(
        candidate.get("rationale") == binding.get("rationale")
        for candidate in matching_status
    ):
        errors.append(f"{prefix} не совпадает с кандидатом not_applicable в screen_shell_candidates")


def _validate_pool_provenance(
    manifest: dict[str, Any],
    pool: dict[str, Any],
    errors: list[str],
) -> None:
    manifest_version = manifest.get("template_set_version")
    pool_version = pool.get("template_set_version")
    if _requires_shell_integration(manifest_version) and manifest_version != pool_version:
        errors.append(
            "template_set_version в UI manifest и screen pool должен совпадать "
            "для единого происхождения UI-пакета"
        )
    elif pool_version is not None and manifest_version != pool_version:
        errors.append(
            "template_set_version в UI manifest и screen pool должен совпадать "
            "для единого происхождения UI-пакета"
        )

def validate_package(
    root: Path,
    errors: list[str],
    framework_root: Path | None = None,
) -> dict[str, Any]:
    """Проверить полный UI-пакет и его cross-artifact traceability."""
    if not _is_directory(root) or root.is_symlink():
        errors.append(f"UI-пакет не найден или является ссылкой: {root}")
        return {"package": str(root), "status": "fail"}
    for required_file in PACKAGE_REQUIRED_FILES:
        if not _is_regular(root / required_file):
            errors.append(f"В UI-пакете отсутствует обязательный файл: {required_file}")
    for required_directory in PACKAGE_REQUIRED_DIRECTORIES:
        if not _is_directory(root / required_directory) or (root / required_directory).is_symlink():
            errors.append(f"В UI-пакете отсутствует обязательный каталог: {required_directory}")
    manifest_path = root / "манифест-спецификации-интерфейса.json"
    pool_path = root / "пул-экранов.json"
    if not _is_regular(manifest_path) or not _is_regular(pool_path):
        return {"package": str(root), "status": "fail"}
    manifest = read_json(manifest_path)
    pool = read_json(pool_path)
    if not isinstance(manifest, dict):
        errors.append("UI manifest должен быть JSON-объектом")
        return {"package": str(root), "status": "fail"}
    if not isinstance(pool, dict):
        errors.append("screen pool должен быть JSON-объектом")
        return {"package": str(root), "status": "fail"}
    contract_version = validate_manifest(manifest_path, errors)
    if not isinstance(contract_version, str) or contract_version not in (
        LEGACY_CONTRACT_VERSION, CURRENT_CONTRACT_VERSION
    ):
        return {"package": str(root), "status": "fail"}
    require_shell_binding = (
        contract_version == CURRENT_CONTRACT_VERSION
        and _requires_shell_integration(manifest.get("template_set_version"))
    )
    pool = validate_pool(
        pool_path,
        errors,
        contract_version,
        require_shell_candidates=require_shell_binding,
        framework_root=framework_root,
    )
    if not isinstance(pool, dict):
        return {"package": str(root), "status": "fail"}
    if contract_version == CURRENT_CONTRACT_VERSION:
        _validate_pool_provenance(manifest, pool, errors)
    screens_value = pool.get("screens")
    screens: list[Any] = screens_value if isinstance(screens_value, list) else []
    pool_screens = {
        screen["screen_id"]: screen
        for screen in screens
        if isinstance(screen, dict) and isinstance(screen.get("screen_id"), str)
    }
    pool_screen_ids = set(pool_screens)
    pattern_candidates = _candidate_map(screens, "pattern_candidates", errors)
    template_candidates = _candidate_map(screens, "template_candidates", errors)
    manifest_screens = manifest.get("screens")
    if not isinstance(manifest_screens, list):
        errors.append("UI manifest должен содержать массив screens")
        manifest_screens = []
    manifest_screen_ids: set[str] = set()
    manifest_screen_map: dict[str, dict[str, Any]] = {}
    for index, screen in enumerate(manifest_screens):
        prefix = f"manifest.screens[{index}]"
        if not isinstance(screen, dict):
            errors.append(f"{prefix} должен быть объектом")
            continue
        _reject_unknown_fields(
            screen,
            {
                "screen_id", "specification", "status", "pattern_refs", "template_refs",
                "reference_artifacts",
            },
            prefix,
            errors,
        )
        screen_id = screen.get("screen_id")
        if not isinstance(screen_id, str) or not screen_id.strip():
            errors.append(f"{prefix}.screen_id обязателен")
            continue
        if screen_id in manifest_screen_ids:
            errors.append(f"Дублирующийся manifest screen_id: {screen_id}")
        manifest_screen_ids.add(screen_id)
        manifest_screen_map[screen_id] = screen
        if screen_id not in pool_screen_ids:
            errors.append(f"{prefix}.screen_id отсутствует в screen pool: {screen_id}")
        specification_path = _safe_relative_path(screen.get("specification"), f"{prefix}.specification", errors)
        if specification_path is not None:
            if specification_path.parts[:1] != ("screens",):
                errors.append(f"{prefix}.specification должен находиться в screens/")
            elif _path_inside(root, specification_path) is None or not _is_regular(root / specification_path):
                errors.append(f"Отсутствует screen specification: {specification_path.as_posix()}")
        if not _is_one_of(screen.get("status"), VALID_STATUSES):
            errors.append(f"{prefix}.status имеет недопустимое значение: {screen.get('status')}")
        _validate_reference_ids(
            screen.get("pattern_refs"), f"{prefix}.pattern_refs", screen_id, pattern_candidates, errors,
            manifest.get("workflow_mode") if contract_version == CURRENT_CONTRACT_VERSION else None,
        )
        _validate_reference_ids(
            screen.get("template_refs"), f"{prefix}.template_refs", screen_id, template_candidates, errors,
            manifest.get("workflow_mode") if contract_version == CURRENT_CONTRACT_VERSION else None,
        )
        if contract_version == CURRENT_CONTRACT_VERSION and "reference_artifacts" not in screen:
            errors.append(f"{prefix}.reference_artifacts отсутствует")
        artifacts = screen.get("reference_artifacts", [])
        if not isinstance(artifacts, list):
            errors.append(f"{prefix}.reference_artifacts должен быть массивом")
        elif contract_version != CURRENT_CONTRACT_VERSION:
            for artifact_index, artifact in enumerate(artifacts):
                artifact_path = artifact.get("path") if isinstance(artifact, dict) else artifact
                artifact_relative = _safe_relative_path(artifact_path, f"{prefix}.reference_artifacts[{artifact_index}]", errors)
                if artifact_relative is not None:
                    if artifact_relative.parts[:1] != ("references",) or _path_inside(root, artifact_relative) is None or not _is_regular(root / artifact_relative):
                        errors.append(f"Некорректный или отсутствующий reference artifact: {artifact_relative.as_posix()}")
    if manifest.get("screen_pool") != "пул-экранов.json":
        errors.append("UI manifest должен ссылаться на пул-экранов.json")
    if contract_version == CURRENT_CONTRACT_VERSION and manifest.get("workflow_mode") != pool.get("workflow_mode"):
        errors.append("workflow_mode UI manifest и screen pool не совпадает")
    if contract_version == CURRENT_CONTRACT_VERSION and manifest.get("status") != pool.get("status"):
        errors.append("status UI manifest и screen pool не совпадает")
    if contract_version == CURRENT_CONTRACT_VERSION:
        for screen_id, screen in manifest_screen_map.items():
            pool_screen = pool_screens.get(screen_id)
            if pool_screen is not None and screen.get("status") != pool_screen.get("status"):
                errors.append(f"status экрана {screen_id} не совпадает в manifest и screen pool")
    required_traceability_screens = (
        {
            screen_id for screen_id, screen in manifest_screen_map.items()
            if screen.get("status") == "confirmed"
        }
        if contract_version == CURRENT_CONTRACT_VERSION and manifest.get("workflow_mode") == "track-integrated"
        else (manifest_screen_ids if contract_version == LEGACY_CONTRACT_VERSION else set())
    )
    _validate_traceability(
        manifest.get("traceability"), manifest_screen_ids, errors, required_traceability_screens
    )
    _validate_gaps(manifest.get("gaps"), errors)
    reference_sets = manifest.get("reference_sets")
    if not isinstance(reference_sets, list):
        errors.append("reference_sets должен быть массивом")
    else:
        reference_artifacts: list[dict[str, Any]] = []
        reference_set_ids: set[str] = set()
        reference_set_paths: set[str] = set()
        for index, reference_set in enumerate(reference_sets):
            prefix = f"reference_sets[{index}]"
            if not isinstance(reference_set, dict):
                errors.append(f"{prefix} должен быть объектом")
                continue
            if contract_version == CURRENT_CONTRACT_VERSION:
                _reject_unknown_fields(
                    reference_set,
                    {"reference_set_id", "path"},
                    prefix,
                    errors,
                )
            reference_set_path = _safe_relative_path(reference_set.get("path"), f"{prefix}.path", errors)
            if reference_set_path is None:
                continue
            reference_set_id = reference_set.get("reference_set_id")
            if contract_version == CURRENT_CONTRACT_VERSION:
                require_string(reference_set_id, f"{prefix}.reference_set_id", errors)
                if isinstance(reference_set_id, str):
                    if reference_set_id in reference_set_ids:
                        errors.append(f"Повторный reference_set_id: {reference_set_id}")
                    reference_set_ids.add(reference_set_id)
            if reference_set_path.as_posix() in reference_set_paths:
                errors.append(f"Повторный reference-set path: {reference_set_path.as_posix()}")
            reference_set_paths.add(reference_set_path.as_posix())
            if reference_set_path.parts[:1] != ("references",) or _path_inside(root, reference_set_path) is None or not _is_directory(root / reference_set_path):
                errors.append(f"Некорректный reference set: {reference_set_path.as_posix()}")
            else:
                reference_artifacts.extend(
                    validate_reference_set(
                        root / reference_set_path,
                        errors,
                        contract_version,
                        reference_set_id if isinstance(reference_set_id, str) else None,
                        require_shell_binding,
                        framework_root,
                        manifest,
                    )
                )
        if contract_version == CURRENT_CONTRACT_VERSION:
            _validate_v2_artifact_links(
                manifest_screen_map, pool_screens, reference_artifacts,
                manifest.get("workflow_mode") if isinstance(manifest.get("workflow_mode"), str) else None,
                require_shell_binding,
                errors,
            )
    return {
        "package": str(root),
        "status": "pass" if not errors else "fail",
        "screen_count": len(manifest_screen_ids),
        "reference_set_count": len(reference_sets) if isinstance(reference_sets, list) else 0,
    }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    framework_root = args.framework_root.absolute() if args.framework_root else _framework_root()
    package_report: dict[str, Any] | None = None
    if args.package:
        package_report = validate_package(args.package.absolute(), errors, framework_root)
    if args.pool:
        pool_data = read_json(args.pool.absolute())
        pool_contract = pool_data.get("contract_version") if isinstance(pool_data, dict) else None
        validate_pool(
            args.pool.absolute(),
            errors,
            pool_contract if isinstance(pool_contract, str) else None,
            framework_root=framework_root,
        )
    if args.manifest:
        validate_manifest(args.manifest.absolute(), errors)
    if args.reference_set:
        reference_root = args.reference_set.absolute()
        package_manifest: dict[str, Any] | None = None
        reference_manifest_path = reference_root / "screen-manifest.json"
        reference_manifest = read_json(reference_manifest_path) if _is_regular(reference_manifest_path) else {}
        reference_contract = (
            reference_manifest.get("contract_version") if isinstance(reference_manifest, dict) else None
        )
        reference_set_id = (
            reference_manifest.get("reference_set_id") if isinstance(reference_manifest, dict) else None
        )
        require_shell_binding = False
        if args.manifest:
            package_manifest = read_json(args.manifest.absolute())
            if isinstance(package_manifest, dict):
                require_shell_binding = _requires_shell_integration(
                    package_manifest.get("template_set_version")
                )
        validate_reference_set(
            reference_root,
            errors,
            reference_contract if isinstance(reference_contract, str) else None,
            reference_set_id if isinstance(reference_set_id, str) else None,
            require_shell_binding,
            framework_root,
            package_manifest,
        )
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
    validate_parser.add_argument(
        "--framework-root",
        type=Path,
        help="Корень установленного Framework для сверки каталога оболочек; по умолчанию определяется по инструменту",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "inventory":
        result = inventory(args.source.absolute())
    elif args.command == "migrate":
        result = migrate(args.source.absolute(), args.target.absolute(), args.write)
        if args.report:
            fs_boundary.mkdirs(args.report.parent)
            report_bytes = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            try:
                fs_boundary.write_bytes(args.report, report_bytes)
            except FileNotFoundError:
                fs_boundary.write_bytes(args.report, report_bytes, create_only=True)
    else:
        result = validate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UiReferenceError, OSError, UnicodeError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
