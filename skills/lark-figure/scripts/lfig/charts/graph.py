"""graph: nodes in left-to-right stages joined by orthogonal arrows. For branches, merges, bypasses and feedback."""
from ..canvas import T, lh, measure, pairs, wrap
from ._common import LayoutError, need, need_list, opt_tone

DOC = {
    'summary': 'Architecture / data flow that branches and merges: you place nodes in stages, arrows route themselves.',
    'fields': {
        'stages': 'list (2-5), left to right, of {name?:str, nodes:[{id, title, sub?:str, tone?, emph?:bool}] (1-4, '
                  'top to bottom)}. Order is exactly what you write: there is no automatic reordering; nodes only slide '
                  'up or down to line up with their neighbours so arrows run straight',
        'edges': 'list (1-20) of {from:id, to:id, label?:str, dashed?:bool}. To the next stage: plain arrow. Skipping '
                 'a stage (max 4): routed over the top. To an earlier stage (max 3): feedback, dashed, routed under '
                 'the bottom. Within a stage: only between vertical neighbours',
        'tips': 'to avoid crossings list each stage\'s nodes in the same top-to-bottom order as the nodes they connect '
                'to; keep labels to a few words',
    },
    'example': {
        'type': 'graph',
        'title': '七成流量走在线链路，缓存命中的请求不再占用 GPU',
        'subtitle': '从左到右是一次请求经过的环节；绿色是本季度新增的缓存旁路',
        'source': '来源：推理网关 2026-10 流量统计',
        'stages': [
            {'name': '入口', 'nodes': [{'id': 'gw', 'title': '推理网关', 'sub': '鉴权 · 限流', 'tone': 'base'}]},
            {'name': '分流', 'nodes': [{'id': 'online', 'title': '在线链路', 'sub': '流量 70%'},
                                     {'id': 'batch', 'title': '批量链路', 'sub': '流量 30%', 'tone': 'base'}]},
            {'name': '执行', 'nodes': [{'id': 'cache', 'title': 'Prefix 缓存', 'sub': '命中率 62%', 'tone': 'good',
                                      'emph': True},
                                     {'id': 'gpu', 'title': 'GPU 推理池'},
                                     {'id': 'spot', 'title': 'Spot 批处理池', 'tone': 'base'}]},
            {'name': '观测', 'nodes': [{'id': 'mon', 'title': '监控告警', 'sub': '延迟 · 成本', 'tone': 'base'}]},
        ],
        'edges': [
            {'from': 'gw', 'to': 'online'}, {'from': 'gw', 'to': 'batch'},
            {'from': 'online', 'to': 'cache'}, {'from': 'cache', 'to': 'gpu', 'label': '未命中'},
            {'from': 'batch', 'to': 'spot'},
            {'from': 'cache', 'to': 'mon'}, {'from': 'gpu', 'to': 'mon'}, {'from': 'spot', 'to': 'mon'},
        ],
    },
}

MIN_GAP, MAX_GAP, MAX_W, PAD, MIN_H = 96, 200, 220, 12, 52
MAX_SKIP, MAX_BACK = 4, 3
NEAR, FAR, STEP = 12, 18, 5  # side lanes for skip/feedback runs: NEAR the node they leave, FAR from the one they enter
LANE, LANE_LABEL, HEAD = 8, 24, 10
CLEAR, PORT, PORT_STEP = 26, 0.68, 0.08  # lane clearance over the nodes it passes; skip ports, as a share of width
ROW_SLACK = 2  # rows the straight-arrow alignment may add to the body before centred columns are kept instead


