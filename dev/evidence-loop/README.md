# evidence-loop 开发资产

不随技能发布的部分：技能本体在 [../../skills/evidence-loop](../../skills/evidence-loop/SKILL.md)，发布包根目录只有 `SKILL.md`、`scripts/`、`references/`、`assets/`。

| 目录 | 内容 |
|---|---|
| `tests/` | 单元与端到端测试：`cd tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest`（可用 `EVLOOP_SKILL_DIR` 指向别处的技能目录） |
| `evals/` | 技能评测用例 `evals.json` 与夹具 `fixtures/`；评测矩阵默认会找到这里，也可用 `EVLOOP_EVALS_DIR` 或 `--evals-file` 指定 |
