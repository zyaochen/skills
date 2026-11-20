"""命令行入口：解析参数，分派到 judge / report，把 EvloopError 统一转成退出码。"""
import argparse
import sys

from . import __version__, judge, report
from . import plan as plan_mod
from .util import CODE_NAMES, CONSTITUTION, INVALID, PROG, RUNS_DIR, EvloopError

DESCRIPTION = """\
澄清 → 循环 → 交付 的机械裁判。仅依赖 Python 标准库。

命令与流程一一对应：
  init      澄清收尾：记录约束与冻结哈希，跑基线（以及优化场景的对照重跑、文档场景的评审校准）
  start     进入循环：绑定工作区、设定截止时间、自检裁判本身
  smoke     自检：证明冻结文件改动与越界改动都会被拒绝
  attempt   循环一轮：范围检查、冻结检查、运行检查、裁决、保留或回滚
  source    研究 / 文档场景：抓取来源并按内容哈希快照，论断只能引用快照
  status    退出判定：约定规则是否满足（修复测试 / 开发蓝图 / 优化目标 / 文档检查），或预算耗尽
  resume    接手 / 上下文压缩后的单行简报：约定、最优、最近几次裁决、下一步
  verify    交付前在保留的最优提交上重跑约定命令
  report    交付物：对比表（修复）、蓝图交付（开发）、过程图（优化）；--progress 出进度快照
  approve   记录人工批准；交付阶段的合并要等它
  relocate  运行目录随仓库迁移后，把契约重新指向新的克隆
  doctor    只读体检：环境、契约封存、工作区、冻结文件与来源快照
  plan      跨会话计划：任务清单、依赖、停止条件、下一会话提示词（每个任务对应一个运行目录）

退出码：0 接受 / 通过，1 拒绝 / 失败 / 检查点，2 无效，3 前置条件不满足。
错误信息打印到 stderr，格式为 "evloop: <precondition|invalid|rejected>: 原因"。
"""


