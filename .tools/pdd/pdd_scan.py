#!/usr/bin/env python3
"""pdd_scan.py

Simple scanner for `@todo` puzzles in source files.

Outputs a compact table (default) or JSON (`--format json` or `--json` alias) with fields:
- file, line, task_id, est, summary, refs, refs_exist, type, prio, owner, accept, age_days

Usage:
  python3 .tools/pdd/pdd_scan.py [--format json|md|table] [--root ROOT]

Note:
  `--json` is kept as a deprecated compatibility alias for `--format json`.
"""
from __future__ import annotations
import argparse
import os
import re
import json
import subprocess
import sys
from datetime import datetime, timezone

TODO_RE = re.compile(r"@todo\s+#(?P<task>[A-Za-z0-9\-]+):(?P<est>[0-9]+[mhd])\s+(?P<summary>.*)")
FIELD_RE = re.compile(r"(?P<key>refs|scope|accept|prio|type|owner|blocked-by|defer)\s*:\s*(?P<val>.+)", re.I)

COMMENT_PREFIX_RE = re.compile(r"^\s*(?P<prefix>//+|#|/\*|\*|;|--)\s*(?P<rest>.*)")

SEARCH_EXTS = None  # None => all files
MAX_LOOKAHEAD = 6


def git_blame_author_time(file: str, line: int) -> int | None:
    try:
        out = subprocess.check_output([
            "git", "--no-pager", "blame", f"-L{line},{line}", "--porcelain", "--", file
        ], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return None
    for l in out.splitlines():
        if l.startswith("author-time "):
            try:
                return int(l.split()[1])
            except Exception:
                return None
    return None


def parse_file(path: str):
    res = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return res
    for i, raw in enumerate(lines, start=1):
        m = TODO_RE.search(raw)
        if not m:
            continue
        task = m.group("task")
        est = m.group("est")
        summary = m.group("summary").strip()
        data = {
            "file": path,
            "line": i,
            "todo_text": raw.strip(),
            "task_id": task,
            "est": est,
            "summary": summary,
            "refs": [],
            "type": None,
            "prio": None,
            "owner": None,
            "accept": None,
        }
        # search same line for inline fields
        for fld in FIELD_RE.finditer(raw):
            key = fld.group("key").lower()
            val = fld.group("val").strip()
            if key == "refs":
                data["refs"].extend([s.strip() for s in re.split(r"[,;]", val) if s.strip()])
            elif key == "type":
                data["type"] = val
            elif key == "prio":
                data["prio"] = val
            elif key == "owner":
                data["owner"] = val
            elif key == "accept":
                data["accept"] = val
        # look ahead a few lines for comment fields
        for j in range(i, min(i + MAX_LOOKAHEAD, len(lines))):
            nxt = lines[j]
            cm = COMMENT_PREFIX_RE.match(nxt)
            if not cm:
                break
            rest = cm.group("rest").strip()
            mf = FIELD_RE.search(rest)
            if mf:
                key = mf.group("key").lower()
                val = mf.group("val").strip()
                if key == "refs":
                    data["refs"].extend([s.strip() for s in re.split(r"[,;]", val) if s.strip()])
                elif key == "type":
                    data["type"] = val
                elif key == "prio":
                    data["prio"] = val
                elif key == "owner":
                    data["owner"] = val
                elif key == "accept":
                    data["accept"] = val
        # dedupe refs
        data["refs"] = list(dict.fromkeys(data["refs"]))
        # check existence
        # None  — поле refs: не указано (нарушение pdd.H4.2)
        # True  — все указанные файлы существуют
        # False — указаны, но файл(ы) не найдены
        if not data["refs"]:
            data["refs_exist"] = None
        else:
            refs_exist = []
            for r in data["refs"]:
                norm = r
                if norm.startswith("."):
                    norm = os.path.normpath(os.path.join(os.getcwd(), norm))
                refs_exist.append(os.path.exists(norm))
            data["refs_exist"] = all(refs_exist)
        # git blame
        ts = git_blame_author_time(path, i)
        if ts is not None:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).days
            data["created_at"] = dt.isoformat()
            data["age_days"] = age_days
        else:
            data["created_at"] = None
            data["age_days"] = None
        res.append(data)
    return res


