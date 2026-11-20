#!/usr/bin/env python3
"""Split a merged collection markdown into per-article files.

Usage: split_collection.py <collection.md> <outdir> [--pattern REGEX]

Default heading pattern matches lines like "## 12. Title". Prints an
inventory (index, bytes, title) so the reader can plan subagent groups.
"""
import argparse
import os
import re
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("outdir")
    ap.add_argument("--pattern", default=r"^## (\d+)\.\s*(.*)$")
    args = ap.parse_args()

    text = open(args.collection, encoding="utf-8").read()
    heading = re.compile(args.pattern, re.M)
    matches = list(heading.finditer(text))
    if not matches:
        print(f"no headings matched {args.pattern!r}", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end]
        n = int(m.group(1))
        path = os.path.join(args.outdir, f"doc{n:02d}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"{n:3d}  {len(body.encode()):8d}  {m.group(2).strip()[:60]}")
    print(f"{len(matches)} articles -> {args.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
