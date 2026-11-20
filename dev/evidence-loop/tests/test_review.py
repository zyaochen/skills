"""评审闸门、宪法、生成路径、契约封存、迁移、体检与健壮性。"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import ENV, JUDGE, Harness, git, read, write


class ReviewGateTests(Harness):
    def reach_target(self):
        self.ready()
        self.attempt({"src/impl.py": "N=140\n"})

    def test_approve_before_start_dies(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.run_j("approve")
        self.assertEqual(r.returncode, 3)

    def test_handoff_waits_for_approval(self):
        self.reach_target()
        self.assertEqual(self.run_j("verify").returncode, 0)
        self.assertIn("report", self.status()["next"])
        self.assertEqual(self.run_j("report").returncode, 0)
        s = self.status()
        self.assertIn("approve", s["next"])
        self.assertIn("审阅这份评审包", read(self.home, "handoff.html"))
        self.assertEqual(self.run_j("approve", "--note", "看过").returncode, 0)
        s = self.status()
        self.assertEqual(s["approved"]["note"], "看过")
        self.assertIn("合并回 main", s["next"])

    def test_approval_requires_verification_and_report(self):
        self.reach_target()
        r = self.run_j("approve")
        self.assertEqual(r.returncode, 3)
        self.assertIn("verify", r.stderr)
        self.run_j("verify")
        r = self.run_j("approve")
        self.assertEqual(r.returncode, 3)
        self.assertIn("report", r.stderr)

    def test_new_attempt_stales_approval(self):
        self.reach_target()
        self.review()
        self.attempt({"src/impl.py": "N=100\n"})
        s = self.status()
        self.assertIsNone(s["approved"])
        self.assertFalse(s["verification_current"])

    def test_changed_report_invalidates_approval(self):
        self.reach_target()
        self.review()
        with open(os.path.join(self.home, "handoff.html"), "a", encoding="utf-8") as f:
            f.write("<!-- edited -->")
        s = self.status()
        self.assertFalse(s["report_current"])
        self.assertIsNone(s["approved"])

    def test_new_verification_requires_new_report_and_approval(self):
        self.reach_target()
        self.review()
        self.assertEqual(self.run_j("verify").returncode, 0)
        s = self.status()
        self.assertFalse(s["report_current"])
        self.assertIsNone(s["approved"])

    def test_progress_preserves_approved_handoff(self):
        self.reach_target()
        self.review()
        before = read(self.home, "process.svg")
        self.assertEqual(self.run_j("report", "--progress").returncode, 0)
        self.assertTrue(self.status()["approved"])
        self.assertEqual(read(self.home, "process.svg"), before)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "progress-process.svg")))

    def test_regenerated_handoff_requests_new_approval(self):
        self.reach_target()
        self.review()
        self.run_j("report")
        self.assertIsNone(self.status()["approved"])

    def test_dirty_report_cannot_be_approved_after_cleanup(self):
        self.reach_target()
        self.run_j("verify")
        write(self.wt, "src/scratch.py", "x")
        self.run_j("report")
        os.remove(os.path.join(self.wt, "src/scratch.py"))
        r = self.run_j("approve")
        self.assertEqual(r.returncode, 3)

    def test_approval_refuses_unjudged_commit(self):
        self.reach_target()
        self.run_j("verify")
        self.run_j("report")
        self.commit({"src/impl.py": "N=1\n"})
        r = self.run_j("approve")
        self.assertEqual(r.returncode, 3)
        self.assertIn("HEAD", r.stderr)

    def test_verify_refuses_non_best_head(self):
        self.reach_target()
        self.commit({"src/impl.py": "N=1\n"})
        self.assertEqual(self.run_j("verify").returncode, 3)

    def test_verify_reproduces_score(self):
        self.reach_target()
        rec = self.json_out(self.run_j("verify"))
        self.assertEqual(rec["score"], 140.0)
        self.assertTrue(rec["score_reproduced"])
        self.assertEqual(rec["verdict"], "verified")

    def test_failed_rerun_revokes_approval(self):
        self.ready("--generated", "out")
        self.attempt({"src/impl.py": "import os\nos.makedirs('out', exist_ok=True)\n"
                                     "N = 300 if os.path.exists('out/x') else 140\nopen('out/x','w').close()\n"})
        self.assertTrue(self.status()["target_met"])
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 2)
        rec = json.loads(r.stdout)
        self.assertFalse(rec["score_reproduced"])
        s = self.status()
        self.assertFalse(s["verification_current"])
        self.assertIn("verify", s["next"])

    def test_verify_refuses_frozen_drift(self):
        self.reach_target()
        write(self.wt, "bench/run.py", "print('latency=1')\n")
        git(self.wt, "update-index", "--assume-unchanged", "bench/run.py")
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 3)
        self.assertIn("冻结", r.stderr)


class ConstitutionTests(Harness):
    def law(self, obj, commit=True):
        write(self.repo, ".evloop/constitution.json", json.dumps(obj))
        return obj

    def test_inherits_frozen_generated_guard_and_budget(self):
        write(self.repo, "golden/g.txt", "g")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "golden")
        self.law({"frozen": ["golden"], "generated": ["build"], "guard_cmd": "true",
                  "budget": {"default_minutes": 20, "reserve_minutes": 2, "max_minutes": 30}})
        self.budget = []
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.contract()
        self.assertIn("golden/g.txt", c["frozen"])
        self.assertEqual(c["generated"], ["build"])
        self.assertEqual(c["guard_cmd"], "true")
        self.assertEqual((c["budget_minutes"], c["reserve_minutes"]), (20, 2))
        self.assertEqual(c["constitution"]["path"], ".evloop/constitution.json")

    def test_constitution_frozen_satisfies_bugfix_requirement(self):
        self.law({"frozen": ["bench"]})
        r = self.run_j("init", "--repo", self.repo, "--scenario", "bugfix", "--editable", "src",
                       "--test-cmd", "false")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_budget_above_max_dies(self):
        self.law({"budget": {"max_minutes": 5}})
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("max_minutes", r.stderr)

    def test_unknown_key_dies(self):
        self.law({"frozn": ["x"]})
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("未知字段", r.stderr)

    def test_bad_types_die(self):
        for law in ({"frozen": "x"}, {"guard_cmd": 3}, {"budget": {"max_minutes": -1}}, []):
            self.law(law)
            r = self.init()
            self.assertEqual(r.returncode, 3, law)

    def test_explicit_missing_constitution_dies(self):
        r = self.init("--constitution", "nope.json")
        self.assertEqual(r.returncode, 3)
        self.assertIn("不存在", r.stderr)

    def test_broken_guard_at_baseline_dies(self):
        self.law({"guard_cmd": "false"})
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("底线", r.stderr)

    def test_guard_failure_is_invalid_and_rolled_back(self):
        self.law({"guard_cmd": "test ! -e src/bad"})
        self.ready()
        base = self.head()
        code, rec = self.attempt({"src/impl.py": "N=100\n", "src/bad": "x"})
        self.assertEqual(code, 2)
        self.assertIn("底线检查", rec["reason"])
        self.assertEqual(self.head(), base)
        code, rec = self.attempt({"src/impl.py": "N=100\n"})
        self.assertEqual(code, 0)

    def test_guard_editing_frozen_is_rejected_before_benchmark(self):
        self.law({"guard_cmd": "test ! -e src/hack || echo x >> bench/run.py"})
        self.ready()
        code, rec = self.attempt({"src/impl.py": "N=100\n", "src/hack": "1"})
        self.assertEqual(code, 2)
        self.assertIn("底线检查改动了冻结文件", rec["reason"])
        self.assertNotIn("score", rec)

    def test_verify_runs_guard(self):
        self.law({"guard_cmd": "true"})
        self.ready()
        self.attempt({"src/impl.py": "N=140\n"})
        rec = self.json_out(self.run_j("verify"))
        self.assertEqual(rec["guard_exit"], 0)

    def test_constitution_change_midloop_is_invalid(self):
        self.law({"generated": ["build"]})
        self.ready()
        self.law({"generated": ["build", "dist"]})
        code, rec = self.attempt({"src/impl.py": "N=100\n"})
        self.assertEqual(code, 2)
        self.assertIn("宪法", rec["reason"])
        self.assertEqual(self.run_j("verify").returncode, 3)
        self.assertTrue(self.status()["constitution_drift"])

    def test_generated_paths_are_not_dirty(self):
        self.ready("--generated", "out")
        code, rec = self.attempt({"src/impl.py": "import os\nos.makedirs('out', exist_ok=True)\n"
                                                 "open('out/r.txt','w').write('1')\nN=100\n"})
        self.assertEqual(code, 0, rec)
        self.assertTrue(self.status()["worktree_clean"])

    def test_undeclared_artifacts_block_with_hint(self):
        self.ready()
        self.commit({"src/impl.py": "N=100\n"})
        write(self.wt, "src/cache.bin", "x")
        r = self.run_j("attempt", "--route", "x")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--generated", r.stderr)

    def test_committed_generated_files_are_invalid(self):
        self.ready("--generated", "src/out")
        code, rec = self.attempt({"src/impl.py": "N=100\n", "src/out/r.txt": "1"})
        self.assertEqual(code, 2)
        self.assertIn("运行产物", rec["reason"])

    def test_generated_overlapping_frozen_dies(self):
        r = self.init("--generated", "bench/out")
        self.assertEqual(r.returncode, 3)
        self.assertIn("重叠", r.stderr)

    def test_baseline_side_effects_recorded(self):
        write(self.repo, "bench/run.py", "open('side.txt','w').write('1')\n" + read(self.repo, "bench/run.py"))
        git(self.repo, "commit", "-qam", "side")
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.contract()["baseline"]["side_effects"], ["side.txt"])
        self.assertIn("--generated", r.stderr)

    def test_baseline_mutating_frozen_dies(self):
        write(self.repo, "bench/run.py", "open('bench/run.py','a').write('#')\n" + read(self.repo, "bench/run.py"))
        git(self.repo, "commit", "-qam", "mutate")
        r = self.init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("冻结", r.stderr)


class SealAndLayoutTests(Harness):
    def test_tampered_agreement_is_refused(self):
        self.ready()
        path = os.path.join(self.home, "contract.json")
        c = json.loads(read(self.home, "contract.json"))
        c["target"] = 999
        write(self.home, "contract.json", json.dumps(c))
        r = self.run_j("status")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--renew", r.stderr)
        self.assertTrue(os.path.isfile(path))

    def test_tampered_sealed_state_is_refused(self):
        self.ready()
        c = json.loads(read(self.home, "contract.json"))
        c["best"] = "0" * 40
        write(self.home, "contract.json", json.dumps(c))
        code, _ = self.attempt({"src/impl.py": "N=100\n"})
        self.assertEqual(code, 2)

    def test_renew_reseals(self):
        self.ready()
        c = json.loads(read(self.home, "contract.json"))
        c["target"] = 1
        write(self.home, "contract.json", json.dumps(c))
        r = self.init("--renew")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.status()["target"], 150)

    def test_newer_schema_is_refused(self):
        from evloop.contract import Home
        self.assertEqual(self.init().returncode, 0)
        h = Home(self.home)
        c = h.load()
        c["schema_version"] = 99
        h.save(c)
        r = self.run_j("status")
        self.assertEqual(r.returncode, 3)
        self.assertIn("升级", r.stderr)

    def test_home_outside_runs_dies(self):
        r = self.run_j(
            "init", "--repo", self.repo, "--scenario", "bugfix", "--editable", "src", "--frozen", "bench",
            "--test-cmd", "false", home=os.path.join(self.root, "elsewhere"))
        self.assertEqual(r.returncode, 3)
        self.assertIn(".evloop/runs", r.stderr)

    def test_home_missing_is_a_usage_error(self):
        r = subprocess.run([sys.executable, JUDGE, "status"], text=True, capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--home", r.stderr)

    def test_state_dir_is_excluded_per_clone(self):
        r = self.init()
        self.assertEqual(r.returncode, 0)
        exclude = read(self.repo, ".git/info/exclude")
        self.assertIn("/.evloop/", exclude)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.init("--renew")
        self.assertEqual(read(self.repo, ".git/info/exclude").count("/.evloop/"), 1)

    def test_worktree_hidden_state_is_refused(self):
        self.ready()
        write(self.wt, ".evloop/stash.txt", "x")
        self.commit({"src/impl.py": "N=100\n"})
        r = self.run_j("attempt", "--route", "x")
        self.assertEqual(r.returncode, 3)
        self.assertIn(".evloop", r.stderr)
        self.assertIn("git clean -fdx", self.status()["next"])

    def test_init_in_linked_worktree_dies(self):
        self.add_worktree()
        r = self.run_j("init", "--repo", self.wt, "--scenario", "bugfix", "--editable", "src",
                       "--frozen", "bench", "--test-cmd", "false",
                       home=os.path.join(self.wt, ".evloop", "runs", "t"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("链接工作区", r.stderr)

    def test_lock_contention_is_refused(self):
        from evloop.util import file_lock
        self.assertEqual(self.init().returncode, 0)
        with file_lock(os.path.join(self.home, ".lock")):
            r = self.run_j("verify")
        self.assertEqual(r.returncode, 3)
        self.assertIn("另一个", r.stderr)

    def test_torn_tail_is_ignored_then_truncated(self):
        self.ready()
        with open(os.path.join(self.home, "attempts.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"n": 9, "kind": "att')
        s = self.run_j("status")
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("残缺", s.stderr)
        code, rec = self.attempt({"src/impl.py": "N=100\n"})
        self.assertEqual(code, 0)
        self.assertEqual(rec["n"], 1)
        self.assertEqual([r["n"] for r in self.records()], [0, 0, 1])

    def test_corrupt_middle_line_is_refused(self):
        self.ready()
        path = os.path.join(self.home, "attempts.jsonl")
        lines = read(self.home, "attempts.jsonl").splitlines()
        lines.insert(1, "garbage")
        write(self.home, "attempts.jsonl", "\n".join(lines) + "\n")
        r = self.run_j("status")
        self.assertEqual(r.returncode, 2)
        self.assertIn("第 2 行", r.stderr)
        self.assertTrue(os.path.isfile(path))


class RelocateTests(Harness):
    def clone(self):
        new = os.path.join(self.root, "clone")
        git(self.root, "clone", "-q", "--no-local", "--single-branch", "-b", "main", self.repo, new)
        return new

    def move_runs(self, new):
        dest = os.path.join(new, ".evloop", "runs", "task")
        os.makedirs(os.path.dirname(dest))
        shutil.copytree(self.home, dest)
        return dest

    def test_relocate_repoints_clone(self):
        self.assertEqual(self.init().returncode, 0)
        new = self.clone()
        home = self.move_runs(new)
        r = self.run_j("relocate", "--repo", new, home=home)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(home, "contract.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["repo"], new)
        self.assertIn("/.evloop/", read(new, ".git/info/exclude"))

    def test_relocate_requires_run_dir_in_new_clone(self):
        self.assertEqual(self.init().returncode, 0)
        new = self.clone()
        r = self.run_j("relocate", "--repo", new)
        self.assertEqual(r.returncode, 3)

    def test_relocate_same_clone_dies(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.run_j("relocate", "--repo", self.repo)
        self.assertEqual(r.returncode, 3)
        self.assertIn("已经指向", r.stderr)

    def test_relocate_to_linked_worktree_dies(self):
        self.assertEqual(self.init().returncode, 0)
        self.add_worktree()
        r = self.run_j("relocate", "--repo", self.wt)
        self.assertEqual(r.returncode, 3)

    def test_relocate_constitution_must_match(self):
        write(self.repo, ".evloop/constitution.json", '{"generated": ["out"]}')
        self.assertEqual(self.init().returncode, 0)
        new = self.clone()
        home = self.move_runs(new)
        r = self.run_j("relocate", "--repo", new, home=home)
        self.assertEqual(r.returncode, 3)
        self.assertIn("宪法", r.stderr)
        shutil.copy(os.path.join(self.repo, ".evloop/constitution.json"),
                    os.path.join(new, ".evloop/constitution.json"))
        self.assertEqual(self.run_j("relocate", "--repo", new, home=home).returncode, 0)

    def test_relocate_requires_best_commit_and_repoints_worktree(self):
        self.ready()
        self.attempt({"src/impl.py": "N=180\n"})
        new = self.clone()
        home = self.move_runs(new)
        r = self.run_j("relocate", "--repo", new, home=home)
        self.assertEqual(r.returncode, 3)
        self.assertIn("最优提交", r.stderr)
        git(new, "fetch", "-q", self.repo, "evloop/task:evloop/task")
        new_wt = os.path.join(self.root, "wt2")
        git(new, "worktree", "add", "-q", new_wt, "evloop/task")
        r = self.run_j("relocate", "--repo", new, "--worktree", new_wt, home=home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["worktree"], new_wt)

    def test_relocate_worktree_must_not_be_the_clone(self):
        self.ready()
        new = self.clone()
        home = self.move_runs(new)
        git(new, "fetch", "-q", self.repo, "evloop/task:evloop/task")
        r = self.run_j("relocate", "--repo", new, "--worktree", new, home=home)
        self.assertEqual(r.returncode, 3)

    def test_relocate_worktree_must_contain_best(self):
        self.ready()
        self.attempt({"src/impl.py": "N=180\n"})
        new = self.clone()
        home = self.move_runs(new)
        git(new, "fetch", "-q", self.repo, "evloop/task:evloop/task")
        other = os.path.join(self.root, "wt3")
        git(new, "worktree", "add", "-q", "-b", "x", other, "main")
        r = self.run_j("relocate", "--repo", new, "--worktree", other, home=home)
        self.assertEqual(r.returncode, 3)
        self.assertIn("不包含最优提交", r.stderr)

    def test_relocate_warns_when_branch_from_missing(self):
        self.assertEqual(self.init("--branch-from", "release").returncode, 0)
        new = self.clone()
        home = self.move_runs(new)
        r = self.run_j("relocate", "--repo", new, home=home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("release", r.stderr)


class DoctorTests(Harness):
    def test_doctor_without_home(self):
        r = subprocess.run([sys.executable, JUDGE, "doctor"], text=True, capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        names = {c["name"] for c in json.loads(r.stdout)["checks"]}
        self.assertEqual(names, {"python", "git"})

    def test_doctor_healthy_loop(self):
        self.ready()
        out = self.json_out(self.run_j("doctor"))
        self.assertTrue(out["ok"], out)

    def test_doctor_flags_problems_without_changing_state(self):
        self.ready()
        self.commit({"src/impl.py": "N=1\n"})
        write(self.wt, ".evloop/x", "1")
        before = read(self.home, "contract.json")
        r = self.run_j("doctor")
        self.assertEqual(r.returncode, 1)
        bad = {c["name"] for c in json.loads(r.stdout)["checks"] if not c["ok"]}
        self.assertEqual(bad, {"head", "hidden_state"})
        self.assertEqual(read(self.home, "contract.json"), before)

    def test_doctor_reports_tampered_contract(self):
        self.ready()
        c = json.loads(read(self.home, "contract.json"))
        c["delta"] = 0.0001
        write(self.home, "contract.json", json.dumps(c))
        out = json.loads(self.run_j("doctor").stdout)
        self.assertFalse(out["ok"])
        self.assertIn("contract", {x["name"] for x in out["checks"] if not x["ok"]})


class CliTests(unittest.TestCase):
    def test_version_and_help(self):
        r = subprocess.run([sys.executable, JUDGE, "--version"], text=True, capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0)
        from evloop import __version__
        self.assertIn(__version__, r.stdout)
        r = subprocess.run([sys.executable, JUDGE, "--help"], text=True, capture_output=True, env=ENV)
        for cmd in ("init", "start", "smoke", "attempt", "status", "verify", "report", "approve",
                    "relocate", "doctor"):
            self.assertIn(cmd, r.stdout)


if __name__ == "__main__":
    unittest.main()
