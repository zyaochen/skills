---
name: evidence-loop
description: 带机械裁判的自主工程循环。当用户要求在明确边界内长时间自主推进、并且结果必须可验证、可复跑、经人批准时使用：修 bug 且不许弄坏别的（bugfix）、按蓝图或架构图实现功能（development）、把某个基准指标压到目标线（optimization）、写带出处的调研（research）或可验收的文档（document）、把大需求拆成跨会话计划（plan）；涉及并发、重试、崩溃恢复、租约的设计可叠加 TLA+/TLC 形式化验证。典型说法："修这个 bug 别弄坏别的"、"按这张架构图实现"、"把 p99 压到 80ms 以内，给你两小时"、"自主跑一晚上"、"调研并给出处"、"写一份使用说明"、"拆成计划每天推进"、"给这个设计做形式化验证"。不要用于：改错别字或一行配置这类小改动、说不清完成标准的任务、需要修改测试或基准本身的任务。Use for long-running, judge-verified, human-approved changes; skip for trivial edits.
license: Apache-2.0
compatibility: 需要 git 2.20+ 与 Python 3.8+（仅标准库）；叠加形式化验证时另需 Java 11+（没有可用 evloop_tlc.py fetch --jre 自动下载）。可在任何能执行 shell 命令的智能体中使用。
metadata:
  version: "1.6.2"
  language: zh-CN
---

# evidence-loop：澄清 → 循环 → 交付

这套流程用"裁判按约定判定做完了"取代"智能体自己说做完了"。

- **你（智能体）负责理解**：读代码，起草约定，设计每一次尝试，解释结果，写评审说明。
- **裁判 `scripts/evloop.py` 负责机械检查**：改动有没有越界，冻结文件有没有被动过，约定命令的退出码与分数，预算是否耗尽，交付包与验证结果是否一致。它不评价代码好坏，判断全部落盘，可以复查。

## 0. 先判断要不要用

| 情况 | 做法 |
|---|---|
| 改错别字、改一行配置、一次性小改动 | **不要用**，直接改 |
| 完成标准说不清，没法写成一条命令 | 先和人把标准谈清楚，谈不清就不要用 |
| 需要改测试、基准或判定脚本本身 | 先单独谈判定依据，不要放进循环里改 |
| 一个请求里有多种目标（例如先修 bug 再提速） | 拆成多个任务，每个一份契约、一个运行目录 |
| 几步、几天、几十个会话的大需求 | 用 `plan`，见 [references/plan.md](references/plan.md) |
| 其余能用命令判定完成的任务 | 用本技能，按下表选场景 |

| 用户的目标 | 场景 | 完成的定义 | 澄清细则 |
|---|---|---|---|
| 某个行为错了，要改对 | `bugfix` | 修复前失败的复现测试现在通过，`verify` 复查它在基线源码上仍然失败 | [references/clarify-bugfix.md](references/clarify-bugfix.md) |
| 新增或重构出一个结构 | `development` | 蓝图每个元素都被认领，回归检查为绿，竣工图与蓝图一致 | [references/clarify-development.md](references/clarify-development.md) |
| 某个指标要变好 | `optimization` | 分数越过目标线（人不设线时只看预算）；预算耗尽也照常如实交付 | [references/clarify-optimization.md](references/clarify-optimization.md) |
| 调研并给出处 | `research` | 硬检查通过，每条论断逐字对得上来源快照，细则评审（如有）达到通过线 | [references/clarify-research.md](references/clarify-research.md) |
| 写使用说明、设计文档 | `document` | 必需章节、篇幅、逐问题验收命令与 doctest 全部通过 | [references/clarify-research.md](references/clarify-research.md) |

改动触及共享状态、重试 / 超时、崩溃恢复或所有权（租约、授权）时，可以在前三个场景上**叠加形式化设计验证**，见 [references/clarify-formal.md](references/clarify-formal.md)。

## 1. 标准流程（照着做）

下面的命令都以 `J="python3 <skill>/scripts/evloop.py --home $PWD/.evloop/runs/<task>"` 开头。`<skill>` 是本技能目录的绝对路径，`$PWD` 是**工作克隆的根目录**，`<task>` 是一个短任务名。

**澄清**（读 [references/clarify.md](references/clarify.md) 和对应场景的细则）

