"""layers: a layered architecture stack. Each layer is a full-width band with a name column and module chips."""
from ..canvas import T, lh, measure, wrap
from ._common import need, need_list, opt_tone

DOC = {
    'summary': 'Layered architecture / capability stack: top layer = closest to the user.',
    'fields': {
        'layers': 'list (2-7) of {name, note?:str, tone?, items:[str | {label, sub?:str, tone?, emph?:bool}]}',
        'side': 'optional {title, items:[str], tone?} a vertical band on the right spanning all layers',
        'arrows': 'optional bool, draw a thin down-arrow between layers (request flow)',
    },
    'example': {
        'type': 'layers',
        'title': '训练平台分四层，调度层是唯一跨团队共享的瓶颈',
        'subtitle': '自上而下是请求方向；红色模块是本季度要改造的部分',
        'source': '来源：平台架构评审 2026Q3',
        'layers': [
            {'name': '接入层', 'note': '用户入口', 'tone': 'base', 'items': ['Web 控制台', 'CLI', 'OpenAPI']},
            {'name': '调度层', 'note': '多租户', 'items': [{'label': '队列调度', 'emph': True, 'tone': 'risk'},
                                                     '配额', {'label': 'Gang 调度', 'sub': '整组分配'}]},
            {'name': '运行时', 'items': ['PyTorch', 'DeepSpeed', 'Megatron', 'vLLM']},
            {'name': '基础设施', 'tone': 'base', 'items': ['K8s', 'RDMA 网络', '并行文件系统', 'GPU 节点']},
        ],
        'side': {'title': '可观测性', 'items': ['指标', '日志', 'Trace'], 'tone': 'good'},
    },
}

CHIP_H, CHIP_H2, CHIP_GAP, MIN_CHIP = 40, 56, 12, 104


def validate(spec):
    errs = need_list(spec, 'layers', 2, 7)
    for i, L in enumerate(spec.get('layers') or []):
        errs += need(L, 'name', f'layers[{i}]') + opt_tone(L, f'layers[{i}]')
        errs += need_list(L, 'items', 1, 12, f'layers[{i}]')
    if spec.get('side'):
        errs += need(spec['side'], 'title', 'side') + need_list(spec['side'], 'items', 1, 8, 'side')
    return errs


def _item(it):
    return it if isinstance(it, dict) else {'label': str(it)}


def _rows(items, w):
    """Flex-wrap chips into rows, then stretch each row to fill w exactly."""
    size = T['type']['body']
    rows, cur, used = [], [], 0
    for it in items:
        need_w = max(MIN_CHIP, measure(it['label'], size, it.get('emph', False)) + 32,
                     measure(it.get('sub', ''), T['type']['tiny']) + 32)
        if cur and used + CHIP_GAP + need_w > w:
            rows.append(cur)
            cur, used = [], 0
        used += (CHIP_GAP if cur else 0) + need_w
        cur.append((it, need_w))
    rows.append(cur)
    return rows


def _band_height(rows):
    hs = [CHIP_H2 if any(it.get('sub') for it, _ in r) else CHIP_H for r in rows]
    return sum(hs) + CHIP_GAP * (len(rows) - 1) + 2 * 16, hs


def _side_width(side_items, side_title):
    """Width of the side panel; adapts to label/value pairs vs plain chips."""
    size = T['type']['body']
    head = measure(side_title, T['type']['head'], True)
    cases = []
    for s in side_items:
        if 'value' in s:
            cases.append(measure(s['label'], size) + measure(s['value'], size, True) + 64)
        else:
            cases.append(measure(s['label'], size) + 48)
    return max([150, max(cases + [head + 48])])


