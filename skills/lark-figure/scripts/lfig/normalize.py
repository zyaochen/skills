"""Accept the near-miss spellings models actually write, deterministically, and say so.

One closed table: a key is renamed only if it is listed here as an alias of a field that exists in that exact place.
Nothing is guessed from content. Every rewrite becomes a note; an alias next to its canonical key is an error;
any other unknown key is left alone and reported with the closest real field name.
"""
import copy
import difflib

from .canvas import T

TYPES = {'flowchart': 'flow', 'pipeline': 'flow', 'process': 'flow', 'dag': 'graph', 'architecture': 'graph',
         'seq': 'sequence', 'sequencediagram': 'sequence', 'loop': 'cycle', 'flywheel': 'cycle', 'layer': 'layers',
         'comparison': 'compare', 'cards': 'compare', 'bar': 'bars', 'barchart': 'bars', 'gantt': 'timeline',
         'quadrant': 'matrix', '2x2': 'matrix', 'lines': 'line', 'linechart': 'line', 'trend': 'line',
         'roadmap': 'milestones', 'milestone': 'milestones', 'breakdown': 'tree', 'hierarchy': 'tree',
         'roof': 'roofline', 'rooflinechart': 'roofline', 'rooflinemodel': 'roofline'}
TONES = {'red': 'risk', 'green': 'good', 'blue': 'main', 'orange': 'contrast', 'purple': 'extra', 'gray': 'base',
         'grey': 'base', '红': 'risk', '绿': 'good', '蓝': 'main', '橙': 'contrast', '紫': 'extra', '灰': 'base',
         'primary': 'main', 'danger': 'risk', 'error': 'risk', 'success': 'good', 'neutral': 'base', 'muted': 'base'}
TOP = ({'type', 'title', 'subtitle', 'source', 'callout', 'legend', 'aspect', 'density', 'footline',
        'title_align', 'frameless', 'formula_banner'},
       {'title': ('headline', 'heading'), 'subtitle': ('sub_title', 'subheading', 'caption', 'description'),
        'source': ('sources', 'citation', 'credit')})
NAME = ('name', 'label', 'title')
EMPH = ('emph', 'highlight', 'emphasis', 'highlighted', 'emphasize')
SUB = ('sub', 'subtitle', 'desc', 'description', 'note')
ENDS = {'from': ('source', 'src', 'start'), 'to': ('target', 'dst', 'dest', 'end')}


def _f(name=None, emph=None, sub=None, also=(), **more):
    """(known keys, {canonical: aliases}) for one place in a spec. name/emph/sub pick that place's canonical word."""
    al = {c: tuple(a for a in group if a != c) for c, group in ((name, NAME), (emph, EMPH), (sub, SUB)) if c}
    al.update({k: tuple(v) for k, v in more.items()})
    known = set(al) | set(also)
    return known, {c: tuple(a for a in aliases if a not in known) for c, aliases in al.items()}


# type -> {path: fields}. A path walks dict keys; lists are entered element by element; a trailing * recurses.
PLACES = {
    'flow': {'steps': _f('title', 'emph', None, ('tone', 'lines', 'metric', 'note'),
                         lines=('desc', 'description', 'details')),
             'groups': _f('label', also=('tone', 'from', 'to'))},
    'graph': {'stages': _f('name', also=('nodes',)), 'stages.nodes': _f('title', 'emph', 'sub', ('tone', 'id')),
              'edges': _f(also=('dashed',), label=('text', 'name'), **ENDS)},
    'sequence': {'actors': _f('name', None, 'sub', ('tone',)), 'sections': _f('label', also=('at',)),
                 'messages': _f(also=('reply',), text=('label', 'message', 'msg', 'name'), **ENDS)},
    'cycle': {'steps': _f('title', 'emph', 'sub', ('tone',))},
    'layers': {'layers': _f('name', None, 'note', ('tone', 'items')), 'side': _f('title', also=('tone', 'items')),
               'layers.items': _f('label', 'emph', 'sub', ('tone',))},
    'compare': {'cards': _f('title', 'highlight', 'subtitle',
                            ('tone', 'verdict', 'rows', 'points', 'foot', 'id', 'icon', 'card_style', 'primary',
                             'sub_placement'))},
    'bars': {'rows': _f('label', None, 'note', ('tone', 'value', 'values')), 'series': _f('name', also=('tone',)),
             'ref': _f('label', also=('value',))},
    'timeline': {'lanes': _f('label', also=('spans',)), 'markers': _f('label', also=('tone', 'at')),
                 'lanes.spans': _f(None, 'emph', None, ('tone', 'start', 'end', 'dashed'),
                                   text=('label', 'name', 'title'))},
    'matrix': {'quadrants': _f('title', 'highlight', None, ('tone', 'items')), 'x': _f('label', also=('low', 'high')),
               'y': _f('label', also=('low', 'high'))},
    'line': {'series': _f('name', also=('tone', 'values', 'area', 'labels')),
             'notes': _f(also=('series', 'index', 'text'))},
    'milestones': {'items': _f('title', None, None, ('tone', 'when', 'lines', 'now'), when=('date', 'time'),
                               lines=('desc', 'description', 'details'), now=('current',))},
    'roofline': {'roofs': _f('name', also=('tone', 'dashed', 'ridge'), peak=('compute', 'peak_tflops', 'flops'),
                             bandwidth=('bw', 'mem_bw', 'memory_bandwidth')),
                 'points': _f('label', 'emph', None, ('tone',), x=('intensity', 'ai', 'oi'),
                              y=('tflops', 'perf', 'performance', 'throughput', 'achieved')),
                 'x': _f('title', also=('min', 'max')), 'y': _f('title', also=('min', 'max'))},
    'tree': {'root*': _f('label', 'emph', 'sub', ('tone', 'children'))},
    'table': {}, 'stack': {},
}
AS_LIST = ('lines', 'points')  # a single string here means a one-item list
MAX_DEPTH = 8


