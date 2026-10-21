#!/usr/bin/env python3
"""Генерация UI-макетов из явных решений UI-пакета и библиотеки оболочек."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


FRAMEWORK_URL = "https://github.com/Druk83/sdd-template.git"
UI_PATTERNS_URL = "https://github.com/Druk83/ui-patterns.git"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ScaffoldError(RuntimeError):
    """Ошибка проверки входного UI-пакета или безопасной генерации."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScaffoldError(f"Не удалось прочитать {label}: {error}") from error
    if not isinstance(value, dict):
        raise ScaffoldError(f"{label} должен быть JSON-объектом")
    return value


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ScaffoldError(f"{label} должен быть непустым относительным путём")
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    windows_candidate = PureWindowsPath(normalized)
    if (
        candidate.is_absolute()
        or windows_candidate.is_absolute()
        or windows_candidate.drive
        or ".." in candidate.parts
        or not candidate.parts
    ):
        raise ScaffoldError(f"{label} выходит за разрешённый каталог: {value}")
    if any(part in {"", "."} for part in candidate.parts):
        raise ScaffoldError(f"{label} содержит недопустимый компонент: {value}")
    return candidate


def _inside(root: Path, relative: PurePosixPath, label: str) -> Path:
    target = root.joinpath(*relative.parts).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ScaffoldError(f"{label} выходит за разрешённый каталог: {relative.as_posix()}")
    return target


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScaffoldError(f"{label} должен быть непустой строкой")
    return value


