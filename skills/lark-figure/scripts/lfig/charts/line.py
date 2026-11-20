"""line: 1-4 series over ordered x labels. Series are labelled directly at their line end, not in a legend box."""
from ..canvas import T, measure
from ._common import fmt, need, need_list, nice_ticks, num, opt_tone

DOC = {
    'summary': 'Trend over an ordered x (sequence length, time, batch size); 1-4 series, direct end labels.',
    'fields': {
        'x': '{labels:[str] (2-16), title?:str}',
        'y': '{title?:str, min?:number, max?:number, unit?:str}',
        'series': 'list (1-4) of {name, values:[number per x label], tone?, area?:bool, labels?:bool}',
        'notes': 'optional list of {series:int, index:int, text} callouts at a data point',
    },
    'example': {
        'type': 'line',
        'title': '序列长度翻 4 倍，Attention 激活显存涨 16 倍',
        'subtitle': '单卡激活显存随序列长度变化；Ring Attention 切到 8 卡后近似线性',
        'source': '来源：本篇 sim_memory.py --seq 输出',
        'x': {'labels': ['8K', '16K', '24K', '32K'], 'title': '序列长度 (tokens)'},
        'y': {'title': '激活显存', 'unit': ' GB', 'min': 0},
        'series': [
            {'name': '不切分', 'values': [2.1, 8.4, 18.9, 33.6], 'tone': 'main', 'area': True, 'labels': True},
            {'name': 'Ring Attention ×8', 'values': [0.26, 1.05, 2.4, 4.2], 'tone': 'good', 'labels': True},
        ],
        'notes': [{'series': 0, 'index': 2, 'text': 'O(S²)'}],
    },
}

PLOT_H = 300


def validate(spec):
    xs = (spec.get('x') or {}).get('labels')
    errs = [] if isinstance(xs, list) and 2 <= len(xs) <= 16 else ['x.labels must be a list of 2-16 strings']
    errs += need_list(spec, 'series', 1, 4)
    for i, s in enumerate(spec.get('series') or []):
        errs += need(s, 'name', f'series[{i}]') + opt_tone(s, f'series[{i}]')
        v = s.get('values')
        if not isinstance(v, list) or (xs and len(v) != len(xs)):
            errs.append(f'series[{i}].values must have one number per x label')
        else:
            for j, val in enumerate(v):
                errs += num(val, f'series[{i}].values[{j}]')
    return errs


def _spread(items, min_gap):
    """Push end labels apart vertically so they never overlap. items: [(y, payload)] → [(y', payload)]."""
    items = sorted(items, key=lambda t: t[0])
    for i in range(1, len(items)):
        if items[i][0] - items[i - 1][0] < min_gap:
            items[i] = (items[i - 1][0] + min_gap, items[i][1])
    return items


def _hits(box, segs, boxes):
    x0, y0, x1, y1 = box
    for (ax, ay), (bx, by) in segs:
        n = max(8, int((abs(bx - ax) + abs(by - ay)) / 3))
        for i in range(n + 1):
            px, py = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
            if x0 - 3 < px < x1 + 3 and y0 - 3 < py < y1 + 3:
                return True
    return any(not (x1 < b[0] or b[2] < x0 or y1 < b[1] or b[3] < y0) for b in boxes)


def _place(px, py, text, size, segs, boxes, bounds, bold=True):
    """First label position around a point that touches no line and no placed label; None if all collide."""
    tw, th = measure(text, size, bold), size
    for dx, dy, anchor in ((0, -12, 'middle'), (0, 22, 'middle'), (8, -10, 'start'), (8, 20, 'start'),
                           (-8, -10, 'end'), (-8, 20, 'end')):
        tx = px + dx
        x0 = tx - tw / 2 if anchor == 'middle' else (tx if anchor == 'start' else tx - tw)
        box = (x0, py + dy - th * 0.85, x0 + tw, py + dy + th * 0.22)
        if box[0] < bounds[0] or box[2] > bounds[2] or box[1] < bounds[1] or box[3] > bounds[3]:
            continue
        if not _hits(box, segs, boxes):
            return tx, py + dy, anchor, box
    return None


