#!/usr/bin/env python3
"""Cross-model check for lark-figure: each model turns the same prose briefs into specs; the engine scores them.

  run_eval.py prompt CASE_ID                 # the exact prompt a model gets for one case
  run_eval.py score DIR [--label NAME]       # score DIR/<case_id>.json files, however they were produced
  run_eval.py run -m MODEL [-m MODEL ...] -o DIR    # drive `codex exec` through the llmgw gateway, then score
  run_eval.py run --runner ccl -m MODEL ... -o DIR  # drive Claude Code on the llmbox profile (the `ccl` alias)

`run` with the codex runner needs LLMGW_OPENAI_API_KEY in the environment and always passes
`-c model_provider=llmgw`; without the key it exits 2 before starting any process, so a request can never fall back
to another endpoint. The ccl runner goes through ~/.claude/bin/claude-run llmbox, which resolves its own credential
and refuses to start without a gateway URL; it runs `--bare` (no CLAUDE.md, hooks or memory) with skills disabled, so
the model sees only the skill copy in its workdir. Either way this script never reads, prints or writes a credential.

Scores are mechanical (does it build, did the engine have to rewrite or drop anything, color and emphasis discipline,
chart type). Whether the figure is good is still a human look at the rendered PNGs.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SKILL = os.path.join(ROOT, 'skills', 'lark-figure')
sys.path.insert(0, os.path.join(SKILL, 'scripts'))

KEY_VAR, PROVIDER = 'LLMGW_OPENAI_API_KEY', 'llmgw'
CLAUDE_RUN, CCL_PROFILE = os.path.expanduser('~/.claude/bin/claude-run'), 'llmbox'
CCL_TOOLS = 'Read Write Edit Glob Grep Bash(python3:*) Bash(ls:*) Bash(cat:*)'
PROMPT = """You have one skill available, in the directory ./lark-figure .
Read ./lark-figure/SKILL.md first and follow it.
Use only what is in that directory; do not use the network and do not write to Lark.

{brief}

