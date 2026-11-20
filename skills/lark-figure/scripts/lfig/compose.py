"""Turn a spec into a finished SVG: frame, judgment title, subtitle, optional callout/legend, chart body, source."""
from .canvas import Canvas, T, lh, measure, wrap
from .charts import CHARTS
from .charts._common import LayoutError, opt_tone
from .normalize import normalize


class SpecError(ValueError):
    def __init__(self, errors):
        super().__init__('\n'.join(errors))
        self.errors = errors


def validate(spec):
    if not isinstance(spec, dict):
        return ['spec must be a JSON object']
    errs = []
    t = spec.get('type')
    if t not in CHARTS:
        return [f'type {t!r} unknown; one of: {", ".join(CHARTS)}  (run `figure.py types`)']
    if not spec.get('title'):
        errs.append('title is required: one sentence stating the takeaway, e.g. "排队占了 60% 的时间"')
    else:
        inner = T['canvas']['width'] - 2 * T['canvas']['pad']
        if measure(spec['title'], T['title']['min'], True) > inner:
            cap = int(inner / (T['title']['min'] * T['measure']['bold_cjk']))
            errs.append(f'title too long for one line (≈{cap} CJK chars max at {T["title"]["min"]}px); shorten it, '
                        'move detail into subtitle')
    co = spec.get('callout')
    if co is not None and not (isinstance(co, dict) and co.get('text')):
        errs.append('callout must be {text, label?, tone?}')
    elif co:
        errs += opt_tone(co, 'callout')
    for i, it in enumerate(spec.get('legend') or []):
        if not isinstance(it, dict) or not it.get('label'):
            errs.append(f'legend[{i}] must be {{label, tone, style?}}')
        else:
            errs += opt_tone(it, f'legend[{i}]')
    aspect = spec.get('aspect')
    if aspect is not None and aspect not in T['canvas'].get('aspect_widths', {}):
        known = ', '.join(sorted(T['canvas'].get('aspect_widths', {'normal': 1200})))
        errs.append(f'aspect {aspect!r} unknown; one of: {known}')
    density = spec.get('density')
    if density is not None and density not in ('compact', 'normal', 'airy'):
        errs.append(f'density {density!r} unknown; one of: compact, normal, airy')
    return errs + CHARTS[t].validate(spec)


MAX_EMPHASIS = 2
OPTICAL_TOP = 0.4  # share of the spare height that goes above a short body


def _emphasised(node, depth=0):
    """How many items in the spec ask for emphasis. Depth is bounded by validation; the cap is only a backstop."""
    if depth > 12:
        return 0
    if isinstance(node, list):
        return sum(_emphasised(v, depth + 1) for v in node)
    if not isinstance(node, dict):
        return 0
    own = any(node.get(k) is True for k in ('emph', 'highlight', 'now'))
    return own + sum(_emphasised(v, depth + 1) for v in node.values())


def _header(cv, spec, canvas_w):
    c, inner = T['canvas'], canvas_w - 2 * T['canvas']['pad']
    centered = (spec.get('title_align') == 'center')
    title_x = canvas_w / 2 if centered else c['pad']
    anchor = 'middle' if centered else 'start'
    size = next(s for s in range(T['title']['size'], T['title']['min'] - 1, -1) if measure(spec['title'], s, True) <= inner)
    cv.text(title_x, T['title']['y'], spec['title'], size, T['ink'], bold=True, anchor=anchor, role='title')
    sub = spec.get('subtitle')
    if not sub:
        return T['body_top_no_sub']
    lines = wrap(sub, T['subtitle']['size'], inner)[:2]
    for i, ln in enumerate(lines):
        cv.text(title_x, T['subtitle']['y'] + i * lh(T['subtitle']['size']), ln, T['subtitle']['size'], T['sub'],
                anchor=anchor, role='subtitle')
    return T['body_top'] + (len(lines) - 1) * lh(T['subtitle']['size'])


def _callout(cv, co, x, y, w):
    f = cv.use(co.get('tone', 'contrast'))
    size, label = T['type']['body'], co.get('label', '结论')
    lw = measure(label + '：', size, True)
    lines = wrap(co['text'], size, w - 40 - lw)
    h = lh(size) * len(lines) + 24
    cv.rect(x, y, w, h, f['bg2'], f['line'], T['radius']['chip'], T['stroke']['thin'], role='callout')
    cv.rect(x, y, 4, h, f['main'], rx=2)
    cv.lines(x + 20, y + 12, [label + '：'], size, f['ink'], bold=True)
    cv.lines(x + 20 + lw, y + 12, lines, size, T['ink'])
    return y + h