def scan(root: str):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # skip hidden dirs like .git
        dirnames[:] = [d for d in dirnames if not d.startswith(('.', '__'))]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            path = os.path.join(dirpath, fn)
            out.extend(parse_file(path))
    return out


def print_table(items):
    if not items:
        print("No @todo found.")
        return
    headers = ["file:line", "task", "est", "refs", "type", "prio", "owner", "age_days", "summary"]
    rows = []
    for it in items:
        rows.append([
            f"{os.path.relpath(it['file'])}:{it['line']}",
            it['task_id'],
            it['est'],
            ",".join(it['refs']) or "-",
            it.get('type') or "-",
            it.get('prio') or "-",
            it.get('owner') or "-",
            str(it.get('age_days')) if it.get('age_days') is not None else "-",
            (it['summary'][:40] + '...') if len(it['summary']) > 40 else it['summary']
        ])
    # compute column widths
    cols = list(zip(*([headers] + rows)))
    widths = [max(len(str(v)) for v in c) for c in cols]
    fmt = "  ".join("{:<%d}" % w for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt.format(*r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', '-r', default='.', help='Root to scan')
    ap.add_argument('--format', choices=['table','json','md'], default='md', help='Output format (default: md)')
    ap.add_argument('--json', action='store_const', dest='format', const='json',
                    help='(deprecated) shortcut for --format json (kept for compatibility)')
    ap.add_argument('--output', '-o', help='Path for output file (requires --write)')
    ap.add_argument('--write', '-w', action='store_true',
                    help='Write output to file instead of stdout (md: .tasks/pdd/@todoregistry.md by default)')
    args = ap.parse_args()

    if args.output and not args.write:
        print("error: --output requires --write", file=sys.stderr)
        sys.exit(1)

    try:
        items = scan(args.root)
    except Exception as exc:
        print(f"error: scan failed: {exc}", file=sys.stderr)
        sys.exit(1)

    def render_md(items):
        lines = []
        lines.append(f"# PDD @todo registry")
        lines.append("")
        lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"Total: {len(items)}")
        lines.append("")
        # table header
        headers = ["file:line", "task", "est", "refs", "refs_exist", "type", "prio", "owner", "age_days", "summary"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + " --- |" * len(headers))
        for it in items:
            refs = ",".join(it.get('refs') or [])
            refs_exist_val = it.get('refs_exist')
            if refs_exist_val is None:
                refs_exist = "n/a"  # поле refs: не указано
            elif refs_exist_val:
                refs_exist = "yes"
            else:
                refs_exist = "no"  # файл(ы) из refs не найдены
            summary = it.get('summary') or ""
            # escape pipes
            refs = refs.replace("|","\\|")
            summary = summary.replace("|","\\|")
            row = [
                f"{os.path.relpath(it['file'])}:{it['line']}",
                it.get('task_id',''),
                it.get('est',''),
                refs or '-',
                refs_exist,
                it.get('type') or '-',
                it.get('prio') or '-',
                it.get('owner') or '-',
                str(it.get('age_days')) if it.get('age_days') is not None else '-',
                summary[:120].replace('\n',' ')
            ]
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    try:
        if args.format == 'json':
            s = json.dumps(items, ensure_ascii=False, indent=2)
            if args.write:
                outpath = args.output or 'todos.json'
                with open(outpath, 'w', encoding='utf-8') as f:
                    f.write(s)
                print(f'Wrote {len(items)} items to {outpath}', file=sys.stderr)
            else:
                print(s)
        elif args.format == 'md':
            md = render_md(items)
            if args.write:
                # записываем в файл только при явном --write
                outpath = args.output or os.path.join('.tasks', 'pdd', '@todoregistry.md')
                odir = os.path.dirname(outpath)
                if odir and not os.path.exists(odir):
                    os.makedirs(odir, exist_ok=True)
                with open(outpath, 'w', encoding='utf-8') as f:
                    f.write(md)
                print(f'Wrote {len(items)} items to {outpath}', file=sys.stderr)
            else:
                print(md)
        else:
            print_table(items)
    except OSError as exc:
        print(f"error: cannot write output: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
