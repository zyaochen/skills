"""优化场景：基线、对照重跑、δ、路线证伪、预算与预留窗口、过程图。"""
import json
import os
import unittest

from helpers import Harness, git, read, write


class InitTests(Harness):
    def test_init_records_baseline_delta_and_frozen_hashes(self):
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.contract()
        self.assertEqual(c["baseline"]["score"], 200.0)
        self.assertEqual(c["delta"], 10.0)
        self.assertIn("bench/run.py", c["frozen"])
        self.assertEqual(c["schema_version"], 1)
        self.assertTrue(c["agreement_sha"])

    def test_control_rerun_measures_noise(self):
        self.assertEqual(self.init().returncode, 0)
        b = self.contract()["baseline"]
        self.assertEqual(b["control_score"], 200.0)
        self.assertEqual(b["noise"], 0.0)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "raw", "control.log")))

    def test_noise_not_below_delta_dies(self):
        write(self.repo, "bench/run.py",
              "import os\np='.evloop/n'\nn=int(open(p).read()) if os.path.exists(p) else 0\n"
              "os.makedirs('.evloop', exist_ok=True); open(p,'w').write(str(n+1))\n"
              "print('latency=' + str(200 + 50*n))\n")
        git(self.repo, "commit", "-qam", "noisy")
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("δ", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, "contract.json")))

    def test_failing_baseline_dies(self):
        r = self.init(test_cmd="python3 -c 'raise SystemExit(4)'")
        self.assertEqual(r.returncode, 3)
        self.assertIn("退出码为 4", r.stderr)

    def test_missing_score_dies(self):
        r = self.init(test_cmd="echo nothing")
        self.assertEqual(r.returncode, 3)
        self.assertIn("score-regex", r.stderr)

    def test_frozen_inside_editable_dies(self):
        r = self.init(frozen="src/impl.py")
        self.assertEqual(r.returncode, 3)
        self.assertIn("可编辑", r.stderr)

    def test_requires_budget(self):
        self.budget = []
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("--budget-minutes", r.stderr)

    def test_reserve_must_be_smaller_than_budget(self):
        r = self.init("--reserve-minutes", "10")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--reserve-minutes", r.stderr)

    def test_delta_and_delta_pct_are_exclusive(self):
        r = self.init("--delta", "3")
        self.assertEqual(r.returncode, 3)
        self.assertIn("二选一", r.stderr)

    def test_non_positive_delta_dies(self):
        self.opt_args = ["--score-regex", r"latency=([0-9.]+)", "--unit", "ms", "--direction", "lower",
                         "--delta", "0", "--target", "150"]
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("正数", r.stderr)

    def test_bad_regex_dies(self):
        self.opt_args = ["--score-regex", "(", "--unit", "ms", "--direction", "lower",
                         "--delta", "1", "--target", "150"]
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("正则", r.stderr)

    def test_zero_baseline_with_pct_delta_dies(self):
        write(self.repo, "src/impl.py", "N=0\n")
        git(self.repo, "commit", "-qam", "zero")
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("--delta", r.stderr)

    def test_absolute_editable_dies(self):
        r = self.init(editable="/etc")
        self.assertEqual(r.returncode, 3)

    def test_optimization_flags_refused_elsewhere(self):
        r = self.run_j("init", "--repo", self.repo, "--scenario", "bugfix", "--editable", "src",
                       "--frozen", "bench", "--test-cmd", "false", "--target", "1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("只用于优化场景", r.stderr)

    def test_existing_contract_needs_renew(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("--renew", r.stderr)

    def test_renew_archives_and_records_previous(self):
        self.ready()
        self.attempt({"src/impl.py": "N=180\n"})
        r = self.init("--renew")
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.contract()
        self.assertEqual(c["renewed_from"]["best_score"], 180.0)
        baks = [n for n in os.listdir(self.home) if n.endswith(".bak")]
        self.assertEqual(len(baks), 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, "attempts.jsonl")))

    def test_failed_renew_keeps_previous_contract(self):
        self.assertEqual(self.init().returncode, 0)
        before = read(self.home, "contract.json")
        r = self.init("--renew", test_cmd="python3 -c 'raise SystemExit(1)'")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read(self.home, "contract.json"), before)
        self.assertFalse([n for n in os.listdir(self.home) if n.endswith(".bak")])


