# 跨智能体与跨模型使用

本技能遵循通用的技能目录格式：一个 `SKILL.md`（YAML frontmatter + 正文）加上按需读取的 `references/`、可执行的 `scripts/`、静态资源 `assets/`（技能根目录只有这四项）。评测用例与单元测试不随技能发布，放在开发仓库的 `dev/evidence-loop/` 下。裁判只依赖 Python 3.8+ 标准库与 git，不依赖任何智能体或模型的私有能力。

## Table of Contents

- 1. 安装到不同的智能体
- 2. 对不同能力的模型
- 3. 针对具体模型的适配
- 4. 实测：跨模型评测矩阵
- 5. 机器友好的输出
- 6. English quick reference

## 1. 安装到不同的智能体

把整个 `evidence-loop/` 目录放到对应智能体扫描技能的位置即可，目录名必须保持 `evidence-loop`（与 frontmatter 的 `name` 一致）：

| 智能体 | 项目级位置 | 说明 |
|---|---|---|
| 通用约定 | `.agents/skills/evidence-loop/` | 越来越多的智能体会扫描这里，推荐作为唯一实体位置 |
| 各家专用目录 | `.<agent>/skills/evidence-loop/` | 用符号链接指向通用位置，避免多份拷贝漂移 |
| 只读 `AGENTS.md` 的智能体 | 仓库根目录 `AGENTS.md` | 把技能目录里的 `assets/AGENTS.md` 内容并入，或引用它的路径 |

```bash
mkdir -p .agents/skills
cp -R <下载位置>/evidence-loop .agents/skills/
ln -s ../.agents/skills/evidence-loop .<agent>/skills/evidence-loop   # 需要时为各家目录建链接
```

`assets/openai.yaml` 为支持该格式的智能体提供显示名称与默认提示词：安装到读取 `agents/openai.yaml` 的智能体时，把它复制到技能目录下的 `agents/openai.yaml`（评测矩阵安装时自动完成），其余智能体会忽略它。

## 2. 对不同能力的模型

裁判的价值在于：**判断不依赖模型自己**。模型越弱，越要把判断交给命令。

| 模型特点 | 建议 |
|---|---|
| 上下文窗口小、易被压缩 | 每轮只看 `attempt` 的单行输出；接手时只跑 `resume`；所有 JSON 命令加 `--brief`；`--tail` 调小（如 `--tail 8`） |
| 指令遵循较弱、容易"自己宣布完成" | 依赖退出码而不是读文字：`0` 才算接受；只有 `status` 的 `decision` 为 `handoff` 才进入交付；在宪法里设 `max_attempts` 兜底 |
| 擅长长程推理、愿意多试 | 用 `--route` / `--differs` 管理思路；必要时用 `attempt --commit` 并行生成、串行裁决；`--prefer-simpler` 防止复杂度堆积 |
| 工具调用昂贵或按 token 计费 | `--token-budget` + `attempt --tokens` 上报用量；`--fast-cmd` 先挡掉明显失败的尝试 |
| 不能执行命令、只能写代码 | 不适用本技能：没有裁判就没有证据，改用普通的代码评审流程 |

无论哪种模型，下面三条都不变：不手改契约与记录；不绕过 `attempt` 叠加改动；不替人运行 `approve`。

## 3. 针对具体模型的适配

下面两节是按官方文档整理的已知差异与对策。差异会随版本变化，判断是否仍然成立请用第 4 节的评测矩阵实测，不要凭印象。

### 3.1 GPT-6（Codex CLI）

| 差异 | 对本技能的影响 | 对策 |
|---|---|---|
| 技能扫描 `.agents/skills/`，并读取 `agents/openai.yaml` | 需要显示名称与默认提示词时多一步 | 按第 1 节放到通用位置，再把 `assets/openai.yaml` 复制为 `agents/openai.yaml` |
| `codex exec` 默认只读沙箱；`workspace-write` 下 `.git` 仍是只读 | `start` 的自检、每次提交、`git worktree add` 都会失败 | 用 `-c sandbox_mode="workspace-write"`，并在 `sandbox_workspace_write.writable_roots` 里加入仓库的上一级目录与 `<repo>/.git` |
| 循环工作区约定在仓库旁边（`../<repo>-evloop-<task>`），位于启动目录之外 | 不加可写根时只能读不能写 | 同上（评测矩阵把仓库的上一级目录设为可写根） |
| `exec resume` 不接受 `-s` | 续写会话时沙箱参数报错 | 沙箱一律通过 `-c` 传入（首轮与续写都适用） |
| 输出风格偏短，倾向一次做完再汇报 | 容易省掉规则 4 要求的"每次 `attempt` 后一两句话" | 在任务提示里明确要求逐轮汇报；用 `--json` 事件流核对 `attempt` 次数 |
| `--json` 输出 JSONL 事件（`thread.started` 带会话 ID，`turn.completed` 带用量） | 便于无人值守评测 | 用 `turn.completed` 的用量配合 `attempt --tokens` 与 `--token-budget` |

推荐：推理强度 `high`；优化场景 `xhigh` 仅在预算宽裕时使用。

### 3.2 Claude Opus 5.5（Claude Code）

