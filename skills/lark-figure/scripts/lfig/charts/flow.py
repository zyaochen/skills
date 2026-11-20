"""flow: a pipeline of steps joined by arrows. Left-to-right rows (wrapping), or a top-down column."""
from ..canvas import T, fit, lh, measure, wrap
from ._common import need, need_list, opt_tone

DOC = {
    'summary': 'Steps joined by arrows: a pipeline, request path, or before→after sequence.',
    'fields': {
        'steps': 'list (2-12) of {title, lines?:[str], metric?:str, tone?, emph?:bool, note?:str}',
        'labels': 'optional list of edge labels, labels[i] sits on the arrow after steps[i]',
        'direction': '"right" (default, wraps after per_row) or "down"',
        'per_row': 'optional int, steps per row for direction=right (default: all if ≤5, else balanced)',
        'numbered': 'optional bool, draw 1,2,3… badges',
        'groups': 'optional list of {from:int, to:int, label, tone?} brackets above step ranges (right only)',
    },
    'example': {
        'type': 'flow',
        'title': '一次推理请求要过四道关，排队占了 60% 的时间',
        'subtitle': '从网关到返回首 token，大号数字是各段 p50 耗时',
        'source': '来源：线上 trace 抽样 1 万条',
        'numbered': True,
        'steps': [
            {'title': '网关鉴权', 'lines': ['限流 + token 校验'], 'metric': '3 ms', 'tone': 'base'},
            {'title': '调度排队', 'lines': ['等空闲 GPU 槽位'], 'metric': '120 ms', 'tone': 'risk', 'emph': True},
            {'title': 'Prefill', 'lines': ['整段 prompt 一次前向'], 'metric': '45 ms'},
            {'title': '首 token 返回', 'lines': ['流式输出开始'], 'metric': '30 ms', 'tone': 'good'},
        ],
        'labels': ['', '分到槽位', ''],
    },
}


def validate(spec):
    errs = need_list(spec, 'steps', 2, 12)
    for i, s in enumerate(spec.get('steps') or []):
        errs += need(s, 'title', f'steps[{i}]') + opt_tone(s, f'steps[{i}]')
    if spec.get('direction', 'right') not in ('right', 'down'):
        errs.append('direction must be "right" or "down"')
    return errs


def _card_content(step, w, badge=0):
    """Lay out one card's text inside width w; only the title makes room for a ``badge``-wide number badge."""
    ty = T['type']
    inner = w - 2 * T['space']['inset']
    head_size, head = fit(step['title'], inner - badge, [ty['head'], 16], 2, bold=True)
    body = []
    for ln in step.get('lines') or []:
        body += wrap(ln, ty['body'], inner)
    metric = step.get('metric')
    h = lh(head_size) * len(head)
    if metric:
        h += lh(ty['metric'])
    if body:
        h += 6 + lh(ty['body']) * len(body)
    return h, head_size, head, body, metric


def _card(cv, x, y, w, h, step, content, index=None):
    f = cv.use(step.get('tone'))
    emph = step.get('emph')
    sp = T['space']
    cv.rect(x, y, w, h, f['bg'] if emph else f['bg2'], f['main'] if emph else f['line'],
            T['radius']['panel'], T['stroke']['emph'] if emph else T['stroke']['panel'], role='step')
    _, head_size, head, body, metric = content
    tx = x + sp['inset']
    cy = y + sp['inset']
    if index is not None:
        cv.badge(x + w - sp['inset'] - 4, y + sp['inset'] + 6, str(index), step.get('tone'))
    cy += cv.lines(tx, cy, head, head_size, T['ink'], bold=True)
    if metric:
        cy += cv.lines(tx, cy, [metric], T['type']['metric'], f['ink'], bold=True)
    if body:
        cv.lines(tx, cy + 6, body, T['type']['body'], T['sub'])


def _gap_for(labels):
    base = T['space']['arrow_gap']
    widest = max([measure(s, T['type']['tiny']) for s in labels if s] or [0])
    return min(140, max(base, widest + 20))


