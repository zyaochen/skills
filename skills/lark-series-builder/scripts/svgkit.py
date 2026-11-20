"""House-style SVG figures that lay themselves out, plus the layout checker every figure must pass.

Components return the y of their bottom edge, so a figure is written top-down without hand-tuned coordinates,
and the canvas height fits the content when h is omitted:

    import sys; sys.path.insert(0, '<skill>/scripts')
    from svgkit import Board
    b = Board('一句判断作主标题', '副标题说明怎么读', src='来源：论文名 表 2；本篇 sim_x.py')
    y = b.stack(40, 150, 1120, [('计算', 62, 'blue'), ('等 HBM', 21, 'orange'), ('等主机', 9, 'gray')], unit=' ms')
    y = b.flow(40, y + 40, [('定天花板', 'Roofline 算出下限'), ('测实际', 'nsys 时间线'), ('复测', '看瓶颈转去哪')])
    b.note(y + 28, '结论一句话：哪项等待被消掉，剩下什么', fam='blue')
    b.save('figs/name.svg')            # writes the file and prints layout issues (fix until it prints OK)

Components: card, panel (legacy signature), note, flow, stack, bars, groups, lanes, table, legend, tag, badge,
plus primitives text, para, rect, line, arrow, circle and the layout helper cols().
check_svg(svg_text) is the checker used by svgcheck.py and lint_doc.py ('E ...' = must fix, 'W ...' = look).
Style values come from config `board` (assets/series.default.json, overridable per series).
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from html import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import load  # noqa: E402

BOARD = load(required=False)['board']
FAM = BOARD['families']
INK, SUB, LINE, BG = BOARD['ink'], BOARD['sub'], BOARD['line'], BOARD['bg']
ARROW, TRACK, CARD = BOARD['arrow'], BOARD['track'], BOARD['card']
NO_LINE_START = set('，。；：、）》」』！？%')


def width_of(s, size):
    """Estimated rendered width: CJK and full-width 1em, everything else 0.58em."""
    return sum(1.0 if ord(c) > 0x2e80 else 0.58 for c in s) * size


def wrap(s, size, maxw):
    """Greedy line wrap by estimated width; CJK breaks anywhere, Latin words stay whole."""
    tokens = re.findall(r'[A-Za-z0-9_.%+\-/×^·]+|\s+|.', s)
    lines, cur = [], ''
    for t in tokens:
        if cur and width_of(cur + t, size) > maxw and not t.isspace():
            if t[0] in NO_LINE_START:
                cur += t
                continue
            lines.append(cur.rstrip())
            cur = t.lstrip()
        else:
            cur += t
    if cur.strip():
        lines.append(cur.rstrip())
    # no orphan: a last line of one CJK character pulls one more character down from the line above
    if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) > 3 and ord(lines[-2][-1]) > 0x2e80:
        lines[-2], lines[-1] = lines[-2][:-1], lines[-2][-1] + lines[-1]
    return lines or ['']


def _t(s):
    # the doc layer turns &lt; back into '<' and truncates the SVG, so comparison signs become full-width
    return escape(str(s).replace('<', '＜').replace('>', '＞'), quote=False)


class Board:
    def __init__(self, title, sub='', src='', h=None, w=None):
        self.w = w or BOARD['width']
        self.h = h
        self.title, self.sub, self.src = title, sub, src
        self.o = []
        self.bottom = BOARD['content_top']

    # ---------- primitives ----------
    def _low(self, y):
        self.bottom = max(self.bottom, y)

    def text(self, x, y, s, size=14, color=INK, bold=False, anchor='start'):
        b = ' font-weight="bold"' if bold else ''
        a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
        self.o.append(f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" fill="{color}"{b}{a}>{_t(s)}</text>')
        self._low(y + size * 0.3)

    def para(self, x, y, s, w, size=14, color=SUB, bold=False):
        """Wrapped paragraph; y is the first baseline. Returns the bottom y."""
        lines = wrap(s, size, w)
        for i, ln in enumerate(lines):
            self.text(x, y + i * (size + 9), ln, size, color, bold)
        return y + (len(lines) - 1) * (size + 9) + size * 0.3

    def rect(self, x, y, w, h, fill=CARD, stroke=LINE, rx=12, sw=1, dash=False):
        d = ' stroke-dasharray="6 4"' if dash else ''
        self.o.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="{rx}" '
                      f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
        self._low(y + h)

    def line(self, x1, y1, x2, y2, color=LINE, sw=1, dash=False):
        d = ' stroke-dasharray="6 4"' if dash else ''
        self.o.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{color}" stroke-width="{sw}"{d}/>')

    def circle(self, cx, cy, r, fill, stroke):
        self.o.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')

    def arrow(self, pts, color=ARROW, sw=2, label='', head=True):
        """Orthogonal polyline with a hand-drawn triangle head (no <marker>)."""
        self.o.append('<polyline points="' + ' '.join(f'{x:.0f},{y:.0f}' for x, y in pts) +
                      f'" fill="none" stroke="{color}" stroke-width="{sw}"/>')
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        if head:
            if x2 > x1:
                tri = [(x2 - 10, y2 - 6), (x2, y2), (x2 - 10, y2 + 6)]
            elif x2 < x1:
                tri = [(x2 + 10, y2 - 6), (x2, y2), (x2 + 10, y2 + 6)]
            elif y2 > y1:
                tri = [(x2 - 6, y2 - 10), (x2, y2), (x2 + 6, y2 - 10)]
            else:
                tri = [(x2 - 6, y2 + 10), (x2, y2), (x2 + 6, y2 + 10)]
            self.o.append('<polygon points="' + ' '.join(f'{a:.0f},{b:.0f}' for a, b in tri) + f'" fill="{color}"/>')
        if label:
            mx, my = (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2
            self.text(mx, my - 8, label, 12, SUB, anchor='middle')

    def cols(self, n, x0=40, x1=None, gap=24):
        """Split [x0, x1] into n equal columns: [(x, w), ...]."""
        x1 = x1 or self.w - 40
        w = (x1 - x0 - gap * (n - 1)) / n
        return [(x0 + i * (w + gap), w) for i in range(n)]

    # ---------- components ----------
    def badge(self, cx, cy, n, fam='blue', r=13):
        c = FAM[fam]
        self.circle(cx, cy, r, c['bg'], c['line'])
        self.text(cx, cy + 5, str(n), 13, c['ink'], True, 'middle')

    def tag(self, x, y, s, fam='blue', size=13):
        """Pill label; returns its width."""
        c = FAM[fam]
        w = width_of(s, size) + 20
        self.rect(x, y, w, size + 12, c['bg'], c['line'], rx=(size + 12) / 2)
        self.text(x + w / 2, y + size + 3, s, size, c['ink'], False, 'middle')
        return w

    def _card_layout(self, w, head, lines, size, badge):
        hs = 18 if size >= 14 else 16
        inner = w - 32 - (32 if badge is not None else 0)
        hl = wrap(head, hs, inner) if head else []
        bl = [ln for item in lines for ln in wrap(item, size, w - 32)]
        y = 16 + hs * 0.85 if hl else 16 + size * 0.85
        heads = []
        for _ in hl:
            heads.append(y)
            y += hs + 8
        if hl:
            y += 4
        else:
            y = 16 + size * 0.85
        body = []
        for _ in bl:
            body.append(y)
            y += size + 9
        last = (body[-1] + size * 0.3) if body else (heads[-1] + hs * 0.3 if heads else 16)
        return hs, hl, bl, heads, body, last + 16

    def card(self, x, y, w, head='', lines=(), fam='blue', size=14, h=None, white=False, center=False, badge=None):
        """Panel with optional numbered badge, bold head and wrapped body lines; height fits the text when h is None.
        Returns the bottom y."""
        c = FAM[fam]
        hs, hl, bl, heads, body, auto = self._card_layout(w, head, lines, size, badge)
        h = h or auto
        self.rect(x, y, w, h, CARD if white else c['bg'], c['line'])
        tx = x + w / 2 if center else x + 16
        anchor = 'middle' if center else 'start'
        if badge is not None:
            self.badge(x + 29, y + heads[0] - 6 if heads else y + 26, badge, fam)
        for ln, by in zip(hl, heads):
            self.text(tx + (16 if badge is not None and center else 32 if badge is not None else 0), y + by, ln, hs, INK, True, anchor)
        for ln, by in zip(bl, body):
            self.text(tx, y + by, ln, size, SUB if head else INK, False, anchor)
        return y + h

    def panel(self, x, y, w, h, fam='blue', head='', lines=(), size=14, center=False, white=False):
        """Legacy svg_kit signature (fixed height). Prefer card()."""
        self.card(x, y, w, head, lines, fam, size, h, white, center)
        return self

    def note(self, y, s, fam='blue', head='', x=40, w=None, size=15):
        """Full-width takeaway banner (the one sentence the reader should leave with). Returns the bottom y."""
        w = w or self.w - x - 40
        return self.card(x, y, w, head, [s], fam, size)

    def legend(self, x, y, items, size=13):
        """items = [(label, fam), ...] drawn left to right; returns the right edge x."""
        for lab, fam in items:
            self.rect(x, y - 11, 14, 14, FAM[fam]['main'], FAM[fam]['main'], rx=3)
            self.text(x + 20, y, lab, size, SUB)
            x += 20 + width_of(lab, size) + 24
        return x

    def flow(self, x, y, steps, w=None, fam='blue', gap=44, size=14, numbered=True, h=None):
        """Left-to-right process of equal boxes joined by arrows. steps = [(head, sub[, fam]), ...]. Returns bottom y."""
        w = w or self.w - 40 - x
        n = len(steps)
        bw = (w - gap * (n - 1)) / n
        lays = [self._card_layout(bw, s[0], [s[1]] if len(s) > 1 and s[1] else [], size, 1 if numbered else None)
                for s in steps]
        h = h or max(lay[-1] for lay in lays)
        for i, s in enumerate(steps):
            bx = x + i * (bw + gap)
            self.card(bx, y, bw, s[0], [s[1]] if len(s) > 1 and s[1] else [], s[2] if len(s) > 2 else fam,
                      size, h, badge=i + 1 if numbered else None)
            if i < n - 1:
                self.arrow([(bx + bw + 6, y + h / 2), (bx + bw + gap - 6, y + h / 2)])
        return y + h

    def stack(self, x, y, w, parts, h=40, unit='', title='', fmt='{:g}', pct=True):
        """One horizontal stacked bar (a time or cost ledger). parts = [(label, value, fam), ...].
        Labels sit under their segment on up to three staggered rows. Returns bottom y."""
        if title:
            self.text(x, y - 12, title, 15, INK, True)
        total = sum(v for _, v, _ in parts) or 1
        cx, centers = x, []
        for lab, v, fam in parts:
            sw = w * v / total
            self.rect(cx, y, max(sw, 2), h, FAM[fam]['main'], CARD, rx=4, sw=2)
            centers.append((cx + sw / 2, lab, v, fam))
            cx += sw
        rows_end = [[], [], []]
        bottom = y + h
        for mid, lab, v, fam in centers:
            t1 = f'{lab} {fmt.format(v)}{unit}'
            t2 = f'{100 * v / total:.0f}%' if pct else ''
            lw = max(width_of(t1, 13), width_of(t2, 12))
            left = min(max(mid - lw / 2, x), x + w - lw)
            r = next((i for i, row in enumerate(rows_end) if all(left > e + 14 or left + lw < s - 14 for s, e in row)), 2)
            rows_end[r].append((left, left + lw))
            ly = y + h + 26 + r * 44
            self.line(mid, y + h + 2, mid, ly - 14, FAM[fam]['line'], 1)
            self.text(left, ly, t1, 13, FAM[fam]['ink'] if fam != 'gray' else SUB)
            if t2:
                self.text(left, ly + 18, t2, 12, SUB)
            bottom = max(bottom, ly + 22)
        return bottom

    def bars(self, x, y, rows, w=700, bh=26, gap=16, label_w=220, unit='', fmt='{:g}', ref=None, max_value=None):
        """Horizontal bars normalised to the max (or max_value). rows = [(label, value, fam[, note]), ...].
        ref = (value, text) draws a dashed reference line such as a hardware ceiling. Returns bottom y."""
        vals = [f'{fmt.format(r[1])}{unit}' + (f'  {r[3]}' if len(r) > 3 else '') for r in rows]
        room = self.w - 40 - x - label_w - max(width_of(v, 13) for v in vals) - 12
        w = min(w, room)
        mx = max_value or max([r[1] for r in rows] + ([ref[0]] if ref else [])) or 1
        for i, r in enumerate(rows):
            yy = y + i * (bh + gap)
            self.text(x + label_w - 12, yy + bh * 0.7, r[0], 14, INK, anchor='end')
            self.rect(x + label_w, yy, w, bh, TRACK, TRACK, rx=4)
            bw = max(4, w * r[1] / mx)
            self.rect(x + label_w, yy, bw, bh, FAM[r[2]]['main'], FAM[r[2]]['main'], rx=4)
            self.text(x + label_w + bw + 8, yy + bh * 0.7, vals[i], 13, SUB)
        end = y + len(rows) * (bh + gap) - gap
        if ref:
            rx = x + label_w + w * ref[0] / mx
            self.line(rx, y - 8, rx, end + 8, FAM['red']['line'], 1.5, dash=True)
            self.text(rx, y - 14, ref[1], 12, FAM['red']['ink'], anchor='middle')
        return end + 8 if ref else end

    def lanes(self, x, y, lanes, t_max, w=None, label_w=150, lane_h=34, gap=14, unit='', ticks=5):
        """Timeline with one lane per stream/device; shows overlap, bubbles and serialisation.
        lanes = [(label, [(t0, t1, fam, text), ...]), ...]. Span text is dropped when it does not fit. Returns bottom y."""
        w = w or self.w - 40 - x
        ax0, aw = x + label_w, w - label_w
        sx = aw / t_max
        for i, (lab, spans) in enumerate(lanes):
            ly = y + i * (lane_h + gap)
            self.text(ax0 - 12, ly + lane_h * 0.65, lab, 14, INK, anchor='end')
            self.rect(ax0, ly, aw, lane_h, TRACK, TRACK, rx=4)
            for t0, t1, fam, txt in spans:
                c = FAM[fam]
                self.rect(ax0 + t0 * sx, ly + 3, max((t1 - t0) * sx, 3), lane_h - 6, c['bg'], c['line'], rx=4)
                if txt and width_of(txt, 12) + 10 < (t1 - t0) * sx:
                    self.text(ax0 + (t0 + t1) / 2 * sx, ly + lane_h * 0.65, txt, 12, c['ink'], anchor='middle')
        end = y + len(lanes) * (lane_h + gap) - gap
        if ticks:
            for k in range(ticks + 1):
                tx = ax0 + aw * k / ticks
                self.line(tx, y - 4, tx, end + 4, LINE, 1, dash=True)
                self.text(tx, end + 22, f'{t_max * k / ticks:g}{unit}', 12, SUB, anchor='middle')
            end += 26
        return end

    def groups(self, x, y, groups, series, w=None, label_w=180, bh=20, gap=6, group_gap=22, unit='', fmt='{:g}'):
        """Grouped bars: one row block per group, one bar per series, a legend on top, one shared scale.
        groups = [(label, [v_series1, v_series2, ...]), ...]; series = [(name, fam), ...]. Returns bottom y.
        Use this (never several bars() calls at shifted x) for workload × variant comparisons."""
        w = w or self.w - 40 - x
        self.legend(x + label_w, y, series)
        y += 24
        vals = [v for _, vs in groups for v in vs]
        room = w - label_w - max(width_of(f'{fmt.format(v)}{unit}', 13) for v in vals) - 12
        mx = max(vals) or 1
        for lab, vs in groups:
            block = len(vs) * (bh + gap) - gap
            self.text(x + label_w - 12, y + block / 2 + 5, lab, 14, INK, True, 'end')
            for k, (v, (_, fam)) in enumerate(zip(vs, series)):
                yy = y + k * (bh + gap)
                bw = max(3, room * v / mx)
                self.rect(x + label_w, yy, room, bh, TRACK, TRACK, rx=4)
                self.rect(x + label_w, yy, bw, bh, FAM[fam]['main'], FAM[fam]['main'], rx=4)
                self.text(x + label_w + bw + 8, yy + bh * 0.75, f'{fmt.format(v)}{unit}', 13, SUB)
            y += block + group_gap
        return y - group_gap

    def table(self, x, y, cols, rows, head_fam='blue', size=14, hl=None, bold_first=True, fit=True):
        """Grid table drawn in SVG (for comparison matrices inside a figure). cols = [(title, width), ...];
        rows = [[cell, ...], ...]; hl = {row_index: fam} tints whole rows. Cells wrap.
        fit=True stretches the columns proportionally to the canvas width. Returns bottom y."""
        hl = hl or {}
        avail = self.w - 40 - x
        total = sum(cw for _, cw in cols)
        if fit and total < avail:
            cols = [(t, cw * avail / total) for t, cw in cols]
        pitch, pad = size + 8, 12
        tw = sum(cw for _, cw in cols)
        hh = size + 2 * pad + 4
        self.rect(x, y, tw, hh, FAM[head_fam]['bg'], FAM[head_fam]['line'], rx=0)
        cx = x
        for title, cw in cols:
            self.text(cx + pad, y + pad + size, title, size, INK, True)
            cx += cw
        yy = y + hh
        for i, row in enumerate(rows):
            cells = [wrap(str(c), size, cw - 2 * pad) for c, (_, cw) in zip(row, cols)]
            rh = max(len(c) for c in cells) * pitch + 2 * pad - 8
            fill = FAM[hl[i]]['bg2'] if i in hl else (CARD if i % 2 == 0 else '#F5F6F7')
            self.rect(x, yy, tw, rh, fill, LINE, rx=0)
            cx = x
            for j, (lines, (_, cw)) in enumerate(zip(cells, cols)):
                for k, ln in enumerate(lines):
                    self.text(cx + pad, yy + pad + size * 0.85 + k * pitch, ln, size, INK, bold_first and j == 0)
                cx += cw
            yy += rh
        return yy

    # ---------- output ----------
    def svg(self):
        gap = BOARD['content_bottom_gap']
        h = self.h or max(BOARD['height'][0], int(math.ceil((self.bottom + gap + 6) / 10.0) * 10))
        t, st, src = BOARD['title'], BOARD['subtitle'], BOARD['source']
        head = [f'<rect x="0" y="0" width="{self.w}" height="{h}" rx="{BOARD["radius"]}" fill="{BG}" stroke="{LINE}"/>',
                f'<text x="{t["x"]}" y="{t["y"]}" font-size="{t["size"]}" fill="{INK}" font-weight="bold">{_t(self.title)}</text>']
        if self.sub:
            head.append(f'<text x="{t["x"]}" y="{st["y"]}" font-size="{st["size"]}" fill="{SUB}">{_t(self.sub)}</text>')
        tail = []
        if self.src:
            pre = src['prefix']
            s = self.src if self.src.startswith(pre.rstrip('：:')) else pre + self.src
            tail.append(f'<text x="{t["x"]}" y="{h - src["bottom"]}" font-size="{src["size"]}" fill="{SUB}">{_t(s)}</text>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {h}" width="{self.w}" height="{h}">\n'
                + '\n'.join(head + self.o + tail) + '\n</svg>\n')

    def check(self):
        return check_svg(self.svg())

    def save(self, path, quiet=False):
        """Write the SVG and print its layout issues; returns the issue list (empty = clean)."""
        s = self.svg()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(s)
        issues = check_svg(s)
        if not quiet:
            name = os.path.basename(path)
            print(f'{name}: OK' if not issues else f'{name}: {len(issues)} issue(s)\n  ' + '\n  '.join(issues))
        return issues


FORBIDDEN = re.compile(r'<(filter|radialGradient|pattern|clipPath|mask|image|script|marker|foreignObject)\b')


def _num(v, d=0.0):
    try:
        return float(re.sub(r'[^0-9.\-]', '', v)) if v not in (None, '') else d
    except ValueError:
        return d


def _hex(c):
    c = c.strip().upper()
    m = re.match(r'RGBA?\((\d+),\s*(\d+),\s*(\d+)', c)
    if m:
        return '#%02X%02X%02X' % tuple(int(v) for v in m.groups())
    if re.match(r'#[0-9A-F]{3}$', c):
        return '#' + ''.join(ch * 2 for ch in c[1:])
    return c


def _palette(board):
    fam_of = {}
    for name, fam in board['families'].items():
        for v in fam.values():
            fam_of[v.upper()] = None if name == 'gray' else name
    for v in board['neutral'] + [board[k] for k in ('bg', 'line', 'ink', 'sub', 'arrow', 'track', 'card')]:
        fam_of[v.upper()] = None
    for v in ('NONE', 'WHITE', 'TRANSPARENT', 'CURRENTCOLOR'):
        fam_of[v] = None
    return fam_of


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def check_svg(svg, board=None):
    """Layout and house-style check. Returns ['E …' must fix, 'W …' look and fix unless a clear false positive]."""
    B = board or BOARD
    out = []
    m = FORBIDDEN.search(svg)
    if m:
        out.append(f'E forbidden element <{m.group(1)}>')
    try:
        root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', svg.strip()))
    except ET.ParseError as e:
        return out + [f'E not well-formed: {e}']
    if root.tag.split('}')[-1] == 'whiteboard':
        root = next((c for c in root if c.tag.split('}')[-1] == 'svg'), root)
    vb = (root.get('viewBox') or '').split()
    if len(vb) != 4:
        out.append('E missing viewBox')
        W, H = float(B['width']), 600.0
    else:
        W, H = float(vb[2]), float(vb[3])
    pal, fams = _palette(B), set()
    texts, rects = [], []

    def walk(el, dx, dy, inherited_size, rotated):
        tag = el.tag.split('}')[-1]
        tr = el.get('transform') or ''
        m = re.search(r'translate\(\s*([-\d.]+)[\s,]*([-\d.]*)', tr)
        if m:
            dx, dy = dx + float(m.group(1)), dy + float(m.group(2) or 0)
        rotated = rotated or bool(re.search(r'rotate|matrix|scale|skew', tr))
        size = _num(el.get('font-size'), inherited_size) if el.get('font-size') else inherited_size
        colors = [el.get(k) for k in ('fill', 'stroke', 'stop-color') if el.get(k)]
        colors += re.findall(r'(?:fill|stroke|stop-color)\s*:\s*([^;]+)', el.get('style') or '')
        for c in colors:
            hx = _hex(c)
            if hx.startswith('URL('):
                continue
            if hx not in pal:
                out.append(f'W off-palette colour {c}')
            elif pal[hx]:
                fams.add(pal[hx])
        if tag == 'text' and not rotated:
            s = ''.join(el.itertext()).strip()
            if s:
                x, y = _num(el.get('x')) + dx, _num(el.get('y')) + dy
                w = width_of(s, size)
                a = el.get('text-anchor', 'start')
                x0 = x - w / 2 if a == 'middle' else x - w if a == 'end' else x
                texts.append((x0, y - size * 0.85, x0 + w, y + size * 0.2, s, size))
        elif tag == 'rect' and not rotated:
            x, y, w, h = (_num(el.get(k)) for k in ('x', 'y', 'width', 'height'))
            x, y = x + dx, y + dy
            if w >= 60 and h >= 30 and not (x <= 1 and y <= 1 and w >= W - 2):
                rects.append((x, y, x + w, y + h))
        for ch in el:
            walk(ch, dx, dy, size, rotated)

    walk(root, 0.0, 0.0, 14.0, False)
    if len(fams) > B['max_families']:
        out.append(f'W {len(fams)} colour families {sorted(fams)} (max {B["max_families"]}: lead blue, contrast orange, good green, risk red)')
    top = [t for t in texts if t[3] < 80]
    title = max(top, key=lambda t: t[5]) if top else None
    src = [t for t in texts if t[4].startswith(B['source']['prefix'].rstrip('：:'))]
    if not title:
        out.append('E missing title (one-sentence judgment, 28px bold, top left)')
    else:
        if title[5] < 24:
            out.append(f'W title font {title[5]:g}px (house style {B["title"]["size"]}px bold)')
        if title[2] > W - 40:
            out.append(f'W title too long for one line ({title[2] - title[0]:.0f}px): shorten the judgment')
    if not src:
        out.append('E missing 来源： line at the bottom')
    for t in texts:
        if t[0] < 0 or t[2] > W + 2 or t[1] < 0 or t[3] > H + 2:
            out.append(f'E off canvas: {t[4][:30]!r}')
        if t[5] < B['min_font']:
            out.append(f'W font {t[5]:g}px below {B["min_font"]}: {t[4][:20]!r}')
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if small > 0 and _inter(a, b) / small > 0.25:
                out.append(f'W text overlap: {a[4][:20]!r} / {b[4][:20]!r}')
    for t in texts:
        area = (t[2] - t[0]) * (t[3] - t[1])
        for r in rects:
            if 0.15 * area < _inter(t, r) < 0.85 * area:
                out.append(f'W spills out of box: {t[4][:30]!r}')
                break
    top = B['content_top'] - 12
    for r in rects:
        if r[1] < top:
            out.append(f'W box inside the title band (y={r[1]:.0f}): start content at y≥{B["content_top"]}')
        if r[3] > H - 36:
            out.append(f'W box reaches the source band (bottom={r[3]:.0f}, canvas {H:.0f}): enlarge the canvas')
    body = [t for t in texts if t not in src and t is not title and t[1] > 100]
    for t in body:
        if t[3] > H - 38:
            out.append(f'W text in the source band: {t[4][:30]!r}')
    for t in body:
        if t[0] < 30:
            out.append(f'W text inside the 40px side margin (x={t[0]:.0f}): {t[4][:20]!r}')
    low = max([t[3] for t in body] + [r[3] for r in rects] + [0])
    if low and low < H - 130:
        lvl = 'E' if low < H - 220 else 'W'
        out.append(f'{lvl} empty band at the bottom: content ends at {low:.0f}, canvas {H:.0f} '
                   f'(never a false positive: omit h so the canvas fits, or add the missing content)')
    right = max([t[2] for t in body] + [r[2] for r in rects] + [0])
    if body and right < 0.72 * W:
        out.append(f'W content uses only the left {right / W:.0%} of the canvas: widen columns/tables or rebalance '
                   f'(never a false positive)')
    if not (1140 <= W <= 1280 and 400 <= H <= 1100):
        out.append(f'W canvas {W:.0f}x{H:.0f} outside 1200 x 400-960')
    return sorted(set(out), key=lambda s: (s[0] != 'E', s))


def wb(svg):
    """Wrap an SVG string as a Lark whiteboard block."""
    return '<whiteboard type="svg">' + re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', svg).strip() + '</whiteboard>'

