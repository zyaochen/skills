"""Theme, text measurement and the low-level SVG canvas every chart draws on.

Coordinates are absolute pixels on a 1200-wide canvas. Chart renderers never pick colors or sizes
themselves: they ask the theme (``T``) through ``fam()`` / ``T['type']`` so one JSON file controls the look.
"""
import json
import os
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_THEME = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'assets', 'theme.json')

T = {}


def load_theme(path=None):
    with open(path or DEFAULT_THEME, encoding='utf-8') as f:
        T.clear()
        T.update(json.load(f))
    return T


load_theme()

NO_BREAK_BEFORE = set('，。、；：？！）」』》】,.;:?!)%')
NO_BREAK_AFTER = set('（「『《【(')


def is_cjk(c):
    return ord(c) > 0x2e80


NARROW = set("ijlI.,:;|!'`()[]{}")
WIDE = set('mwMW@%')


def char_w(c, bold=False):
    """Advance width in em, per character class, fitted to whiteboard-cli's own text box widths."""
    m = T['measure']
    if is_cjk(c):
        return m['bold_cjk'] if bold else m['cjk']
    if c == ' ':
        w = m['space']
    elif c in NARROW:
        w = m['narrow']
    elif c in WIDE:
        w = m['wide']
    elif c.isdigit():
        w = m['digit']
    elif c.isupper():
        w = m['upper']
    elif c.islower():
        w = m['lower']
    else:
        w = m['other']
    return w * (m['bold_latin'] if bold else 1)


def measure(s, size, bold=False):
    """Width the whiteboard will give this text (it measures bold ~20% wider, so pass bold for bold text)."""
    return sum(char_w(c, bold) for c in str(s)) * size + T['measure']['pad']


def _tokens(s):
    """Split into breakable units: one CJK char, or one Latin word with its trailing space."""
    out, buf = [], ''
    for c in s:
        if is_cjk(c):
            if buf:
                out.append(buf)
                buf = ''
            out.append(c)
        else:
            buf += c
            if c == ' ':
                out.append(buf)
                buf = ''
    if buf:
        out.append(buf)
    # glue punctuation so it never starts a line, and open brackets so they never end one
    glued = []
    for tok in out:
        if glued and (tok[0] in NO_BREAK_BEFORE or glued[-1][-1] in NO_BREAK_AFTER):
            glued[-1] += tok
        else:
            glued.append(tok)
    return glued


WRAP_EPS = 0.01  # absorbs float round-trip when a caller derives maxw from a measured width


def _unwidow(prev, last, size, maxw, bold, short):
    """Move the last word of ``prev`` down onto a too-short ``last`` line, unless that overflows or strands ``prev``."""
    cut = len(prev) - 1
    while cut > 0 and not prev[cut].strip():
        cut -= 1
    keep, moved = prev[:cut], prev[cut:] + last
    if (measure(''.join(keep).rstrip(), size, bold) >= short
            and measure(''.join(moved).rstrip(), size, bold) <= maxw + WRAP_EPS):
        return keep, moved
    return prev, last


def wrap(s, size, maxw, bold=False):
    """Greedy line wrap. Explicit '\\n' forces a break. Over-long Latin words are split by char.

    A paragraph never ends on a line shorter than two CJK chars if the line above can spare a word.
    """
    lim = maxw + WRAP_EPS
    short = 2 * T['measure']['cjk'] * size + T['measure']['pad']
    out = []
    for para in str(s).split('\n'):
        lines, cur = [], []  # each line is a list of tokens, so words keep their spaces when they move
        for tok in _tokens(para):
            if cur and measure(''.join(cur) + tok, size, bold) > lim:
                lines.append(cur)
                cur, tok = [], tok.lstrip()
            if tok:
                cur.append(tok)
            text = ''.join(cur)
            while measure(text, size, bold) > lim and len(text) > 1:
                cut = len(text)
                while cut > 1 and measure(text[:cut], size, bold) > lim:
                    cut -= 1
                lines.append([text[:cut]])
                text = text[cut:]
                cur = [text]
        if cur or not lines:
            lines.append(cur)
        if len(lines) > 1 and measure(''.join(lines[-1]).rstrip(), size, bold) < short:
            lines[-2], lines[-1] = _unwidow(lines[-2], lines[-1], size, maxw, bold, short)
        out += [''.join(ln).rstrip() for ln in lines]
    return out


