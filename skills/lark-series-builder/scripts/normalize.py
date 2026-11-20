"""Structural clean-up of drafts/NN/seg/*.xml after parallel writers (run before review and before publish).

    python3 normalize.py 05          # fix in place, print a report
    python3 normalize.py 05 --dry    # report only

Fixes:
  - escaped tag openers ('<h1&gt;'), wrapper tags (<section>, <figure>, <div>, <?xml?>…), Markdown bold and inline code
  - s00 keeps title + opening + 导读 + 分工; chapters written into s00 move to s00_1.xml or are dropped as duplicates
  - <title> is the registry title and comes first
  - chapters renumbered 1..N in file order; h2 'N.M' prefixes follow their chapter
  - every callout gets the emoji of its bold label and the series callout colour
  - hard-coded <a href="URL">[n]</a> becomes {{r:key}} when the URL is in refs.json; {{C:PFX-NN}} -> {{C:NN}}
Reports only: duplicate chapter titles, segments without a chapter, bare [n] citations, links missing from refs.json.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import ddir, docs, load, segs  # noqa: E402

WRAPPERS = r'<\?xml[^>]*\?>|</?(?:document|section|segment|root|content|body|article|chapter|figure|figcaption|div|span)\b[^>]*>'


def main():
    cfg = load()
    num, dry = sys.argv[1], '--dry' in sys.argv
    t = cfg['template']
    d = ddir(cfg, num)
    refs = json.load(open(os.path.join(d, 'refs.json'), encoding='utf-8'))
    by_url = {v['url'].rstrip('/'): k for k, v in refs.items()}
    paths = segs(cfg, num)
    texts = {p: open(p, encoding='utf-8').read() for p in paths}
    rep = []
    ch_open = t['chapter_h1'].split('{n}')[0]
    ch_close = t['chapter_h1'].split('{n}')[1]
    CH = re.compile('<h1>' + re.escape(ch_open) + r'(\d+)' + re.escape(ch_close) + r'([^<]*)</h1>')

    for p in paths:
        x = re.sub(r'<(/?)(h[1-6]|p|li|ul|ol|b|code|callout|table|tr|td|th)&gt;', r'<\1\2>', texts[p])
        x2 = re.sub(WRAPPERS, '', x)
        x2 = re.sub(r'<h2>' + re.escape(ch_open) + r'(\d+)\.(\d+) 节 · ', r'<h2>\1.\2 ', x2)
        x2 = re.sub(r'\*\*([^*<>\n]+)\*\*', r'<b>\1</b>', x2)
        parts = re.split(r'(<pre\b.*?</pre>)', x2, flags=re.S)
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r'`([^`\n]{1,120})`',
                              lambda m: '<code>' + m.group(1).replace('<', '&lt;').replace('>', '&gt;') + '</code>', parts[i])
        x2 = ''.join(parts)
        if x2 != texts[p]:
            rep.append(f'{os.path.basename(p)}: stripped wrappers / Markdown')
        texts[p] = x2

    s00 = paths[0] if paths and os.path.basename(paths[0]) == 's00.xml' else None
    want = docs(cfg).get(num, {}).get('title')
    if s00:
        x = texts[s00]
        for h in re.findall(r'<h1>(?!' + re.escape(t['guide_h1'].split(' ')[0]) + '|' + re.escape(ch_open) + r'\d)[^<]*</h1>', x):
            x = x.replace(h, '', 1)
            rep.append(f's00: removed stray h1 {h!r}')
        if want:
            if not x.lstrip().startswith(f'<title>{want}</title>'):
                rep.append('s00: title set to the registry title and moved first')
            x = f'<title>{want}</title>' + re.sub(r'<title>[^<]*</title>', '', x).lstrip()
        later = any(CH.search(texts[p]) for p in paths[1:])
        m = CH.search(x)
        if m and later:
            tail = x[m.start():]
            keep = re.findall(r'<p><b>' + re.escape(t['split']) + r'.*?</p>|<p>' + re.escape(t['split']) + r'.*?</p>', tail, flags=re.S)
            for k in keep:
                tail = tail.replace(k, '')
            x = x[:m.start()] + ''.join(keep)
            later_titles = {h.strip() for p in paths[1:] for _, h in CH.findall(texts[p])}
            moved = []
            for blk in re.split(r'(?=<h1>' + re.escape(ch_open) + r'\d)', tail):
                mt = CH.match(blk)
                if not mt:
                    continue
                if mt.group(2).strip() in later_titles:
                    rep.append(f's00: dropped duplicate chapter {mt.group(2)!r}')
                else:
                    moved.append(blk)
                    rep.append(f's00: moved chapter {mt.group(2)!r} to s00_1.xml')
            if moved:
                p1 = os.path.join(d, 'seg', 's00_1.xml')
                paths.insert(1, p1)
                texts[p1] = ''.join(moved)
        texts[s00] = x

    n, titles = 0, {}
    for p in (paths[1:] if s00 else paths):
        x = texts[p]
        heads = list(CH.finditer(x))
        if not heads:
            rep.append(f'{os.path.basename(p)}: no chapter h1')
            continue
        start = n + 1
        for h in heads:
            n += 1
            titles.setdefault(h.group(2).strip(), []).append(os.path.basename(p))
            if h.group(1) != str(n):
                rep.append(f'{os.path.basename(p)}: chapter {h.group(1)} -> {n}')
        it = iter(range(start, n + 1))
        x = CH.sub(lambda m: f'<h1>{ch_open}{next(it)}{ch_close}{m.group(2)}</h1>', x)
        out, pos, cur = [], 0, start
        for m in re.finditer(r'<h1>' + re.escape(ch_open) + r'(\d+)|<h2>(\d+)\.(\d+)', x):
            if m.group(1):
                cur = int(m.group(1))
                continue
            out.append(x[pos:m.start()] + f'<h2>{cur}.{m.group(3)}')
            pos = m.end()
        texts[p] = ''.join(out) + x[pos:]
    for title, files in titles.items():
        if len(files) > 1:
            rep.append(f'DUPLICATE chapter title {title!r} in {files}')

    cc = t['callout_color']

    def fix_callout(m):
        inner = m.group(2)
        emo = next((e for lab, e in t['callouts'].items() if lab in inner[:200]), None)
        if emo is None:
            mm = re.search(r'emoji="([^"&]+)"', m.group(1))
            emo = mm.group(1) if mm else '💡'
        return f'<callout emoji="{emo}" background-color="{cc["bg"]}" border-color="{cc["border"]}">' + inner + '</callout>'

    for p in paths:
        x = re.sub(r'<callout\b([^>]*)>(.*?)</callout>', fix_callout, texts[p], flags=re.S)
        x = re.sub(r'\{\{C:[A-Za-z]+-(\d+)\}\}', r'{{C:\1}}', x)
        x = re.sub(r'<a href="([^"]+)">\[\d+\]</a>',
                   lambda m: '{{r:' + by_url[m.group(1).rstrip('/')] + '}}' if m.group(1).rstrip('/') in by_url else m.group(0), x)
        left = re.findall(r'<a href="([^"]+)">\[\d+\]</a>', x)
        if left:
            rep.append(f'{os.path.basename(p)}: {len(left)} linked [n] not in refs.json, e.g. {left[0]}')
        bare = re.findall(r'(?<![">])\[\d+\]', re.sub(r'<pre.*?</pre>', '', x, flags=re.S))
        if bare:
            rep.append(f'{os.path.basename(p)}: {len(bare)} bare [n] citations (replace with {{{{r:key}}}})')
        texts[p] = x

    if not dry:
        for p in paths:
            open(p, 'w', encoding='utf-8').write(texts[p])
    print('\n'.join(rep) or 'clean')
    print(f'chapters={n}')


if __name__ == '__main__':
    main()
