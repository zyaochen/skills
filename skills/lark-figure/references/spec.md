# spec 字段参考

由 `dev/lark-figure/gen_spec_doc.py` 从各图型模块的 `DOC` 生成，不要手改。命令行等价：`figure.py example <type> --fields`。

## 所有图型通用

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | 下面任一图型名 |
| `title` | 是 | 一句判断，一行放得下（约 24 个汉字） |
| `subtitle` | 否 | 一句话说明怎么读这张图，最多两行 |
| `source` | 建议 | 以“来源：”开头；缺省写“来源：本文整理” |
| `callout` | 否 | `{text, label?:"结论", tone?:"contrast"}`，标题下方的结论横幅 |
| `legend` | 否 | `[{label, tone, style?: solid / dashed / line / dot}]` |

tone 取值：`main`（blue）、`contrast`（orange）、`good`（green）、`risk`（red）、`extra`（purple）、`base`（gray）

## flow

Steps joined by arrows: a pipeline, request path, or before→after sequence.

| 字段 | 说明 |
|---|---|
| `steps` | list (2-12) of {title, lines?:[str], metric?:str, tone?, emph?:bool, note?:str} |
| `labels` | optional list of edge labels, labels[i] sits on the arrow after steps[i] |
| `direction` | "right" (default, wraps after per_row) or "down" |
| `per_row` | optional int, steps per row for direction=right (default: all if ≤5, else balanced) |
| `numbered` | optional bool, draw 1,2,3… badges |
| `groups` | optional list of {from:int, to:int, label, tone?} brackets above step ranges (right only) |

样例：`examples/flow.json`

## graph

Architecture / data flow that branches and merges: you place nodes in stages, arrows route themselves.

| 字段 | 说明 |
|---|---|
| `stages` | list (2-5), left to right, of {name?:str, nodes:[{id, title, sub?:str, tone?, emph?:bool}] (1-4, top to bottom)}. Order is exactly what you write: there is no automatic reordering; nodes only slide up or down to line up with their neighbours so arrows run straight |
| `edges` | list (1-20) of {from:id, to:id, label?:str, dashed?:bool}. To the next stage: plain arrow. Skipping a stage (max 4): routed over the top. To an earlier stage (max 3): feedback, dashed, routed under the bottom. Within a stage: only between vertical neighbours |
| `tips` | to avoid crossings list each stage's nodes in the same top-to-bottom order as the nodes they connect to; keep labels to a few words |

样例：`examples/graph.json`

## sequence

Calls between 2-6 services or roles in time order: request path, handshake, incident hand-offs.

| 字段 | 说明 |
|---|---|
| `actors` | list (2-6), left to right, of str | {name, sub?:str, tone?} |
| `messages` | list (1-14), top to bottom, of {from:actor name, to:actor name, text, reply?:bool}. reply draws a dashed return arrow; from == to draws a self-call. Keep text to one short phrase |
| `sections` | optional list of {at:int, label}: a labelled divider before messages[at] (phases of the exchange) |

样例：`examples/sequence.json`

## cycle

A loop that feeds itself: iterate-measure-improve, incident lifecycle, control loop, flywheel.

| 字段 | 说明 |
|---|---|
| `steps` | list (3-8), clockwise from the top-left, of {title, sub?:str, tone?, emph?:bool} |
| `center` | optional short phrase in the middle of the loop: what the loop drives (a metric, a goal) |
| `numbered` | optional bool (default true), draw 1,2,3… badges so the starting point is clear |

样例：`examples/cycle.json`

## layers

Layered architecture / capability stack: top layer = closest to the user.

| 字段 | 说明 |
|---|---|
| `layers` | list (2-7) of {name, note?:str, tone?, items:[str | {label, sub?:str, tone?, emph?:bool}]} |
| `side` | optional {title, items:[str], tone?} a vertical band on the right spanning all layers |
| `arrows` | optional bool, draw a thin down-arrow between layers (request flow) |

样例：`examples/layers.json`

## compare

Side-by-side options with comparable attributes (A vs B vs C); mark the recommended one with primary.

| 字段 | 说明 |
|---|---|
| `cards` | list (2-4) of {title, subtitle?, tone?, primary?:bool, highlight?:bool (legacy), id?:str (①②③ badge), icon?:str (✗/✓ prefix), card_style?:"filled"|"outlined", verdict?:str, rows?:[[key, value] | {k, v, tone?}], points?:[str], foot?:str} |
| `note` | every card should use the same row keys in the same order so values line up; only ONE card should be primary; tone stays on verdict pill text only |

样例：`examples/compare.json`

## bars

Ranking or magnitude comparison; long labels welcome. Use grouped form for 2-3 series per category.

