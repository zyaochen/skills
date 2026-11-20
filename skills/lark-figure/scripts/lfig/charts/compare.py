"""compare: 2-4 side-by-side cards with the same rows, so the reader scans across. One card may be primary."""
from ..canvas import T, fit, lh, measure, wrap
from ._common import need, need_list, opt_tone

DOC = {
    'summary': 'Side-by-side options with comparable attributes (A vs B vs C); mark the recommended one with primary.',
    'fields': {
        'cards': 'list (2-4) of {title, subtitle?, tone?, primary?:bool, highlight?:bool (legacy), '
                 'id?:str (①②③ badge), icon?:str (✗/✓ prefix), card_style?:"filled"|"outlined", '
                 'verdict?:str, rows?:[[key, value] | {k, v, tone?}], points?:[str], foot?:str}',
        'note': 'every card should use the same row keys in the same order so values line up; '
                'only ONE card should be primary; tone stays on verdict pill text only',
    },
    'example': {
        'type': 'compare',
        'title': '同样 64 卡，TP8×PP2×DP4 比纯数据并行省 98% 显存',
        'subtitle': '三种切法的单卡显存、每步通信和 MFU；✗ = 旧方案，✓ = 推荐',
        'source': '来源：本篇 sim_parallel.py 输出',
        'cards': [
            {'title': '纯 DP', 'subtitle': 'DP=64', 'id': '①', 'icon': '✗', 'verdict': '显存放不下',
             'rows': [['显存 / 卡', {'v': '90 GB', 'tone': 'risk'}], ['通信 / 步', '160 ms'], ['MFU', '24%']]},
            {'title': 'TP8 · PP2 · DP4', 'subtitle': '机内切张量，机间切流水', 'id': '②', 'icon': '✓',
             'primary': True, 'tone': 'good', 'verdict': '推荐',
             'rows': [['显存 / 卡', '1.5 GB'], ['通信 / 步', '40 ms'], ['MFU', '35–45%']]},
            {'title': 'PP8', 'subtitle': '只切流水线', 'id': '③', 'icon': '✗', 'verdict': '气泡大',
             'rows': [['显存 / 卡', '11 GB'], ['通信 / 步', '25 ms'], ['MFU', '18%']]},
        ],
    },
}

ROW_H = 38
ID_R = 11  # radius of the circular ① badge
PILL_ROW = T['type']['tiny'] + 12 + 8  # a verdict pill on its own row under the title, with the gap below it


def validate(spec):
    errs = need_list(spec, 'cards', 2, 7)
    n_primary = 0
    for i, c in enumerate(spec.get('cards') or []):
        errs += need(c, 'title', f'cards[{i}]') + opt_tone(c, f'cards[{i}]')
        if not c.get('rows') and not c.get('points'):
            errs.append(f'cards[{i}] needs rows or points')
        if c.get('primary') or c.get('highlight'):
            n_primary += 1
        style = c.get('card_style')
        if style is not None and style not in ('filled', 'outlined'):
            errs.append(f"cards[{i}].card_style must be 'filled' or 'outlined', got {style!r}")
        for j, r in enumerate(c.get('rows') or []):
            ok = (isinstance(r, list) and len(r) == 2) or (isinstance(r, dict) and 'k' in r and 'v' in r)
            if not ok:
                errs.append(f'cards[{i}].rows[{j}] must be [key, value] or {{k, v, tone?}}')
    if n_primary > 1:
        errs.append(f'{n_primary} cards have primary:true; only the recommended one may be primary')
    return errs


def _row(r):
    if isinstance(r, dict):
        return r['k'], r['v'], r.get('tone')
    k, v = r
    if isinstance(v, dict):
        return k, v.get('v', ''), v.get('tone')
    return k, v, None


def _title_text(card):
    """Combine icon prefix with the raw title — icon is a character, not a separate element."""
    icon = (card.get('icon') or '').strip()
    title = card['title']
    return f'{icon} {title}' if icon else title


def _point(p):
    """Points may be plain strings or {text, icon?}. icon is rendered as a colored ✓/✗/etc. prefix."""
    if isinstance(p, dict):
        return p.get('text', ''), p.get('icon')
    return str(p), None


def _verdict_w(card):
    """Room the verdict pill takes from the title line, including the gap before it."""
    return measure(card['verdict'], T['type']['tiny']) + 18 + 8 if card.get('verdict') else 0


