# 速查：{SERIES}（子 Agent 只读这一份规范）

由 `render_prompt.py quick` 从 skill 的 references/quick.md 渲染，阈值是本系列的实际值。详细规范在 {SKILL}/references/（write_brief、style_pairs、chart_brief），任务卡要求时再读。

## 主线
- 主线定义在 `{ROOT}/spec/MAINLINE.md`，和它冲突时以它为准。
- 方法步骤词（正文必须出现）：{TERMS}
- 主线位置段标签：{POSITION}（开篇 callout 后紧跟，cite 上一篇和下一篇）。
- 每章末 🔑 `<b>本章要点</b>`，末句点明本章解决了主线上的哪一项。

## 结构
- s00：title、🎯 开篇（这篇文档解决什么问题 / 使用方式 / 代码）、主线位置、`<h1>导读 · 先给结论</h1>` {GUIDE} 条 `<li><b>结论。</b>依据{{r:key}}</li>`、总览图、📎 分工段。
- s01..sKK：每个文件一个 `<h1>第 N 章 · 标题</h1>`，{CHAPTERS} 章，每章 {H2} 个 h2。第 1 章标题含“{FIRST}”，最后一章含“{LAST}”（📌 核对清单 + 自测题 + 接下来的问题在哪）。
- 💡 常见误区全篇 {PITFALLS} 个：现象、原因、改法。

## 厚度门槛（stats.py 检查）
- 每章散文汉字 ≥ {CH_MIN}，目标 {CH_LO} 到 {CH_HI}；s00 ≥ {S00_MIN}。
- 每章 ≥ {CITE_MIN} 个不同引用；除清单章外每章 ≥ 1 张图；不许整章只有散文。
- 全篇图 {FIG_LO} 到 {FIG_HI} 张，参考文献 {REF_LO} 到 {REF_HI} 条。
- 一章要有：论点、机制、3 个以上带口径的数字、可照做的命令或配置、边界条件。

## 占位符
- 引用 `{{r:key}}`（key 在 refs.json）；系列内 `{{C:NN}}` 只指别的篇，本篇章节写“第 N 章”；图 `{{F:name}}` 单独成段，每张只放一次。
- callout：`<callout emoji="💡" background-color="{CALLOUT_BG}" border-color="{CALLOUT_BORDER}"><p><b>常见误区</b>：…</p></callout>`，里面只放 p 和 ul。
- 表格 `<table><colgroup><col width="160"/>…</colgroup><thead><tr><th background-color="rgb(240,244,255)" vertical-align="top"><p>表头</p></th></tr></thead><tbody><tr><td vertical-align="top"><p>内容</p></td></tr></tbody></table>`，列宽和 700 到 820。代码块 `<pre lang="bash" caption="说明"><code>…</code></pre>`。
- 正文 `<` 写 `&lt;`，`&` 写 `&amp;`。不用 Markdown、`<section>`、`<figure>`、`<div>`。

## 文风红线（lint 只扫散文）
- 禁止：“不是 X 而是 Y”“不在 X 而在 Y”、破折号“——”、“进行”、“完成了”、“一是……二是”、“第一，……第二，”、量词标题。改写句子，别删掉意思（示例：{SKILL}/references/style_pairs.md）。
- 中文旁只用全角标点，中文引号用“”。
- 每个数字都有 `{{r:key}}` 或“本篇 sim_xxx.py 输出”，口径写清（稠密/稀疏、单向/双向、单卡/整机、峰值/实测）。不编数字。
- 先结论后依据，句子 15 到 25 字，不用口号。

## 图（figs/name.py → figs/name.svg）
- 用 svgkit：`import sys; sys.path.insert(0, '{S}'); from svgkit import Board`，构件 stack/flow/bars/groups/lanes/card/note/table/tag/cols，返回底边 y，省略 h 自动定高。`b.save('figs/name.svg')` 必须打印 OK（E 清零，W 改完或说明误报）。
- 先选图型，照 {SKILL}/assets/gallery/ 里同型样板改：ledger、flow、bars、groups、lanes、compare、matrix、ladder、arch。不截断词；“空带”“只占左边”“侧边距”永远不是误报。
- 主标题一句判断，副标题说明怎么读，底部“来源：”。一张图最多三个色系：主角蓝、对照橙、正向绿、风险红。字号不小于 12。
- `python3 {S}/preview_local.py figs/name.svg` 后 Read `figs/name.png` 看一遍。

## 命令（在 {ROOT} 下运行）
- `python3 {S}/normalize.py NN` 结构清理；`python3 {S}/autofix.py NN` 修标点。
- `python3 {S}/build.py NN --quiet` 装配 + lint，看 ERROR 和 SUMMARY。
- `python3 {S}/stats.py NN` 每段厚度；`python3 {S}/svgcheck.py NN -v` 图的版面。
- 不做 git，lark-cli 只用 --as user，发布只由发布角色做。