1. 读代码，跑一遍约定命令看基线结果。
2. 把约定草案**一次性**完整呈交给人，包括：场景，可编辑路径，冻结路径，命令原文，基线结果，目标与预算，你看到的风险。
3. 等人"批准"或"修改"。人修改了，就更新草案再呈交；人批准之后才运行 `init`：

```bash
$J init --scenario bugfix --editable src/billing --frozen tests/billing \
  --test-cmd "python3 -m pytest -q tests/billing"
$J doctor                       # 全部通过再继续
```

**循环**（读 [references/loop.md](references/loop.md)）

4. 创建独立的 worktree，然后运行 `start`（它会自检裁判能否识别违规）：

```bash
git worktree add -b evloop/<task> ../<repo>-evloop-<task> HEAD
$J start --worktree ../<repo>-evloop-<task>
```

5. 在 worktree 里每改一个想法就提交一次，然后运行 `attempt`：

```bash
git -C ../<repo>-evloop-<task> commit -am "一句话说明"
$J attempt --note "改了什么、为什么"      # 优化场景加 --route <思路标签>；开发场景加 --elements <元素>
```

6. 每次 `attempt` 之后，用一两句**正文文字**告诉人：试了什么，裁决是什么，下一步打算做什么。
7. 重复第 5、6 步，直到 `$J status` 的 `decision` 变成 `handoff`。优化场景第一条路线就达标时，如果 `next` 提示预算还有余量，先换一条不同的 `--route` 再试一次，再进入交付。

**交付**（读 [references/handoff.md](references/handoff.md)）

8. 运行 `$J verify`，在保留的最优提交上重跑约定命令。
9. 在运行目录里写 `review.md`（写法见 [references/visualization.md](references/visualization.md)），然后运行 `$J report`。
10. 把 `handoff.html` 呈交给人（能内嵌预览就预览，否则给绝对路径和 `report` 输出里的 `open` 命令），然后**停下来等**。
11. 人明确批准后，运行 `$J approve --note "<评审人的原话>"`，再用普通合并把 `evloop/<task>` 合回 `branch_from`，最后移除 worktree 和循环分支。

**会话中断或上下文被压缩时**：先运行 `$J resume`，按输出里的 `next` 继续，不要凭记忆。

## 2. 读懂裁决

| 退出码 | 含义 | 工作区 | 你接下来做什么 |
|---|---|---|---|
| `0` | 接受 / 通过（`accepted`、`green`） | 成为新的最优 | 汇报，继续下一步，或看 `status` 是否已经 `handoff` |
| `1` | 未完成（`failing`、`checkpoint`） | **保留**为新的最优 | 读 `failure` 与 `tail`，在它之上继续改 |
| `1` | 拒绝（`rejected`） | 已回滚到最优 | 这条思路在当前最优之上已证伪，换一条 |
| `2` | 无效（`invalid`） | 已回滚到最优 | 越界、动了冻结文件、预检失败、编造引用等；看 stderr 的原因，改正后重试 |
| `3` | 前置条件不满足（`precondition`） | **什么都没改** | 按 stderr 的提示修正状态，然后原样重跑 |

- 只看退出码和 JSON 字段，不要凭感觉宣布完成。"测试通过了"不等于完成，`status` 给出 `decision: handoff` 才进入交付。
- 错误打印在 stderr，前缀是 `evloop: <precondition|invalid|rejected>:`。
- 所有命令的输出都是 JSON；加 `--brief` 变成单行（`--brief`、`--home` 写在子命令前后都可以）。失败的尝试带 `failure`（关键行摘要），`attempt --tail N` 控制附带的日志尾部行数。

## 3. 红线（任何情况下都不做）

1. **不改判定依据**：冻结路径（测试、基准、蓝图、文档规格、检查清单）、`contract.json`、`attempts.jsonl` 都不手改。约定确实需要变，就回到澄清，人批准后 `init --renew`。
2. **不绕过裁判**：每个改动都要提交后交给 `attempt`。不在最优提交上叠加未裁决的改动，不在裁判之外"偷偷试"。
3. **不替人批准**：只有人明确说批准之后才运行 `approve`，`--note` 必须记录评审人的原话。批准之前不合并、不删 worktree。
4. **不为"做完"放宽约定**：卡住时如实报告，不缩小范围，不删性质，不降目标。预算耗尽没达标也照常交付，结论写"未达成"。
5. **不在工作区的 `.evloop/` 下写东西**：运行目录在工作克隆里，不在循环工作区里。

