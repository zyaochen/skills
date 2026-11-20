# 项目宪法：跨任务长期生效的规则

宪法是仓库里的一个 JSON 文件，默认位置 `.evloop/constitution.json`（也可以用 `init --constitution PATH` 指定）。每次 `init` 都会读取它，把规则合并进契约。它适合放那些"不管做什么任务都不能破"的底线。

## 1. 字段

```json
{
  "frozen": ["tests/golden", "benchmarks/harness"],
  "generated": ["build", ".pytest_cache"],
  "guard_cmd": "python3 -m compileall -q src",
  "fast_cmd": "python3 -m pytest -q -x tests/smoke",
  "budget": {"default_minutes": 60, "max_minutes": 240, "reserve_minutes": 10,
             "max_attempts": 40, "token_budget": 2000000}
}
```

| 字段 | 作用 |
|---|---|
| `frozen` | 每个任务都冻结的路径；与 `--frozen` 合并，并计入冻结哈希 |
| `generated` | 每个任务都声明的运行产物路径；与 `--generated` 合并 |
| `guard_cmd` | 底线检查：`init` 时先在未改动的源码上跑一次，之后每次尝试与 `verify` 都先跑它，失败即判无效 |
| `fast_cmd` | 默认的快速预检：`init` 未给 `--fast-cmd` 时采用；基线上必须通过，之后每次尝试在底线检查之后、完整测试之前运行 |
| `budget.default_minutes` | 优化场景未给 `--budget-minutes` 时的默认预算 |
| `budget.max_minutes` | 任何场景预算的上限，超出时 `init` 拒绝 |
| `budget.reserve_minutes` | 优化场景未给 `--reserve-minutes` 时的默认预留 |
| `budget.max_attempts` | 任何场景未给 `--max-attempts` 时的默认尝试次数上限 |
| `budget.token_budget` | 任何场景未给 `--token-budget` 时的默认 token 上限 |

示例文件见技能目录下的 `assets/constitution.json`。

## 2. 严格校验

- 未知字段（包括 `budget` 下的未知字段）一律拒绝，避免拼写错误让规则悄悄失效。
- `frozen` / `generated` 必须是非空字符串列表，`guard_cmd` / `fast_cmd` 必须是非空字符串，预算必须是非负数，`max_attempts` / `token_budget` 必须是正整数。
- 宪法的 `frozen` 也会与可编辑范围做冲突检查。
- 底线检查在未改动的源码上就失败时，`init` 拒绝——已经失守的底线无法用来裁决尝试。

## 3. 封存与漂移

`init` 时记录宪法文件的路径与 sha256。之后宪法被修改或删除：

- `start` 拒绝开始；
- 每次 `attempt` 判无效；
- `status` 报告 `constitution_drift`，批准随之失效；
- `relocate` 要求新克隆里的宪法与原来完全一致；
- `doctor` 把它列为失败项。

想改宪法，就在两个任务之间改，然后对需要的任务重新澄清并 `init --renew`。

## 4. 是底线，不是天花板

宪法只规定最低要求。具体任务可以冻结更多路径、给更窄的可编辑范围、设更短的预算；但不能让预算超过上限，也不能把宪法冻结的路径变成可编辑。

## 5. 怎么选底线检查

好的 `guard_cmd`：快（几秒到几十秒）、稳定（不依赖网络与时间）、和任务无关但能拦住明显的破坏——语法检查、类型检查、lint、关键冒烟测试。不要把慢的完整测试放进来，它会吃掉每一轮的预算；完整测试属于具体任务的 `--test-cmd`。

## 6. 让它慢慢长大

从空宪法开始。每次交付时回顾：这次循环里是否出现过"差点改了不该改的东西"、"本该每次都检查的东西"？把它们作为一条提议交给人，人同意后再加进宪法。