def fit(s, maxw, sizes, max_lines=2, bold=False):
    """Largest size from ``sizes`` whose wrap fits in ``max_lines``; otherwise smallest size, wrapped."""
    for size in sizes:
        lines = wrap(s, size, maxw, bold)
        if len(lines) <= max_lines:
            return size, lines
    return sizes[-1], wrap(s, sizes[-1], maxw, bold)


def lh(size):
    return round(size * T['type']['line_height'])


def fam(tone):
    """Resolve a tone (semantic name or family name) to its color family dict."""
    tone = tone or 'base'
    name = T['tones'].get(tone, tone)
    if name not in T['families']:
        raise ValueError(f'unknown tone {tone!r}; use one of {sorted(T["tones"]) + sorted(T["families"])}')
    return T['families'][name]


def family_name(tone):
    tone = tone or 'base'
    return T['tones'].get(tone, tone)


def pairs(pts):
    """Consecutive pairs: the segments of a polyline. (itertools.pairwise needs Python 3.10.)"""
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def _n(v):
    v = round(float(v), 1)
    return int(v) if v == int(v) else v


def _txt(s):
    # the doc layer turns &lt; back into '<' and truncates the SVG, so angle brackets go full-width
    return escape(str(s).replace('<', '＜').replace('>', '＞'), quote=False)