## 4. 常见报错与处理

| 报错（stderr 关键词） | 原因 | 处理 |
|---|---|---|
| `--home 必须是 <repo>/.evloop/runs/ 下的一个运行目录` | 运行目录用了相对路径或放错了位置 | 用绝对路径 `$PWD/.evloop/runs/<task>`，`$PWD` 是工作克隆根目录 |
| `请在工作克隆里运行 init，而不是在链接工作区里` | 在 `git worktree add` 出来的目录里运行了 `init` | 回到主克隆运行 `init`；worktree 等 `start` 时再绑定 |
| `契约已存在；重新澄清后使用 --renew` | 同名任务已经初始化过 | 想接着做就 `resume`；约定变了，经人批准后 `init --renew` |
| `需要 --frozen` | 修复 / 优化场景没有冻结判定依据 | 把测试或基准目录加入 `--frozen` |
| `约定的测试在未改动的源码上已经通过` | 复现测试没有复现缺陷 | 先写一条在当前代码上失败的测试，经人确认后再 `init` |
| `未改动的对照重跑让分数移动了…没有低于 δ` | 基准噪声比门槛大 | 稳定基准（多次取中位数、固定种子），或和人商量调大 `--delta` / `--delta-pct` |
| `--worktree 就是工作克隆本身` / `契约目录必须在循环工作区之外` | 工作区没有独立出来 | 按第 1 节第 4 步用 `git worktree add` 在仓库旁边建 |
| `循环尚未开始；先运行 start` | 没有运行过 `start` | 运行 `start --worktree ...` |
| `HEAD 已经是最优提交；先把这次尝试提交成 commit` | 改了没提交 | 先在 worktree 里 `git commit`，再 `attempt` |
| `HEAD 不是基于当前最优…的提交` | 在旧的基础上提交了 | `git -C <worktree> reset --hard <best>`，在最优之上重做 |
| `工作区不干净` / `HEAD 不是保留的最优提交` | 有未提交或未裁决的改动 | 提交后 `attempt`，或丢弃；拿不准时先跑 `status` 看 `next` |
| `优化场景需要 --route` | 优化尝试没有命名思路 | 加 `--route <短标签>` |
| `路线…已在当前最优之上被证伪` | 重复了被拒绝的思路 | 换一条路线，或用 `--differs "这次的不同之处"` 说明 |
| `依赖尚未实现` | 认领的元素依赖还没实现的元素 | 先实现依赖，或在本次一并认领 |
| `budget exhausted` / `reserve window reached` | 预算用完了 | 不再尝试：`verify` → `report` → 如实交付 |
| `批准之前…需要一次成功的 verify` / `在最近一次 verify 之后运行 report` | 交付链不完整 | 依次运行 `verify`、`report`，呈交后再等批准 |

其余情况先运行 `doctor`，它一次性报告环境、封存、排除规则、工作区与预算的所有问题，且不修改任何状态。

## 5. 宣布完成之前自查

- [ ] `status` 的 `decision` 是 `handoff`（不是我自己判断的）。
- [ ] 最近一次 `verify` 通过，并且之后没有新的尝试。
- [ ] `review.md` 写清了做了什么、证据、未验证的部分、风险。
- [ ] `report` 在最近一次 `verify` 之后运行，`handoff.html` 已呈交给人。
- [ ] 结论没有超出证据：没测到的行为写在"未验证"里；未达标就写"未达成"。
- [ ] 还没有人批准时，我停下来等，没有 `approve`、没有合并。

## 6. 命令速查

| 命令 | 作用 |
|---|---|
| `init` | 记录约定，计算冻结哈希，跑基线（优化场景另跑一次对照），封存契约 |
| `start --worktree PATH` | 绑定循环工作区，开始计时，运行裁判自检 |
| `smoke` | 重新自检：改冻结文件、提交越界文件都必须被拒绝，回滚必须干净 |
| `attempt --note ...` | 裁决当前 HEAD；被拒或无效时回滚。可加 `--route R`、`--elements E...`、`--differs`、`--commit REV`（裁决旁路候选）、`--tokens K`、`--tail N` |
| `status` | 完整状态；`decision` 为 `continue` 或 `handoff`，`stop_reason` 说明原因，`next` 给出下一步 |
| `resume [--last N]` | 接手或上下文压缩后的单行简报 |
| `verify` | 在最优提交上重跑约定命令 |
| `report [--progress] [--open]` | 生成交付包，或生成不影响审批的进度快照 |
| `approve --note ...` | 记录人工批准，绑定最优提交、验证编号和交付包哈希 |
| `source add --url U` / `source list` | 研究 / 文档场景：按内容哈希快照来源，论断只能引用快照 |
| `relocate --repo PATH` | 运行目录随仓库迁移后重新指向新克隆 |
| `doctor` | 只读体检（`--home` 指向计划目录时检查计划） |
| `plan init/add/approve/next/done/fail/assume/prompt/status/report …` | 跨会话计划，见 [references/plan.md](references/plan.md) |

