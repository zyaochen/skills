---
name: lark-figure
description: 把一个判断画成飞书画板配图：模型只写内容（JSON spec：一句判断做主标题、要素、数字、来源），排版、配色、字号、留白、箭头走线全部由脚本按固定审美算出来，再过 lint 和画板自检，最后写进飞书画板并导出真实渲染图复核。覆盖流程、带分支和汇合的架构/数据流、调用时序、闭环、分层架构、方案对比卡片、条形图、甘特/时间重叠、2×2 矩阵、表格、折线、Roofline 屋顶线（对数轴）、里程碑、拆解树，以及上下拼两张子图；也用于把已有的旧图按同一风格重画。用户说“画张图/配个图/画个架构图/流程图/数据流图/调用链/时序图/闭环图/对比图/柱状图/时间线/路线图/拆解图”“Roofline/屋顶线/算术强度图”“把这段画成飞书画板”“给文档配图”“重画这张画板/这批旧图”“画板风格统一一下”时使用。不用于：类图、思维导图、带 alt/loop 嵌套框的时序图（交给 Mermaid）；插画、UI 原型这类自由创作（见 references/freeform.md 的手写 SVG 通道）。Use for editorial Lark whiteboard figures with a fixed house style; layout, color and type are computed by the script, not improvised by the model writing the spec.
license: Apache-2.0
compatibility: Python 3.8+（仅标准库）。本地预览和画板自检需要 Node（npx @larksuite/whiteboard-cli）；写入飞书需要 lark-cli 且已 `lark-cli auth login`。
metadata:
  version: "1.4.0"
  language: zh-CN
---

# lark-figure：内容由你写，好看由脚本保证

审美不靠临场发挥。这套技能把一套已经在 LLM 系列文档里反复验证过的画板风格（浅底圆角画布、左上角一句判断做主标题、飞书色板、浅底深字、正交箭头、底部来源）写成了排版引擎。你只负责**说清楚这张图要讲什么**，几何和颜色由 `scripts/figure.py` 算，所以观感不取决于是哪个模型在写 spec。

`$S` 指本技能的 `scripts/` 目录。

## 1. 先想清楚一句话

每张图只讲一个判断，判断写进主标题。动笔前先回答：

| 问题 | 写到哪 | 例子 |
|---|---|---|
| 读者看完该记住哪一句？ | `title`（≤ 24 个汉字左右，必须是判断句） | “排队占了 60% 的时间”，不是“请求流程图” |
| 这张图怎么读？ | `subtitle`（一句） | “大号数字是各段 p50 耗时；红色是瓶颈” |
| 数字和事实从哪来？ | `source` | “来源：线上 trace 抽样 1 万条”；没有外部出处写“来源：本文整理” |
| 谁是主角、谁是对照、哪里有风险？ | 各元素的 `tone` | 见第 3 节 |

说不出这一句话，就先别画；回去问用户或者读原文。不要补造原文没有的模块、数字、角色。

## 2. 选图型

先跑 `python3 $S/figure.py types` 看全表。按“你要表达的关系”选，不按“用户口头说的图名”选：

| 想表达 | 用 | 不要用 |
|---|---|---|
| 一条直线上的先后步骤、哪一步最慢 | `flow` | 有分叉还用 flow |
| 有分流、汇合、旁路、回写的架构或数据流 | `graph`（你按阶段摆节点，连线自动走） | 用 flow 画分支；一张图塞超过 12 个节点 |
| 几个服务或角色之间按时间先后的调用 | `sequence` | 用 graph 画先后顺序 |
| 首尾相接、会自己转起来的闭环 | `cycle` | 用 flow 画完再口头说“回到第一步” |
| 系统分几层、每层有哪些模块、哪块要改 | `layers` | 用 flow 画层级 |
| 2–4 个**可选方案**按同一组指标比较、推荐哪个 | `compare`（指标少）/ `table`（指标多、要精确值） | 用 bars 比文字属性 |
| 一件事的几项约束或资源、哪一项卡住了（如 SM 四项资源取 min） | `table` + `highlight_row` 标出卡住的那一行 | 拆成几张 compare 卡片：卡片是给读者挑的，不是给属性分栏的 |
| 谁大谁小、排名、提速多少 | `bars`（可分组、可对数轴、可加目标线） | 用 line 画无序类别 |
| 多件事在时间上怎么重叠、关键路径在哪 | `timeline` | 用 flow 画并行 |
| 两个维度上的取舍、先做哪个 | `matrix` | 用 compare 硬凑 |
| 随某个有序量的变化趋势 | `line` | 用 bars 画趋势 |
| 算子落在带宽受限还是算力受限、离屋顶多远、理论 vs 实测上限 | `roofline`（只给峰值和带宽，屋顶和拐点由脚本算） | 用 line/bars 硬画对数坐标；手画屋顶线 |
| 版本演进、路线图、事故时间线 | `milestones` | 用 timeline 画离散事件 |
| 一个总量拆成几块、根因拆解、组织结构 | `tree` | 用 layers 画树 |
| 两张子图合起来才讲得清一个判断 | `stack`（最多 3 个子图） | 一张图塞两个判断：拆成两张 |

