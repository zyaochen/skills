# series.json 字段

`ROOT/spec/series.json` 只写和默认值（`assets/series.default.json`）不同的键，按键深合并。完整样例见 `assets/example_series/spec/series.json`。

## 系列信息

| 键 | 说明 |
|---|---|
| `name` | 系列名，出现在回报和 SERIES 行 |
| `prefix` | 篇号前缀，如 `GPU`、`LLM`；`{{C:GPU-05}}` 会规范成 `{{C:05}}` |
| `verified_on` | 开篇“核对于”那句的日期，如 `2026 年 11 月 4 日` |
| `refs_asof` | 参考文献首段“资料截至”的日期 |
| `folder` | `{"token": …, "url": …}` 飞书文件夹，新建文档落点 |
| `code_repo` | `{"url": 远端仓库, "local": 相对 ROOT 的本地路径, "branch": …}`，没有配套代码就留空 |

## 文档登记

`hub` 是总览篇（可为 null），`docs` 是正文篇列表，每项：

| 键 | 必填 | 说明 |
|---|---|---|
| `num` | 是 | 两位篇号字符串，`drafts/NN/` 的目录名 |
| `token` | 是 | 飞书 docx token，发布和 `{{C:NN}}` 都从这里取，不手传 |
| `title` | 是 | 完整标题，lint 要求 `<title>` 与之一致 |
| `url` | 否 | 文档链接，回报用 |
| `level` | 否 | 分层名（如 L1 硬件与内核），总览表格分组用 |
| `status` | 否 | `new` 新写、`rewrite` 重写、`ok` 只做检查，series_check 展示 |
| `focus` | 是 | 本篇在主线上负责的那一项（一句话），提示词渲染成 {FOCUS} |
| `scope` | 是 | 本篇深挖的范围；相邻内容一句话指向别篇 |
| `prev` / `next` | 否 | 主线上的前后篇号，主线位置段要 cite 它们 |
| `code_dir` | 否 | 配套代码目录（相对 `code_repo.local`） |
| `backup` | 否 | 旧版正文路径（重写时的素材库），如 `backup/05.xml` |

## 模板 `template`

| 键 | 默认 | 说明 |
|---|---|---|
| `guide_h1` / `chapter_h1` / `refs_h1` | 导读 · 先给结论 / `第 {n} 章 · ` / 参考文献 | 标题格式 |
| `refs_lead` | 按正文首次引用顺序编号，资料截至 {refs_asof}。 | 参考文献首段 |
| `split` | 📎 与系列其他文档的分工 | 导读末的分工段 |
| `position` | 空 | 主线位置段的标签（如 `🧭 主线位置`），非空时每篇必须有，且要 cite prev/next |
| `callouts` | 标签 → emoji | normalize 按粗体标签统一 emoji |
| `callout_color` | 橙色 | 所有 callout 同色，lint 检查 |
| `first_chapter_contains` / `last_chapter_contains` | 空 / 清单 | 第 1 章、最后一章标题必须包含的词 |
| `required` | 开篇、导读、分工、要点、参考文献 | 每篇必须出现的字符串 |
| `required_terms` | 空 | 方法闭环的步骤词（如 定天花板、测实际…），每篇正文必须出现 |
| `hub_required` | 开篇、参考文献 | 总览篇必须出现的字符串 |

## 阈值 `thresholds`

`chapters` `h2_per_chapter` `guide_items` `prose_chars` `refs` `figures` `pitfalls` `sentence_mean` `table_width` 都是 `[下限, 上限]`，超出报 WARN。`chapter_cjk_min`、`s00_cjk_min`、`cites_per_chapter_min` 是 stats.py 的 THIN、LOWCITE 门槛，`chapter_cjk_target` 是扩写目标。系列篇幅偏短（例如每篇 0.8 万字）时整体调低，不要逐篇豁免。

## 文风 `style`、画图 `board`、审计 `audit`

- `style.red`：红线正则，命中即 ERROR；以 `<` 开头的正则扫原始 XML（用于标题），其余只扫散文。`style.soft` 加 `soft_per_10k_max`：密度上限。
- `board`：画布、字号、色板，`svgkit` 和 `check_svg` 共用。改样式改这里，不改脚本。
- `audit.reference_values`：本领域的参考值清单（一条一句），审计和代码自检时逐条对照。例：`"H100 SXM BF16 稠密 989 TFLOPS（稀疏 1979）"`、`"NVLink4 每卡单向 450 GB/s，双向 900"`。这一项决定事实审计的上限，写得越具体越好。
