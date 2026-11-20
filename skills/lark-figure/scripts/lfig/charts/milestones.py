"""milestones: dated events on a horizontal axis, cards alternating above and below to keep text roomy."""
from ..canvas import T, fit, lh, measure, wrap
from ._common import need, need_list, opt_tone

MIN_CARD = 176

DOC = {
    'summary': 'Roadmap, release history, incident timeline: 3-8 dated events in order.',
    'fields': {
        'items': 'list (3-8) of {when, title, lines?:[str], tone?, now?:bool}',
        'note': 'mark the current point with now:true; use tone good for done, main for planned, risk for slipped',
    },
    'example': {
        'type': 'milestones',
        'title': '推理平台一年三次换代，下一步是 PD 分离',
        'subtitle': '绿色已上线，蓝色在做，灰色规划中',
        'source': '来源：平台 roadmap 2026',
        'items': [
            {'when': '2026-01', 'title': '静态批处理', 'lines': ['单模型单实例'], 'tone': 'good'},
            {'when': '2026-04', 'title': '连续批处理', 'lines': ['吞吐 ×2.3'], 'tone': 'good'},
            {'when': '2026-08', 'title': 'Prefix 缓存', 'lines': ['首 token 时延 -40%'], 'tone': 'good'},
            {'when': '2026-11', 'title': 'PD 分离', 'lines': ['预填与解码分池'], 'tone': 'main', 'now': True},
            {'when': '2027-Q2', 'title': '多模型混部', 'lines': ['按 SLO 调度'], 'tone': 'base'},
        ],
    },
}


def validate(spec):
    errs = need_list(spec, 'items', 3, 8)
    for i, it in enumerate(spec.get('items') or []):
        errs += need(it, 'when', f'items[{i}]') + need(it, 'title', f'items[{i}]') + opt_tone(it, f'items[{i}]')
    return errs


def draw(cv, spec, x, y, w):
    items = spec['items']
    n, inset = len(items), 16
    slot = w / n
    alternate = n > 4
    # end cards get clamped inward, so size cards to leave a 12px gap to their same-side neighbour even then
    cap = min(300, 2 * slot - 24, (2.5 * slot - 12) / 1.5) if alternate else min(300, slot - 24)
    # one shared width that hugs the widest card's content: a 300px box around a 6-char title reads as empty
    small = T['type']['small']
    natural = max(max([measure(it['when'], small, True), measure(it['title'], 16, True)] +
                      [measure(s, small) for s in it.get('lines') or []]) for it in items) + 2 * inset + 8
    cw = min(cap, max(MIN_CARD, natural))
    lays = []
    for it in items:
        ts, tl = fit(it['title'], cw - 2 * inset, [16, 15, 14], 2, bold=True)
        body = [ln for s in it.get('lines') or [] for ln in wrap(s, T['type']['small'], cw - 2 * inset)]
        h = 2 * inset + lh(T['type']['small']) + 4 + lh(ts) * len(tl) + lh(T['type']['small']) * len(body)
        lays.append((ts, tl, body, h))
    ch = max(L[3] for L in lays)
    stem = 28
    axis_y = y + ch + stem
    bottom = axis_y + (ch + stem if alternate else 0)
    cv.line(x, axis_y, x + w, axis_y, T['rule'], 2)
    for i, (it, L) in enumerate(zip(items, lays)):
        f = cv.use(it.get('tone'))
        cx = x + slot * (i + 0.5)
        up = not alternate or i % 2 == 0
        card_y = axis_y - stem - ch if up else axis_y + stem
        card_x = min(max(cx - cw / 2, x), x + w - cw)  # end cards slide inward instead of leaving the margin
        cv.line(cx, axis_y + (-8 if up else 8), cx, card_y + (ch if up else 0), T['rule'], 1.5, dash=True)
        hi = it.get('now')
        cv.rect(card_x, card_y, cw, ch, f['bg'] if hi else T['card'], f['main'] if hi else f['line'],
                T['radius']['panel'], T['stroke']['emph'] if hi else T['stroke']['thin'], role='milestone')
        if hi:
            cv.circle(cx, axis_y, 13, f['bg'], f['line'], 1)
        cv.circle(cx, axis_y, 7, f['main'], T['card'], 2)
        ts, tl, body, _ = L
        ty = card_y + inset - 2
        ty += cv.lines(card_x + inset, ty, [it['when']], T['type']['small'], f['ink'], bold=True) + 4
        ty += cv.lines(card_x + inset, ty, tl, ts, T['ink'], bold=True)
        cv.lines(card_x + inset, ty, body, T['type']['small'], T['sub'])
    return max(bottom, axis_y + 14)