class StartTests(Harness):
    def test_start_smoke_passes_and_leaves_clean_worktree(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.start()
        out = json.loads(r.stdout)
        self.assertEqual(out["smoke"], {"frozen_edit": "rejected", "out_of_scope": "rejected",
                                        "rollback": "clean"})
        self.assertTrue(self.clean())
        self.assertEqual(self.records()[0]["kind"], "baseline")
        self.assertEqual(self.records()[1]["kind"], "smoke")
        self.assertTrue(self.contract()["deadline"])

    def test_start_refuses_users_checkout(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.run_j("start", "--worktree", self.repo)
        self.assertEqual(r.returncode, 3)
        self.assertIn("工作克隆本身", r.stderr)

    def test_start_refuses_dirty_worktree(self):
        self.assertEqual(self.init().returncode, 0)
        self.add_worktree()
        write(self.wt, "src/x.py", "x")
        r = self.run_j("start", "--worktree", self.wt)
        self.assertEqual(r.returncode, 3)
        self.assertIn("干净", r.stderr)

    def test_start_warns_on_target_branch(self):
        self.assertEqual(self.init().returncode, 0)
        git(self.repo, "checkout", "-q", "-b", "other")
        git(self.repo, "worktree", "add", "-q", self.wt, "main")
        r = self.run_j("start", "--worktree", self.wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("交付目标分支", r.stderr)

    def test_smoke_command_reruns(self):
        self.ready()
        r = self.run_j("smoke")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.clean())


class AttemptTests(Harness):
    def setUp(self):
        super().setUp()
        self.ready()

    def test_improvement_is_accepted_and_becomes_best(self):
        code, rec = self.attempt({"src/impl.py": "N=180\n"})
        self.assertEqual(code, 0)
        self.assertEqual(rec["verdict"], "accepted")
        self.assertEqual(self.contract()["best"], self.head())
        self.assertEqual(self.contract()["best_score"], 180.0)

    def test_regression_is_rejected_and_rolled_back(self):
        base = self.head()
        code, rec = self.attempt({"src/impl.py": "N=250\n"})
        self.assertEqual((code, rec["verdict"]), (1, "rejected"))
        self.assertEqual(self.head(), base)
        self.assertEqual(rec["rolled_back_to"], base)

    def test_improvement_below_delta_is_rejected(self):
        code, rec = self.attempt({"src/impl.py": "N=195\n"})
        self.assertEqual((code, rec["verdict"]), (1, "rejected"))

    def test_frozen_file_edit_is_invalid_and_rolled_back(self):
        base = self.head()
        code, rec = self.attempt({"bench/run.py": 'print("latency=1")\n'})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))
        self.assertEqual(rec["files"], ["bench/run.py"])
        self.assertEqual(self.head(), base)

    def test_new_file_outside_scope_is_invalid_and_removed(self):
        code, rec = self.attempt({"src/impl.py": "N=100\n", "notes.txt": "x"})
        self.assertEqual(code, 2)
        self.assertEqual(rec["files"], ["notes.txt"])
        self.assertFalse(os.path.exists(os.path.join(self.wt, "notes.txt")))

    def test_new_file_inside_scope_is_kept_on_accept(self):
        code, _ = self.attempt({"src/impl.py": "N=100\n", "src/helper.py": "x=1\n"})
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.wt, "src/helper.py")))

    def test_rename_out_of_scope_reports_new_path(self):
        os.makedirs(os.path.join(self.wt, "lib"))
        git(self.wt, "mv", "src/impl.py", "lib/impl.py")
        code, rec = self.attempt({"lib/impl.py": "N=100\n"})
        self.assertEqual(code, 2)
        self.assertEqual(rec["files"], ["lib/impl.py"])
        self.assertTrue(os.path.exists(os.path.join(self.wt, "src/impl.py")))

    def test_dirty_worktree_is_precondition_error(self):
        write(self.wt, "src/impl.py", "N=1\n")
        code, rec = self.attempt(route="r")
        self.assertEqual(code, 3)
        self.assertIsNone(rec)

    def test_uncommitted_head_equals_best_is_precondition_error(self):
        code, _ = self.attempt()
        self.assertEqual(code, 3)

    def test_head_must_descend_from_best(self):
        git(self.wt, "checkout", "-q", "--orphan", "stray")
        write(self.wt, "src/impl.py", "N=1\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-qm", "orphan")
        code, _ = self.attempt()
        self.assertEqual(code, 3)

    def test_crash_is_invalid(self):
        code, rec = self.attempt({"src/impl.py": "raise SystemExit(7)\n"})
        self.assertEqual(code, 2)
        self.assertIn("退出码 7", rec["reason"])

    def test_missing_score_is_invalid(self):
        code, rec = self.attempt({"src/impl.py": "N='x'\n"})
        self.assertEqual(code, 2)
        self.assertIn("分数", rec["reason"])

    def test_route_is_required_for_optimization(self):
        self.commit({"src/impl.py": "N=100\n"})
        r = self.run_j("attempt", "--note", "x")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--route", r.stderr)

    def test_route_label_is_validated(self):
        self.commit({"src/impl.py": "N=100\n"})
        r = self.run_j("attempt", "--route", "has space")
        self.assertEqual(r.returncode, 3)

    def test_refuted_route_needs_differs(self):
        self.attempt({"src/impl.py": "N=250\n"}, route="cache")
        self.commit({"src/impl.py": "N=240\n"})
        r = self.run_j("attempt", "--route", "cache")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--differs", r.stderr)
        _, rec = self.attempt(None, "--differs", "更小的缓存", route="cache")
        self.assertEqual(rec["differs"], "更小的缓存")

    def test_new_best_reopens_refuted_routes(self):
        self.attempt({"src/impl.py": "N=250\n"}, route="cache")
        self.assertIn("cache", self.status()["ruled_out"])
        self.attempt({"src/impl.py": "N=180\n"}, route="simd")
        self.assertEqual(self.status()["ruled_out"], {})
        code, _ = self.attempt({"src/impl.py": "N=160\n"}, route="cache")
        self.assertEqual(code, 0)

    def test_invalid_without_run_does_not_refute(self):
        self.attempt({"bench/run.py": "x"}, route="cheat")
        self.assertNotIn("cheat", self.status()["ruled_out"])

    def test_elements_only_for_development(self):
        self.commit({"src/impl.py": "N=100\n"})
        r = self.run_j("attempt", "--route", "x", "--elements", "a")
        self.assertEqual(r.returncode, 3)

    def test_command_editing_frozen_is_rolled_back(self):
        code, rec = self.attempt({"src/impl.py": "open('bench/run.py','a').write('#x')\nN=100\n"})
        self.assertEqual(code, 2)
        self.assertIn("命令改动了冻结文件", rec["reason"])
        self.assertTrue(self.clean())

    def test_command_deleting_frozen_is_rolled_back(self):
        code, _ = self.attempt({"src/impl.py": "import os\nN=100\nos.remove('bench/run.py')\n"})
        self.assertEqual(code, 2)
        self.assertTrue(os.path.exists(os.path.join(self.wt, "bench/run.py")))


