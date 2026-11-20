"""cycle: 3-8 steps on a closed loop, clockwise. Top row runs left to right, bottom row comes back."""
from ..canvas import T, lh, wrap
from ._common import LayoutError, need, need_list, opt_tone

DOC = {
    'summary': 'A loop that feeds itself: iterate-measure-improve, incident lifecycle, control loop, flywheel.',
    'fields': {
        'steps': 'list (3-8), clockwise from the top-left, of {title, sub?:str, tone?, emph?:bool}',
        'center': 'optional short phrase in the middle of the loop: what the loop drives (a metric, a goal)',
        'numbered': 'optional bool (default true), draw 1,2,3… badges so the starting point is clear',
    },
    'example': {
        'type': 'cycle',
        'title': '复盘改进项回流到容量评估后，重复事故从 9 起降到 2 起',
        'subtitle': '事故处理的五个环节首尾相接；绿色是今年补上的一环',
        'source': '来源：SRE 季度复盘 2026Q3',
        'center': '季度重复事故 9 → 2',
        'steps': [
            {'title': '容量评估', 'sub': '按上季度峰值留 30% 余量', 'tone': 'base'},
            {'title': '灰度发布', 'sub': '1% → 10% → 全量', 'tone': 'base'},
            {'title': '监控告警', 'sub': '发现时间 p50 3 分钟', 'tone': 'base'},
            {'title': '事故响应', 'sub': '止损优先于定位', 'tone': 'base'},
            {'title': '复盘改进', 'sub': '改进项进入下次容量评估', 'tone': 'good', 'emph': True},
        ],
    },
}

MAX_W, MIN_GAP, MAX_GAP, INSET, BADGE = 240, 72, 140, 16, 30


def validate(spec):
    errs = need_list(spec, 'steps', 3, 8)
    for i, s in enumerate(spec['steps'] if isinstance(spec.get('steps'), list) else []):
        if not isinstance(s, dict):
            errs.append(f'steps[{i}] must be {{title, sub?, tone?, emph?}}')
            continue
        errs += need(s, 'title', f'steps[{i}]') + opt_tone(s, f'steps[{i}]')
    return errs


def draw(cv, spec, x, y, w):
    steps = spec['steps']
    n = len(steps)
    k = (n + 1) // 2  # steps in the top row; the rest come back along the bottom
    cw = min(MAX_W, (w - (k - 1) * MIN_GAP) / k)
    gap = min(MAX_GAP, (w - k * cw) / (k - 1))
    pitch = cw + gap
    left = x + (w - k * cw - (k - 1) * gap) / 2
    size, small = T['type']['body'], T['type']['small']
    numbered = spec.get('numbered', True)
    lays = [(wrap(s['title'], size, cw - 2 * INSET - (BADGE if numbered else 0), True),
             wrap(s['sub'], small, cw - 2 * INSET) if s.get('sub') else []) for s in steps]
    ch = max(lh(size) * len(t) + (lh(small) * len(sub) + 2 if sub else 0) for t, sub in lays) + 2 * INSET
    first_cx, last_cx = left + cw / 2, left + (k - 1) * pitch + cw / 2
    center = wrap(spec['center'], T['type']['head'], last_cx - first_cx - 60, True) if spec.get('center') else []
    if len(center) > 2:
        raise LayoutError('center is too long for the middle of the loop; keep it to one short phrase '
                          '(a metric or a goal) and move the rest into subtitle')
    row_gap = max(64, lh(T['type']['head']) * len(center) + 44)
    odd = n - k < k  # an odd loop has one step fewer below, so the bottom row sits between the top columns
    pos = [(left + i * pitch, y) for i in range(k)]
    pos += [(left + (k - 1 - j) * pitch - (pitch / 2 if odd else 0), y + ch + row_gap) for j in range(n - k)]
    top_mid, bot_mid = y + ch / 2, y + ch + row_gap + ch / 2
    for i in range(k - 1):
        cv.arrow([(pos[i][0] + cw + 6, top_mid), (pos[i + 1][0] - 6, top_mid)])
    for j in range(k, n - 1):
        cv.arrow([(pos[j][0] - 6, bot_mid), (pos[j + 1][0] + cw + 6, bot_mid)])
    down, up = (last_cx, y + ch + 6), (first_cx, y + ch + 6)
    if odd:
        cv.arrow([down, (last_cx, bot_mid), (pos[k][0] + cw + 6, bot_mid)])
        cv.arrow([(pos[-1][0] - 6, bot_mid), (first_cx, bot_mid), up])
    else:
        cv.arrow([down, (last_cx, y + ch + row_gap - 6)])
        cv.arrow([(first_cx, y + ch + row_gap - 6), up])
    for i, (s, (title, sub), (px, py)) in enumerate(zip(steps, lays, pos)):
        f = cv.use(s.get('tone'))
        emph = s.get('emph')
        cv.rect(px, py, cw, ch, f['bg'] if emph else f['bg2'], f['main'] if emph else f['line'],
                T['radius']['panel'], T['stroke']['emph'] if emph else T['stroke']['panel'], role='step')
        if numbered:
            cv.badge(px + cw - INSET - 4, py + INSET + 6, str(i + 1), s.get('tone'))
        block = lh(size) * len(title) + (lh(small) * len(sub) + 2 if sub else 0)
        ty = py + (ch - block) / 2
        ty += cv.lines(px + INSET, ty, title, size, f['ink'] if emph else T['ink'], bold=True) + 2
        cv.lines(px + INSET, ty, sub, small, T['sub'])
    if center:
        block = lh(T['type']['head']) * len(center)
        cv.lines((first_cx + last_cx) / 2, y + ch + (row_gap - block) / 2, center, T['type']['head'], T['ink'],
                 bold=True, anchor='middle')
    return y + 2 * ch + row_gap
