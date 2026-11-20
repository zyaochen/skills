# 跨会话计划：一个想法，多次会话，裁判把关

单个运行目录解决"一个任务做没做完"。很多需求比这大：一个想法要拆成几步，每步都要单独验证，还可能跨越几天、几十个会话。`plan` 把这件事落到磁盘上：

```
想法 → 澄清 → 计划（任务 + 验收 + 依赖）→ 每个会话推进一个任务 → 更新状态 → 排期下一会话 → … → 停止条件命中
```

计划目录固定在 `<repo>/.evloop/plans/<project>/`，以 `--home` 传入（不在这个位置会被拒绝）：

| 文件 | 内容 |
|---|---|
| `plan.json` | 目标、模式、配置、任务、假设；带封存哈希 |
| `state.json` | 任务状态、失败计数、会话数、停止标记、批准；带封存哈希 |
| `plan-log.jsonl` | 只追加的事件日志，用于监控与复盘 |

## 1. 任务清单

```json
[{"id": "spec",  "title": "写清接口约定", "scenario": "document"},
 {"id": "impl",  "title": "实现导出接口", "scenario": "development", "depends": ["spec"], "approve": true},
 {"id": "perf",  "title": "导出 p99 压到 200ms", "scenario": "optimization", "depends": ["impl"]},
 {"id": "smoke", "title": "冒烟脚本可跑", "check": "bash scripts/smoke.sh", "depends": ["impl"],
  "max_attempts": 2}]
```

- `scenario` 与 `check` 二选一。`scenario` 表示这个任务由一个 evloop 运行目录裁决，`run` 默认 `.evloop/runs/<id>`；`check` 是一条命令，退出码 0 即完成。
- `depends` 只能指向前面已登记的任务，因此天然无环。
- `max_attempts`：这个任务最多失败几个会话后判为失败，默认 3。
- `approve`：完成前需要人已批准运行目录的交付包。
- `notes`：给下一会话的补充说明。

## 2. 创建与模式

```bash
P="python3 <skill>/scripts/evloop.py --home $PWD/.evloop/plans/<project>"
$P plan init --repo . --goal "一句话：做完之后什么成立" --mode confirm --tasks tasks.json \
  --max-consecutive-failures 3 --cycle-hours 48 --delay-minutes 5
$P plan add --id docs --title "补使用说明" --scenario document --depends impl
```

- **确认模式**（`confirm`，默认）：计划呈交给人，人同意后运行 `plan approve --note "<原话>"` 才开始执行。批准绑定计划内容指纹，之后再 `plan add` 或修改计划，批准自动失效，需要重新批准。
- **自动模式**（`auto`）：不等计划批准，适合人已经授权、只想事后复核的场景。遇到小决定时自行决定，但必须用 `plan assume --text "…" [--task ID]` 记录假设（`init --assume` 可预先记录）；交付时人逐条复核。删除数据、对外发布、花钱的决定仍然要停下来问人。

澄清阶段照常只打扰一次：把目标、任务、每个任务怎么验收、依赖、停止条件一次性呈交。

## 3. 每个会话的协议

1. `plan next`：先检查停止条件。命中则输出 `decision: stop` 与 `stop_reason`，向人汇报后结束，**不再排期**；否则领取一个就绪任务（依赖都已完成），会话数加一。
2. 推进这个任务：
   - 带 `run` 的任务：先对运行目录 `resume`；运行目录不存在时按场景澄清、`init`、`start`。然后照常循环，直到 `status` 为 `handoff`，再 `verify`、`report`。
   - 带 `check` 的任务：直接完成工作。
   - 领到的任务若仍是 `active`（上一会话既没 `done` 也没 `fail` 就结束了——崩溃、超时或忘了记录），`plan next` 先记一次 `abandoned` 失败，计入 `max_attempts` 与连续失败，防止崩溃的会话无限重来；输出里的 `last_reason` 写着上次卡在哪里。
3. `plan done --task ID`：裁判核对证据。运行目录必须达成目标、最终验证有效（任务要求批准时还要已批准），或 `check` 命令退出码为 0。证据不成立返回 1，任务保持未完成——**说完成不算，裁判认可才算**。没能完成就 `plan fail --task ID --reason "卡在哪里"`，任务交还待办，下一会话的提示词会带上这条原因。
4. 先更新状态，再排期：`plan prompt --out next.md` 生成一段自包含的下一会话提示词和建议延迟 `schedule.delay_seconds`。`decision` 为 `continue` 时，在调用定时任务之前的最后一刻计算触发时间（当前时间 + 延迟），用你所在平台的定时任务能力排期，提示词就用 `next.md` 的内容。

evloop 自己不排期、不常驻、不开端口；它只给出"该不该继续"和"下一会话该看什么"。下一会话不依赖任何记忆，提示词里有仓库、计划目录、裁判路径、协议与安全规则，以及自动模式下已记录的假设。

## 4. 停止条件

`plan next`、`plan prompt` 按以下顺序判定，命中第一条即停止：

| `stop_reason` | 含义 | 怎么恢复 |
|---|---|---|
| `plan tampered` | `plan.json` 或 `state.json` 被手工改动（封存哈希对不上） | 人查明原因后 `plan init --renew` 重建 |
| `stopped` | 人运行了 `plan stop --reason …` | `plan restart` |
| `all done` | 全部任务完成 | 交付 |
| `too many failures` | 连续失败会话数达到 `--max-consecutive-failures` | 人看过后 `plan restart --note …` |
| `cycle exhausted` | 从开始计时起超过 `--cycle-hours` | `plan restart` 重新计时 |
| `blocked` | 剩余任务都被失败的依赖卡住 | `plan retry --task ID --note …` |
| `awaiting plan approval` | 确认模式下计划未批准，或批准后计划被修改 | `plan approve` |

一个任务失败次数达到 `max_attempts` 就判为 `failed`，依赖它的任务全部被卡住；成功完成任何任务会把连续失败计数清零。

## 5. 防篡改

- 计划与状态都带封存哈希。手工改 `state.json` 把任务标成完成，下一次 `plan next` / `done` / `status` / `prompt` 会以退出码 2 报 `plan tampered` 并拒绝继续。
- 计划目录有文件锁，两个会话同时推进同一个计划会立刻失败。
- 所有变更写进 `plan-log.jsonl`；被拒绝的 `done`（`done_refused`）也会记录。
- 任务的验收依据（运行目录的冻结文件、`check` 命令）由计划和契约封存，智能体不能为了过关去改它们。

## 6. 监控

- `doctor --home <计划目录>`：只读体检——封存、任务与状态是否一致、仓库、每个未完成任务的运行目录契约与下一步、停止条件。
- `plan status [--last N]`：只读监控视图——每个任务的状态、失败次数、会话数、最近一次失败原因，计数汇总，停止条件，确认模式下计划是否已批准，最近 N 条事件。
- `plan report [--out FILE]`：生成自包含的 `plan.html`：按状态着色的任务依赖图、任务表、假设与最近事件。
- 每个任务的运行目录照常有自己的 `report --progress` 与交付包。
