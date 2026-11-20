"""修复与开发场景。"""
import json
import os
import unittest

from helpers import Harness, git, read, write

TEST = "import sys; sys.path.insert(0, 'src'); import impl; raise SystemExit(0 if impl.add(2, 2) == 4 else 1)\n"

BLUEPRINT = {"meta": {"title": "目标"},
             "nodes": [{"id": "api", "label": "API"}, {"id": "store", "label": "存储"},
                       {"id": "cli", "label": "命令行"}],
             "edges": [{"from": "cli", "to": "api"}, {"from": "api", "to": "store"}],
             "depends": {"api": ["store"], "cli": ["api"]}}
ASIS = {"nodes": [{"id": "store", "label": "存储"}]}


class BugfixTests(Harness):
    scenario = "bugfix"

    def seed(self):
        write(self.repo, "src/impl.py", "def add(a, b):\n    return a - b\n")
        write(self.repo, "tests/t.py", TEST)

    def ready(self, *extra):
        r = self.init(*extra, frozen="tests", test_cmd="python3 tests/t.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()

    def test_requires_test_cmd(self):
        r = self.init(frozen="tests", test_cmd=None)
        self.assertEqual(r.returncode, 3)
        self.assertIn("--test-cmd", r.stderr)

    def test_requires_frozen(self):
        r = self.init(frozen=None, test_cmd="python3 tests/t.py")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--frozen", r.stderr)

    def test_rejects_baseline_that_already_passes(self):
        r = self.init(frozen="tests", test_cmd="true")
        self.assertEqual(r.returncode, 3)
        self.assertIn("已经通过", r.stderr)

    def test_failing_then_fixed(self):
        self.ready()
        code, rec = self.attempt({"src/impl.py": "def add(a, b):\n    return a * b + 0 - 0 if False else 0\n"})
        self.assertEqual((code, rec["verdict"]), (1, "failing"))
        self.assertEqual(self.contract()["best"], self.head())
        self.assertEqual(self.status()["decision"], "continue")
        code, rec = self.attempt({"src/impl.py": "def add(a, b):\n    return a + b\n"})
        self.assertEqual((code, rec["verdict"]), (0, "accepted"))
        s = self.status()
        self.assertTrue(s["all_tests_pass"])
        self.assertEqual(s["decision"], "handoff")

    def test_rolled_back_attempt_keeps_passing_state(self):
        self.ready()
        self.attempt({"src/impl.py": "def add(a, b):\n    return a + b\n"})
        code, _ = self.attempt({"README": "x"})
        self.assertEqual(code, 2)
        self.assertTrue(self.status()["all_tests_pass"])

    def test_frozen_test_edit_is_invalid(self):
        self.ready()
        code, rec = self.attempt({"tests/t.py": "pass\n"})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))

    def test_verify_and_report(self):
        self.ready()
        self.attempt({"src/impl.py": "def add(a, b):\n    return a + b\n"})
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["verdict"], "verified")
        self.run_j("report")
        html = read(self.home, "handoff.html")
        self.assertIn("约定测试全部通过", html)
        self.assertIn("已验证", html)

    def test_report_does_not_claim_success_after_failed_verification(self):
        self.ready("--generated", "out")
        self.attempt({"src/impl.py": "import os\nos.makedirs('out', exist_ok=True)\n"
                                     "FLAG = os.path.exists('out/seen')\nopen('out/seen', 'w').close()\n"
                                     "def add(a, b):\n    return a - b if FLAG else a + b\n"})
        self.assertTrue(self.status()["all_tests_pass"])
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 2)
        self.run_j("report")
        html = read(self.home, "handoff.html")
        self.assertIn("验证失败", html)
        self.assertIn("尚未完成", html)


