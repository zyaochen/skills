"""Offline tests for skills/lark-figure. Stdlib only; no network, no whiteboard-cli.

    python3 -m unittest discover -s dev/lark-figure -v
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(ROOT, 'skills', 'lark-figure')
sys.path.insert(0, os.path.join(SKILL, 'scripts'))

from lfig import lark
from lfig.canvas import NO_BREAK_BEFORE, T, _tokens, measure, pairs, wrap
from lfig.charts import CHARTS
from lfig.compose import SpecError, build, validate
from lfig.lint import lint, summarize
from lfig.normalize import PLACES, TONES, TOP, TYPES, _each, normalize

HERE = os.path.dirname(os.path.abspath(__file__))
LONG = '这是一段相当长的说明文字，包含 English words 和 numbers 12345，用来测试自动换行是否可靠'


def greedy_wrap(s, size, maxw, bold=False):
    """The 1.0 wrap, kept as the reference: 1.1 may move words between the last two lines but never adds a line."""
    lines = []
    for para in str(s).split('\n'):
        cur = ''
        for tok in _tokens(para):
            if measure(cur + tok, size, bold) <= maxw or not cur:
                cur += tok
            else:
                lines.append(cur.rstrip())
                cur = tok.lstrip()
            while measure(cur, size, bold) > maxw and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and measure(cur[:cut], size, bold) > maxw:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        lines.append(cur.rstrip())
    return lines


def stranded_orphans(text, size, maxw, bold):
    """Paragraphs that end on a one-character line although the line above could have spared its last word."""
    short, out = 2 * T['measure']['cjk'] * size + T['measure']['pad'], []
    for para in text.split('\n'):
        p = wrap(para, size, maxw, bold)
        if len(p) > 1 and len(p[-1]) == 1:
            toks = _tokens(p[-2])
            keep, moved = ''.join(toks[:-1]).rstrip(), toks[-1] + p[-1]
            if measure(keep, size, bold) >= short and measure(moved, size, bold) <= maxw:
                out.append(p)
    return out


def errors(svg):
    return [f for f in lint(svg) if f[0] == 'E']


def frame(body, h=480, title='排队占了六成时间，计算只占三成', source=True):
    src = f'<text x="40" y="{h - 24}" font-size="12" fill="#646A73">来源：测试</text>' if source else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" width="1200" height="{h}">'
            f'<rect x="0" y="0" width="1200" height="{h}" rx="16" fill="#FAFBFD" stroke="#DEE0E3"/>'
            f'<text x="40" y="58" font-size="28" font-weight="bold" fill="#1F2329">{title}</text>'
            f'{body}{src}</svg>')


class Examples(unittest.TestCase):
    def test_every_type_has_a_clean_example(self):
        for name, m in CHARTS.items():
            with self.subTest(name):
                svg, notes = build(copy.deepcopy(m.DOC['example']))
                self.assertEqual(errors(svg), [], name)
                self.assertEqual(notes, [], name)

    def test_build_is_deterministic(self):
        spec = CHARTS['flow'].DOC['example']
        self.assertEqual(build(copy.deepcopy(spec))[0], build(copy.deepcopy(spec))[0])

    def test_generated_docs_are_current(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'gen_spec_doc.py'), '--check'],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)


# messy, maximal input of the kind a weaker model writes; every one must still lay out cleanly
STRESS = {
    'flow_wrap': {'type': 'flow', 'title': '七个步骤的长流程会自动折成两行', 'subtitle': LONG, 'numbered': True,
                  'steps': [{'title': f'步骤 {i} 名称很长的 Step Title', 'lines': [LONG[:30], 'second line'],
                             'metric': f'{i * 10} ms', 'tone': ['main', 'base', 'risk'][i % 3]} for i in range(7)],
                  'labels': ['标签很长的边', 'x', '', 'y', '', 'z']},
    'flow_down': {'type': 'flow', 'direction': 'down', 'title': '纵向流程每一步都带注释说明',
                  'steps': [{'title': '第一步', 'note': LONG}, {'title': '第二步', 'lines': [LONG]},
                            {'title': '第三步', 'note': '短注释'}]},
    'layers_7': {'type': 'layers', 'title': '七层架构，每层模块数量不一样也能对齐', 'arrows': True,
                 'layers': [{'name': f'第 {i} 层名字较长', 'note': '备注',
                             'items': [f'模块 Module-{j} 名称' for j in range(i + 1)]} for i in range(7)],
                 'side': {'title': '横切关注点', 'items': ['安全审计与合规', '可观测性', '成本']}},
    'compare_4': {'type': 'compare', 'title': '四张卡片的对比，标题很长时自动缩小字号',
                  'cards': [{'title': f'方案 {c} Very Long Option Name', 'subtitle': LONG[:40],
                             'verdict': '推荐' if c == 'B' else None, 'highlight': c == 'B',
                             'tone': 'good' if c == 'B' else 'base',
                             'rows': [['指标一', '123,456 ms'], ['较长的指标名称', '99.9%'], ['第三项', '≈ 3×']],
                             'points': [LONG[:36], '短要点'], 'foot': '脚注：' + LONG[:30]} for c in 'ABCD']},
    'bars_16': {'type': 'bars', 'title': '十六行条形图，标签长短混排也对齐', 'unit': ' tok/s', 'sort': 'desc',
                'rows': [{'label': ('非常长的类别标签名称 Long Label ' if i % 3 == 0 else 'S') + str(i),
                          'value': (i + 1) * 137.5, 'tone': 'main' if i == 5 else 'base',
                          'note': '本文' if i == 5 else None} for i in range(16)],
                'ref': {'value': 1000, 'label': '目标'}},
    'bars_group': {'type': 'bars', 'title': '分组条形图，三组系列逐场景对比', 'unit': '%',
                   'series': [{'name': '基线', 'tone': 'base'}, {'name': '方案 A', 'tone': 'main'},
                              {'name': '方案 B', 'tone': 'contrast'}],
                   'rows': [{'label': f'场景 {i} 长名字', 'values': [30 + i, 50 + i * 3, 40 + i * 2]} for i in range(5)]},
    'bars_log': {'type': 'bars', 'title': '对数坐标下跨四个数量级也能看清', 'log': True,
                 'rows': [{'label': 'A', 'value': 1.2}, {'label': 'B', 'value': 35}, {'label': 'C', 'value': 980},
                          {'label': 'D', 'value': 12000, 'tone': 'risk'}]},
    'timeline_14': {'type': 'timeline', 'title': '十四条泳道的甘特图里标记线不穿字', 'axis': {'unit': '天'},
                    'lanes': [{'label': f'任务 {i} 名称', 'spans': [
                        {'start': i * 3, 'end': i * 3 + 8, 'text': '开发阶段', 'tone': 'main' if i in (0, 13) else 'base'},
                        {'start': i * 3 + 8, 'end': i * 3 + 11, 'text': '测试', 'tone': 'base', 'dashed': True}]}
                              for i in range(14)],
                    'markers': [{'at': 20, 'label': '里程碑一'}, {'at': 45, 'label': '发布', 'tone': 'good'}]},
    'matrix_long': {'type': 'matrix', 'title': '象限里内容很多时自动增高',
                    'x': {'label': '投入', 'low': '少', 'high': '多'}, 'y': {'label': '回报', 'low': '低', 'high': '高'},
                    'quadrants': [{'title': f'象限 {q}', 'items': [LONG[:20 + k * 5] for k in range(4)]}
                                  for q in range(4)]},
    'table_6': {'type': 'table', 'title': '六列十二行的表格里数字列居中对齐',
                'columns': ['名称', '指标 A', '指标 B', '较长的列名 C', 'D', 'E'],
                'rows': [[f'行 {i} ' + ('很长的行名称需要换行显示' if i % 4 == 0 else ''), f'{i * 1.5} ms', f'{i}%',
                          '文本内容', '≈ 3×', f'{i}–{i + 3} GB'] for i in range(12)],
                'highlight_row': 2, 'tone': 'main'},
    'line_4': {'type': 'line', 'title': '四条曲线交叉时端点标签自动避让',
               'x': {'labels': [str(2018 + i) for i in range(9)]}, 'y': {'unit': '%'},
               'series': [{'name': f'系列 {k} 名字', 'values': [10 + k * 2 + i * (3 - k) for i in range(9)],
                           'tone': ['main', 'contrast', 'good', 'base'][k], 'labels': k == 0} for k in range(4)]},
    'milestones_8': {'type': 'milestones', 'title': '八个里程碑交错排布，两端卡片不出界',
                     'items': [{'when': f'2026-0{i + 1}', 'title': f'里程碑 {i} 名称较长的标题文本',
                                'lines': [LONG[:24]], 'tone': 'good' if i < 4 else 'base', 'now': i == 4}
                               for i in range(8)]},
    'tree_16': {'type': 'tree', 'title': '十六个叶子的拆解树仍然对齐',
                'root': {'label': '总成本 100%', 'children': [
                    {'label': f'分支 {b} 名称', 'sub': '25%', 'children': [{'label': f'叶子 {b}-{l} 较长名称'}
                                                                         for l in range(4)]} for b in range(4)]}},
}


STRESS['graph_max'] = {
    'type': 'graph', 'title': '五个阶段二十条边的分支图仍然不穿字',
    'stages': [{'name': f'阶段 {s} 名称', 'nodes': [{'id': f'n{s}{j}', 'title': f'节点 {s}-{j} 名称较长 Long Node Title',
                                                'sub': '补充说明 sub text', 'tone': ['main', 'base', 'good'][j % 3],
                                                'emph': s == 2 and j == 1} for j in range(4)]} for s in range(5)],
    'edges': [{'from': f'n{s}{j}', 'to': f'n{s + 1}{(j + s) % 4}'} for s in range(4) for j in range(4)]
    + [{'from': 'n00', 'to': 'n20', 'label': '旁路'}, {'from': 'n10', 'to': 'n40'},
       {'from': 'n43', 'to': 'n03', 'label': '回写'}, {'from': 'n21', 'to': 'n22', 'label': '未命中'}]}
STRESS['graph_two'] = {
    'type': 'graph', 'title': '两个阶段的最小分支图也居中排布',
    'stages': [{'nodes': [{'id': 'a', 'title': '上游'}]},
               {'nodes': [{'id': 'b', 'title': '下游一'}, {'id': 'c', 'title': '下游二'}]}],
    'edges': [{'from': 'a', 'to': 'b', 'label': '同步'}, {'from': 'a', 'to': 'c', 'label': '异步', 'dashed': True},
              {'from': 'b', 'to': 'c'}, {'from': 'c', 'to': 'b'}, {'from': 'c', 'to': 'a', 'label': '回调'}]}
STRESS['graph_resid'] = {
    'type': 'graph', 'title': '残差块里两条旁路各走各的，主链箭头全是直线',
    'stages': [{'name': n, 'nodes': [{'id': i, 'title': i} for i in ids]} for n, ids in (
        ('input', ['x']), ('attn', ['ln1', 'attn']), ('y1', ['y1']), ('mlp', ['ln2', 'mlp']), ('out', ['y']))],
    'edges': [{'from': a, 'to': b} for a, b in (('x', 'ln1'), ('ln1', 'attn'), ('attn', 'y1'), ('y1', 'ln2'),
                                                ('ln2', 'mlp'), ('mlp', 'y'))]
    + [{'from': 'x', 'to': 'y1', 'label': 'shortcut', 'dashed': True},
       {'from': 'y1', 'to': 'y', 'label': 'shortcut', 'dashed': True}]}
SEQ_ACTORS = [f'服务 {i} 名称较长 Service' for i in range(6)]
STRESS['sequence_max'] = {
    'type': 'sequence', 'title': '六个参与者十四条消息的时序图里文字不碰生命线',
    'actors': [{'name': a, 'sub': '补充说明', 'tone': 'risk' if i == 2 else 'base'} for i, a in enumerate(SEQ_ACTORS)],
    'messages': [{'from': SEQ_ACTORS[i % 6], 'to': SEQ_ACTORS[(i * 5 + 1) % 6 if i % 4 else i % 6],
                  'text': '较长的消息文本 long message text' if i % 3 == 0 else f'调用 {i}', 'reply': i % 5 == 4}
                 for i in range(14)],
    'sections': [{'at': 0, 'label': '第一阶段'}, {'at': 7, 'label': '第二阶段名称较长'}]}
for _n in (3, 4, 8):
    STRESS[f'cycle_{_n}'] = {
        'type': 'cycle', 'title': f'{_n} 个环节的闭环首尾相接、箭头不穿字', 'center': '核心指标名称 North Star 99.9%',
        'steps': [{'title': f'环节 {i} 名称较长 Long Step Title', 'sub': LONG[:26], 'emph': i == 1,
                   'tone': 'good' if i == 1 else 'base'} for i in range(_n)]}
STRESS['table_first_col'] = dict(CHARTS['table'].DOC['example'], highlight_col=0)
STRESS['table_last_row'] = dict({k: v for k, v in CHARTS['table'].DOC['example'].items() if k != 'highlight_col'},
                                highlight_row=2)
STRESS['tree_shallow'] = {'type': 'tree', 'title': '三类成本里，GPU 租用占了八成', 'root': {'label': '月成本 120 万', 'children': [
    {'label': 'GPU 96 万', 'tone': 'risk', 'emph': True}, {'label': '存储 14 万'}, {'label': '网络 10 万'}]}}

# four cards whose long verdict pills push the titles onto a second line (a real GPU-series figure)
STRESS['compare_verdict'] = {'type': 'compare', 'title': '驻留块数取四项资源上限的最小值，本例被 warp 槽位卡在 4 块', 'cards': [
    {'title': t, 'subtitle': s, 'verdict': v, 'rows': [['硬件上限', a], ['本例需求', b]]}
    for t, s, v, a, b in (('warp 槽位', 'SM 算力上限 4 warp 槽位', '本例需求 64 warp', '64 warp', '16 warp'),
                          ('寄存器', 'SM 寄存器池', '本例 128x64', '256 KB', '32 KB / 块'),
                          ('共享内存', 'SMEM 228 KB', '本例 48 KB/块', '228 KB', '48 KB / 块'),
                          ('块数上限', '硬件调度器硬编码', '本例 32 块', '32 块', '4 块'))]}
STRESS['roofline_max'] = {
    'type': 'roofline', 'title': '十二个算子里只有两个越过了拐点，其余都卡在带宽上',
    'roofs': [{'name': 'FP8 1979T · 3.35 TB/s', 'peak': 1979, 'bandwidth': 3.35},
              {'name': 'BF16 989T · 3.35 TB/s', 'peak': 989, 'bandwidth': 3.35, 'dashed': False, 'tone': 'base'},
              {'name': '实测 786T · 3.02 TB/s', 'peak': 786, 'bandwidth': 3.02, 'ridge': False}],
    'points': [{'label': f'算子 {i}', 'x': x, 'y': y} for i, (x, y) in enumerate(
        [(0.06, 0.15), (0.125, 0.3), (0.25, 0.7), (0.5, 1.4), (1, 2.6), (1, 1.2), (2, 5), (4, 9),
         (16, 40), (64, 150), (600, 700), (1365, 760)])],
    'regions': ['带宽受限', '算力受限']}
STRESS['roofline_bare'] = {'type': 'roofline', 'title': 'H100 的拐点在 295 FLOP/Byte',
                           'roofs': [{'name': 'H100 SXM 989T · 3.35 TB/s', 'peak': 989, 'bandwidth': 3.35}]}
STRESS['roofline_on_roof'] = {
    'type': 'roofline', 'title': 'decode 的 GEMV 强度只有 1，batch 加到 256 才摸到拐点',
    'roofs': [{'name': 'A100 312T · 2.0 TB/s', 'peak': 312, 'bandwidth': 2.0}],
    'points': [{'label': f'batch {b}', 'x': b} for b in (1, 8, 64, 256)],
    'x': {'title': '算术强度（FLOP/Byte）'}, 'y': {'title': '吞吐上限（TFLOPS）'}}


def rects(svg, role):
    """(x, y, w, h) of every rect with this data-role."""
    root = ET.fromstring(svg)
    return [tuple(float(el.get(k)) for k in ('x', 'y', 'width', 'height'))
            for el in root.iter('{http://www.w3.org/2000/svg}rect') if el.get('data-role') == role]


class Polish(unittest.TestCase):
    def test_tree_uses_the_body_width_without_stretching(self):
        inner = T['canvas']['width'] - 2 * T['canvas']['pad']
        for name, spec, lo in (('example', CHARTS['tree'].DOC['example'], 0.8), ('tree_16', STRESS['tree_16'], 0.8),
                               ('shallow', STRESS['tree_shallow'], 0.45)):
            with self.subTest(name):
                svg, _ = build(copy.deepcopy(dict(spec, source='来源：测试')))
                nodes = rects(svg, 'node')
                span = max(x + w for x, _, w, _ in nodes) - min(x for x, _, _, _ in nodes)
                self.assertGreaterEqual(span, lo * inner)
                self.assertLessEqual(span, inner + 0.01)
                self.assertLessEqual(max(w for _, _, w, _ in nodes), 240)
                self.assertNotIn('<polygon', svg)

    def test_table_highlight_stays_inside_the_table(self):
        for name in ('table_first_col', 'table_last_row', 'table_6'):
            with self.subTest(name):
                svg, _ = build(copy.deepcopy(dict(STRESS[name], source='来源：测试')))
                (tx, ty, tw, th), = rects(svg, 'table')
                root = ET.fromstring(svg)
                fills = [tuple(float(el.get(k)) for k in ('x', 'y', 'width', 'height'))
                         for el in root.iter('{http://www.w3.org/2000/svg}rect')
                         if (el.get('fill') or '').upper() in (v.upper() for v in T['families']['green'].values())
                         or (el.get('fill') or '').upper() in (v.upper() for v in T['families']['blue'].values())]
                self.assertTrue(fills)
                outside = [f for f in fills if f[0] < tx or f[1] < ty or f[0] + f[2] > tx + tw or f[1] + f[3] > ty + th]
                self.assertEqual(outside, [])


    def test_graph_arrows_avoid_nodes_and_stay_orthogonal(self):
        for name in ('example', 'graph_max', 'graph_two', 'graph_resid'):
            with self.subTest(name):
                spec = CHARTS['graph'].DOC['example'] if name == 'example' else dict(STRESS[name], source='来源：测试')
                svg, _ = build(copy.deepcopy(spec))
                nodes = rects(svg, 'node')
                lines = [[tuple(float(v) for v in p.split(',')) for p in el.get('points').split()]
                         for el in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}polyline')]
                segs = [seg for pts in lines for seg in pairs(pts)]
                self.assertEqual([sg for sg in segs if sg[0][0] != sg[1][0] and sg[0][1] != sg[1][1]], [])
                through = [(sg, nd) for sg in segs for nd in nodes
                           if max(sg[0][0], sg[1][0]) > nd[0] + 1 and min(sg[0][0], sg[1][0]) < nd[0] + nd[2] - 1
                           and max(sg[0][1], sg[1][1]) > nd[1] + 1 and min(sg[0][1], sg[1][1]) < nd[1] + nd[3] - 1]
                self.assertEqual(through, [])


    def test_graph_rows_line_up_so_next_stage_arrows_run_straight(self):
        svg, _ = build(dict(STRESS['graph_resid'], source='来源：测试'))
        lines = [[tuple(float(v) for v in p.split(',')) for p in el.get('points').split()]
                 for el in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}polyline')]
        solid = [pts for pts, el in zip(lines, ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}polyline'))
                 if not el.get('stroke-dasharray')]
        self.assertEqual([pts for pts in solid if len(pts) != 2], [])
        # the bypass into y1 and the bypass out of it leave the node at clearly different points
        stubs = sorted(pts[0][0] for pts in lines if len(pts) == 4) + sorted(pts[-1][0] for pts in lines if len(pts) == 4)
        y1 = next(r for r in rects(svg, 'node') if r[0] < stubs[1] < r[0] + r[2] and r[0] < stubs[2] < r[0] + r[2])
        self.assertGreater(abs(stubs[1] - stubs[2]), y1[2] / 4)

    def test_graph_label_beside_a_vertical_arrow_clears_its_head(self):
        # the board reads a label that overlaps an arrowhead as the head's own text and reports text-overflow
        spec = dict(STRESS['graph_two'], source='来源：测试')
        spec['edges'] = [{'from': 'a', 'to': 'b'}, {'from': 'c', 'to': 'b', 'label': '积压消掉回灌'},
                         {'from': 'b', 'to': 'c', 'label': '未命中'}]
        root = ET.fromstring(build(spec)[0])
        heads = [[tuple(float(v) for v in p.split(',')) for p in el.get('points').split()]
                 for el in root.iter('{http://www.w3.org/2000/svg}polygon')]
        labels = [el for el in root.iter('{http://www.w3.org/2000/svg}text') if el.text in ('积压消掉回灌', '未命中')]
        self.assertEqual(len(labels), 2)
        for el in labels:
            x, y, tw = float(el.get('x')), float(el.get('y')), measure(el.text, 12)
            x0, x1 = (x - tw, x) if el.get('text-anchor') == 'end' else (x, x + tw)
            beside = [h for h in heads if min(px for px, _ in h) < x1 + 12 and max(px for px, _ in h) > x0 - 12]
            self.assertEqual(len(beside), 1)
            self.assertEqual([h for h in beside if min(py for _, py in h) < y + 7 and max(py for _, py in h) > y - 14], [])

    def test_sequence_labels_stay_clear_of_lifelines(self):
        for name, spec in (('example', CHARTS['sequence'].DOC['example']), ('max', STRESS['sequence_max'])):
            with self.subTest(name):
                svg, _ = build(copy.deepcopy(dict(spec, source='来源：测试')))
                root = ET.fromstring(svg)
                lifelines = [float(el.get('x1')) for el in root.iter('{http://www.w3.org/2000/svg}line')
                             if el.get('x1') == el.get('x2') and el.get('stroke-dasharray')]
                self.assertEqual(len(lifelines), len(spec['actors']))
                top = min(y + h for _, y, _, h in rects(svg, 'actor'))
                hit = []
                for el in root.iter('{http://www.w3.org/2000/svg}text'):
                    tx, ty, size = float(el.get('x')), float(el.get('y')), float(el.get('font-size'))
                    tw = measure(el.text, size, el.get('font-weight') == 'bold')
                    x0 = tx - tw if el.get('text-anchor') == 'end' else tx - tw / 2 if el.get('text-anchor') else tx
                    labels = [s['label'] for s in spec['sections']]
                    if el.get('data-role') is None and ty > top + 40 and el.text not in labels:
                        hit += [el.text for lx in lifelines if x0 < lx < x0 + tw]
                self.assertEqual(hit, [])

    def test_roofline_knee_and_points_sit_where_the_numbers_say(self):
        for name in ('example', 'roofline_max', 'roofline_on_roof'):
            with self.subTest(name):
                spec = CHARTS['roofline'].DOC['example'] if name == 'example' else dict(STRESS[name], source='来源：测试')
                root = ET.fromstring(build(copy.deepcopy(spec))[0])
                ns = '{http://www.w3.org/2000/svg}'
                roofs = [[tuple(float(v) for v in p.split(',')) for p in el.get('points').split()]
                         for el in root.iter(ns + 'polyline')]
                ridges = {float(el.get('x1')) for el in root.iter(ns + 'line')
                          if el.get('x1') == el.get('x2') and el.get('stroke-dasharray')}
                shown = [r for r in spec['roofs'] if r.get('ridge') is not False]
                knees = [pts[1][0] for pts, r in zip(roofs, spec['roofs']) if r.get('ridge') is not False]
                self.assertEqual(len(ridges), len(shown))
                for k in knees:
                    self.assertTrue(any(abs(k - rx) < 0.11 for rx in ridges))

                highest = min(roofs, key=lambda pts: min(y for _, y in pts))

                def under(cx, cy, roof=highest):  # svg y grows downwards
                    return all(cy >= ay + (by - ay) * (cx - ax) / (bx - ax) - 1
                               for (ax, ay), (bx, by) in pairs(roof) if ax <= cx <= bx and bx > ax)
                dots = [(float(el.get('cx')), float(el.get('cy'))) for el in root.iter(ns + 'circle')]
                self.assertEqual(len(dots), len(spec.get('points', [])))
                self.assertEqual([d for d in dots if not under(*d)], [])

    def test_compare_verdict_never_breaks_a_title_that_fits(self):
        ns = '{http://www.w3.org/2000/svg}'

        def parts(spec):
            svg, _ = build(copy.deepcopy(spec))
            titles = [el for el in ET.fromstring(svg).iter(ns + 'text') if el.get('data-role') == 'card-title']
            return rects(svg, 'card'), rects(svg, 'pill'), titles

        # a long verdict next to a short title: the pill drops to its own row, in every card of the row
        spec = dict(STRESS['compare_verdict'], source='来源：测试')
        cards, pills, titles = parts(spec)
        self.assertEqual(sorted(el.text for el in titles), sorted(c['title'] for c in spec['cards']))
        self.assertEqual(len(pills), len(spec['cards']))
        self.assertEqual(len({y for _, y, _, _ in pills}), 1)
        self.assertGreater(pills[0][1], max(float(el.get('y')) for el in titles))
        for (cx, _, cw, _), (px, _, pw, _) in zip(sorted(cards), sorted(pills)):
            self.assertGreaterEqual(px, cx)
            self.assertLessEqual(px + pw, cx + cw)

        # short verdicts keep the pill on the title line, at the right edge of the card
        spec = CHARTS['compare'].DOC['example']
        cards, pills, titles = parts(spec)
        self.assertEqual(len(pills), sum(1 for c in spec['cards'] if c.get('verdict')))
        first_title_y = min(float(el.get('y')) for el in titles)
        for px, py, pw, ph in pills:
            self.assertLess(py, first_title_y)
            self.assertTrue(any(abs(px + pw - (cx + cw - T['space']['inset'])) < 0.5 for cx, _, cw, _ in cards))

    def test_cycle_closes_the_loop(self):
        for n in (3, 4, 5, 8):
            with self.subTest(n=n):
                spec = CHARTS['cycle'].DOC['example'] if n == 5 else dict(STRESS[f'cycle_{n}'], source='来源：测试')
                svg, _ = build(copy.deepcopy(spec))
                heads = list(ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}polygon'))
                self.assertEqual(len(heads), n)
                self.assertEqual(len(rects(svg, 'step')), n)

    def test_short_milestone_cards_hug_their_content(self):
        svg, _ = build(copy.deepcopy(CHARTS['milestones'].DOC['example']))
        widths = {w for _, _, w, _ in rects(svg, 'milestone')}
        self.assertEqual(len(widths), 1)
        self.assertLess(widths.pop(), 240)

    def test_layer_chips_share_column_edges_when_labels_fit(self):
        svg, _ = build(copy.deepcopy(CHARTS['layers'].DOC['example']))
        by_row = {}
        for x, y, w, _ in rects(svg, 'layer-chip'):
            by_row.setdefault(y, []).append((x, w))
        four = [sorted(r) for r in by_row.values() if len(r) == 4]
        self.assertGreaterEqual(len(four), 2)
        self.assertTrue(all(r == four[0] for r in four))

    def test_timeline_emph_span_gets_the_strong_edge(self):
        spec = CHARTS['timeline'].DOC['example']
        _, notes, errs = normalize(spec, CHARTS)
        self.assertEqual((notes, errs), ([], []))
        svg, _ = build(copy.deepcopy(spec))
        widths = [float(el.get('stroke-width')) for el in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}rect')
                  if el.get('data-role') == 'span']
        self.assertEqual(widths.count(T['stroke']['emph']), 1)

    def test_compare_colorline_stays_off_the_rounded_corners(self):
        svg, _ = build(copy.deepcopy(CHARTS['compare'].DOC['example']))
        (lx, _, lw, _), = rects(svg, 'colorline')
        r = T['radius']['panel']
        self.assertTrue(any(cx + r <= lx and lx + lw <= cx + cw - r for cx, _, cw, _ in rects(svg, 'card')))

    def test_compare_header_makes_room_when_the_verdict_wraps_the_title(self):
        card = {'title': 'Beam Search (n=4)', 'id': '③', 'icon': '✗', 'subtitle': '翻译残留', 'verdict': 'chat 不实用',
                'rows': [['TTF', '1200 ms']]}
        spec = {'type': 'compare', 'title': '三种解码策略里 spec-decode 最快', 'source': '来源：测试',
                'cards': [dict(card, title=t) for t in ('Greedy', 'Spec Decode (k=4)')] + [card]}
        svg, _ = build(spec)
        root = ET.fromstring(svg)
        sub_y = max(float(el.get('y')) for el in root.iter('{http://www.w3.org/2000/svg}text') if el.text == '翻译残留')
        dividers = [float(el.get('y1')) for el in root.iter('{http://www.w3.org/2000/svg}line')
                    if el.get('y1') == el.get('y2') and float(el.get('y1')) > sub_y - 30]
        self.assertGreater(min(dividers), sub_y + 4)

    def test_timeline_short_span_labels_move_beside_the_span_or_become_a_note(self):
        spec = {'type': 'timeline', 'title': '短段的标签挪到旁边', 'source': '来源：测试',
                'axis': {'min': 0, 'max': 100},
                'lanes': [{'label': 'a', 'spans': [{'start': 0, 'end': 50, 'text': 'main'},
                                                   {'start': 50, 'end': 52, 'text': 'tail phase'}]},
                          {'label': 'b', 'spans': [{'start': 0, 'end': 49, 'text': 'x'},
                                                   {'start': 49, 'end': 51, 'text': 'squeezed in'},
                                                   {'start': 51, 'end': 100, 'text': 'y'}]}]}
        svg, notes = build(spec)
        texts = [el.text for el in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}text')]
        self.assertIn('tail phase', texts)
        self.assertNotIn('squeezed in', texts)
        self.assertTrue(any("'squeezed in'" in n for n in notes))


class Stress(unittest.TestCase):
    def test_stress_specs_lint_clean(self):
        for name, spec in STRESS.items():
            with self.subTest(name):
                spec = dict(spec, source='来源：压力测试')
                svg, _ = build(copy.deepcopy(spec))
                self.assertEqual(errors(svg), [], name)

    def test_a_tone_on_every_span_goes_over_the_color_budget(self):
        spec = dict(copy.deepcopy(STRESS['timeline_14']), source='来源：压力测试')
        for lane in spec['lanes']:
            lane['spans'][0]['tone'], lane['spans'][1]['tone'] = 'main', 'good'
        svg, _ = build(spec)
        self.assertEqual({code for _, code, _ in errors(svg)}, {'COLOR-OVERUSE', 'TONE-AS-CLASSIFIER'})

    def test_figure_over_the_height_cap_is_a_spec_error(self):
        spec = dict(copy.deepcopy(STRESS['tree_16']), source='来源：压力测试')
        for branch in spec['root']['children']:
            for leaf in branch['children']:
                leaf['sub'] = '6%'
        with self.assertRaises(SpecError) as ctx:
            build(spec)
        self.assertIn(f"max {T['canvas']['max_height']}", ctx.exception.errors[0])
        self.assertIn('split into two figures', ctx.exception.errors[0])
        # density only scales compare/table rows and a narrower canvas does not shorten a tree
        self.assertNotIn('"density"', ctx.exception.errors[0])
        self.assertNotIn('"aspect"', ctx.exception.errors[0])

    def test_over_height_error_offers_density_when_it_brings_the_figure_under_the_cap(self):
        spec = copy.deepcopy(CHARTS['compare'].DOC['example'])
        for card in spec['cards']:
            card['rows'] = [[f'指标 {i}', f'值 {i}'] for i in range(22)]
        with self.assertRaises(SpecError) as ctx:
            build(copy.deepcopy(spec))
        self.assertIn('"density": "compact"', ctx.exception.errors[0])
        self.assertNotIn('"aspect"', ctx.exception.errors[0])
        build(dict(spec, density='compact'))

    def test_tree_without_tones_stays_gray(self):
        svg, _ = build(dict(copy.deepcopy(STRESS['tree_16']), source='来源：压力测试'))
        blue = T['families'][T['tones']['main']]
        self.assertFalse([c for c in blue.values() if c in svg])
        svg, _ = build(dict(copy.deepcopy(STRESS['tree_16']), source='来源：压力测试',
                            root=dict(copy.deepcopy(STRESS['tree_16']['root']), tone='main')))
        self.assertIn('TONE-AS-CLASSIFIER', {code for _, code, _ in errors(svg)})


class Validation(unittest.TestCase):
    def test_messages_say_how_to_fix(self):
        cases = [
            ({'type': 'pie'}, 'unknown'),
            ({'type': 'flow', 'steps': [{'title': 'a'}, {'title': 'b'}]}, 'title is required'),
            ({'type': 'flow', 'title': '一' * 60, 'steps': [{'title': 'a'}, {'title': 'b'}]}, 'shorten'),
            ({'type': 'flow', 'title': '有判断的标题', 'steps': [{'title': 'a'}]}, 'Split'),
            ({'type': 'bars', 'title': '有判断的标题', 'rows': [{'label': 'a', 'value': 'x'}]}, 'number'),
            ({'type': 'bars', 'title': '有判断的标题', 'rows': [{'label': 'a', 'value': 1, 'tone': 'pink'}]}, 'tone'),
            ({'type': 'table', 'title': '有判断的标题', 'columns': ['a', 'b'], 'rows': [['1']]}, 'exactly 2'),
            ({'type': 'matrix', 'title': '有判断的标题', 'quadrants': []}, 'x must be'),
        ]
        for spec, needle in cases:
            with self.subTest(needle):
                errs = validate(spec)
                self.assertTrue(errs and any(needle in e for e in errs), errs)

    def test_build_raises_spec_error(self):
        with self.assertRaises(SpecError):
            build({'type': 'flow', 'title': '缺步骤的流程图示例标题'})

    def test_missing_source_is_filled_and_noted(self):
        spec = copy.deepcopy(CHARTS['bars'].DOC['example'])
        del spec['source']
        svg, notes = build(spec)
        self.assertIn(T['source']['default'], svg)
        self.assertTrue(any('no source' in n for n in notes))

    def test_non_finite_numbers_rejected(self):
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(bad=bad):
                spec = copy.deepcopy(CHARTS['bars'].DOC['example'])
                spec['rows'][0]['value'] = bad
                self.assertTrue(any('finite' in e for e in validate(spec)), validate(spec))

    def test_tree_limits_fail_as_messages_not_exceptions(self):
        chain = node = {'label': 'x'}
        for _ in range(3000):
            node['children'] = [{'label': 'x'}]
            node = node['children'][0]
        cases = [
            (chain, 'depth > 4'),
            ({'label': 'x', 'children': [{'label': str(i)} for i in range(13)]}, 'max 12'),
            ({'label': 'x'}, 'root.children is required'),
            ({'label': 'x', 'children': ['just a string']}, 'must be {label'),
            ({'label': 'x', 'children': {'label': 'not a list'}}, 'must be a list'),
        ]
        for root, needle in cases:
            with self.subTest(needle):
                errs = validate({'type': 'tree', 'title': '边界输入要报错而不是崩溃', 'root': root})
                self.assertTrue(any(needle in e for e in errs), errs)

    def test_graph_rejects_what_it_cannot_route(self):
        def graph(stages=None, edges=None):
            base = copy.deepcopy(CHARTS['graph'].DOC['example'])
            return dict(base, stages=stages or base['stages'], edges=edges or base['edges'])

        def one(i):
            return {'nodes': [{'id': f's{i}', 'title': f'节点 {i}'}]}

        def chain(*hops):
            return [{'from': f's{a}', 'to': f's{b}'} for a, b in hops]

        five, dup = [one(i) for i in range(5)], graph()
        dup['stages'][1]['nodes'][1]['id'] = 'gw'
        cases = [
            (dup, 'already used'),
            (graph(edges=[{'from': 'gw', 'to': 'nowhere'}]), "no node has id 'nowhere'"),
            (graph(edges=[{'from': 'gw'}]), 'no node has id None'),
            (graph(edges=[{'from': 'gw', 'to': 'gw'}]), 'self-loop'),
            (graph(edges=[{'from': 'cache', 'to': 'spot'}]), 'not neighbours'),
            (graph(edges=['gw -> mon']), 'must be {from:id, to:id}'),
            (graph(stages=[one(i) for i in range(6)]), 'allowed 2-5'),
            (graph(stages=[one(0), {'nodes': [{'id': f'x{j}', 'title': 'x'} for j in range(5)]}]), '1-4 nodes'),
            (graph(stages=[one(0), {'nodes': ['just a name']}]), 'must be {id:str'),
            (graph(stages=five, edges=chain((0, 2), (0, 3), (0, 4), (1, 3), (1, 4))), 'skip a stage'),
            (graph(stages=five, edges=chain((4, 0), (3, 0), (2, 0), (4, 1))), 'earlier stage'),
        ]
        for spec, needle in cases:
            with self.subTest(needle):
                errs = validate(spec)
                self.assertTrue(any(needle in e for e in errs), errs)

    def test_sequence_and_cycle_reject_bad_input_with_a_fix(self):
        seq, cyc = CHARTS['sequence'].DOC['example'], CHARTS['cycle'].DOC['example']
        cases = [
            (dict(seq, actors=['只有一个']), 'allowed 2-6'),
            (dict(seq, actors=['网关', '网关', '调度器']), 'appears twice'),
            (dict(seq, messages=[{'from': '客户端', 'to': '数据库', 'text': '查询'}]), "'数据库' is not an actor"),
            (dict(seq, messages=[{'from': '客户端', 'to': '网关'}]), 'messages[0].text is required'),
            (dict(seq, messages=['客户端 -> 网关']), 'must be {from, to, text'),
            (dict(seq, sections=[{'at': 99, 'label': 'x'}]), 'index of the section'),
            (dict(seq, sections=[{'at': True, 'label': 'x'}]), 'index of the section'),
            (dict(cyc, steps=cyc['steps'][:2]), 'allowed 3-8'),
            (dict(cyc, steps=['a', 'b', 'c']), 'must be {title'),
            (dict(cyc, steps=[{'sub': 'x'}] * 3), 'steps[0].title is required'),
        ]
        for spec, needle in cases:
            with self.subTest(needle):
                errs = validate(spec)
                self.assertTrue(any(needle in e for e in errs), errs)
        long_msg = dict(seq, sections=[], messages=[{'from': '客户端', 'to': '网关', 'text': LONG * 2}])
        for spec, needle in ((long_msg, 'messages[0].text'),
                             (dict(cyc, center=LONG * 2), 'center is too long')):
            with self.subTest(needle), self.assertRaises(SpecError) as ctx:
                build(copy.deepcopy(spec))
            self.assertIn(needle, ctx.exception.errors[0])

    def test_roofline_rejects_impossible_and_unplottable_numbers(self):
        base = copy.deepcopy(CHARTS['roofline'].DOC['example'])
        cases = {
            # the old GPU-02 figure drew ReLU at 8 TFLOPS with intensity 0.06: a roof of 0.2 TFLOPS there
            'above the roof': ({'points': [{'label': 'ReLU 64M', 'x': 0.06, 'y': 8}]}, "nothing runs above its roof"),
            'zero on a log axis': ({'points': [{'label': 'k', 'x': 0, 'y': 1}]}, 'positive number (log axis)'),
            'no intensity': ({'points': [{'label': 'k', 'y': 1}]}, 'points[0].x (arithmetic intensity) is required'),
            'bad roof': ({'roofs': [{'name': 'r', 'peak': -1, 'bandwidth': 3}]}, 'roofs[0].peak must be above 0'),
            'axis order': ({'x': {'min': 100, 'max': 10}}, 'x.min must be below x.max'),
            'regions shape': ({'regions': '带宽受限'}, 'regions must be [left label, right label]'),
            'too many points': ({'points': [{'label': str(i), 'x': 1} for i in range(13)]}, 'at most 12'),
        }
        for name, (patch, msg) in cases.items():
            with self.subTest(name):
                with self.assertRaises(SpecError) as cm:
                    build(dict(base, **patch))
                self.assertTrue(any(msg in e for e in cm.exception.errors), cm.exception.errors)
        with self.assertRaises(SpecError) as cm:
            build(dict(base, points=[{'label': 'k', 'x': 1e-9, 'y': 1e-9}]))
        self.assertIn('decades', cm.exception.errors[0])

    def test_graph_label_without_room_is_a_spec_error(self):
        spec = copy.deepcopy(CHARTS['graph'].DOC['example'])
        spec['edges'][3]['label'] = '缓存未命中时才把请求转给 GPU 推理池继续处理并记录一次回源' * 3
        with self.assertRaises(SpecError) as ctx:
            build(spec)
        self.assertIn('edges[3].label', ctx.exception.errors[0])
        self.assertIn('shorten', ctx.exception.errors[0])

    def test_too_many_families_is_noted(self):
        spec = copy.deepcopy(CHARTS['bars'].DOC['example'])
        spec['rows'] = [{'label': t, 'value': 1, 'tone': t} for t in ('main', 'contrast', 'good', 'risk')]
        # the cap lives in theme.json; pin it so the note is tested whatever the theme currently allows
        with mock.patch.dict(T, max_families=3):
            _, notes = build(spec)
        self.assertTrue(any('color families' in n and 'max 3' in n for n in notes))


class Lint(unittest.TestCase):
    def codes(self, svg):
        return {c for _, c, _ in lint(svg)}

    def test_clean_frame(self):
        self.assertEqual(errors(frame('')), [])

    def test_detects_each_rule(self):
        cases = {
            'FORBID': frame('<filter id="f"/>'),
            'TRANSFORM': frame('<g transform="skewX(10)"></g>'),
            'LT': frame('<text x="40" y="200" font-size="14" fill="#1F2329">a &lt; b</text>'),
            'PALETTE': frame('<rect x="100" y="200" width="80" height="40" fill="#123456"/>'),
            'DARK': frame('<text x="40" y="200" font-size="14" fill="#FFFFFF">白字</text>'),
            'SOURCE': frame('', source=False),
            'TITLE': frame('', title='') .replace('font-size="28" font-weight="bold"', 'font-size="18"'),
            'FONT': frame('<text x="40" y="200" font-size="10" fill="#1F2329">小字</text>'),
            'OVERLAP': frame('<text x="40" y="200" font-size="14" fill="#1F2329">重叠文字一</text>'
                             '<text x="44" y="202" font-size="14" fill="#1F2329">重叠文字二</text>'),
            'SPILL': frame('<rect x="100" y="180" width="60" height="40" fill="#FFFFFF" stroke="#DEE0E3"/>'
                           '<text x="110" y="205" font-size="14" fill="#1F2329">这段文字比框宽很多</text>'),
            'CROSS': frame('<text x="300" y="200" font-size="14" fill="#1F2329">被穿过的文字</text>'
                           '<line x1="250" y1="195" x2="500" y2="195" stroke="#8F959E" stroke-width="2"/>'),
            'MARGIN': frame('<rect x="5" y="200" width="100" height="40" fill="#FFFFFF" stroke="#DEE0E3"/>'),
            'CANVAS': frame('<text x="1150" y="200" font-size="14" fill="#1F2329">出界的长文字内容</text>'),
            'TITLE-LABEL': frame('', title='系统架构图'),
        }
        for code, svg in cases.items():
            with self.subTest(code):
                self.assertIn(code, self.codes(svg))

    def test_line_hidden_behind_opaque_block_is_not_a_cross(self):
        svg = frame('<line x1="250" y1="195" x2="500" y2="195" stroke="#8F959E" stroke-width="2"/>'
                    '<rect x="280" y="170" width="200" height="40" fill="#E1EAFF" stroke="#3370FF"/>'
                    '<text x="300" y="195" font-size="14" fill="#1F2329">盖住线的块</text>')
        self.assertNotIn('CROSS', self.codes(svg))

    def test_four_families_rejected(self):
        body = ''.join(f'<rect x="{100 + i * 100}" y="200" width="80" height="40" fill="{c}"/>'
                       for i, c in enumerate(('#3370FF', '#FF8800', '#34C724', '#F54A45')))
        with mock.patch.dict(T, max_families=3):
            self.assertIn('FAMILIES', self.codes(frame(body)))

    def test_summary_shape(self):
        s = summarize(lint(frame('')))
        self.assertTrue(s['ok'])
        self.assertEqual(s['errors'], 0)


class Measure(unittest.TestCase):
    def test_bold_is_wider(self):
        self.assertGreater(measure('推荐配置', 16, True), measure('推荐配置', 16))

    def test_matches_board_probe(self):
        # widths whiteboard-cli reported for these strings (text_shape.width); stay within 6% and never under 3%
        for s, size, bold, board in (('中文测试中文测试中文测试', 16, False, 202), ('中文测试中文测试中文测试', 16, True, 239),
                                     ('abcdefghijklmnopqrst', 14, False, 153), ('01234567890123456789', 14, True, 206),
                                     ('ABCDEFGHIJKLMNOPQRST', 20, False, 266)):
            with self.subTest(s=s, bold=bold):
                est = measure(s, size, bold)
                self.assertGreater(est, board * 0.97)
                self.assertLess(est, board * 1.06)

    def test_wrap_keeps_punctuation_off_line_start(self):
        for ln in wrap(LONG * 3, 14, 200)[1:]:
            self.assertNotIn(ln[:1], '，。、；：）')

    def test_wrap_exact_results(self):
        m = measure('FlashAttention-2', 14)
        cases = [
            # a width derived from the measured width must not wrap its own text (float round-trip)
            (('FlashAttention-2', 14, (m + 20) - 20), ['FlashAttention-2']),
            # no orphan last line when the line above can spare a word
            (('整段 prompt 一次前向', 14, 153.84), ['整段 prompt 一次', '前向']),
            (('use the new cache x', 14, measure('use the new cache ', 14) + 0.5), ['use the new', 'cache x']),
            (('缓存命中后直接返回 ok', 14, measure('缓存命中后直接返回 ', 14) + 0.5), ['缓存命中后直接返', '回 ok']),
            # ... but never across an explicit newline, and never by stranding the line above instead
            (('第一段内容\n向', 14, 400), ['第一段内容', '向']),
            (('AB CD E', 14, measure('AB CD ', 14) + 0.5), ['AB CD', 'E']),
            (('中文字', 14, measure('中文', 14) + 1), ['中文', '字']),
            (('', 14, 100), ['']),
        ]
        for args, want in cases:
            with self.subTest(args[0]):
                self.assertEqual(wrap(*args), want)

    def test_wrap_properties(self):
        texts = [LONG, LONG * 2, '整段 prompt 一次前向', 'The quick brown fox jumps over the lazy dog',
                 '首 token 时延（TTFT）下降 40%，吞吐不变。', 'vLLM、SGLang 和 TGI 的对比：见下表', 'a b c d e f g h i j k l m n',
                 'Supercalifragilisticexpialidocious 是一个很长的单词', '第一段\n第二段内容稍微长一些\n三']
        for text in texts:
            for size, maxw, bold in ((14, 90, False), (14, 153.84, False), (18, 200, True), (12, 64, False)):
                with self.subTest(text=text[:16], maxw=maxw):
                    lines, ref = wrap(text, size, maxw, bold), greedy_wrap(text, size, maxw, bold)
                    self.assertEqual(len(lines), len(ref))
                    self.assertEqual(''.join(''.join(lines).split()), ''.join(text.split()))
                    latin = [w for w in text.replace('\n', ' ').split(' ') if w.isascii() and w]
                    fits = [w for w in latin if measure(w, size, bold) <= maxw]
                    self.assertEqual([w for w in fits if not any(w in ln for ln in lines)], [])
                    fused = [latin[i] + latin[i + 1] for i in range(len(latin) - 1)]
                    fused = [f for f in fused if f not in text]
                    self.assertEqual([f for f in fused if any(f in ln for ln in lines)], [])
                    wide = [ln for ln in lines if measure(ln, size, bold) > maxw + 0.01 and len(_tokens(ln)) > 1]
                    self.assertEqual(wide, [])
                    self.assertEqual([ln for ln in lines[1:] if ln[:1] in NO_BREAK_BEFORE and ln not in ref], [])
                    self.assertEqual(stranded_orphans(text, size, maxw, bold), [])


class Normalize(unittest.TestCase):
    def test_clean_specs_pass_through_untouched(self):
        for name, m in CHARTS.items():
            with self.subTest(name):
                before = copy.deepcopy(m.DOC['example'])
                self.assertEqual(normalize(m.DOC['example'], CHARTS), (before, [], []))
                self.assertEqual(m.DOC['example'], before)

    def test_every_alias_in_the_table_is_read_as_its_field(self):
        tried = 0
        for ctype, places in PLACES.items():
            for path, (_, aliases) in places.items():
                for canon, names in aliases.items():
                    spec = copy.deepcopy(CHARTS[ctype].DOC['example'])
                    hit = next((d for _, d in _each(spec, path.split('.'), '') if canon in d), None)
                    for alias in names if hit else ():
                        with self.subTest(type=ctype, path=path, alias=alias):
                            messy = copy.deepcopy(CHARTS[ctype].DOC['example'])
                            d = next(d for _, d in _each(messy, path.split('.'), '') if canon in d)
                            d[alias] = d.pop(canon)
                            fixed, notes, errs = normalize(messy, CHARTS)
                            self.assertEqual((fixed, errs), (CHARTS[ctype].DOC['example'], []))
                            self.assertTrue(any(f'{alias} read as "{canon}"' in n for n in notes), notes)
                            tried += 1
        self.assertGreater(tried, 60)

    def test_top_level_type_and_tone_spellings(self):
        ex = CHARTS['flow'].DOC['example']
        for canon, names in TOP[1].items():
            for alias in names:
                with self.subTest(alias=alias):
                    messy = {(alias if k == canon else k): v for k, v in ex.items()}
                    self.assertEqual(normalize(messy, CHARTS)[0], ex)
        for word, ctype in list(TYPES.items()) + [('Flow', 'flow'), (' BARS ', 'bars'), ('bar-chart', 'bars')]:
            with self.subTest(type=word):
                self.assertEqual(normalize({'type': word}, CHARTS)[0]['type'], ctype)
        for word, tone in list(TONES.items()) + [('Red', 'risk'), ('红色', 'risk'), (' GOOD ', 'good')]:
            for key in ('tone', 'color', 'colour'):
                with self.subTest(tone=word, key=key):
                    messy = {'type': 'bars', 'rows': [{'label': 'a', 'value': 1, key: word}]}
                    fixed, notes, errs = normalize(messy, CHARTS)
                    self.assertEqual((fixed['rows'][0], errs), ({'label': 'a', 'value': 1, 'tone': tone}, []))
                    self.assertTrue(notes)

    def test_alias_next_to_its_field_is_an_error_not_a_guess(self):
        base = CHARTS['flow'].DOC['example']
        for patch, needle in (({'name': '别名'}, 'keep only "title"'), ({'color': 'red'}, 'keep only "tone"'),
                              ({'highlight': True, 'emph': True}, 'keep only "emph"')):
            with self.subTest(needle):
                spec = copy.deepcopy(base)
                spec['steps'][1].update(patch)
                with self.assertRaises(SpecError) as ctx:
                    build(spec)
                self.assertTrue(any(needle in e for e in ctx.exception.errors), ctx.exception.errors)

    def test_unknown_field_is_reported_with_the_nearest_name_and_left_alone(self):
        spec = copy.deepcopy(CHARTS['flow'].DOC['example'])
        spec['steps'][0]['metirc'] = '3 ms'
        spec['paragraph'] = '解释文字'
        fixed, notes, errs = normalize(spec, CHARTS)
        self.assertEqual((fixed, errs), (spec, []))
        self.assertTrue(any('steps[0].metirc' in n and 'did you mean "metric"' in n for n in notes), notes)
        self.assertTrue(any('spec.paragraph' in n and 'ignored' in n for n in notes), notes)

    def test_tone_where_nothing_is_colored_is_reported(self):
        spec = copy.deepcopy(CHARTS['graph'].DOC['example'])
        spec['edges'][0]['tone'] = 'good'
        notes = normalize(spec, CHARTS)[1]
        self.assertEqual(notes, ['edges[0].tone is not a field here and was ignored. Fields: dashed, from, label, to'])

    def test_messy_spec_draws_the_same_figure_as_the_clean_one(self):
        clean = {'type': 'flow', 'title': '排队占了六成时间，计算只占三成', 'subtitle': '大号数字是 p50', 'source': '线上 trace',
                 'steps': [{'title': '网关', 'tone': 'base', 'lines': ['鉴权']},
                           {'title': '排队', 'tone': 'risk', 'emph': True, 'metric': '120 ms'},
                           {'title': '计算', 'tone': 'good', 'lines': ['一次前向']}]}
        messy = {'type': 'Flowchart', 'headline': clean['title'], 'caption': clean['subtitle'],
                 'sources': clean['source'],
                 'steps': [{'name': '网关', 'color': 'gray', 'desc': '鉴权'},
                           {'label': '排队', 'tone': 'Red', 'highlight': True, 'metric': '120 ms'},
                           {'title': '计算', 'colour': '绿色', 'lines': '一次前向'}]}
        before = copy.deepcopy(messy)
        self.assertEqual(build(messy)[0], build(clean)[0])
        self.assertEqual(messy, before)
        self.assertEqual(build(clean)[1], [])
        self.assertGreaterEqual(len(build(messy)[1]), 8)

    def test_hostile_nesting_is_a_message(self):
        chain = node = {'label': 'x'}
        for _ in range(3000):
            node['children'] = [{'label': 'x'}]
            node = node['children'][0]
        with self.assertRaises(SpecError):
            build({'type': 'tree', 'title': '边界输入要报错而不是崩溃', 'root': chain})

    def test_too_much_emphasis_is_noted(self):
        spec = copy.deepcopy(CHARTS['flow'].DOC['example'])
        self.assertEqual(build(copy.deepcopy(spec))[1], [])
        for s in spec['steps']:
            s['emph'] = True
        self.assertTrue(any('4 items are emphasised' in n for n in build(spec)[1]))


class Lark(unittest.TestCase):
    def test_token_must_be_plain(self):
        for bad in ('abc\n', 'a/b', '..', '../x', 'a b', '', None, 123):
            with self.subTest(bad=bad), self.assertRaises(lark.ToolError):
                lark.check_token(bad)
        self.assertEqual(lark.check_token('ok_Tok-1'), 'ok_Tok-1')

    def test_bad_token_never_reaches_a_command_or_the_filesystem(self):
        with tempfile.TemporaryDirectory() as d:
            svg = os.path.join(d, 'x.svg')
            with open(svg, 'w', encoding='utf-8') as f:
                f.write(frame(''))
            calls = (lambda: lark.put('../x', svg, dry=True), lambda: lark.backup('../x'),
                     lambda: lark.restore('../x', svg), lambda: lark.preview('../x', os.path.join(d, 'o.png')))
            for call in calls:
                with mock.patch.object(lark, '_run', side_effect=AssertionError('must not run')), \
                        mock.patch.object(lark.shutil, 'copy', side_effect=AssertionError('must not copy')), \
                        self.assertRaises(lark.ToolError):
                    call()


class Eval(unittest.TestCase):
    script = os.path.join(HERE, 'eval', 'run_eval.py')

    def test_run_refuses_to_start_without_the_gateway_key(self):
        env = {k: v for k, v in os.environ.items() if k != 'LLMGW_OPENAI_API_KEY'}
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'out')
            # PATH is emptied so that even a regression past the key check could not launch codex
            r = subprocess.run([sys.executable, self.script, 'run', '-m', 'any-model', '-o', out],
                               capture_output=True, text=True, check=False, env=dict(env, PATH=''))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn('LLMGW_OPENAI_API_KEY is not set', r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_ccl_runner_refuses_to_start_without_its_launcher(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'out')
            # HOME is an empty dir, so ~/.claude/bin/claude-run is missing; PATH is emptied as a second fence
            r = subprocess.run([sys.executable, self.script, 'run', '--runner', 'ccl', '-m', 'any-model', '-o', out],
                               capture_output=True, text=True, check=False, env=dict(os.environ, HOME=d, PATH=''))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn('the ccl runner needs', r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_score_counts_what_the_engine_had_to_fix(self):
        with open(os.path.join(HERE, 'eval', 'cases.json'), encoding='utf-8') as f:
            case = json.load(f)[0]
        with tempfile.TemporaryDirectory() as d:
            spec = copy.deepcopy(CHARTS['graph'].DOC['example'])
            spec['edges'][0]['tone'] = 'good'
            # an untoned node is gray, so name the second family instead of leaning on the default tone
            spec['stages'][1]['nodes'][0]['tone'] = 'main'
            spec['stages'][0]['nodes'][0]['name'] = spec['stages'][0]['nodes'][0].pop('title')
            with open(os.path.join(d, case['id'] + '.json'), 'w', encoding='utf-8') as f:
                json.dump(spec, f, ensure_ascii=False)
            r = subprocess.run([sys.executable, self.script, 'score', d], capture_output=True, text=True, check=False)
            res = json.loads(r.stdout)
        row = res['rows'][0]
        self.assertEqual((row['builds'], row['type_ok'], row['dropped'], row['rewritten'], row['families']),
                         (True, True, 1, 1, 2))
        self.assertEqual((res['summary']['cases'], res['summary']['clean_builds']), (6, 1))
        self.assertEqual([x['produced'] for x in res['rows'][1:]], [False] * 5)


class Package(unittest.TestCase):
    def test_skill_frontmatter_is_plain_yaml(self):
        # the skills platform parses this with a strict YAML parser: an unquoted value may not contain ": " or " #"
        with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as f:
            head = f.read().split('---')[1]
        top = [ln for ln in head.strip().splitlines() if ln[:1] not in (' ', '')]
        self.assertEqual([ln.split(':')[0] for ln in top], ['name', 'description', 'license', 'compatibility', 'metadata'])
        for ln in top:
            value = ln.split(':', 1)[1].strip()
            with self.subTest(ln[:20]):
                self.assertFalse(value[:1] in ('"', "'", '[', '{', '&', '*', '!', '|', '>', '%', '@', '`'), value[:30])
                self.assertNotIn(': ', value)
                self.assertNotIn(' #', value)
                self.assertFalse(value.endswith(':'))


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'figure.py'), *args],
                              capture_output=True, text=True, check=False)

    def test_build_no_render_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, 'k1.json')
            with open(good, 'w', encoding='utf-8') as f:
                json.dump(CHARTS['compare'].DOC['example'], f, ensure_ascii=False)
            r = self.run_cli('build', good, '-o', d, '--no-render')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(os.path.exists(os.path.join(d, 'k1.svg')))
            with open(os.path.join(d, 'k1.report.json'), encoding='utf-8') as f:
                self.assertTrue(json.load(f)['ok'])
            bad = os.path.join(d, 'k2.json')
            with open(bad, 'w', encoding='utf-8') as f:
                json.dump({'type': 'flow'}, f)
            self.assertEqual(self.run_cli('build', bad, '-o', d, '--no-render').returncode, 1)

    def test_wrap_and_types(self):
        self.assertIn('flow', self.run_cli('types').stdout)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.svg')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(frame(''))
            out = self.run_cli('wrap', p).stdout
            self.assertTrue(out.startswith('<whiteboard type="svg"><svg'))


if __name__ == '__main__':
    unittest.main()