Deliver exactly one file: the figure spec as JSON at ./out/{case}.json . Check it with
`python3 lark-figure/scripts/figure.py build out/{case}.json -o out --no-render` and fix the spec until it passes.
"""


def cases():
    with open(os.path.join(HERE, 'cases.json'), encoding='utf-8') as f:
        return json.load(f)


def prompt_for(case):
    return PROMPT.format(brief=case['brief'], case=case['id'])


def score_one(case, path):
    """Mechanical facts about one produced spec. Never raises on bad model output: that is a result, not a crash."""
    from lfig.charts import CHARTS
    from lfig.compose import SpecError, _emphasised, build
    from lfig.lint import lint, summarize
    row = {'case': case['id'], 'produced': os.path.exists(path), 'builds': False}
    if not row['produced']:
        return row
    try:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
    except ValueError as e:
        return dict(row, error=f'not JSON: {e}')
    if not isinstance(spec, dict):
        return dict(row, error='spec is not a JSON object')
    try:
        svg, notes = build(spec)
    except SpecError as e:
        return dict(row, error='; '.join(e.errors)[:400])
    res = summarize(lint(svg))
    codes = [f['code'] for f in res['findings']]
    from lfig.normalize import normalize
    fixed = normalize(spec, CHARTS)[0]
    return dict(row, builds=True, lint_errors=res['errors'], type=fixed.get('type'),
                type_ok=fixed.get('type') in case['accept'],
                rewritten=sum(' read as ' in n for n in notes), dropped=sum('was ignored' in n for n in notes),
                families=svg_families(svg), emphasised=_emphasised(fixed),
                title_is_claim='TITLE-LABEL' not in codes, has_source=not any('no source given' in n for n in notes))


def svg_families(svg):
    """Color families the figure really uses, counted the way lint counts them."""
    import re

    from lfig.lint import family_of
    return len({family_of(c.lower()) for c in re.findall(r'#[0-9A-Fa-f]{6}', svg)} - {None, 'gray'})


def score_dir(d, label):
    rows = [score_one(c, os.path.join(d, c['id'] + '.json')) for c in cases()]
    ok = [r for r in rows if r['builds'] and not r['lint_errors']]
    summary = {'label': label, 'cases': len(rows), 'clean_builds': len(ok),
               'right_type': sum(r.get('type_ok', False) for r in rows),
               'within_3_families': sum(r.get('families', 9) <= 3 for r in ok),
               'within_2_emphasis': sum(r.get('emphasised', 9) <= 2 for r in ok),
               'title_is_claim': sum(r.get('title_is_claim', False) for r in ok),
               'fields_dropped': sum(r.get('dropped', 0) for r in rows),
               'fields_rewritten': sum(r.get('rewritten', 0) for r in rows)}
    return {'summary': summary, 'rows': rows}


def agent_cmd(runner, model, work, prompt):
    if runner == 'ccl':
        return ['bash', CLAUDE_RUN, CCL_PROFILE, '--bare', '--disable-slash-commands', '--model', model,
                '--permission-mode', 'acceptEdits', '--allowedTools', CCL_TOOLS, '-p', prompt]
    return ['codex', 'exec', '-c', f'model_provider={PROVIDER}', '-m', model, '-s', 'workspace-write',
            '--skip-git-repo-check', '--ephemeral', '-C', work, prompt]


def run_model(runner, model, out_dir, timeout, only=None):
    """One isolated workdir per case, holding only a copy of the skill."""
    dst = os.path.join(out_dir, model)
    os.makedirs(dst, exist_ok=True)
    for case in [c for c in cases() if not only or c['id'] in only]:
        with tempfile.TemporaryDirectory(prefix='lfig_eval_') as work:
            shutil.copytree(SKILL, os.path.join(work, 'lark-figure'))
            os.makedirs(os.path.join(work, 'out'))
            cmd = agent_cmd(runner, model, work, prompt_for(case))
            try:
                r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout, check=False)
                status = f'exit {r.returncode}'
                with open(os.path.join(dst, case['id'] + '.log'), 'w', encoding='utf-8') as f:
                    f.write(r.stdout + r.stderr)
            except subprocess.TimeoutExpired:
                status = f'timeout after {timeout}s'
            made = os.path.join(work, 'out', case['id'] + '.json')
            if os.path.exists(made):
                shutil.copy(made, os.path.join(dst, case['id'] + '.json'))
            print(f'{model} {case["id"]}: {status}', file=sys.stderr)
    return dst


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('prompt')
    s.add_argument('case')
    s = sub.add_parser('score')
    s.add_argument('dir')
    s.add_argument('--label')
    s = sub.add_parser('run')
    s.add_argument('-m', '--model', action='append', required=True)
    s.add_argument('-o', '--out', required=True)
    s.add_argument('--runner', choices=('codex', 'ccl'), default='codex')
    s.add_argument('--case', action='append', help='run only these case ids (repeatable); scoring still covers all')
    s.add_argument('--timeout', type=int, default=900)
    a = p.parse_args(argv)
    if a.cmd == 'prompt':
        match = [c for c in cases() if c['id'] == a.case]
        if not match:
            sys.exit(f'unknown case {a.case!r}; one of: {", ".join(c["id"] for c in cases())}')
        print(prompt_for(match[0]))
        return 0
    if a.cmd == 'score':
        label = a.label or os.path.basename(os.path.abspath(a.dir))
        print(json.dumps(score_dir(a.dir, label), ensure_ascii=False, indent=1))
        return 0
    if a.runner == 'ccl' and not (os.path.isfile(CLAUDE_RUN) and shutil.which('claude')):
        print(f'the ccl runner needs {CLAUDE_RUN} and claude on PATH', file=sys.stderr)
        return 2
    if a.runner == 'codex' and not os.environ.get(KEY_VAR):
        print(f'{KEY_VAR} is not set. `run` only goes through the {PROVIDER} gateway and will not start without it.',
              file=sys.stderr)
        return 2
    if a.runner == 'codex' and not shutil.which('codex'):
        print('codex CLI not found on PATH', file=sys.stderr)
        return 2
    results = [score_dir(run_model(a.runner, m, a.out, a.timeout, a.case), m) for m in a.model]
    with open(os.path.join(a.out, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(json.dumps([r['summary'] for r in results], ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