全局参数：`--brief`（单行 JSON），`--version`；`--brief` 与 `--home` 写在子命令之前或之后都生效。

各场景 `init` 的必填参数（完整示例见各细则）：

| 场景 | 必填 | 常用可选 |
|---|---|---|
| `bugfix` | `--editable` `--frozen` `--test-cmd` | `--generated` `--fast-cmd` `--max-attempts` |
| `development` | `--editable` `--blueprint` `--asis` `--asbuilt` | `--check-cmd` `--frozen` |
| `optimization` | `--editable` `--frozen` `--test-cmd` `--score-regex` `--direction` `--unit` `--delta`（或 `--delta-pct`）`--budget-minutes`；`--target` 应当给，人明确不设线时可省 | `--reserve-minutes` `--secondary-regex` `--secondary-direction` `--prefer-simpler` |
| `research` / `document` | `--editable` `--draft` `--doc-spec` | `--judge-cmd` `--rubric` `--golden-good` `--golden-bad` `--rubric-threshold` `--rubric-samples` `--allow-local-sources` |
| 叠加形式化验证 | `--formal-spec` `--model-cmd` `--checker-path` `--checker-sha256` | 后三个不要手写：先运行 `python3 <skill>/scripts/evloop_tlc.py fetch --dir <仓库外目录>`（没有 Java 11+ 时加 `--jre`），自检通过后它会打印可以直接粘贴的参数 |

任何场景都可以加成本上限 `--max-attempts` / `--token-budget`（之后每次 `attempt --tokens K` 如实上报用量）。完整测试较慢时，加一个几秒内能跑完的 `--fast-cmd`。

## 7. 参考文件（按需读取）

| 什么时候读 | 文件 |
|---|---|
| 开始任何任务前的澄清通则 | [references/clarify.md](references/clarify.md) |
| 修复场景：复现测试、影响面 | [references/clarify-bugfix.md](references/clarify-bugfix.md) |
| 开发场景：现状图、蓝图格式、范围 | [references/clarify-development.md](references/clarify-development.md) |
| 优化场景：基准、噪声、δ、预算 | [references/clarify-optimization.md](references/clarify-optimization.md) |
| 研究 / 文档场景：文档规格、论断与来源、细则评审、防注入 | [references/clarify-research.md](references/clarify-research.md) |
| 形式化设计验证：筛选、检查清单、反例分类、证据边界 | [references/clarify-formal.md](references/clarify-formal.md) |
| 跨会话计划：任务清单、会话协议、排期、停止条件 | [references/plan.md](references/plan.md) |
| 进入循环、接手进行中的循环、预算、并行候选 | [references/loop.md](references/loop.md) |
| 判断"证据够不够" | [references/verification.md](references/verification.md) |
| 进度快照与 `review.md` 怎么写 | [references/visualization.md](references/visualization.md) |
| 交付、批准、合并 | [references/handoff.md](references/handoff.md) |
| 项目宪法（跨任务的长期规则） | [references/constitution.md](references/constitution.md) |
| 换智能体 / 换模型使用、无头运行、英文速览 | [references/portability.md](references/portability.md) |
| 评测这套技能本身 | [references/evals.md](references/evals.md) |
| 代码结构与工程加固（维护者用） | [references/internals.md](references/internals.md) |

示例蓝图与宪法见 [assets/blueprint.json](assets/blueprint.json)、[assets/constitution.json](assets/constitution.json)。给只读 `AGENTS.md` 的智能体用的速读规则见 [assets/AGENTS.md](assets/AGENTS.md)，显示名称与默认提示词见 [assets/openai.yaml](assets/openai.yaml)。蓝图、现状图、竣工图可以单独预览：`python3 <skill>/scripts/evloop_render.py FILE.json`。
