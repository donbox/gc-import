#!/usr/bin/env python3.11
"""gc import list — show what this city imports.

Usage:
    gc import list           # flat table
    gc import list --tree    # indented import graph
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import lockfile, manifest, ui  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gc import list")
    parser.add_argument("--tree", action="store_true", help="Show as an indented tree")
    args = parser.parse_args(argv)

    city_root = ui.find_city_root()
    lf = lockfile.read(city_root / "pack.lock")
    m = manifest.read(city_root / "imports.toml")

    if not lf.packs and not m.imports:
        ui.info("No imports in this city.")
        ui.info("Run `gc import add <url>` to add one.")
        return 0

    if args.tree:
        return _print_tree(lf, m)
    return _print_flat(lf, m)


def _print_flat(lf, m) -> int:
    rows = []
    for handle in sorted(lf.packs.keys()):
        p = lf.packs[handle]
        marker = ""
        if p.frozen:
            marker = " (frozen)"
        elif p.parent:
            marker = f" ← {p.parent}"
        rows.append((handle, p.version, p.constraint, _short_url(p.url), marker))

    # Path imports (not in lock)
    for handle in sorted(m.imports.keys()):
        spec = m.imports[handle]
        if spec.is_path():
            rows.append((handle, "(local)", "", spec.path, ""))

    if not rows:
        ui.info("No imports.")
        return 0

    name_w = max(max(len(r[0]) for r in rows), len("NAME")) + 2
    ver_w = max(max(len(r[1]) for r in rows), len("VERSION")) + 2
    con_w = max(max(len(r[2]) for r in rows), len("CONSTRAINT")) + 2

    print(f"{'NAME':<{name_w}}{'VERSION':<{ver_w}}{'CONSTRAINT':<{con_w}}URL")
    for name, version, constraint, url, marker in rows:
        print(f"{name:<{name_w}}{version:<{ver_w}}{constraint:<{con_w}}{url}{marker}")
    return 0


def _print_tree(lf, m) -> int:
    # Build parent → children map
    children: dict[str, list[str]] = {}
    for h, p in lf.packs.items():
        children.setdefault(p.parent or "", []).append(h)
    for k in children:
        children[k].sort()

    # Direct (root) entries are those with no parent
    roots = sorted(children.get("", []))

    def walk(handle: str, prefix: str = "", is_last: bool = True):
        p = lf.packs[handle]
        marker = ""
        if p.frozen:
            marker = " (frozen)"
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{handle} {p.version} ({p.constraint}){marker}  — {_short_url(p.url)}")
        kids = children.get(handle, [])
        for i, kid in enumerate(kids):
            extension = "    " if is_last else "│   "
            walk(kid, prefix + extension, i == len(kids) - 1)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1)

    # Path imports
    for handle in sorted(m.imports.keys()):
        spec = m.imports[handle]
        if spec.is_path():
            print(f"{handle} (local) — {spec.path}")
    return 0


def _short_url(url: str) -> str:
    """Trim a URL for display."""
    if len(url) <= 60:
        return url
    return "…" + url[-59:]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
