"""sequence: who calls whom, in order. Actors across the top with lifelines, messages top to bottom."""
from ..canvas import T, fit, lh, wrap
from ._common import LayoutError, need, need_list, opt_tone

DOC = {
    'summary': 'Calls between 2-6 services or roles in time order: request path, handshake, incident hand-offs.',
    'fields': {
        'actors': 'list (2-6), left to right, of str | {name, sub?:str, tone?}',
        'messages': 'list (1-14), top to bottom, of {from:actor name, to:actor name, text, reply?:bool}. '
                    'reply draws a dashed return arrow; from == to draws a self-call. Keep text to one short phrase',
        'sections': 'optional list of {at:int, label}: a labelled divider before messages[at] (phases of the exchange)',
    },
    'example': {
        'type': 'sequence',
        'title': '首 token 的 165 ms 里，有 120 ms 是调度器在排队',
        'subtitle': '一次流式推理请求的调用顺序；虚线是返回，红色是耗时最长的一方',
        'source': '来源：线上 trace 抽样 1 万条',
        'actors': ['客户端', {'name': '网关', 'sub': '鉴权 · 限流'}, {'name': '调度器', 'sub': '多租户队列', 'tone': 'risk'},
                   {'name': 'GPU 节点', 'sub': 'vLLM'}],
        'messages': [
            {'from': '客户端', 'to': '网关', 'text': 'POST /v1/chat'},
            {'from': '网关', 'to': '调度器', 'text': '申请推理槽位'},
            {'from': '调度器', 'to': '调度器', 'text': '排队 120 ms'},
            {'from': '调度器', 'to': 'GPU 节点', 'text': '下发 batch'},
            {'from': 'GPU 节点', 'to': '网关', 'text': '首 token（45 ms）', 'reply': True},
            {'from': '网关', 'to': '客户端', 'text': '流式返回', 'reply': True},
        ],
        'sections': [{'at': 0, 'label': '接入与排队'}, {'at': 3, 'label': '计算与返回'}],
    },
}

HEAD_H, HEAD_H2, ROW_GAP, LOOP = 40, 58, 18, 26


def _actor(a):
    return a if isinstance(a, dict) else {'name': str(a)}


def validate(spec):
    errs = need_list(spec, 'actors', 2, 6) + need_list(spec, 'messages', 1, 14)
    names = []
    for i, a in enumerate(spec['actors'] if isinstance(spec.get('actors'), list) else []):
        a = _actor(a)
        errs += need(a, 'name', f'actors[{i}]') + opt_tone(a, f'actors[{i}]')
        if a.get('name') in names:
            errs.append(f'actors[{i}].name {a["name"]!r} appears twice; every actor needs its own name')
        names.append(a.get('name'))
    msgs = spec['messages'] if isinstance(spec.get('messages'), list) else []
    for k, m in enumerate(msgs):
        if not isinstance(m, dict):
            errs.append(f'messages[{k}] must be {{from, to, text, reply?}}')
            continue
        errs += need(m, 'text', f'messages[{k}]')
        for end in ('from', 'to'):
            if m.get(end) not in names:
                errs.append(f'messages[{k}].{end} {m.get(end)!r} is not an actor; '
                            f'use one of: {", ".join(map(str, names))}')
    for j, s in enumerate(spec.get('sections') or []):
        at = s.get('at') if isinstance(s, dict) else None
        if not isinstance(at, int) or isinstance(at, bool) or not 0 <= at < len(msgs) or not s.get('label'):
            errs.append(f'sections[{j}] must be {{at:int, label}} with at = index of the section\'s first message '
                        f'(0-{len(msgs) - 1})')
    return errs


def draw(cv, spec, x, y, w):
    actors = [_actor(a) for a in spec['actors']]
    n = len(actors)
    pitch = w / n
    cxs = {a['name']: x + pitch * (i + 0.5) for i, a in enumerate(actors)}
    order = {a['name']: i for i, a in enumerate(actors)}
    size, small = T['type']['body'], T['type']['small']
    bw = min(200, pitch - 24)
    bh = HEAD_H2 if any(a.get('sub') for a in actors) else HEAD_H
    room = pitch - 24  # a label stays inside one lifeline span, so no lifeline ever runs through it
    sections = {s['at']: s['label'] for s in spec.get('sections') or []}
    rows, cy = [], y + bh + 20
    for k, m in enumerate(spec['messages']):
        lines = wrap(m['text'], small, room)
        if len(lines) > 2:
            raise LayoutError(f'messages[{k}].text is too long to sit between two lifelines; keep it under about '
                              f'{int(room / (small * T["measure"]["cjk"])) * 2} CJK chars or split the message')
        if k in sections:
            rows.append(('section', sections[k], cy + 10))
            cy += 34
        ay = cy + lh(small) * len(lines) + 3
        rows.append(('message', m, lines, cy, ay))
        cy = ay + (LOOP if m['from'] == m['to'] else 0) + ROW_GAP
    bottom = cy - ROW_GAP + 14
    for a in actors:
        f = cv.use(a.get('tone', 'base'))
        cx = cxs[a['name']]
        cv.line(cx, y + bh, cx, bottom, T['rule'], 1.5, dash=True)
        cv.rect(cx - bw / 2, y, bw, bh, f['bg2'], f['line'], T['radius']['chip'], T['stroke']['panel'], role='actor')
        nsize, name = fit(a['name'], bw - 16, [size, small, T['type']['tiny']], 1, bold=True)
        ink = T['ink'] if a.get('tone', 'base') == 'base' else f['ink']
        if a.get('sub'):
            cv.text(cx, y + 25, name[0], nsize, ink, True, 'middle')
            sub = wrap(a['sub'], T['type']['tiny'], bw - 16)[0]
            cv.text(cx, y + 44, sub, T['type']['tiny'], T['sub'], anchor='middle')
        else:
            cv.text(cx, y + bh / 2 + 5, name[0], nsize, ink, True, 'middle')
    for row in rows:
        if row[0] == 'section':
            _, label, sy = row
            lw = cv.pill(x, sy - 12, label, 'base')[0]
            cv.line(x + lw + 8, sy, x + w, sy, T['divider'], 1)
            continue
        _, m, lines, ty, ay = row
        a, b = cxs[m['from']], cxs[m['to']]
        # labels start at the sender; the last actor's self-call folds to the left to stay on the canvas
        right = b > a or (a == b and order[m['from']] < n - 1)
        cv.lines(a + 10 if right else a - 10, ty, lines, small, T['ink'], anchor='start' if right else 'end')
        if a == b:
            d = LOOP if right else -LOOP
            cv.arrow([(a, ay), (a + d, ay), (a + d, ay + LOOP - 8), (a + (4 if right else -4), ay + LOOP - 8)])
        else:
            cv.arrow([(a, ay), (b + (-2 if right else 2), ay)], dash=bool(m.get('reply')))
    return bottom
