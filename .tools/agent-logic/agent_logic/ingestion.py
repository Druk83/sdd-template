"""Input discovery and UTF-8 provenance capture."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .code_analyzers import CODE_LIKE_SUFFIXES, DEFAULT_ANALYZERS, CodeAnalysis
from .errors import InputError


MAX_FILES = 100
MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_TOTAL_LINES = 100_000
SUPPORTED_SUFFIXES = {".txt", ".md"} | set(CODE_LIKE_SUFFIXES)


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    relative_path: str
    text: str
    size_bytes: int
    line_count: int
    title: str | None
    input_kind: str = "text"
    analysis: CodeAnalysis | None = None

    def as_dict(self) -> dict:
        line_range = {"start": 1, "end": self.line_count} if self.line_count else None
        return {
            "path": str(self.path.resolve()),
            "relative_path": self.relative_path,
            "encoding": "UTF-8",
            "title": self.title,
            "line_range": line_range,
            "fragment": self.text,
            "extraction_method": "file_read_utf8",
            "confidence": 1.0,
            "input_kind": self.input_kind,
            "language": self.analysis.language if self.analysis else None,
        }


@dataclass(frozen=True)
class InputMaterialSet:
    """Normalized input set for one compilation run."""

    compilation_id: str
    sources: tuple[SourceDocument, ...]
    source_count: int
    total_bytes: int

    def __iter__(self):
        yield self.compilation_id
        yield list(self.sources)

    def as_compile_input(self) -> tuple[str, list[SourceDocument]]:
        return self.compilation_id, list(self.sources)

    def as_dict(self) -> dict:
        return {
            "compilationId": self.compilation_id,
            "sources": [source.as_dict() for source in self.sources],
            "source_count": self.source_count,
            "total_bytes": self.total_bytes,
        }



def _title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            value = stripped.lstrip("#").strip()
            if value:
                return value
    return None


def _candidate_files(input_path: Path) -> tuple[Path, list[Path]]:
    if not input_path.exists():
        raise InputError(f"input path does not exist: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise InputError(f"unsupported input extension: {input_path.suffix or '<none>'}")
        return input_path.parent, [input_path]
    if not input_path.is_dir():
        raise InputError(f"input path is not a regular file or directory: {input_path}")
    files = [
        item for item in input_path.rglob("*")
        if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    files.sort(
        key=lambda item: (
            item.relative_to(input_path).as_posix().casefold(),
            item.relative_to(input_path).as_posix(),
        )
    )
    if not files:
        raise InputError(f"no UTF-8 text or Markdown files found under: {input_path}")
    return input_path, files


def load_sources(input_path: str | Path | None = None) -> InputMaterialSet:
    root = Path(input_path) if input_path is not None else Path(".source")
    base, files = _candidate_files(root)
    if len(files) > MAX_FILES:
        raise InputError(f"file limit exceeded: {len(files)} > {MAX_FILES}")

    documents: list[SourceDocument] = []
    total_bytes = 0
    total_lines = 0
    digest = hashlib.sha256()
    for path in files:
        data = path.read_bytes()
        size = len(data)
        if size > MAX_FILE_BYTES:
            raise InputError(f"file size limit exceeded for {path}: {size} > {MAX_FILE_BYTES} bytes")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"input is not valid UTF-8: {path}") from exc
        lines = len(text.splitlines())
        total_bytes += size
        total_lines += lines
        if total_bytes > MAX_TOTAL_BYTES:
            raise InputError(f"total input size limit exceeded: {total_bytes} > {MAX_TOTAL_BYTES} bytes")
        if total_lines > MAX_TOTAL_LINES:
            raise InputError(f"total line limit exceeded: {total_lines} > {MAX_TOTAL_LINES}")
        relative = path.relative_to(base).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        input_kind = "code" if path.suffix.lower() in CODE_LIKE_SUFFIXES else "text"
        analysis = DEFAULT_ANALYZERS.analyze(path, relative, text) if input_kind == "code" else None
        documents.append(SourceDocument(path, relative, text, size, lines, _title(text), input_kind, analysis))
    compilation_id = digest.hexdigest()[:32]
    return InputMaterialSet(
        compilation_id=compilation_id,
        sources=tuple(documents),
        source_count=len(documents),
        total_bytes=total_bytes,
    )