def draw(cv, spec, x, y, w):
    layers = spec['layers']
    side = spec.get('side')
    # normalize side items: dicts pass through _item so `{'label': '46.7B'}` renders as '46.7B'.
    side_items = [_item(s) for s in side['items']] if side else []
    side_w = 0
    if side:
        side_w = _side_width(side_items, side['title'])
    band_w = w - (side_w + T['space']['tight'] if side else 0)
    name_w = min(240, max(132, max(measure(L['name'], T['type']['head'], True) for L in layers) + 44))
    chip_w = band_w - name_w - 16
    gap = 28 if spec.get('arrows') else T['space']['tight']
    cy = y
    for i, L in enumerate(layers):
        f = cv.use(L.get('tone'))
        rows = _rows([_item(it) for it in L['items']], chip_w)
        bh, hs = _band_height(rows)
        cv.rect(x, cy, band_w, bh, f['bg2'], f['line'], T['radius']['panel'], T['stroke']['panel'], role='layer')
        note = L.get('note')
        name_h = lh(T['type']['head']) + (lh(T['type']['tiny']) if note else 0)
        ny = cy + (bh - name_h) / 2
        cv.lines(x + 20, ny, [L['name']], T['type']['head'], f['ink'], bold=True)
        if note:
            cv.lines(x + 20, ny + lh(T['type']['head']), [note], T['type']['tiny'], T['sub'])
        ry = cy + 16
        for r, row in enumerate(rows):
            total = sum(nw for _, nw in row) + CHIP_GAP * (len(row) - 1)
            extra = (chip_w - total) / len(row)
            # equal widths whenever every label fits: layers with the same chip count then share column edges
            equal = (chip_w - CHIP_GAP * (len(row) - 1)) / len(row)
            even = all(nw <= equal for _, nw in row)
            rx = x + name_w
            for it, nw in row:
                cw = equal if even else nw + extra
                tone_used = it.get('tone') or L.get('tone') or 'base'
                cf = cv.use(tone_used)
                emph = it.get('emph')
                disabled = it.get('disabled')
                # chip stroke: emph uses family main; base (gray) uses rule (stronger than gray.line) so
                # the chip doesn't blend into its own pale background. colored families keep their own line.
                border = cf['main'] if emph else (T['rule'] if tone_used == 'base' else cf['line'])
                border_w = T['stroke']['emph'] if emph else T['stroke']['thin']
                if disabled:
                    # R4: disabled chips render as a ghost of themselves — dashed gray border, sub-colour text
                    cv.rect(rx, ry, cw, hs[r], T['card'], T['rule'], T['radius']['chip'],
                            border_w, dash=True, role='chip-disabled')
                else:
                    cv.rect(rx, ry, cw, hs[r], cf['bg'] if emph else T['card'], border,
                            T['radius']['chip'], border_w, role='layer-chip')
                text_color = T['sub'] if it.get('disabled') else T['ink']
                if it.get('sub'):
                    cv.text(rx + cw / 2, ry + 23, it['label'], T['type']['body'], text_color, emph, 'middle')
                    cv.text(rx + cw / 2, ry + 43, it['sub'], T['type']['tiny'], T['sub'], anchor='middle')
                else:
                    cv.text(rx + cw / 2, ry + hs[r] / 2 + 5, it['label'], T['type']['body'], text_color, emph, 'middle')
                rx += cw + CHIP_GAP
            ry += hs[r] + CHIP_GAP
        cy += bh
        if spec.get('arrows') and i < len(layers) - 1:
            cv.arrow([(x + band_w / 2, cy + 3), (x + band_w / 2, cy + gap - 3)], sw=1.5)
        cy += gap
    bottom = cy - gap
    if side:
        f = cv.use(side.get('tone', 'base'))
        sx = x + w - side_w
        cv.rect(sx, y, side_w, bottom - y, f['bg2'], f['line'], T['radius']['panel'], T['stroke']['panel'], role='side')
        cv.text(sx + side_w / 2, y + 34, side['title'], T['type']['head'], f['ink'], True, 'middle')
        n = len(side_items)
        top, avail = y + 56, bottom - y - 56 - 16
        ih = min(44, (avail - (n - 1) * 10) / n)
        start = top  # items hang under their heading; centring them leaves the heading stranded at the top
        for k, s in enumerate(side_items):
            iy = start + k * (ih + 10)
            if 'value' in s:
                # key=value pair: grey label on the left, value chip on the right
                cv.text(sx + 20, iy + ih / 2 + 5, s['label'], T['type']['body'], T['sub'])
                vf = cv.use(s.get('tone', 'main'))
                vw = measure(s['value'], T['type']['body'], True) + 16
                cv.rect(sx + side_w - 20 - vw, iy + (ih - 24) / 2, vw, 24,
                        vf['bg2'], vf['line'], T['radius']['chip'], T['stroke']['thin'], role='side-kv')
                cv.text(sx + side_w - 20 - vw / 2, iy + ih / 2 + 5, s['value'],
                        T['type']['body'], vf['ink'], True, 'middle')
            else:
                if s.get('tone'):
                    sf = cv.use(s['tone'])
                    cv.rect(sx + 16, iy, side_w - 32, ih, sf['bg2'], sf['line'], T['radius']['chip'])
                    ink = sf['ink']
                else:
                    cv.rect(sx + 16, iy, side_w - 32, ih, T['card'], f['line'], T['radius']['chip'])
                    ink = T['ink']
                label = wrap(s['label'], T['type']['body'], side_w - 48)[0]
                cv.text(sx + side_w / 2, iy + ih / 2 + 5, label, T['type']['body'], ink, anchor='middle')
    return bottom
