"""timeline: Gantt-style spans on lanes over a numeric axis (time, steps, tokens). Good for overlap and critical paths."""
from ..canvas import T, measure
from ._common import fmt, need, need_list, nice_ticks, num, opt_tone

DOC = {
    'summary': 'Spans on parallel lanes over a shared axis: pipeline overlap, schedules, critical path, Gantt.',
    'fields': {
        'lanes': 'list (1-14) of {label, spans:[{start, end, text?, tone?, dashed?:bool, emph?:bool}]}; '
                 'emph gives one span (the critical one) a strong edge',
        'axis': '{min?, max?, ticks?:[number], unit?:str}; min/max default to the data range',
        'markers': 'optional list of {at, label, tone?} vertical lines (deadline, sync point)',
        'legend': 'recommended: [{label, tone, style?:"solid"|"dashed"}] explaining span colors',
    },
    'example': {
        'type': 'timeline',
        'title': '梯度分桶让通信藏进计算，只剩最后 10 ms 露在外面',
        'subtitle': '每桶计算 20 ms、AllReduce 10 ms；前 3 段通信落在下一桶的计算里',
        'source': '来源：Llama 7B 例子，4 桶合计 90 ms',
        'axis': {'min': 0, 'max': 100, 'ticks': [0, 20, 40, 60, 80, 100], 'unit': 'ms'},
        'lanes': [
            {'label': '桶 1', 'spans': [{'start': 0, 'end': 20, 'text': '计算', 'tone': 'good'},
                                       {'start': 20, 'end': 30, 'text': '通信', 'dashed': True}]},
            {'label': '桶 2', 'spans': [{'start': 20, 'end': 40, 'text': '计算', 'tone': 'good'},
                                       {'start': 40, 'end': 50, 'text': '通信', 'dashed': True}]},
            {'label': '桶 3', 'spans': [{'start': 40, 'end': 60, 'text': '计算', 'tone': 'good'},
                                       {'start': 60, 'end': 70, 'text': '通信', 'dashed': True}]},
            {'label': '桶 4', 'spans': [{'start': 60, 'end': 80, 'text': '计算', 'tone': 'good'},
                                       {'start': 80, 'end': 90, 'text': '暴露', 'tone': 'risk', 'emph': True}]},
        ],
        'markers': [{'at': 90, 'label': '迭代结束', 'tone': 'risk'}],
        'legend': [{'label': '计算', 'tone': 'good'}, {'label': '被下一桶盖住的通信', 'tone': 'base', 'style': 'dashed'},
                   {'label': '关键路径上的通信', 'tone': 'risk'}],
    },
}

LANE_H, LANE_GAP = 34, 10


def _label(cv, s, f, siblings, sx, plot, marks, ly, where):
    """Span text goes inside when it fits (stepping down to tiny), else just beside the span on whichever side
    of the lane is empty and marker-free, Gantt style. Only when neither side has room is it dropped, with a note."""
    txt, x0, x1 = s['text'], sx(s['start']), sx(s['end'])
    ty = ly + LANE_H / 2 + 4.5
    for size, pad in ((T['type']['small'], 10), (T['type']['tiny'], 6)):
        if measure(txt, size) + pad <= x1 - x0:
            cv.text((x0 + x1) / 2, ty, txt, size, f['ink'], anchor='middle')
            return
    size, gap = T['type']['tiny'], 6
    tw = measure(txt, size)
    others = [o for o in siblings if o is not s]
    right = min([sx(o['start']) for o in others if o['start'] >= s['end']] + [plot[1]])
    left = max([sx(o['end']) for o in others if o['end'] <= s['start']] + [plot[0]])
    clear = lambda a, b: not any(a - 4 <= m <= b + 4 for m in marks)
    if x1 + gap + tw + gap <= right and clear(x1, x1 + gap + tw):
        cv.text(x1 + gap, ty, txt, size, T['sub'])
    elif x0 - gap - tw - gap >= left and clear(x0 - gap - tw, x0):
        cv.text(x0 - gap, ty, txt, size, T['sub'], anchor='end')
    else:
        cv.notes.append(f'{where}.text {txt!r} fits neither inside its span nor beside it; widen the span, '
                        'shorten the text, or move it to the legend')


