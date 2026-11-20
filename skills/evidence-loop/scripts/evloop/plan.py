"""跨会话计划：把一个想法拆成带验证与依赖的任务，每个会话只推进一个任务，状态落盘，下一会话自取。

计划目录 <repo>/.evloop/plans/<project>/：
  plan.json      计划定义（目标、模式、配置、任务、假设），带 plan_sha 封存；只能经由命令修改
  state.json     执行状态（任务状态、失败计数、会话数、停止标记），带 state_sha 封存
  plan-log.jsonl 只追加的事件日志，用于监控与复盘
  .lock          互斥锁

每个任务要么对应一个 evloop 运行目录（scenario + run，裁判说了算），要么给出一条 check 命令。
plan done 只在证据成立时才把任务标为完成：运行目录的 status 达成目标且最终验证有效
（任务要求人工批准时还要已批准），或 check 命令退出码为 0。

停止条件（按顺序）：计划或状态被手工改动 → 人工停止 → 全部完成 → 连续失败次数达到上限 →
周期时长用完 → 剩余任务都被失败的依赖卡住。命中任何一条，next / prompt 都给出 stop，不再排期。

evloop 不调度任何东西：plan prompt 只生成一段自包含的下一会话提示词与建议延迟，
由智能体在当前会话结束前，用它自己的定时任务能力排期。

会话中断：plan next 领到的任务仍是 active（上一会话既没有 done 也没有 fail 就结束了），
记一次失败（abandoned），计入任务的 max_attempts 与连续失败数，防止崩溃的会话无限重来。
"""
import json
import os
import re

from . import render
from .contract import Home
from .runner import run_command
from .util import (ACCEPTED, INVALID, PRECONDITION, REJECTED, STATE_DIR, append_line, atomic_write_json,
                   atomic_write_text, fail, file_lock, in_scope, inside, iso, norm, parse_iso, sha256_json,
                   utc_now)

PLANS_DIR = STATE_DIR + "/plans"
TASK_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
SCENARIOS = ("development", "bugfix", "optimization", "research", "document")
MODES = ("confirm", "auto")
TASK_KEYS = {"id", "title", "scenario", "run", "check", "depends", "max_attempts", "approve", "notes"}
STATUSES = ("pending", "active", "done", "failed")
STOP_WORDS = {"plan tampered": "计划或状态文件被手工改动",
              "stopped": "已人工停止",
              "all done": "全部任务已完成",
              "too many failures": "连续失败次数达到上限",
              "cycle exhausted": "周期时长已用完",
              "blocked": "剩余任务都被失败的依赖卡住",
              "awaiting plan approval": "确认模式下计划尚未获得人工批准"}
EVLOOP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evloop.py")


def _emit(obj):
    from . import judge
    judge.emit(obj)


class Plan:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.plan_path = os.path.join(self.path, "plan.json")
        self.state_path = os.path.join(self.path, "state.json")
        self.log_path = os.path.join(self.path, "plan-log.jsonl")
        self.lock_path = os.path.join(self.path, ".lock")

    def exists(self):
        return os.path.exists(self.plan_path)

    def lock(self):
        return file_lock(self.lock_path)

    def _read(self, path, key):
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except FileNotFoundError:
            fail(f"{path} 不存在；先运行 plan init")
        except ValueError as e:
            return None, f"{os.path.basename(path)} 已损坏：{e}"
        if not isinstance(obj, dict) or obj.get(key) != seal(obj, key):
            return obj, f"{os.path.basename(path)} 在命令之外被改动过"
        return obj, None

    def load(self, strict=True):
        """返回 (plan, state, 篡改说明或 None)。strict 时篡改直接判无效。"""
        plan, err1 = self._read(self.plan_path, "plan_sha")
        state, err2 = self._read(self.state_path, "state_sha")
        err = err1 or err2
        if err and strict:
            fail(err + "；计划只能经由 plan 命令修改。核对 plan-log.jsonl 后用 plan init --renew 重建", INVALID)
        return plan, state, err

    def save(self, plan=None, state=None):
        os.makedirs(self.path, exist_ok=True)
        if plan is not None:
            plan["plan_sha"] = seal(plan, "plan_sha")
            atomic_write_json(self.plan_path, plan)
        if state is not None:
            state["state_sha"] = seal(state, "state_sha")
            atomic_write_json(self.state_path, state)

    def log(self, event, **fields):
        row = dict(fields, time=fields.get("time") or iso(utc_now()), event=event)
        append_line(self.log_path, json.dumps(row, ensure_ascii=False))

    def events(self, last=None):
        if not os.path.exists(self.log_path):
            return []
        out = []
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out[-last:] if last else out


def seal(obj, key):
    return sha256_json({k: v for k, v in obj.items() if k != key})


def definition_sha(plan):
    """计划内容指纹：目标、任务、配置；批准绑定到它，计划改了批准就失效。"""
    return sha256_json({k: plan.get(k) for k in ("goal", "mode", "config", "tasks")})


