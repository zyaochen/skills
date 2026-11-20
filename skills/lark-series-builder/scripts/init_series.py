"""Scaffold (or top up) a series working directory. Idempotent: existing files are never overwritten.

    python3 init_series.py ROOT            # creates ROOT/spec/{series.json, MAINLINE.md, review_notes.md, cards/},
                                           # drafts/NN/{seg,figs} for every registered doc, and spec/QUICK.md
After editing spec/series.json (docs, tokens, focus/scope, template, reference values) run it again:
new docs get their draft folders and QUICK.md is re-rendered with the current thresholds.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = os.path.abspath(os.path.expanduser(sys.argv[1]))
    spec = os.path.join(root, 'spec')
    os.makedirs(os.path.join(spec, 'cards'), exist_ok=True)
    made = []
    src = {'series.json': os.path.join(SKILL, 'assets', 'series.example.json'),
           'MAINLINE.md': os.path.join(SKILL, 'references', 'mainline_template.md')}
    for name, path in src.items():
        dst = os.path.join(spec, name)
        if not os.path.exists(dst):
            shutil.copy(path, dst)
            made.append(dst)
    notes = os.path.join(spec, 'review_notes.md')
    if not os.path.exists(notes):
        open(notes, 'w', encoding='utf-8').write('# 主编复核备注（每篇一节：## NN，写清作废的旧数字和新口径）\n')
        made.append(notes)
    cfg = json.load(open(os.path.join(spec, 'series.json'), encoding='utf-8'))
    nums = [d['num'] for d in cfg.get('docs', [])] + ([cfg['hub']['num']] if cfg.get('hub') else [])
    for n in nums:
        for sub in ('seg', 'figs'):
            p = os.path.join(root, 'drafts', n, sub)
            if not os.path.isdir(p):
                os.makedirs(p)
                made.append(p)
        refs = os.path.join(root, 'drafts', n, 'refs.json')
        if not os.path.exists(refs):
            open(refs, 'w', encoding='utf-8').write('{}\n')
    env = {**os.environ, 'SERIES_ROOT': root}
    q = subprocess.run([sys.executable, os.path.join(HERE, 'render_prompt.py'), 'quick'], env=env, capture_output=True, text=True)
    print('\n'.join(made) or 'nothing new')
    print(q.stdout.strip() or q.stderr.strip())


if __name__ == '__main__':
    main()