def validate(spec):
    errs = need_list(spec, 'stages', 2, 5) + need_list(spec, 'edges', 1, 20)
    ids = {}
    for i, st in enumerate(spec['stages'] if isinstance(spec.get('stages'), list) else []):
        if not isinstance(st, dict) or need_list(st, 'nodes', 1, 4):
            errs.append(f'stages[{i}] must be {{name?, nodes:[1-4 nodes]}}; split a crowded stage in two')
            continue
        for j, n in enumerate(st['nodes']):
            where = f'stages[{i}].nodes[{j}]'
            if not isinstance(n, dict) or not isinstance(n.get('id'), (str, int)):
                errs.append(f'{where} must be {{id:str, title, sub?, tone?, emph?}}')
                continue
            errs += need(n, 'title', where) + opt_tone(n, where)
            if n['id'] in ids:
                errs.append(f'{where}.id {n["id"]!r} is already used; every node needs its own id')
            ids[n['id']] = (i, j)
    skips = backs = 0
    for k, e in enumerate(spec['edges'] if isinstance(spec.get('edges'), list) else []):
        a, b = (e.get('from'), e.get('to')) if isinstance(e, dict) else (None, None)
        unknown = [v for v in (a, b) if not isinstance(v, (str, int)) or v not in ids]
        if unknown:
            errs.append(f'edges[{k}] must be {{from:id, to:id}}; no node has id {unknown[0]!r} '
                        f'(ids: {", ".join(map(str, ids))})')
            continue
        (sa, ja), (sb, jb) = ids[a], ids[b]
        if a == b:
            errs.append(f'edges[{k}]: from and to are both {a!r}; say "retries" in the node sub instead of a self-loop')
        elif sa == sb and abs(ja - jb) != 1:
            errs.append(f'edges[{k}]: {a!r} and {b!r} share a stage but are not neighbours; reorder that stage\'s '
                        'nodes or move one of them to another stage')
        skips += sb - sa > 1
        backs += sb < sa
    if skips > MAX_SKIP:
        errs.append(f'{skips} edges skip a stage; max {MAX_SKIP}. Add the skipped stage\'s node to the path or split')
    if backs > MAX_BACK:
        errs.append(f'{backs} edges point to an earlier stage; max {MAX_BACK}. Keep only the feedback that matters')
    return errs


def _adjacent(edges, at, mid, gl, gr):
    """Paths for the edges crossing one gap. Bends that share a source (or a target) share one vertical trunk."""
    bent = [e for e in edges if abs(mid(at[e['from']]) - mid(at[e['to']])) > 0.5]
    fan_out = [e['from'] for e in bent]
    fan_in = [e['to'] for e in bent]
    groups = {}
    for i, e in enumerate(bent):
        key = (('from', e['from']) if fan_out.count(e['from']) > 1 else
               ('to', e['to']) if fan_in.count(e['to']) > 1 else ('edge', i))
        groups.setdefault(key, []).append(e)

    def rank(es):
        sy = sum(mid(at[e['from']]) for e in es) / len(es)
        down = sum(mid(at[e['to']]) for e in es) / len(es) > sy
        return (0, sy) if down else (1, -sy)

    # trunks run in the middle of the gap, the upper-left-to-lower-right ones rightmost: that order never crosses
    lo, hi = gl + NEAR + MAX_SKIP * STEP + 4, gr - FAR - MAX_SKIP * STEP - 4
    order = sorted(groups.values(), key=rank)
    trunk = {id(e): hi - (hi - lo) * (r + 0.5) / len(order) for r, es in enumerate(order) for e in es}
    paths = []
    for e in edges:
        sy, ty = mid(at[e['from']]), mid(at[e['to']])
        tx = trunk.get(id(e))
        paths.append((e, [(gl + 4, sy), (gr - 4, ty)] if tx is None else
                      [(gl + 4, sy), (tx, sy), (tx, ty), (gr - 4, ty)]))
    return paths