# ---------------------------------------------------------------- 任务校验

def check_task(t, repo, known):
    if not isinstance(t, dict):
        fail("每个任务都必须是 JSON 对象")
    extra = set(t) - TASK_KEYS
    if extra:
        fail(f"任务有未知字段：{sorted(extra)}")
    tid = t.get("id")
    if not isinstance(tid, str) or not TASK_ID_RE.fullmatch(tid):
        fail("任务 id 只能由字母、数字、'_'、'-' 组成")
    if tid in known:
        fail(f"任务 id 重复：{tid}")
    if not isinstance(t.get("title"), str) or not t["title"].strip():
        fail(f"任务 {tid} 需要 title（一句话说明交付什么）")
    scenario, check = t.get("scenario"), t.get("check")
    if bool(scenario) == bool(check):
        fail(f"任务 {tid} 需要 scenario（由 evloop 运行目录裁决）或 check（一条验收命令）之一")
    out = {"id": tid, "title": t["title"].strip(), "depends": list(dict.fromkeys(t.get("depends") or [])),
           "max_attempts": t.get("max_attempts") or 3, "approve": bool(t.get("approve"))}
    if not isinstance(out["max_attempts"], int) or isinstance(out["max_attempts"], bool) or out["max_attempts"] < 1:
        fail(f"任务 {tid} 的 max_attempts 必须是正整数")
    if scenario:
        if scenario not in SCENARIOS:
            fail(f"任务 {tid} 的 scenario 必须是 {', '.join(SCENARIOS)} 之一")
        run = norm(t.get("run") or f"{STATE_DIR}/runs/{tid}")
        if os.path.isabs(run) or not in_scope(run, [f"{STATE_DIR}/runs"]) or run == f"{STATE_DIR}/runs":
            fail(f"任务 {tid} 的 run 必须是仓库内 {STATE_DIR}/runs/ 下的相对路径")
        out.update(scenario=scenario, run=run)
    else:
        if not isinstance(check, str) or not check.strip():
            fail(f"任务 {tid} 的 check 必须是命令字符串")
        if t.get("run"):
            fail(f"任务 {tid} 用 check 验收时不需要 run")
        out["check"] = check
    if t.get("notes"):
        out["notes"] = str(t["notes"])
    missing = [d for d in out["depends"] if d not in known]
    if missing:
        fail(f"任务 {tid} 依赖的任务尚未登记：{missing}（先登记被依赖的任务）")
    if tid in out["depends"]:
        fail(f"任务 {tid} 不能依赖自己")
    return out


def _new_task_state():
    return {"status": "pending", "failures": 0, "sessions": 0}


# ---------------------------------------------------------------- 推进逻辑

def ready_tasks(plan, state):
    """依赖都已完成、尚未结束的任务；上一会话没收尾的 active 任务排在最前。"""
    done = {tid for tid, s in state["tasks"].items() if s["status"] == "done"}
    ready = [t["id"] for t in plan["tasks"]
             if state["tasks"][t["id"]]["status"] in ("pending", "active") and set(t["depends"]) <= done]
    return sorted(ready, key=lambda tid: state["tasks"][tid]["status"] != "active")


def blocked_tasks(plan, state):
    """被失败任务（直接或间接）卡住的任务。"""
    dead = {tid for tid, s in state["tasks"].items() if s["status"] == "failed"}
    changed = True
    while changed:
        changed = False
        for t in plan["tasks"]:
            if t["id"] not in dead and state["tasks"][t["id"]]["status"] != "done" and set(t["depends"]) & dead:
                dead.add(t["id"])
                changed = True
    return [t["id"] for t in plan["tasks"] if t["id"] in dead and state["tasks"][t["id"]]["status"] != "failed"]


def elapsed_hours(state, now=None):
    if not state.get("cycle_started"):
        return 0.0
    now = now or utc_now()
    return (now - parse_iso(state["cycle_started"])).total_seconds() / 3600.0


def stop_reason(plan, state, tamper=None, now=None):
    if tamper:
        return "plan tampered"
    if state.get("stopped"):
        return "stopped"
    statuses = [state["tasks"][t["id"]]["status"] for t in plan["tasks"]]
    if plan["tasks"] and all(s == "done" for s in statuses):
        return "all done"
    cfg = plan["config"]
    if state.get("consecutive_failures", 0) >= cfg["max_consecutive_failures"]:
        return "too many failures"
    if cfg.get("cycle_hours") and elapsed_hours(state, now) >= cfg["cycle_hours"]:
        return "cycle exhausted"
    if plan["tasks"] and not ready_tasks(plan, state):
        return "blocked"
    if plan["mode"] == "confirm" and (state.get("approved") or {}).get("definition") != definition_sha(plan):
        return "awaiting plan approval"
    return None


def task_by_id(plan, tid):
    for t in plan["tasks"]:
        if t["id"] == tid:
            return t
    fail(f"计划里没有任务 {tid}")


