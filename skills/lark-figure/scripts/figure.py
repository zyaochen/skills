#!/usr/bin/env python3
"""lark-figure CLI: content spec (JSON) → house-style SVG → lint gate → local preview → Lark whiteboard.

  figure.py types                          # chart types and when to use each
  figure.py example flow > k1.json         # a complete, valid spec to start from
  figure.py build k1.json [-o DIR]         # compile + lint + render; writes DIR/k1.svg, k1.png, k1.report.json
  figure.py lint my.svg [--render]         # gate a hand-written SVG (same rules)
  figure.py wrap k1.svg                    # print <whiteboard type="svg">…</whiteboard> for lark-doc XML
  figure.py put TOKEN k1.svg [--yes]       # overwrite a board; without --yes only dry-runs
  figure.py preview TOKEN -o k1.lark.png   # export what Lark really renders
  figure.py restore TOKEN BACKUP.json --yes

Exit codes: 0 ok, 1 spec/lint errors (read the messages, fix the spec, rerun), 2 tool/environment failure.
Python 3.8+, stdlib only. Theme: assets/theme.json (override with --theme).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lfig import canvas, lark
from lfig.charts import CHARTS
from lfig.compose import SpecError, build
from lfig.lint import lint, summarize


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def cmd_types(a):
    for name, m in CHARTS.items():
        print(f'{name:11} {m.DOC["summary"]}')
    print('\nCommon fields (all types): title (one-sentence takeaway, required), subtitle (how to read it), '
          'source (where facts came from), callout {text, label?, tone?}, legend [{label, tone, style?}]')
    print('Tones: ' + ', '.join(f'{k}={v}' for k, v in canvas.T['tones'].items()))


def cmd_example(a):
    m = CHARTS.get(a.type)
    if not m:
        sys.exit(f'unknown type {a.type!r}; one of {", ".join(CHARTS)}')
    if a.fields:
        _print(m.DOC['fields'])
    else:
        _print(m.DOC['example'])


def _gate(svg_path, render, report):
    """Lint, then (optionally) the board's own --check and a local PNG. Mutates and returns report."""
    with open(svg_path, encoding='utf-8') as f:
        report['lint'] = summarize(lint(f.read()))
    if render:
        try:
            issues = lark.wb_check(svg_path)
            # node-overlap is expected (bar on its track, highlight behind a column); text problems are not
            report['wb_check'] = [i for i in issues if i.get('type') != 'node-overlap']
            report['wb_overlaps'] = len(issues) - len(report['wb_check'])
            png = svg_path[:-4] + '.png'
            lark.render_png(svg_path, png)
            report['png'] = png
        except lark.ToolError as e:
            report['tool_error'] = str(e)
    report['ok'] = report['lint']['ok'] and not report.get('wb_check')
    return report


def _finish(report, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    _print(report)
    if not report['ok']:
        return 1
    return 2 if report.get('tool_error') else 0


def cmd_build(a):
    with open(a.spec, encoding='utf-8') as f:
        try:
            spec = json.load(f)
        except ValueError as e:
            _print({'ok': False, 'stage': 'json', 'errors': [f'{a.spec} is not valid JSON: {e}']})
            return 1
    stem = os.path.splitext(os.path.basename(a.spec))[0]
    out = a.out or os.path.dirname(os.path.abspath(a.spec))
    os.makedirs(out, exist_ok=True)
    try:
        svg, notes = build(spec)
    except SpecError as e:
        _print({'ok': False, 'stage': 'spec', 'errors': e.errors})
        return 1
    svg_path = os.path.join(out, stem + '.svg')
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg)
    report = {'svg': svg_path, 'notes': notes}
    return _finish(_gate(svg_path, not a.no_render, report), os.path.join(out, stem + '.report.json'))


def cmd_lint(a):
    report = {'svg': os.path.abspath(a.svg)}
    return _finish(_gate(a.svg, a.render, report), os.path.splitext(a.svg)[0] + '.report.json')


def cmd_wrap(a):
    with open(a.svg, encoding='utf-8') as f:
        svg = f.read().strip()
    print('<whiteboard type="svg">' + svg + '</whiteboard>')


def cmd_put(a):
    with open(a.svg, encoding='utf-8') as f:
        res = summarize(lint(f.read()))
    if not res['ok'] and not a.force:
        _print({'ok': False, 'stage': 'lint', 'lint': res, 'hint': 'fix lint errors first (or --force)'})
        return 1
    _print(lark.put(a.token, a.svg, dry=not a.yes))
    return 0


def cmd_preview(a):
    _print({'ok': True, 'png': lark.preview(a.token, os.path.abspath(a.out))})
    return 0


def cmd_restore(a):
    if not a.yes:
        print(f'would restore {a.token} from {a.backup}; rerun with --yes')
        return 0
    _print(lark.restore(a.token, a.backup))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--theme', help='alternative theme.json')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('types').set_defaults(fn=cmd_types)
    s = sub.add_parser('example')
    s.add_argument('type')
    s.add_argument('--fields', action='store_true', help='print field reference instead of the example')
    s.set_defaults(fn=cmd_example)
    s = sub.add_parser('build')
    s.add_argument('spec')
    s.add_argument('-o', '--out', help='output dir (default: next to the spec)')
    s.add_argument('--no-render', action='store_true', help='skip whiteboard-cli check/PNG (offline)')
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser('lint')
    s.add_argument('svg')
    s.add_argument('--render', action='store_true')
    s.set_defaults(fn=cmd_lint)
    s = sub.add_parser('wrap')
    s.add_argument('svg')
    s.set_defaults(fn=cmd_wrap)
    s = sub.add_parser('put')
    s.add_argument('token')
    s.add_argument('svg')
    s.add_argument('--yes', action='store_true', help='actually write (default is dry-run)')
    s.add_argument('--force', action='store_true', help='write even if lint has errors')
    s.set_defaults(fn=cmd_put)
    s = sub.add_parser('preview')
    s.add_argument('token')
    s.add_argument('-o', '--out', required=True)
    s.set_defaults(fn=cmd_preview)
    s = sub.add_parser('restore')
    s.add_argument('token')
    s.add_argument('backup')
    s.add_argument('--yes', action='store_true')
    s.set_defaults(fn=cmd_restore)
    a = p.parse_args(argv)
    if a.theme:
        canvas.load_theme(a.theme)
    try:
        return a.fn(a) or 0
    except lark.ToolError as e:
        _print({'ok': False, 'stage': 'tool', 'error': str(e)})
        return 2


if __name__ == '__main__':
    sys.exit(main())