def _isotonic(d, w, step):
    """Weighted least-squares fit of y to d keeping y[j+1] - y[j] >= step: pool adjacent violators on d[j] - j*step."""
    blocks = []
    for j, (dj, wj) in enumerate(zip(d, w)):
        blocks.append([dj - j * step, wj, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    return [v + j * step for j, v in enumerate(v for v, _, c in blocks for _ in range(c))]


def _rows(stages, adjacent, at, step):
    """Top of every node relative to the body. Each node slides toward the nodes it links to in the neighbouring
    stages so those arrows run straight instead of jogging, keeping the written order and spacing. If that would
    stack the body more than ROW_SLACK rows taller than plain centred columns, the centred columns win."""
    col = [[nd['id'] for nd in st['nodes']] for st in stages]
    tall = max(len(c) for c in col)
    centred = {i: (tall - len(c)) * step / 2 + j * step for c in col for j, i in enumerate(c)}
    prev, succ = {i: [] for i in at}, {i: [] for i in at}
    for e in adjacent:
        prev[e['to']].append(e['from'])
        succ[e['from']].append(e['to'])
    y = dict(centred)
    for sweep in range(4):
        fwd = sweep % 2 == 0
        for s in range(1, len(col)) if fwd else range(len(col) - 2, -1, -1):
            links = [(prev if fwd else succ)[i] for i in col[s]]
            d = [sum(y[k] for k in ln) / len(ln) if ln else y[i] for i, ln in zip(col[s], links)]
            y.update(zip(col[s], _isotonic(d, [1 if ln else 1e-3 for ln in links], step)))
    lo = min(y.values())
    y = {i: v - lo for i, v in y.items()}
    return y if max(y.values()) <= max(centred.values()) + ROW_SLACK * step else centred


def _lanes(es, at, nh, cw, sep, over):
    """(edge, lane, ax, bx) for skips routed over the top or feedback under the bottom. A lane clears every node it
    passes, and the ones its stubs climb past, by CLEAR; lanes whose runs overlap stack sep apart. Ports sit off-centre
    toward the direction of travel, so a node that receives one bypass and sends the next never shares a stub."""
    out, used = [], {}
    sign = -1 if over else 1
    for e in sorted(es, key=lambda e: abs(at[e['to']]['s'] - at[e['from']]['s'])):
        a, b = at[e['from']], at[e['to']]
        ka, kb = used.get(('out', e['from']), 0), used.get(('in', e['to']), 0)
        used[('out', e['from'])], used[('in', e['to'])] = ka + 1, kb + 1
        fa, fb = (PORT + PORT_STEP * ka, 1 - PORT - PORT_STEP * kb) if over else \
            (1 - PORT - PORT_STEP * ka, PORT + PORT_STEP * kb)
        ax, bx = a['x'] + cw * fa, b['x'] + cw * fb
        s0, s1 = sorted((a['s'], b['s']))
        near = [v for v in at.values() if s0 < v['s'] < s1 or v is a or v is b
                or any(v['s'] == u['s'] and (v['j'] < u['j'] if over else v['j'] > u['j']) for u in (a, b))]
        lane = min(v['y'] for v in near) - CLEAR if over else max(v['y'] + nh for v in near) + CLEAR
        x0, x1 = sorted((ax, bx))
        while True:
            hit = [ln for _, ln, p, q in out if min(p, q) < x1 + 12 and max(p, q) > x0 - 12 and abs(ln - lane) < sep]
            if not hit:
                break
            lane = (min(hit) if over else max(hit)) + sign * sep
        out.append((e, lane, ax, bx))
    return out


def _label_spot(pts, text, others, bounds):
    """Baseline position (x, y, anchor) for an edge label beside its own line, clear of every other line and box."""
    size = T['type']['tiny']
    tw = measure(text, size)
    # the last segment ends in the arrowhead: centre on its shaft, because the board takes a label that overlaps
    # the head for the head's own text and reports it as overflowing
    (px, py), (qx, qy) = pts[-2], pts[-1]
    shaft = (qx - HEAD * (qx > px) + HEAD * (qx < px), qy - HEAD * (qy > py) + HEAD * (qy < py))
    segs = pairs(pts[:-1] + [shaft])
    for (ax, ay), (bx, by) in sorted(segs, key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))):
        if ay == by:
            cx = (ax + bx) / 2
            tries = [(cx, ay - 9, 'middle', cx - tw / 2), (cx, ay + 18, 'middle', cx - tw / 2)]
        else:
            cy = (ay + by) / 2 + 4
            tries = [(ax + 8, cy, 'start', ax + 8), (ax - 8, cy, 'end', ax - 8 - tw)]
        for tx, ty, anchor, x0 in tries:
            box = (x0 - 2, ty - size * 0.85 - 2, x0 + tw + 2, ty + size * 0.22 + 2)
            inside = bounds[0] <= box[0] and box[2] <= bounds[1]
            if inside and not any(o[0] < box[2] and o[2] > box[0] and o[1] < box[3] and o[3] > box[1] for o in others):
                return tx, ty, anchor, box
    return None


