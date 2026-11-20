#!/usr/bin/env python3
"""Pre-publish checks for a DocxXML distillation document.

Usage: check_xml.py <doc.xml>   (run from the directory used for publishing)

Checks: valid UTF-8, unescaped '&', unsupported attributes seen in practice,
svg/mermaid path references exist, whiteboard count vs quality bar.
Exit code 1 on errors; warnings do not fail.
"""
import argparse
import os
import re
import sys

MIN_WHITEBOARDS = 12
MIN_SVG = 3
UNESCAPED_AMP = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")
CALLOUT_FORBIDDEN = re.compile(r"<(table|whiteboard|grid|pre|img)\b")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def check_text(text):
    errors = []
    if "\ufffd" in text:
        errors.append("contains U+FFFD replacement characters (encoding damage)")
    for m in UNESCAPED_AMP.finditer(text):
        errors.append(f"line {line_of(text, m.start())}: unescaped '&' (use &amp;)")
    if re.search(r"<checkbox[^>]*\bchecked=", text):
        errors.append('<checkbox checked=...> unsupported; use done="true|false"')
    if re.search(r"<grid[^>]*\bcols=", text):
        errors.append("<grid cols=...> unsupported; use <column width-ratio=...>")
    for m in re.finditer(r"<callout\b.*?</callout>", text, re.S):
        if CALLOUT_FORBIDDEN.search(m.group(0)):
            errors.append(f"line {line_of(text, m.start())}: callout contains a block tag it cannot hold")
    return errors


def check_svg(ref):
    try:
        svg = open(ref, "rb").read().decode("utf-8")
    except UnicodeDecodeError:
        return [f"{ref}: not valid UTF-8"], []
    warnings = []
    if "viewBox" not in svg:
        warnings.append(f"{ref}: missing viewBox")
    if re.search(r"<(pattern|clipPath|mask)\b", svg):
        warnings.append(f"{ref}: uses pattern/clipPath/mask (unsupported)")
    return [], warnings


def check_paths(text):
    errors, warnings = [], []
    for m in re.finditer(r'<whiteboard[^>]*\bpath="@([^"]+)"', text):
        ref = m.group(1)
        if not os.path.isfile(ref):
            errors.append(f"whiteboard path not found relative to cwd: {ref}")
        elif ref.endswith(".svg"):
            e, w = check_svg(ref)
            errors += e
            warnings += w
    return errors, warnings


def quality_warnings(text, boards, svg_boards):
    warnings = []
    if boards < MIN_WHITEBOARDS:
        warnings.append(f"only {boards} whiteboards (quality bar >= {MIN_WHITEBOARDS})")
    if svg_boards < MIN_SVG:
        warnings.append(f"only {svg_boards} SVG infographics (recommend 3-5)")
    if "<title>" not in text:
        warnings.append("missing <title>")
    return warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-publish checks for a DocxXML distillation document.")
    ap.add_argument("xml", help="DocxXML file; run from the directory used for publishing")
    path = ap.parse_args().xml
    try:
        text = open(path, "rb").read().decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"ERROR not valid UTF-8: {e}")
        return 1

    errors = check_text(text)
    path_errors, warnings = check_paths(text)
    errors += path_errors
    boards = len(re.findall(r"<whiteboard\b", text))
    svg_boards = len(re.findall(r'<whiteboard[^>]*type="svg"', text))
    warnings += quality_warnings(text, boards, svg_boards)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"chars={len(text)} whiteboards={boards} svg={svg_boards} "
          f"h1={text.count('<h1>')} errors={len(errors)} warnings={len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