def run_status(plan, t):
    """读取任务对应运行目录的裁判状态；不存在时返回 None。"""
    if not t.get("run"):
        return None
    home = Home(os.path.join(plan["repo"], t["run"]))
    if not home.exists():
        return {"exists": False}
    from .judge import execution_status
    try:
        c = home.load()
        s = execution_status(home, c)
    except Exception as e:  # noqa: BLE001 —— 监控要把问题报出来，而不是崩溃
        return {"exists": True, "error": str(e)}
    out = {"exists": True, "scenario": c["scenario"], "decision": s["decision"],
           "goal_met": bool(s.get("goal_met")), "verification_current": s["verification_current"],
           "approved": bool(s["approved"]), "best": (c.get("best") or "")[:12] or None,
           "attempts": s["attempts"], "next": s["next"]}
    if c["scenario"] != t["scenario"]:
        out["error"] = f"运行目录的场景是 {c['scenario']}，计划约定的是 {t['scenario']}"
    return out


def overview(pl, plan, state, tamper=None, last=8):
    now = utc_now()
    reason = stop_reason(plan, state, tamper, now)
    tasks = []
    for t in plan["tasks"]:
        s = state["tasks"][t["id"]]
        item = {"id": t["id"], "title": t["title"], "status": s["status"], "failures": s["failures"],
                "depends": t["depends"]}
        if t.get("scenario"):
            item["scenario"], item["run"] = t["scenario"], t["run"]
            rs = run_status(plan, t)
            if rs and rs.get("exists"):
                item["run_state"] = {k: rs[k] for k in ("decision", "goal_met", "verification_current",
                                                        "approved", "attempts", "error") if k in rs}
        if s.get("evidence"):
            item["evidence"] = s["evidence"]
        if s.get("last_reason"):
            item["last_reason"] = s["last_reason"]
        tasks.append(item)
    counts = {k: sum(1 for t in tasks if t["status"] == k) for k in STATUSES}
    last_activity = state.get("last_activity")
    out = {"goal": plan["goal"], "mode": plan["mode"], "counts": counts,
           "consecutive_failures": state.get("consecutive_failures", 0),
           "max_consecutive_failures": plan["config"]["max_consecutive_failures"],
           "sessions": state.get("sessions", 0),
           "elapsed_hours": round(elapsed_hours(state, now), 2), "cycle_hours": plan["config"].get("cycle_hours"),
           "last_activity": last_activity,
           "idle_minutes": (round((now - parse_iso(last_activity)).total_seconds() / 60, 1)
                            if last_activity else None),
           "ready": ready_tasks(plan, state), "blocked": blocked_tasks(plan, state),
           "stop_reason": reason, "stop_words": STOP_WORDS.get(reason),
           "decision": "stop" if reason else "continue", "tasks": tasks,
           "assumptions": plan.get("assumptions", []),
           "recent_events": pl.events(last)}
    if tamper:
        out["tamper"] = tamper
    if plan["mode"] == "confirm":
        out["plan_approved"] = (state.get("approved") or {}).get("definition") == definition_sha(plan)
    return out


# ---------------------------------------------------------------- 提示词