都不合适时：先看能不能拆成两张标准图；确实不行再走 `references/freeform.md` 的手写 SVG 通道（同样要过 lint）。

### 重画已有的图

把一批旧图统一成这套风格时，按原图**讲的关系**重新写 spec，不照搬原图的版式：

1. **先找原图里的判断**。旧图的结论常常不在标题里，而在底部的灰色说明、“常见误区”或图注里（例如“更多 warp ≠ 更高 occupancy”）。把它提成 `title`；原标题是描述性的（“SM 资源上限”“TMA 的架构优势”）就换掉。`callout` 只在还需要第二句时保留。
2. **按关系选图型**：资源/约束取 min → `table` + `highlight_row`；前后对比、两种做法 → `compare` 两张卡，推荐的那张写 `primary: true`；轮转、流水重叠 → `timeline`；五步闭环 → `cycle`；屋顶线、算术强度分布 → `roofline`。一批图里 `compare` 超过一半，通常说明选型偷懒了。
3. **数字原样搬，但先核一遍**：算式和表里的数要对得上（min(…) 的结果、乘积、百分比）；`roofline` 会直接拒绝高过屋顶的点。原图错了，告诉用户，不要把错误画得更好看。
4. **不要只换色板和字体**。旧 SVG 的文字框是按旧字体的宽度摆的，换成画板字体后宽度会变，溢出和重叠要逐张返工；颜色也只是被换了色值，没有“谁是主角”的语义。统一观感只走 spec 重建这一条路。

## 3. 写 spec

```bash
python3 $S/figure.py example flow > k1.json        # 拿一个完整、可通过的样例当起点
python3 $S/figure.py example flow --fields         # 看这个图型每个字段的含义和上限
```

改样例里的内容，**只改内容不改结构**。不要写坐标、颜色值、字号——spec 里没有这些字段，写了也会被忽略。

颜色只用语义色 `tone`。先用 `base`（灰）打底，再判断要不要上色。什么时候上色、怎么用：

| 场景 | 用法 |
|---|---|
| 同 category 多卡对比（三种并行方案 / 三种切法） | **列卡同 tone**——比如全 `base`，或全 `main`。然后用 ①②③ + ✗/✓ 区分，不让色彩干分类器 |
| 异 category 多卡（演进版本 v1/v2/v3 / 新旧方案 / 旧 API vs 新 API） | **列卡异色**——每张卡一个 family（红/绿/橙/蓝/紫），整卡 pale wash bg2 自动上色，色彩担当合法分类器 |
| 主卡 / 推荐 | 1 张 `primary: true`，顶部 colorline + verdict pill 同色 |
| 风险 / 瓶颈 / 不达标 | 行 value 用 `tone: "risk"`，行右侧出 chip |

| tone | 颜色 | 什么时候用 |
|---|---|---|
| `main` | 蓝 | 本文主角、推荐方案 |
| `contrast` | 橙 | 对照组、过渡方案、备选 |
| `good` | 绿 | 正向结论、已完成、达标 |
| `risk` | 红 | 瓶颈、风险、不可用、超标 |
| `extra` | 紫 | 第五类，很少需要 |
| `base` | 灰 | 背景信息、基线、无关紧要的部分（不写 `tone` 时的默认值） |

强调手段：`tone`、`emph: true`、`highlight: true`（兼容字段，等同 `primary: true`）、`icon: "✗"/"✓"`（title 前缀）、`id: "①"`（title 左侧圆形编号）。一张图里被强调的元素不超过 2 处。

