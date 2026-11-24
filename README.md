# skills

我在用的 9 个 agent skill。用来给 Claude Code 加能力——画飞书画板、批量产文档、跑自主工程循环、追问方案、答生活决策。每个目录一份 `SKILL.md`，规定 agent 什么时候触发、怎么干、怎么算干完。

## 装

```bash
git clone https://github.com/zyaochen/skills.git
ln -s "$PWD/skills/skills/lark-figure" ~/.claude/skills/lark-figure
```

不要软链 `skills/` 整层，要链到 `skills/<name>` 本身；`git pull` 即生效。

## 一览

| skill | 干什么 |
|---|---|
| [evidence-loop](skills/evidence-loop/SKILL.md) | 自主工程循环：机械裁判按约定判定做完，每次改动要么保留要么回滚 |
| [lark-figure](skills/lark-figure/SKILL.md) | 飞书画板配图：模型只写内容 spec，脚本按 14 种图型排版、配色、走线 |
| [lark-series-builder](skills/lark-series-builder/SKILL.md) | 批量写或重写飞书系列文档：主编定规范、派活、验收，正文交给子 agent |
| [monument-valley](skills/monument-valley/SKILL.md) | 把一个主题的公开材料做成纪念碑谷式可探索档案 |
| [thought-distillation](skills/thought-distillation/SKILL.md) | 把一个人或团队的全部写作串成一条主线，产出飞书长文 |
| [skill-guide-writer](skills/skill-guide-writer/SKILL.md) | 给已有 skill、工具、插件写 Quick Start 和升级说明，本地证据优先 |
| [life-decision-guide](skills/life-decision-guide/SKILL.md) | 基于《高性价比人生指南》离线快照回答生活选择，注明出处 |
| [grilling](skills/grilling/SKILL.md) | 按 design tree 逐轮追问方案、决策或想法，直到没有隐含假设 |
| [grill-me](skills/grill-me/SKILL.md) | `/grill-me` 手动触发 `grilling`，不让模型自动接管 |

## 依赖

按上手门槛从高到低：

| skill | 需要 |
|---|---|
| lark-figure、lark-series-builder、monument-valley、thought-distillation | 登录后的 `lark-cli`（user 身份）；lark-figure 本地预览另要 Node（`npx @larksuite/whiteboard-cli`） |
| lark-series-builder 本地预览 | macOS Quick Look |
| evidence-loop | Python 3.8+、git 2.20+；形式化模式另需 Java 11+ |
| monument-valley | Pillow 可选；macOS 上未装则回退 `sips` |
| skill-guide-writer、life-decision-guide、grilling、grill-me | Python 3.8+ 标准库即可 |

## 测试

在仓库根目录跑：

```bash
python3 -m unittest discover -s dev/evidence-loop/tests -p 'test_*.py'
python3 -m unittest discover -s dev/lark-figure          -p 'test_*.py'
python3 -m unittest discover -s dev/life-decision-guide  -p 'test_*.py'
python3 -m unittest discover -s dev/monument-valley      -p 'test_*.py'
python3 -m unittest discover -s dev/thought-distillation -p 'test_*.py'
bash skills/lark-series-builder/scripts/selftest.sh      # 期望输出 SELFTEST OK
```

测试放在 `dev/<name>/`，靠相对路径反向引用 `skills/<name>`。装的时候不用带。

## 限制

- 4 个写飞书的 skill 都在你确认后才真写。`lark-figure put` 默认 dry-run，加 `--yes` 才落笔。
- `evidence-loop` 在独立 worktree 跑长任务，回主分支前等你批准。
- `thought-distillation` 的整篇 publish 用 `overwrite`，会丢原评论和画板，只对它自己新建的文档用。
- `dev/lark-figure/eval/results/` 是 2026 年评测的原始输出，说明当时表现，不是效果承诺。
- `grilling` 期间模型只问不答；`evidence-loop` 的裁判只校验约定达成，不评价代码好坏。

## 排障

| 现象 | 怎么办 |
|---|---|
| 装了不触发 | 软链要指到 `skills/<name>` 目录本身而不是父目录，再开一个新会话 |
| 测试找不到 skill | 必须在仓库根目录跑，`dev/<name>` 靠相对路径引用 `skills/<name>` |
| 写飞书报权限错 | `lark-cli auth status`，确认 user 已登录且有文档和画板的写权限 |

## 许可

自写部分 MIT，见 [LICENSE](LICENSE)。

两个改编自上游的 skill 沿用上游许可：

- `life-decision-guide` — [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter) @ `24e3d67` · Unlicense
- `grilling` / `grill-me` — [mattpocock/skills](https://github.com/mattpocock/skills) 早期快照 · MIT