def build_prompt(pl, plan, state):
    reason = stop_reason(plan, state)
    plan_home = pl.path
    repo = plan["repo"]
    lines = [f"# 计划续跑：{plan['goal']}", "",
             "你在一个由 evidence-loop 管理的跨会话计划里。这段提示词是自包含的：不要依赖之前会话的记忆，",
             "一切以磁盘上的状态与裁判输出为准。", "",
             "## 位置", f"- 仓库：`{repo}`", f"- 计划目录：`{plan_home}`", f"- 裁判：`python3 {EVLOOP}`", "",
             "## 本次会话只做一件事"]
    lines += [
        f"1. 运行 `python3 {EVLOOP} --home {plan_home} plan next`。decision 为 stop 时，"
        "向人汇报 stop_reason 与 status 摘要，然后结束——不要再排期。",
        "2. 拿到的任务若带 run（evloop 运行目录）："
        f"先运行 `python3 {EVLOOP} --home <repo>/<run> resume`；运行目录不存在时按场景完成澄清并 init、start。"
        "然后按 evidence-loop 的循环推进，直到 status 的 decision 为 handoff，再 verify、report。",
        "   任务带 check 时：完成工作后由 plan done 运行那条命令判定。",
        f"3. 完成后运行 `python3 {EVLOOP} --home {plan_home} plan done --task <id>`；裁判不认可就是没完成。"
        f"本次会话没能完成时运行 `plan fail --task <id> --reason \"…\"`，写清卡在哪里。",
        "4. 先更新计划状态，再排期。最后运行 "
        f"`python3 {EVLOOP} --home {plan_home} plan prompt --out <文件>` 取得下一会话的提示词与建议延迟；"
        "decision 为 continue 时，在调用定时任务能力之前的最后一刻计算触发时间（当前时间 + delay_seconds），"
        "用这段新提示词排期下一会话。",
        "",
        "## 安全规则",
        "- 不手工编辑 plan.json、state.json、contract.json、attempts.jsonl；它们被封存，改动会让计划停止。",
        "- 不为了让任务通过而修改冻结文件、验收命令或评分细则；需要改约定时停下来，交给人重新澄清。",
        "- 任务要求人工批准（approve）时，交付评审包后结束本会话，由人运行 approve；不要替人批准。",
        "- 一个会话只推进一个任务；不确定的事情停下来问人，或在自动模式下用 plan assume 记录假设。",
        "- 不合并到受保护分支，不发布到外部，除非任务和人工批准都明确允许。",
    ]
    if plan["mode"] == "auto":
        lines += ["", "## 自动模式",
                  "这个计划运行在自动模式：遇到需要人拍板的小决定时自行决定，但必须用 "
                  f"`python3 {EVLOOP} --home {plan_home} plan assume --text \"…\"` 记录这条假设，"
                  "交付时人会逐条复核。涉及删除数据、对外发布、花钱的决定一律停下来问人。"]
        if plan.get("assumptions"):
            lines += ["", "已记录的假设："] + [f"- {a['text']}" for a in plan["assumptions"][-10:]]
    nxt = ready_tasks(plan, state)
    lines += ["", "## 当前快照（仅供参考，以 plan next 为准）",
              f"- 会话数：{state.get('sessions', 0)}；连续失败：{state.get('consecutive_failures', 0)}"
              f"/{plan['config']['max_consecutive_failures']}",
              f"- 就绪任务：{', '.join(nxt) or '无'}",
              f"- 停止原因：{STOP_WORDS.get(reason, '无')}"]
    if nxt:
        head = task_by_id(plan, nxt[0])
        hs = state["tasks"][head["id"]]
        lines.append(f"- 下一个任务 `{head['id']}`：{head['title']}"
                     f"（已失败 {hs['failures']}/{head['max_attempts']} 次）")
        if hs.get("last_reason"):
            lines.append(f"- 上次卡在：{hs['last_reason']}——先针对它换思路，别原样重来")
        if head.get("notes"):
            lines.append(f"- 补充说明：{head['notes']}")
    return "\n".join(lines) + "\n", reason


def doctor_checks(path, check):
    """doctor 的计划体检：封存、任务登记、运行目录契约。check(name, ok, detail)。只读。"""
    pl = Plan(path)
    try:
        plan, state, tamper = pl.load(strict=False)
    except Exception as e:  # noqa: BLE001 —— 体检要把所有问题都报出来
        check("plan", False, str(e))
        return
    if plan is None or state is None:
        check("plan", False, tamper)
        return
    check("plan", not tamper, tamper or f"{len(plan['tasks'])} 个任务，封存校验通过")
    missing = [t["id"] for t in plan["tasks"] if t["id"] not in state["tasks"]]
    check("plan_state", not missing, ("状态里缺少任务：" + ", ".join(missing)) if missing else "任务与状态一致")
    if missing:
        return
    from . import gitops as g
    check("plan_repo", g.is_work_tree(plan["repo"]), plan["repo"])
    for t in plan["tasks"]:
        if not t.get("run") or state["tasks"][t["id"]]["status"] == "done":
            continue
        rs = run_status(plan, t)
        if rs.get("exists"):
            check(f"task:{t['id']}", not rs.get("error"),
                  rs.get("error") or f"{rs['scenario']}，{rs['decision']}，下一步：{rs['next']}")
    reason = stop_reason(plan, state, tamper)
    check("plan_stop", reason in (None, "all done"), STOP_WORDS.get(reason) or "可以继续")


# ---------------------------------------------------------------- 命令

def _require_plan_dir(pl, repo):
    plans = os.path.join(repo, PLANS_DIR)
    if not inside(pl.path, plans) or os.path.realpath(pl.path) == os.path.realpath(plans):
        fail(f"计划的 --home 必须是 <repo>/{PLANS_DIR}/ 下的一个目录，例如 " + os.path.join(plans, "project"))


def _touch(state):
    state["last_activity"] = iso(utc_now())


