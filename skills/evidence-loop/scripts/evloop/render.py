"""图 JSON 校验与渲染：架构图 SVG、过程图 SVG、自包含 HTML 页面。

产出的页面不含 JavaScript，也不引用任何外部资源，用 file:// 直接打开即可。

图 JSON 结构：
  {"meta": {"title": "..."},
   "nodes":   [{"id": "order-api", "label": "...", "sublabel": "...",
                "kind": "service|store|external|decision|flow", "row": 0, "col": 1}],
   "edges":   [{"from": "a", "to": "b", "label": "调用", "dashed": false}],
   "regions": [{"label": "后端", "wraps": ["order-api"]}],
   "depends": {"order-api": ["order-store"]}}

所有节点都给出整数 row/col 时按网格摆放；否则按"最长前驱链"分层，从左到右排列。
depends 是裁判检查的构建顺序数据，同时参与分层。
"""
import html
import json
import os
import re
import subprocess
import sys

from .util import atomic_write_text

NODE_W, NODE_H = 208, 64
GAP_X, GAP_Y = 56, 72
MARGIN = 40

INK = "#DCE6F7"
MUTE = "#9DB5E8"
LINE = "#6B7A99"
NODE_BG = "#131E36"
NODE_STROKE = "#2E3F66"
ACCENT = "#00C8D2"
TARGET = "#78E6DD"
GOOD = "#3DDC97"
WARN = "#FFB454"
BAD = "#FF7A7A"
BEST_LINE = "#3C8CFF"

KIND_DOT = {"service": "#3C8CFF", "store": "#3DDC97", "external": "#6B7A99",
            "decision": "#FFB454", "flow": "#B78CFF"}
PROGRESS_COLOR = {"done": GOOD, "pending": WARN}

ID_PATTERN = r"[A-Za-z0-9_-]+"
_ID_RE = re.compile(ID_PATTERN)


def esc(value):
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------- 校验

class DiagramError(ValueError):
    pass


def load_diagram(path):
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except ValueError as e:
        raise DiagramError(f"{path} 不是合法的 JSON：{e}") from None
    return check_diagram(spec, path)


def _str_list(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def check_diagram(spec, name="diagram"):
    """结构校验；不合法时抛 DiagramError，合法时原样返回。"""
    if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list) or not spec["nodes"]:
        raise DiagramError(f'{name}：需要非空的 "nodes" 列表')
    ids = []
    for n in spec["nodes"]:
        nid = n.get("id") if isinstance(n, dict) else None
        if not isinstance(nid, str) or not _ID_RE.fullmatch(nid):
            raise DiagramError(f"{name}：每个节点都需要匹配 {ID_PATTERN} 的 id")
        for key in ("label", "sublabel", "kind", "accept"):
            if key in n and not isinstance(n[key], str):
                raise DiagramError(f"{name}：节点 {nid} 的 {key} 必须是字符串")
        ids.append(nid)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise DiagramError(f"{name}：节点 id 重复 {dupes}")
    known = set(ids)

    edges = spec.get("edges", [])
    if not isinstance(edges, list):
        raise DiagramError(f'{name}："edges" 必须是列表')
    for e in edges:
        if not isinstance(e, dict):
            raise DiagramError(f"{name}：每条边都必须是对象")
        bad = [e.get(k) for k in ("from", "to") if e.get(k) not in known]
        if bad:
            raise DiagramError(f"{name}：边引用了不存在的节点 {bad}")

    regions = spec.get("regions", [])
    if not isinstance(regions, list):
        raise DiagramError(f'{name}："regions" 必须是列表')
    for r in regions:
        if not isinstance(r, dict) or not _str_list(r.get("wraps", [])):
            raise DiagramError(f'{name}：每个区域都必须是对象，且 "wraps" 为字符串列表')
        bad = [w for w in r.get("wraps", []) if w not in known]
        if bad:
            raise DiagramError(f"{name}：区域包含不存在的节点 {bad}")

    depends = spec.get("depends", {})
    if not isinstance(depends, dict):
        raise DiagramError(f'{name}："depends" 必须是对象 {{节点: [依赖节点…]}}')
    for node, needs in depends.items():
        if not _str_list(needs):
            raise DiagramError(f"{name}：depends[{node}] 必须是字符串列表")
        bad = [x for x in [node, *needs] if x not in known]
        if bad:
            raise DiagramError(f"{name}：depends 引用了不存在的节点 {bad}")
    return spec


def node_ids(spec):
    return {n["id"] for n in spec["nodes"]}


