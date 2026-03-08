#!/usr/bin/env python3
"""
PlantUML Render Tool
Renders .plantuml files to PNG/SVG via a Kroki-compatible endpoint.
"""

import argparse
import base64
import os
import sys
import zlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_KROKI_URL = "https://kroki.io"
DEFAULT_TIMEOUT = 30


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


def render_file(file_path, kroki_url, output_format="png", timeout=DEFAULT_TIMEOUT, dry_run=False):
    """Render a single PlantUML file."""
    try:
        with open(file_path, "r", encoding="utf-8") as input_file:
            source = input_file.read()

        encoded = encode_plantuml(source)
        url = f"{kroki_url}/plantuml/{output_format}/{encoded}"

        if dry_run:
            print(f"[DRY-RUN] Would render: {file_path} via {kroki_url}", file=sys.stderr)
            return 2

        req = Request(url, headers={"User-Agent": "plantuml-render-tool/1.1"})
        with urlopen(req, timeout=timeout) as response:
            image_data = response.read()

        output_path = file_path.with_suffix(f".{output_format}")
        with open(output_path, "wb") as output_file:
            output_file.write(image_data)

        print(f"[OK] Rendered: {file_path} -> {output_path}", file=sys.stderr)
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


def find_plantuml_files(root_path):
    """Find all .plantuml files recursively."""
    root = Path(root_path)
    if not root.exists():
        print(f"[ERROR] Path does not exist: {root_path}", file=sys.stderr)
        return []

    if root.is_file():
        return [root] if root.suffix == ".plantuml" else []

    return list(root.rglob("*.plantuml"))


def main():
    parser = argparse.ArgumentParser(
        description="Render PlantUML diagrams to PNG/SVG via Kroki-compatible API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Render all .plantuml files in current directory (default Kroki endpoint)
  plantuml-render

  # Render files in a specific directory
  plantuml-render --path docs/requirements/

  # Use local Kroki endpoint
  plantuml-render --kroki-url http://localhost:8000

  # Dry-run (check what would be rendered)
  plantuml-render --dry-run

  # Render to SVG format
  plantuml-render --format svg

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
        help="Path to .plantuml file or directory (default: current directory)",
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
        default=os.getenv("KROKI_BASE_URL", DEFAULT_KROKI_URL),
        help=(
            "Kroki base URL. Can be set via KROKI_BASE_URL "
            f"(default: {DEFAULT_KROKI_URL})"
        ),
    )
    parser.add_argument(
        "--timeout",
        default=os.getenv("KROKI_TIMEOUT", str(DEFAULT_TIMEOUT)),
        help=(
            "HTTP timeout in seconds. Can be set via KROKI_TIMEOUT "
            f"(default: {DEFAULT_TIMEOUT})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be rendered without actual rendering",
    )

    args = parser.parse_args()

    try:
        kroki_url = normalize_kroki_url(args.kroki_url)
        timeout = get_timeout(args.timeout)
    except ValueError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    files = find_plantuml_files(args.path)
    if not files:
        print(f"No .plantuml files found in: {args.path}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} .plantuml file(s)", file=sys.stderr)
    print(f"Using Kroki endpoint: {kroki_url}", file=sys.stderr)

    exit_codes = []
    for file_path in files:
        code = render_file(
            file_path=file_path,
            kroki_url=kroki_url,
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
