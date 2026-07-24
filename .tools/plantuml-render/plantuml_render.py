#!/usr/bin/env python3
"""Рендеринг PlantUML и BPMN диаграмм через Kroki-compatible endpoint."""

import argparse
import base64
import sys
import zlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT = 30
RUNTIME_ENV_FILE = Path(__file__).with_name(".env")
RUNTIME_ENV_KEYS = (
    "KROKI_IMAGE",
    "KROKI_BPMN_IMAGE",
    "KROKI_PORT",
    "KROKI_BPMN_PNG_PORT",
    "KROKI_BPMN_PNG_URL",
    "KROKI_BASE_URL",
    "KROKI_TIMEOUT",
    "KROKI_MAX_URI_LENGTH",
    "PLANTUML_LIMIT_SIZE",
)
FILE_DIAGRAM_TYPES = {
    ".plantuml": "plantuml",
    ".bpmn": "bpmn",
    ".dot": "graphviz",
}


def load_runtime_env():
    """Load and validate the production configuration next to this script."""
    if not RUNTIME_ENV_FILE.is_file():
        raise ValueError(
            f"Production configuration is missing: {RUNTIME_ENV_FILE}. "
            "Create it from .env.example."
        )

    values = {}
    with RUNTIME_ENV_FILE.open("r", encoding="utf-8") as env_file:
        for line_number, raw_line in enumerate(env_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not key:
                raise ValueError(
                    f"Invalid production configuration line {line_number}. "
                    "Expected KEY=VALUE."
                )
            values[key] = value.strip().strip('"').strip("'")

    missing_keys = [key for key in RUNTIME_ENV_KEYS if not values.get(key)]
    if missing_keys:
        raise ValueError(
            "Production configuration is incomplete. Missing: "
            + ", ".join(missing_keys)
        )

    return values


def encode_plantuml(source):
    """Encode PlantUML source for Kroki API."""
    compressed = zlib.compress(source.encode("utf-8"), 9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def normalize_kroki_url(url):
    """Return Kroki URL without trailing slash and with basic validation."""
    normalized = (url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"Invalid Kroki URL '{url}'. Use full URL, e.g. "
            f"'https://kroki.io' or 'http://localhost:8000'."
        )
    return normalized


def get_timeout(value):
    """Validate timeout value and return int seconds."""
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timeout '{value}'. Use a positive integer.") from exc

    if timeout <= 0:
        raise ValueError("Timeout must be greater than 0.")
    return timeout


def get_bpmn_png_url(value, kroki_url):
    """Определяет URL локального сервиса растеризации BPMN SVG."""
    if value:
        return normalize_kroki_url(value)

    parsed = urlparse(kroki_url)
    if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port == 8000:
        return f"{parsed.scheme}://{parsed.hostname}:8001"
    return None


def get_diagram_type(file_path):
    """Возвращает тип диаграммы по расширению файла."""
    return FILE_DIAGRAM_TYPES.get(file_path.suffix.lower())


def render_file(
    file_path,
    diagram_type,
    kroki_url,
    bpmn_png_url,
    output_format="png",
    timeout=DEFAULT_TIMEOUT,
    dry_run=False,
):
    """Рендерит один файл поддерживаемого типа диаграммы."""
    try:
        with open(file_path, "r", encoding="utf-8") as input_file:
            source = input_file.read()

        if dry_run:
            print(
                f"[DRY-RUN] Would render {diagram_type}: {file_path} via {kroki_url}",
                file=sys.stderr,
            )
            return 2

        if diagram_type == "plantuml":
            encoded = encode_plantuml(source)
            url = f"{kroki_url}/plantuml/{output_format}/{encoded}"
            req = Request(url, headers={"User-Agent": "plantuml-render-tool/1.2"})
        elif diagram_type == "bpmn":
            url = f"{kroki_url}/bpmn/svg"
            req = Request(
                url,
                data=source.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "User-Agent": "plantuml-render-tool/1.2",
                },
                method="POST",
            )
        else:
            url = f"{kroki_url}/graphviz/{output_format}"
            req = Request(
                url,
                data=source.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "User-Agent": "plantuml-render-tool/1.4",
                },
                method="POST",
            )

        with urlopen(req, timeout=timeout) as response:
            image_data = response.read()

        if diagram_type == "bpmn" and output_format == "png":
            if not bpmn_png_url:
                raise ValueError(
                    "BPMN supports SVG only in Kroki. Start the local Docker stack "
                    "or set KROKI_BPMN_PNG_URL / --bpmn-png-url."
                )
            rasterizer_request = Request(
                f"{bpmn_png_url}/rasterize",
                data=image_data,
                headers={
                    "Content-Type": "image/svg+xml; charset=utf-8",
                    "User-Agent": "plantuml-render-tool/1.3",
                },
                method="POST",
            )
            with urlopen(rasterizer_request, timeout=timeout) as response:
                image_data = response.read()

        output_path = file_path.with_suffix(f".{output_format}")
        with open(output_path, "wb") as output_file:
            output_file.write(image_data)

        print(
            f"[OK] Rendered {diagram_type}: {file_path} -> {output_path}",
            file=sys.stderr,
        )
        return 0

    except FileNotFoundError:
        print(f"[ERROR] File not found: {file_path}", file=sys.stderr)
        return 1
    except (URLError, HTTPError) as error:
        print(
            f"[ERROR] Network error rendering {file_path} via {kroki_url}: {error}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(f"[ERROR] Error rendering {file_path}: {error}", file=sys.stderr)
        return 1


def find_diagram_files(root_path, requested_type):
    """Ищет поддерживаемые файлы диаграмм рекурсивно."""
    root = Path(root_path)
    if not root.exists():
        print(f"[ERROR] Path does not exist: {root_path}", file=sys.stderr)
        return []

    if root.is_file():
        diagram_type = get_diagram_type(root)
        if diagram_type and (requested_type == "auto" or diagram_type == requested_type):
            return [root]
        return []

    files = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        diagram_type = get_diagram_type(file_path)
        if diagram_type and (requested_type == "auto" or diagram_type == requested_type):
            files.append(file_path)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="Render PlantUML, BPMN and Graphviz diagrams to PNG/SVG via Kroki-compatible API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Render all supported diagrams in current directory (default Kroki endpoint)
  plantuml-render

  # Render files in a specific directory
  plantuml-render --path docs/requirements/

  # Use local Kroki endpoint
  plantuml-render --kroki-url http://localhost:8000

  # Dry-run (check what would be rendered)
  plantuml-render --dry-run

  # Render to SVG format
  plantuml-render --format svg

  # Render a BPMN file via a local Kroki endpoint
  plantuml-render --kroki-url http://localhost:8000 --path process.bpmn

  # Render a DOT finite-state graph via a local Kroki endpoint
  plantuml-render --kroki-url http://localhost:8000 --diagram-type graphviz --path normative-order.dot

Exit codes:
  0 - Success
  1 - Error
  2 - Warning (e.g., dry-run)
        """,
    )

    parser.add_argument(
        "--path",
        "-p",
        default=".",
        help="Path to a .plantuml/.bpmn/.dot file or directory (default: current directory)",
    )
    parser.add_argument(
        "--diagram-type",
        "--type",
        dest="diagram_type",
        choices=["auto", "plantuml", "bpmn", "graphviz"],
        default="auto",
        help="Diagram type filter (default: auto-detect by file extension)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["png", "svg"],
        default="png",
        help="Output format (default: png)",
    )
    parser.add_argument(
        "--kroki-url",
        default=None,
        help=(
            "Kroki base URL. By default, KROKI_BASE_URL is read from "
            ".tools/plantuml-render/.env."
        ),
    )
    parser.add_argument(
        "--timeout",
        default=None,
        help=(
            "HTTP timeout in seconds. By default, KROKI_TIMEOUT is read "
            "from .tools/plantuml-render/.env."
        ),
    )
    parser.add_argument(
        "--bpmn-png-url",
        default=None,
        help=(
            "URL of the local BPMN SVG-to-PNG service. By default, "
            "KROKI_BPMN_PNG_URL is read from .tools/plantuml-render/.env."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be rendered without actual rendering",
    )

    args = parser.parse_args()

    try:
        runtime_env = load_runtime_env()
        kroki_url = normalize_kroki_url(
            args.kroki_url or runtime_env["KROKI_BASE_URL"]
        )
        timeout = get_timeout(args.timeout or runtime_env["KROKI_TIMEOUT"])
        bpmn_png_url = get_bpmn_png_url(
            args.bpmn_png_url or runtime_env["KROKI_BPMN_PNG_URL"],
            kroki_url,
        )
    except ValueError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    files = find_diagram_files(args.path, args.diagram_type)
    if not files:
        print(
            f"No supported diagram files found in: {args.path}. "
            "Supported extensions: .plantuml, .bpmn, .dot",
            file=sys.stderr,
        )
        return 1

    print(f"Found {len(files)} diagram file(s)", file=sys.stderr)
    print(f"Using Kroki endpoint: {kroki_url}", file=sys.stderr)

    exit_codes = []
    for file_path in files:
        code = render_file(
            file_path=file_path,
            diagram_type=get_diagram_type(file_path),
            kroki_url=kroki_url,
            bpmn_png_url=bpmn_png_url,
            output_format=args.format,
            timeout=timeout,
            dry_run=args.dry_run,
        )
        exit_codes.append(code)

    if all(code == 0 for code in exit_codes):
        return 0
    if any(code == 1 for code in exit_codes):
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
