"""Shared helpers for every script: series root, config, doc registry, prose stripping, lark-cli calls.

Series root = the directory holding spec/series.json (found from $SERIES_ROOT or by walking up from cwd).
Config = assets/series.default.json deep-merged with ROOT/spec/series.json.
Layout under ROOT:
  spec/series.json  spec/MAINLINE.md  spec/QUICK.md  spec/cards/NN.md  spec/review_notes.md
  drafts/NN/{refs.json, facts.md, outline.md, code_outputs.md, seg/sXX.xml, figs/NAME.py|svg, doc.xml, pv/}
"""
import copy
import json
import os
import re
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(SKILL, 'assets', 'series.default.json')
CJK = re.compile(r'[一-鿿]')
LARK_ENV = {**os.environ, 'LARKSUITE_CLI_NO_UPDATE_NOTIFIER': '1', 'LARKSUITE_CLI_NO_SKILLS_NOTIFIER': '1'}


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def find_root(required=True):
    env = os.environ.get('SERIES_ROOT')
    if env:
        return os.path.abspath(os.path.expanduser(env))
    d = os.getcwd()
    while not os.path.exists(os.path.join(d, 'spec', 'series.json')):
        if os.path.dirname(d) == d:
            if required:
                sys.exit('series root not found: cd into it or export SERIES_ROOT (it must contain spec/series.json)')
            return None
        d = os.path.dirname(d)
    return d


def load(required=True):
    cfg = json.load(open(DEFAULT, encoding='utf-8'))
    root = find_root(required)
    if root:
        cfg = merge(cfg, json.load(open(os.path.join(root, 'spec', 'series.json'), encoding='utf-8')))
    cfg['_root'] = root
    return cfg


def docs(cfg):
    """num -> registry entry, hub included."""
    out = {d['num']: d for d in cfg.get('docs', [])}
    if cfg.get('hub'):
        out[cfg['hub']['num']] = cfg['hub']
    return out


def is_hub(cfg, num):
    return bool(cfg.get('hub')) and cfg['hub']['num'] == num


def ddir(cfg, num):
    return os.path.join(cfg['_root'], 'drafts', num)


def segs(cfg, num):
    d = os.path.join(ddir(cfg, num), 'seg')
    return sorted(os.path.join(d, f) for f in os.listdir(d) if re.match(r's\d.*\.xml$', f)) if os.path.isdir(d) else []


def chapter_re(cfg):
    """Regex for numbered chapter h1, groups: (number, title)."""
    head = re.escape(cfg['template']['chapter_h1']).replace(re.escape('{n}'), r'(\d+)')
    return re.compile('<h1>' + head + r'([^<]*)</h1>')


def strip_prose(xml):
    """Prose only: drop figures, tables, code, cites and tags, so style checks never fire on non-prose."""
    s = re.sub(r'<whiteboard[^>]*>.*?</whiteboard>|<table.*?</table>|<pre.*?</pre>|<cite[^>]*>.*?</cite>'
               r'|<code[^>]*>.*?</code>|\{\{[^}]*\}\}', ' ', xml, flags=re.S)
    s = re.sub(r'</(?:p|li|h\d|title)>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    return s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')


def cjk(s):
    return len(CJK.findall(s))


def sentence_lengths(prose):
    parts = re.split(r'[。！？；\n]', prose)
    return [len(re.sub(r'\s', '', p)) for p in parts if cjk(p) >= 4]


def lark(args, cwd=None):
    """Run lark-cli and return parsed JSON; exit with the raw output on failure."""
    r = subprocess.run(['lark-cli', *args], cwd=cwd, capture_output=True, text=True, env=LARK_ENV)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f'lark-cli {" ".join(args[:3])} failed: rc={r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}')
