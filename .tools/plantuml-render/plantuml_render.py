#!/usr/bin/env python3
"""
PlantUML Render Tool
Renders .plantuml files to PNG using Kroki.io API
"""

import argparse
import base64
import os
import sys
import zlib
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


def encode_plantuml(source):
    """Encode PlantUML source for Kroki API"""
    compressed = zlib.compress(source.encode('utf-8'), 9)
    encoded = base64.urlsafe_b64encode(compressed).decode('ascii')
    return encoded


def render_file(file_path, output_format='png', dry_run=False):
    """Render a single PlantUML file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # Encode for Kroki
        encoded = encode_plantuml(source)

        # Kroki API endpoint
        url = f'https://kroki.io/plantuml/{output_format}/{encoded}'

        if dry_run:
            print(f"[DRY-RUN] Would render: {file_path}", file=sys.stderr)
            return 2  # Warning code for dry-run

        # Make request
        req = Request(url, headers={'User-Agent': 'plantuml-render-tool/1.0'})
        with urlopen(req, timeout=30) as response:
            image_data = response.read()

        # Save output
        output_path = file_path.with_suffix(f'.{output_format}')
        with open(output_path, 'wb') as f:
            f.write(image_data)

        print(f"✓ Rendered: {file_path} → {output_path}", file=sys.stderr)
        return 0

    except FileNotFoundError:
        print(f"✗ File not found: {file_path}", file=sys.stderr)
        return 1
    except (URLError, HTTPError) as e:
        print(f"✗ Network error rendering {file_path}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Error rendering {file_path}: {e}", file=sys.stderr)
        return 1


def find_plantuml_files(root_path):
    """Find all .plantuml files recursively"""
    root = Path(root_path)
    if not root.exists():
        print(f"✗ Path does not exist: {root_path}", file=sys.stderr)
        return []

    if root.is_file():
        return [root] if root.suffix == '.plantuml' else []

    return list(root.rglob('*.plantuml'))


def main():
    parser = argparse.ArgumentParser(
        description='Render PlantUML diagrams to PNG using Kroki.io API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Render all .plantuml files in current directory
  plantuml-render

  # Render files in specific directory
  plantuml-render --path примеры/Виды_архитектур/

  # Dry-run (check what would be rendered)
  plantuml-render --dry-run

  # Render to SVG format
  plantuml-render --format svg

Exit codes:
  0 - Success
  1 - Error
  2 - Warning (e.g., dry-run or partial success)
        """
    )

    parser.add_argument(
        '--path', '-p',
        default='.',
        help='Path to .plantuml file or directory (default: current directory)'
    )

    parser.add_argument(
        '--format', '-f',
        choices=['png', 'svg'],
        default='png',
        help='Output format (default: png)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be rendered without actually rendering'
    )

    args = parser.parse_args()

    # Find files
    files = find_plantuml_files(args.path)

    if not files:
        print(f"No .plantuml files found in: {args.path}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} .plantuml file(s)", file=sys.stderr)

    # Render files
    exit_codes = []
    for file_path in files:
        code = render_file(file_path, args.format, args.dry_run)
        exit_codes.append(code)

    # Determine final exit code
    if all(code == 0 for code in exit_codes):
        return 0
    elif any(code == 1 for code in exit_codes):
        return 1
    else:
        return 2


if __name__ == '__main__':
    sys.exit(main())
