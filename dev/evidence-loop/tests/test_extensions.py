"""1.1 新增能力：接手简报、紧凑输出、失败摘要、多种预算、快速预检、红绿检查、
逐元素验收、次要指标与简化规则、并行候选裁决、技能评测。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers
from helpers import ENV, Harness, git, write
from evloop import evals

EVAL_CLI = os.path.join(helpers.SCRIPTS, "evloop_eval.py")
SKILL = helpers.SKILL

LOUD_TEST = ("import sys; sys.path.insert(0, 'src'); import impl\n"
             "print('running add')\n"
             "if impl.add(2, 2) != 4:\n"
             "    print('AssertionError: add(2, 2) != 4')\n"
             "    raise SystemExit(1)\n")
FIX = {"src/impl.py": "def add(a, b):\n    return a + b\n"}
STILL_BROKEN = {"src/impl.py": "def add(a, b):\n    return a * 3\n"}


class BugfixBase(Harness):
    scenario = "bugfix"

    def seed(self):
        write(self.repo, "src/impl.py", "def add(a, b):\n    return a - b\n")
        write(self.repo, "tests/t.py", LOUD_TEST)

    def ready(self, *extra, test_cmd="python3 tests/t.py"):
        r = self.init(*extra, frozen="tests", test_cmd=test_cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()


class OutputTests(BugfixBase):
    def test_failure_summary_tail_and_diff(self):
        self.ready()
        code, rec = self.attempt(STILL_BROKEN)
        self.assertEqual((code, rec["verdict"]), (1, "failing"))
        self.assertIn("AssertionError: add(2, 2) != 4", rec["failure"])
        self.assertEqual(rec["tail"][-1], "AssertionError: add(2, 2) != 4")
        self.assertEqual(rec["diff"], {"added": 1, "deleted": 1})
        logged = self.records()[-1]
        self.assertIn("failure", logged)
        self.assertNotIn("tail", logged)  # tail 只给当下的智能体看，不进记录

    def test_tail_can_be_disabled_and_success_has_no_failure(self):
        self.ready()
        _, rec = self.attempt(STILL_BROKEN, "--tail", "0")
        self.assertNotIn("tail", rec)
        _, rec = self.attempt(FIX)
        self.assertEqual(rec["verdict"], "accepted")
        self.assertNotIn("failure", rec)
        self.assertNotIn("tail", rec)

    def test_negative_tail_and_tokens_are_refused(self):
        self.ready()
        self.commit(FIX)
        for flag in ("--tail", "--tokens"):
            r = self.run_j("attempt", flag, "-1")
            self.assertEqual(r.returncode, 3, flag)

    def test_brief_prints_one_line(self):
        self.ready()
        r = self.run_j("--brief", "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().count("\n"), 0)
        self.assertEqual(json.loads(r.stdout)["scenario"], "bugfix")

    def test_stderr_carries_code_name(self):
        r = self.init(frozen="tests", test_cmd=None)
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stderr.startswith("evloop: precondition: "), r.stderr)

    def test_resume_is_a_compact_brief(self):
        self.ready()
        self.attempt(STILL_BROKEN, note="乘以三")
        r = self.run_j("resume", "--last", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().count("\n"), 0)
        brief = json.loads(r.stdout)
        self.assertEqual(brief["contract"]["scenario"], "bugfix")
        self.assertEqual(brief["contract"]["frozen"], ["tests"])
        self.assertEqual(brief["best"], self.head()[:12])
        self.assertEqual(brief["recent"][-1]["verdict"], "failing")
        self.assertEqual(brief["recent"][-1]["note"], "乘以三")
        self.assertLessEqual(len(brief["recent"][-1]["failure"]), 2)
        self.assertEqual(brief["decision"], "continue")
        self.assertTrue(brief["next"])
        self.assertNotIn("warnings", brief)

    def test_resume_warns_about_unjudged_head(self):
        self.ready()
        self.commit(FIX)
        brief = json.loads(self.run_j("resume").stdout)
        self.assertIn("worktree_dirty_or_unjudged", brief["warnings"])


class BudgetTests(BugfixBase):
    def test_attempt_budget(self):
        self.ready("--max-attempts", "2")
        self.attempt(STILL_BROKEN)
        s = self.status()
        self.assertEqual((s["attempts_remaining"], s["decision"]), (1, "continue"))
        self.attempt({"src/impl.py": "def add(a, b):\n    return 0\n"})
        s = self.status()
        self.assertEqual(s["attempts_remaining"], 0)
        self.assertEqual((s["stop_reason"], s["decision"]), ("attempt budget exhausted", "handoff"))
        best = self.head()
        code, _ = self.attempt(FIX)
        self.assertEqual(code, 3)
        self.assertEqual(self.head(), best)  # 超预算的提交被回滚
        self.assertEqual(self.records()[-1]["verdict"], "invalid")

    def test_token_budget(self):
        self.ready("--token-budget", "100")
        self.attempt(STILL_BROKEN, "--tokens", "60")
        self.assertEqual(self.status()["tokens_remaining"], 40)
        self.attempt({"src/impl.py": "def add(a, b):\n    return 1\n"}, "--tokens", "50")
        s = self.status()
        self.assertEqual((s["tokens_used"], s["stop_reason"]), (110, "token budget exhausted"))

    def test_budget_flags_must_be_positive(self):
        for flag in ("--max-attempts", "--token-budget"):
            r = self.init(flag, "0", frozen="tests", test_cmd="python3 tests/t.py")
            self.assertEqual(r.returncode, 3, flag)

    def test_goal_reached_wins_over_budget(self):
        self.ready("--max-attempts", "1")
        self.attempt(FIX)
        self.assertEqual(self.status()["stop_reason"], "goal reached")


class RedGreenTests(BugfixBase):
    def test_verify_proves_baseline_is_red(self):
        self.ready()
        self.attempt(FIX)
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout)
        self.assertIs(rec["baseline_red"], True)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "raw", "verify.baseline.log")))
        self.assertEqual(git(self.repo, "worktree", "list").count("\n"), 1)  # 临时工作区已清理

    def test_test_that_passes_on_baseline_fails_verification(self):
        # 第一次运行失败、之后都通过的"假红"测试：基线 init 通过检查，但红绿检查必须识破
        counter = os.path.join(self.root, "seen")
        write(self.repo, "tests/flaky.py",
              "import os, sys\np = sys.argv[1]\nif os.path.exists(p):\n    raise SystemExit(0)\n"
              "open(p, 'w').close()\nraise SystemExit(1)\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "flaky")
        self.ready(test_cmd=f"python3 tests/flaky.py {counter}")
        _, rec = self.attempt(FIX)
        self.assertEqual(rec["verdict"], "accepted")
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 2)
        rec = json.loads(r.stdout)
        self.assertIs(rec["baseline_red"], False)
        self.assertEqual(rec["verdict"], "failed")
        self.assertIn("红绿", rec["reason"])


class FastCmdAndLawTests(Harness):
    def law(self, obj):
        write(self.repo, ".evloop/constitution.json", json.dumps(obj))

    def test_fast_cmd_failure_is_invalid_before_benchmark(self):
        self.ready("--fast-cmd", "test ! -e src/bad")
        base = self.head()
        code, rec = self.attempt({"src/impl.py": "N=100\n", "src/bad": "x"})
        self.assertEqual((code, rec["verdict"], rec["stage"]), (2, "invalid", "fast"))
        self.assertNotIn("score", rec)  # 完整基准根本没跑
        self.assertEqual(self.head(), base)

    def test_fast_cmd_must_pass_on_baseline(self):
        r = self.init("--fast-cmd", "false")
        self.assertEqual(r.returncode, 3)
        self.assertIn("快速预检", r.stderr)

    def test_constitution_supplies_fast_cmd_and_budgets(self):
        self.law({"fast_cmd": "true", "budget": {"max_attempts": 3, "token_budget": 1000}})
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.contract()
        self.assertEqual((c["fast_cmd"], c["max_attempts"], c["token_budget"]), ("true", 3, 1000))

    def test_command_line_overrides_constitution(self):
        self.law({"budget": {"max_attempts": 3}})
        r = self.init("--max-attempts", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.contract()["max_attempts"], 7)

    def test_bad_new_constitution_keys_die(self):
        for law in ({"fast_cmd": ""}, {"budget": {"max_attempts": 1.5}}, {"budget": {"token_budget": 0}}):
            self.law(law)
            r = self.init()
            self.assertEqual(r.returncode, 3, law)


BENCH2 = ('import sys; sys.path.insert(0, "src"); import impl\n'
          'print("latency=" + str(impl.N)); print("mem=" + str(impl.M))\n')
SECONDARY = ["--secondary-regex", r"mem=([0-9.]+)", "--secondary-direction", "lower"]


class SimplicityTests(Harness):
    def seed(self):
        write(self.repo, "src/impl.py", "N=200\nM=10\n# a\n# b\n# c\n")
        write(self.repo, "bench/run.py", BENCH2)

    def test_simpler_tie_is_accepted_without_moving_best(self):
        self.ready(*SECONDARY, "--prefer-simpler")
        code, rec = self.attempt({"src/impl.py": "N=195\nM=10\n"})
        self.assertEqual((code, rec["verdict"]), (0, "accepted"))
        self.assertTrue(rec["simplified"])
        self.assertEqual(rec["secondary"], 10)
        c = self.contract()
        self.assertEqual((c["best"], c["best_score"]), (self.head(), 200))

    def test_simpler_tie_that_worsens_secondary_is_rejected(self):
        self.ready(*SECONDARY, "--prefer-simpler")
        code, rec = self.attempt({"src/impl.py": "N=195\nM=20\n"})
        self.assertEqual((code, rec["verdict"]), (1, "rejected"))

    def test_tie_without_deletion_is_rejected(self):
        self.ready(*SECONDARY, "--prefer-simpler")
        code, _ = self.attempt({"src/impl.py": "N=195\nM=10\n# a\n# b\n# c\n# d\n"})
        self.assertEqual(code, 1)

    def test_tie_is_rejected_without_prefer_simpler(self):
        self.ready(*SECONDARY)
        code, _ = self.attempt({"src/impl.py": "N=195\nM=10\n"})
        self.assertEqual(code, 1)

    def test_missing_secondary_is_invalid(self):
        self.ready(*SECONDARY)
        code, rec = self.attempt({"src/impl.py": "N=100\nM='x'\n"})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))

    def test_improvement_updates_best_secondary(self):
        self.ready(*SECONDARY)
        self.attempt({"src/impl.py": "N=100\nM=8\n"})
        self.assertEqual(self.status()["best_secondary"], 8)

    def test_secondary_flags_validation(self):
        r = self.init("--secondary-regex", "mem=(\\d+)")
        self.assertEqual(r.returncode, 3)
        r = self.init(scenario="bugfix", frozen="bench", test_cmd="false")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.init("--prefer-simpler", "--renew", scenario="bugfix", frozen="bench", test_cmd="false")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--prefer-simpler", r.stderr)


class CandidateTests(Harness):
    def candidate(self, files, start="evloop/task", name="cand"):
        git(self.wt, "checkout", "-q", "-b", name, start)
        sha = self.commit(files)
        git(self.wt, "checkout", "-q", "evloop/task")
        return sha

    def test_commit_flag_judges_a_side_candidate(self):
        self.ready()
        sha = self.candidate({"src/impl.py": "N=100\n"})
        code, rec = self.attempt(None, "--commit", "cand")
        self.assertEqual((code, rec["verdict"], rec["commit"]), (0, "accepted", sha))
        self.assertEqual(self.head(), sha)
        self.assertEqual(git(self.wt, "rev-parse", "evloop/task"), sha)

    def test_rejected_candidate_rolls_back(self):
        self.ready()
        base = self.head()
        self.candidate({"src/impl.py": "N=300\n"})
        code, _ = self.attempt(None, "--commit", "cand")
        self.assertEqual(code, 1)
        self.assertEqual(self.head(), base)

    def test_stale_candidate_is_refused(self):
        self.ready()
        base = self.head()
        self.candidate({"src/impl.py": "N=100\n"}, name="good")
        self.attempt(None, "--commit", "good")
        self.candidate({"src/impl.py": "N=90\n"}, start=base, name="stale")
        r = self.run_j("attempt", "--route", "x", "--commit", "stale")
        self.assertEqual(r.returncode, 3)
        self.assertIn("不是基于当前最优", r.stderr)

    def test_commit_flag_requires_head_at_best(self):
        self.ready()
        self.candidate({"src/impl.py": "N=100\n"})
        self.commit({"src/impl.py": "N=120\n"})
        r = self.run_j("attempt", "--route", "x", "--commit", "cand")
        self.assertEqual(r.returncode, 3)
        self.assertIn("HEAD", r.stderr)

    def test_unknown_commit_is_refused(self):
        self.ready()
        r = self.run_j("attempt", "--route", "x", "--commit", "no-such-ref")
        self.assertEqual(r.returncode, 3)


ACCEPT_BP = {"meta": {"title": "目标"},
             "nodes": [{"id": "store", "label": "存储", "accept": "test -e src/store.py"},
                       {"id": "api", "label": "API", "accept": "test -e src/api.py"},
                       {"id": "cli", "label": "命令行"}],
             "edges": [{"from": "cli", "to": "api"}, {"from": "api", "to": "store"}],
             "depends": {"api": ["store"], "cli": ["api"]}}


class AcceptTests(Harness):
    scenario = "development"

    def seed(self):
        write(self.repo, "src/app.py", "x = 1\n")
        write(self.repo, "design/blueprint.json", json.dumps(ACCEPT_BP, ensure_ascii=False))
        write(self.repo, "design/asis.json", json.dumps({"nodes": [{"id": "x", "label": "旧"}]}))

    def dev_ready(self):
        r = self.init("--blueprint", "design/blueprint.json", "--asis", "design/asis.json",
                      "--asbuilt", "src/asbuilt.json", "--check-cmd", "true", frozen=None, test_cmd=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()

    def test_contract_records_accept_commands(self):
        self.dev_ready()
        self.assertEqual(self.contract()["accept"],
                         {"store": "test -e src/store.py", "api": "test -e src/api.py"})

    def test_failed_accept_keeps_element_pending_until_it_passes(self):
        self.dev_ready()
        code, rec = self.attempt({"src/store.py": "s\n"}, "--elements", "store")
        self.assertEqual((code, rec["verdict"]), (0, "green"))
        self.assertEqual(rec["accept"]["store"]["exit"], 0)
        code, rec = self.attempt({"src/other.py": "o\n"}, "--elements", "api")
        self.assertEqual((code, rec["verdict"], rec["accept_failed"]), (1, "failing", ["api"]))
        s = self.status()
        self.assertEqual((s["elements_done"], s["elements_pending"]), (["store"], ["api"]))
        code, rec = self.attempt({"src/api.py": "a\n"})
        self.assertEqual((code, rec["verdict"]), (0, "green"))
        self.assertIn("api", rec["accept"])  # 待定元素的验收命令被自动重跑
        self.assertEqual(self.status()["elements_done"], ["store", "api"])

    def test_verify_reruns_every_accept_command(self):
        self.dev_ready()
        self.attempt({"src/store.py": "s\n", "src/api.py": "a\n"}, "--elements", "store", "api")
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(json.loads(r.stdout)["accept"]), ["api", "store"])


class EvalTests(BugfixBase):
    def test_grade_a_real_run(self):
        self.ready()
        self.attempt(STILL_BROKEN)
        self.attempt(FIX)
        self.run_j("verify")
        self.run_j("report")
        checks = [{"kind": "contract"}, {"kind": "scenario", "equals": "bugfix"},
                  {"kind": "attempts_min", "value": 2}, {"kind": "verdict", "equals": "accepted"},
                  {"kind": "no_verdict", "equals": "invalid"}, {"kind": "verified"},
                  {"kind": "report"}, {"kind": "not_approved"},
                  {"kind": "approved", "text": "已批准"}, {"kind": "elements_done"}]
        out = evals.grade(self.home, checks)
        passed = {r["text"]: r["passed"] for r in out["assertion_results"]}
        self.assertFalse(passed["已批准"])
        self.assertEqual(out["summary"]["total"], 10)
        self.assertEqual(out["summary"]["passed"], 8)  # approved 与 elements_done 不通过
        self.assertEqual(out["summary"]["pass_rate"], 0.8)

    def test_grade_missing_run_fails_every_check(self):
        out = evals.grade(os.path.join(self.root, "nope"), [{"kind": "contract"}, {"kind": "verified"}])
        self.assertEqual(out["summary"], {"passed": 0, "failed": 2, "total": 2, "pass_rate": 0.0})

    def test_grade_cli_writes_grading_json(self):
        self.ready()
        self.attempt(FIX)
        spec = os.path.join(self.root, "evals.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"skill_name": "evidence-loop", "evals": [
                {"id": 7, "prompt": "修复", "expected_output": "通过",
                 "checks": [{"kind": "verdict", "equals": "accepted"}]}]}, f)
        out = os.path.join(self.root, "grading.json")
        r = subprocess.run([sys.executable, EVAL_CLI, "grade", spec, "--eval-id", "7", "--run", self.home,
                            "--out", out], capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["summary"]["passed"], 1)


class EvalFormatTests(unittest.TestCase):
    def test_validate(self):
        good = {"skill_name": "s", "evals": [{"id": 1, "prompt": "p", "expected_output": "e",
                                              "assertions": ["a"], "checks": [{"kind": "verified"}]}]}
        self.assertEqual(evals.validate(good, "s"), [])
        bad = {"skill_name": "x", "evals": [{"id": 1, "prompt": "", "expected_output": "e",
                                             "checks": [{"kind": "magic"}]},
                                            {"id": 1, "prompt": "p", "expected_output": "e",
                                             "assertions": [3]}]}
        problems = " ".join(evals.validate(bad, "s"))
        for word in ("skill_name", "prompt", "kind", "重复", "assertions"):
            self.assertIn(word, problems)
        self.assertTrue(evals.validate({"evals": []}))

    def test_shipped_evals_are_valid(self):
        path = os.path.join(helpers.EVALS_DIR, "evals.json")
        r = subprocess.run([sys.executable, EVAL_CLI, "validate", path, "--skill-name", "evidence-loop"],
                           capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(json.loads(r.stdout)["evals"], 6)

    def test_benchmark(self):
        with tempfile.TemporaryDirectory() as d:
            def put(case, config, rate, tokens, ms):
                base = os.path.join(d, case, config)
                os.makedirs(base)
                with open(os.path.join(base, "grading.json"), "w") as f:
                    json.dump({"summary": {"pass_rate": rate}}, f)
                with open(os.path.join(base, "timing.json"), "w") as f:
                    json.dump({"total_tokens": tokens, "duration_ms": ms}, f)
            put("eval-1", "with_skill", 1.0, 1000, 10000)
            put("eval-2", "with_skill", 0.5, 3000, 30000)
            put("eval-1", "without_skill", 0.25, 500, 5000)
            out = evals.benchmark(d)["run_summary"]
        self.assertEqual(out["with_skill"]["pass_rate"], {"mean": 0.75, "stddev": 0.25, "n": 2})
        self.assertEqual(out["with_skill"]["time_seconds"]["mean"], 20.0)
        self.assertEqual(out["delta"], {"pass_rate": 0.5, "tokens": 1500.0, "time_seconds": 15.0})


if __name__ == "__main__":
    unittest.main()
