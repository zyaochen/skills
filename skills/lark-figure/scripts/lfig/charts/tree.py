"""tree: left-to-right decomposition (root → branches → leaves) with orthogonal connectors. Depth ≤ 4."""
from ..canvas import T, lh, measure, wrap
from ._common import need, opt_tone

DOC = {
    'summary': 'Breakdown of one thing into parts: cost decomposition, cause tree, module hierarchy, org chart.',
    'fields': {
        'root': '{label, sub?:str, tone?, children:[node]}; node = {label, sub?, tone?, emph?:bool, children?:[node]}',
        'limits': 'depth ≤ 4, ≤ 12 children per node, ≤ 16 leaves (about 12 when every leaf has a sub: the figure '
                  'must stay under the height cap); an unset root is base (gray) and a child inherits its parent '
                  'tone unless it sets one',
    },
    'example': {
        'type': 'tree',
        'title': 'P99 延迟超标，七成来自排队而不是计算',
        'subtitle': '按耗时拆解一次慢请求；红色是本次要治理的分支',
        'source': '来源：慢请求 trace 抽样 500 条',
        'root': {'label': 'P99 1.8 s', 'sub': '目标 800 ms', 'tone': 'main', 'children': [
            {'label': '排队 1.2 s', 'tone': 'risk', 'emph': True, 'children': [
                {'label': '调度队列', 'sub': '0.9 s'}, {'label': '批次等待', 'sub': '0.3 s'}]},
            {'label': '计算 0.5 s', 'children': [
                {'label': 'Prefill', 'sub': '0.3 s'}, {'label': 'Decode', 'sub': '0.2 s'}]},
            {'label': '网络 0.1 s', 'tone': 'base'},
        ]},
    },
}

NODE_GAP, MIN_W, MAX_W, GROW_W, MAX_GAP = 12, 120, 240, 200, 160
MAX_DEPTH, MAX_KIDS = 4, 12


def validate(spec):
    errs = []
    root = spec.get('root')
    if not isinstance(root, dict):
        return ['root must be {label, children:[...]}']

    too_deep = False

    def walk(n, path, depth):
        nonlocal too_deep
        if not isinstance(n, dict):
            return [f'{path} must be {{label, children?:[...]}}, got {type(n).__name__}']
        e = need(n, 'label', path) + opt_tone(n, path)
        if depth > MAX_DEPTH:
            too_deep = True
            return e + [f'{path}: depth > {MAX_DEPTH}; collapse a level']
        kids = n.get('children') or []
        if not isinstance(kids, list):
            return e + [f'{path}.children must be a list of nodes']
        if len(kids) > MAX_KIDS:
            e.append(f'{path} has {len(kids)} children; max {MAX_KIDS}. Group them under 2-3 parents or split')
        for i, c in enumerate(kids):
            e += walk(c, f'{path}.children[{i}]', depth + 1)
        return e

    errs += walk(root, 'root', 1)
    if not root.get('children'):
        errs.append('root.children is required')
    elif not errs and not too_deep and _leaves(root) > 16:
        errs.append('more than 16 leaves; split into two figures or merge small leaves into "其他"')
    return errs


def _leaves(n):
    return sum(_leaves(c) for c in n['children']) if n.get('children') else 1


def _levels(n, d=0, acc=None):
    acc = acc if acc is not None else {}
    acc.setdefault(d, []).append(n)
    for c in n.get('children') or []:
        _levels(c, d + 1, acc)
    return acc


def draw(cv, spec, x, y, w):
    root = spec['root']
    levels = _levels(root)
    depth = len(levels)
    size, ssize = T['type']['body'], T['type']['tiny']
    col_w = [min(MAX_W, max(MIN_W, max(max(measure(n['label'], size, True), measure(n.get('sub', ''), ssize))
                                       for n in levels[d]) + 32)) for d in range(depth)]
    # spare width goes to the gaps first, then to narrow columns; whatever is left becomes equal side margins
    hgap = min(MAX_GAP, max(48, (w - sum(col_w)) / (depth - 1))) if depth > 1 else 0
    grow = (w - sum(col_w) - hgap * (depth - 1)) / depth
    if grow > 0:
        col_w = [max(cw, min(GROW_W, cw + grow)) for cw in col_w]
    total_w = sum(col_w) + hgap * (depth - 1)
    xs = [x + (w - total_w) / 2]
    for d in range(1, depth):
        xs.append(xs[-1] + col_w[d - 1] + hgap)

    def node_h(n, d):
        lines = wrap(n['label'], size, col_w[d] - 24, True)
        return lh(size) * len(lines) + (lh(ssize) if n.get('sub') else 0) + 18, lines

    def place(n, d, top, tone):
        """Post-order: leaves stack downward; a parent centres on its children. Returns subtree bottom."""
        n['_tone'] = n.get('tone') or tone
        n['_h'], n['_lines'] = node_h(n, d)
        n['_d'] = d
        kids = n.get('children') or []
        if not kids:
            n['_y'] = top
            return top + n['_h']
        cur = top
        for c in kids:
            cur = place(c, d + 1, cur, n['_tone'] if d > 0 else c.get('tone') or tone) + NODE_GAP
        cur -= NODE_GAP
        first, last = kids[0], kids[-1]
        mid = (first['_y'] + first['_h'] / 2 + last['_y'] + last['_h'] / 2) / 2
        n['_y'] = max(top, mid - n['_h'] / 2)
        return max(cur, n['_y'] + n['_h'])

    bottom = place(root, 0, y, root.get('tone', 'base'))

    def paint(n):
        d = n['_d']
        f = cv.use(n['_tone'])
        nx, ny, nh = xs[d], n['_y'], n['_h']
        is_root, emph = d == 0, n.get('emph')
        leaf = not n.get('children')
        fill = f['bg'] if is_root or emph else (T['card'] if leaf else f['bg2'])
        stroke = f['main'] if is_root or emph else f['line']
        cv.rect(nx, ny, col_w[d], nh, fill, stroke, T['radius']['chip'],
                T['stroke']['emph'] if is_root or emph else T['stroke']['thin'], role='node')
        ty = ny + 9
        ty += cv.lines(nx + col_w[d] / 2, ty, n['_lines'], size, f['ink'] if is_root or emph else T['ink'],
                       bold=is_root or emph or not leaf, anchor='middle')
        if n.get('sub'):
            cv.lines(nx + col_w[d] / 2, ty, [n['sub']], ssize, T['sub'], anchor='middle')
        kids = n.get('children') or []
        if kids:
            sx0 = nx + col_w[d]
            sy = ny + nh / 2
            bx = sx0 + hgap / 2
            ys = [c['_y'] + c['_h'] / 2 for c in kids]
            cv.polyline([(sx0, sy), (bx, sy)], T['rule'], 1.5)
            lo, hi = min(ys + [sy]), max(ys + [sy])
            if hi > lo:
                cv.polyline([(bx, lo), (bx, hi)], T['rule'], 1.5)
            for c, cy in zip(kids, ys):
                cv.polyline([(bx, cy), (xs[d + 1], cy)], T['rule'], 1.5)
                paint(c)

    paint(root)
    return bottom