class Canvas:
    def __init__(self, width=None, density=None):
        self.w = width or T['canvas']['width']
        self.density = density if density in ('compact', 'normal', 'airy') else 'normal'
        self.els = []
        self.bottom = 0
        self.families = set()
        self.notes = []  # things a chart had to give up on; build() hands them to the author

    def row_h(self, base):
        """Density-scaled row height. compact=0.8×, normal=1.0×, airy=1.15×."""
        scale = T['canvas'].get('density_row_scale', {}).get(self.density, 1.0)
        return max(20, round(base * scale))

    def _grow(self, y):
        self.bottom = max(self.bottom, y)

    def use(self, tone):
        n = family_name(tone)
        if n != 'gray':
            self.families.add(n)
        return fam(tone)

    def text(self, x, y, s, size=None, color=None, bold=False, anchor='start', role=None):
        size = size or T['type']['body']
        attrs = f'x="{_n(x)}" y="{_n(y)}" font-size="{size}" fill="{color or T["ink"]}"'
        if bold:
            attrs += ' font-weight="bold"'
        if anchor != 'start':
            attrs += f' text-anchor="{anchor}"'
        if role:
            attrs += f' data-role="{role}"'
        self.els.append(f'<text {attrs}>{_txt(s)}</text>')
        self._grow(y + size * 0.3)

    def lines(self, x, y_top, lines, size, color=None, bold=False, anchor='start', role=None):
        """Draw pre-wrapped lines whose first line box starts at ``y_top``. Returns block height."""
        step = lh(size)
        for i, ln in enumerate(lines):
            self.text(x, y_top + i * step + (step + size * 0.7) / 2, ln, size, color, bold, anchor, role)
        return step * len(lines)

    def rect(self, x, y, w, h, fill=None, stroke=None, rx=0, sw=1, dash=False, opacity=None, role=None):
        a = f'x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"'
        if rx:
            a += f' rx="{_n(rx)}"'
        a += f' fill="{fill or "none"}"'
        if opacity is not None:
            a += f' fill-opacity="{opacity}"'
        if stroke:
            a += f' stroke="{stroke}" stroke-width="{sw}"'
            if dash:
                a += ' stroke-dasharray="6 4"'
        if role:
            a += f' data-role="{role}"'
        self.els.append(f'<rect {a}/>')
        self._grow(y + h)

    def circle(self, cx, cy, r, fill=None, stroke=None, sw=1, role=None):
        a = f'cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" fill="{fill or "none"}"'
        if stroke:
            a += f' stroke="{stroke}" stroke-width="{sw}"'
        if role:
            a += f' data-role="{role}"'
        self.els.append(f'<circle {a}/>')
        self._grow(cy + r)

    def line(self, x1, y1, x2, y2, color=None, sw=1, dash=False):
        d = ' stroke-dasharray="6 4"' if dash else ''
        self.els.append(f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
                        f'stroke="{color or T["divider"]}" stroke-width="{sw}"{d}/>')
        self._grow(max(y1, y2))

    def polyline(self, pts, color=None, sw=2, dash=False):
        d = ' stroke-dasharray="6 4"' if dash else ''
        self.els.append('<polyline points="' + ' '.join(f'{_n(x)},{_n(y)}' for x, y in pts) +
                        f'" fill="none" stroke="{color or T["arrow"]}" stroke-width="{sw}"{d}/>')
        self._grow(max(y for _, y in pts))

    def polygon(self, pts, fill, opacity=None, stroke=None):
        o = f' fill-opacity="{opacity}"' if opacity is not None else ''
        s = f' stroke="{stroke}"' if stroke else ''
        self.els.append('<polygon points="' + ' '.join(f'{_n(x)},{_n(y)}' for x, y in pts) +
                        f'" fill="{fill}"{o}{s}/>')
        self._grow(max(y for _, y in pts))

    def arrow(self, pts, color=None, sw=None, dash=False, label=None, head=True):
        """Orthogonal polyline with a hand-drawn triangle head (markers are not reliable on the board)."""
        color = color or T['arrow']
        sw = sw or T['stroke']['arrow']
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        hl, hw = 10, 6
        body = list(pts)
        if head:
            # stop the line at the arrow base so the stroke does not poke through the tip
            if x2 != x1:
                sgn = 1 if x2 > x1 else -1
                body[-1] = (x2 - sgn * hl, y2)
                tri = [(x2 - sgn * hl, y2 - hw), (x2, y2), (x2 - sgn * hl, y2 + hw)]
            else:
                sgn = 1 if y2 > y1 else -1
                body[-1] = (x2, y2 - sgn * hl)
                tri = [(x2 - hw, y2 - sgn * hl), (x2, y2), (x2 + hw, y2 - sgn * hl)]
        self.polyline(body, color, sw, dash)
        if head:
            self.polygon(tri, color)
        if label:
            (ax, ay), (bx, by) = pts[0], pts[1]
            if ay == by:
                self.text((ax + bx) / 2, ay - 9, label, T['type']['tiny'], T['sub'], anchor='middle')
            else:
                self.text(ax + 10, (ay + by) / 2 + 4, label, T['type']['tiny'], T['sub'])

    def pill(self, x, y, s, tone='base', size=None, anchor='start', role='pill'):
        """Rounded tag: light fill, family border, family ink. Returns (width, height)."""
        size = size or T['type']['tiny']
        f = self.use(tone)
        w, h = measure(s, size) + 18, size + 12
        if anchor == 'end':
            x -= w
        elif anchor == 'middle':
            x -= w / 2
        r = f' data-role="{role}"' if role else ''
        self.rect(x, y, w, h, f['bg'], f['line'], rx=h / 2, role=role)
        self.text(x + w / 2, y + h / 2 + size * 0.35, s, size, f['ink'], anchor='middle', role=role)
        return w, h

    def badge(self, cx, cy, s, tone='base', r=13):
        f = self.use(tone)
        self.circle(cx, cy, r, f['bg'], f['main'], T['stroke']['emph'])
        self.text(cx, cy + 4.5, s, T['type']['small'], f['ink'], bold=True, anchor='middle')

    def svg(self, height):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {_n(height)}" '
                f'width="{self.w}" height="{_n(height)}">\n' + '\n'.join(self.els) + '\n</svg>\n')