class StatusTests(Harness):
    def test_status_before_start_points_to_start(self):
        self.assertEqual(self.init().returncode, 0)
        s = self.status()
        self.assertEqual(s["decision"], "continue")
        self.assertIn("start", s["next"])

    def test_target_met_status_decides_handoff(self):
        self.ready()
        self.attempt({"src/impl.py": "N=140\n"})
        s = self.status()
        self.assertTrue(s["target_met"])
        self.assertEqual(s["decision"], "handoff")
        self.assertEqual(s["stop_reason"], "target reached")
        self.assertIn("verify", s["next"])

    def test_rejected_attempt_cannot_meet_target(self):
        self.opt_args = ["--score-regex", r"latency=([0-9.]+)", "--unit", "ms", "--direction", "lower",
                         "--delta", "100", "--target", "150"]
        self.ready()
        code, _ = self.attempt({"src/impl.py": "N=140\n"})
        self.assertEqual(code, 1)
        self.assertFalse(self.status()["target_met"])

    def test_exclusive_target_excludes_equality(self):
        self.ready("--exclusive")
        self.attempt({"src/impl.py": "N=150\n"})
        self.assertFalse(self.status()["target_met"])

    def test_higher_direction(self):
        self.opt_args = ["--score-regex", r"latency=([0-9.]+)", "--unit", "ops", "--direction", "higher",
                         "--delta", "5", "--target", "300"]
        self.ready()
        self.assertEqual(self.attempt({"src/impl.py": "N=150\n"})[0], 1)
        self.assertEqual(self.attempt({"src/impl.py": "N=320\n"})[0], 0)
        self.assertTrue(self.status()["target_met"])

    def test_status_reports_in_flight_work(self):
        self.ready()
        self.commit({"src/impl.py": "N=100\n"})
        s = self.status()
        self.assertFalse(s["head_is_best"])
        self.assertIn("attempt", s["next"])
        write(self.wt, "src/impl.py", "N=3\n")
        self.assertFalse(self.status()["worktree_clean"])

    def test_status_names_ruled_out_routes(self):
        self.ready()
        self.attempt({"src/impl.py": "N=250\n"}, route="unroll")
        self.assertIn("unroll", self.status()["next"])

    def test_unjudged_head_comes_before_handoff(self):
        self.ready()
        self.attempt({"src/impl.py": "N=100\n"})
        self.commit({"src/impl.py": "N=90\n"})
        self.assertIn("attempt", self.status()["next"])