def cmd_init(a, pl):
    from . import gitops as g
    repo = os.path.abspath(a.repo)
    g.require_work_tree(repo, "--repo")
    repo = g.toplevel(repo)
    _require_plan_dir(pl, repo)
    if a.max_consecutive_failures is not None and a.max_consecutive_failures < 1:
        fail("--max-consecutive-failures 必须是正整数")
    if a.cycle_hours is not None and a.cycle_hours <= 0:
        fail("--cycle-hours 必须是正数")
    if a.delay_minutes is not None and a.delay_minutes < 0:
        fail("--delay-minutes 必须是非负数")
    if not a.goal.strip():
        fail("--goal 不能为空")
    with pl.lock():
        if pl.exists() and not a.renew:
            fail("计划已存在；需要重建时用 --renew（旧文件会归档为 .bak）")
        tasks = []
        if a.tasks:
            try:
                with open(a.tasks, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError) as e:
                fail(f"--tasks 读取失败：{e}")
            if not isinstance(raw, list) or not raw:
                fail("--tasks 必须是非空的任务列表")
            known = set()
            for t in raw:
                tasks.append(check_task(t, repo, known))
                known.add(tasks[-1]["id"])
        now = iso(utc_now())
        plan = {"version": 1, "goal": a.goal.strip(), "mode": a.mode, "repo": repo, "created": now,
                "config": {"max_consecutive_failures": a.max_consecutive_failures or 3,
                           "cycle_hours": a.cycle_hours, "delay_seconds": int((a.delay_minutes or 5) * 60)},
                "tasks": tasks, "assumptions": [{"time": now, "text": x} for x in (a.assume or [])]}
        state = {"tasks": {t["id"]: _new_task_state() for t in tasks}, "consecutive_failures": 0,
                 "sessions": 0, "cycle_started": now, "stopped": None, "approved": None, "last_activity": now}
        if pl.exists():
            stamp = now.replace(":", "")
            for path in (pl.plan_path, pl.state_path):
                if os.path.exists(path):
                    os.replace(path, f"{path}.{stamp}.bak")
        g.add_exclude(repo)
        pl.save(plan, state)
        pl.log("init", goal=plan["goal"], mode=plan["mode"], tasks=[t["id"] for t in tasks])
        _emit(overview(pl, plan, state))
        return ACCEPTED


def cmd_add(a, pl):
    with pl.lock():
        plan, state, _ = pl.load()
        raw = {"id": a.id, "title": a.title, "scenario": a.scenario, "run": a.run, "check": a.check,
               "depends": a.depends, "max_attempts": a.max_attempts, "approve": a.approve, "notes": a.notes}
        task = check_task({k: v for k, v in raw.items() if v not in (None, False, [])}, plan["repo"],
                          {t["id"] for t in plan["tasks"]})
        if task.get("run") and any(t.get("run") == task["run"] for t in plan["tasks"]):
            fail(f"运行目录 {task['run']} 已被别的任务使用")
        plan["tasks"].append(task)
        state["tasks"][task["id"]] = _new_task_state()
        _touch(state)
        pl.save(plan, state)
        pl.log("add", task=task["id"])
        _emit(task)
        return ACCEPTED


def cmd_assume(a, pl):
    if not a.text.strip():
        fail("--text 不能为空")
    with pl.lock():
        plan, state, _ = pl.load()
        entry = {"time": iso(utc_now()), "text": a.text.strip()}
        if a.task:
            task_by_id(plan, a.task)
            entry["task"] = a.task
        plan.setdefault("assumptions", []).append(entry)
        _touch(state)
        pl.save(plan, state)
        pl.log("assume", **entry)
        _emit(entry)
        return ACCEPTED


def cmd_approve(a, pl):
    with pl.lock():
        plan, state, _ = pl.load()
        if not plan["tasks"]:
            fail("计划里还没有任务")
        state["approved"] = {"at": iso(utc_now()), "definition": definition_sha(plan), "note": a.note or ""}
        _touch(state)
        pl.save(plan, state)
        pl.log("approve", note=a.note or "")
        _emit(state["approved"])
        return ACCEPTED


def _record_failure(state, t, reason):
    """记一次失败：任务失败数与连续失败数各加一，达到 max_attempts 判失败。"""
    s = state["tasks"][t["id"]]
    s["failures"] += 1
    s["last_reason"] = reason
    if s["failures"] >= t["max_attempts"]:
        s["status"] = "failed"
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1


def cmd_next(a, pl):
    with pl.lock():
        plan, state, tamper = pl.load(strict=False)
        if plan is None or state is None:
            fail(tamper, INVALID)
        changed = False
        while True:
            reason = stop_reason(plan, state, tamper)
            if reason:
                if changed:
                    pl.save(plan, state)
                pl.log("stop", reason=reason)
                out = overview(pl, plan, state, tamper, last=3)
                _emit({k: out[k] for k in ("decision", "stop_reason", "stop_words", "counts", "consecutive_failures",
                                           "elapsed_hours", "blocked", "abandoned") if k in out})
                return INVALID if tamper else REJECTED
            tid = ready_tasks(plan, state)[0]
            t = task_by_id(plan, tid)
            s = state["tasks"][tid]
            if s["status"] != "active":
                break
            # 上一会话领了任务却没有收尾（崩溃、超时、忘了记录）：记一次失败再重新判定
            _record_failure(state, t, "上一会话领取了这个任务，但没有记录 done 或 fail 就结束了")
            s["status"] = "failed" if s["status"] == "failed" else "pending"
            _touch(state)
            changed = True
            pl.log("abandoned", task=tid, failures=s["failures"], status=s["status"])
        s["status"] = "active"
        s["sessions"] += 1
        state["sessions"] = state.get("sessions", 0) + 1
        _touch(state)
        pl.save(plan, state)
        pl.log("next", task=tid, session=state["sessions"])
        out = {"decision": "continue", "task": t, "attempts_used": s["failures"],
               "attempts_left": t["max_attempts"] - s["failures"]}
        if s.get("last_reason"):
            out["last_reason"] = s["last_reason"]
        if t.get("run"):
            out["run_home"] = os.path.join(plan["repo"], t["run"])
            rs = run_status(plan, t)
            out["run_state"] = rs
            out["hint"] = (f"python3 {EVLOOP} --home {out['run_home']} resume" if rs and rs.get("exists")
                           else f"按 {t['scenario']} 场景澄清后 init（--home {out['run_home']}）")
        else:
            out["hint"] = "完成后运行 plan done，由 check 命令判定"
        _emit(out)
        return ACCEPTED


