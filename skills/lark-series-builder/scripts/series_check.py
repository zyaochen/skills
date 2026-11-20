"""Series completeness dashboard: one row per doc plus series-level link checks.

    python3 series_check.py            # table + SERIES line
    python3 series_check.py --strict   # exit 1 unless every doc is READY

Per doc: segs, lint E/W (on the built doc.xml), thin/flagged segments, figures, publish state, code files.
  build  = 'ok' | 'stale' (a seg or figure is newer than doc.xml) | 'none'
  live   = 'ok' (publish_resp success and newer than doc.xml) | 'stale' | 'no'
  READY  = build ok, lint E 0, no flagged segment, live ok (and code present when the doc declares code_dir)
Series: prev/next chain symmetric, hub links every doc ({{C:NN}} in hub segments), numbering continuous.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import ddir, docs, is_hub, load, segs  # noqa: E402
from lint_doc import lint  # noqa: E402
from stats import report  # noqa: E402


def mtime(paths):
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def doc_row(cfg, num, entry):
    d = ddir(cfg, num)
    files = segs(cfg, num)
    figs = glob.glob(os.path.join(d, 'figs', '*.svg'))
    doc = os.path.join(d, 'doc.xml')
    row = {'num': num, 'status': entry.get('status', ''), 'segs': len(files)}
    if not os.path.exists(doc):
        row['build'] = 'none'
        row['E'] = row['W'] = row['fig'] = '-'
    else:
        row['build'] = 'stale' if mtime(files + figs) > os.path.getmtime(doc) else 'ok'
        E, W, summary = lint(cfg, num, open(doc, encoding='utf-8').read())
        row['E'], row['W'] = len(E), len(W)
        row['fig'] = int(re.search(r'figures=(\d+)', summary).group(1))
    flagged = report(cfg, num, table=False, quiet=True) if files else None
    row['thin'] = '-' if flagged is None else len(flagged)
    resp = os.path.join(d, 'publish_resp.json')
    if os.path.exists(resp):
        j = json.load(open(resp, encoding='utf-8'))
        good = j.get('ok') and j.get('data', {}).get('result') in (None, 'success')
        row['live'] = 'ok' if good and os.path.getmtime(resp) >= mtime([doc]) else 'stale'
    else:
        row['live'] = 'no'
    code = cfg.get('code_repo', {}).get('local')
    if code and entry.get('code_dir'):
        cd = os.path.join(cfg['_root'], code, entry['code_dir'])
        sims = glob.glob(os.path.join(cd, 'sim_*.py'))
        tests = glob.glob(os.path.join(cd, 'test_*.py'))
        row['code'] = f'{len(sims)}s/{len(tests)}t' if os.path.isdir(cd) else 'none'
        code_ok = bool(sims and tests)
    else:
        row['code'], code_ok = '-', True
    row['ready'] = (row['build'] == 'ok' and row['E'] == 0 and row['thin'] == 0 and row['live'] == 'ok' and code_ok)
    return row


def main():
    cfg = load()
    reg = docs(cfg)
    nums = sorted(reg)
    rows = [doc_row(cfg, n, reg[n]) for n in nums]
    print(f'{"doc":5}{"status":9}{"segs":>5}{"build":>7}{"E":>4}{"W":>4}{"thin":>5}{"fig":>5}{"live":>7}{"code":>7}  ready  title')
    for r in rows:
        print(f'{r["num"]:5}{r["status"][:8]:9}{r["segs"]:5}{r["build"]:>7}{r["E"]!s:>4}{r["W"]!s:>4}{r["thin"]!s:>5}'
              f'{r["fig"]!s:>5}{r["live"]:>7}{r["code"]:>7}  {"READY" if r["ready"] else "  -  "}  {reg[r["num"]]["title"][:30]}')
    issues = []
    for n in nums:
        e = reg[n]
        for k, back in (('prev', 'next'), ('next', 'prev')):
            o = e.get(k)
            if o and o in reg and reg[o].get(back) not in (n, None) and not is_hub(cfg, o):
                issues.append(f'{n}.{k}={o} but {o}.{back}={reg[o].get(back)}')
            if o and o not in reg:
                issues.append(f'{n}.{k} points at unknown doc {o}')
    hub = cfg.get('hub')
    if hub:
        text = ''.join(open(p, encoding='utf-8').read() for p in segs(cfg, hub['num']))
        if text:
            missing = [n for n in nums if n != hub['num'] and f'{{{{C:{n}}}}}' not in text and reg[n]['token'] not in text]
            if missing:
                issues.append(f'hub does not link: {missing}')
    plain = [int(n) for n in nums if not is_hub(cfg, n)]
    if plain and plain != list(range(plain[0], plain[0] + len(plain))):
        issues.append(f'numbering has gaps: {plain}')
    for i in issues:
        print('SERIES-ISSUE', i)
    ready = sum(r['ready'] for r in rows)
    print(f'SERIES {cfg.get("name", "")}: docs={len(rows)} ready={ready} not_ready={len(rows) - ready} series_issues={len(issues)}')
    sys.exit(1 if '--strict' in sys.argv and (ready < len(rows) or issues) else 0)


if __name__ == '__main__':
    main()
