# skills

我自己在用的 9 个 agent skill，都遵循 `SKILL.md` 规范。用来给 Claude Code（以及其他支持同一规范的 agent）加能力——飞书画板配图、系列文档批量产出、自主工程循环、方案追问、生活决策查询等。

skill 不是工具、不是 MCP——每个目录就是一份流程规约加几个脚本：规定 agent 在什么场景触发、按什么步骤做、做到什么标准算完成。

## 装

```bash
git clone https://github.com/zyaochen/skills.git
cd skills
ln -s "$PWD/skills/lark-figure" ~/.claude/skills/lark-figure
```

软链指向 `skills/<name>` 目录本身；`git pull` 之后立即生效，不用重启会话。想只用某一版就复制目录过去，不要软链。

## 一览

| skill | 干什么 |
|---|---|
| [evidence-loop](skills/evidence-loop/SKILL.md) | 带机械裁判的自主工程循环：修 bug、按蓝图开发、压指标、带出处的调研；每次改动要么保留要么回滚，裁判按约定判定做完了 |
| [lark-figure](skills/lark-figure/SKILL.md) | 飞书画板配图：模型只写内容 spec，14 种图型的排版、配色、走线全由脚本算 |
| [lark-series-builder](skills/lark-series-builder/SKILL.md) | 批量写完或重写一整套飞书系列文档：主编定规范、派活、验收，正文交给子 agent |
| [monument-valley](skills/monument-valley/SKILL.md) | 把一个主题的公开材料做成纪念碑谷式可探索档案：关卡叙事加统一等距插画 |
| [thought-distillation](skills/thought-distillation/SKILL.md) | 把一个人或团队的全部写作精读后串成一条主线，产出图文并茂的飞书文档 |
| [skill-guide-writer](skills/skill-guide-writer/SKILL.md) | 以本地证据为先，给已有 skill、工具、插件写 Quick Start 和升级说明 |
| [life-decision-guide](skills/life-decision-guide/SKILL.md) | 基于《高性价比人生指南》离线快照回答具体生活选择，注明出处 |
| [grilling](skills/grilling/SKILL.md) | 按 design tree 逐轮追问方案、决策或想法，直到没有隐含假设 |
| [grill-me](skills/grill-me/SKILL.md) | `grilling` 的手动入口（`/grill-me`），不让模型自动触发 |

## 依赖

按上手门槛从高到低：

| skill | 需要 |
|---|---|
| lark-figure、lark-series-builder、monument-valley、thought-distillation | 已登录的 `lark-cli`（`lark-cli auth login`，user 身份）；lark-figure 本地预览还要 Node（`npx @larksuite/whiteboard-cli`） |
| lark-series-builder 的本地预览 | macOS Quick Look（`qlmanage`） |
| evidence-loop | Python 3.8+、git 2.20+；形式化模式另需 Java 11+，首次运行 `evloop_tlc.py fetch --jre` 下载钉死版本的 `tla2tools.jar` |
| monument-valley | Pillow 可选，macOS 上没装则回退 `sips` |
| skill-guide-writer、life-decision-guide、grilling、grill-me | Python 3.8+ 标准库即可 |

## 测试

测试放在 `dev/<name>/`，不属于技能本体，安装时不用复制。在仓库根目录跑：

```bash
python3 -m unittest discover -s dev/evidence-loop/tests -p 'test_*.py'
python3 -m unittest discover -s dev/lark-figure          -p 'test_*.py'
python3 -m unittest discover -s dev/life-decision-guide  -p 'test_*.py'
python3 -m unittest discover -s dev/monument-valley      -p 'test_*.py'
python3 -m unittest discover -s dev/thought-distillation -p 'test_*.py'
bash skills/lark-series-builder/scripts/selftest.sh      # 期望输出 SELFTEST OK
```

测试按相对路径引用 `skills/<name>`，所以必须在仓库根目录运行。

## 限制与边界

- 4 个写飞书的 skill（lark-figure / lark-series-builder / monument-valley / thought-distillation）都在你确认后才真写。lark-figure 的 `put` 默认 dry-run，要加 `--yes` 才落笔。
- evidence-loop 在独立 worktree 跑长任务，交回主分支前要经你批准——不是无脑自治。
- thought-distillation 的整篇 publish 用 `overwrite`，会丢原评论和画板，只能对它自己新建的文档用；已有文档请走 update 路径。
- `dev/lark-figure/eval/results/` 是 2026 年几次模型评测的原始输出，只说明当时的表现，不构成效果承诺。
- grilling 期间模型只能问，不替你下决定；evidence-loop 的裁判只看约定是否达成，不评价代码好坏。

## 排障

| 现象 | 怎么办 |
|---|---|
| 装了却不触发 | 软链必须指向 `skills/<name>` 目录本身而不是父目录，再开一个新会话。agent 按 `SKILL.md` 的 `description` 决定何时调用 |
| 测试 ImportError 或找不到技能 | 你必须在仓库根目录跑；`dev/<name>/` 里的测试靠相对路径找 `skills/<name>/` |
| 写飞书报权限错 | 跑 `lark-cli auth status` 确认 user 身份已登录，且有文档和画板的写权限 |

## 目录

```text
skills/
  <name>/
    SKILL.md            # 入口：触发条件、流程、硬约束
    references/         # 按需加载的细则
    scripts/            # skill 实际跑的脚本
dev/
  <name>/
    tests/              # 对应 skill 的单元测试与评测
LICENSE                 # 自写部分 MIT
```

## 上游与许可

自写部分 MIT，见 [LICENSE](LICENSE)。

两个 skill 改编自上游，沿用上游许可：

- `life-decision-guide`——改自 [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)（@ `24e3d67`），Unlicense。
- `grilling` 和 `grill-me`——镜像 [mattpocock/skills](https://github.com/mattpocock/skills) 的早期快照，MIT。和上游最新版只有格式差异。
