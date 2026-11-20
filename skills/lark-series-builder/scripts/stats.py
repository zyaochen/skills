"""Thickness report per segment: is every chapter substantial, sourced and illustrated?

    python3 stats.py 05            # table + THICKNESS line
    python3 stats.py 05 --strict   # exit 1 when any segment is flagged (use as a gate)
    python3 stats.py all           # one THICKNESS line per doc in the registry

Columns: cjk = CJK characters of prose (tables, code, figures, placeholders stripped); keys = distinct {{r:key}};
fig = {{F:}} count; tbl / code = tables and code blocks; pit = 💡 常见误区; h2 = sections; sent = mean sentence length.
Flags: THIN (cjk below chapter_cjk_min, or s00 below s00_cjk_min), LOWCITE (keys below cites_per_chapter_min),
NOFIG (chapter without a figure, except the last checklist chapter), FLAT (no table, code block or figure at all),
H2 (section count out of range), NOKEY (🔑 本章要点 missing).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import chapter_re, cjk, docs, is_hub, load, segs, sentence_lengths, strip_prose  # noqa: E402


def seg_stats(cfg, path, is_last):
    th = cfg['thresholds']
    x = open(path, encoding='utf-8').read()
    p = strip_prose(x)
    sl = sentence_lengths(p)
    s = {
        'name': os.path.basename(path)[:-4],
        'cjk': cjk(p),
        'keys': len({k.strip() for g in re.findall(r'\{\{r:([^}]+)\}\}', x) for k in g.split(',')}),
        'fig': len(re.findall(r'\{\{F:', x)),
        'tbl': len(re.findall(r'<table', x)),
        'code': len(re.findall(r'<pre', x)),
        'pit': len(re.findall(r'<b>常见误区', x)),
        'h2': len(re.findall(r'<h2>', x)),
        'sent': sum(sl) / len(sl) if sl else 0,
        'h1': (chapter_re(cfg).search(x).group(2) if chapter_re(cfg).search(x) else
               (re.search(r'<h1>([^<]*)</h1>', x).group(1) if re.search(r'<h1>([^<]*)</h1>', x) else '')),
    }
    chapter = bool(chapter_re(cfg).search(x))
    flags = []
    if chapter:
        if s['cjk'] < th['chapter_cjk_min']:
            flags.append('THIN')
        if s['keys'] < th['cites_per_chapter_min']:
            flags.append('LOWCITE')
        if s['fig'] == 0 and not is_last:
            flags.append('NOFIG')
        if s['fig'] + s['tbl'] + s['code'] + (is_last and '<ul>' in x) == 0:
            flags.append('FLAT')
        if not th['h2_per_chapter'][0] <= s['h2'] <= th['h2_per_chapter'][1]:
            flags.append('H2')
        if '本章要点' in cfg['template']['callouts'] and '本章要点' not in x and '小结' not in x:
            flags.append('NOKEY')
    elif s['name'] == 's00' and s['cjk'] < th['s00_cjk_min']:
        flags.append('THIN')
    s['flags'] = flags
    return s


def report(cfg, num, table=True, quiet=False):
    files = segs(cfg, num)
    if not files:
        return None
    rows = [seg_stats(cfg, p, i == len(files) - 1) for i, p in enumerate(files)]
    if is_hub(cfg, num):
        for r in rows:
            r['flags'] = [f for f in r['flags'] if f == 'THIN']
    lo, hi = cfg['thresholds']['chapter_cjk_target']
    if table:
        print(f'{"seg":8}{"cjk":>6}{"keys":>5}{"fig":>4}{"tbl":>4}{"code":>5}{"pit":>4}{"h2":>4}{"sent":>6}  flags / h1')
        for r in rows:
            mark = '' if lo <= r['cjk'] <= hi or r['name'] == 's00' else ' (target %d-%d)' % (lo, hi)
            print(f'{r["name"]:8}{r["cjk"]:6d}{r["keys"]:5d}{r["fig"]:4d}{r["tbl"]:4d}{r["code"]:5d}{r["pit"]:4d}'
                  f'{r["h2"]:4d}{r["sent"]:6.1f}  {",".join(r["flags"]) or "-"}{mark}  {r["h1"][:28]}')
    flagged = [r for r in rows if r['flags']]
    total = sum(r['cjk'] for r in rows)
    if not quiet:
        print(f'THICKNESS {num}: segs={len(rows)} cjk={total} figs={sum(r["fig"] for r in rows)} '
              f'flagged={len(flagged)} {" ".join(r["name"] + ":" + "/".join(r["flags"]) for r in flagged)}')
    return flagged


def main():
    cfg = load()
    a = sys.argv[1]
    nums = sorted(docs(cfg)) if a == 'all' else [a]
    bad = 0
    for n in nums:
        f = report(cfg, n, table=a != 'all')
        if f is None:
            print(f'THICKNESS {n}: no segments')
            bad += 1
        else:
            bad += bool(f)
    sys.exit(1 if bad and '--strict' in sys.argv else 0)


if __name__ == '__main__':
    main()