def _evidence(plan, t, home_path):
    """任务完成的证据：成立时返回 (True, 证据)，否则 (False, 原因)。"""
    if t.get("check"):
        raw = os.path.join(home_path, "raw", f"check-{t['id']}.log")
        r = run_command(t["check"], plan["repo"], raw)
        if r.code != 0:
            return False, (f"check 命令{'超时' if r.timed_out else f'退出码 {r.code}'}"
                           f"（见 raw/check-{t['id']}.log）")
        return True, {"check_exit": 0, "raw": f"raw/check-{t['id']}.log"}
    rs = run_status(plan, t)
    if not rs or not rs.get("exists"):
        return False, f"运行目录 {t['run']} 还没有契约；先完成澄清与 init"
    if rs.get("error"):
        return False, rs["error"]
    if not rs["goal_met"]:
        return False, f"运行目录尚未达成约定目标（下一步：{rs['next']}）"
    if not rs["verification_current"]:
        return False, "运行目录的最终验证缺失或已过期；先运行 verify"
    if t.get("approve") and not rs["approved"]:
        return False, "这个任务要求人工批准；呈交评审包，等人运行 approve"
    return True, {"run": t["run"], "best": rs["best"], "attempts": rs["attempts"], "approved": rs["approved"]}


def cmd_done(a, pl):
    with pl.lock():
        plan, state, _ = pl.load()
        t = task_by_id(plan, a.task)
        s = state["tasks"][t["id"]]
        if s["status"] == "done":
            fail(f"任务 {t['id']} 已经完成")
        if s["status"] == "failed":
            fail(f"任务 {t['id']} 已判失败；需要重试时先 plan retry")
        unmet = [d for d in t["depends"] if state["tasks"][d]["status"] != "done"]
        if unmet:
            fail(f"任务 {t['id']} 的依赖尚未完成：{unmet}")
        ok, ev = _evidence(plan, t, pl.path)
        if not ok:
            pl.log("done_refused", task=t["id"], reason=ev)
            _emit({"task": t["id"], "done": False, "reason": ev})
            return REJECTED
        s.update(status="done", evidence=ev, completed=iso(utc_now()))
        s.pop("last_reason", None)
        state["consecutive_failures"] = 0
        _touch(state)
        pl.save(plan, state)
        pl.log("done", task=t["id"], evidence=ev)
        _emit({"task": t["id"], "done": True, "evidence": ev, "stop_reason": stop_reason(plan, state)})
        return ACCEPTED


def cmd_fail(a, pl):
    if not a.reason.strip():
        fail("--reason 不能为空：写清这次卡在哪里，下一会话才接得上")
    with pl.lock():
        plan, state, _ = pl.load()
        t = task_by_id(plan, a.task)
        s = state["tasks"][t["id"]]
        if s["status"] in ("done", "failed"):
            fail(f"任务 {t['id']} 的状态是 {s['status']}，不能再记失败")
        _record_failure(state, t, a.reason.strip())
        if s["status"] == "active":
            s["status"] = "pending"
        _touch(state)
        pl.save(plan, state)
        pl.log("fail", task=t["id"], reason=s["last_reason"], failures=s["failures"])
        _emit({"task": t["id"], "status": s["status"], "failures": s["failures"],
               "consecutive_failures": state["consecutive_failures"], "stop_reason": stop_reason(plan, state)})
        return REJECTED


def cmd_retry(a, pl):
    with pl.lock():
        plan, state, _ = pl.load()
        t = task_by_id(plan, a.task)
        s = state["tasks"][t["id"]]
        if s["status"] != "failed":
            fail(f"任务 {t['id']} 没有判失败，不需要 retry")
        s.update(status="pending", failures=0)
        _touch(state)
        pl.save(plan, state)
        pl.log("retry", task=t["id"], note=a.note or "")
        _emit({"task": t["id"], "status": "pending"})
        return ACCEPTED


