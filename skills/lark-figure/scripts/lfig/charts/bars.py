"""bars: horizontal bars, values written at the bar end. Single series or grouped (series × categories)."""
import math

from ..canvas import T, measure, wrap
from ._common import fmt, need, need_list, num, opt_tone

DOC = {
    'summary': 'Ranking or magnitude comparison; long labels welcome. Use grouped form for 2-3 series per category.',
    'fields': {
        'rows': 'single series: list (2-16) of {label, value:number, tone?, note?:str}',
        'series': 'grouped form: list (2-3) of {name, tone?}; then rows are {label, values:[number per series]}',
        'unit': 'optional suffix written after every value, e.g. "ms", "%", " GB"',
        'sort': 'optional "desc" | "asc" | "none" (default none: keep your order)',
        'log': 'optional bool, log10 scale for values spanning orders of magnitude (say so in subtitle)',
        'ref': 'optional {value, label} dashed reference line, e.g. a target or baseline',
    },
    'example': {
        'type': 'bars',
        'title': '换成 FlashAttention-3 后，长序列 Attention 提速 2.6 倍',
        'subtitle': '单卡 H100，序列长度 16K，前向耗时；蓝色是本文方案',
        'source': '来源：FlashAttention-3 论文 表 3',
        'unit': ' ms',
        'rows': [
            {'label': '标准 Attention', 'value': 41.2, 'tone': 'base'},
            {'label': 'FlashAttention-2', 'value': 22.5, 'tone': 'base'},
            {'label': 'FlashAttention-3', 'value': 15.8, 'tone': 'main', 'note': '本文'},
        ],
        'ref': {'value': 20, 'label': '目标 20 ms'},
    },
}

BH, GAP, GBH, GGAP, GROUP_GAP = 28, 14, 20, 4, 20


def validate(spec):
    errs = need_list(spec, 'rows', 1, 16)
    series = spec.get('series')
    if series:
        errs += need_list(spec, 'series', 2, 4)
    for i, r in enumerate(spec.get('rows') or []):
        errs += need(r, 'label', f'rows[{i}]') + opt_tone(r, f'rows[{i}]')
        if series:
            vals = r.get('values')
            if not isinstance(vals, list) or len(vals) != len(series):
                errs.append(f'rows[{i}].values must list one number per series ({len(series)})')
            else:
                for j, v in enumerate(vals):
                    errs += num(v, f'rows[{i}].values[{j}]')
        else:
            errs += num(r.get('value'), f'rows[{i}].value')
    if spec.get('log'):
        vals = [v for r in spec.get('rows') or [] for v in (r.get('values') or [r.get('value')])]
        if any(isinstance(v, (int, float)) and v <= 0 for v in vals):
            errs.append('log scale needs every value > 0')
    return errs


def _scale(spec, vmax, width):
    if spec.get('log'):
        vals = [v for r in spec['rows'] for v in (r.get('values') or [r['value']])]
        lo = 10 ** math.floor(math.log10(min(vals)))
        hi = math.log10(vmax / lo) or 1
        return lambda v: max(4, width * (0.08 + 0.92 * math.log10(v / lo) / hi))
    return lambda v: max(4, width * v / (vmax or 1))


