# skills

这里放的是我自己日常在用、和公司业务无关的 Agent skill，在 Claude Code 和其他支持 `SKILL.md` 的 Agent 里都能用。每个 skill 一个目录，入口是 `skills/<name>/SKILL.md`。测试和评测用例放在 `dev/<name>/`，不属于技能本体，安装时不用复制。

## 能做什么

| skill | 用途 | 来源与许可 |
|---|---|---|
| [evidence-loop](skills/evidence-loop/SKILL.md) | 带机械裁判的自主工程循环：先澄清约定，在独立 worktree 里逐次裁决，结果要么保留要么回滚，最后验证并交人批准。覆盖缺陷修复、按蓝图开发、性能优化、带出处的调研、TLA+/TLC 形式化验证 | 自写，MIT |
| [lark-figure](skills/lark-figure/SKILL.md) | 飞书画板配图：模型只写内容 spec（一句判断、要素、数字、来源），排版、配色、走线由脚本生成，过 lint 和画板自检后写入画板。14 种图型加拼图 | 自写，MIT |
| [lark-series-builder](skills/lark-series-builder/SKILL.md) | 批量写完、重写或提质一整套飞书系列文档：主编定规范、派活、验收，正文和图交给子 Agent，靠数字门槛、自排版 SVG 构件、图型样板和独立评审保证水准 | 自写，MIT |
| [monument-valley](skills/monument-valley/SKILL.md) | 把一个主题的公开材料做成纪念碑谷式的可探索档案：关卡叙事、统一等距插画、可续建的飞书文档 | 自写，MIT |
| [thought-distillation](skills/thought-distillation/SKILL.md) | 把一个人或团队的全部写作精读后串成一条主线，产出图文并茂的飞书文档 | 自写，MIT |
| [skill-guide-writer](skills/skill-guide-writer/SKILL.md) | 以本地证据为先，给已有的 skill、工具或插件写 Quick Start、完整指南和升级说明 | 自写，MIT |
| [life-decision-guide](skills/life-decision-guide/SKILL.md) | 基于《高性价比人生指南》离线快照回答具体生活选择，先查原文再答，并注明出处 | 改编自 [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)，Unlicense；快照版本见 `references/provenance.json` |
| [grilling](skills/grilling/SKILL.md) | 对方案、决策或想法逐轮追问，直到没有遗留的隐含假设 | 外部公开 skill，2026-08-14 装到本机，上游没有记录，不在本仓库的 MIT 范围内 |
| [grill-me](skills/grill-me/SKILL.md) | `grilling` 的手动入口，只能由用户输入 `/grill-me` 触发 | 同 `grilling` |

## 怎么用

装到 Claude Code（用户级）：

```bash
git clone https://github.com/zyaochen/skills.git ~/src/skills
ln -s ~/src/skills/skills/evidence-loop ~/.claude/skills/evidence-loop   # 按需逐个软链
```

软链的好处是 `git pull` 后立即生效。只想用某一版就直接复制目录。项目级安装把链接放到项目的 `.claude/skills/` 下。

跑测试（Python 3.8+）：

```bash
python3 -m unittest discover -s dev/evidence-loop/tests -p 'test_*.py'
python3 -m unittest discover -s dev/lark-figure -p 'test_*.py'          # monument-valley、thought-distillation、life-decision-guide 同理
bash skills/lark-series-builder/scripts/selftest.sh                      # 输出 SELFTEST OK
```

## 依赖

| skill | 需要 |
|---|---|
| lark-figure、lark-series-builder、monument-valley、thought-distillation | 飞书官方 `lark-cli` 已登录（`--as user`）；lark-figure 本地预览还要 Node，`npx @larksuite/whiteboard-cli` |
| lark-series-builder 的本地预览 | macOS Quick Look（`qlmanage`） |
| evidence-loop 的形式化模式 | Java 11+，首次运行下载钉死版本的 `tla2tools.jar` |
| monument-valley 的图片检查 | Pillow，macOS 上没装时改用 `sips` |
| 其余 | Python 3.8+ 标准库 |

## 文件约定

| 路径 | 内容 |
|---|---|
| `skills/<name>/SKILL.md` | 技能入口：触发条件、流程、硬约束 |
| `skills/<name>/references/` | 按需加载的细则 |
| `skills/<name>/scripts/` | 技能调用的脚本 |
| `dev/<name>/` | 单元测试、评测用例和夹具，测试按相对路径找 `skills/<name>` |

## 限制

- 四个飞书相关的 skill 会写飞书文档或画板。`lark-figure put` 不加 `--yes` 时只做 dry-run；`lark-series-builder` 只在用户授权后整篇覆盖发布；`thought-distillation` 的发布步骤用 `overwrite`，会丢掉目标文档原有的评论和画板，只能对它自己新建的文档用。
- `dev/lark-figure/eval/results/` 是 2026 年几次模型评测的原始输出，只说明当时的表现，不作为效果承诺。
- `grilling` 和 `grill-me` 的上游没有记录。公开前要先找到上游并核对许可，找不到就从仓库移除。

## 常见问题

- **装了却不触发**：Claude Code 按 `SKILL.md` 里的 `description` 判断何时调用。确认软链指向的是 `skills/<name>` 目录本身，再新开会话。
- **测试找不到技能**：测试按相对路径找 `skills/<name>`，要在仓库根目录下运行，不要把 `dev/` 单独拷走。
- **写飞书报权限错误**：先跑 `lark-cli auth status`，确认 user 身份已登录，并且有文档和画板的写权限。

## 许可

自写部分为 MIT，见 [LICENSE](LICENSE)。`life-decision-guide` 沿用上游的 Unlicense；`grilling`、`grill-me` 按上表说明处理。