| 差异 | 对本技能的影响 | 对策 |
|---|---|---|
| 技能扫描 `.claude/skills/`；没有 `CLAUDE.md` 时读取 `AGENTS.md` | 无需额外配置；想在仓库级常驻规则时并入 `assets/AGENTS.md` | 放在 `.claude/skills/evidence-loop/`，或用符号链接指向通用位置 |
| 默认推理强度为 medium | 开发与优化场景（多轮、要比较路线）容易过早收手 | `--effort high`，长时间优化用 `xhigh` |
| 思考过程默认不展示 | 人看不到过程，与规则 4"过程可见"冲突 | 不依赖思考过程：每次 `attempt` 后由模型输出一两句文字汇报，关键节点跑 `report --progress` |
| 可能以一段文字更新结束本轮 | 无头模式（`-p`）会在中途停下，循环没跑完 | 无人值守时用续写轮（`--resume`），评测矩阵用 `--max-turns` |
| 不复述完整推理记录 | 要求"贴出思考过程"会被拒绝或变形 | 只要求可核对的产物：`attempt` 输出、`review.md`、`report` |
| `-p` 需要显式权限模式，续写时要重新传 | 续写轮权限丢失，命令被拦 | 每一轮都带 `--permission-mode`；只在一次性仓库里放开权限 |

推荐：推理强度 `high`；用 `--add-dir` 把仓库的上一级目录加入可访问范围，让循环工作区可写。

### 3.3 两者共同

- 澄清阶段"一次性呈交约定、等人确认"在无头模式下没有人回复：评测时用模拟评审人的续写消息代替（评测矩阵自带），真实使用时让人回复。
- 两个模型都可能把"测试通过"当作完成：一律以 `status` 的 `decision` 为准。
- 不要在提示里放评测用例或测试——评测用例与测试本来就不在技能目录里，评测矩阵安装技能时也会再排除一次 `evals/` 与 `tests/`。

## 4. 实测：跨模型评测矩阵

`scripts/evloop_matrix.py` 在本机已安装、已登录的 `codex` 与 `claude` 命令行上，把开发仓库 `dev/evidence-loop/evals/evals.json`（或环境变量 `EVLOOP_EVALS_DIR` 指向的目录、`--evals-file` 指定的文件）的每条用例各跑一遍（带技能 / 不带技能），机械评分并按模型汇总。它只调用官方命令行，不直接访问任何模型接口。

```bash
python3 <skill>/scripts/evloop_matrix.py plan --workspace /tmp/evloop-matrix --eval 1 8   # 只看命令
python3 <skill>/scripts/evloop_matrix.py run  --workspace /tmp/evloop-matrix \
  --agents codex claude --effort high --max-turns 4
```

模型名默认是 `gpt-6-sol` 与 `claude-opus-5-5`，可用 `--codex-model` / `--claude-model` 覆盖；结果的读法见 [evals.md](evals.md)。

## 5. 机器友好的输出

- 所有命令的结果都是 JSON（`resume` 固定为单行；其余命令加 `--brief` 变成单行，`--brief` 与 `--home` 写在子命令前后都可以）。
- 退出码：`0` 接受 / 通过，`1` 拒绝 / 失败 / 检查点，`2` 无效（已回滚），`3` 前置条件不满足（什么都没改）。
- 错误统一打印到 stderr，格式为 `evloop: <precondition|invalid|rejected>: 原因`，可以直接按前缀分支。
- 未通过的尝试带 `failure`（关键行摘要）与 `tail`（日志尾部），不需要再去翻 `raw/`。

- 跨会话计划时，排期用你所在平台自己的定时任务能力；evloop 只给出 `plan prompt` 的提示词与 `schedule.delay_seconds`，不常驻、不排期。
- 细则评审命令由用户配置，建议用与写草稿不同的模型；裁判本身不调用任何模型接口。

## 6. English quick reference

`evidence-loop` is a mechanical judge for long-running autonomous coding loops. Flow: **clarify** (agree on editable paths, frozen paths, commands, targets and budgets once, then `init` seals a contract) → **loop** (commit an attempt in a dedicated git worktree, run `attempt`; rejected or invalid attempts are rolled back automatically) → **handoff** (`verify` re-runs the agreed commands on the kept best commit, `report` builds `handoff.html`, a human approves, then merge).

Scenarios: `bugfix` (a reproduction test must fail before and pass after; `verify` re-checks red on the baseline source), `development` (blueprint elements with dependencies and optional per-element `accept` commands; an as-built diagram must match the blueprint), `optimization` (one numeric score, noise-checked δ, optional target, wall-clock budget; optional secondary metric and a simplicity rule).

Useful flags for agents: `resume` (one-line state brief after context loss), `--brief` (compact JSON; `--brief`/`--home` may go before or after the subcommand), `attempt --tail N` (log tail on failure), `--max-attempts` / `--token-budget` (cost caps), `--fast-cmd` (cheap pre-check), `attempt --commit REV` (judge side-branch candidates one at a time). Never edit the contract, never bypass `attempt`, never approve on the human's behalf. Exit codes: `0` new best; `1` failing (kept as best) or rejected (rolled back); `2` invalid (rolled back); `3` precondition (nothing changed). Treat only `status` → `decision: handoff` as done.

Research and documents: `research` / `document` scenarios use `--draft` and a frozen `--doc-spec`; `source add` snapshots sources by content hash, claims must quote snapshots verbatim, fabricated citations and prompt-injection text are invalid, and an optional rubric judge (`--judge-cmd`, calibrated on golden good/bad samples, median of K samples) can only veto. Cross-session plans: `plan init/next/done/fail/prompt` keep a sealed task list under `.evloop/plans/<project>`; one task per session, `done` needs judge evidence, and `plan prompt` returns a self-contained next-session prompt plus a delay for the agent's own scheduler.

Per-model notes: on Codex CLI make the parent directory and `<repo>/.git` writable roots (the default sandbox keeps `.git` read-only) and pass the sandbox via `-c` so `exec resume` works; on Claude Code use `--effort high`, re-pass `--permission-mode` on every `--resume`, and report each attempt in plain text because thinking is hidden by default. Measure instead of guessing: `scripts/evloop_matrix.py run --agents codex claude`.