def draw(cv, spec, x, y, w):
    steps, labels = spec['steps'], list(spec.get('labels') or [])
    labels += [''] * (len(steps) - len(labels))
    if spec.get('direction') == 'down':
        return _draw_down(cv, spec, steps, labels, x, y, w)
    n = len(steps)
    per = spec.get('per_row') or (n if n <= 5 else -(-n // -(-n // 5)))
    rows = [steps[i:i + per] for i in range(0, n, per)]
    gap = _gap_for(labels)
    cw = (w - (per - 1) * gap) / per
    cut = 30 if spec.get('numbered') else 0
    contents = [_card_content(s, cw, cut) for s in steps]
    ch = max(c[0] for c in contents) + 2 * T['space']['inset']
    top = y
    if spec.get('groups'):
        top += 34
    row_gap = 56
    pos = []
    for r, row in enumerate(rows):
        ry = top + r * (ch + row_gap)
        for c, _ in enumerate(row):
            pos.append((x + c * (cw + gap), ry))
    for i, s in enumerate(steps):
        px, py = pos[i]
        _card(cv, px, py, cw, ch, s, contents[i], i + 1 if spec.get('numbered') else None)
    for i in range(n - 1):
        (ax, ay), (bx, by) = pos[i], pos[i + 1]
        if ay == by:
            cv.arrow([(ax + cw + 6, ay + ch / 2), (bx - 6, by + ch / 2)], label=labels[i] or None)
        else:
            mid = ay + ch + row_gap / 2
            cv.arrow([(ax + cw / 2, ay + ch + 4), (ax + cw / 2, mid), (bx + cw / 2, mid), (bx + cw / 2, by - 4)])
            if labels[i]:
                cv.text((ax + bx + cw) / 2, mid - 8, labels[i], T['type']['tiny'], T['sub'], anchor='middle')
    for g in spec.get('groups') or []:
        a, b = pos[g['from']], pos[g['to']]
        if a[1] != b[1]:
            continue
        f = cv.use(g.get('tone', 'base'))
        gx0, gx1, gy = a[0], b[0] + cw, a[1] - 14
        color = f['line'] if g.get('tone') else T['rule']
        cv.polyline([(gx0, gy + 8), (gx0, gy), (gx1, gy), (gx1, gy + 8)], color, 1.5)
        lw = measure(g['label'], T['type']['small'], True) + 16
        cv.rect((gx0 + gx1 - lw) / 2, gy - 10, lw, 20, T['canvas']['bg'])
        cv.text((gx0 + gx1) / 2, gy + 4.5, g['label'], T['type']['small'], f['ink'], bold=True, anchor='middle')
    return pos[-1][1] + ch


def _draw_down(cv, spec, steps, labels, x, y, w):
    has_notes = any(s.get('note') for s in steps)
    cw = min(560, w * 0.5) if has_notes else min(640, w * 0.6)
    cx = x + (w - cw) / 2 if not has_notes else x + 40
    gap = 44
    cy = y
    for i, s in enumerate(steps):
        content = _card_content(s, cw, 30 if spec.get('numbered') else 0)
        ch = content[0] + 2 * T['space']['inset']
        _card(cv, cx, cy, cw, ch, s, content, i + 1 if spec.get('numbered') else None)
        if s.get('note'):
            nx = cx + cw + 40
            note = wrap(s['note'], T['type']['body'], x + w - nx)
            cv.line(cx + cw + 8, cy + ch / 2, nx - 10, cy + ch / 2, T['rule'], 1, dash=True)
            nh = lh(T['type']['body']) * len(note)
            cv.lines(nx, cy + ch / 2 - nh / 2, note, T['type']['body'], T['sub'])
        if i < len(steps) - 1:
            cv.arrow([(cx + cw / 2, cy + ch + 4), (cx + cw / 2, cy + ch + gap - 4)], label=labels[i] or None)
        cy += ch + gap
    return cy - gap