通用可选字段：`callout`（标题下一条「结论：…」横幅；最多 1 条）、`footline`（compare 专用，卡下方一条「结论：…」 banner；最多 1 条；`dashed: true` 切换成"小总结"虚线样式）、`legend`（图例，颜色本身不能自解释时才加）。

排版可选字段（写完内容仍然太挤 / 太宽 / 太瘦时用）：

| 字段 | 取值 | 什么时候用 |
|---|---|---|
| `aspect` | `normal`（默认，1200 宽）/ `wide`（1300 宽）/ `narrow`（1000 宽） | 极宽的表格或 4 张并排卡用 `wide`；希望 viewBox 更接近正方形、减少服务端 square-fill 后的空白用 `narrow` |
| `density` | `normal`（默认）/ `compact`（行高 ×0.8）/ `airy`（行高 ×1.15） | compare/table 行数 ≥ 8、图接近高度上限时用 `compact`；装饰性强的场景才用 `airy` |
| `title_align` | `left`（默认，左上）/ `center`（居中） | editorial / 演进 / 生命周期图用 `center`，日常卡片图用默认 `left` |
| `frameless` | `false`（默认，带 frame）/ `true`（去 frame，漂浮白底） | editorial / 内容 infographic 用 `true`；嵌在文档里跟其他卡片混排时保持默认 `false` |

最常见的写错（脚本能认出一部分并在 `notes` 里告诉你，但别依赖它）：

| 写错 | 正确 |
|---|---|
| `"color": "red"`、`"tone": "red"` | `"tone": "risk"`（写语义，不写颜色） |
| 步骤、卡片、节点的名字字段混用 `name` / `label` / `title` | 以 `example <type> --fields` 为准，每个位置只有一个名字字段 |
| 标题写成“XX 流程图”“XX 架构” | 写结论：“排队占了 60% 的时间” |
| 给连线、消息加 `tone` / `color` | 连线一律中性灰；颜色只属于节点、卡片、条 |
| 把一整句话塞进节点标题或连线标签 | 标题 ≤ 8 个字，细节放 `sub` / `lines`；连线标签 ≤ 4 个字 |
| `compare` 里没有一张卡是 `primary`，也没有 ✓/✗ 或 `verdict` 表明取舍 | 没有要挑的方案就不是 compare：多半该用 `table` |
| `verdict` 写成一长串数字（“本例需求 64 warp”） | `verdict` 是 2–6 个字的判断（“推荐”“卡在这里”）；数字放 `rows` |
| 原文没有的数字、模块，为了“好看”补上 | 不补。材料不够就少画 |

## 4. 生成并过闸

```bash
python3 $S/figure.py build k1.json -o out/
```

一次完成：校验 spec → 排版出 `out/k1.svg` → 风格 lint → 画板自检（whiteboard-cli --check）→ 本地渲染 `out/k1.png` → 写 `out/k1.report.json`。

- 退出码 0：通过。**用 Read 打开 `out/k1.png` 看一眼**，确认主标题那句话在图上一眼能看出来。
- 退出码 1：按输出里的 `errors` / `lint.findings` / `wb_check` 改 **spec**，再跑。消息都写成了改法（例如“title too long … shorten it”）。最多 3 轮；3 轮还不过，停下来把报错原文和 spec 交给用户。
- 退出码 2：工具缺失或网络问题（Node / npx 不可用），加 `--no-render` 先完成 lint，并告诉用户本地预览没跑。
- `W` 级提示（如 TITLE-LABEL、SIZE）不拦截，但要看图确认。
- `notes` 每一条都要读：`… read as "…"` 是脚本替你改了写法，图没问题，下次按正确字段写；`… is not a field here and was ignored` 是**你写的内容没有画出来**，按提示改字段名后重跑；颜色太多、强调太多、图太高时按提示改 tone 或拆图。

**不要手改生成的 SVG 来“修”问题**：改 spec 重新生成。手改的 SVG 下次重建就丢了，也绕过了排版引擎。

## 5. 放进飞书

三种情况，都用 `--as user`。写操作前先 dry-run（`put` 不带 `--yes` 就是 dry-run）。