def _formula_banner(cv, fb, x, y, w):
    """A wide formula banner: left title + center formula chip + trailing token chips.
    Matches the LLM-01 'P(x_t|x_<t)' banner layout."""
    f = cv.use(fb.get('tone', 'main'))
    size = T['type']['body']
    h = 64  # taller than a normal callout: formula chips need vertical room
    cv.rect(x, y, w, h, f['bg2'], f['line'], T['radius']['chip'], T['stroke']['thin'])
    # left title (e.g. '第 1 章 · 心智模型' as a pill)
    tx = x + 20
    if fb.get('label'):
        mf = cv.use(fb.get('label_tone', 'main'))
        lbl_w = measure(fb['label'], T['type']['small'], True) + 20
        cv.rect(tx, y + (h - 24) / 2, lbl_w, 24, mf['bg'],
                mf['line'], T['radius']['chip'], T['stroke']['thin'], role='banner-chip')
        cv.text(tx + lbl_w / 2, y + h / 2 + 5, fb['label'], T['type']['small'],
                mf['ink'], bold=True, anchor='middle')
        tx += lbl_w + 16
    # intro text
    intro = fb.get('intro', '')
    if intro:
        cv.lines(tx, y + (h - lh(size)) / 2, [intro], size, T['ink'])
        tx += measure(intro, size) + 24
    # formula chip
    if fb.get('formula'):
        fw = measure(fb['formula'], T['type']['head'], False) + 24
        cv.rect(tx, y + (h - 28) / 2, fw, 28, T['card'], T['rule'], T['radius']['chip'], T['stroke']['thin'], role='banner-chip')
        cv.text(tx + fw / 2, y + h / 2 + 6, fb['formula'], T['type']['head'], T['ink'], anchor='middle')
        tx += fw + 20
    # token chips (e.g. 今天 / 天气 / 很 → 「噢？好？」)
    tokens = fb.get('tokens') or []
    trailing = fb.get('trailing')
    for t in tokens:
        tw = measure(t, T['type']['small'], True) + 14
        cv.rect(tx, y + (h - 24) / 2, tw, 24, T['card'], T['rule'], T['radius']['chip'], T['stroke']['thin'], role='banner-chip')
        cv.text(tx + tw / 2, y + h / 2 + 5, t, T['type']['small'], T['ink'], anchor='middle')
        tx += tw + 8
    if trailing:
        # highlight chip at the end — the "next token" prediction
        tw = measure(trailing, T['type']['small'], True) + 16
        cv.rect(tx, y + (h - 24) / 2, tw, 24, f['bg'], f['main'], T['radius']['chip'], T['stroke']['emph'], role='banner-chip')
        cv.text(tx + tw / 2, y + h / 2 + 5, trailing, T['type']['small'], f['ink'], bold=True, anchor='middle')
    return y + h


def _legend(cv, items, x, y):
    size = T['type']['small']
    cx = x
    for it in items:
        f = cv.use(it.get('tone'))
        style = it.get('style', 'solid')
        if style == 'line':
            cv.line(cx, y + 8, cx + 18, y + 8, f['main'], 2.5)
            sw = 18
        elif style == 'dot':
            cv.circle(cx + 6, y + 8, 5, f['main'])
            sw = 12
        else:
            dashed = style == 'dashed'
            # swatches use the same soft border as the blocks they explain
            cv.rect(cx, y + 1, 14, 14, f['bg2'] if dashed else f['bg'], f['line'], 3, T['stroke']['panel'], dash=dashed)
            sw = 14
        cv.text(cx + sw + 8, y + 13, it['label'], size, T['sub'])
        cx += sw + 8 + measure(it['label'], size) + 28
    return y + 18


def _body(cv, spec, top, canvas_w):
    c = T['canvas']
    x, w = c['pad'], canvas_w - 2 * c['pad']
    y = top
    if spec.get('formula_banner'):
        y = _formula_banner(cv, spec['formula_banner'], x, y, w) + T['space']['gap']
    if spec.get('callout'):
        y = _callout(cv, spec['callout'], x, y, w) + T['space']['gap']
    if spec.get('legend'):
        y = _legend(cv, spec['legend'], x, y) + T['space']['gap']
    return CHARTS[spec['type']].draw(cv, spec, x, y, w)


