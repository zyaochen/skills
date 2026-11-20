"""roofline: kernels placed against a machine's compute and bandwidth ceilings, on log-log axes.

The roofs are computed from peak and bandwidth, never drawn by hand, so the ridge sits exactly at peak / bandwidth.
A point above every roof is physically impossible and is rejected: it is almost always a wrong number or unit.
"""
import math

from ..canvas import T, measure, pairs
from ._common import LayoutError, need, need_list, num, opt_tone
from .line import _hits

DOC = {
    'summary': 'Kernels against compute and memory-bandwidth ceilings on log-log axes: bandwidth- vs compute-bound.',
    'fields': {
        'roofs': 'list (1-3) of {name, peak:number (y unit, e.g. TFLOPS), bandwidth:number (y unit per x unit, '
                 'e.g. TB/s when y is TFLOPS and x is FLOP/Byte), tone?, dashed?:bool, ridge?:str|false}. '
                 'The first roof is the reference; later ones are dashed by default. ridge labels the knee '
                 '(default "拐点 <peak/bandwidth>"; false hides it)',
        'points': 'optional list (0-12) of {label, x:number (intensity), y?:number (achieved; default: on the first '
                  'roof), tone?, emph?:bool}. Keep labels to a short kernel name',
        'x': 'optional {title?:str, min?:number, max?:number}; default title "算术强度（FLOP/Byte）"',
        'y': 'optional {title?:str, min?:number, max?:number}; default title "吞吐（TFLOPS）"',
        'regions': 'optional [left, right]: short labels under the sloped and the flat part, '
                   'e.g. ["带宽受限", "算力受限"]',
    },
    'example': {
        'type': 'roofline',
        'title': '除了大矩阵乘，常见算子都落在拐点 295 左边：它们等的是带宽，不是算力',
        'subtitle': 'H100 SXM BF16 稠密算力与 HBM3 带宽；实线是标称值，虚线是实测上限',
        'source': '来源：本篇 sim_roofline.py 输出（示意数据）',
        'roofs': [
            {'name': '标称 989 TFLOPS · 3.35 TB/s', 'peak': 989, 'bandwidth': 3.35},
            {'name': '实测 786 TFLOPS · 3.02 TB/s', 'peak': 786, 'bandwidth': 3.02, 'tone': 'base'},
        ],
        'points': [
            {'label': 'ReLU', 'x': 0.125, 'y': 0.36},
            {'label': 'LayerNorm', 'x': 1.0, 'y': 2.6},
            {'label': 'Decode GEMV', 'x': 2.0, 'y': 5.4},
            {'label': 'FlashAttention', 'x': 160, 'y': 380, 'tone': 'contrast'},
            {'label': 'GEMM 4096³', 'x': 1365, 'y': 720, 'tone': 'good', 'emph': True},
        ],
        'regions': ['带宽受限', '算力受限'],
    },
}

PLOT_H, MARK, HEAD_ROOM, MAX_DECADES, EDGE = 340, 5, 2.5, 8, 1.5
TOO_HIGH = 1.01  # rounding slack before a point counts as above the roof
NEAR = [(0, -12, 'middle'), (10, 4, 'start'), (-10, 4, 'end'), (0, 22, 'middle'), (8, -10, 'start'),
        (-8, -10, 'end'), (8, 20, 'start'), (-8, 20, 'end')]
SPOTS = NEAR + [(dx * 2.2, dy * 1.8, a) for dx, dy, a in NEAR]


def roof_at(r, x):
    return min(r['peak'], r['bandwidth'] * x)


