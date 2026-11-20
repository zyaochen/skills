"""matrix: a 2×2 quadrant on two named axes. Items listed inside each quadrant; the target quadrant highlighted."""
from ..canvas import T, lh, measure, wrap
from ._common import need, need_list, opt_tone

DOC = {
    'summary': '2×2 positioning on two axes (cost × benefit, urgency × impact); point at the quadrant that wins.',
    'fields': {
        'x': '{label, low, high} horizontal axis, low on the left',
        'y': '{label, low, high} vertical axis, low at the bottom',
        'quadrants': 'exactly 4, order [top-left, top-right, bottom-left, bottom-right]; '
                     'each {title, items?:[str], tone?, highlight?:bool}',
    },
    'example': {
        'type': 'matrix',
        'title': '先做左上角：缓存和批处理收益高、改动小',
        'subtitle': '横轴是改造成本，纵轴是预期降本幅度',
        'source': '来源：推理成本复盘会 2026-10',
        'x': {'label': '改造成本', 'low': '低', 'high': '高'},
        'y': {'label': '降本幅度', 'low': '小', 'high': '大'},
        'quadrants': [
            {'title': '立刻做', 'items': ['Prefix 缓存', '动态批处理'], 'tone': 'good', 'highlight': True},
            {'title': '值得排期', 'items': ['投机解码', '量化到 FP8'], 'tone': 'base'},
            {'title': '顺手做', 'items': ['日志降采样'], 'tone': 'base'},
            {'title': '暂缓', 'items': ['自研推理引擎'], 'tone': 'base'},
        ],
    },
}


def validate(spec):
    errs = []
    for ax in ('x', 'y'):
        a = spec.get(ax)
        if not isinstance(a, dict):
            errs.append(f'{ax} must be {{label, low, high}}')
            continue
        for k in ('label', 'low', 'high'):
            errs += need(a, k, ax)
    errs += need_list(spec, 'quadrants', 4, 4)
    for i, q in enumerate(spec.get('quadrants') or []):
        errs += need(q, 'title', f'quadrants[{i}]') + opt_tone(q, f'quadrants[{i}]')
    return errs


def draw(cv, spec, x, y, w):
    qs, gap, inset = spec['quadrants'], T['space']['tight'], T['space']['inset']
    axis_w = max(64, measure(spec['y']['label'], T['type']['small']) + 16)
    gx0 = x + axis_w
    qw = (w - axis_w - gap) / 2
    body = [[ln for it in (q.get('items') or []) for ln in wrap(it, T['type']['body'], qw - 2 * inset - 16)] for q in qs]
    content = max(lh(T['type']['head']) + 10 + lh(T['type']['body']) * len(b) for b in body)
    qh = max(150, content + 2 * inset)
    top = y + 24
    for i, q in enumerate(qs):
        f = cv.use(q.get('tone'))
        hi = q.get('highlight')
        qx = gx0 + (i % 2) * (qw + gap)
        qy = top + (i // 2) * (qh + gap)
        cv.rect(qx, qy, qw, qh, f['bg'] if hi else f['bg2'], f['main'] if hi else f['line'],
                T['radius']['panel'], T['stroke']['emph'] if hi else T['stroke']['panel'], role='quadrant')
        ty = qy + inset
        ty += cv.lines(qx + inset, ty, [q['title']], T['type']['head'], f['ink'], bold=True) + 10
        for it in q.get('items') or []:
            ls = wrap(it, T['type']['body'], qw - 2 * inset - 16)
            cv.circle(qx + inset + 4, ty + lh(T['type']['body']) / 2, 3, f['main'])
            ty += cv.lines(qx + inset + 16, ty, ls, T['type']['body'], T['ink'])
    gh = 2 * qh + gap
    small, sub = T['type']['small'], T['sub']
    # y axis: arrow up along the left edge, high at top, low at bottom, name above
    ax = gx0 - 22
    cv.arrow([(ax, top + gh), (ax, top)], T['arrow'], 1.5)
    cv.text(ax, top - 10, spec['y']['label'], small, T['ink'], True, 'middle')
    cv.text(ax - 10, top + 24, spec['y']['high'], small, sub, anchor='end')
    cv.text(ax - 10, top + gh - 8, spec['y']['low'], small, sub, anchor='end')
    # x axis: arrow right under the grid
    ay = top + gh + 20
    cv.arrow([(gx0, ay), (gx0 + w - axis_w, ay)], T['arrow'], 1.5)
    cv.text(gx0, ay + 22, spec['x']['low'], small, sub)
    cv.text(gx0 + w - axis_w, ay + 22, spec['x']['high'], small, sub, anchor='end')
    cv.text(gx0 + (w - axis_w) / 2, ay + 22, spec['x']['label'], small, T['ink'], True, 'middle')
    return ay + 28