def _as_map(items: Any, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ScaffoldError(f"{field} должен быть массивом")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ScaffoldError(f"{field}[{index}] должен быть объектом")
        item_id = _require_string(item.get("screen_id"), f"{field}[{index}].screen_id")
        if item_id in result:
            raise ScaffoldError(f"Повторный screen_id в {field}: {item_id}")
        result[item_id] = item
    return result


def _shell_file(shells_root: Path, value: Any, label: str) -> Path:
    relative = _safe_relative(value, label)
    path = _inside(shells_root, relative, label)
    if not path.is_file():
        raise ScaffoldError(f"Файл библиотеки оболочек не найден: {relative.as_posix()}")
    return path


def _shell_stylesheet(shells_root: Path, shell_page: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ScaffoldError(f"{label} должен быть непустым относительным путём")
    candidate = PurePosixPath(value.replace("\\", "/"))
    windows_candidate = PureWindowsPath(value)
    if candidate.is_absolute() or windows_candidate.is_absolute() or windows_candidate.drive:
        raise ScaffoldError(f"{label} не может быть абсолютным путём")
    path = (shell_page.parent / Path(*candidate.parts)).resolve()
    resolved_root = shells_root.resolve()
    if resolved_root not in path.parents or not path.is_file():
        raise ScaffoldError(f"{label} выходит за библиотеку или файл не найден")
    return path


def _validate_provenance(
    package_manifest: dict[str, Any],
    screen_manifest: dict[str, Any],
    package_version: str,
) -> tuple[str, str]:
    template_version = package_manifest.get("template_set_version")
    source_url = package_manifest.get("source_url")
    revision = package_manifest.get("revision")
    if not isinstance(template_version, str) or not SEMVER_PATTERN.fullmatch(template_version):
        raise ScaffoldError("UI manifest.template_set_version должен иметь формат X.Y.Z")
    if source_url != UI_PATTERNS_URL:
        raise ScaffoldError("UI manifest.source_url должен указывать на официальный ui-patterns")
    if not isinstance(revision, str) or not revision.strip():
        raise ScaffoldError("UI manifest.revision обязателен")
    if template_version != package_version:
        raise ScaffoldError("Версия ui-patterns в screen pool и UI manifest не совпадает")

    for field, expected in (
        ("template_set_version", template_version),
        ("source_url", source_url),
        ("revision", revision),
    ):
        recorded = screen_manifest.get(field)
        if recorded != expected:
            raise ScaffoldError(f"screen-manifest.{field} не совпадает с UI manifest")
    return template_version, revision


def _validate_output_path(value: Any, screen_id: str, viewport_id: str) -> PurePosixPath:
    relative = _safe_relative(value, "artifact.path")
    expected = ("screens", screen_id, viewport_id, "index.html")
    if relative.parts != expected:
        raise ScaffoldError(
            "artifact.path должен иметь вид "
            f"screens/{screen_id}/{viewport_id}/index.html"
        )
    return relative


def _equal_geometry(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return all(left.get(key) == right.get(key) for key in ("width", "height", "unit", "orientation"))


def _render_artifact(
    page_source: str,
    artifact_path: PurePosixPath,
    screen_id: str,
    artifact_ids: list[str],
    shell_id: str,
    viewport_id: str,
    viewport: dict[str, Any],
) -> str:
    if 'data-slot-id="screen-content"' not in page_source:
        raise ScaffoldError(f"Шаблон оболочки {shell_id} не содержит обязательный слот screen-content")
    link = re.compile(r'(<link\s+rel="stylesheet"\s+href=")[^"]+("\s*/?>)')
    rendered, count = link.subn(r"\1shell.css\2", page_source, count=1)
    if count != 1:
        raise ScaffoldError(f"Шаблон оболочки {shell_id} не содержит ожидаемую ссылку на CSS")
    body = re.compile(r"<body\b([^>]*)>", re.IGNORECASE)
    width = viewport.get("width")
    height = viewport.get("height")
    body_attributes = (
        f' data-reference-artifact="true" '
        f'style="--viewport-width: {width}px; --viewport-height: {height}px"'
    )
    rendered, count = body.subn(
        lambda match: f"<body{match.group(1)}{body_attributes}>",
        rendered,
        count=1,
    )
    if count != 1:
        raise ScaffoldError(f"Шаблон оболочки {shell_id} не содержит элемент body")
    head_end = re.compile(r"</head\s*>", re.IGNORECASE)
    rendered, count = head_end.subn('<link rel="icon" href="data:,">\n</head>', rendered, count=1)
    if count != 1:
        raise ScaffoldError(f"Шаблон оболочки {shell_id} не содержит закрывающий head")
    canvas = re.compile(r'(<main\b[^>]*data-shell-id="[^"]+"[^>]*data-viewport-id="[^"]+")')
    escaped_screen = html.escape(screen_id, quote=True)
    escaped_artifacts = html.escape(",".join(artifact_ids), quote=True)
    rendered, count = canvas.subn(
        rf'\1 data-screen-id="{escaped_screen}" data-artifact-ids="{escaped_artifacts}"',
        rendered,
        count=1,
    )
    if count != 1 or viewport_id not in rendered:
        raise ScaffoldError(f"Не удалось связать HTML-шаблон с {screen_id}/{viewport_id}")
    return rendered


def _render_artifact_css(css_source: str) -> str:
    return (
        css_source.rstrip()
        + '\n\n'
        + '/* Сброс презентационной страницы: артефакт показывает только viewport. */\n'
        + 'body[data-reference-artifact="true"] {\n'
        + '  width: var(--viewport-width);\n'
        + '  height: var(--viewport-height);\n'
        + '  min-width: var(--viewport-width);\n'
        + '  min-height: var(--viewport-height);\n'
        + '  margin: 0;\n'
        + '  padding: 0;\n'
        + '  overflow: hidden;\n'
        + '  background: #fff;\n'
        + '}\n'
        + 'body[data-reference-artifact="true"] > .preview-header,\n'
        + 'body[data-reference-artifact="true"] > .preview-footer {\n'
        + '  display: none;\n'
        + '}\n'
        + 'body[data-reference-artifact="true"] > .viewport-canvas {\n'
        + '  margin: 0;\n'
        + '}\n'
    )


def build_plan(
    package_root: Path,
    reference_set_id: str,
    framework_root: Path,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    framework_root = framework_root.resolve()
    if not package_root.is_dir():
        raise ScaffoldError(f"UI-пакет не найден: {package_root}")

    package_manifest = _read_json(package_root / "манифест-спецификации-интерфейса.json", "UI manifest")
    if package_manifest.get("contract_version") != "2":
        raise ScaffoldError("Генератор поддерживает только UI manifest contract_version 2")
    if package_manifest.get("source_url") != UI_PATTERNS_URL:
        raise ScaffoldError("UI manifest.source_url должен указывать на официальный ui-patterns")
    if package_manifest.get("workflow_mode") not in {"early-prototype", "track-integrated"}:
        raise ScaffoldError("UI manifest.workflow_mode имеет недопустимое значение")

    pool_relative = _safe_relative(package_manifest.get("screen_pool"), "UI manifest.screen_pool")
    pool_path = _inside(package_root, pool_relative, "UI manifest.screen_pool")
    pool = _read_json(pool_path, "screen pool")
    if pool.get("contract_version") != "2":
        raise ScaffoldError("Генератор поддерживает только screen pool contract_version 2")
    if pool.get("workflow_mode") != package_manifest.get("workflow_mode"):
        raise ScaffoldError("workflow_mode в screen pool и UI manifest не совпадает")

    reference_sets = package_manifest.get("reference_sets")
    if not isinstance(reference_sets, list):
        raise ScaffoldError("UI manifest.reference_sets должен быть массивом")
    matching_sets = [
        item for item in reference_sets
        if isinstance(item, dict) and item.get("reference_set_id") == reference_set_id
    ]
    if len(matching_sets) != 1:
        raise ScaffoldError(f"reference_set_id должен встречаться ровно один раз: {reference_set_id}")
    reference_relative = _safe_relative(matching_sets[0].get("path"), "reference_set.path")
    reference_root = _inside(package_root, reference_relative, "reference_set.path")
    if not reference_root.is_dir():
        raise ScaffoldError(f"Каталог reference-set не найден: {reference_relative.as_posix()}")
    screen_manifest = _read_json(reference_root / "screen-manifest.json", "screen-manifest.json")
    if screen_manifest.get("contract_version") != "2" or screen_manifest.get("schema_version") != "2.0":
        raise ScaffoldError("Генератор поддерживает только screen-manifest contract_version 2")
    if screen_manifest.get("reference_set_id") != reference_set_id:
        raise ScaffoldError("reference_set_id в screen-manifest не совпадает с UI manifest")

    template_version, ui_revision = _validate_provenance(
        package_manifest,
        screen_manifest,
        str(pool.get("template_set_version", "")),
    )
    if tuple(int(part) for part in template_version.split(".")) < (0, 3, 1):
        raise ScaffoldError("Генерация оболочек требует UI-пакет с ui-patterns 0.3.1 или новее")

    release_manifest = _read_json(framework_root / "release-manifest.json", "Framework release-manifest.json")
    if release_manifest.get("package_id") != "sdd-template":
        raise ScaffoldError("release-manifest.json не описывает SDD Framework")
    source_commit = release_manifest.get("source_commit")
    if not isinstance(source_commit, str) or not COMMIT_PATTERN.fullmatch(source_commit):
        raise ScaffoldError("release-manifest.json не содержит точный source_commit")

    shells_root = framework_root / ".tools" / "ui-screen-scaffold" / "shells"
    library = _read_json(shells_root / "shell-library.json", "shell-library.json")
    shell_entries = library.get("shells")
    if not isinstance(shell_entries, list):
        raise ScaffoldError("shell-library.json.shells должен быть массивом")
    shells_by_id = {
        item.get("shell_id"): item
        for item in shell_entries
        if isinstance(item, dict) and isinstance(item.get("shell_id"), str)
    }
    if len(shells_by_id) != len(shell_entries):
        raise ScaffoldError("shell-library.json содержит некорректные или повторные shell_id")

    package_screens = _as_map(package_manifest.get("screens"), "UI manifest.screens")
    pool_screens = _as_map(pool.get("screens"), "screen pool.screens")
    artifacts = screen_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ScaffoldError("screen-manifest.artifacts должен быть массивом")

    workflow_mode = package_manifest["workflow_mode"]
    shell_integration_required = True
    writes: dict[str, str] = {}
    outputs: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    reported_reference_gaps: set[tuple[str, str]] = set()
    if not artifacts:
        gaps.append(
            {
                "status": "gap",
                "reason": "В screen-manifest нет явно заданных артефактов для генерации.",
                "decision_needed": "Добавить выбранные варианты либо явно зафиксировать отсутствие визуальных экранов.",
            }
        )
    artifact_ids: set[str] = set()
    path_groups: dict[str, list[dict[str, Any]]] = {}

    for index, artifact in enumerate(artifacts):
        label = f"screen-manifest.artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise ScaffoldError(f"{label} должен быть объектом")
        artifact_id = _require_string(artifact.get("artifact_id"), f"{label}.artifact_id")
        if artifact_id in artifact_ids:
            raise ScaffoldError(f"Повторный artifact_id: {artifact_id}")
        artifact_ids.add(artifact_id)
        screen_id = _require_string(artifact.get("screen_id"), f"{label}.screen_id")
        role = _require_string(artifact.get("role"), f"{label}.role")
        state = _require_string(artifact.get("state"), f"{label}.state")
        screen = package_screens.get(screen_id)
        pool_screen = pool_screens.get(screen_id)
        if screen is None or pool_screen is None:
            raise ScaffoldError(f"{label} ссылается на неизвестный экран: {screen_id}")
        roles = pool_screen.get("user_roles")
        if not isinstance(roles, list) or role not in roles:
            raise ScaffoldError(f"{label}.role отсутствует в ролях экрана {screen_id}")
        states = pool_screen.get("states")
        if not isinstance(states, list) or state not in states:
            raise ScaffoldError(f"{label}.state отсутствует в состояниях экрана {screen_id}")

        viewport = artifact.get("viewport")
        if not isinstance(viewport, dict):
            raise ScaffoldError(f"{label}.viewport должен быть объектом")
        viewport_id = _require_string(viewport.get("viewport_id"), f"{label}.viewport.viewport_id")
        viewport_path = _validate_output_path(artifact.get("path"), screen_id, viewport_id)
        viewport_candidates = pool_screen.get("viewport_candidates")
        if not isinstance(viewport_candidates, list):
            raise ScaffoldError(f"screen pool для {screen_id} не содержит viewport_candidates")
        matching_viewports = [
            item for item in viewport_candidates
            if isinstance(item, dict) and item.get("viewport_id") == viewport_id
        ]
        if len(matching_viewports) != 1:
            raise ScaffoldError(f"Viewport {viewport_id} должен встречаться ровно один раз в screen pool")
        pool_viewport = matching_viewports[0]
        if not _equal_geometry(viewport, pool_viewport):
            raise ScaffoldError(f"Геометрия artifact {artifact_id} не совпадает с screen pool")

        binding = artifact.get("shell_binding")
        if not isinstance(binding, dict):
            raise ScaffoldError(f"{label}.shell_binding должен быть объектом")
        binding_status = binding.get("status")
        if binding_status in {"gap", "not_applicable"}:
            gaps.append(
                {
                    "artifact_id": artifact_id,
                    "screen_id": screen_id,
                    "viewport_id": viewport_id,
                    "status": binding_status,
                    "reason": binding.get("reason") or binding.get("rationale"),
                    "decision_needed": binding.get("decision_needed"),
                }
            )
            continue
        if binding_status not in {"selected", "proposed"}:
            raise ScaffoldError(f"{label}.shell_binding.status недопустим")
        if workflow_mode == "track-integrated" and binding_status != "selected":
            raise ScaffoldError(f"track-integrated требует selected shell для {artifact_id}")
        if workflow_mode == "track-integrated" and (
            screen.get("status") != "confirmed" or pool_viewport.get("status") != "confirmed"
        ):
            raise ScaffoldError(f"track-integrated требует подтверждённые экран и viewport для {artifact_id}")

        required_binding = (
            "catalog_url", "catalog_revision", "shell_id", "shell_version", "viewport_id", "shell_viewport"
        )
        for field in required_binding:
            if field not in binding:
                raise ScaffoldError(f"{label}.shell_binding.{field} обязателен для {binding_status}")
        if binding.get("catalog_url") != FRAMEWORK_URL:
            raise ScaffoldError(f"{label}.shell_binding.catalog_url не указывает на библиотеку Framework")
        if binding.get("catalog_revision") != source_commit:
            raise ScaffoldError(f"{label}.shell_binding.catalog_revision не совпадает с Framework source_commit")
        if binding.get("viewport_id") != viewport_id:
            raise ScaffoldError(f"{label}.shell_binding.viewport_id не совпадает с viewport")
        if not _equal_geometry(binding.get("shell_viewport"), viewport):
            raise ScaffoldError(f"Геометрия shell_binding не совпадает с artifact {artifact_id}")

        candidates = pool_viewport.get("screen_shell_candidates")
        if not isinstance(candidates, list):
            raise ScaffoldError(f"Viewport {viewport_id} не содержит screen_shell_candidates")
        matching_candidates = [
            item for item in candidates
            if isinstance(item, dict)
            and item.get("status") == binding_status
            and item.get("shell_id") == binding.get("shell_id")
            and item.get("shell_version") == binding.get("shell_version")
            and item.get("catalog_url") == binding.get("catalog_url")
            and item.get("catalog_revision") == binding.get("catalog_revision")
            and _equal_geometry(item.get("shell_viewport"), binding.get("shell_viewport"))
        ]
        if not matching_candidates:
            raise ScaffoldError(f"Привязка {artifact_id} не совпадает с кандидатом того же viewport в screen pool")
        if binding_status == "selected" and pool_viewport.get("status") != "confirmed":
            raise ScaffoldError(f"selected shell допускается только для подтверждённого viewport: {viewport_id}")

        shell_id = _require_string(binding.get("shell_id"), f"{label}.shell_binding.shell_id")
        shell = shells_by_id.get(shell_id)
        if shell is None:
            raise ScaffoldError(f"Неизвестный shell_id в библиотеке Framework: {shell_id}")
        for field in ("shell_version", "viewport_id", "width", "height", "unit", "orientation"):
            expected_value = binding.get("shell_version") if field == "shell_version" else (
                viewport_id if field == "viewport_id" else viewport.get(field)
            )
            if shell.get(field) != expected_value:
                raise ScaffoldError(f"Оболочка {shell_id}.{field} не совпадает с выбранной привязкой")

        pattern_refs = screen.get("pattern_refs", [])
        template_refs = screen.get("template_refs", [])
        if not isinstance(pattern_refs, list) or not isinstance(template_refs, list):
            raise ScaffoldError(f"pattern_refs/template_refs экрана {screen_id} должны быть массивами")
        for field, expected in (("pattern_refs", pattern_refs), ("template_refs", template_refs)):
            if artifact.get(field) != expected:
                raise ScaffoldError(f"{label}.{field} должен совпадать со ссылками экрана в UI manifest")
            if not expected and (screen_id, field) not in reported_reference_gaps:
                candidate_field = "pattern_candidates" if field == "pattern_refs" else "template_candidates"
                reference_candidates = pool_screen.get(candidate_field, [])
                statuses = [
                    item.get("status") for item in reference_candidates if isinstance(item, dict)
                ] if isinstance(reference_candidates, list) else []
                if not statuses or any(status != "not_applicable" for status in statuses):
                    gaps.append(
                        {
                            "screen_id": screen_id,
                            "area": field,
                            "status": "gap",
                            "reason": f"Для {screen_id} нет выбранных ссылок {field}.",
                            "decision_needed": "Выбрать применимые элементы либо явно подтвердить not_applicable.",
                        }
                    )
                reported_reference_gaps.add((screen_id, field))

        page_source = _shell_file(shells_root, shell.get("path"), f"shell {shell_id}.path").read_text(encoding="utf-8")
        shell_page = _shell_file(shells_root, shell.get("path"), f"shell {shell_id}.path")
        css_source = _shell_stylesheet(
            shells_root,
            shell_page,
            shell.get("stylesheet"),
            f"shell {shell_id}.stylesheet",
        ).read_text(encoding="utf-8")
        path_key = viewport_path.as_posix()
        path_groups.setdefault(path_key, []).append(
            {
                "artifact": artifact,
                "artifact_id": artifact_id,
                "screen_id": screen_id,
                "role": role,
                "state": state,
                "viewport": viewport,
                "viewport_id": viewport_id,
                "binding": binding,
                "shell": shell,
                "page_source": page_source,
                "css_source": css_source,
                "pattern_refs": pattern_refs,
                "template_refs": template_refs,
            }
        )

    for path_key, entries in path_groups.items():
        first = entries[0]
        for entry in entries[1:]:
            if any(
                entry[key] != first[key]
                for key in ("screen_id", "viewport_id", "binding", "shell", "page_source", "css_source")
            ):
                raise ScaffoldError(f"Общий путь {path_key} содержит несовместимые варианты")
            if not isinstance(entry["artifact"].get("target"), dict):
                raise ScaffoldError(f"Общий путь {path_key} требует target для каждого артефакта")
        if len(entries) > 1:
            targets = [
                (entry["artifact"]["target"].get("kind"), entry["artifact"]["target"].get("value"))
                for entry in entries
            ]
            if len(set(targets)) != len(targets):
                raise ScaffoldError(f"Общий путь {path_key} содержит повторные target")

        target_relative = PurePosixPath(path_key)
        parent = target_relative.parent
        output_paths = [
            target_relative,
            parent / "shell.css",
            parent / "reference-manifest.json",
            parent / "README.md",
        ]
        output_ids = [entry["artifact_id"] for entry in entries]
        rendered_page = _render_artifact(
            first["page_source"],
            target_relative,
            first["screen_id"],
            output_ids,
            first["binding"]["shell_id"],
            first["viewport_id"],
            first["viewport"],
        )
        local_manifest = {
            "schema_version": "1.0",
            "reference_set_id": reference_set_id,
            "screen_id": first["screen_id"],
            "viewport": first["viewport"],
            "shell_binding": first["binding"],
            "ui_patterns": {
                "template_set_version": template_version,
                "source_url": UI_PATTERNS_URL,
                "revision": ui_revision,
                "pattern_refs": first["pattern_refs"],
                "template_refs": first["template_refs"],
            },
            "artifacts": [
                {
                    "artifact_id": entry["artifact_id"],
                    "role": entry["role"],
                    "state": entry["state"],
                    "target": entry["artifact"].get("target"),
                }
                for entry in entries
            ],
        }
        variant_lines = "\n".join(
            f"- `{entry['artifact_id']}` — роль `{entry['role']}`, состояние `{entry['state']}`"
            for entry in entries
        )
        local_readme = (
            f"# {first['screen_id']} — {first['viewport_id']}\n\n"
            f"Открой `index.html` в браузере. Область просмотра: "
            f"{first['viewport']['width']} × {first['viewport']['height']} CSS px, "
            f"{first['viewport']['orientation']}. Оболочка: `{first['binding']['shell_id']}` "
            f"(`{first['binding']['shell_version']}`).\n\n"
            "Заполнитель `screen-content` предназначен для композиции по спецификации "
            "экрана и выбранным UI-паттернам/шаблонам. Генератор не добавляет продуктовый контент.\n\n"
            f"## Представления\n\n{variant_lines}\n"
        )
        writes[(parent / "index.html").as_posix()] = rendered_page
        writes[(parent / "shell.css").as_posix()] = _render_artifact_css(first["css_source"])
        writes[(parent / "reference-manifest.json").as_posix()] = (
            json.dumps(local_manifest, ensure_ascii=False, indent=2) + "\n"
        )
        writes[(parent / "README.md").as_posix()] = local_readme
        outputs.append(
            {
                "screen_id": first["screen_id"],
                "viewport_id": first["viewport_id"],
                "shell_id": first["binding"]["shell_id"],
                "artifact_ids": output_ids,
                "path": (reference_relative / parent / "index.html").as_posix(),
            }
        )

    conflicts = []
    for relative_value in writes:
        relative = _safe_relative(relative_value, "generated path")
        target = _inside(reference_root, relative, "generated path")
        if target.exists():
            conflicts.append(relative.as_posix())
    if conflicts:
        raise ScaffoldError("Целевые файлы уже существуют; запись остановлена без изменений: " + ", ".join(conflicts))

    return {
        "status": "ready_with_gaps" if outputs and gaps else ("ready" if outputs else "gap"),
        "package": str(package_root),
        "reference_set_id": reference_set_id,
        "workflow_mode": workflow_mode,
        "framework_catalog": {"url": FRAMEWORK_URL, "revision": source_commit},
        "ui_patterns": {
            "template_set_version": template_version,
            "source_url": UI_PATTERNS_URL,
            "revision": ui_revision,
        },
        "outputs": outputs,
        "gaps": gaps,
        "files": sorted((reference_relative / PurePosixPath(value)).as_posix() for value in writes),
        "_writes": writes,
        "_reference_root": reference_root,
    }


def write_plan(plan: dict[str, Any]) -> list[str]:
    reference_root = plan["_reference_root"]
    writes = plan["_writes"]
    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        for relative_value, content in writes.items():
            relative = _safe_relative(relative_value, "generated path")
            target = _inside(reference_root, relative, "generated path")
            missing_parents = []
            parent = target.parent
            while parent != reference_root and not parent.exists():
                missing_parents.append(parent)
                parent = parent.parent
            for directory in reversed(missing_parents):
                directory.mkdir(exist_ok=False)
                created_directories.append(directory)
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                created_files.append(target)
                stream.write(content)
    except OSError as error:
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass
        for path in reversed(created_directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise ScaffoldError(f"Не удалось записать весь набор файлов; созданные файлы откатили: {error}") from error
    return [path.relative_to(reference_root).as_posix() for path in created_files]


def _framework_root_from_tool() -> Path:
    return Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Создание UI-макетов на основе подтверждённых оболочек Framework")
    subparsers = root.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="Проверить план и при --write создать HTML/CSS-оболочки")
    generate.add_argument("--package", type=Path, required=True, help="Корневой каталог UI-пакета проекта")
    generate.add_argument("--reference-set", required=True, help="Идентификатор набора из UI manifest")
    generate.add_argument(
        "--framework-root",
        type=Path,
        default=_framework_root_from_tool(),
        help="Корень установленного Framework; по умолчанию определяется по расположению инструмента",
    )
    generate.add_argument("--write", action="store_true", help="Записать новые файлы; без флага выполняется dry-run")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        plan = build_plan(args.package, args.reference_set, args.framework_root)
        output = {key: value for key, value in plan.items() if not key.startswith("_")}
        if args.write and plan["_writes"]:
            output["written_files"] = write_plan(plan)
            output["status"] = "written_with_gaps" if plan["gaps"] else "written"
        elif plan["_writes"]:
            output["status"] = "dry-run"
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2 if plan["gaps"] else (2 if output["status"] == "gap" else 0)
    except ScaffoldError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