def _pos(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _validate_axis(spec, key):
    ax = spec.get(key)
    if ax is None:
        return []
    if not isinstance(ax, dict):
        return [f'{key} must be {{title?, min?, max?}}']
    errs = [f'{key}.{k} must be a positive number (log axis), got {ax[k]!r}' for k in ('min', 'max')
            if k in ax and not _pos(ax[k])]
    if not errs and _pos(ax.get('min')) and _pos(ax.get('max')) and ax['min'] >= ax['max']:
        errs.append(f'{key}.min must be below {key}.max')
    return errs


def validate(spec):
    errs = need_list(spec, 'roofs', 1, 3)
    roofs = [r for r in spec['roofs'] if isinstance(r, dict)] if isinstance(spec.get('roofs'), list) else []
    for i, r in enumerate(spec.get('roofs') if isinstance(spec.get('roofs'), list) else []):
        if not isinstance(r, dict):
            errs.append(f'roofs[{i}] must be {{name, peak, bandwidth, tone?, dashed?, ridge?}}')
            continue
        errs += need(r, 'name', f'roofs[{i}]') + opt_tone(r, f'roofs[{i}]')
        for k in ('peak', 'bandwidth'):
            bad = num(r.get(k), f'roofs[{i}].{k}')
            errs += bad or ([] if r[k] > 0 else [f'roofs[{i}].{k} must be above 0'])
    good_roofs = [r for r in roofs if _pos(r.get('peak')) and _pos(r.get('bandwidth'))]
    pts = spec.get('points', [])
    if not isinstance(pts, list) or len(pts) > 12:
        errs.append('points must be a list of at most 12 kernels; split into two figures or keep the ones the '
                    'title talks about')
        pts = []
    for i, p in enumerate(pts):
        if not isinstance(p, dict):
            errs.append(f'points[{i}] must be {{label, x, y?, tone?, emph?}}')
            continue
        errs += need(p, 'label', f'points[{i}]') + opt_tone(p, f'points[{i}]')
        for k in ('x', 'y'):
            if k in p and not _pos(p[k]):
                errs.append(f'points[{i}].{k} must be a positive number (log axis), got {p[k]!r}')
        if 'x' not in p:
            errs.append(f'points[{i}].x (arithmetic intensity) is required')
        elif _pos(p['x']) and _pos(p.get('y')) and good_roofs:
            top = max(roof_at(r, p['x']) for r in good_roofs)
            if p['y'] > top * TOO_HIGH:
                errs.append(f'points[{i}] ({p.get("label")}) is at y={p["y"]:g} but the highest roof at '
                            f'x={p["x"]:g} is {top:.3g}; nothing runs above its roof. Check the number, its unit, '
                            f'and that x is FLOP per byte')
    errs += _validate_axis(spec, 'x') + _validate_axis(spec, 'y')
    reg = spec.get('regions')
    if reg is not None and not (isinstance(reg, list) and len(reg) == 2 and all(isinstance(s, str) for s in reg)):
        errs.append('regions must be [left label, right label], e.g. ["带宽受限", "算力受限"]')
    return errs


def _tick(v):
    for div, suffix in ((1e6, 'M'), (1e3, 'K')):
        if v >= div:
            return f'{v / div:g}{suffix}'
    return f'{v:g}'


def _ridge(r):
    v = r['peak'] / r['bandwidth']
    return f'{v:.0f}' if v >= 10 else f'{v:.2g}'


def _ranges(spec, roofs, pts):
    ax, ay = spec.get('x') or {}, spec.get('y') or {}
    ridges = [r['peak'] / r['bandwidth'] for r in roofs]
    # points keep at least half a marker-spacing off the frame, so none sits on an axis line
    xs = [p['x'] / EDGE for p in pts]
    xlo = ax.get('min') or 10 ** math.floor(math.log10(min(xs + [k / 30 for k in ridges])))
    xhi = ax.get('max') or 10 ** math.ceil(math.log10(max([p['x'] * EDGE for p in pts] + [k * 8 for k in ridges])))
    peak = max(r['peak'] for r in roofs)
    ys = [p['y'] / EDGE for p in pts]
    ylo = ay.get('min') or 10 ** math.floor(math.log10(min(ys + [peak / 1000])))
    yhi = ay.get('max') or peak * HEAD_ROOM
    if math.log10(xhi / xlo) > MAX_DECADES or math.log10(yhi / ylo) > MAX_DECADES:
        raise LayoutError(f'the axes would span more than {MAX_DECADES} decades; drop the outlier point or set '
                          'x/y min and max')
    return xlo, xhi, ylo, yhi


def _decades(lo, hi):
    return [10.0 ** k for k in range(math.ceil(math.log10(lo) - 1e-9), math.floor(math.log10(hi) + 1e-9) + 1)]


def _spot(px, py, text, size, bold, segs, boxes, bounds, cands=SPOTS):
    """First label box near (px, py) that clears every segment, box and the plot edge; None if all collide."""
    tw, th = measure(text, size, bold), size
    for dx, dy, anchor in cands:
        tx = px + dx
        x0 = tx - tw / 2 if anchor == 'middle' else tx if anchor == 'start' else tx - tw
        box = (x0, py + dy - th * 0.85, x0 + tw, py + dy + th * 0.22)
        if box[0] < bounds[0] or box[2] > bounds[2] or box[1] < bounds[1] or box[3] > bounds[3]:
            continue
        if not _hits(box, segs, boxes):
            return tx, py + dy, anchor, box
    return None


def draw(cv, spec, x, y, w):
    roofs = [dict({'tone': ('main', 'contrast', 'base')[i], 'dashed': i > 0}, **r) for i, r in enumerate(spec['roofs'])]
    pts = [dict(p, y=p.get('y') or roof_at(roofs[0], p['x'])) for p in spec.get('points') or []]
    xlo, xhi, ylo, yhi = _ranges(spec, roofs, pts)
    ax, ay = spec.get('x') or {}, spec.get('y') or {}
    tiny, small = T['type']['tiny'], T['type']['small']
    yt = _decades(ylo, yhi)
    tick_w = max(measure(_tick(t), tiny) for t in yt) + 12
    top, ph = y + 26, PLOT_H
    px0, pw = x + tick_w, w - tick_w - 8
    lx, ly = math.log10(xlo), math.log10(ylo)
    sx = lambda v: px0 + pw * (math.log10(v) - lx) / (math.log10(xhi) - lx)
    sy = lambda v: top + ph - ph * (math.log10(v) - ly) / (math.log10(yhi) - ly)
    bounds = (px0 + 4, top + 2, px0 + pw - 4, top + ph - 4)

    cv.text(x, y + 12, ay.get('title', '吞吐（TFLOPS）'), tiny, T['sub'])
    # roofs that differ by a few percent run a few pixels apart, so they are named in a key row above the plot
    kx = x + w
    for r in reversed(roofs):
        f = cv.use(r['tone'])
        kx -= measure(r['name'], small, True)
        cv.text(kx, y + 12, r['name'], small, f['ink'], True)
        cv.line(kx - 26, y + 7.5, kx - 6, y + 7.5, f['main'], 2.5, dash=r['dashed'])
        kx -= 26 + 20
    if kx < x + measure(ay.get('title', '吞吐（TFLOPS）'), tiny) + 16:
        raise LayoutError('roof names do not fit on one row above the plot; shorten them (e.g. "实测 786T · 3.02 TB/s")')
    for t in yt:
        cv.line(px0, sy(t), px0 + pw, sy(t), T['divider'], 1)
        cv.text(px0 - 8, sy(t) + 4, _tick(t), tiny, T['sub'], anchor='end')
    for t in _decades(xlo, xhi):
        cv.line(sx(t), top, sx(t), top + ph, T['divider'], 1)
        cv.text(sx(t), top + ph + 18, _tick(t), tiny, T['sub'], anchor='middle')
    cv.line(px0, top + ph, px0 + pw, top + ph, T['rule'], 1)
    cv.line(px0, top, px0, top + ph, T['rule'], 1)
    cv.text(px0 + pw / 2, top + ph + 42, ax.get('title', '算术强度（FLOP/Byte）'), tiny, T['sub'], anchor='middle')

    lines, segs = [], []
    for r in roofs:
        x_start = max(xlo, ylo / r['bandwidth'])
        knee = r['peak'] / r['bandwidth']
        path = [(sx(x_start), sy(roof_at(r, x_start)))]
        if xlo < knee < xhi:
            path.append((sx(knee), sy(r['peak'])))
        path.append((sx(xhi), sy(roof_at(r, xhi))))
        lines.append((r, path, knee))
        segs += pairs(path)
    for r, _, knee in lines:
        if r.get('ridge') is not False and xlo < knee < xhi:
            segs.append(((sx(knee), sy(r['peak'])), (sx(knee), top + ph)))

    boxes = [(sx(p['x']) - MARK - 2, sy(p['y']) - MARK - 2, sx(p['x']) + MARK + 2, sy(p['y']) + MARK + 2)
             for p in pts]
    labels = []

    def place(where, px, py, text, size, bold, cands=SPOTS):
        spot = _spot(px, py, text, size, bold, segs, boxes, bounds, cands)
        if not spot:
            raise LayoutError(f'{where} {text!r} has no free spot in the plot; shorten it, drop a nearby point, '
                              'or widen the x/y range')
        boxes.append(spot[3])
        return spot[:3]

    for k, (r, path, knee) in enumerate(lines):
        f = cv.use(r['tone'])
        cv.polyline(path, f['main'], 2.5 if k == 0 else 2, dash=r['dashed'])
        if r.get('ridge') is not False and xlo < knee < xhi:
            kx = sx(knee)
            cv.line(kx, sy(r['peak']), kx, top + ph, f['line'], 1, dash=True)
            text = r.get('ridge') or f'拐点 {_ridge(r)}'
            labels.append((place(f'roofs[{k}].ridge', kx, top + ph - 10, text, tiny, False,
                                 [(6, 0, 'start'), (-6, 0, 'end'), (6, -24, 'start'), (-6, -24, 'end')]),
                           text, tiny, f['ink'], False))

    for i, p in enumerate(pts):
        f = cv.use(p['tone']) if p.get('tone') else None
        color = f['main'] if f else T['ink']
        cv.circle(sx(p['x']), sy(p['y']), MARK + (1.5 if p.get('emph') else 0), color, T['card'], 1.5)
        bold = bool(p.get('emph'))
        labels.append((place(f'points[{i}].label', sx(p['x']), sy(p['y']), p['label'], tiny, bold),
                       p['label'], tiny, f['ink'] if f else T['ink'], bold))

    reg = spec.get('regions')
    if reg:
        knees = [knee for _, _, knee in lines]
        left_mid = (px0 + sx(min(max(min(knees), xlo), xhi))) / 2
        right_mid = (sx(min(max(max(knees), xlo), xhi)) + px0 + pw) / 2
        for side, (cx, text) in enumerate(((left_mid, reg[0]), (right_mid, reg[1]))):
            labels.append((place(f'regions[{side}]', cx, top + ph - 12, text, small, False,
                                 [(0, 0, 'middle'), (0, -24, 'middle'), (0, -ph / 2, 'middle')]),
                           text, small, T['sub'], False))

    for (tx, ty, anchor), text, size, color, bold in labels:
        cv.text(tx, ty, text, size, color, bold, anchor)
    return top + ph + 50
