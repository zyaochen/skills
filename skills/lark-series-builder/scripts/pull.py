"""Pull a published doc back into segment drafts (entry point for improving an existing series).

    python3 pull.py 05                 # fetch the live doc -> drafts/05/{live.xml, refs.json, seg/*.xml, old_pv/}
    python3 pull.py 05 --from x.xml    # use a saved XML instead of fetching
    python3 pull.py 05 --force         # existing seg/ is moved to seg_bak_N/ first (default: refuse)
    python3 pull.py 05 --no-previews   # skip exporting old whiteboard images

What it does:
  - reference list -> refs.json (merged; an URL already present keeps its key)
  - <a href="URL">[n]</a> -> {{r:key}};  <cite doc-id=TOKEN> of a registered doc -> {{C:NN}}
  - every old whiteboard -> {{F:oldK}} plus drafts/NN/old_pv/figK.jpg. Old whiteboard tokens do not survive a
    whole-doc overwrite, so the build fails until each oldK is redrawn as figs/oldK.py (svgkit) or replaced.
  - split: s00 = everything before the first numbered chapter, then one sNN.xml per chapter
Then run normalize.py NN (restores callout colours, renumbers) and build.py NN to see what is missing.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import chapter_re, ddir, docs, lark, load  # noqa: E402


def slug(cite, url, used):
    words = re.findall(r'[A-Za-z][A-Za-z0-9]+', cite)[:3] or re.findall(r'[A-Za-z0-9]+', url.split('//')[-1])[:2]
    base = '_'.join(w.lower() for w in words)[:32] or 'ref'
    key, i = base, 2
    while key in used:
        key, i = f'{base}_{i}', i + 1
    return key


def main():
    cfg = load()
    num = sys.argv[1]
    d = ddir(cfg, num)
    reg = docs(cfg)
    os.makedirs(d, exist_ok=True)
    if '--from' in sys.argv:
        xml = open(sys.argv[sys.argv.index('--from') + 1], encoding='utf-8').read()
    else:
        xml = lark(['docs', '+fetch', '--as', 'user', '--doc', reg[num]['token']], d)['data']['document']['content']
        open(os.path.join(d, 'live.xml'), 'w', encoding='utf-8').write(xml)
    seg = os.path.join(d, 'seg')
    if os.path.isdir(seg) and os.listdir(seg):
        if '--force' not in sys.argv:
            sys.exit(f'{seg} is not empty; pass --force to move it aside first')
        k = 1
        while os.path.exists(os.path.join(d, f'seg_bak_{k}')):
            k += 1
        shutil.move(seg, os.path.join(d, f'seg_bak_{k}'))
    os.makedirs(seg, exist_ok=True)

    t = cfg['template']
    head = f'<h1>{t["refs_h1"]}</h1>'
    body, _, refsec = xml.partition(head)
    rp = os.path.join(d, 'refs.json')
    refs = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}
    by_url = {v['url'].rstrip('/'): k for k, v in refs.items()}
    num_url = {}
    for n, cite, url in re.findall(r'<p>\[(\d+)\]\s*(.*?)\s*<a href="([^"]+)"', refsec, flags=re.S):
        cite = re.sub(r'<[^>]+>', '', cite).replace('&amp;', '&').strip()
        u = url.replace('&amp;', '&')
        if u.rstrip('/') not in by_url:
            key = slug(cite, u, refs)
            refs[key] = {'cite': cite, 'url': u}
            by_url[u.rstrip('/')] = key
        num_url[n] = u
    json.dump(refs, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    def cite_ref(m):
        k = by_url.get(m.group(1).replace('&amp;', '&').rstrip('/'))
        return '{{r:' + k + '}}' if k else m.group(0)
    body = re.sub(r'<a href="([^"]+)">\[\d+\]</a>', cite_ref, body)
    tok2num = {v['token']: k for k, v in reg.items()}
    body = re.sub(r'<cite\b[^>]*doc-id="([^"]+)"[^>]*>(?:</cite>)?',
                  lambda m: '{{C:' + tok2num[m.group(1)] + '}}' if m.group(1) in tok2num else m.group(0), body)

    boards = []

    def board(m):
        boards.append(m.group(1))
        return '{{F:old%d}}' % len(boards)
    body = re.sub(r'<whiteboard token="([^"]+)"[^>]*?(?:/>|>.*?</whiteboard>)', board, body, flags=re.S)
    if boards and '--no-previews' not in sys.argv and '--from' not in sys.argv:
        os.makedirs(os.path.join(d, 'old_pv'), exist_ok=True)
        for i, tok in enumerate(boards, 1):
            lark(['whiteboard', '+query', '--as', 'user', '--whiteboard-token', tok, '--output_as', 'image',
                  '--output', f'./old_pv/fig{i}.jpg', '--overwrite'], d)

    parts = re.split(r'(?=<h1>' + re.escape(t['chapter_h1'].split('{n}')[0]) + r'\d)', body)
    files = [('s00.xml', parts[0])] + [(f's{i:02d}.xml', p) for i, p in enumerate(parts[1:], 1)]
    for name, text in files:
        open(os.path.join(seg, name), 'w', encoding='utf-8').write(text.strip() + '\n')
    n_ch = len(chapter_re(cfg).findall(body))
    print(f'PULL {num}: segments={len(files)} chapters={n_ch} refs={len(refs)} (from list: {len(num_url)}) '
          f'old_figures={len(boards)}')
    if boards:
        print(f'redraw needed: {{{{F:old1}}}}..{{{{F:old{len(boards)}}}}} -> figs/oldK.py (previews in old_pv/)')
    print(f'next: python3 {os.path.dirname(os.path.abspath(__file__))}/normalize.py {num} && build.py {num} --quiet')


if __name__ == '__main__':
    main()