def _layout(card, w, below=False):
    """Title beside the verdict pill when it fits on one line; otherwise the pill gets its own row under the title,
    so a short title is never broken just to make room for a long verdict."""
    ty, inset = T['type'], T['space']['inset']
    inner = w - 2 * inset
    if card.get('id'):
        inner -= 2 * ID_R + 8  # reserve space for the circular ① badge
    title = _title_text(card)
    for size in (ty['card_title'], ty['head']) if card.get('verdict') and not below else ():
        tlines = wrap(title, size, inner - _verdict_w(card), True)
        if len(tlines) == 1:
            tsize = size
            break
    else:
        tsize, tlines = fit(title, inner, [ty['card_title'], ty['head'], 16], 2, bold=True)
        below = bool(card.get('verdict'))
    sub_placement = (card.get('subtitle') or '') and (card.get('sub_placement') or 'below')
    if sub_placement == 'right':
        # sub rides on the title's baseline as a right-side caption (LLM-series Aime style); stays on one line.
        sub = wrap(card['subtitle'], ty['small'], inner)[:1] if card.get('subtitle') else []
    else:
        sub = wrap(card['subtitle'], ty['small'], inner) if card.get('subtitle') else []
    pts = [(wrap(txt, ty['body'], inner - 32), icon) for txt, icon in (_point(p) for p in card.get('points') or [])]
    foot = wrap(card['foot'], ty['tiny'], inner) if card.get('foot') else []
    return tsize, tlines, sub, pts, foot, sub_placement, below