def _each(node, parts, where, depth=0):
    """Yield (where, dict) for every dict a path reaches."""
    if not parts:
        if isinstance(node, dict):
            yield where, node
        return
    key, star = parts[0].rstrip('*'), parts[0].endswith('*')
    kids = node.get(key) if isinstance(node, dict) else None
    for sub_where, kid in ([(f'{where}{key}[{i}]', k) for i, k in enumerate(kids)] if isinstance(kids, list)
                           else [(f'{where}{key}', kids)]):
        yield from _each(kid, parts[1:], sub_where + ('.' if parts[1:] else ''))
        if star and isinstance(kid, dict) and depth < MAX_DEPTH:
            yield from _each(kid, ['children*'], sub_where + '.', depth + 1)


def _rename(d, where, fields, notes, errs):
    known, aliases = fields
    for canon, names in aliases.items():
        found = [a for a in names if a in d]
        if found and (canon in d or len(found) > 1):
            errs.append(f'{where}: {", ".join([canon] * (canon in d) + found)!r} mean the same field here; '
                        f'keep only "{canon}"')
        elif found:
            d[canon] = d.pop(found[0])
            notes.append(f'{where}.{found[0]} read as "{canon}" (the field name here is "{canon}")')
    for k in AS_LIST:
        if k in known and isinstance(d.get(k), str):
            d[k] = [d[k]]
            notes.append(f'{where}.{k} was a string; read as a one-item list')
    for k in [k for k in d if k not in known and not str(k).startswith('_')]:
        near = difflib.get_close_matches(str(k), sorted(known), 1, 0.6) if k != 'tone' else []
        notes.append(f'{where}.{k} is not a field here and was ignored'
                     + (f'; did you mean "{near[0]}"?' if near else f'. Fields: {", ".join(sorted(known))}'))


def _tones(node, where, notes, errs, depth=0):
    """color → tone and color words → semantic tones, on every dict in the spec."""
    if depth > MAX_DEPTH + 4:
        return
    if isinstance(node, list):
        for i, v in enumerate(node):
            _tones(v, f'{where}[{i}]', notes, errs, depth + 1)
    if not isinstance(node, dict):
        return
    found = [k for k in ('color', 'colour') if k in node]
    if found and ('tone' in node or len(found) > 1):
        errs.append(f'{where}: both "tone" and "{found[0]}" are set; keep only "tone"')
    elif found:
        node['tone'] = node.pop(found[0])
        notes.append(f'{where}.{found[0]} read as "tone"')
    t = node.get('tone')
    if isinstance(t, str) and t not in T['tones']:
        word = t.strip().lower().rstrip('色')
        fixed = word if word in T['tones'] else TONES.get(word)
        if fixed:
            node['tone'] = fixed
            if fixed != t:
                notes.append(f'{where}.tone {t!r} read as "{fixed}"; tones are {", ".join(T["tones"])}')
    for k, v in node.items():
        if isinstance(v, (dict, list)):
            _tones(v, f'{where}.{k}' if where else str(k), notes, errs, depth + 1)


def _chart(spec, where, charts, notes, errs):
    t = spec.get('type')
    if isinstance(t, str) and t not in charts:
        fixed = t.strip().lower().replace('-', '').replace('_', '').replace(' ', '')
        fixed = fixed if fixed in charts else TYPES.get(fixed)
        if fixed:
            spec['type'] = fixed
            notes.append(f'{where}type {t!r} read as "{fixed}"')
    t = spec.get('type')
    if not isinstance(t, str) or t not in charts:
        return
    doc_only = {'note', 'limits', 'tips'}
    known = set(TOP[0]) | (set(charts[t].DOC['fields']) - doc_only) | ({'label', 'tone'} if where else set())
    _rename(spec, (where or 'spec.').rstrip('.'), (known, {} if where else TOP[1]), notes, errs)
    for path, fields in PLACES.get(t, {}).items():
        for sub_where, d in _each(spec, path.split('.'), where):
            _rename(d, sub_where, fields, notes, errs)
    if t == 'stack' and isinstance(spec.get('parts'), list):
        for i, p in enumerate(spec['parts']):
            if isinstance(p, dict):
                _chart(p, f'parts[{i}].', charts, notes, errs)


def normalize(spec, charts):
    """Return (spec, notes, errors). The input is never modified; a clean spec comes back equal, with no notes."""
    if not isinstance(spec, dict):
        return spec, [], []
    try:
        spec = copy.deepcopy(spec)
    except RecursionError:
        return spec, [], ['spec is nested too deeply; no figure needs more than a few levels']
    notes, errs = [], []
    _tones(spec, '', notes, errs)
    _chart(spec, '', charts, notes, errs)
    return spec, notes, errs
