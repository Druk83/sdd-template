#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, TextIO, Tuple


DEFAULT_PATHS = [
    "docs",
    "README.md",
    "apps",
    "services",
    "scripts",
    ".manifest",
    ".requirements",
    ".tasks",
    ".issues",
]
DEFAULT_MAX_FILE_SIZE_KB = 1024
SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "coverage",
}

LATIN_MOJIBAKE_RE = re.compile(r"(Гђ|Г‘|Гѓ|Г‚|Гўв‚¬|Гўв‚¬в„ў|Гўв‚¬Е“|Гўв‚¬\x9d|Гўв‚¬вЂњ|Гўв‚¬вЂќ|ГўвЂћ|Гўв‚¬В¦)")
# Частые сигнатуры кракозябр для кириллицы и пунктуации.
# 1) точечные паттерны, часто встречающиеся в репозитории;
# 2) повтор пары [Р|С]+кириллица — типичный след UTF-8/CP1251 mojibake;
# 3) латиница после Р/С — дополнительная эвристика для смешанных искажений.
CYRILLIC_MOJIBAKE_RE = re.compile(r"(?:в„|Р¤Р|Р”Р|(?:[РС][А-Яа-яЁё]){2,}|Р[A-Za-z]|С[A-Za-z])")
STRICT_BROKEN_WORD_RE = re.compile(r"\b(?:мя|сточник|сполнитель)\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check-encoding",
        description="Scan repository for suspicious mojibake encoding artifacts.",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=DEFAULT_PATHS,
        help="Files/directories to scan. Default: docs README.md",
    )
    parser.add_argument(
        "--max-file-size-kb",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE_KB,
        help="Skip files larger than this value in KB. Default: 1024",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable stricter heuristics (may report more false positives).",
    )
    return parser.parse_args()


def collect_files(paths: Iterable[str], max_size_kb: int) -> Tuple[List[Path], List[str]]:
    files: List[Path] = []
    warnings: List[str] = []
    max_size_bytes = max_size_kb * 1024

    for raw in paths:
        path = Path(raw)
        if not path.exists():
            warnings.append(f"Path does not exist: {raw}")
            continue
        if path.is_file():
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.stat().st_size <= max_size_bytes:
                files.append(path)
            continue
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in item.parts):
                continue
            try:
                if item.stat().st_size > max_size_bytes:
                    continue
                files.append(item)
            except OSError:
                continue

    unique_sorted = sorted(set(files), key=lambda p: str(p).lower())
    return unique_sorted, warnings


def is_russian_cyrillic(ch: str) -> bool:
    code = ord(ch)
    return (0x0410 <= code <= 0x044F) or code in (0x0401, 0x0451)


def find_line_issues(line: str, strict: bool = False) -> List[str]:
    issues: List[str] = []
    if "\ufffd" in line:
        issues.append("replacement_char")
    if line.count("\ufffd") >= 2:
        issues.append("replacement_char_run")
    if any((0x0400 <= ord(ch) <= 0x04FF) and not is_russian_cyrillic(ch) for ch in line):
        issues.append("non_ru_cyrillic")
    if LATIN_MOJIBAKE_RE.search(line):
        issues.append("latin_mojibake")
    if CYRILLIC_MOJIBAKE_RE.search(line):
        issues.append("cyrillic_mojibake")
    if strict and STRICT_BROKEN_WORD_RE.search(line):
        issues.append("strict_broken_word")
    return issues


def scan_file(path: Path, strict: bool = False) -> Dict:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"file": str(path), "error": f"read_error: {exc}"}

    if b"\x00" in raw:
        return {"file": str(path), "skipped": "binary_like"}

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {
            "file": str(path),
            "issues": [{"line": 0, "kinds": ["invalid_utf8"], "snippet": str(exc)}],
        }

    issues = []
    for idx, line in enumerate(text.splitlines(), start=1):
        kinds = find_line_issues(line, strict=strict)
        if kinds:
            issues.append({"line": idx, "kinds": kinds, "snippet": line[:220]})

    return {"file": str(path), "issues": issues}


def safe_write_line(message: str, stream: TextIO = sys.stdout) -> None:
    """Печатает строку без падения при несовместимой кодировке консоли."""
    encoding = stream.encoding or "utf-8"
    data = (message + "\n").encode(encoding, errors="backslashreplace")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
    else:
        stream.write(data.decode(encoding, errors="ignore"))


def render_text(results: List[Dict], warnings: List[str]) -> int:
    suspicious_count = 0

    for warning in warnings:
        safe_write_line(f"[WARN] {warning}", stream=sys.stderr)

    for item in results:
        if item.get("skipped"):
            continue
        if item.get("error"):
            safe_write_line(f"[ERROR] {item['file']}: {item['error']}", stream=sys.stderr)
            suspicious_count += 1
            continue
        issues = item.get("issues", [])
        if not issues:
            continue
        suspicious_count += len(issues)
        safe_write_line(f"\n{item['file']}")
        for issue in issues:
            kinds = ",".join(issue["kinds"])
            safe_write_line(f"  L{issue['line']}: [{kinds}] {issue['snippet']}")

    if suspicious_count == 0:
        safe_write_line("No suspicious encoding artifacts found.")
    else:
        safe_write_line(f"\nFound suspicious lines: {suspicious_count}")

    return suspicious_count


def main() -> int:
    args = parse_args()
    files, warnings = collect_files(args.paths, args.max_file_size_kb)
    if not files and warnings:
        for warning in warnings:
            safe_write_line(f"[WARN] {warning}", stream=sys.stderr)
        safe_write_line("No files to scan.", stream=sys.stderr)
        return 2

    results = [scan_file(path, strict=args.strict) for path in files]

    if args.format == "json":
        payload = {"warnings": warnings, "results": results}
        safe_write_line(json.dumps(payload, ensure_ascii=True, indent=2))
        has_issues = any(item.get("issues") for item in results)
        has_errors = any(item.get("error") for item in results)
        return 1 if (has_issues or has_errors) else 0

    suspicious_count = render_text(results, warnings)
    return 1 if suspicious_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
