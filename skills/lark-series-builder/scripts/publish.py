"""Publish one doc: lint, overwrite the Lark doc in place, fetch back, export figure previews.

    python3 publish.py 05             # lint -> overwrite -> drafts/05/pv/figNN.jpg
    python3 publish.py 05 --dry       # lint only
    python3 publish.py 05 --previews  # re-export previews of what is live

The token comes from the registry (spec/series.json); never pass one by hand. The live version before the
overwrite is saved to drafts/NN/live_before.xml. A response with result != success (e.g. partial_success
'ViewType(oneof)') usually means unsupported tags slipped in: run normalize.py, rebuild, publish again.
lark-cli runs as --as user only.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import ddir, docs, lark, load  # noqa: E402


def fetch(tok, cwd):
    return lark(['docs', '+fetch', '--as', 'user', '--doc', tok], cwd)['data']['document']['content']


def previews(tok, d):
    pv = os.path.join(d, 'pv')
    os.makedirs(pv, exist_ok=True)
    xml = fetch(tok, d)
    open(os.path.join(d, 'live.xml'), 'w', encoding='utf-8').write(xml)
    toks = re.findall(r'<whiteboard token="([^"]+)"', xml)
    for i, t in enumerate(toks, 1):
        lark(['whiteboard', '+query', '--as', 'user', '--whiteboard-token', t, '--output_as', 'image',
              '--output', f'./pv/fig{i:02d}.jpg', '--overwrite'], d)
    print(json.dumps({'doc': tok, 'figures': len(toks), 'previews': [f'pv/fig{i:02d}.jpg' for i in range(1, len(toks) + 1)],
                      'live_chars': len(xml)}, ensure_ascii=False))


def main():
    cfg = load()
    num = sys.argv[1]
    d = ddir(cfg, num)
    tok = docs(cfg)[num]['token']
    if '--previews' in sys.argv:
        return previews(tok, d)
    here = os.path.dirname(os.path.abspath(__file__))
    lint = subprocess.run([sys.executable, os.path.join(here, 'lint_doc.py'), num], capture_output=True, text=True)
    print('\n'.join(ln for ln in lint.stdout.splitlines() if ln.startswith(('ERROR', 'SUMMARY'))))
    if lint.returncode != 0:
        sys.exit('lint has ERROR lines; fix the segments, rebuild, then publish')
    if '--dry' in sys.argv:
        return
    open(os.path.join(d, 'live_before.xml'), 'w', encoding='utf-8').write(fetch(tok, d))
    j = lark(['docs', '+update', '--as', 'user', '--doc', tok, '--command', 'overwrite', '--content', '@doc.xml'], d)
    json.dump(j, open(os.path.join(d, 'publish_resp.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    data = j.get('data', {})
    new = data.get('document', {}).get('new_blocks', [])
    print(json.dumps({'ok': j.get('ok'), 'result': data.get('result'), 'warnings': data.get('warnings'),
                      'new_whiteboards': len([b for b in new if b.get('block_type') == 'whiteboard'])}, ensure_ascii=False))
    if not j.get('ok') or data.get('result') not in (None, 'success'):
        sys.exit('overwrite did not fully succeed, see publish_resp.json (run normalize.py, rebuild, retry)')
    previews(tok, d)


if __name__ == '__main__':
    main()