def _box(seg):
    (ax, ay), (bx, by) = seg
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def draw(cv, spec, x, y, w):
    stages, edges = spec['stages'], spec['edges']
    n = len(stages)
    cw = min(MAX_W, (w - (n - 1) * MIN_GAP) / n)
    gap = min(MAX_GAP, (w - n * cw) / (n - 1))
    left = x + (w - n * cw - (n - 1) * gap) / 2
    size, ssize = T['type']['body'], T['type']['tiny']
    at = {}
    for s, st in enumerate(stages):
        for j, nd in enumerate(st['nodes']):
            title = wrap(nd['title'], size, cw - 2 * PAD, True)
            sub = wrap(nd['sub'], ssize, cw - 2 * PAD) if nd.get('sub') else []
            at[nd['id']] = {'s': s, 'j': j, 'x': left + s * (cw + gap), 'title': title, 'sub': sub, 'spec': nd}
    nh = max([MIN_H] + [lh(size) * len(v['title']) + lh(ssize) * len(v['sub']) + 2 * PAD for v in at.values()])
    span = [(e, at[e['to']]['s'] - at[e['from']]['s']) for e in edges]
    skips, backs = [e for e, d in span if d > 1], [e for e, d in span if d < 0]
    # a vertical arrow between neighbours needs room for its head, and for a label beside the shaft if it has one
    vgap = max([20] + [56 if e.get('label') else 34 for e, d in span if d == 0])
    rows = _rows(stages, [e for e, d in span if d == 1], at, nh + vgap)
    for i, v in at.items():
        v['y'] = rows[i]
    head = 30 if any(st.get('name') for st in stages) else 0
    # lanes over the top (skips) and under the bottom (feedback) sit closer together when none carries a label
    up, dn = (LANE_LABEL if any(e.get('label') for e in es) else LANE for es in (skips, backs))
    lanes = _lanes(skips, at, nh, cw, up, True) + _lanes(backs, at, nh, cw, dn, False)
    room = {id(e): LANE_LABEL if e.get('label') else LANE for e in skips + backs}
    lo = min([0] + [ln - room[id(e)] for e, ln, _, _ in lanes if e in skips])
    hi = max([max(rows.values()) + nh] + [ln + room[id(e)] for e, ln, _, _ in lanes if e in backs])
    dy = y + head + (8 if skips else 0) - lo
    for v in at.values():
        v['y'] += dy

    def mid(v):
        return v['y'] + nh / 2

    paths = []
    for g in range(n - 1):
        here = [e for e, d in span if d == 1 and at[e['from']]['s'] == g]
        paths += _adjacent(here, at, mid, left + g * (cw + gap) + cw, left + (g + 1) * (cw + gap))
    for e, lane, ax, bx in lanes:
        a, b = at[e['from']], at[e['to']]
        ay, by = (a['y'] - 4, b['y'] - 4) if e in skips else (a['y'] + nh + 4, b['y'] + nh + 4)
        paths.append((e, [(ax, ay), (ax, lane + dy), (bx, lane + dy), (bx, by)]))
    links = {(e['from'], e['to']) for e in edges}
    for e, d in span:
        if d == 0:
            a, b = at[e['from']], at[e['to']]
            down = a['j'] < b['j']
            cx = a['x'] + cw / 2 + ((10 if down else -10) if (e['to'], e['from']) in links else 0)
            paths.append((e, [(cx, a['y'] + nh + 4), (cx, b['y'] - 4)] if down else
                          [(cx, a['y'] - 4), (cx, b['y'] + nh + 4)]))

    taken = []
    for s, st in enumerate(stages):
        if st.get('name'):
            cx = left + s * (cw + gap) + cw / 2
            cv.text(cx, y + 15, st['name'], T['type']['small'], T['sub'], True, 'middle')
            taken.append((cx - cw / 2, y, cx + cw / 2, y + 20))
    for e, pts in paths:
        cv.arrow(pts, dash=bool(e.get('dashed')) or e in backs)
    for v in at.values():
        nd = v['spec']
        f = cv.use(nd.get('tone'))
        emph = nd.get('emph')
        cv.rect(v['x'], v['y'], cw, nh, f['bg'] if emph else f['bg2'], f['main'] if emph else f['line'],
                T['radius']['chip'], T['stroke']['emph'] if emph else T['stroke']['panel'], role='node')
        block = lh(size) * len(v['title']) + lh(ssize) * len(v['sub'])
        ty = v['y'] + (nh - block) / 2
        ty += cv.lines(v['x'] + cw / 2, ty, v['title'], size, f['ink'] if emph else T['ink'], True, 'middle')
        cv.lines(v['x'] + cw / 2, ty, v['sub'], ssize, T['sub'], anchor='middle')

    taken += [_box(seg) for _, pts in paths for seg in pairs(pts)]
    taken += [(v['x'], v['y'], v['x'] + cw, v['y'] + nh) for v in at.values()]
    for k, e in enumerate(edges):
        if not e.get('label'):
            continue
        pts = next(p for ee, p in paths if ee is e)
        spot = _label_spot(pts, e['label'], taken, (x, x + w))
        if not spot:
            raise LayoutError(f'edges[{k}].label {e["label"]!r} has no free spot beside its arrow; shorten it to a '
                              'word or two, or move the detail into the node sub')
        tx, ty, anchor, box = spot
        taken.append(box)
        cv.text(tx, ty, e['label'], T['type']['tiny'], T['sub'], anchor=anchor)
    return hi + dy + (4 if backs else 0)
