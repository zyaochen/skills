"""跨会话计划：生命周期、证据门槛、停止条件、篡改检测、下一会话提示词。"""
import json
import os
import sys
import tempfile
import unittest

import helpers
from helpers import git, sh, write
from evloop import plan as pm

TASKS = [{"id": "a", "title": "生成 a", "check": "test -f a.txt"},
         {"id": "b", "title": "生成 b", "check": "test -f b.txt", "depends": ["a"], "max_attempts": 2},
         {"id": "c", "title": "依赖 b 的收尾", "check": "test -f c.txt", "depends": ["b"]}]


class PlanUnitTests(unittest.TestCase):
    def mk(self, tasks=None, mode="auto", **cfg):
        tasks = tasks or [pm.check_task(t, "/r", {x["id"] for x in TASKS[:i]}) for i, t in enumerate(TASKS)]
        plan = {"goal": "g", "mode": mode, "repo": "/r", "tasks": tasks,
                "config": dict({"max_consecutive_failures": 3, "cycle_hours": None, "delay_seconds": 60}, **cfg)}
        state = {"tasks": {t["id"]: {"status": "pending", "failures": 0, "sessions": 0} for t in tasks},
                 "consecutive_failures": 0, "cycle_started": "2026-01-01T00:00:00+00:00"}
        return plan, state

    def test_check_task_rules(self):
        with self.assertRaises(Exception):
            pm.check_task({"id": "x", "title": "t"}, "/r", set())  # 既无 scenario 也无 check
        with self.assertRaises(Exception):
            pm.check_task({"id": "x", "title": "t", "check": "true", "scenario": "bugfix"}, "/r", set())
        with self.assertRaises(Exception):
            pm.check_task({"id": "x", "title": "t", "check": "true", "depends": ["y"]}, "/r", set())
        with self.assertRaises(Exception):
            pm.check_task({"id": "x", "title": "t", "scenario": "research", "run": "../out"}, "/r", set())
        t = pm.check_task({"id": "x", "title": "t", "scenario": "research"}, "/r", set())
        self.assertEqual(t["run"], ".evloop/runs/x")
        self.assertEqual(t["max_attempts"], 3)

    def test_ready_and_blocked(self):
        plan, state = self.mk()
        self.assertEqual(pm.ready_tasks(plan, state), ["a"])
        state["tasks"]["a"]["status"] = "failed"
        self.assertEqual(pm.blocked_tasks(plan, state), ["b", "c"])
        self.assertEqual(pm.stop_reason(plan, state), "blocked")

    def test_stop_order(self):
        plan, state = self.mk()
        self.assertIsNone(pm.stop_reason(plan, state, now=pm.parse_iso("2026-01-01T01:00:00+00:00")))
        self.assertEqual(pm.stop_reason(plan, state, tamper="x"), "plan tampered")
        state["consecutive_failures"] = 3
        self.assertEqual(pm.stop_reason(plan, state), "too many failures")
        state["stopped"] = {"reason": "人"}
        self.assertEqual(pm.stop_reason(plan, state), "stopped")
        plan, state = self.mk(cycle_hours=2)
        self.assertEqual(pm.stop_reason(plan, state, now=pm.parse_iso("2026-01-01T03:00:00+00:00")),
                         "cycle exhausted")
        plan, state = self.mk(mode="confirm")
        self.assertEqual(pm.stop_reason(plan, state, now=pm.parse_iso("2026-01-01T01:00:00+00:00")),
                         "awaiting plan approval")
        state["approved"] = {"definition": pm.definition_sha(plan)}
        self.assertIsNone(pm.stop_reason(plan, state, now=pm.parse_iso("2026-01-01T01:00:00+00:00")))
        plan["tasks"][0]["title"] = "改过的计划"
        self.assertEqual(pm.stop_reason(plan, state, now=pm.parse_iso("2026-01-01T01:00:00+00:00")),
                         "awaiting plan approval", "计划改动后批准失效")
        for s in state["tasks"].values():
            s["status"] = "done"
        self.assertEqual(pm.stop_reason(plan, state), "all done")

    def test_seal_detects_edits(self):
        obj = {"a": 1}
        obj["plan_sha"] = pm.seal(obj, "plan_sha")
        self.assertEqual(obj["plan_sha"], pm.seal(obj, "plan_sha"))
        obj["a"] = 2
        self.assertNotEqual(obj["plan_sha"], pm.seal(obj, "plan_sha"))


class PlanEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "README.md", "x\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        self.home = os.path.join(self.repo, ".evloop", "plans", "demo")
        self.tasks = os.path.join(self.root, "tasks.json")
        with open(self.tasks, "w", encoding="utf-8") as f:
            json.dump(TASKS, f, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, *args, home=None):
        r = sh(self.repo, sys.executable, helpers.JUDGE, "--home", home or self.home, "plan", *args)
        out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
        return r.returncode, out, r.stderr

    def init(self, *extra, mode="confirm"):
        code, out, err = self.plan("init", "--repo", self.repo, "--goal", "三步演示", "--mode", mode,
                                   "--tasks", self.tasks, *extra)
        self.assertEqual(code, 0, err)
        return out

    def touch(self, name):
        write(self.repo, name, "ok\n")

    def test_confirm_lifecycle(self):
        out = self.init()
        self.assertEqual(out["stop_reason"], "awaiting plan approval")
        self.assertEqual(self.plan("next")[0], 1)
        self.assertEqual(self.plan("approve", "--note", "看过了")[0], 0)
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["task"]["id"]), (0, "a"))
        code, out, _ = self.plan("done", "--task", "a")
        self.assertEqual((code, out["done"]), (1, False), "没有证据不能标完成")
        self.touch("a.txt")
        code, out, _ = self.plan("done", "--task", "a")
        self.assertEqual((code, out["done"]), (0, True))
        self.assertEqual(self.plan("done", "--task", "c")[0], 3, "依赖未完成")
        for name in ("b", "c"):
            self.assertEqual(self.plan("next")[1]["task"]["id"], name)
            self.touch(f"{name}.txt")
            self.assertEqual(self.plan("done", "--task", name)[0], 0)
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["stop_reason"]), (1, "all done"))
        code, out, _ = self.plan("prompt")
        self.assertEqual((code, out["decision"]), (1, "stop"))
        self.assertNotIn("schedule", out)
        code, out, _ = self.plan("status")
        self.assertEqual(out["counts"]["done"], 3)
        self.assertEqual(out["sessions"], 3)

    def test_failures_block_and_stop(self):
        self.init(mode="auto")
        self.touch("a.txt")
        self.plan("next")
        self.plan("done", "--task", "a")
        self.plan("next")
        code, out, _ = self.plan("fail", "--task", "b", "--reason", "依赖装不上")
        self.assertEqual((code, out["status"]), (1, "pending"), "记了失败就交还待办，不算会话中断")
        code, out, _ = self.plan("fail", "--task", "b", "--reason", "还是装不上")
        self.assertEqual((out["status"], out["stop_reason"]), ("failed", "blocked"))
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["blocked"]), (1, ["c"]))
        self.assertEqual(self.plan("retry", "--task", "b", "--note", "换了镜像")[0], 0)
        self.plan("next")
        code, out, _ = self.plan("fail", "--task", "b", "--reason", "第三次")
        self.assertEqual(out["consecutive_failures"], 3)
        self.assertEqual(self.plan("next")[1]["stop_reason"], "too many failures")
        self.assertEqual(self.plan("restart", "--note", "人看过了")[0], 0)
        self.assertEqual(self.plan("next")[1]["decision"], "continue")

    def test_manual_stop_and_cycle(self):
        self.init("--cycle-hours", "1000", mode="auto")
        self.assertEqual(self.plan("stop", "--reason", "先暂停")[0], 0)
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["stop_reason"]), (1, "stopped"))
        self.plan("restart")
        self.assertEqual(self.plan("next")[0], 0)

    def test_tamper_detected(self):
        self.init(mode="auto")
        path = os.path.join(self.home, "state.json")
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state["tasks"]["a"]["status"] = "done"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["stop_reason"]), (2, "plan tampered"))
        self.assertEqual(self.plan("done", "--task", "b")[0], 2)
        self.assertEqual(self.plan("status")[0], 2)
        self.assertEqual(self.plan("prompt")[0], 2)
        self.assertEqual(self.plan("init", "--repo", self.repo, "--goal", "重建", "--mode", "auto",
                                   "--tasks", self.tasks, "--renew")[0], 0)
        self.assertEqual(self.plan("next")[0], 0)

    def test_auto_mode_assumptions_and_prompt(self):
        self.init("--assume", "默认用 UTF-8", "--delay-minutes", "2", mode="auto")
        self.assertEqual(self.plan("assume", "--text", "日志目录用 logs/", "--task", "a")[0], 0)
        out_file = os.path.join(self.root, "next.md")
        code, out, _ = self.plan("prompt", "--out", out_file)
        self.assertEqual((code, out["decision"], out["schedule"]["delay_seconds"]), (0, "continue", 120))
        with open(out_file, encoding="utf-8") as f:
            text = f.read()
        for needle in ("plan next", "plan done", "plan prompt", "plan assume", "日志目录用 logs/", self.home):
            self.assertIn(needle, text)
        code, out, _ = self.plan("report")
        self.assertEqual(code, 0)
        with open(out["plan_html"], encoding="utf-8") as f:
            page = f.read()
        self.assertIn("默认用 UTF-8", page)
        with open(os.path.join(self.home, "plan-log.jsonl"), encoding="utf-8") as f:
            events = [json.loads(x)["event"] for x in f]
        self.assertEqual(events[:2], ["init", "assume"])

    def test_add_and_run_backed_task(self):
        self.init(mode="auto")
        code, out, err = self.plan("add", "--id", "r", "--title", "调研", "--scenario", "research",
                                   "--depends", "a")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["run"], ".evloop/runs/r")
        self.assertEqual(self.plan("add", "--id", "r", "--title", "重复", "--check", "true")[0], 3)
        self.touch("a.txt")
        self.plan("next")
        self.plan("done", "--task", "a")
        nxt = self.plan("next")[1]
        self.assertEqual(nxt["task"]["id"], "b")
        code, out, _ = self.plan("done", "--task", "r")
        self.assertEqual(code, 1)
        self.assertIn("契约", out["reason"])

    def test_abandoned_session_counts_as_failure(self):
        self.init(mode="auto")
        self.assertEqual(self.plan("next")[1]["task"]["id"], "a")
        # 上一会话既没有 done 也没有 fail 就结束了
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["task"]["id"], out["attempts_used"]), (0, "a", 1))
        self.assertIn("没有记录 done 或 fail", out["last_reason"])
        self.plan("next")
        code, out, _ = self.plan("next")
        self.assertEqual((code, out["stop_reason"]), (1, "too many failures"), "崩溃的会话不能无限重来")
        with open(os.path.join(self.home, "plan-log.jsonl"), encoding="utf-8") as f:
            events = [json.loads(x)["event"] for x in f]
        self.assertEqual(events.count("abandoned"), 3)
        code, out, _ = self.plan("status")
        self.assertEqual(out["tasks"][0]["status"], "failed")

    def test_prompt_carries_last_failure_and_doctor(self):
        self.init(mode="auto")
        self.plan("next")
        self.plan("fail", "--task", "a", "--reason", "磁盘满了")
        code, out, _ = self.plan("prompt")
        self.assertEqual(code, 0)
        self.assertIn("磁盘满了", out["prompt"])
        self.assertIn("已失败 1/3", out["prompt"])
        r = sh(self.repo, sys.executable, helpers.JUDGE, "--home", self.home, "doctor")
        names = {c["name"]: c["ok"] for c in json.loads(r.stdout)["checks"]}
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(names["plan"] and names["plan_state"] and names["plan_stop"])
        path = os.path.join(self.home, "state.json")
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state["sessions"] = 99
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        r = sh(self.repo, sys.executable, helpers.JUDGE, "--home", self.home, "doctor")
        self.assertEqual(r.returncode, 1)
        self.assertFalse({c["name"]: c["ok"] for c in json.loads(r.stdout)["checks"]}["plan"])

    def test_home_must_be_under_plans(self):
        code, _, err = self.plan("init", "--repo", self.repo, "--goal", "x",
                                 home=os.path.join(self.repo, ".evloop", "runs", "x"))
        self.assertEqual(code, 3, err)
        self.assertEqual(self.plan("status")[0], 3, "计划不存在")


if __name__ == "__main__":
    unittest.main()
