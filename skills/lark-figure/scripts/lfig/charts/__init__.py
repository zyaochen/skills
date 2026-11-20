"""Chart registry. Every module exposes DOC (fields + a complete example), validate(spec) and draw(cv, spec, x, y, w)."""
from types import SimpleNamespace

from ..canvas import T
from . import (
    bars,
    compare,
    cycle,
    flow,
    graph,
    layers,
    line,
    matrix,
    milestones,
    roofline,
    sequence,
    table,
    timeline,
    tree,
)

CHARTS = {m.__name__.rsplit('.', 1)[-1]: m for m in
          (flow, graph, sequence, cycle, layers, compare, bars, timeline, matrix, table, line, roofline, milestones,
           tree)}


def _validate_stack(spec):
    parts = spec.get('parts')
    if not isinstance(parts, list) or not 2 <= len(parts) <= 3:
        return ['stack.parts must be a list of 2-3 sub-charts']
    errs = []
    for i, p in enumerate(parts):
        t = p.get('type')
        if t not in CHARTS:
            errs.append(f'parts[{i}].type {t!r} unknown; one of {", ".join(CHARTS)}')
            continue
        errs += [f'parts[{i}]: {e}' for e in CHARTS[t].validate(p)]
    return errs


def _draw_stack(cv, spec, x, y, w):
    cy = y
    for i, p in enumerate(spec['parts']):
        if p.get('label'):
            cv.rect(x, cy + 3, 4, 14, cv.use(p.get('tone', 'base'))['main'], rx=2)
            cv.text(x + 12, cy + 15, p['label'], T['type']['small'], T['sub'], bold=True)
            cy += 30
        cy = CHARTS[p['type']].draw(cv, p, x, cy, w)
        if i < len(spec['parts']) - 1:
            cy += T['space']['section_gap']
    return cy


_STACK_DOC = {
    'summary': 'Two or three sub-charts stacked vertically under one title (e.g. compare cards + a table).',
    'fields': {'parts': 'list (2-3) of {label?:str, tone?, type:<any other type>, ...that type\'s fields}'},
    'example': {
        'type': 'stack',
        'title': 'TP 吃机内带宽，DP 吃机间带宽，推荐配置让两者都不饱和',
        'subtitle': '上半部分是三种并行各自的通信特征，下半部分是推荐配置的实测',
        'source': '来源：本篇 sim_parallel.py 输出',
        'parts': [
            {'label': '三种并行的通信特征', 'type': 'compare', 'cards': [
                {'title': 'TP', 'subtitle': '张量并行', 'tone': 'main',
                 'rows': [['通信', '机内 NVLink'], ['带宽', '450 GB/s']]},
                {'title': 'PP', 'subtitle': '流水线并行', 'tone': 'contrast',
                 'rows': [['通信', '跨机点对点'], ['带宽', '50 GB/s']]},
                {'title': 'DP', 'subtitle': '数据并行', 'tone': 'good',
                 'rows': [['通信', 'AllReduce'], ['带宽', '50 GB/s']]}]},
            {'label': '推荐配置实测', 'type': 'bars', 'unit': ' ms', 'rows': [
                {'label': 'TP 通信', 'value': 12, 'tone': 'main'},
                {'label': 'PP 通信', 'value': 9, 'tone': 'contrast'},
                {'label': 'DP 通信', 'value': 19, 'tone': 'good'}]},
        ],
    },
}

CHARTS['stack'] = SimpleNamespace(DOC=_STACK_DOC, validate=_validate_stack, draw=_draw_stack)