def draw(cv, spec, x, y, w):
    xl, ys, series = spec['x']['labels'], spec.get('y') or {}, spec['series']
    unit = ys.get('unit', '')
    vals = [v for s in series for v in s['values']]
    lo = ys.get('min', min(0, min(vals)))
    ticks = nice_ticks(lo, ys.get('max', max(vals)))
    lo, hi = ticks[0], ticks[-1]
    tick_w = max(measure(fmt(t), T['type']['tiny']) for t in ticks) + 14
    end_w = max(measure(s['name'] + ('' if s.get('labels') else '  ' + fmt(s['values'][-1], unit.strip())),
                        T['type']['small'], True) for s in series) + 22
    top = y + (24 if ys.get('title') else 4)
    px0, pw, ph = x + tick_w, w - tick_w - end_w, PLOT_H
    sx = lambda i: px0 + pw * i / (len(xl) - 1)
    sy = lambda v: top + ph - ph * (v - lo) / ((hi - lo) or 1)
    if ys.get('title'):
        # Avoid "KV cache (GB) (GB)": if the caller already embedded the unit in the title, don't duplicate it.
        title = ys['title']
        u = unit.strip()
        if u and u not in title:
            title = f'{title}（{u}）'
        cv.text(x, y + 12, title, T['type']['tiny'], T['sub'])
    for t in ticks:
        ty = sy(t)
        cv.line(px0, ty, px0 + pw, ty, T['divider'] if t != lo else T['rule'], 1)
        cv.text(px0 - 10, ty + 4, fmt(t), T['type']['tiny'], T['sub'], anchor='end')
    for i, lab in enumerate(xl):
        cv.text(sx(i), top + ph + 22, lab, T['type']['tiny'], T['sub'], anchor='middle')
    bottom = top + ph + 30
    if spec['x'].get('title'):
        cv.text(px0 + pw / 2, bottom + 16, spec['x']['title'], T['type']['tiny'], T['sub'], anchor='middle')
        bottom += 22
    for s in series:
        if s.get('area'):
            f = cv.use(s.get('tone'))
            pts = [(sx(i), sy(v)) for i, v in enumerate(s['values'])]
            cv.polygon(pts + [(sx(len(xl) - 1), sy(lo)), (sx(0), sy(lo))], f['bg'], opacity=0.6)
    ends, all_pts = [], []
    for s in series:
        all_pts.append([(sx(i), sy(v)) for i, v in enumerate(s['values'])])
    segs = [seg for pts in all_pts for seg in zip(pts, pts[1:])]
    boxes = []
    for k, s in enumerate(series):
        f = cv.use(s.get('tone'))
        pts = all_pts[k]
        cv.polyline(pts, f['main'], 2.5)
        for i, (px, py) in enumerate(pts):
            cv.circle(px, py, 4, T['card'], f['main'], 2, role='series-point')
            if s.get('labels') and i < len(pts) - 1:
                txt = fmt(s['values'][i], unit.strip())
                spot = _place(px, py, txt, T['type']['tiny'], segs, boxes, (px0 + 2, top - 4, px0 + pw, top + ph))
                if spot:
                    tx, ty, anchor, box = spot
                    boxes.append(box)
                    cv.text(tx, ty, txt, T['type']['tiny'], f['ink'], True, anchor)
        ends.append((pts[-1][1], (s, f, pts[-1])))
    for ey, (s, f, (px, py)) in _spread(ends, 34 if any(s.get('labels') for s in series) else 20):
        label = s['name'] + ('  ' + fmt(s['values'][-1], unit.strip()) if s.get('labels') else '')
        if s.get('labels'):
            cv.text(px + 12, ey + 1, s['name'], T['type']['small'], f['ink'], True)
            cv.text(px + 12, ey + 17, fmt(s['values'][-1], unit.strip()), T['type']['tiny'], f['ink'])
        else:
            cv.text(px + 12, ey + 4.5, label, T['type']['small'], f['ink'], True)
    for n in spec.get('notes') or []:
        s = series[n['series']]
        f = cv.use(s.get('tone'))
        px, py = sx(n['index']), sy(s['values'][n['index']])
        spot = _place(px, py, n['text'], T['type']['small'], segs, boxes, (px0 + 2, top - 4, px0 + pw, top + ph))
        if spot:
            tx, ty, anchor, box = spot
            boxes.append(box)
            cv.text(tx, ty, n['text'], T['type']['small'], f['ink'], True, anchor)
    return bottom