class DevelopmentTests(Harness):
    scenario = "development"

    def seed(self):
        write(self.repo, "src/app.py", "x = 1\n")
        write(self.repo, "design/blueprint.json", json.dumps(BLUEPRINT, ensure_ascii=False))
        write(self.repo, "design/asis.json", json.dumps(ASIS))

    def dev_init(self, *extra, check_cmd=None, blueprint="design/blueprint.json", asbuilt="src/asbuilt.json"):
        args = ["--blueprint", blueprint, "--asis", "design/asis.json", "--asbuilt", asbuilt]
        if check_cmd:
            args += ["--check-cmd", check_cmd]
        return self.init(*args, *extra, frozen=None, test_cmd=None)

    def dev_ready(self, **kw):
        r = self.dev_init(**kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()

    def test_init_stores_elements_batches_and_freezes_docs(self):
        r = self.dev_init()
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.contract()
        self.assertEqual(c["elements"], ["api", "store", "cli"])
        self.assertEqual(c["batches"], [["store"], ["api"], ["cli"]])
        self.assertEqual(c["elements_new"], ["api", "cli"])
        self.assertIn("design/blueprint.json", c["frozen"])
        for name in ("blueprint.html", "asis.html", "blueprint.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.home, name)), name)

    def test_init_rejects_test_cmd(self):
        r = self.init("--blueprint", "design/blueprint.json", "--asis", "design/asis.json",
                      "--asbuilt", "src/a.json", frozen=None, test_cmd="true")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--check-cmd", r.stderr)

    def test_invalid_blueprint_dies(self):
        write(self.repo, "design/bad.json", '{"nodes": []}')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "bad")
        r = self.dev_init(blueprint="design/bad.json")
        self.assertEqual(r.returncode, 3)
        self.assertIn("nodes", r.stderr)

    def test_cycle_dies(self):
        bp = dict(BLUEPRINT, depends={"api": ["cli"], "cli": ["api"]})
        write(self.repo, "design/blueprint.json", json.dumps(bp))
        git(self.repo, "commit", "-qam", "cycle")
        r = self.dev_init()
        self.assertEqual(r.returncode, 3)
        self.assertIn("成环", r.stderr)

    def test_unknown_dependency_dies(self):
        bp = dict(BLUEPRINT, depends={"api": ["ghost"]})
        write(self.repo, "design/blueprint.json", json.dumps(bp))
        git(self.repo, "commit", "-qam", "ghost")
        r = self.dev_init()
        self.assertEqual(r.returncode, 3)

    def test_asbuilt_outside_editable_dies(self):
        r = self.dev_init(asbuilt="docs/asbuilt.json")
        self.assertEqual(r.returncode, 3)
        self.assertIn("--asbuilt", r.stderr)

    def test_checkpoint_without_check_cmd(self):
        self.dev_ready()
        code, rec = self.attempt({"src/store.py": "s = {}\n"}, "--elements", "store")
        self.assertEqual((code, rec["verdict"]), (1, "checkpoint"))
        self.assertEqual(self.contract()["best"], self.head())
        self.assertEqual(self.status()["elements_done"], ["store"])

    def test_claim_with_unmet_dependency_is_refused(self):
        self.dev_ready()
        self.commit({"src/cli.py": "x\n"})
        r = self.run_j("attempt", "--elements", "cli")
        self.assertEqual(r.returncode, 3)
        self.assertIn("依赖尚未实现", r.stderr)
        r = self.run_j("attempt", "--elements", "cli", "api", "store")
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_unknown_element_is_refused(self):
        self.dev_ready()
        self.commit({"src/x.py": "x\n"})
        r = self.run_j("attempt", "--elements", "nope")
        self.assertEqual(r.returncode, 3)

    def test_failing_claim_is_pending_until_green(self):
        self.dev_ready(check_cmd="test ! -e src/broken")
        code, rec = self.attempt({"src/store.py": "s\n", "src/broken": "1"}, "--elements", "store")
        self.assertEqual((code, rec["verdict"]), (1, "failing"))
        s = self.status()
        self.assertEqual(s["elements_pending"], ["store"])
        self.assertEqual(s["elements_done"], [])
        self.assertIn("变绿", s["next"])
        code, rec = self.attempt({"src/broken": None})
        self.assertEqual((code, rec["verdict"]), (0, "green"))
        self.assertEqual(self.status()["elements_done"], ["store"])

    def test_frozen_doc_edit_is_invalid(self):
        self.dev_ready()
        write(self.wt, "src/x.py", "x")
        code, rec = self.attempt({"design/asis.json": "{}"})
        self.assertEqual(code, 2)

    def test_status_gates_on_asbuilt_elements_and_check(self):
        self.dev_ready(check_cmd="true")
        self.attempt({"src/store.py": "s\n"}, "--elements", "store")
        self.attempt({"src/api.py": "a\n"}, "--elements", "api", "cli")
        s = self.status()
        self.assertFalse(s["asbuilt_exists"])
        self.assertEqual(s["decision"], "continue")
        self.assertIn("竣工图", s["next"])
        partial = {"nodes": [{"id": "store", "label": "存储"}]}
        self.attempt({"src/asbuilt.json": json.dumps(partial)})
        s = self.status()
        self.assertEqual(s["elements_missing"], ["api", "cli"])
        self.attempt({"src/asbuilt.json": json.dumps(BLUEPRINT, ensure_ascii=False)})
        s = self.status()
        self.assertTrue(s["asbuilt_matches_blueprint"])
        self.assertEqual(s["decision"], "handoff")

    def test_matching_asbuilt_without_claims_does_not_hand_off(self):
        self.dev_ready(check_cmd="true")
        self.attempt({"src/asbuilt.json": json.dumps(BLUEPRINT, ensure_ascii=False)})
        s = self.status()
        self.assertTrue(s["asbuilt_matches_blueprint"])
        self.assertEqual(s["decision"], "continue")

    def test_broken_asbuilt_is_reported(self):
        self.dev_ready()
        self.attempt({"src/asbuilt.json": "{oops"}, "--elements", "store", "api", "cli")
        s = self.status()
        self.assertIn("asbuilt_error", s)
        self.assertEqual(s["decision"], "continue")

    def test_verify_without_check_cmd_dies(self):
        self.dev_ready()
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 3)

    def test_manual_approval_without_check_cmd(self):
        self.dev_ready()
        self.attempt({"src/asbuilt.json": json.dumps(BLUEPRINT, ensure_ascii=False)},
                     "--elements", "store", "api", "cli")
        self.assertEqual(self.status()["decision"], "handoff")
        self.assertEqual(self.run_j("report").returncode, 0)
        r = self.run_j("approve", "--note", "人工看过")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.status()["approved"])

    def test_report_lists_build_order_and_coverage(self):
        self.dev_ready()
        self.attempt({"src/asbuilt.json": json.dumps(ASIS)}, "--elements", "store")
        r = self.run_j("report", "--progress")
        self.assertEqual(r.returncode, 0, r.stderr)
        html = read(self.home, "progress.html")
        self.assertIn("构建顺序", html)
        self.assertIn("新增", html)
        self.assertIn("当前实现", html)
        self.assertIn("元素覆盖", html)


if __name__ == "__main__":
    unittest.main()
