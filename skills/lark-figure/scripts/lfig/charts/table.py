"""table: a compact styled table with an optional highlighted column or row. Numbers right-aligned."""
import re

from ..canvas import T, lh, measure, wrap
from ._common import need_list

DOC = {
    'summary': 'Exact values across a few options × metrics where bars would lose precision. Keep ≤ 6 columns.',
    'fields': {
        'columns': 'list (2-6) of header strings; first column is the row label',
        'rows': 'list (1-12) of lists; a cell is a string/number or {text, tone?, bold?}',
        'highlight_col': 'optional int column index to emphasise (e.g. the recommended option)',
        'highlight_row': 'optional int row index to emphasise',
        'tone': 'optional tone of the highlight (default good)',
    },
    'example': {
        'type': 'table',
        'title': '推荐配置把显存从 90 GB 压到 1.5 GB，通信只多 25%',
        'subtitle': '64 卡训练 70B 模型，三项关键指标；绿色列是推荐配置',
        'source': '来源：本篇 sim_parallel.py 输出',
        'columns': ['指标', '纯 DP', 'PP8', 'TP8·PP2·DP4'],
        'rows': [
            ['显存 / 卡', {'text': '90 GB', 'tone': 'risk'}, '11 GB', '1.5 GB'],
            ['通信 / 步', '160 ms', '25 ms', '40 ms'],
            ['MFU', '24%', '18%', '35–45%'],
        ],
        'highlight_col': 3,
    },
}

ROW_H, HEAD_H, PAD = 42, 44, 18
NUMERIC = re.compile(r'^[\s~≈<>＜＞+\-−]*[\d.,]+([\s\-–~]+[\d.,]+)?\s*[%a-zA-Z/×xμ·\s]*$')


def validate(spec):
    errs = need_list(spec, 'columns', 2, 6) + need_list(spec, 'rows', 1, 12)
    n = len(spec.get('columns') or [])
    for i, r in enumerate(spec.get('rows') or []):
        if not isinstance(r, list) or len(r) != n:
            errs.append(f'rows[{i}] must have exactly {n} cells (one per column)')
    return errs


def _cell(c):
    if isinstance(c, dict):
        return str(c.get('text', '')), c.get('tone'), c.get('bold', False)
    return str(c), None, False


def _block(cv, x, y, w, h, fill, r=0, keep=''):
    """Filled block whose corners named in ``keep`` (tl tr bl br) follow radius r; the others are squared off again.

    Squaring uses r-sized patches in the corners only: the board takes any shape under a text for its container,
    so a patch must never reach the cell text.
    """
    cv.rect(x, y, w, h, fill, rx=r)
    for corner in ('tl', 'tr', 'bl', 'br') if r else ():
        if corner not in keep:
            cv.rect(x if corner[1] == 'l' else x + w - r, y if corner[0] == 't' else y + h - r, r, r, fill)


def draw(cv, spec, x, y, w):
    cols, rows = spec['columns'], spec['rows']
    size = T['type']['body']
    natural = [max([measure(cols[j], size, True)] + [measure(_cell(r[j])[0], size, True) for r in rows]) + 2 * PAD
               for j in range(len(cols))]
    natural = [max(96, n) for n in natural]
    if sum(natural) <= w:
        # spare width goes equally to every column so value columns stay evenly spaced
        widths = [n + (w - sum(natural)) / len(natural) for n in natural]
    else:
        widths = [n * w / sum(natural) for n in natural]
    numeric = [j > 0 and all(NUMERIC.match(_cell(r[j])[0]) for r in rows) for j in range(len(cols))]
    hc, hr = spec.get('highlight_col'), spec.get('highlight_row')
    hf = cv.use(spec.get('tone', 'good')) if hc is not None or hr is not None else None
    wrapped = [[wrap(_cell(c)[0], size, widths[j] - 2 * PAD, True) for j, c in enumerate(r)] for r in rows]
    heights = [max(cv.row_h(ROW_H), max(len(ls) for ls in row) * lh(size) + 18) for row in wrapped]
    total = HEAD_H + sum(heights)
    xs = [x]
    for cw in widths[:-1]:
        xs.append(xs[-1] + cw)
    cv.rect(x, y, w, total, T['card'], T['canvas']['border'], T['radius']['panel'], role='table')
    # header band stays neutral gray: the highlight's own band below tints its header cell, nothing else
    head_bg = T['families']['gray']['bg']
    cv.rect(x + 1, y + 1, w - 2, HEAD_H - 1, head_bg, rx=T['radius']['panel'] - 1)
    cv.rect(x + 1, y + HEAD_H - 12, w - 2, 12, head_bg)
    # a highlight is a tinted band of the table itself: it sits under the grid and follows the table's own corners
    inner_r = T['radius']['panel'] - 1
    if hc is not None:
        first, last = hc == 0, hc == len(cols) - 1
        cx = xs[hc] + (1 if first else 0)
        cw = widths[hc] - (1 if first else 0) - (1 if last else 0)
        r, side = (inner_r, 'l' if first else 'r') if first or last else (0, '')
        _block(cv, cx, y + 1, cw, total - 2, hf['bg2'], r, f't{side} b{side}')
        _block(cv, cx, y + 1, cw, HEAD_H - 1, hf['bg'], r, f't{side}')
    if hr is not None:
        ry0 = y + HEAD_H + sum(heights[:hr])
        bottom = hr == len(rows) - 1
        _block(cv, x + 1, ry0, w - 2, heights[hr] - (1 if bottom else 0), hf['bg2'], inner_r if bottom else 0, 'bl br')
    cv.line(x, y + HEAD_H, x + w, y + HEAD_H, T['canvas']['border'])
    for i in range(len(rows) - 1):
        ly = y + HEAD_H + sum(heights[:i + 1])
        cv.line(x + 1, ly, x + w - 1, ly, T['divider'])
    if hc is not None:
        for ex in ([] if first else [xs[hc]]) + ([] if last else [xs[hc] + widths[hc]]):
            cv.line(ex, y + 1, ex, y + total - 1, hf['line'], T['stroke']['thin'])
    if hr is not None:
        for ey in [ry0] + ([] if bottom else [ry0 + heights[hr]]):
            cv.line(x + 1, ey, x + w - 1, ey, hf['line'], T['stroke']['thin'])
    if hf:
        cv.rect(x, y, w, total, None, T['canvas']['border'], T['radius']['panel'])

    def anchor_x(j):
        return (xs[j] + widths[j] / 2, 'middle') if numeric[j] else (xs[j] + PAD, 'start')

    for j, c in enumerate(cols):
        tx, anchor = anchor_x(j)
        cv.text(tx, y + HEAD_H / 2 + 5, c, size, hf['ink'] if j == hc else T['ink'], True, anchor)
    ry = y + HEAD_H
    for i, r in enumerate(rows):
        for j, c in enumerate(r):
            _, tone, bold = _cell(c)
            emph = j == hc or i == hr
            color = cv.use(tone)['ink'] if tone else (hf['ink'] if emph else T['ink'])
            block = len(wrapped[i][j]) * lh(size)
            tx, anchor = anchor_x(j)
            cv.lines(tx, ry + (heights[i] - block) / 2, wrapped[i][j], size, color,
                     bold or emph or tone is not None, anchor)
        ry += heights[i]
    return y + total
