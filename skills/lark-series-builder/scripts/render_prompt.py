"""Fill a role prompt for one doc, ready to paste as an Agent task (header + role card).

    python3 render_prompt.py list                                   # roles available
    python3 render_prompt.py writer 05 --segs s01,s02               # print the prompt
    python3 render_prompt.py polish 05 --segs s03 --extra-file notes.txt
    python3 render_prompt.py figure 05 --have 5 --extra "focus on chapter 4"
    python3 render_prompt.py quick                                  # (re)write ROOT/spec/QUICK.md from the template

Placeholders are {UPPER_CASE} names; series values come from spec/series.json and its defaults.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import SKILL, docs, load  # noqa: E402

PROMPTS = os.path.join(SKILL, 'prompts')


def values(cfg, num=None, segs='', extra='', have=''):
    t, th = cfg['template'], cfg['thresholds']
    reg = docs(cfg)
    d = reg.get(num, {}) if num else {}
    code = cfg.get('code_repo', {}).get('local')
    backup = d.get('backup')
    rv = cfg.get('audit', {}).get('reference_values') or ['(none configured: rely on cited sources)']
    v = {
        'SERIES': cfg.get('name', ''), 'PREFIX': cfg.get('prefix', ''), 'ROOT': cfg['_root'], 'SKILL': SKILL,
        'S': os.path.join(SKILL, 'scripts'), 'MAXW': str(cfg['agent']['max_write_chars']),
        'NN': num or '', 'TITLE': d.get('title', ''), 'FOCUS': d.get('focus', ''), 'SCOPE': d.get('scope', ''),
        'PREV': d.get('prev') or '-', 'NEXT': d.get('next') or '-',
        'CODE_PATH': os.path.join(cfg['_root'], code, d['code_dir']) if code and d.get('code_dir') else '(no companion code)',
        'BACKUP_HINT': (f'the old version {backup} as source material (grep, read only matching ranges; reuse facts, '
                        f're-verify links, restructure along the mainline), ') if backup else '',
        'SEGS': segs, 'EXTRA': extra, 'HAVE': have,
        'REFVALUES': '\n'.join('  - ' + r for r in rv),
        'TERMS': '、'.join(t['required_terms']) or '（本系列未定义）', 'POSITION': t['position'] or '（本系列不要求）',
        'FIRST': t['first_chapter_contains'] or '（不限）', 'LAST': t['last_chapter_contains'] or '（不限）',
        'CALLOUT_BG': t['callout_color']['bg'], 'CALLOUT_BORDER': t['callout_color']['border'],
        'GUIDE': '%d 到 %d' % tuple(th['guide_items']), 'CHAPTERS': '%d 到 %d' % tuple(th['chapters']),
        'H2': '%d 到 %d' % tuple(th['h2_per_chapter']), 'PITFALLS': '%d 到 %d' % tuple(th['pitfalls']),
        'CH_MIN': str(th['chapter_cjk_min']), 'CH_LO': str(th['chapter_cjk_target'][0]), 'CH_HI': str(th['chapter_cjk_target'][1]),
        'S00_MIN': str(th['s00_cjk_min']), 'CITE_MIN': str(th['cites_per_chapter_min']),
        'FIG_LO': str(th['figures'][0]), 'FIG_HI': str(th['figures'][1]),
        'REF_LO': str(th['refs'][0]), 'REF_HI': str(th['refs'][1]),
    }
    return v


def fill(text, v):
    return re.sub(r'\{([A-Z][A-Z0-9_]*)\}', lambda m: v.get(m.group(1), m.group(0)), text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('role')
    ap.add_argument('num', nargs='?')
    ap.add_argument('--segs', default='')
    ap.add_argument('--extra', default='')
    ap.add_argument('--extra-file')
    ap.add_argument('--have', default='')
    a = ap.parse_args()
    roles = sorted(f[:-4] for f in os.listdir(PROMPTS) if f.endswith('.txt') and not f.startswith('_'))
    if a.role == 'list':
        print('\n'.join(roles + ['quick']))
        return
    cfg = load()
    if a.role == 'quick':
        out = os.path.join(cfg['_root'], 'spec', 'QUICK.md')
        open(out, 'w', encoding='utf-8').write(fill(open(os.path.join(SKILL, 'references', 'quick.md'), encoding='utf-8').read(),
                                                    values(cfg)))
        print(out)
        return
    if a.role not in roles:
        sys.exit(f'unknown role {a.role}; one of {roles}')
    if not a.num or a.num not in docs(cfg):
        sys.exit('give a doc number that is in spec/series.json')
    extra = open(a.extra_file, encoding='utf-8').read() if a.extra_file else a.extra
    v = values(cfg, a.num, a.segs, extra, a.have)
    head = open(os.path.join(PROMPTS, '_header.txt'), encoding='utf-8').read()
    body = open(os.path.join(PROMPTS, a.role + '.txt'), encoding='utf-8').read()
    print(fill(head + '\n' + body, v).strip())


if __name__ == '__main__':
    main()