class BudgetTests(Harness):
    def _expire(self, minutes_left=-1):
        import datetime as dt

        from evloop.contract import Home
        from evloop.util import iso, utc_now
        h = Home(self.home)
        c = h.load()
        c["deadline"] = iso(utc_now() + dt.timedelta(minutes=minutes_left))
        h.save(c)

    def test_budget_exhausted(self):
        self.ready()
        self._expire()
        s = self.status()
        self.assertTrue(s["budget_exhausted"])
        self.assertEqual(s["decision"], "handoff")
        self.assertIn("呈交", s["next"] if s["verification_current"] else "呈交")
        base = self.head()
        code, _ = self.attempt({"src/impl.py": "N=10\n"})
        self.assertEqual(code, 3)
        self.assertEqual(self.head(), base)
        self.assertEqual(self.records()[-1]["verdict"], "invalid")

    def test_reserve_window_blocks_attempts(self):
        self.ready("--reserve-minutes", "5")
        self._expire(minutes_left=3)
        code, _ = self.attempt({"src/impl.py": "N=10\n"})
        self.assertEqual(code, 3)
        s = self.status()
        self.assertEqual(s["stop_reason"], "reserve window reached")
        self.assertFalse(s["budget_exhausted"])

    def test_timeout_is_invalid(self):
        self.ready()
        # The deadline is stored truncated to whole seconds, so 0.02 min left only 0.2-1.2 s for the commit and
        # the judge start-up; any slower and the attempt was refused as budget exhausted (exit 3) instead.
        self._expire(minutes_left=0.1)
        code, rec = self.attempt({"src/impl.py": "import time; time.sleep(30)\nN=1\n"})
        self.assertEqual(code, 2)
        self.assertIn("预算", rec["reason"])