def build_parser():
    p = argparse.ArgumentParser(prog=f"{PROG}.py", description=DESCRIPTION,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--home", help=f"契约目录：<repo>/{RUNS_DIR}/<task>（通过 .git/info/exclude 只在本地生效），"
                                  "必须位于循环工作区之外；除 doctor 外都必填")
    p.add_argument("--brief", action="store_true", help="JSON 输出不缩进（单行），节省智能体上下文")
    sub = p.add_subparsers(dest="cmd", metavar="命令")
    sub.required = True

    i = sub.add_parser("init", help="记录约定并跑基线")
    i.add_argument("--repo", default=".", help="工作克隆（不能是链接工作区），默认当前目录")
    i.add_argument("--scenario", choices=["development", "bugfix", "optimization", "research", "document"], required=True)
    i.add_argument("--branch-from", help="交付时合并回的分支，默认工作克隆当前分支")
    i.add_argument("--editable", nargs="+", required=True, help="允许改动的路径；'.' 表示整个仓库")
    i.add_argument("--frozen", nargs="+", help="必须保持不变的文件或目录（修复与优化场景必填）")
    i.add_argument("--generated", nargs="+",
                   help="约定命令会写入的运行产物路径：其中未跟踪的文件不会阻塞尝试、回滚时会被清掉，"
                        "但把它们提交进尝试判为无效")
    i.add_argument("--test-cmd", help="约定测试命令（修复与优化场景必填；研究与文档场景可选）")
    i.add_argument("--check-cmd", help="回归检查命令（开发场景，可选；不给则每轮为人工检查点）")
    i.add_argument("--blueprint", help="蓝图 JSON（开发场景）")
    i.add_argument("--asis", help="现状图 JSON（开发场景）")
    i.add_argument("--asbuilt", help="竣工图 JSON 的路径，必须在 --editable 内（开发场景）")
    i.add_argument("--budget-minutes", type=float, help="墙钟时间预算（优化场景必填，可由宪法给默认值）")
    i.add_argument("--reserve-minutes", type=float,
                   help="预算末尾留给 verify 与交付的时间；进入该窗口后拒绝新的尝试")
    i.add_argument("--score-regex", help="从输出中提取分数的正则；有捕获组时取第一组，取最后一个匹配")
    i.add_argument("--direction", choices=["lower", "higher"], help="分数越低越好还是越高越好")
    i.add_argument("--unit", help="分数单位，用于报告")
    i.add_argument("--delta", type=float, help="判定为改进所需的最小幅度（绝对值）")
    i.add_argument("--delta-pct", type=float, help="判定为改进所需的最小幅度（基线的百分比）")
    i.add_argument("--target", type=float, help="达标线")
    i.add_argument("--exclusive", action="store_true", help="达标不含等于")
    i.add_argument("--fast-cmd", help="快速预检命令：每次尝试先跑它，失败即判无效，省下完整测试的时间；"
                                      "可由宪法 fast_cmd 给默认值")
    i.add_argument("--max-attempts", type=int, help="尝试次数上限；用完后进入交付（任何场景可用）")
    i.add_argument("--token-budget", type=int, help="token 上限；attempt --tokens 上报的累计用量达到后进入交付")
    i.add_argument("--secondary-regex", help="次要指标的正则（优化场景，可选），用于平局时的护栏")
    i.add_argument("--secondary-direction", choices=["lower", "higher"], help="次要指标越低越好还是越高越好")
    i.add_argument("--prefer-simpler", action="store_true",
                   help="优化场景：分数在 δ 内持平、次要指标未变差、且净删除代码时，按简化接受")
    i.add_argument("--draft", help="交付文档的路径，必须在 --editable 内（研究与文档场景）")
    i.add_argument("--doc-spec", help="文档规格 JSON：必需标题、篇幅、禁用内容、论断文件、问题清单（研究与文档场景）")
    i.add_argument("--judge-cmd", help="细则评审命令：从标准输入读提示词，最后输出一行 SCORE: <数字>；"
                                       "建议用与生成草稿不同的模型")
    i.add_argument("--rubric", help="评分细则文件（冻结）")
    i.add_argument("--golden-good", help="校准用的好样本（冻结）")
    i.add_argument("--golden-bad", help="校准用的差样本（冻结）")
    i.add_argument("--rubric-samples", type=int, help="每次评审的采样次数 K（默认 3），取中位数")
    i.add_argument("--rubric-threshold", type=float, help="细则评审的通过线")
    i.add_argument("--allow-local-sources", action="store_true",
                   help="接受 source add --file 登记的本地文件作为来源（默认只接受网页）")
    i.add_argument("--formal-spec", help="形式化检查清单 checks.json（冻结）：筛选结论、案例、性质、需求覆盖、"
                                        "未建模范围；叠加在修复 / 开发 / 优化场景上")
    i.add_argument("--model-cmd", help="模型检查命令，必须含 {checker} {model} {cfg} {metadir} 占位符与 -tool、"
                                      "-noGenerateSpecTE，不得带 -continue")
    i.add_argument("--checker-path", help="检查器 jar 路径（相对仓库或绝对路径）")
    i.add_argument("--checker-sha256", help="检查器 jar 的 sha256；不符即阻断，不做静默回退")
    i.add_argument("--renew", action="store_true", help="重新澄清后覆盖已有契约（旧契约与记录会归档为 .bak）")
    i.add_argument("--constitution", help=f"项目宪法文件；默认在存在时读取 {CONSTITUTION}")
    i.set_defaults(fn=judge.cmd_init)

    s = sub.add_parser("start", help="绑定循环工作区并开始计时")
    s.add_argument("--worktree", required=True, help="为循环单独创建的 git worktree")
    s.add_argument("--no-smoke", action="store_true", help="跳过裁判自检")
    s.set_defaults(fn=judge.cmd_start)

    sub.add_parser("smoke", help="重新运行裁判自检").set_defaults(fn=judge.cmd_smoke)

    t = sub.add_parser("attempt", help="裁决当前 HEAD 上的一次尝试")
    t.add_argument("--note", default="", help="这次改了什么")
    t.add_argument("--route", help="这次检验的思路标签；优化场景必填")
    t.add_argument("--differs", help="重试一条已在当前最优之上被证伪的路线时，说明这次的不同之处")
    t.add_argument("--elements", nargs="+", help="本次开发检查点实现的蓝图元素 ID")
    t.add_argument("--commit", help="裁决指定的候选提交（工作区会先切到它）；用于并行生成、串行裁决")
    t.add_argument("--tokens", type=int, help="产出这次尝试消耗的 token 数，计入 --token-budget")
    t.add_argument("--tail", type=int, default=20,
                   help="未通过时在输出里附带原始日志的最后 N 行（默认 20，0 关闭；不写入记录）")
    t.set_defaults(fn=judge.cmd_attempt)

    so = sub.add_parser("source", help="登记或列出来源快照（研究与文档场景）")
    sos = so.add_subparsers(dest="source_cmd", metavar="动作")
    sos.required = True
    sa = sos.add_parser("add", help="抓取 URL（或读取本地文件）并快照")
    sa.add_argument("--url", help="http / https 来源")
    sa.add_argument("--file", help="本地文本文件（需要契约允许本地来源）")
    sa.add_argument("--id", help="来源 id，默认 s1、s2……")
    sa.add_argument("--note", help="为什么引用这个来源")
    sa.set_defaults(fn=judge.cmd_source)
    sos.add_parser("list", help="列出已登记的来源与快照完整性").set_defaults(fn=judge.cmd_source)

    sub.add_parser("status", help="当前状态与下一步").set_defaults(fn=judge.cmd_status)
    rs = sub.add_parser("resume", help="接手用的单行简报（只读）")
    rs.add_argument("--last", type=int, default=5, help="附带最近几次尝试，默认 5")
    rs.set_defaults(fn=judge.cmd_resume)
    sub.add_parser("verify", help="在保留的最优提交上做最终验证").set_defaults(fn=judge.cmd_verify)

    r = sub.add_parser("report", help="生成交付包或进度快照")
    r.add_argument("--out", help="handoff.html 的输出路径，默认在契约目录")
    r.add_argument("--progress", action="store_true", help="写 progress.html，不改动交付包与审批状态")
    r.add_argument("--open", dest="open_", action="store_true", help="写完后用系统查看器打开")
    r.set_defaults(fn=report.cmd_report)

    ap = sub.add_parser("approve", help="记录人工批准")
    ap.add_argument("--note", default="", help="用评审人的话记录批准了什么")
    ap.set_defaults(fn=judge.cmd_approve)

    m = sub.add_parser("relocate", help="把迁移后的契约重新指向新的克隆")
    m.add_argument("--repo", required=True, help="运行目录被迁入的工作克隆")
    m.add_argument("--worktree", help="循环工作区也迁移了时，给出新路径")
    m.set_defaults(fn=judge.cmd_relocate)

    plan_mod.add_parser(sub)

    sub.add_parser("doctor", help="只读体检（--home 可选）").set_defaults(fn=judge.cmd_doctor)
    return p