| 字段 | 说明 |
|---|---|
| `rows` | single series: list (2-16) of {label, value:number, tone?, note?:str} |
| `series` | grouped form: list (2-3) of {name, tone?}; then rows are {label, values:[number per series]} |
| `unit` | optional suffix written after every value, e.g. "ms", "%", " GB" |
| `sort` | optional "desc" | "asc" | "none" (default none: keep your order) |
| `log` | optional bool, log10 scale for values spanning orders of magnitude (say so in subtitle) |
| `ref` | optional {value, label} dashed reference line, e.g. a target or baseline |

样例：`examples/bars.json`

## timeline

Spans on parallel lanes over a shared axis: pipeline overlap, schedules, critical path, Gantt.

| 字段 | 说明 |
|---|---|
| `lanes` | list (1-14) of {label, spans:[{start, end, text?, tone?, dashed?:bool, emph?:bool}]}; emph gives one span (the critical one) a strong edge |
| `axis` | {min?, max?, ticks?:[number], unit?:str}; min/max default to the data range |
| `markers` | optional list of {at, label, tone?} vertical lines (deadline, sync point) |
| `legend` | recommended: [{label, tone, style?:"solid"|"dashed"}] explaining span colors |

样例：`examples/timeline.json`

## matrix

2×2 positioning on two axes (cost × benefit, urgency × impact); point at the quadrant that wins.

| 字段 | 说明 |
|---|---|
| `x` | {label, low, high} horizontal axis, low on the left |
| `y` | {label, low, high} vertical axis, low at the bottom |
| `quadrants` | exactly 4, order [top-left, top-right, bottom-left, bottom-right]; each {title, items?:[str], tone?, highlight?:bool} |

样例：`examples/matrix.json`

## table

Exact values across a few options × metrics where bars would lose precision. Keep ≤ 6 columns.

| 字段 | 说明 |
|---|---|
| `columns` | list (2-6) of header strings; first column is the row label |
| `rows` | list (1-12) of lists; a cell is a string/number or {text, tone?, bold?} |
| `highlight_col` | optional int column index to emphasise (e.g. the recommended option) |
| `highlight_row` | optional int row index to emphasise |
| `tone` | optional tone of the highlight (default good) |

样例：`examples/table.json`

## line

Trend over an ordered x (sequence length, time, batch size); 1-4 series, direct end labels.

| 字段 | 说明 |
|---|---|
| `x` | {labels:[str] (2-16), title?:str} |
| `y` | {title?:str, min?:number, max?:number, unit?:str} |
| `series` | list (1-4) of {name, values:[number per x label], tone?, area?:bool, labels?:bool} |
| `notes` | optional list of {series:int, index:int, text} callouts at a data point |

样例：`examples/line.json`

## roofline

Kernels against compute and memory-bandwidth ceilings on log-log axes: bandwidth- vs compute-bound.

| 字段 | 说明 |
|---|---|
| `roofs` | list (1-3) of {name, peak:number (y unit, e.g. TFLOPS), bandwidth:number (y unit per x unit, e.g. TB/s when y is TFLOPS and x is FLOP/Byte), tone?, dashed?:bool, ridge?:str|false}. The first roof is the reference; later ones are dashed by default. ridge labels the knee (default "拐点 <peak/bandwidth>"; false hides it) |
| `points` | optional list (0-12) of {label, x:number (intensity), y?:number (achieved; default: on the first roof), tone?, emph?:bool}. Keep labels to a short kernel name |
| `x` | optional {title?:str, min?:number, max?:number}; default title "算术强度（FLOP/Byte）" |
| `y` | optional {title?:str, min?:number, max?:number}; default title "吞吐（TFLOPS）" |
| `regions` | optional [left, right]: short labels under the sloped and the flat part, e.g. ["带宽受限", "算力受限"] |

样例：`examples/roofline.json`

## milestones

Roadmap, release history, incident timeline: 3-8 dated events in order.

| 字段 | 说明 |
|---|---|
| `items` | list (3-8) of {when, title, lines?:[str], tone?, now?:bool} |
| `note` | mark the current point with now:true; use tone good for done, main for planned, risk for slipped |

样例：`examples/milestones.json`

## tree

Breakdown of one thing into parts: cost decomposition, cause tree, module hierarchy, org chart.

| 字段 | 说明 |
|---|---|
| `root` | {label, sub?:str, tone?, children:[node]}; node = {label, sub?, tone?, emph?:bool, children?:[node]} |
| `limits` | depth ≤ 4, ≤ 12 children per node, ≤ 16 leaves (about 12 when every leaf has a sub: the figure must stay under the height cap); an unset root is base (gray) and a child inherits its parent tone unless it sets one |

样例：`examples/tree.json`

## stack

Two or three sub-charts stacked vertically under one title (e.g. compare cards + a table).

| 字段 | 说明 |
|---|---|
| `parts` | list (2-3) of {label?:str, tone?, type:<any other type>, ...that type's fields} |

样例：`examples/stack.json`