def cmd_stop(a, pl):
    with pl.lock():
        plan, state, _ = pl.load()
        state["stopped"] = {"at": iso(utc_now()), "reason": a.reason or "人工停止"}
        _touch(state)
        pl.save(plan, state)
        pl.log("manual_stop", reason=state["stopped"]["reason"])
        _emit(state["stopped"])
        return ACCEPTED


def cmd_restart(a, pl):
    """清除人工停止与连续失败计数，重新开始计周期时长。"""
    with pl.lock():
        plan, state, _ = pl.load()
        state.update(stopped=None, consecutive_failures=0, cycle_started=iso(utc_now()))
        _touch(state)
        pl.save(plan, state)
        pl.log("restart", note=a.note or "")
        _emit(overview(pl, plan, state, last=3))
        return ACCEPTED


def cmd_status(a, pl):
    plan, state, tamper = pl.load(strict=False)
    if plan is None or state is None:
        fail(tamper, INVALID)
    _emit(overview(pl, plan, state, tamper, last=a.last))
    return INVALID if tamper else ACCEPTED


def cmd_prompt(a, pl):
    with pl.lock():
        plan, state, tamper = pl.load(strict=False)
        if plan is None or state is None:
            fail(tamper, INVALID)
        text, reason = build_prompt(pl, plan, state)
        reason = "plan tampered" if tamper else reason
        out = {"decision": "stop" if reason else "continue", "stop_reason": reason,
               "stop_words": STOP_WORDS.get(reason)}
        if not reason:
            out["schedule"] = {"delay_seconds": plan["config"]["delay_seconds"],
                               "rule": "在调用定时任务能力之前的最后一刻计算触发时间 = 当前时间 + delay_seconds"}
        if a.out:
            atomic_write_text(a.out, text)
            out["prompt_file"] = os.path.abspath(a.out)
        else:
            out["prompt"] = text
        pl.log("prompt", decision=out["decision"], reason=reason)
        _emit(out)
        return ACCEPTED if not reason else (INVALID if tamper else REJECTED)


def cmd_report(a, pl):
    """plan.html：任务依赖图（按状态着色）、任务表、假设与最近事件。只读计划，不改状态。"""
    plan, state, tamper = pl.load(strict=False)
    if plan is None or state is None:
        fail(tamper, INVALID)
    if not plan["tasks"]:
        fail("计划里还没有任务")
    ov = overview(pl, plan, state, tamper, last=15)
    esc = render.esc
    diagram = {"nodes": [{"id": t["id"], "label": t["title"][:24], "sublabel": t.get("scenario") or "check",
                          "kind": "service" if t.get("scenario") else "flow"} for t in plan["tasks"]],
               "edges": [{"from": d, "to": t["id"]} for t in plan["tasks"] for d in t["depends"]],
               "depends": {t["id"]: t["depends"] for t in plan["tasks"] if t["depends"]}}
    progress = {t["id"]: ("done" if state["tasks"][t["id"]]["status"] == "done" else "pending")
                for t in plan["tasks"] if state["tasks"][t["id"]]["status"] in ("done", "active")}
    body = render.stats([("完成", f'{ov["counts"]["done"]}/{len(plan["tasks"])}'),
                         ("失败", ov["counts"]["failed"]), ("会话数", ov["sessions"]),
                         ("连续失败", f'{ov["consecutive_failures"]}/{ov["max_consecutive_failures"]}'),
                         ("已用时长", f'{ov["elapsed_hours"]:g} 小时')])
    if tamper:
        body += f'<p class="bad">{esc(tamper)}</p>'
    body += render.section("下一步", '<p class="next-action">' + esc(
        ("停止：" + ov["stop_words"]) if ov["stop_reason"] else "继续：" + ", ".join(ov["ready"])) + "</p>")
    body += render.section("任务依赖", render.graph_svg(diagram, progress))
    rows = []
    for t in ov["tasks"]:
        cls = {"done": "ok", "failed": "bad"}.get(t["status"], "warn")
        rows.append([f'<code>{esc(t["id"])}</code>', esc(t["title"]), f'<span class="{cls}">{esc(t["status"])}</span>',
                     esc(t.get("scenario") or "check"), esc(", ".join(t["depends"]) or "—"), t["failures"],
                     esc(t.get("last_reason") or "")])
    body += render.section("任务", render.table(["任务", "交付", "状态", "裁决方式", "依赖", "失败", "最近原因"], rows))
    if ov["assumptions"]:
        body += render.section("自动模式记录的假设（需人工复核）", render.table(
            ["时间", "任务", "假设"], [[esc(x["time"]), esc(x.get("task") or "—"), esc(x["text"])]
                                   for x in ov["assumptions"]]))
    body += render.section("最近事件", render.table(
        ["时间", "事件", "详情"],
        [[esc(e.get("time")), esc(e.get("event")),
          esc(json.dumps({k: v for k, v in e.items() if k not in ("time", "event")}, ensure_ascii=False))]
         for e in ov["recent_events"]]))
    output = os.path.abspath(a.out or os.path.join(pl.path, "plan.html"))
    render.write_page(output, f"计划 — {plan['goal'][:40]}",
                      f'<span class="badge">{"自动" if plan["mode"] == "auto" else "确认"}模式</span> '
                      f'{esc(ov["stop_words"] or "进行中")}', body)
    _emit({"plan_html": output, "decision": ov["decision"]})
    return ACCEPTED