def draw(cv, spec, x, y, w):
    cards = spec['cards']
    n, gap, inset = len(cards), T['space']['gap'], T['space']['inset']
    row_h = cv.row_h(ROW_H)
    cw = (w - (n - 1) * gap) / n
    lays = [_layout(c, cw) for c in cards]
    if any(L[6] for L in lays):  # cards in a row put their verdicts in the same place
        lays = [_layout(c, cw, True) for c in cards]
    head_h = max(
        lh(L[0]) * len(L[1]) + (lh(T['type']['small']) * len(L[2]) if L[5] != 'right' else 0) + PILL_ROW * L[6]
        for L in lays
    )
    has_verdict = any(c.get('verdict') for c in cards)
    if has_verdict:
        head_h = max(head_h, lh(T['type']['card_title']) + 4)
    nrows = max(len(c.get('rows') or []) for c in cards)
    pts_h = max(sum(lh(T['type']['body']) * len(p) + 6 for p, _ in L[3]) for L in lays)
    foot_h = max(lh(T['type']['tiny']) * len(L[4]) for L in lays)
    body_top = inset + head_h + 14
    ch = body_top + 10 + nrows * row_h + pts_h + (foot_h + 10 if foot_h else 0) + inset - 4
    for i, (c, L) in enumerate(zip(cards, lays)):
        cx = x + i * (cw + gap)
        f = cv.use(c.get('tone'))
        primary = bool(c.get('primary') or c.get('highlight'))
        style = c.get('card_style') or 'filled'
        # C+C': pale wash for toned cards. When tone != base the card IS its own category
        # (the LLM-series Aime 1.0/1.5/2.0/2.5/3.0 evolution layout), so it reads
        # as family.bg2 regardless of whether it's primary. tone=base stays white.
        toned = (c.get('tone') not in (None, '', 'base'))
        body_fill = f['bg2'] if (primary or toned) else T['card']
        if style == 'outlined':
            border_color, border_w = f['main'], T['stroke']['emph']
        else:
            border_color, border_w = T['rule'], T['stroke']['panel']
        cv.rect(cx, y, cw, ch, body_fill, border_color,
                T['radius']['panel'], border_w, role='card')
        if primary:
            # the bar rides the straight part of the top edge only, so it never pokes past the rounded corners
            r = T['radius']['panel']
            cv.rect(cx + r, y - 1, cw - 2 * r, 3, f['main'], rx=1.5, role='colorline')
        tsize, tlines, sub, pts, foot, sub_placement, below = L
        verdict_w = 0
        if c.get('verdict') and not below:
            verdict_w, _ = cv.pill(cx + cw - inset, y + inset, c['verdict'], c.get('tone'), anchor='end')
        # Title row: optional circular id badge + (icon-prefixed) text
        title_x = cx + inset
        if c.get('id'):
            badge_cx = cx + inset + ID_R
            badge_cy = y + inset + ID_R - 2
            cv.circle(badge_cx, badge_cy, ID_R, T['card'], f['main'], T['stroke']['emph'], role='card-id')
            cv.text(badge_cx, badge_cy + 5, c['id'], T['type']['small'], f['ink'], bold=True, anchor='middle')
            title_x = cx + inset + 2 * ID_R + 8
        ty = y + inset - 2
        sub_beside = False
        if sub_placement == 'right' and sub:
            title_first_w = measure(tlines[0], tsize, True)
            title_end = title_x + title_first_w
            sub_w = measure(sub[0], T['type']['small'])
            room_right = cx + cw - inset - verdict_w - (8 if verdict_w else 0)
            sub_x = max(title_end + 12, room_right - sub_w)
            sub_beside = (sub_x + sub_w) <= room_right
            if sub_beside:
                first_line_h = lh(tsize)
                title_baseline_y = ty + (first_line_h + tsize * 0.7) / 2
                cv.text(sub_x, title_baseline_y, sub[0], T['type']['small'], T['sub'])
        ty += cv.lines(title_x, ty, tlines, tsize, f['ink'], bold=True, role='card-title')
        if below:
            cv.pill(title_x, ty + 4, c['verdict'], c.get('tone'))
            ty += PILL_ROW
        if not sub_beside:
            # the sub hangs under the title text, not under the id badge: badge left, text block right
            cv.lines(title_x, ty, sub, T['type']['small'], T['sub'])
        ly = y + body_top
        cv.line(cx + inset, ly, cx + cw - inset, ly, T['divider'], T['stroke']['thin'])
        ry = ly + 10
        for k, r in enumerate(c.get('rows') or []):
            key, val, tone = _row(r)
            mid = ry + row_h / 2 + 5
            cv.text(cx + inset, mid, key, T['type']['body'], T['sub'])
            if tone:
                # B: toned values read as a small chip on the row's right edge, echoing the verdict pill
                vf = cv.use(tone)
                vw = measure(val, T['type']['body'], True) + 16
                vh = T['type']['body'] + 10
                cv.rect(cx + cw - inset - vw, mid - vh / 2 - 3, vw, vh,
                        vf['bg2'], vf['line'], T['radius']['chip'], T['stroke']['thin'], role='value-chip')
                cv.text(cx + cw - inset - 8, mid, val, T['type']['body'], vf['ink'], bold=True, anchor='end')
            else:
                cv.text(cx + cw - inset, mid, val, T['type']['body'], T['ink'], bold=True, anchor='end')
            if k < nrows - 1:
                cv.line(cx + inset, ry + row_h, cx + cw - inset, ry + row_h, T['divider'])
            ry += row_h
        ry = ly + 10 + nrows * row_h + (6 if pts else 0)
        for p_lines, p_icon in pts:
            if p_icon:
                # R3: icon prefix replaces the gray bullet dot. Color the icon by tone family if it carries
                # sentiment (✓ → good, ✗ → risk); '-' is the "plain bullet" form (N8).
                if p_icon.startswith('✓'):
                    icon_color = T['families']['green']['ink']
                elif p_icon.startswith('✗'):
                    icon_color = T['families']['red']['ink']
                else:
                    icon_color = T['sub']
                cv.text(cx + inset + 4, ry + lh(T['type']['body']) / 2 + 5, p_icon, T['type']['body'], icon_color,
                        bold=True, role='point-icon')
            else:
                cv.circle(cx + inset + 4, ry + lh(T['type']['body']) / 2, 3, T['sub'])
            ry += cv.lines(cx + inset + 24, ry, p_lines, T['type']['body'], T['ink'], role='card-body') + 6
        if foot:
            cv.lines(cx + inset, y + ch - inset + 4 - lh(T['type']['tiny']) * len(foot), foot, T['type']['tiny'], T['sub'])
    y_bottom = y + ch
    if spec.get('footline'):
        # footline: a one-line summary row across all cards. Colored with the same palette as a callout
        # but slimmer — it answers "what should the reader take away?" after scanning the cards.
        # dashed:true switches to the "sub-total separator" style: dashed border, no left accent bar.
        fl = spec['footline']
        fl_text = fl if isinstance(fl, str) else fl.get('text', '')
        fl_tone = 'contrast' if isinstance(fl, str) else fl.get('tone', 'contrast')
        fl_label = None if isinstance(fl, str) else fl.get('label')
        fl_dashed = False if isinstance(fl, str) else bool(fl.get('dashed'))
        ffl = cv.use(fl_tone)
        fy = y_bottom + 18
        flines = wrap(fl_text, T['type']['body'], w - 40 - (measure(fl_label + '：', T['type']['body'], True) if fl_label else 0))
        fh = lh(T['type']['body']) * len(flines) + 16
        cv.rect(x, fy, w, fh, ffl['bg2'], ffl['line'], T['radius']['chip'], T['stroke']['thin'],
                dash=fl_dashed, role='footline')
        if not fl_dashed:
            cv.rect(x, fy, 4, fh, ffl['main'], rx=2)
        tx = x + 20
        if fl_label:
            lw = measure(fl_label + '：', T['type']['body'], True)
            cv.text(tx, fy + (fh + 4) / 2 + 2, fl_label + '：', T['type']['body'], ffl['ink'], bold=True)
            tx += lw
        cv.lines(tx, fy + 6, flines, T['type']['body'], T['ink'])
        y_bottom = fy + fh
    return y_bottom