def draw(cv, spec, x, y, w):
    rows, unit, series = list(spec['rows']), spec.get('unit', ''), spec.get('series')
    if spec.get('sort') in ('desc', 'asc') and not series:
        rows.sort(key=lambda r: r['value'], reverse=spec['sort'] == 'desc')
    size, vsize = T['type']['body'], T['type']['small']
    label_w = min(360, max(100, max(measure(r['label'], size) for r in rows) + 20))
    vals = [v for r in rows for v in (r.get('values') or [r['value']])]
    notes = [r.get('note') for r in rows]
    tail = max(measure(fmt(v, unit), vsize, True) for v in vals) + 16
    tail += max([measure(' · ' + n, vsize) for n in notes if n] or [0])
    # the track spans the whole row (bar area + value tail) so every value label sits inside it;
    # the board flags text that starts inside a shape and runs past its edge
    bar_w = w - label_w - tail
    vmax = max(vals + [spec.get('ref', {}).get('value', 0)])
    sx = _scale(spec, vmax, bar_w)
    bx = x + label_w
    cy = y
    if series:
        lx = bx
        for s in series:
            f = cv.use(s.get('tone'))
            cv.rect(lx, cy + 2, 12, 12, f['main'], rx=3)
            cv.text(lx + 18, cy + 13, s['name'], T['type']['small'], T['sub'])
            lx += measure(s['name'], T['type']['small']) + 44
        cy += 32
    top = cy
    texts = []  # (row_top, row_bottom, x0, x1) of value labels, so the ref line can skip them
    for r in rows:
        if series:
            gh = len(series) * GBH + (len(series) - 1) * GGAP
            label = wrap(r['label'], size, label_w - 20)
            cv.lines(bx - 14, cy + gh / 2 - len(label) * 11, label, size, T['ink'], anchor='end')
            for j, s in enumerate(series):
                f = cv.use(s.get('tone'))
                v = r['values'][j]
                yy = cy + j * (GBH + GGAP)
                cv.rect(bx, yy, bar_w + tail, GBH, T['track'], rx=T['radius']['bar'], role='track')
                cv.rect(bx, yy, sx(v), GBH, f['main'], rx=T['radius']['bar'], role='bar')
                cv.text(bx + sx(v) + 8, yy + GBH / 2 + 4.5, fmt(v, unit), vsize, T['sub'])
                texts.append((yy, yy + GBH, bx + sx(v) + 8, bx + sx(v) + 8 + measure(fmt(v, unit), vsize)))
            cy += gh + GROUP_GAP
        else:
            f = cv.use(r.get('tone'))
            label = wrap(r['label'], size, label_w - 20)
            cv.lines(bx - 14, cy + BH / 2 - len(label) * 11, label, size, T['ink'], anchor='end')
            cv.rect(bx, cy, bar_w + tail, BH, T['track'], rx=T['radius']['bar'], role='track')
            cv.rect(bx, cy, sx(r['value']), BH, f['main'], rx=T['radius']['bar'], role='bar')
            vtxt = fmt(r['value'], unit)
            bold = bool(r.get('tone')) and r.get('tone') != 'base'
            tx0 = bx + sx(r['value']) + 8
            cv.text(tx0, cy + BH / 2 + 4.5, vtxt, vsize, f['ink'] if r.get('tone') else T['sub'], bold=bold)
            tx1 = tx0 + measure(vtxt, vsize, bold)
            if r.get('note'):
                cv.text(tx1 + 2, cy + BH / 2 + 4.5, '· ' + r['note'], vsize, T['sub'])
                tx1 += 2 + measure('· ' + r['note'], vsize)
            texts.append((cy, cy + BH, tx0, tx1))
            cy += max(BH, 22 * len(label)) + GAP
    bottom = cy - (GROUP_GAP if series else GAP)
    ref = spec.get('ref')
    if ref:
        rx = bx + sx(ref['value'])
        # draw the reference line in pieces, leaving a gap wherever a value label sits on it
        cuts = sorted((t0 - 2, t1 + 2) for t0, t1, a, b in texts if a - 4 <= rx <= b + 4)
        y0 = top - 6
        for c0, c1 in cuts:
            if c0 > y0:
                cv.line(rx, y0, rx, c0, T['arrow'], 1.5, dash=True)
            y0 = max(y0, c1)
        if bottom + 6 > y0:
            cv.line(rx, y0, rx, bottom + 6, T['arrow'], 1.5, dash=True)
        cv.text(rx, bottom + 24, ref.get('label') or fmt(ref['value'], unit), T['type']['tiny'], T['sub'], anchor='middle')
        bottom += 28
    return bottom