def diagram_signature(spec):
    """只看内容的指纹：节点、边、依赖相同即视为同一张图，与标题和布局无关。"""
    return {
        "nodes": sorted((n["id"], n.get("label", "")) for n in spec["nodes"]),
        "edges": sorted((e["from"], e["to"], e.get("label", "")) for e in spec.get("edges", [])),
        "depends": {k: sorted(set(v)) for k, v in sorted(spec.get("depends", {}).items())},
    }


def topo_batches(order, deps):
    """Kahn 分批：每批内的元素只依赖之前批次。返回 (batches, 成环的剩余元素)。"""
    batches, placed = [], set()
    remaining = list(order)
    while remaining:
        batch = [e for e in remaining if set(deps.get(e, [])) <= placed]
        if not batch:
            return batches, remaining
        batches.append(batch)
        placed |= set(batch)
        remaining = [e for e in remaining if e not in placed]
    return batches, []


# ---------------------------------------------------------------- 布局

def _depths(spec):
    """最长前驱链深度。迭代实现，长链不会触发递归上限；环上的回边被忽略。"""
    ids = [n["id"] for n in spec["nodes"]]
    preds = {i: [] for i in ids}
    for e in spec.get("edges", []):
        if e.get("to") in preds and e.get("from") in preds:
            preds[e["to"]].append(e["from"])
    for node, needs in spec.get("depends", {}).items():
        if node in preds:
            preds[node] += [x for x in needs if x in preds]
    depth, state = {}, {}  # state: 1 = 在栈上, 2 = 已完成
    for root in ids:
        if state.get(root) == 2:
            continue
        stack = [(root, iter(preds[root]))]
        state[root] = 1
        while stack:
            nid, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                depth[nid] = max([depth[p] + 1 for p in preds[nid] if state.get(p) == 2] or [0])
                state[nid] = 2
                stack.pop()
            elif state.get(nxt) is None:
                state[nxt] = 1
                stack.append((nxt, iter(preds[nxt])))
    return depth


def layout(spec):
    nodes = spec["nodes"]
    if all(isinstance(n.get("row"), int) and isinstance(n.get("col"), int) for n in nodes):
        return {n["id"]: (MARGIN + n["col"] * (NODE_W + GAP_X),
                          MARGIN + n["row"] * (NODE_H + GAP_Y)) for n in nodes}
    depth = _depths(spec)
    col_of = {d: i for i, d in enumerate(sorted(set(depth.values())))}
    rows, pos = {}, {}
    for n in nodes:
        c = col_of[depth[n["id"]]]
        r = rows.get(c, 0)
        rows[c] = r + 1
        pos[n["id"]] = (MARGIN + c * (NODE_W + GAP_X), MARGIN + r * (NODE_H + GAP_Y))
    return pos