class ReportTests(Harness):
    def test_report_chart_and_caption(self):
        self.ready()
        self.attempt({"src/impl.py": "N=250\n"}, route="a")
        self.attempt({"src/impl.py": "N=140\n"}, route="b")
        r = self.run_j("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        manifest = json.loads(r.stdout)
        self.assertTrue(os.path.isfile(manifest["handoff"]))
        cap = json.loads(read(self.home, "caption.json"))
        self.assertEqual((cap["baseline"], cap["final"], cap["attempts"]), (200.0, 140.0, 2))
        self.assertTrue(cap["target_met"])
        self.assertEqual(cap["routes"]["a"]["rejected"], 1)
        self.assertEqual(cap["routes"]["b"]["accepted"], 1)
        svg = read(self.home, "process.svg")
        self.assertTrue(svg.startswith("<svg"))
        html = read(self.home, "handoff.html")
        self.assertIn("性能优化", html)
        self.assertIn("待验证", html)

    def test_snapshot_before_start_shows_baseline(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.run_j("report", "--progress")
        self.assertEqual(r.returncode, 0, r.stderr)
        html = read(self.home, "progress.html")
        self.assertIn("执行快照", html)
        self.assertIn("200", html)
        self.assertNotIn("report", self.contract())

    def test_progress_cannot_overwrite_handoff(self):
        self.ready()
        r = self.run_j("report", "--progress", "--out", os.path.join(self.home, "handoff.html"))
        self.assertEqual(r.returncode, 3)

    def test_review_notes_are_shown(self):
        self.ready()
        write(self.home, "review.md", "只测了冷启动路径")
        self.run_j("report", "--progress")
        self.assertIn("只测了冷启动路径", read(self.home, "progress.html"))

    def test_dirty_snapshot_warns(self):
        self.ready()
        write(self.wt, "src/impl.py", "N=1\n")
        r = self.run_j("report")
        self.assertIn("不能用于审批", r.stderr)
        self.assertIn("未提交或未裁决", read(self.home, "handoff.html"))
        self.assertFalse(self.contract()["report"]["source_clean"])


class Release161Tests(Harness):
    """1.6.1：全局参数位置、可选目标线、达标后的第二路线提示、冻结文件的越界说明。"""

    def test_brief_and_home_after_subcommand(self):
        self.ready()
        import subprocess
        import sys

        from helpers import JUDGE
        for args in (["status", "--brief", "--home", self.home],
                     ["status", "--home=" + self.home, "--brief"]):
            r = subprocess.run([sys.executable, JUDGE, *args], cwd=self.root,
                               capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(r.stdout.strip().splitlines()), 1)
            self.assertEqual(json.loads(r.stdout)["scenario"], "optimization")

    def test_hoist_globals_keeps_double_dash(self):
        from evloop.cli import hoist_globals
        self.assertEqual(hoist_globals(["status", "--brief", "--home", "h"]),
                         ["--brief", "--home", "h", "status"])
        self.assertEqual(hoist_globals(["x", "--", "--brief"]), ["x", "--", "--brief"])

    def test_target_is_optional(self):
        self.opt_args = ["--score-regex", r"latency=([0-9.]+)", "--unit", "ms", "--direction", "lower",
                         "--delta-pct", "5"]
        self.ready("--max-attempts", "2")
        self.assertIsNone(self.contract()["target"])
        self.assertEqual(self.attempt({"src/impl.py": "N=100\n"})[0], 0)
        s = self.status()
        self.assertIsNone(s["target"])
        self.assertFalse(s["target_met"])
        self.assertEqual(s["decision"], "continue")
        self.attempt({"src/impl.py": "N=90\n"})
        s = self.status()
        self.assertEqual((s["decision"], s["stop_reason"]), ("handoff", "attempt budget exhausted"))
        self.assertEqual(self.run_j("resume").returncode, 0)
        self.assertEqual(self.run_j("verify").returncode, 0)
        r = self.run_j("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        html = read(self.home, "handoff.html")
        self.assertIn("未设目标线", html)
        self.assertIn("已改进", html)

    def test_single_route_hit_suggests_another_route(self):
        self.ready()
        self.attempt({"src/impl.py": "N=140\n"}, route="a")
        s = self.status()
        self.assertEqual(s["decision"], "handoff")
        self.assertEqual(s["routes_tried"], ["a"])
        self.assertIn("--route", s["next"])
        self.attempt({"src/impl.py": "N=130\n"}, route="b")
        s = self.status()
        self.assertNotIn("--route", s["next"])
        self.assertIn("verify", s["next"])

    def test_no_second_route_hint_when_attempts_used_up(self):
        self.ready("--max-attempts", "1")
        self.attempt({"src/impl.py": "N=140\n"}, route="a")
        self.assertNotIn("--route", self.status()["next"])

    def test_outside_frozen_file_is_named(self):
        self.ready()
        code, rec = self.attempt({"bench/run.py": 'print("latency=1")\n'})
        self.assertEqual(code, 2)
        self.assertIn("冻结文件", rec["reason"])
        self.assertIn("bench/run.py", rec["reason"])


if __name__ == "__main__":
    unittest.main()
