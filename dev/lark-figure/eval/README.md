# lark-figure 跨模型评测

目的：检验「模型只写内容，观感由脚本决定」在不同模型上是否成立。6 段运维场景的文字（`cases.json`），每个模型只拿到技能目录和同一份提示词，产出 spec；由引擎机械打分，再由人看渲染图。

## 现状（2026-11-20）

| 模型 | 状态 |
|---|---|
| GPT 系列 | `gpt-5.4` 测过一轮（2026-11-13，6 个用例各 1 次），结果见下 |
| Kimi 系列 | `kimi-k3` 测过一轮（2026-11-13，6 个用例各 1 次），结果见下 |
| Seed 系列 | **未测** |
| Claude Haiku（代理） | 已测（2026-11-13），结果见下；其中 1 个 spec 在现在的引擎上已不能构建 |

三组结果都是 2026-11-13 在 1.1 引擎上的一次性测量，之后没有重跑模型。`results/` 里只留了 spec 和当时的分数，没有留运行日志，所以 `gpt-5.4` / `kimi-k3` 这两轮当时走的是哪个 runner、哪个网关，从仓库里无法复核。

**Claude Haiku 的代理结果不能当作 GPT / Kimi / Seed 的结论**：它和写这套技能的模型同源，对同一套措辞的理解天然更接近。

`run` 的两个 runner 在合入 1.4.0 时都没有重新跑过：

- `codex`（默认）：经 `llmgw` 网关，需要 `LLMGW_OPENAI_API_KEY`。只验证了「没有 key 时以 2 退出、不启动任何进程」（有单测）。
- `ccl`：经 `~/.claude/bin/claude-run llmbox` 驱动 Claude Code。2026-11-20 这台机器上没有这个文件，此时 `run --runner ccl` 以 2 退出、不启动任何进程（有单测）。

第一次在网关环境里跑时，先用一个模型、一个用例（`--case`）确认参数可用。

## 怎么跑

```bash
# 在已经配置好 llmgw 的环境里（变量由你的网关工具注入；脚本不读取、不打印、不落盘它的值）
python3 dev/lark-figure/eval/run_eval.py run -m gpt-5.6-terra -m kimi-k3 -o /tmp/lfig_eval
# 每个模型的 spec 和每个用例的运行日志（<case>.log）在 /tmp/lfig_eval/<model>/，汇总在 /tmp/lfig_eval/results.json

# 换成 Claude Code 驱动（llmbox 档位，即 ccl 别名）；--case 只跑指定用例，打分仍覆盖全部 6 个
python3 dev/lark-figure/eval/run_eval.py run --runner ccl -m kimi-k3 --case branching -o /tmp/lfig_eval

# 逐张出图，人工看
for f in /tmp/lfig_eval/<model>/*.json; do python3 skills/lark-figure/scripts/figure.py build "$f" -o /tmp/lfig_eval/<model>/png; done

# 其他方式得到的 spec（别的 CLI、手工粘贴）也可以直接打分
python3 dev/lark-figure/eval/run_eval.py score <目录> --label <名字>
python3 dev/lark-figure/eval/run_eval.py prompt branching      # 给模型的原始提示词
```

`codex` runner 固定传 `-c model_provider=llmgw`，没有 key 直接退出，请求不会落到别的端点。`ccl` runner 用 `--bare` 启动并关闭 slash command，模型只看得到工作目录里那份技能拷贝；凭据由 `claude-run` 自己解析，脚本不经手。运行日志是模型的标准输出和标准错误，提交进仓库前先看一遍里面有没有不该留的内容。给模型的提示词要求只用 `--no-render` 自检，所以画板自检（`wb_check`）的问题模型自己看不到，要靠上面「逐张出图」那一步发现。

## 打分项

