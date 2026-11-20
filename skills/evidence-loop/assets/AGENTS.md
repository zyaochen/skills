# evidence-loop：给智能体的速读规则

完整说明见 [SKILL.md](../SKILL.md)，跨智能体 / 跨模型用法见 [references/portability.md](../references/portability.md)。只读 `AGENTS.md` 的智能体：把本文件并入仓库根目录的 `AGENTS.md`。

## 何时启用

用户要求在明确边界内长时间自主推进、并要求结果可验证时：缺陷修复（`bugfix`）、按蓝图开发（`development`）、基准优化（`optimization`）、带出处的研究（`research`）、文档（`document`）。比单个任务大的需求用 `plan` 拆成跨会话的任务清单（见 [references/plan.md](../references/plan.md)）。

不启用：改错别字、改一行配置等一次性小改动（直接做）；完成标准写不成一条命令的任务（先和人谈清）；需要修改测试或基准本身的任务（先单独谈判定依据）。

## 红线

1. 不手工编辑运行目录下的 `contract.json`、`attempts.jsonl`，不修改冻结路径（测试、基准、判定脚本）。约定要变，回到澄清，人批准后 `init --renew`。
2. 每次改动都提交后交给 `attempt` 裁决；不绕过裁判在最优提交上叠加改动。
3. 不替人运行 `approve`，不自行合并；`approve --note` 必须记录评审人的原话。
4. 卡住或预算耗尽时如实交付"未达成"，不缩范围、不降目标。

## 标准流程

```bash
J="python3 <skill>/scripts/evloop.py --home $PWD/.evloop/runs/<task>"   # $PWD 是工作克隆根目录，必须是绝对路径
# 1. 澄清：约定草案一次性交给人，人批准后才 init
$J init --scenario bugfix --editable src/x.py --frozen tests --test-cmd "python3 -m pytest -q tests/test_x.py"
$J doctor
# 2. 循环：独立 worktree，每个想法提交一次再 attempt
git worktree add -b evloop/<task> ../<repo>-evloop-<task> HEAD
$J start --worktree ../<repo>-evloop-<task>
git -C ../<repo>-evloop-<task> commit -am "一句话说明"
$J attempt --note "做了什么、为什么"
$J status                              # decision 为 handoff 才进入交付
# 3. 交付：verify → 写 review.md → report → 呈交 handoff.html → 停下等批准
$J verify && $J report
$J resume                              # 会话中断或上下文压缩后先跑这一条
```

退出码：`0` 接受（成为新的最优）；`1` 未完成（`failing` / `checkpoint`，保留为最优，接着改）或拒绝（`rejected`，已回滚，换思路）；`2` 无效（越界、动冻结文件、编造引用等，已回滚）；`3` 前置条件不满足（什么都没改，按 stderr 修正后原样重跑）。

- 判断只看退出码与 JSON 字段，不凭自己的感觉宣布完成。拿不准下一步时跑 `status` 或 `doctor`，按输出里的 `next` 做。
- 所有 JSON 命令可加 `--brief` 得到单行输出（写在子命令前后都行）；失败的尝试带 `failure` 摘要与 `tail` 日志尾部。
- 每次 `attempt` 后用正文文字汇报：试了什么、裁决是什么、下一步做什么（思考过程可能对人不可见）。
- 无头 / 非交互运行时，确保循环工作区（仓库的上一级目录）与 `<repo>/.git` 可写，否则提交与 `start` 自检会失败；细节见 [references/portability.md](../references/portability.md)。
- 研究 / 文档：先 `source add` 再引用，论断摘录从快照原样复制；草稿里不要写任何给评审的指令。
- 计划：每个会话只推进一个任务，`plan done` 被认可后再 `plan prompt` 排期；`decision` 为 `stop` 时不再排期，不手工改 `plan.json` / `state.json`。
- 形式化设计验证（改动涉及并发、重试、崩溃恢复、租约时）：先用 `scripts/evloop_tlc.py fetch --dir <仓库外目录>`（无 Java 11+ 加 `--jre`）准备检查器并拿到参数，再给 `init` 加 `--formal-spec` 等四个参数；约定案例必须 verified，每条反例先分类为设计缺陷 / 建模缺陷 / 需求歧义再改，不删性质、不把故障假设掉、不缩范围；对外只说"在指定模型、参数与假设下未发现违例"。见 [references/clarify-formal.md](../references/clarify-formal.md)。
- 需要成本上限时在 `init` 加 `--max-attempts` / `--token-budget`，并用 `attempt --tokens` 上报用量。

## 宣布完成之前

`status` 为 `handoff`；最近一次 `verify` 通过且之后没有新尝试；`review.md` 写清证据与未验证部分；`report` 在 `verify` 之后运行且 `handoff.html` 已呈交；没有人批准时停下等待。

## English summary

Use it only when "done" can be judged by a command; skip trivial edits. Clarify once (editable paths, frozen paths, commands, targets, budgets) and wait for approval → `init` seals a contract → commit each change in the dedicated worktree and run `attempt` (exit 0 = new best; 1 = failing-but-kept or rejected-and-rolled-back; 2 = invalid, rolled back; 3 = precondition, nothing changed) → when `status` says `handoff`, run `verify`, write `review.md`, run `report`, present `handoff.html`, then stop and wait for an explicit human approval. Never edit the contract or frozen files, never bypass `attempt`, never approve on the human's behalf, never shrink the goal just to finish. After context loss, run `resume` first. For research/documents, register sources with `source add` and quote them verbatim. For concurrency/retry/recovery/ownership designs, add `--formal-spec` with a pinned model checker: contract cases must be verified, counterexamples are triaged, never weakened away. For multi-session work, use `plan`: one task per session, `plan done` needs judge evidence, then `plan prompt` gives the next-session prompt for your own scheduler.