def _canvas_width(spec):
    aspect = spec.get('aspect') or 'normal'
    return T['canvas'].get('aspect_widths', {}).get(aspect, T['canvas']['width'])


def _fits(spec, **change):
    """True when the same spec with `change` applied lays out under the height cap."""
    trial = dict(spec, **change)
    canvas_w = _canvas_width(trial)
    probe = Canvas(width=canvas_w, density=trial.get('density') or 'normal')
    try:
        bottom = _body(probe, trial, _header(probe, trial, canvas_w), canvas_w)
    except LayoutError:
        return False
    return bottom + T['footer_gap'] <= T['canvas']['max_height']


def build(spec):
    """Return (svg_text, notes). Raises SpecError with every problem found, phrased as a fix instruction."""
    spec, notes, errs = normalize(spec, CHARTS)
    errs = errs + validate(spec)
    if errs:
        raise SpecError(errs)
    loud = _emphasised(spec)
    if loud > MAX_EMPHASIS:
        notes.append(f'{loud} items are emphasised (emph / highlight / now); keep it to {MAX_EMPHASIS} so the one '
                     'that carries the title\'s claim stands out')
    c = T['canvas']
    canvas_w = _canvas_width(spec)
    density = spec.get('density') or 'normal'
    # pass 1 measures the body; pass 2 draws it, vertically centred when the figure is shorter than min_height
    probe = Canvas(width=canvas_w, density=density)
    top = _header(probe, spec, canvas_w)
    try:
        bottom = _body(probe, spec, top, canvas_w)
    except LayoutError as e:
        raise SpecError([str(e)]) from e
    height = max(c['min_height'], bottom + T['footer_gap'])
    # vertical centring when shorter than min_height is the right default for the 1200px-wide
    # canvas (asymmetric whitespace reads as wasteful); on narrow aspect the user explicitly
    # asked for a compact top-aligned look, so skip the centring and keep the layout tight.
    # The split is optical, not geometric: a little less room above than below keeps the body attached
    # to the title it proves instead of floating halfway down to the source line.
    cur_aspect = spec.get('aspect') or 'normal'
    if bottom + T['footer_gap'] < c['min_height'] and cur_aspect != 'narrow':
        dy = (height - T['footer_gap'] - bottom) * OPTICAL_TOP
    else:
        dy = 0
    cv = Canvas(width=canvas_w, density=density)
    if not spec.get('frameless'):
        cv.rect(0, 0, canvas_w, height, c['bg'], c['border'], c['radius'], role='frame')
    _header(cv, spec, canvas_w)
    _body(cv, spec, top + dy, canvas_w)
    notes += cv.notes
    src = spec.get('source') or T['source']['default']
    if not spec.get('source'):
        notes.append(f'no source given; wrote "{src}". Cite the paper/table/system if the numbers came from one')
    prefix = T['source']['prefix']
    if not src.startswith(prefix.rstrip('：:')):
        src = prefix + src
    cv.text(c['pad'], height - T['source']['bottom'], src, T['source']['size'], T['sub'], role='source')
    fams = cv.families
    if len(fams) > T['max_families']:
        notes.append(f'uses {len(fams)} color families {sorted(fams)}; max {T["max_families"]}. '
                     'Retone background items to "base"')
    if height > c['max_height']:
        # only offer a knob that really brings this figure under the cap: density scales compare/table rows and
        # nothing else, and whether a narrower canvas helps depends on the chart
        hints = []
        if density != 'compact' and _fits(spec, density='compact'):
            hints.append('add "density": "compact" to shrink row heights ~20%')
        if cur_aspect != 'narrow' and _fits(spec, aspect='narrow'):
            hints.append('add "aspect": "narrow" (1000px wide)')
        hints.append('split into two figures (preferred for big content)')
        raise SpecError([f'figure is {round(height)}px tall (max {c["max_height"]}); content would be clipped or '
                         f'square-filled to invisibility on the board. Options:\n  - ' + '\n  - '.join(hints)])
    return cv.svg(height), notes