都是机械事实，不评价好不好看（「彩色系 ≤ 3」是评测当时的 lint 上限；引擎上限后来放宽到 5，这一项保留下来只度量用色是否克制，不再等于 lint 上限）：能否构建且 lint 无 error（`clean_builds`）、图型是否在可接受范围（`right_type`）、彩色系 ≤ 3、强调 ≤ 2、标题是不是判断句、引擎替它改写了几个字段（`fields_rewritten`）、有几个字段被丢弃即内容没画出来（`fields_dropped`）。

## gpt-5.4 / kimi-k3 结果（2026-11-13）

spec 在 `results/gpt-5.4/`、`results/kimi-k3/`，分数在同名的 `.score.json`（当时的引擎算的，原样保留）。

| 项 | gpt-5.4 | kimi-k3 |
|---|---|---|
| 构建且 lint 无 error | 6 / 6 | 6 / 6 |
| 图型正确 | 6 / 6 | 6 / 6 |
| 彩色系 ≤ 3、强调 ≤ 2、标题是判断句 | 6 / 6 | 6 / 6 |
| 引擎改写字段 | 0 | 0 |
| 被丢弃的字段 | 0 | 0 |

2026-11-20 用 1.4.0 的引擎对这 12 个 spec 重新打分（`run_eval.py score`）：汇总行与上表一致，12 个都还能构建。逐行只有彩色系个数变了，3 处由 2 变 1（`gpt-5.4` 的 `breakdown`，`kimi-k3` 的 `branching` 和 `breakdown`），原因是不写 `tone` 的元素现在是灰色。同一天带渲染的完整 build 是 12 / 12 通过（lint 0 error、画板自检为空）；渲染图只抽看了两张 `options`。

这两轮没有留下逐张人工看图的记录，内容层面的问题（数字是否出自原文、措辞是否走样）没有核过。每个用例只跑了 1 次。

## Claude Haiku 代理结果（2026-11-13）

spec 在 `results/claude-haiku-proxy/`，分数在 `results/claude-haiku-proxy.score.json`（1.1 引擎修复后重算的，原样保留）。

**在现在的引擎上这组结果已经不成立**：`branching.json` 从 `05fde84`（2026-11-17，graph 各行对齐）起不能构建，报 `edges[4].label '积压 >5min' has no free spot beside its arrow`。2026-11-20 重新打分是构建 5 / 6、被丢弃的字段 1（`branching` 不再计入）。存下来的 spec 是当时的测量，没有改；graph 对这类标签的摆放是引擎的待办，不是这份 spec 的问题。下表是 2026-11-13 的数：

| 项 | 结果 |
|---|---|
| 构建且 lint 无 error | 6 / 6 |
| 图型正确 | 6 / 6（graph、sequence、cycle、bars、compare、tree） |
| 彩色系 ≤ 3、强调 ≤ 2、标题是判断句 | 6 / 6 |
| 引擎改写字段 | 0 |
| 被丢弃的字段 | 3（都是给连线或消息写了 `tone`） |
| 带渲染的完整 build 一次通过 | 5 / 6 |

这一轮暴露并已修掉的问题：

1. `branching`：同一阶段上下两个节点之间的连线标签压到了箭头，画板自检报 `text-overflow`，`--no-render` 下看不出来。已修：这类连线有标签时加大节点间距，标签只对着线身居中；有单测。
2. 连线、消息上的 `tone` 原先被静默忽略。已修：现在出现在 `notes` 里，SKILL.md 的常见错误表也加了一行。
3. 打分脚本原先数彩色系的方法偏少，已改成和 lint 同一口径。

人工看图发现、引擎管不了的内容问题（原样保留，没有改 spec）：

- `calls` 的标题写了「62%」，是用原文的 510 / 820 算出来的，原文没有这个数。
- `loop` 的副标题把原文的「以前」写成了「前年」。
- `options` 三张卡各用一种颜色（3 个彩色系），没有按「其余用 base」来；在上限内，但不是推荐的 1–2 种。
- `ranking` 的目标线标签只写了「发布规范要求」，没带「30 秒」。

样本只有 6 个、每个用例跑 1 次，只能说明「没有系统性失败」，不能给出稳定的通过率。