GLOBAL_FLAGS = ("--brief",)
GLOBAL_OPTIONS = ("--home",)


def hoist_globals(argv):
    """把写在子命令之后的全局参数（--brief、--home X、--home=X）挪到最前面。

    智能体常把 `--brief` 追加在命令末尾；argparse 只在子命令之前认全局参数，
    这里统一前移，写在哪里都生效。`--` 之后的参数原样保留。
    """
    head, rest, i = [], [], 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            rest.extend(argv[i:])
            break
        if tok in GLOBAL_FLAGS:
            head.append(tok)
        elif tok in GLOBAL_OPTIONS and i + 1 < len(argv):
            head.extend(argv[i:i + 2])
            i += 1
        elif any(tok.startswith(o + "=") for o in GLOBAL_OPTIONS):
            head.append(tok)
        else:
            rest.append(tok)
        i += 1
    return head + rest


def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(hoist_globals(list(sys.argv[1:] if argv is None else argv)))
    if a.cmd != "doctor" and not a.home:
        parser.error(f"{a.cmd} 需要 --home")
    judge.BRIEF = a.brief
    try:
        return a.fn(a)
    except EvloopError as e:
        print(f"{PROG}: {CODE_NAMES.get(e.code, 'error')}: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print(f"{PROG}: 已中断", file=sys.stderr)
        return INVALID
