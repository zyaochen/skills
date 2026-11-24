# skills

我自己日常在用的 agent skill 集合，共 9 个。遵循 `SKILL.md` 规范，Claude Code 和其他支持该规范的 agent 都能用。

skill 不是工具也不是 MCP：每个目录就是一份流程规约加若干脚本，规定 agent 在什么场景触发、按什么步骤做、做到什么标准算完成。

## 装

```bash
git clone https://github.com/zyaochen/skills.git
cd skills
ln -s "$PWD/skills/lark-figure" ~/.claude/skills/lark-figure   # 按需逐个软链，注意软链的是 skills/<name> 这层
```

```text
$ ls ~/.claude/skills/
lark-figure
```

软链指到目录本身；`git pull` 后无需任何重启。不要软链 `skills/` 整层，不要把多个 skill 平铺在一个父目录下。

## 9 个 skill 一览

| skill | 一句话用途 | 上游 / 许可 |
|---|---|---|
| [evidence-loop](skills/evidence-loop/SKILL.md) | 机械裁判驱动的自主工程循环：修 bug、按蓝图开发、压指标、调研，结果要么保留要么回滚 | 自写 · MIT |
| [lark-figure](skills/lark-figure/SKILL.md) | 飞书画板配图：模型只写内容 spec，排版/配色/走线由 14 种图型的脚本生成，过 lint 后写入画板 | 自写 · MIT |
| [lark-series-builder](skills/lark-series-builder/SKILL.md) | 批量写完或提质一整套飞书系列文档：主编定规范、派活、验收，正文交给子 agent | 自写 · MIT |
| [monument-valley](skills/monument-valley/SKILL.md) | 把任意主题的公开材料做成纪念碑谷式可探索档案（关卡叙事 + 等距插画） | 自写 · MIT |
| [thought-distillation](skills/thought-distillation/SKILL.md) | 把一个人或团队的全部写作精读后串成一条主线，产出图文并茂的飞书文档 | 自写 · MIT |
| [skill-guide-writer](skills/skill-guide-writer/SKILL.md) | 以本地证据为先，给已有 skill / 工具 / 插件写 Quick Start 和升级说明 | 自写 · MIT |
| [life-decision-guide](skills/life-decision-guide/SKILL.md) | 基于《高性价比人生指南》离线快照回答具体生活选择，注明出处 | [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter) @ `24e3d67` · Unlicense |
| [grilling](skills/grilling/SKILL.md) | 按 design tree 的 frontier 逐轮探问，把方案 / 决策 / 想法追问到没有隐含假设 | [mattpocock/skills](https://github.com/mattpocock/skills) 早期快照 · MIT |
| [grill-me](skills/grill-me/SKILL.md) | grilling 的用户手动入口（`/grill-me`），不让模型自动触发 | 同上 · MIT |

镜像快照与上游最新版只有格式差异（破折号 / 空行），另有 2 处小省略；同步发生时以 commit log 为准。

## 依赖

按「只要 pip / npm / 装了就能用」到「要特定账号」排序：

| skill | 需要 |
|---|---|
| skill-guide-writer、life-decision-guide、grilling、grill-me | Python 3.8+ 标准库，无外部依赖 |
| evidence-loop | Python 3.8+、git 2.20+；形式化模式另需 Java 11+，首次运行 `evloop_tlc.py fetch --jre` 下载钉死版本的 `tla2tools.jar` |
| lark-figure、lark-series-builder、monument-valley、thought-distillation | 已登录的 `lark-cli`（`lark-cli auth login`，user 身份）；lark-figure 本地预览还要 Node（跑 `npx @larksuite/whiteboard-cli`） |
| monument-valley | Pillow（可选，图片检查；macOS 上回退到 `sips`） |
| lark-series-builder 本地预览 | macOS Quick Look（`qlmanage`） |

## 测试

每个 skill 的测试放在 `dev/<name>/`（不属于技能本体，安装时不用复制）。在仓库根目录跑：

```bash
python3 -m unittest discover -s dev/evidence-loop/tests -p 'test_*.py'
python3 -m unittest discover -s dev/lark-figure          -p 'test_*.py'
python3 -m unittest discover -s dev/life-decision-guide  -p 'test_*.py'
python3 -m unittest discover -s dev/monument-valley      -p 'test_*.py'
python3 -m unittest discover -s dev/thought-distillation -p 'test_*.py'
bash skills/lark-series-builder/scripts/selftest.sh      # 期望输出 SELFTEST OK
```

在仓库根目录跑因为测试按相对路径找 `skills/<name>`。

## 限制

- 4 个写飞书的 skill（lark-figure / lark-series-builder / monument-valley / thought-distillation）都只在与你确认后才写入飞书；lark-figure 的 `put` 默认 dry-run，要加 `--yes` 才真写。
- evidence-loop 跑长任务时在独立 worktree 工作，完事还要经你批准才能合并回主分支；它不是无脑自治。
- thought-distillation 的整篇 publish 步骤用 `overwrite`（会丢原评论），只应对自动新建的文档用；已有飞书文档请走 update 路径。
- `dev/lark-figure/eval/results/` 是 2026 年几次模型评测的原始输出，只说明当时的表现，不构成效果承诺。
- 不写 skill 做不到的：`grilling` 期间模型只能问，不替你下决定；`evidence-loop` 的裁判不评价代码好坏，只校验约定是否达成。

## 排障 & FAQ

| 问题 | 处理 |
|---|---|
| 装了却不触发 | 检查软链指向的是 `skills/<name>` 目录本身，而不是父目录；再开一个新会话。agent 按 `SKILL.md` 的 `description` 决定何时调用 |
| 测试 ImportError / 找不到技能 | 必须在仓库根目录跑测试——`dev/<name>/` 靠相对路径引用 `skills/<name>/` |
| 写飞书报权限错 | `lark-cli auth status` 确认 user 身份已登录且具备文档 / 画板的写权限 |

## 目录结构

```text
skills/
  <name>/
    SKILL.md            # 入口：触发条件、流程、硬约束
    references/         # 按需加载的细则
    scripts/            # skill 实际跑的脚本
dev/
  <name>/
    tests/              # 对应 skill 的单元测试 / 评测
    ...
LICENSE                 # MIT（自写部分）
```

## 许可

自写部分 MIT，见 [LICENSE](LICENSE)。

改编自上游的 skill 沿用上游许可：

- `life-decision-guide` — Unlicense（与上游 eternity4719/HowToLiveBetter 一致）
- `grilling` / `grill-me` — MIT（与上游 mattpocock/skills 一致）