def validate(spec):
    errs = need_list(spec, 'lanes', 1, 14)
    for i, L in enumerate(spec.get('lanes') or []):
        errs += need(L, 'label', f'lanes[{i}]') + need_list(L, 'spans', 1, 20, f'lanes[{i}]')
        for j, s in enumerate(L.get('spans') or []):
            w = f'lanes[{i}].spans[{j}]'
            bad = num(s.get('start'), w + '.start') + num(s.get('end'), w + '.end')
            errs += bad + opt_tone(s, w)
            if not bad and s['end'] <= s['start']:
                errs.append(f'{w}: end must be > start')
    for k, m in enumerate(spec.get('markers') or []):
        errs += num(m.get('at'), f'markers[{k}].at')
    return errs


def draw(cv, spec, x, y, w):
    lanes, axis = spec['lanes'], spec.get('axis') or {}
    spans = [s for L in lanes for s in L['spans']]
    lo = axis.get('min', min(s['start'] for s in spans))
    hi = axis.get('max', max(s['end'] for s in spans))
    ticks = axis.get('ticks') or [t for t in nice_ticks(lo, hi) if lo <= t <= hi]
    unit = axis.get('unit', '')
    label_w = min(220, max(64, max(measure(L['label'], T['type']['body']) for L in lanes) + 24))
    unit_w = measure(unit, T['type']['tiny']) + 8 if unit else 0
    px0, pw = x + label_w, w - label_w - 40 - unit_w
    sx = lambda v: px0 + pw * (v - lo) / ((hi - lo) or 1)
    top = y + (22 if spec.get('markers') else 0)
    bottom = top + len(lanes) * (LANE_H + LANE_GAP) - LANE_GAP
    marks = [sx(m['at']) for m in spec.get('markers') or []]
    # markers go first so the opaque spans sit on top of them and the line never crosses span text
    for m in spec.get('markers') or []:
        f = cv.use(m.get('tone', 'risk'))
        mx = sx(m['at'])
        cv.line(mx, top - 6, mx, bottom + 8, f['main'], 1.5, dash=True)
        cv.text(mx, top - 12, m['label'], T['type']['tiny'], f['ink'], bold=True, anchor='middle')
    for i, L in enumerate(lanes):
        ly = top + i * (LANE_H + LANE_GAP)
        cv.text(px0 - 14, ly + LANE_H / 2 + 5, L['label'], T['type']['body'], T['ink'], anchor='end')
        for j, s in enumerate(L['spans']):
            f = cv.use(s.get('tone'))
            x0, x1 = sx(s['start']), sx(s['end'])
            dashed, emph = s.get('dashed'), s.get('emph') and not s.get('dashed')
            # every span gets its family's soft border; only an emph span earns the saturated 2px edge
            cv.rect(x0 + 1, ly, x1 - x0 - 2, LANE_H, f['bg2'] if dashed else f['bg'],
                    f['main'] if emph else f['line'], 6, T['stroke']['emph'] if emph else T['stroke']['panel'],
                    dash=dashed, role='span')
            if s.get('text'):
                _label(cv, s, f, L['spans'], sx, (px0, px0 + pw + 28), marks, ly, f'lanes[{i}].spans[{j}]')
    ay = bottom + 18
    cv.arrow([(px0, ay), (px0 + pw + 28, ay)], T['arrow'], 1.5)
    for t in ticks:
        tx = sx(t)
        cv.line(tx, ay - 4, tx, ay, T['arrow'], 1.5)
        cv.text(tx, ay + 20, fmt(t), T['type']['tiny'], T['sub'], anchor='middle')
    if unit:
        cv.text(px0 + pw + 36, ay + 4.5, unit, T['type']['tiny'], T['sub'])
    return ay + 26
