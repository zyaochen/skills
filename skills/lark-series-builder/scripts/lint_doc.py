"""Machine acceptance for one doc: structure, citations, figures, style. ERROR must be 0 before publishing.

    python3 lint_doc.py 05                      # lints drafts/05/doc.xml
    python3 lint_doc.py path/doc.xml --num 05

All rules and thresholds come from config (template, thresholds, style, board). Style rules scan prose only:
figures, tables, code, cites are stripped first. Exit 1 when any ERROR line exists.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import chapter_re, cjk, ddir, docs, is_hub, load, sentence_lengths, strip_prose  # noqa: E402
from svgkit import check_svg  # noqa: E402

PUNCT = re.compile(r'[一-鿿][,;:?!()]|[,;:?!(][一-鿿]')
QUOTE = re.compile(r'[一-鿿]"|"[一-鿿]')


def rng(v, lo_hi):
    return lo_hi[0] <= v <= lo_hi[1]


def lint(cfg, num, xml):
    t, th, st = cfg['template'], cfg['thresholds'], cfg['style']
    reg = docs(cfg)
    me = reg.get(num, {})
    hub = is_hub(cfg, num)
    E, W = [], []
    try:
        ET.fromstring('<root>' + xml + '</root>')
    except ET.ParseError as e:
        E.append(f'XML not well-formed: {e}')
    m = re.match(r'\s*<title>([^<]+)</title>', xml)
    if not m:
        E.append('missing leading <title>')
    elif me and m.group(1) != me['title']:
        E.append(f'title differs from registry: {m.group(1)!r} vs {me["title"]!r}')

    need = t['hub_required'] if hub else t['required'] + t['required_terms'] + ([t['position']] if t['position'] else [])
    for s in need:
        if s not in xml:
            E.append(f'missing required element: {s}')

    body = xml.split(f'<h1>{t["refs_h1"]}</h1>')[0]
    chre = chapter_re(cfg)
    chapters = chre.findall(body)
    if not hub:
        if not rng(len(chapters), th['chapters']):
            W.append(f'{len(chapters)} numbered chapters (expected {th["chapters"][0]}-{th["chapters"][1]})')
        if [int(n) for n, _ in chapters] != list(range(1, len(chapters) + 1)):
            E.append(f'chapter numbers not 1..N: {[n for n, _ in chapters]}')
        if chapters and t['first_chapter_contains'] and t['first_chapter_contains'] not in chapters[0][1]:
            E.append(f'chapter 1 title must contain {t["first_chapter_contains"]!r}: {chapters[0][1]!r}')
        if chapters and t['last_chapter_contains'] and t['last_chapter_contains'] not in chapters[-1][1]:
            E.append(f'last chapter title must contain {t["last_chapter_contains"]!r}: {chapters[-1][1]!r}')
        blocks = re.split(r'(?=<h1>)', body)
        for b in blocks:
            mm = chre.match(b)
            if not mm:
                continue
            n_h2 = len(re.findall(r'<h2>', b))
            if not rng(n_h2, th['h2_per_chapter']):
                W.append(f'chapter {mm.group(1)} has {n_h2} h2 (expected {th["h2_per_chapter"][0]}-{th["h2_per_chapter"][1]})')
            if '本章要点' in t['callouts'] and not re.search(r'<callout[^>]*>\s*<p><b>(本章要点|小结)', b):
                W.append(f'chapter {mm.group(1)} has no 🔑 本章要点 callout')
        g = re.search(re.escape(f'<h1>{t["guide_h1"]}</h1>') + r'(.*?)(?=<h1>)', body, flags=re.S)
        if g:
            items = re.findall(r'<li>(.*?)</li>', g.group(1), flags=re.S)
            if not rng(len(items), th['guide_items']):
                W.append(f'导读 has {len(items)} conclusions (expected {th["guide_items"][0]}-{th["guide_items"][1]})')
            if any(not i.lstrip().startswith('<b>') for i in items):
                W.append('导读 items must start with a bold one-sentence conclusion')
        if t['position']:
            pos = re.search(r'<p>[^\n]*?' + re.escape(t['position']) + r'.*?</p>', xml, flags=re.S)
            for k in ('prev', 'next'):
                other = reg.get(me.get(k) or '')
                if pos and other and other['token'] not in pos.group(0):
                    W.append(f'{t["position"]} paragraph does not cite {k} doc {me[k]}')
        pit = len(re.findall(r'<callout[^>]*>\s*<p><b>常见误区', xml))
        if not rng(pit, th['pitfalls']):
            W.append(f'{pit} 💡 常见误区 callouts (expected {th["pitfalls"][0]}-{th["pitfalls"][1]})')

    for attrs in re.findall(r'<callout\b([^>]*)>', xml):
        cc = t['callout_color']
        if f'background-color="{cc["bg"]}"' not in attrs or f'border-color="{cc["border"]}"' not in attrs:
            E.append(f'callout colour must be {cc}: <callout{attrs[:80]}>')
            break
    for cols in re.findall(r'<colgroup>(.*?)</colgroup>', xml, flags=re.S):
        tw = sum(int(x) for x in re.findall(r'width="(\d+)"', cols))
        if not rng(tw, th['table_width']):
            W.append(f'table column widths sum to {tw} (expected {th["table_width"][0]}-{th["table_width"][1]})')

    wbs = re.findall(r'<whiteboard type="svg">(.*?)</whiteboard>', xml, flags=re.S)
    if re.search(r'<whiteboard(?! type="svg")[^>]*>', xml):
        E.append('non-SVG whiteboard (mermaid or old token): redraw as SVG')
    if not hub and not rng(len(wbs), th['figures']):
        W.append(f'{len(wbs)} figures (expected {th["figures"][0]}-{th["figures"][1]})')
    seen = {}
    for i, svg in enumerate(wbs, 1):
        title = re.search(r'font-weight="bold"[^>]*>([^<]{0,30})', svg)
        tag = f'figure {i} ({title.group(1) if title else "?"})'
        if svg in seen:
            E.append(f'{tag}: duplicate of figure {seen[svg]} (same {{{{F:name}}}} placed twice?)')
            continue
        seen[svg] = i
        for issue in check_svg(svg):
            (E if issue.startswith('E') else W).append(f'{tag}: {issue[2:]}')

    for tok, title in re.findall(r'<cite type="doc" doc-id="([^"]+)"[^>]*title="([^"]*)"', xml):
        hit = next((d for d in reg.values() if d['token'] == tok), None)
        if not hit:
            E.append(f'cite to unknown doc token {tok}')
        elif hit['title'] != title.replace('&amp;', '&').replace('&quot;', '"'):
            E.append(f'cite title mismatch for {tok}: {title!r} vs {hit["title"]!r}')
        elif me and tok == me.get('token'):
            E.append('doc cites itself; own chapters are written as 第 N 章')

    refsec = xml.split(f'<h1>{t["refs_h1"]}</h1>')[-1] if f'<h1>{t["refs_h1"]}</h1>' in xml else ''
    listed = [int(x) for x in re.findall(r'<p>\[(\d+)\]', refsec)]
    used = {int(x) for x in re.findall(r'>\[(\d+)\]</a>', body)}
    if listed != list(range(1, len(listed) + 1)):
        E.append('reference list numbering is not 1..N in order')
    if not hub and not rng(len(listed), th['refs']):
        W.append(f'{len(listed)} references (expected {th["refs"][0]}-{th["refs"][1]})')
    if sorted(used - set(listed)):
        E.append(f'cited but not listed: {sorted(used - set(listed))[:20]}')
    if sorted(set(listed) - used):
        W.append(f'listed but never cited: {sorted(set(listed) - used)[:20]}')
    if re.search(r'(?<![">])\[\d+\](?!</a>)', re.sub(r'<pre.*?</pre>|<whiteboard.*?</whiteboard>', '', body, flags=re.S)):
        W.append('bare [n] in prose without a link: use {{r:key}}')

    p = strip_prose(body)
    for name, rx in st['red'].items():
        hits = re.findall(rx, body if rx.startswith('<') else p)
        if hits:
            E.append(f'style red line {name}: {len(hits)} hit(s), e.g. {str(hits[0])[:40]!r}')
    for rx, name in ((PUNCT, 'half-width punctuation next to CJK'), (QUOTE, 'straight quote next to CJK')):
        hits = rx.findall(p)
        if hits:
            E.append(f'{name}: {len(hits)} hit(s), e.g. {hits[:5]}')
    if re.search(r'\*\*[^*]+\*\*|`[^`\n]+`|^\s*#{1,3} ', p, flags=re.M):
        E.append('Markdown syntax in prose (** ` #): use <b>, <code>, <h2>')
    n_chars = len(re.sub(r'\s', '', p))
    if not hub and not rng(n_chars, th['prose_chars']):
        W.append(f'prose {n_chars} chars (expected {th["prose_chars"][0]}-{th["prose_chars"][1]})')
    per10k = max(n_chars, 1) / 10000
    for name, rx in st['soft'].items():
        dens = len(re.findall(rx, p)) / per10k
        cap = st.get('soft_per_10k_max', {}).get(name)
        if cap is not None and dens > cap:
            W.append(f'soft style {name}: {dens:.1f} per 10k chars (max {cap})')
    sl = sentence_lengths(p)
    mean = sum(sl) / len(sl) if sl else 0
    if sl and not rng(mean, th['sentence_mean']):
        W.append(f'mean sentence length {mean:.1f} (expected {th["sentence_mean"][0]}-{th["sentence_mean"][1]})')
    summary = (f'SUMMARY errors={len(E)} warns={len(W)} figures={len(wbs)} chapters={len(chapters)} refs={len(listed)} '
               f'prose_chars={n_chars} cjk={cjk(p)} sent_mean={mean:.1f}')
    return E, W, summary


def main():
    cfg = load()
    a = sys.argv[1]
    if re.fullmatch(r'\d+', a):
        num, path = a, os.path.join(ddir(cfg, a), 'doc.xml')
    else:
        path = a
        num = sys.argv[sys.argv.index('--num') + 1] if '--num' in sys.argv else os.path.basename(os.path.dirname(os.path.abspath(a)))
    E, W, summary = lint(cfg, num, open(path, encoding='utf-8').read())
    for e in E:
        print('ERROR', e)
    for w in W:
        print('WARN ', w)
    print(summary)
    sys.exit(1 if E else 0)


if __name__ == '__main__':
    main()
