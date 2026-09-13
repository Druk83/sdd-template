#!/usr/bin/env python3
"""Проверяет H8-документ по выбранному манифесту без изменения файлов."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Literal, TypedDict


RULE_ID_RE = re.compile(r"^#{2,3}\s+([A-Za-z][\w-]*\.H[34]\.\d+)\b", re.MULTILINE)
GAP_ID_RE = re.compile(r"^GAP-\d{3}$")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
UNFINISHED_RE = re.compile(
    r"(?i)(?<!@)\b(?:TODO|FIXME|XXX)\b|<!--\s*@update-after:[^>]+-->|"
    r"\b(?:заполнить|заполняется|будет заполнено)\b"
)


class ValidationResult(TypedDict):
    """Результат проверки документа и манифеста."""

    doc: str
    manifest: str
    status: Literal["PASS", "FAIL"]
    errors: list[str]
    warnings: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="manifest-validator",
        description="Validate an H8 document against a project manifest.",
    )
    parser.add_argument("--doc", required=True, help="Document path to validate.")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Manifest name such as gapmanifest or a path to a manifest.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root used to resolve relative paths. Default: .",
    )
    parser.add_argument(
        "--check-cleanup",
        action="store_true",
        help="Reject unfinished markers in the selected H8 document.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Default: text",
    )
    return parser.parse_args()


def resolve_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def resolve_manifest(root: Path, value: str) -> Path:
    candidate = resolve_path(root, value)
    if candidate.exists():
        return candidate
    name = value[:-3] if value.endswith(".md") else value
    return root / ".manifest" / f"{name}.md"


def read_utf8(path: Path, errors: list[str], label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"{label} not found: {path}")
    except UnicodeDecodeError as exc:
        errors.append(f"{label} is not valid UTF-8: {path} ({exc})")
    except OSError as exc:
        errors.append(f"Cannot read {label.lower()} {path}: {exc}")
    return ""


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if not value.startswith("|"):
        return []
    cells = value.strip("|").split("|")
    return [cell.strip() for cell in cells]


def table_rows(text: str) -> Iterable[tuple[int, list[str]]]:
    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = split_table_row(line)
        if not cells or all(TABLE_SEPARATOR_RE.fullmatch(cell) for cell in cells):
            continue
        yield line_number, cells


def manifest_rule_ids(text: str) -> list[str]:
    return RULE_ID_RE.findall(text)


def manifest_values(text: str, values: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        cells = split_table_row(line)
        if len(cells) < 2:
            continue
        for value in values:
            if value in cells:
                found.add(value)
    return found


def cleanup_errors(text: str) -> list[str]:
    errors: list[str] = []
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if UNFINISHED_RE.search(line):
            errors.append(f"L{line_number}: unfinished marker or instruction")
    return errors


def validate(doc: Path, manifest: Path, check_cleanup: bool) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    manifest_text = read_utf8(manifest, errors, "Manifest")
    doc_text = read_utf8(doc, errors, "Document")

    rule_ids = manifest_rule_ids(manifest_text)
    if manifest_text and not rule_ids:
        errors.append("Manifest has no H3/H4 rule identifiers.")
    if len(rule_ids) != len(set(rule_ids)):
        errors.append("Manifest contains duplicate H3/H4 rule identifiers.")

    if doc_text and not re.search(r"^#\s+\S+", doc_text, re.MULTILINE):
        errors.append("Document has no H1 title.")

    if manifest.stem == "gapmanifest" and doc_text:
        required_headings = (
            "## Gap Tracking",
            "### Статистика",
            "### Открытые пробелы",
            "### История",
        )
        for heading in required_headings:
            if heading not in doc_text:
                errors.append(f"Missing required section: {heading}")

        allowed_criticality = manifest_values(manifest_text, ("HIGH", "MEDIUM", "LOW"))
        allowed_statuses = manifest_values(
            manifest_text, ("OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED", "WONTFIX")
        )
        for line_number, cells in table_rows(doc_text):
            if not cells or not GAP_ID_RE.fullmatch(cells[0]):
                continue
            if len(cells) == 7:
                if allowed_criticality and cells[4] not in allowed_criticality:
                    errors.append(f"L{line_number}: invalid GAP criticality: {cells[4]}")
                if allowed_statuses and cells[6] not in allowed_statuses:
                    errors.append(f"L{line_number}: invalid GAP status: {cells[6]}")
            elif len(cells) != 3:
                errors.append(
                    f"L{line_number}: GAP table row must have 7 or 3 columns, got {len(cells)}"
                )

    if check_cleanup and doc_text:
        errors.extend(cleanup_errors(doc_text))

    return {
        "doc": str(doc),
        "manifest": str(manifest),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
    }


def render(result: ValidationResult, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    status = result["status"]
    errors = result["errors"]
    print(f"{status} ({len(errors)} errors)")
    for error in errors:
        print(f"- {error}")
    for warning in result["warnings"]:
        print(f"WARN: {warning}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    doc = resolve_path(root, args.doc)
    manifest = resolve_manifest(root, args.manifest)
    result = validate(doc, manifest, args.check_cleanup)
    render(result, args.format)
    if result["errors"]:
        return 1
    if result["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