ACTIONS = {"init": cmd_init, "add": cmd_add, "assume": cmd_assume, "approve": cmd_approve, "next": cmd_next,
           "done": cmd_done, "fail": cmd_fail, "retry": cmd_retry, "stop": cmd_stop, "restart": cmd_restart,
           "status": cmd_status, "prompt": cmd_prompt, "report": cmd_report}


def cmd_plan(a):
    pl = Plan(a.home)
    if a.plan_cmd != "init" and not pl.exists():
        fail(f"{pl.plan_path} 不存在；先运行 plan init", PRECONDITION)
    return ACTIONS[a.plan_cmd](a, pl)


def add_parser(sub):
    p = sub.add_parser("plan", help="跨会话计划：任务、依赖、停止条件、下一会话提示词")
    ps = p.add_subparsers(dest="plan_cmd", metavar="动作")
    ps.required = True
    i = ps.add_parser("init", help="创建计划（--home 为 <repo>/.evloop/plans/<project>）")
    i.add_argument("--repo", default=".", help="工作克隆，默认当前目录")
    i.add_argument("--goal", required=True, help="一句话目标：做完之后什么成立")
    i.add_argument("--mode", choices=MODES, default="confirm",
                   help="confirm：计划需人工 plan approve 后才开始；auto：不等批准，但每个自行做出的决定都要 plan assume 记录")
    i.add_argument("--tasks", help="任务清单 JSON（列表），字段见 references/plan.md")
    i.add_argument("--max-consecutive-failures", type=int, help="连续失败多少次后停止，默认 3")
    i.add_argument("--cycle-hours", type=float, help="整个计划的周期时长上限（小时），用完即停止")
    i.add_argument("--delay-minutes", type=float, help="建议的下一会话延迟（分钟），默认 5")
    i.add_argument("--assume", action="append", help="自动模式下预先记录的假设，可重复")
    i.add_argument("--renew", action="store_true", help="覆盖已有计划（旧文件归档为 .bak）")
    ad = ps.add_parser("add", help="登记一个任务")
    ad.add_argument("--id", required=True)
    ad.add_argument("--title", required=True, help="一句话说明交付什么")
    ad.add_argument("--scenario", choices=SCENARIOS, help="由 evloop 运行目录裁决时的场景")
    ad.add_argument("--run", help=f"运行目录（仓库内 {STATE_DIR}/runs/ 下），默认 {STATE_DIR}/runs/<id>")
    ad.add_argument("--check", help="不走 evloop 运行目录时的验收命令（退出码 0 即完成）")
    ad.add_argument("--depends", nargs="+", help="依赖的任务 id")
    ad.add_argument("--max-attempts", type=int, help="这个任务最多失败几次（会话）后判失败，默认 3")
    ad.add_argument("--approve", action="store_true", help="完成前需要人工批准运行目录的评审包")
    ad.add_argument("--notes", help="补充说明")
    asm = ps.add_parser("assume", help="记录一条自行做出的假设（自动模式）")
    asm.add_argument("--text", required=True)
    asm.add_argument("--task", help="相关任务 id")
    apv = ps.add_parser("approve", help="人工批准计划（确认模式）；计划再被修改需要重新批准")
    apv.add_argument("--note", help="批准说明")
    ps.add_parser("next", help="检查停止条件并领取下一个就绪任务")
    dn = ps.add_parser("done", help="凭裁判证据把任务标为完成")
    dn.add_argument("--task", required=True)
    fl = ps.add_parser("fail", help="记录本会话没能完成任务")
    fl.add_argument("--task", required=True)
    fl.add_argument("--reason", required=True, help="卡在哪里")
    rt = ps.add_parser("retry", help="把判失败的任务重新放回待办")
    rt.add_argument("--task", required=True)
    rt.add_argument("--note", help="为什么重试")
    st = ps.add_parser("stop", help="人工停止计划")
    st.add_argument("--reason", help="停止原因")
    rs = ps.add_parser("restart", help="清除停止标记与连续失败计数，重新计周期")
    rs.add_argument("--note", help="说明")
    ss = ps.add_parser("status", help="监控视图：任务、计数、停止条件、最近事件（只读）")
    ss.add_argument("--last", type=int, default=8, help="附带最近几条事件，默认 8")
    pr = ps.add_parser("prompt", help="生成自包含的下一会话提示词与建议延迟")
    pr.add_argument("--out", help="把提示词写到文件")
    rp = ps.add_parser("report", help="生成 plan.html 监控页（只读）")
    rp.add_argument("--out", help="输出路径，默认计划目录下的 plan.html")
    p.set_defaults(fn=cmd_plan)
    return p