| 情况 | 做法 |
|---|---|
| 新文档 / 文档里新插一张图 | `python3 $S/figure.py wrap out/k1.svg` 得到 `<whiteboard type="svg">…</whiteboard>`，交给 lark-doc 技能用 `docs +create` / `docs +update` 写入；返回的 `new_blocks[].block_token` 就是画板 token |
| 覆盖已有画板（重画、改样式） | `python3 $S/figure.py put <画板token> out/k1.svg` 先 dry-run，确认后加 `--yes`；会先把原画板备份到 `~/.cache/lark-figure/bak/`，回滚用 `figure.py restore <token> <备份> --yes` |
| 复核 | `python3 $S/figure.py preview <画板token> -o out/k1.lark.png`，用 Read 看飞书真实渲染（刚写完读不到时脚本会自动重试） |

交付时回报：画板 token（或文档链接）、飞书导出图路径、一句话说明这张图讲什么、report 里的 lint 结果。

## 6. 硬规矩

1. 主标题是判断句，带数字更好；不写“XX 架构图 / XX 流程 / 概览”。
2. 图里的每个数字必须出自用户给的材料或原文，和正文一致；没有的不编。
3. 不加图题“图 3”，不在图里写段落；超过两行的解释放正文。
4. 只用 spec 支持的字段。需要新能力时改引擎（`scripts/lfig/`）并补测试，不在单张图上打补丁。
5. 不上深色底浅色字、不用渐变阴影滤镜、不引外部图片字体——lint 会拦。
6. 一张图超过 1100 高、或 lint 报 DENSITY，优先拆图。`density: "compact"` 只压 compare / table 的行高，对其他图型无效；超高报错里只列出确实能把这张图压回上限内的选项。

### 彩色有额度预算
- 默认所有元素 tone="base"，再按需上色。
- 同 category 多卡：同 tone，靠 id / icon / verdict 区分。
- 异 category 多卡：每卡一个 family，整卡 pale wash 自动生效（不需 highlight）。
- 主卡/推荐：1 张 `primary: true`（顶部 colorline + verdict pill 同色）。
- 风险/瓶颈：行内 value 用 `tone: "risk"`。
- 1 张 compare 图里最多 1 张 primary 卡。

### tone 不当分类器：仅当「同 category」
- **同 category 多卡**（三种并行实现 / 三种切法）：不让色彩干分类器——卡片 tone 一致（典型是全 base），对比靠 ①②③ `id` + ✗/✓ `icon` + `verdict` 文本。
- **异 category 多卡**（版本演进 / 新旧方案 / 模块并列）：色彩**就是**分类器，每张卡一个 family（红/绿/橙/蓝/紫），引擎自动 pale wash 整卡。饱和度自动压在 bg2 档，视觉上仍是「轻轻彩」。
- 不放开：同一张卡不要超过 1 个 family。同图上限是 5 个 family（`theme.json` 的 `max_families`），也就是色板的全部彩色系，所以这条上限在默认主题下不会触发；颜色用多了由 `COLOR-OVERUSE` 和 `TONE-AS-CLASSIFIER` 拦。

### 每张图最多 1 个结论横幅
- `callout`（标题下）和 `footline`（compare 卡下）只能选一个，不能两个都上。

### border / frame / 背景默认全部灰
- 卡片默认 fill = `#FFFFFF`,border = `#C9CDD4` 1.5px。
- 卡片 tone ≠ base 时，fill 自动换成该 family 的 `bg2`（pale wash），不需手动。
- 子模块边界用 dashed `#DEE0E3`。
- compare 想突出「对比组」时，用 `card_style: "outlined"`（白底 + 主色描边），不要 highlight 整卡。

### tone 语义解绑定
- good ≠ 推荐；good = 已完成、已达标。
- risk ≠ 对比中的坏方案；risk = 需要马上行动。
- main ≠ 多主角的区分色；main = 唯一主角 或"本篇主题"。
- contrast = 中间状态过渡、备选、对照方案。

## 参考

| 文件 | 什么时候读 |
|---|---|
| [references/taste.md](references/taste.md) | 想知道为什么这样排、或者要改 theme 时 |
| [references/spec.md](references/spec.md) | 写 spec 遇到字段问题；也可直接跑 `example <type> --fields` |
| [references/lint.md](references/lint.md) | lint 报错码的含义和对应改法 |
| [references/freeform.md](references/freeform.md) | 标准图型确实覆盖不到、要手写 SVG 时 |
| [references/publish.md](references/publish.md) | 写入飞书的细节、权限问题、批量替换文档里的图 |
| `examples/*.json` | 每种图型一个可通过的完整样例 |