def _edge(pos, e):
    sx, sy = pos[e["from"]]
    tx, ty = pos[e["to"]]
    srx, smy = sx + NODE_W, sy + NODE_H / 2
    tlx, tmy = tx, ty + NODE_H / 2
    if tlx > srx + 8:                                   # 向前：折线
        mx = (srx + tlx) / 2
        path = f"M {srx} {smy} H {mx:.1f} V {tmy} H {tlx}"
        label_at = (mx, (smy + tmy) / 2 - 6)
    elif tx == sx:                                      # 同列：向右绕出
        dx = sx + NODE_W + 22
        path = f"M {srx} {smy} H {dx} V {tmy} H {tx + NODE_W}"
        label_at = (dx + 4, (smy + tmy) / 2)
    else:                                               # 回边：从上方越过
        scx, tcx = sx + NODE_W / 2, tx + NODE_W / 2
        lane = min(sy, ty) - 24
        path = f"M {scx} {sy} V {lane} H {tcx} V {ty}"
        label_at = ((scx + tcx) / 2, lane - 6)
    dash = ' stroke-dasharray="6 5"' if e.get("dashed") else ""
    out = [f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="1.5"{dash} marker-end="url(#arr)"/>']
    if e.get("label"):
        out.append(f'<text x="{label_at[0]:.1f}" y="{label_at[1]:.1f}" text-anchor="middle" '
                   f'fill="{MUTE}" font-size="11">{esc(str(e["label"])[:28])}</text>')
    return out


def graph_svg(spec, progress=None):
    """progress: {id: 'done'|'pending'}，按循环进度给节点描边。"""
    progress = progress or {}
    pos = layout(spec)
    w = max(x for x, _ in pos.values()) + NODE_W + MARGIN
    h = max(y for _, y in pos.values()) + NODE_H + MARGIN
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="13">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>']
    for r in spec.get("regions", []):
        if not r.get("wraps"):
            continue
        rxs = [pos[i][0] for i in r["wraps"]]
        rys = [pos[i][1] for i in r["wraps"]]
        x0, y0 = min(rxs) - 18, min(rys) - 34
        x1, y1 = max(rxs) + NODE_W + 18, max(rys) + NODE_H + 18
        svg += [f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="12" fill="none" '
                f'stroke="#3A4B70" stroke-width="1.2" stroke-dasharray="4 5"/>',
                f'<text x="{x0 + 12}" y="{y0 + 16}" fill="{MUTE}" font-size="11" '
                f'letter-spacing="1">{esc(r.get("label", ""))}</text>']
    for e in spec.get("edges", []):
        svg += _edge(pos, e)
    for n in spec["nodes"]:
        x, y = pos[n["id"]]
        state = progress.get(n["id"])
        stroke = PROGRESS_COLOR.get(state, NODE_STROKE)
        svg.append(f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="10" '
                   f'fill="{NODE_BG}" stroke="{stroke}" stroke-width="1.5"/>')
        dot = KIND_DOT.get(n.get("kind")) or PROGRESS_COLOR.get(state)
        tx = x + 14
        if dot:
            svg.append(f'<circle cx="{x + 16}" cy="{y + NODE_H / 2}" r="4" fill="{dot}"/>')
            tx = x + 30
        label, sub = n.get("label", n["id"])[:24], n.get("sublabel", "")[:36]
        if sub:
            svg.append(f'<text x="{tx}" y="{y + 28}" fill="{INK}" font-weight="600">{esc(label)}</text>')
            svg.append(f'<text x="{tx}" y="{y + 47}" fill="{MUTE}" font-size="11">{esc(sub)}</text>')
        else:
            svg.append(f'<text x="{tx}" y="{y + NODE_H / 2 + 5}" fill="{INK}" font-weight="600">{esc(label)}</text>')
    svg.append("</svg>")
    return "".join(svg)


# ---------------------------------------------------------------- 过程图

def chart_svg(pts, unit, direction, target, baseline):
    """优化过程图：基线 → 各次尝试 → 保留的最优值阶梯线。

    单点、所有分数相同、目标等于基线等退化情形都能得到可读的纵轴。
    """
    pts = list(pts) or [{"verdict": "baseline", "score": baseline}]
    values = [r["score"] for r in pts if r.get("score") is not None]
    values += [v for v in (target, baseline) if v is not None]
    lo, hi = (min(values), max(values)) if values else (0.0, 1.0)
    pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad
    W, H, L, R, T, B = 960, 480, 90, 30, 40, 70
    span = max(len(pts) - 1, 1)

    def X(i):
        if len(pts) == 1:
            return L + (W - L - R) / 2
        return L + (W - L - R) * i / span

    def Y(v):
        return T + (H - T - B) * (hi - v) / (hi - lo)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="13">',
           f'<rect width="{W}" height="{H}" fill="#0B1220"/>',
           f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="{LINE}"/>',
           f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="{LINE}"/>']
    if target is not None:
        svg += [f'<line x1="{L}" y1="{Y(target):.1f}" x2="{W - R}" y2="{Y(target):.1f}" '
                f'stroke="{TARGET}" stroke-dasharray="6 6"/>',
                f'<text x="{W - R}" y="{Y(target) - 6:.1f}" text-anchor="end" fill="{TARGET}">'
                f'目标 {target:g} {esc(unit)}</text>']
    best = baseline
    line = []
    for i, r in enumerate(pts):
        s = r.get("score")
        if best is not None:
            line.append((X(i), Y(best)))
        if s is not None and r.get("verdict") in ("accepted", "baseline") and not r.get("simplified"):
            best = s
        if best is not None:
            line.append((X(i), Y(best)))
    if line:
        svg.append(f'<polyline fill="none" stroke="{BEST_LINE}" stroke-width="2" points="' +
                   " ".join(f"{x:.1f},{y:.1f}" for x, y in line) + '"/>')
    for i, r in enumerate(pts):
        x, s, v = X(i), r.get("score"), r.get("verdict")
        if s is None:
            svg.append(f'<text x="{x:.1f}" y="{H - B - 8:.1f}" text-anchor="middle" fill="{BAD}">✕</text>')
        else:
            color = {"baseline": "#FFFFFF", "accepted": ACCENT, "rejected": BAD}.get(v, MUTE)
            svg.append(f'<circle cx="{x:.1f}" cy="{Y(s):.1f}" r="5" fill="{color}"/>')
        svg.append(f'<text x="{x:.1f}" y="{H - B + 18}" text-anchor="middle" fill="{MUTE}">{i}</text>')
    for v in sorted({lo + pad, hi - pad}):
        svg.append(f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="{MUTE}">{v:g}</text>')
    better = "越低越好" if direction == "lower" else "越高越好"
    svg.append(f'<text x="{L}" y="{T - 14}" fill="#FFFFFF" font-size="15">分数（{esc(unit)}，{better}）'
               '— 白：基线 · 青：接受 · 红：拒绝 · ✕：无效 · 蓝线：保留的最优</text>')
    svg.append(f'<text x="{W / 2:.0f}" y="{H - 14}" text-anchor="middle" fill="{MUTE}">尝试序号</text>')
    svg.append("</svg>")
    return "".join(svg)


# ---------------------------------------------------------------- 页面

PAGE_CSS = """\
body{margin:0;background:#0B1220;color:#DCE6F7;font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",Helvetica,Arial,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:22px;margin:0 0 6px}
.sub{color:#9DB5E8;margin:0 0 28px}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid #3C8CFF;color:#7FB2FF;font-size:11px;letter-spacing:.08em}
.badge.ok{border-color:#3DDC97;color:#3DDC97}
.badge.bad{border-color:#FF7A7A;color:#FF7A7A}
.badge.warn{border-color:#FFB454;color:#FFB454}
section{margin:26px 0}
h2{font-size:16px;color:#DCE6F7;font-weight:600;margin:0 0 12px}
h3{font-size:14px;color:#C9D6EE;font-weight:600;margin:18px 0 8px}
table{border-collapse:collapse;width:100%}
th,td{padding:8px 12px;border-bottom:1px solid #22304E;text-align:left;font-size:13px;vertical-align:top}
th{color:#9DB5E8;font-weight:600}
code{background:#131E36;padding:1px 6px;border-radius:4px;font-size:12px}
svg{max-width:100%;height:auto;background:#0E1730;border:1px solid #22304E;border-radius:8px}
.stats{display:flex;gap:14px;flex-wrap:wrap}
.stats>div{background:#0E1730;border:1px solid #22304E;border-radius:8px;padding:10px 18px;min-width:110px}
.stats b{display:block;font-size:19px}
.stats span{color:#9DB5E8;font-size:11px;letter-spacing:.06em}
a{color:#7FB2FF}
pre{background:#0E1730;border:1px solid #22304E;border-radius:8px;padding:12px;overflow:auto;font-size:12px;max-height:340px}
.ok{color:#3DDC97}.bad{color:#FF7A7A}.warn{color:#FFB454}.mute{color:#9DB5E8}
ol.batches li{margin:4px 0}
.diagram-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
.diagram-pair section{min-width:0;overflow-x:auto}
.diagram-pair svg{max-width:none}
.next-action{padding:16px 20px;border-left:3px solid #3C8CFF;background:#101D32;border-radius:0 8px 8px 0}
.review-notes{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 -apple-system,"Segoe UI","PingFang SC",Helvetica,Arial,sans-serif;max-height:none;border-color:#324869}
@media(max-width:720px){main{padding:24px 16px 48px}.diagram-pair{grid-template-columns:1fr;gap:0}table{display:block;overflow-x:auto}.stats>div{min-width:100px}}
"""


def page(title, subtitle_html, body):
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{PAGE_CSS}</style></head><body><main>"
            f"<h1>{esc(title)}</h1><p class=\"sub\">{subtitle_html}</p>{body}</main></body></html>")


def stats(items):
    cells = "".join(f"<div><b>{v}</b><span>{esc(k)}</span></div>" for k, v in items)
    return f'<div class="stats">{cells}</div>'


def table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def section(title, inner):
    return f"<section><h2>{esc(title)}</h2>{inner}</section>"


def write_page(path, title, subtitle_html, body):
    atomic_write_text(path, page(title, subtitle_html, body))
    return os.path.abspath(path)


def open_command(path):
    if sys.platform == "darwin":
        return ["open", path]
    if os.name == "nt":
        return None
    return ["xdg-open", path]


def open_path(path):
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 —— 有意调起系统查看器
            return True
        cmd = open_command(path)
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------- 命令行

def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="evloop_render.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("diagram", help="图 JSON 文件")
    p.add_argument("-o", "--out", help="输出 HTML 路径（默认与输入同名，扩展名改为 .html）")
    a = p.parse_args(argv)
    try:
        spec = load_diagram(a.diagram)
    except (OSError, ValueError) as e:
        print(f"evloop_render: {e}", file=sys.stderr)
        return 3
    out = a.out or os.path.splitext(a.diagram)[0] + ".html"
    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    title = meta.get("title") or os.path.basename(a.diagram)
    print(write_page(out, title, '<span class="badge">架构图</span>', graph_svg(spec)))
    return 0
