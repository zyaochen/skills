"""Lint an SVG against the house style and whiteboard compatibility. Works on generated and hand-written SVG.

Each finding is (level, code, message). Level E blocks delivery; W must be looked at in the preview.
Codes: PARSE FORBID TRANSFORM LT PALETTE FAMILIES DARK TITLE TITLE-LABEL SOURCE SIZE FONT OVERLAP SPILL CANVAS MARGIN CROSS
       DENSITY COLOR-OVERUSE TONE-AS-CLASSIFIER PRIMARY-DUPLICATE SIZE-WIDTH
"""
import colorsys
import re
import xml.etree.ElementTree as ET

from .canvas import T, measure

NS = '{http://www.w3.org/2000/svg}'
HEX = re.compile(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b')
RGB = re.compile(r'rgba?\(([^)]*)\)')
COLOR_ATTRS = ('fill', 'stroke', 'stop-color', 'color')


def _num(v, d=0.0):
    try:
        return float(re.sub(r'[^0-9.\-]', '', v)) if v not in (None, '') else d
    except ValueError:
        return d


def _norm(c):
    c = c.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', c):
        c = '#' + ''.join(ch * 2 for ch in c[1:])
    m = RGB.fullmatch(c)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')][:3]
        try:
            c = '#' + ''.join(f'{int(float(p)):02x}' for p in parts)
        except ValueError:
            pass
    return c


def palette():
    cols = {c.lower() for f in T['families'].values() for c in f.values()}
    return cols | {c.lower() for c in T['neutral']} | {'none', 'transparent', 'currentcolor'}


def family_of(c):
    for name, f in T['families'].items():
        if c in {v.lower() for v in f.values()}:
            return name
    return None


def lightness(c):
    if not re.fullmatch(r'#[0-9a-f]{6}', c):
        return 0.5
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[1]


def _style_colors(el):
    out = []
    for k in COLOR_ATTRS:
        if el.get(k):
            out.append(el.get(k))
    for decl in (el.get('style') or '').split(';'):
        if ':' in decl:
            k, v = decl.split(':', 1)
            if k.strip() in COLOR_ATTRS:
                out.append(v)
    return [_norm(c) for c in out if not c.strip().startswith('url(')]


def _text_box(el):
    s = ''.join(el.itertext()).strip()
    size = _num(el.get('font-size'), 14)
    x, y = _num(el.get('x')), _num(el.get('y'))
    w = measure(s, size, el.get('font-weight') == 'bold')
    a = el.get('text-anchor', 'start')
    x0 = x - w / 2 if a == 'middle' else x - w if a == 'end' else x
    return (x0, y - size * 0.85, x0 + w, y + size * 0.22, s, size)


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _seg_hits(p, q, box):
    """Does segment p→q pass through box? Sampled every ~3px, good enough for any straight segment."""
    (x1, y1), (x2, y2) = p, q
    steps = max(8, int((abs(x2 - x1) + abs(y2 - y1)) / 3))
    for i in range(steps + 1):
        t = i / steps
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        if box[0] < x < box[2] and box[1] < y < box[3]:
            return True
    return False


def lint(svg_text):
    out = []

    def add(level, code, msg):
        out.append((level, code, msg))

    for tag in T['forbidden_svg']:
        if re.search(r'<\s*' + tag + r'\b', svg_text):
            add('E', 'FORBID', f'<{tag}> is not supported by the whiteboard; remove it')
    if re.search(r'(skewX|skewY|matrix)\s*\(', svg_text):
        add('E', 'TRANSFORM', 'skew/matrix transforms are degraded on the board; use translate/rotate/scale')
    if '&lt;' in svg_text:
        add('E', 'LT', '"&lt;" in text is turned back into "<" by the doc layer and truncates the SVG; write "＜" or "小于"')
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as e:
        add('E', 'PARSE', f'not well-formed XML: {e}')
        return out
    if root.tag.replace(NS, '') != 'svg' or not root.get('viewBox'):
        add('E', 'PARSE', 'root must be <svg> with a viewBox')
        return out
    vb = [float(v) for v in root.get('viewBox').replace(',', ' ').split()]
    W, H = vb[2], vb[3]
    pal, fams = palette(), set()
    off, dark_fills, texts, rects, segs, margin_hits = set(), [], [], [], [], []
    covers = []  # (box, order) of opaque filled rects: they hide lines drawn before them
    for order, el in enumerate(root.iter()):
        tag = el.tag.replace(NS, '')
        for c in _style_colors(el):
            if c not in pal:
                off.add(c)
            f = family_of(c)
            if f and f != 'gray':
                fams.add(f)
        if tag == 'text':
            box = _text_box(el)
            if box[4]:
                texts.append((box, el))
        elif tag in ('line', 'polyline') and lightness(_norm(el.get('stroke') or '')) > 0.9:
            continue  # hairline gridlines/dividers may pass behind text
        elif tag == 'line':
            segs.append((((_num(el.get('x1')), _num(el.get('y1'))), (_num(el.get('x2')), _num(el.get('y2')))), order))
        elif tag == 'polyline':
            pts = [tuple(float(v) for v in p.split(',')) for p in (el.get('points') or '').split() if ',' in p]
            segs += [(sg, order) for sg in zip(pts, pts[1:])]
        elif tag == 'rect':
            x, y, w, h = (_num(el.get(k)) for k in ('x', 'y', 'width', 'height'))
            fill = (el.get('fill') or '').lower()
            if fill not in ('', 'none', 'transparent') and el.get('fill-opacity') in (None, '1'):
                covers.append(((x, y, x + w, y + h), order))
            if el.get('data-role') in ('track', 'bar'):
                continue
            frame = x <= 1 and y <= 1 and w >= W - 2
            margin = T['canvas']['pad'] / 2
            if not frame and w > 0 and (x < margin or x + w > W - margin or y + h > H - margin):
                margin_hits.append(f'{w:g}x{h:g} at ({x:g},{y:g})')
            if w >= 40 and h >= 24 and not frame:
                rects.append((x, y, x + w, y + h))
                fill = _norm(el.get('fill') or '')
                if fill.startswith('#') and lightness(fill) < 0.55:
                    dark_fills.append((x, y, x + w, y + h))
    if margin_hits:
        add('E', 'MARGIN', f'{len(margin_hits)} shape(s) reach into the frame margin, e.g. {margin_hits[0]}; '
                           f'keep content {T["canvas"]["pad"]}px inside the frame')
    if off:
        add('E', 'PALETTE', f'{len(off)} color(s) outside theme palette: {", ".join(sorted(off)[:6])}. '
                            'Use theme families/neutral only')
    if len(fams) > T['max_families']:
        add('E', 'FAMILIES', f'{len(fams)} color families {sorted(fams)}; max {T["max_families"]}. '
                             'Background items go gray (tone "base")')
    for (box, el) in texts:
        color = _norm(el.get('fill') or T['ink'])
        if color.startswith('#') and lightness(color) > 0.85:
            add('E', 'DARK', f'light text {color} on {box[4][:16]!r}: the board may render it black. '
                             'Use light fill + dark text')
    if dark_fills:
        for (box, _) in texts:
            if any(_inter(box, r) > 0 for r in dark_fills):
                add('E', 'DARK', f'text {box[4][:16]!r} sits on a dark fill; use the family bg + ink instead')
                break
    # title: the biggest text near the top, bold, inside the title size range
    tops = [(box, el) for box, el in texts if box[3] < 110]
    title = max(tops, key=lambda t: t[0][5]) if tops else None
    if not title or not T['title']['min'] <= title[0][5] <= T['title']['max'] or title[1].get('font-weight') != 'bold':
        add('E', 'TITLE', f'need a bold title {T["title"]["min"]}-{T["title"]["max"]}px at the top-left (y≈{T["title"]["y"]})')
    else:
        s = title[0][4]
        if len(s) <= 8 or any(s.endswith(suf) for suf in T['title_label_suffixes']):
            add('W', 'TITLE-LABEL', f'title {s!r} reads like a label; state the takeaway instead '
                                    '(e.g. "排队占了 60% 的时间" not "请求流程图")')
    prefix = T['source']['prefix'].rstrip('：:')
    if not any(b[4].startswith(prefix) and b[3] > H - 60 for b, _ in texts):
        add('E', 'SOURCE', f'no "{T["source"]["prefix"]}…" line at the bottom; cite where the content came from')
    lo, hi = T['canvas']['lint_height']
    house_w = T['canvas']['width']
    allowed_widths = {house_w} | set(T['canvas'].get('aspect_widths', {}).values())
    if not any(abs(W - w) <= 1 for w in allowed_widths):
        wrange = T['canvas'].get('size_width_range')
        in_range = wrange and wrange[0] <= W <= wrange[1]
        if in_range:
            add('W', 'SIZE', f'width {W:g}; house widths are {sorted(allowed_widths)} '
                             f'(within allowed range {wrange[0]}-{wrange[1]})')
        else:
            add('E', 'SIZE-WIDTH', f'width {W:g} is neither a house width {sorted(allowed_widths)} '
                                   f'nor in size_width_range {wrange}; pick one of those (or use spec.aspect)')
    if not lo <= H <= hi:
        add('W', 'SIZE', f'height {H:g} outside {lo}-{hi}; fine for dense data, check the preview')
    small = sorted({b[5] for b, _ in texts if b[5] < T['type']['tiny']})
    if small:
        add('E', 'FONT', f'font sizes {small} below {T["type"]["tiny"]}px are unreadable in docs')
    boxes = [b for b, _ in texts]
    for b in boxes:
        if b[0] < 0 or b[2] > W + 2 or b[1] < 0 or b[3] > H + 2:
            add('E', 'CANVAS', f'text off canvas: {b[4][:24]!r}')
    for i, (a, ea) in enumerate(texts):
        if ea.get('data-role') in ('card-title', 'card-body'):
            continue  # wrapped card content can sit against its own id badge; that's by design
        for b, _ in texts[i + 1:]:
            ov = _inter(a, b)
            small_area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if small_area > 0 and ov / small_area > 0.15:
                add('E', 'OVERLAP', f'text overlap: {a[4][:18]!r} / {b[4][:18]!r}')
    for b, el in texts:
        if el.get('data-role') in ('card-title', 'card-body'):
            continue  # card content wraps by design; id-badge overlaps are benign
        area = (b[2] - b[0]) * (b[3] - b[1])
        for r in rects:
            ov = _inter(b, r)
            if 0.1 * area < ov < 0.9 * area:
                add('E', 'SPILL', f'text spills out of its box: {b[4][:24]!r}')
                break
    for b in boxes:
        inner = (b[0] + 2, b[1] + 2, b[2] - 2, b[3] - 2)
        hidden_before = max([o for r, o in covers if r[0] <= b[0] and r[1] <= b[1] and r[2] >= b[2] and r[3] >= b[3]
                             and not (r[0] <= 1 and r[1] <= 1)] or [-1])
        if any(_seg_hits(p, q, inner) for (p, q), o in segs if o > hidden_before):
            add('E', 'CROSS', f'a line or arrow runs through text {b[4][:24]!r}; reroute it or move the text')
    if len(boxes) > 90:
        add('W', 'DENSITY', f'{len(boxes)} text items; one figure should carry one point. Consider splitting')
    # G5.a — E_COLOR_OVERUSE: count elements painted with a *saturated* family color
    # (ink / main / line — the loud ones). bg / bg2 are quiet washes and don't count.
    # bars/tracks are data, not decoration — they don't count toward the budget either.
    # The budget is generous; we want to stop "every element is its own color" (5+ loud marks),
    # not engine-driven pills/dividers that share one tone across a row of cards.
    def _loud(el):
        loud_fams = set()
        for c in _style_colors(el):
            f = family_of(c)
            if not f or f == 'gray':
                continue
            fam = T['families'][f]
            cl = c.lower()
            if cl in (fam['bg'].lower(), fam['bg2'].lower()):
                continue  # quiet wash
            loud_fams.add(f)
        return loud_fams
    n_loud = 0
    fam_use = {}
    for el in root.iter():
        if el.get('data-role') in ('track', 'bar', 'series-point', 'value-chip', 'side-kv', 'point-icon',
                                    'banner-chip', 'card-id', 'pill', 'card-title', 'card-body', 'layer-chip'):
            continue
        loud = _loud(el)
        if not loud:
            continue
        n_loud += 1
        for f in loud:
            fam_use[f] = fam_use.get(f, 0) + 1
    if n_loud > 25:
        add('E', 'COLOR-OVERUSE', f'{n_loud} elements with saturated family color; max 25. '
                                  'Quiet panels (bg/bg2) are fine — saturated ink/main/line should be rare. '
                                  'Set secondary items to tone "base"')
    # G5.b — E_TONE_AS_CLASSIFIER: one family painting ≥15 *loud* elements means tone is doing classifier work,
    # not semaphore work. Compare cards sharing one tone across their title+pill+divider legitimately hit ~12;
    # anything above that is the same color discriminating many peers.
    for f, n in sorted(fam_use.items()):
        if n >= 15:
            add('E', 'TONE-AS-CLASSIFIER', f"family '{f}' paints {n} saturated elements; tone is a semaphore, "
                                           f"not a classifier. Discriminate cards with ①②③ / ✗✓ in titles instead")
    # G5.c — E_PRIMARY_DUPLICATE: compare emits data-role="colorline" only on highlight cards; >1 means several primaries.
    n_primary = sum(1 for el in root.iter() if el.get('data-role') == 'colorline')
    if n_primary > 1:
        add('E', 'PRIMARY-DUPLICATE', f'{n_primary} colorline primary markers; only the main card may carry one. '
                                      'Pick one highlight / primary')
    return out


def summarize(findings):
    errs = [f for f in findings if f[0] == 'E']
    return {'ok': not errs, 'errors': len(errs), 'warnings': len(findings) - len(errs),
            'findings': [{'level': lv, 'code': c, 'message': m} for lv, c, m in findings]}
