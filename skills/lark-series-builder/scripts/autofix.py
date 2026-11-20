"""Mechanical punctuation and escaping fixes for drafts/NN/seg/*.xml (prose only).

    python3 autofix.py 05

Skips <pre>, <code>, <whiteboard>, tag markup and {{placeholders}}. Fixes:
  - bare '<' before a digit/space/=… and bare '&' (they break XML) -> &lt; / &amp;
  - straight double quotes around or touching CJK -> “…”
  - half-width ( ) around or touching CJK -> （ ）
  - half-width , ; : ? ! right after CJK -> ，；：？！
Dashes and wording red lines need rewording by an agent; this script does not touch them.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import load, segs  # noqa: E402

CJK = r'[一-鿿]'
SKIP = re.compile(r'(<pre\b.*?</pre>|<code\b.*?</code>|<whiteboard\b.*?</whiteboard>|\{\{[^}]*\}\}|<[^>]+>)', re.S)
PAIRS = {',': '，', ';': '；', ':': '：', '?': '？', '!': '！'}


def fix_text(t):
    n = 0

    def q(m):
        nonlocal n
        n += 1
        return '“' + m.group(1) + '”'
    t = re.sub(r'"([^"<>\n]{0,80}?' + CJK + r'[^"<>\n]{0,80}?)"', q, t)
    t = re.sub(r'(?<=' + CJK + r')"([^"<>\n]{1,60})"', q, t)
    t = re.sub(r'"([^"<>\n]{1,60})"(?=' + CJK + r')', q, t)

    def paren(m):
        nonlocal n
        n += 1
        return '（' + m.group(1) + '）'
    t = re.sub(r'\(([^()<>\n]{0,80}?' + CJK + r'[^()<>\n]{0,80}?)\)', paren, t)
    t = re.sub(r'(?<=' + CJK + r')\(([^()<>\n]{0,80}?)\)', paren, t)

    def punct(m):
        nonlocal n
        n += 1
        return PAIRS[m.group(1)]
    t = re.sub(r'(?<=' + CJK + r')([,;:?!])(?!//)', punct, t)
    return t, n


def main():
    cfg = load()
    total = 0
    for p in segs(cfg, sys.argv[1]):
        x = open(p, encoding='utf-8').read()
        x = re.sub(r'<(?=[\s=\d$¥~≈±.])', '&lt;', x)
        x = re.sub(r'&(?!(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);)', '&amp;', x)
        parts = SKIP.split(x)
        cnt = 0
        for i in range(0, len(parts), 2):
            parts[i], k = fix_text(parts[i])
            cnt += k
        y = ''.join(parts)
        if y != open(p, encoding='utf-8').read():
            open(p, 'w', encoding='utf-8').write(y)
        total += cnt
        print(f'{os.path.basename(p)}: {cnt} fixes')
    print(f'total {total}')


if __name__ == '__main__':
    main()
