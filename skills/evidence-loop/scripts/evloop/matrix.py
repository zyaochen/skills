"""跨模型评测矩阵：把 evals.json（不随技能发布，见 EVALS_DIR）的每条用例，在本机的官方智能体命令行上各跑一遍。

矩阵 = 用例 × 智能体（codex / claude）× 配置（with_skill / without_skill）。每个格子：
  1. 从 <evals 目录>/fixtures/<fixture> 复制出一个全新的 git 仓库，必要时用裁判预置运行状态（setup）；
  2. with_skill 时把技能装进该智能体扫描的目录（不含 evals/ 与 tests/，避免把答案交给被测模型）；
  3. 以非交互方式调用智能体，必要时用"模拟评审人"的续写消息继续同一会话；
  4. 读取 <repo>/.evloop/runs/ 下的运行目录做机械评分，写 grading.json、timing.json、run.json；
最后把整个 iteration 目录汇总成 benchmark.json（按模型分组给出 with_skill − without_skill）。

本模块只通过子进程调用本机已安装、已登录的 codex / claude 命令行，不直接访问任何模型接口。
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from . import evals
from .util import PROG, RUNS_DIR, STATE_DIR, EvloopError, atomic_write_text, fail

SKILL_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _default_evals_dir():
    """评测用例不随技能发布：优先环境变量 EVLOOP_EVALS_DIR，其次技能内的 evals/，最后是开发仓库的 dev/evidence-loop/evals。"""
    env = os.environ.get("EVLOOP_EVALS_DIR")
    if env:
        return os.path.realpath(env)
    for cand in (os.path.join(SKILL_DIR, "evals"),
                 os.path.join(SKILL_DIR, "..", "..", "dev", "evidence-loop", "evals")):
        if os.path.isfile(os.path.join(cand, "evals.json")):
            return os.path.realpath(cand)
    return os.path.join(SKILL_DIR, "evals")


EVALS_DIR = _default_evals_dir()
EVALS_JSON = os.path.join(EVALS_DIR, "evals.json")
FIXTURES = os.path.join(EVALS_DIR, "fixtures")
JUDGE = os.path.join(SKILL_DIR, "scripts", "evloop.py")

AGENTS = {
    # 智能体 -> (默认模型, 技能安装位置)
    "codex": ("gpt-6-sol", ".agents/skills"),
    "claude": ("claude-opus-5-5", ".claude/skills"),
}
VARIANTS = ("with_skill", "without_skill")
EFFORTS = ("low", "medium", "high", "xhigh")
# 安装给被测模型的技能副本里不放评测用例与测试
INSTALL_IGNORE = ("evals", "tests", "__pycache__", "*.pyc", ".evloop")

CONTINUE_PROMPT = ("（评审人回复）如果你在等我确认约定草案：我同意草案，按草案执行。"
                   "否则请继续推进，直到确实需要我做决定为止，并告诉我在等什么。")

FIXTURE_IDENT = {"user.name": "evloop-matrix", "user.email": "matrix@localhost", "commit.gpgsign": "false"}


# ---------------------------------------------------------------- 小工具

def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        fail(f"git {' '.join(args)} 失败：{r.stderr.strip()}")
    return r.stdout.strip()


def _judge(*args, cwd=None):
    r = subprocess.run([sys.executable, JUDGE, *args], cwd=cwd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        fail(f"预置运行状态失败（evloop {' '.join(args[2:4])}，退出码 {r.returncode}）：{r.stderr.strip()}")
    return r.stdout


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _dump(path, obj):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _exclude(repo, line):
    path = os.path.join(repo, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------- 仓库与预置状态

def build_repo(fixture, dest, fixtures=None):
    """把 fixtures/<fixture> 复制成 dest 处的一个独立 git 仓库（main 分支，一次初始提交）。"""
    src = os.path.join(fixtures or FIXTURES, fixture)
    if not os.path.isdir(src):
        fail(f"没有名为 {fixture} 的夹具：{src}")
    if os.path.exists(dest):
        fail(f"目标已存在，拒绝覆盖：{dest}")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _write(os.path.join(dest, ".gitignore"), "__pycache__/\n*.pyc\n")
    _git(dest, "init", "-q")
    _git(dest, "checkout", "-q", "-b", "main")
    for k, v in FIXTURE_IDENT.items():
        _git(dest, "config", k, v)
    # Do not inherit the machine's global hooks: a commit-msg hook that demands a trailer rejects the commit below.
    _git(dest, "config", "core.hooksPath", os.devnull)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "初始版本")
    return dest


FIXED_ROUND_CENTS = '''

def round_cents(mills):
    """四舍五入到分，半分远离零进位：1125 厘 -> 113 分，-1125 厘 -> -113 分。"""
    q, r = divmod(abs(mills), 10)
    q += r >= 5
    return q if mills >= 0 else -q
'''

SPLIT_PARSER = '''"""解析 "key=value;key=value" 形式的记录。"""


def parse_line(line):
    record = {}
    for part in line.split(";"):
        key = ""
        value = ""
        in_value = False
        for ch in part:
            if ch == "=" and not in_value:
                in_value = True
            elif in_value:
                value = value + ch
            else:
                key = key + ch
        if key.strip():
            record[key.strip()] = value.strip()
    return record


def parse(text):
    return [parse_line(line) for line in text.splitlines() if line.strip()]
'''


def _loop_worktree(repo, task):
    """按文档约定在仓库旁边建循环工作区：../<repo>-evloop-<task>。"""
    wt = os.path.join(os.path.dirname(repo), f"{os.path.basename(repo)}-evloop-{task}")
    _git(repo, "worktree", "add", "-q", "-b", f"evloop/{task}", wt, "HEAD")
    return wt


def _commit_all(cwd, message):
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "-m", message)


def setup_awaiting_approval(repo):
    """修复已完成、已 verify、已生成交付包，只差人工批准。"""
    home = os.path.join(repo, RUNS_DIR, "money-fix")
    _judge("--home", home, "init", "--repo", repo, "--scenario", "bugfix", "--editable", "src/money.py",
           "--frozen", "tests", "--test-cmd", "python3 tests/test_money.py")
    wt = _loop_worktree(repo, "money-fix")
    _judge("--home", home, "start", "--worktree", wt)
    path = os.path.join(wt, "src", "money.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    head, _, rest = text.partition("\n\ndef round_cents")
    tail = rest[rest.index("\n\ndef format_cents"):]
    _write(path, head + FIXED_ROUND_CENTS + tail)
    _commit_all(wt, "round_cents：负数半分远离零进位")
    _judge("--home", home, "attempt", "--note", "负数先取绝对值再进位")
    _judge("--home", home, "verify")
    _write(os.path.join(home, "review.md"), "改动只涉及 src/money.py 的 round_cents；tests/ 未改动。\n")
    _judge("--home", home, "report")
    return home


def setup_interrupted(repo):
    """优化任务做到一半：契约已封存、已开始计时、已有一次被接受的尝试。"""
    home = os.path.join(repo, RUNS_DIR, "parser-speed")
    _judge("--home", home, "init", "--repo", repo, "--scenario", "optimization", "--editable", "src",
           "--frozen", "bench", "tests", "--test-cmd", "python3 bench/throughput.py",
           "--score-regex", "throughput=([0-9.]+)", "--direction", "higher", "--unit", "records",
           "--delta-pct", "5", "--target", "40000", "--budget-minutes", "90", "--max-attempts", "8")
    wt = _loop_worktree(repo, "parser-speed")
    _judge("--home", home, "start", "--worktree", wt)
    _write(os.path.join(wt, "src", "kvparse.py"), SPLIT_PARSER)
    _commit_all(wt, "先按分号切分，再逐字符解析")
    _judge("--home", home, "attempt", "--route", "split-first", "--note", "先 split 再逐字符")
    return home


SETUPS = {"awaiting_approval": setup_awaiting_approval, "interrupted": setup_interrupted}


def install_skill(repo, agent):
    rel = os.path.join(AGENTS[agent][1], "evidence-loop")
    dest = os.path.join(repo, rel)
    shutil.copytree(SKILL_DIR, dest, ignore=shutil.ignore_patterns(*INSTALL_IGNORE))
    # 发布包根目录只保留标准条目；智能体侧的元数据在 assets/ 里，安装时放回各家约定的位置
    yaml = os.path.join(dest, "assets", "openai.yaml")
    if agent == "codex" and os.path.isfile(yaml):
        os.makedirs(os.path.join(dest, "agents"), exist_ok=True)
        shutil.copy(yaml, os.path.join(dest, "agents", "openai.yaml"))
    # 只在本克隆忽略，不让技能副本出现在 git status 与尝试的改动里
    _exclude(repo, "/" + AGENTS[agent][1].split("/")[0] + "/")
    return rel


# ---------------------------------------------------------------- 命令

def agent_argv(agent, model, effort, repo, work, prompt, session=None, permission_mode="bypassPermissions"):
    """返回调用智能体的 argv。session 不为空时续写同一会话。"""
    if agent == "codex":
        roots = json.dumps([work, os.path.join(repo, ".git")])
        argv = ["codex", "exec", "--json", "--skip-git-repo-check", "-m", model,
                "-c", 'sandbox_mode="workspace-write"',
                "-c", f"sandbox_workspace_write.writable_roots={roots}",
                "-c", 'approval_policy="never"',
                "-c", f'model_reasoning_effort="{effort}"']
        if session:
            return argv + ["resume", session, prompt]
        return argv + ["-C", repo, prompt]
    argv = ["claude", "-p", "--model", model, "--output-format", "json",
            "--permission-mode", permission_mode, "--effort", effort, "--add-dir", work]
    if session:
        argv += ["--resume", session]
    return argv + [prompt]


def parse_codex(stdout):
    out = {"session": None, "tokens": 0, "message": None, "errors": []}
    seen_usage = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "thread.started":
            out["session"] = ev.get("thread_id") or out["session"]
        elif kind == "turn.completed":
            u = ev.get("usage") or {}
            out["tokens"] += int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
            seen_usage = True
        elif kind == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message":
                out["message"] = item.get("text")
        elif kind in ("turn.failed", "error"):
            out["errors"].append(ev.get("message") or json.dumps(ev.get("error"), ensure_ascii=False))
    if not seen_usage:
        out["tokens"] = None
    return out


def parse_claude(stdout):
    out = {"session": None, "tokens": None, "message": None, "errors": [], "cost_usd": None}
    text = stdout.strip()
    start = text.find("{")
    try:
        data = json.loads(text[start:]) if start >= 0 else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        out["errors"].append("输出不是 JSON")
        return out
    u = data.get("usage") or {}
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    if any(k in u for k in keys):
        out["tokens"] = sum(int(u.get(k) or 0) for k in keys)
    out.update(session=data.get("session_id"), message=data.get("result"), cost_usd=data.get("total_cost_usd"))
    if data.get("is_error"):
        out["errors"].append(str(data.get("result") or data.get("subtype")))
    return out


PARSERS = {"codex": parse_codex, "claude": parse_claude}


def run_turn(argv, cwd, timeout, log_prefix):
    """运行一轮；超时杀整个进程组。返回 (退出码或 None, stdout, 秒)。"""
    started = time.monotonic()
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, **kwargs)
    except OSError as e:
        fail(f"无法启动 {argv[0]}：{e}；请先安装并登录该智能体的命令行")
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL) if os.name == "posix" else proc.kill()
        except OSError:
            pass
        out, err = proc.communicate()
        code = None
    stdout = out.decode("utf-8", errors="replace")
    _write(log_prefix + ".stdout", stdout)
    _write(log_prefix + ".stderr", err.decode("utf-8", errors="replace"))
    return code, stdout, time.monotonic() - started


# ---------------------------------------------------------------- 评分

def find_run(repo):
    """被评分的运行目录：契约最新的那个；一个都没有时返回 runs 目录本身（no_run 据此判通过）。"""
    runs = os.path.join(repo, RUNS_DIR)
    best, best_t = None, -1.0
    if os.path.isdir(runs):
        for name in sorted(os.listdir(runs)):
            c = os.path.join(runs, name, "contract.json")
            if os.path.isfile(c) and os.path.getmtime(c) > best_t:
                best, best_t = os.path.join(runs, name), os.path.getmtime(c)
    return best or runs


def grade_cell(case, repo):
    run_dir = find_run(repo)
    result = evals.grade(run_dir, case.get("checks", []))
    result["eval_id"] = case["id"]
    result["run_dir"] = os.path.relpath(run_dir, repo)
    return result


# ---------------------------------------------------------------- 矩阵

class Cell:
    def __init__(self, case, agent, model, variant, root, fixtures=None):
        self.case, self.agent, self.model, self.variant = case, agent, model, variant
        self.fixtures = fixtures or FIXTURES
        self.config = f"{model}__{variant}"
        self.dir = os.path.join(root, f"eval-{case['id']}", self.config)
        self.work = os.path.join(self.dir, "work")
        self.repo = os.path.join(self.work, case["fixture"])


def select(data, ids, agents, variants, models, root, fixtures=None):
    cases = data["evals"]
    if ids:
        wanted = {str(i) for i in ids}
        cases = [e for e in cases if str(e["id"]) in wanted]
        missing = wanted - {str(e["id"]) for e in cases}
        if missing:
            fail(f"evals.json 里没有这些用例：{sorted(missing)}")
    for e in cases:
        if not e.get("fixture"):
            fail(f"用例 {e['id']} 没有 fixture，无法自动搭建仓库")
    return [Cell(e, a, models[a], v, root, fixtures) for e in cases for a in agents for v in variants]


def prepare(cell):
    build_repo(cell.case["fixture"], cell.repo, cell.fixtures)
    setup = cell.case.get("setup")
    if setup:
        SETUPS[setup](cell.repo)
    if cell.variant == "with_skill":
        install_skill(cell.repo, cell.agent)
    _git(cell.repo, "status", "--porcelain")  # 确认仓库可用


def run_cell(cell, a):
    prepare(cell)
    parse = PARSERS[cell.agent]
    turns, session, tokens, cost, seconds = [], None, 0, 0.0, 0.0
    token_seen = cost_seen = False
    grading, stop = None, "max turns"
    for i in range(1, a.max_turns + 1):
        prompt = cell.case["prompt"] if i == 1 else CONTINUE_PROMPT
        argv = agent_argv(cell.agent, cell.model, a.effort, cell.repo, cell.work, prompt,
                          session=session if i > 1 else None, permission_mode=a.claude_permission_mode)
        code, stdout, secs = run_turn(argv, cell.repo, a.turn_timeout_minutes * 60,
                                      os.path.join(cell.dir, f"turn-{i}"))
        info = parse(stdout)
        seconds += secs
        if info["tokens"] is not None:
            tokens, token_seen = tokens + info["tokens"], True
        if info.get("cost_usd") is not None:
            cost, cost_seen = cost + info["cost_usd"], True
        session = info["session"] or session
        turns.append({"turn": i, "argv": argv, "exit": code, "seconds": round(secs, 1),
                      "tokens": info["tokens"], "session": info["session"], "errors": info["errors"],
                      "message": (info["message"] or "")[-2000:]})
        grading = grade_cell(cell.case, cell.repo)
        if code is None:
            stop = "timeout"
            break
        if grading["summary"]["total"] and grading["summary"]["failed"] == 0:
            stop = "checks passed"
            break
        if not session:
            stop = "no session to resume"
            break
    _dump(os.path.join(cell.dir, "grading.json"), grading)
    timing = {"total_tokens": tokens if token_seen else None, "duration_ms": int(seconds * 1000),
              "turns": len(turns), "agent": cell.agent, "model": cell.model}
    if cost_seen:
        timing["cost_usd"] = round(cost, 4)
    _dump(os.path.join(cell.dir, "timing.json"), timing)
    _dump(os.path.join(cell.dir, "run.json"), {"eval_id": cell.case["id"], "agent": cell.agent,
                                               "model": cell.model, "variant": cell.variant,
                                               "effort": a.effort, "stop_reason": stop, "turns": turns})
    return {"eval": cell.case["id"], "config": cell.config, "stop_reason": stop,
            "pass_rate": grading["summary"]["pass_rate"], "tokens": timing["total_tokens"],
            "seconds": round(seconds, 1)}


def _models(a):
    return {"codex": a.codex_model, "claude": a.claude_model}


def _fixtures(a):
    """夹具目录与用例文件同级：<evals 目录>/fixtures。"""
    return os.path.join(os.path.dirname(os.path.abspath(a.evals_file)), "fixtures")


def _root(a):
    return os.path.abspath(os.path.join(a.workspace, f"iteration-{a.iteration}"))


def cmd_plan(a, data):
    cells = select(data, a.eval, a.agents, a.variants, _models(a), _root(a), _fixtures(a))
    plan = []
    for c in cells:
        plan.append({"eval": c.case["id"], "config": c.config, "fixture": c.case["fixture"],
                     "setup": c.case.get("setup"),
                     "skill_dir": (os.path.join(AGENTS[c.agent][1], "evidence-loop")
                                   if c.variant == "with_skill" else None),
                     "cwd": c.repo,
                     "first": agent_argv(c.agent, c.model, a.effort, c.repo, c.work, c.case["prompt"],
                                         permission_mode=a.claude_permission_mode),
                     "resume": agent_argv(c.agent, c.model, a.effort, c.repo, c.work, CONTINUE_PROMPT,
                                          session="<session>", permission_mode=a.claude_permission_mode)})
    print(json.dumps({"iteration": _root(a), "cells": plan}, ensure_ascii=False, indent=2))
    return 0


def cmd_run(a, data):
    root = _root(a)
    cells = select(data, a.eval, a.agents, a.variants, _models(a), root, _fixtures(a))
    clash = [c.dir for c in cells if os.path.exists(c.dir)]
    if clash:
        fail(f"这些格子已经存在，换一个 --iteration 或先删除：{clash[:3]}")
    if not a.prepare_only:
        for agent in a.agents:
            if shutil.which(agent) is None:
                fail(f"找不到 {agent} 命令；先安装并登录，或用 --agents 去掉它")
    results = []
    for c in cells:
        if a.prepare_only:
            prepare(c)
            results.append({"eval": c.case["id"], "config": c.config, "repo": c.repo})
            continue
        print(f"{PROG}: eval-{c.case['id']} {c.config} …", file=sys.stderr, flush=True)
        results.append(run_cell(c, a))
    out = {"iteration": root, "cells": results}
    if not a.prepare_only:
        bench = evals.benchmark(root)
        _dump(os.path.join(root, "benchmark.json"), bench)
        out["benchmark"] = os.path.join(root, "benchmark.json")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog=f"{PROG}_matrix.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", metavar="命令")
    sub.required = True
    for name, help_ in (("plan", "只打印每个格子要执行的命令，不创建任何文件"),
                        ("run", "搭建仓库、调用智能体、评分，并写 benchmark.json")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--workspace", required=True, help="矩阵输出目录；本次结果写到其下的 iteration-N/")
        s.add_argument("--iteration", type=int, default=1, help="迭代编号，默认 1")
        s.add_argument("--evals-file", default=EVALS_JSON, help="用例文件（夹具取同级的 fixtures/）；默认按 EVLOOP_EVALS_DIR、技能内 evals/、开发仓库 dev/evidence-loop/evals 的顺序查找")
        s.add_argument("--eval", nargs="+", help="只跑这些用例 ID")
        s.add_argument("--agents", nargs="+", choices=sorted(AGENTS), default=sorted(AGENTS))
        s.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
        s.add_argument("--codex-model", default=AGENTS["codex"][0], help="codex 使用的模型")
        s.add_argument("--claude-model", default=AGENTS["claude"][0], help="claude 使用的模型")
        s.add_argument("--effort", choices=EFFORTS, default="high", help="推理强度，两个智能体共用")
        s.add_argument("--claude-permission-mode", default="bypassPermissions",
                       help="claude 的权限模式；夹具仓库是一次性的，默认放开以便无人值守")
        s.add_argument("--max-turns", type=int, default=4, help="每个格子最多几轮（含模拟评审人的续写）")
        s.add_argument("--turn-timeout-minutes", type=float, default=120, help="单轮超时")
        if name == "run":
            s.add_argument("--prepare-only", action="store_true", help="只搭建仓库与预置状态，不调用智能体")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.max_turns < 1:
            fail("--max-turns 至少为 1")
        data = evals.load(a.evals_file)
        return (cmd_plan if a.cmd == "plan" else cmd_run)(a, data)
    except EvloopError as e:
        from .util import CODE_NAMES
        print(f"{PROG}: {CODE_NAMES.get(e.code, 'error')}: {e}", file=sys.stderr)
        return e.code


__all__ = ["SETUPS", "STATE_DIR", "agent_argv", "build_parser", "build_repo", "find_run", "main", "parse_claude",
           "parse_codex"]
