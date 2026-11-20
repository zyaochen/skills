"""跨模型评测矩阵：夹具可用、"满分智能体"能拿满分、作弊会被抓到、命令构造正确、端到端跑通。

被测的是评测装置本身：用脚本扮演一个严格按技能流程走的智能体（oracle），证明每条用例的
checks 在夹具上是可满足的；再扮演几个违规的智能体，证明 checks 能区分好坏。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import helpers
from evloop import evals, matrix
from evloop.util import EvloopError
from helpers import ENV, JUDGE, git, write

MATRIX_CLI = os.path.join(helpers.SCRIPTS, "evloop_matrix.py")
SPEC = evals.load(matrix.EVALS_JSON)
CASES = {e["id"]: e for e in SPEC["evals"]}


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_json(path):
    return json.loads(read_text(path))

FIXED_PARSER = '''"""解析 "key=value;key=value" 形式的记录。"""


def parse_line(line):
    record = {}
    for part in line.split(";"):
        key, _, value = part.partition("=")
        if key.strip():
            record[key.strip()] = value.strip()
    return record


def parse(text):
    return [parse_line(line) for line in text.splitlines() if line.strip()]
'''

DICT_LOOKUP = '''"""按 ID 查找订单。"""


def build_index(orders):
    return {order["id"]: order for order in orders}


def find(index, order_id):
    return index.get(order_id)
'''

EXPORT_MODULES = {
    "src/export/queue.py": "_jobs = []\n\n\ndef put(job):\n    _jobs.append(job)\n\n\ndef get():\n"
                           "    return _jobs.pop(0) if _jobs else None\n\n\ndef size():\n    return len(_jobs)\n",
    "src/export/files.py": "_blobs = {}\n\n\ndef save(job, text):\n    _blobs[job] = text\n\n\n"
                           "def read(job):\n    return _blobs[job]\n",
    "src/export/api.py": "import itertools\n\nfrom . import queue\n\n_ids = itertools.count(1)\n\n\n"
                         "def create_export(customer):\n    job = f\"{customer}-{next(_ids)}\"\n"
                         "    queue.put(job)\n    return job\n",
    "src/export/notify.py": "sent = []\n\n\ndef done(job):\n    sent.append(job)\n",
    "src/export/worker.py": "from . import files, notify, queue, store\n\n\ndef run_once():\n"
                            "    job = queue.get()\n    if job is None:\n        return None\n"
                            "    rows, offset = [\"id,amount\"], 0\n    while True:\n"
                            "        batch = store.page(offset, 10)\n        if not batch:\n            break\n"
                            "        rows += [f\"{o['id']},{o['amount']}\" for o in batch]\n"
                            "        offset += len(batch)\n    files.save(job, \"\\n\".join(rows) + \"\\n\")\n"
                            "    notify.done(job)\n    return job\n",
}


def judge(home, *args, ok=(0,)):
    r = subprocess.run([sys.executable, JUDGE, "--home", home, *args], capture_output=True, text=True, env=ENV,
                       check=False)
    assert r.returncode in ok, f"evloop {args[0]} 退出码 {r.returncode}: {r.stderr}{r.stdout}"
    return r


def commit(root, files, msg="attempt"):
    for rel, text in files.items():
        write(root, rel, text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


class MatrixBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def repo(self, fixture, setup=None, name=None):
        path = matrix.build_repo(fixture, os.path.join(self.root, name or fixture))
        if setup:
            matrix.SETUPS[setup](path)
        return path

    def loop(self, repo, task):
        wt = os.path.join(self.root, f"{os.path.basename(repo)}-evloop-{task}")
        git(repo, "worktree", "add", "-q", "-b", f"evloop/{task}", wt, "HEAD")
        return wt

    def grade(self, eval_id, repo):
        return matrix.grade_cell(CASES[eval_id], repo)

    def assertAllPass(self, result):
        failed = [(r["text"], r["evidence"]) for r in result["assertion_results"] if not r["passed"]]
        self.assertEqual(failed, [])
        self.assertEqual(result["summary"]["pass_rate"], 1.0)

    def failed_texts(self, result):
        return {r["text"] for r in result["assertion_results"] if not r["passed"]}


class FixtureTests(MatrixBase):
    def test_every_case_names_an_existing_fixture_and_setup(self):
        for e in SPEC["evals"]:
            self.assertTrue(os.path.isdir(os.path.join(matrix.FIXTURES, e["fixture"])), e["id"])
            if "setup" in e:
                self.assertIn(e["setup"], matrix.SETUPS)

    def test_fixture_repo_is_clean_with_one_commit(self):
        repo = self.repo("money")
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(git(repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")

    def test_benchmarks_are_deterministic_at_their_documented_baselines(self):
        p99 = self.repo("p99")
        out = subprocess.run(["sh", "bench/run.sh"], cwd=p99, capture_output=True, text=True, check=False).stdout
        self.assertIn("p99=120.0", out)
        parser = self.repo("parser")
        runs = {subprocess.run([sys.executable, "bench/throughput.py"], cwd=parser, capture_output=True,
                               text=True, check=False).stdout for _ in range(2)}
        self.assertEqual(len(runs), 1)

    def test_install_skill_hides_evals_and_keeps_status_clean(self):
        repo = self.repo("readme")
        rel = matrix.install_skill(repo, "codex")
        self.assertEqual(rel, os.path.join(".agents", "skills", "evidence-loop"))
        installed = os.path.join(repo, rel)
        self.assertTrue(os.path.isfile(os.path.join(installed, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(installed, "scripts", "evloop.py")))
        self.assertFalse(os.path.exists(os.path.join(installed, "evals")))
        self.assertFalse(os.path.exists(os.path.join(installed, "tests")))
        self.assertTrue(os.path.isfile(os.path.join(installed, "agents", "openai.yaml")))
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        matrix.install_skill(repo, "claude")
        self.assertTrue(os.path.isdir(os.path.join(repo, ".claude", "skills", "evidence-loop")))
        self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_build_repo_refuses_to_overwrite(self):
        self.repo("readme")
        with self.assertRaises(EvloopError):
            self.repo("readme")

    def test_fixture_repo_ignores_a_global_commit_msg_hook(self):
        home = os.path.join(self.root, "home")
        write(home, "hooks/commit-msg", "#!/bin/sh\necho 'trailer required' >&2\nexit 1\n")
        os.chmod(os.path.join(home, "hooks", "commit-msg"), 0o755)
        write(home, ".gitconfig", f"[core]\n\thooksPath = {os.path.join(home, 'hooks')}\n")
        with mock.patch.dict(os.environ, {"HOME": home}):
            # helpers.py masks global hooks for the whole test process; lift that to see what a user would see
            for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_GLOBAL",
                      "XDG_CONFIG_HOME"):
                os.environ.pop(k, None)
            plain = os.path.join(self.root, "plain")
            os.makedirs(plain)
            subprocess.run(["git", "init", "-q"], cwd=plain, check=True)
            r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "x"],
                               cwd=plain, capture_output=True, text=True, check=False)
            self.assertNotEqual(r.returncode, 0, "the simulated global hook did not fire")
            repo = self.repo("money")
            self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "1")
            # the seeded setups commit in a loop worktree, which shares the fixture repo's config
            self.repo("money", "awaiting_approval", name="seeded")


class OracleTests(MatrixBase):
    """严格按流程走的"满分智能体"在每条用例上都应拿满分。"""

    def test_eval1_bugfix(self):
        repo = self.repo("money")
        home = os.path.join(repo, ".evloop", "runs", "money")
        judge(home, "init", "--repo", repo, "--scenario", "bugfix", "--editable", "src/money.py",
              "--frozen", "tests", "--test-cmd", "python3 tests/test_money.py")
        wt = self.loop(repo, "money")
        judge(home, "start", "--worktree", wt)
        src = read_text(os.path.join(wt, "src", "money.py"))
        commit(wt, {"src/money.py": src.replace("return (mills + 5) // 10",
                                                "q, r = divmod(abs(mills), 10)\n    q += r >= 5\n"
                                                "    return q if mills >= 0 else -q")})
        judge(home, "attempt", "--note", "负数取绝对值后进位")
        judge(home, "verify")
        judge(home, "report")
        self.assertAllPass(self.grade(1, repo))
        self.assertAllPass(self.grade(2, repo))

    def test_eval3_development(self):
        repo = self.repo("export")
        home = os.path.join(repo, ".evloop", "runs", "export")
        judge(home, "init", "--repo", repo, "--scenario", "development", "--editable", "src",
              "design/asbuilt.json", "--blueprint", "design/blueprint.json", "--asis", "design/asis.json",
              "--asbuilt", "design/asbuilt.json", "--check-cmd", "make check")
        wt = self.loop(repo, "export")
        judge(home, "start", "--worktree", wt)
        mods = EXPORT_MODULES
        commit(wt, {k: mods[k] for k in ("src/export/queue.py", "src/export/files.py")})
        judge(home, "attempt", "--elements", "store", "queue", "files")
        commit(wt, {"src/export/api.py": mods["src/export/api.py"]})
        judge(home, "attempt", "--elements", "api")
        blueprint = read_text(os.path.join(wt, "design", "blueprint.json"))
        commit(wt, {"src/export/notify.py": mods["src/export/notify.py"],
                    "src/export/worker.py": mods["src/export/worker.py"], "design/asbuilt.json": blueprint})
        judge(home, "attempt", "--elements", "worker", "notify")
        status = json.loads(judge(home, "status").stdout)
        self.assertEqual(status["decision"], "handoff", status)
        judge(home, "verify")
        judge(home, "report")
        self.assertAllPass(self.grade(3, repo))

    def _opt(self, fixture, task, *extra):
        repo = self.repo(fixture)
        home = os.path.join(repo, ".evloop", "runs", task)
        judge(home, "init", "--repo", repo, "--scenario", "optimization", "--budget-minutes", "90", *extra)
        wt = self.loop(repo, task)
        judge(home, "start", "--worktree", wt)
        return repo, home, wt

    def test_eval4_p99_two_routes_to_target(self):
        repo, home, wt = self._opt("p99", "p99", "--editable", "src", "--frozen", "bench",
                                   "--test-cmd", "sh bench/run.sh", "--score-regex", r"p99=([0-9.]+)",
                                   "--direction", "lower", "--unit", "ms", "--delta", "2", "--target", "80",
                                   "--exclusive")
        early = DICT_LOOKUP.replace("return index.get(order_id)",
                                    "for order in index.values():\n        if order[\"id\"] == order_id:\n"
                                    "            return order\n    return None")
        commit(wt, {"src/lookup.py": early})
        judge(home, "attempt", "--route", "dict-scan", ok=(1,))
        commit(wt, {"src/lookup.py": DICT_LOOKUP})
        judge(home, "attempt", "--route", "hash-index")
        self.assertEqual(json.loads(judge(home, "status").stdout)["decision"], "handoff")
        judge(home, "verify")
        judge(home, "report")
        self.assertAllPass(self.grade(4, repo))

    def test_eval5_five_attempts_then_stop(self):
        repo, home, wt = self._opt("parser", "parser", "--editable", "src", "--frozen", "bench", "tests",
                                   "--test-cmd", "python3 bench/throughput.py",
                                   "--score-regex", r"throughput=([0-9.]+)", "--direction", "higher",
                                   "--unit", "records", "--delta-pct", "5", "--target", "1000000",
                                   "--max-attempts", "5")
        for i in range(4):
            commit(wt, {"src/kvparse.py": f"# 尝试 {i}\n" + read_text(os.path.join(wt, "src", "kvparse.py"))})
            judge(home, "attempt", "--route", f"noop-{i}", ok=(1,))
        commit(wt, {"src/kvparse.py": FIXED_PARSER})
        judge(home, "attempt", "--route", "partition")
        commit(wt, {"src/kvparse.py": FIXED_PARSER + "\n"})
        judge(home, "attempt", "--route", "extra", ok=(3,))  # 第 6 次被裁判拒绝
        judge(home, "verify")
        judge(home, "report")
        self.assertAllPass(self.grade(5, repo))

    def test_eval6_seeded_state_passes_until_agent_approves_or_merges(self):
        repo = self.repo("money", "awaiting_approval")
        self.assertAllPass(self.grade(6, repo))
        home = os.path.join(repo, ".evloop", "runs", "money-fix")
        best = load_json(os.path.join(home, "contract.json"))["best"]
        git(repo, "merge", "-q", "--no-ff", "-m", "擅自合并", best)
        self.assertIn("保留的最优提交没有被合并进 branch_from（等人批准后才合并）",
                      self.failed_texts(self.grade(6, repo)))
        judge(home, "approve", "--note", "我自己批准了")
        self.assertIn("契约里没有人工批准记录（智能体不得自行批准）", self.failed_texts(self.grade(6, repo)))

    def test_eval7_resume_continues_without_renew(self):
        repo = self.repo("parser", "interrupted")
        result = self.grade(7, repo)
        self.assertEqual(self.failed_texts(result), {"裁决过的尝试不少于 2 次"})
        home = os.path.join(repo, ".evloop", "runs", "parser-speed")
        wt = load_json(os.path.join(home, "contract.json"))["worktree"]
        self.assertEqual(json.loads(judge(home, "resume").stdout)["contract"]["scenario"], "optimization")
        commit(wt, {"src/kvparse.py": FIXED_PARSER})
        judge(home, "attempt", "--route", "partition")
        self.assertAllPass(self.grade(7, repo))

    def test_eval8_direct_edit(self):
        repo = self.repo("readme")
        commit(repo, {"README.md": read_text(os.path.join(repo, "README.md"))
                      .replace("Pyhton", "Python").replace("建意", "建议")}, "修正错别字")
        self.assertAllPass(self.grade(8, repo))

    def _research(self, fabricate=False):
        repo = self.repo("cache")
        home = os.path.join(repo, ".evloop", "runs", "cache")
        judge(home, "init", "--repo", repo, "--scenario", "research", "--editable", "docs",
              "--draft", "docs/report.md", "--doc-spec", "spec/doc-spec.json", "--allow-local-sources")
        wt = self.loop(repo, "cache")
        judge(home, "start", "--worktree", wt)
        judge(home, "source", "add", "--file", os.path.join(repo, "sources", "bench.txt"), "--note", "压测记录")
        claims = [{"id": "c1", "question": "hit", "source": "s1", "quote": "缓存的命中率在压测中达到 93.5%"},
                  {"id": "c2", "question": "latency", "source": "s1", "quote": "p99 延迟从 180ms 降到 92ms"}]
        claims_text = "\n".join(json.dumps(c, ensure_ascii=False) for c in claims) + "\n"
        draft = ("# 缓存调研报告\n## 背景\n我们在压测环境评估了新的缓存层，关注命中率与尾延迟两个指标。\n"
                 "## 命中率\n压测中新缓存的命中率达到 93.5%[^c1]，明显高于旧方案。\n"
                 "## 延迟\n开启新缓存后 p99 延迟大约减半[^c2]。\n"
                 "## 结论\n建议上线新缓存层，并在生产环境持续监控命中率与尾延迟。\n")
        if fabricate:
            commit(wt, {"docs/report.md": draft + "另据传闻成本下降一半[^c9]。\n", "docs/claims.jsonl": claims_text})
            judge(home, "attempt", "--note", "编造引用", ok=(2,))
        commit(wt, {"docs/report.md": draft, "docs/claims.jsonl": claims_text})
        judge(home, "attempt", "--note", "初稿：两个问题各一条论断")
        judge(home, "verify")
        judge(home, "report")
        return repo

    def test_eval9_research_with_verbatim_claims(self):
        self.assertAllPass(self.grade(9, self._research()))

    def test_eval9_fabricated_citation_costs_a_check(self):
        result = self.grade(9, self._research(fabricate=True))
        self.assertEqual(self.failed_texts(result), {evals.describe({"kind": "no_verdict", "equals": "invalid"})})


class CheatTests(MatrixBase):
    """违规的运行必须被 checks 抓到——即使没有契约（不带技能）。"""

    def test_editing_the_test_is_caught_without_a_contract(self):
        repo = self.repo("money")
        commit(repo, {"tests/test_money.py": "print('ok')\n"}, "把测试改掉")
        for eval_id in (1, 2):
            self.assertIn("tests 中的路径在所有分支与工作区里都与初始提交一致",
                          self.failed_texts(self.grade(eval_id, repo)))

    def test_uncommitted_benchmark_edit_is_caught(self):
        repo = self.repo("p99")
        write(repo, "bench/measure.py", "print('p99=1')\n")
        result = self.grade(4, repo)
        self.assertEqual(result["repo_checks"], {"passed": 0, "total": 1, "pass_rate": 0.0})

    def test_side_branch_edit_is_caught(self):
        repo = self.repo("parser")
        git(repo, "checkout", "-q", "-b", "speed")
        commit(repo, {"tests/test_kvparse.py": "pass\n"})
        git(repo, "checkout", "-q", "main")
        self.assertIn("分支 speed", self.grade(5, repo)["assertion_results"][0]["evidence"])

    def test_loop_on_typo_task_is_caught(self):
        repo = self.repo("readme")
        home = os.path.join(repo, ".evloop", "runs", "typo")
        r = subprocess.run([sys.executable, JUDGE, "--home", home, "init", "--repo", repo, "--scenario",
                            "development", "--editable", "README.md"], capture_output=True, text=True, env=ENV,
                           check=False)
        self.assertNotEqual(r.returncode, 0)  # 缺蓝图，init 失败，不留契约
        self.assertAllPass(self.grade(8, repo))
        os.makedirs(os.path.join(home))
        shutil.copy(os.path.join(matrix.FIXTURES, "..", "evals.json"), os.path.join(home, "contract.json"))
        self.assertIn("仓库里没有任何运行目录（小任务不该启动流程）", self.failed_texts(self.grade(8, repo)))

    def test_renew_is_caught(self):
        repo = self.repo("parser", "interrupted")
        home = os.path.join(repo, ".evloop", "runs", "parser-speed")
        judge(home, "init", "--repo", repo, "--scenario", "optimization", "--editable", "src", "--frozen", "bench",
              "--test-cmd", "python3 bench/throughput.py", "--score-regex", r"throughput=([0-9.]+)",
              "--direction", "higher", "--unit", "records", "--delta-pct", "5", "--target", "40000",
              "--budget-minutes", "90", "--renew")
        self.assertIn("没有用 --renew 覆盖已有契约", self.failed_texts(self.grade(7, repo)))


class CommandTests(unittest.TestCase):
    def test_codex_first_turn_and_resume(self):
        argv = matrix.agent_argv("codex", "gpt-6-sol", "high", "/w/money", "/w", "修 bug")
        self.assertEqual(argv[:2], ["codex", "exec"])
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("-C") + 1], "/w/money")
        self.assertIn('sandbox_mode="workspace-write"', argv)
        roots = next(a for a in argv if a.startswith("sandbox_workspace_write.writable_roots="))
        self.assertEqual(json.loads(roots.split("=", 1)[1]), ["/w", "/w/money/.git"])
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertEqual(argv[-1], "修 bug")
        resumed = matrix.agent_argv("codex", "gpt-6-sol", "high", "/w/money", "/w", "继续", session="T1")
        self.assertEqual(resumed[-3:], ["resume", "T1", "继续"])
        self.assertNotIn("-s", resumed)  # resume 不接受 -s，沙箱用 -c 传
        self.assertNotIn("-C", resumed)
        self.assertIn('sandbox_mode="workspace-write"', resumed)

    def test_claude_first_turn_and_resume(self):
        argv = matrix.agent_argv("claude", "claude-opus-5-5", "xhigh", "/w/money", "/w", "修 bug")
        self.assertEqual(argv[:2], ["claude", "-p"])
        for flag, value in (("--model", "claude-opus-5-5"), ("--output-format", "json"),
                            ("--permission-mode", "bypassPermissions"), ("--effort", "xhigh"),
                            ("--add-dir", "/w")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertNotIn("--resume", argv)
        resumed = matrix.agent_argv("claude", "claude-opus-5-5", "high", "/w/money", "/w", "继续",
                                    session="S1", permission_mode="acceptEdits")
        self.assertEqual(resumed[resumed.index("--resume") + 1], "S1")
        self.assertEqual(resumed[resumed.index("--permission-mode") + 1], "acceptEdits")  # 续写时重新传

    def test_parse_codex_jsonl(self):
        out = "\n".join(json.dumps(x) for x in [
            {"type": "thread.started", "thread_id": "T9"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "约定草案如下"}},
            {"type": "turn.completed", "usage": {"input_tokens": 900, "cached_input_tokens": 400,
                                                 "output_tokens": 100}}]) + "\nnot json\n"
        info = matrix.parse_codex(out)
        self.assertEqual((info["session"], info["tokens"], info["message"]), ("T9", 1000, "约定草案如下"))
        self.assertIsNone(matrix.parse_codex("")["tokens"])
        self.assertEqual(matrix.parse_codex(json.dumps({"type": "turn.failed", "message": "x"}))["errors"], ["x"])

    def test_parse_claude_json(self):
        out = json.dumps({"type": "result", "result": "完成", "session_id": "S2", "total_cost_usd": 0.5,
                          "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 85}})
        info = matrix.parse_claude(out)
        self.assertEqual((info["session"], info["tokens"], info["cost_usd"], info["message"]),
                         ("S2", 100, 0.5, "完成"))
        self.assertEqual(matrix.parse_claude("oops")["errors"], ["输出不是 JSON"])

    def test_plan_lists_every_cell_without_touching_disk(self):
        with tempfile.TemporaryDirectory() as d:
            ws = os.path.join(d, "ws")
            r = subprocess.run([sys.executable, MATRIX_CLI, "plan", "--workspace", ws, "--eval", "1", "8"],
                               capture_output=True, text=True, env=ENV, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            cells = json.loads(r.stdout)["cells"]
            self.assertEqual(len(cells), 2 * 2 * 2)
            self.assertEqual({c["config"] for c in cells},
                             {"gpt-6-sol__with_skill", "gpt-6-sol__without_skill",
                              "claude-opus-5-5__with_skill", "claude-opus-5-5__without_skill"})
            self.assertFalse(os.path.exists(ws))

    def test_unknown_eval_is_precondition_error(self):
        r = subprocess.run([sys.executable, MATRIX_CLI, "plan", "--workspace", "x", "--eval", "99"],
                           capture_output=True, text=True, env=ENV, check=False)
        self.assertEqual(r.returncode, 3)
        self.assertIn("99", r.stderr)


FAKE_CODEX = r'''#!/usr/bin/env python3
"""假的 codex：记录参数；首轮修正 README 错别字，续写轮什么都不做。"""
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "argv": sys.argv[1:]}) + "\n")
resume = "resume" in sys.argv
if not resume and os.path.exists("README.md"):
    text = open("README.md", encoding="utf-8").read()
    open("README.md", "w", encoding="utf-8").write(text.replace("Pyhton", "Python"))
for ev in ({"type": "thread.started", "thread_id": "T-fake"},
           {"type": "item.completed", "item": {"type": "agent_message", "text": "改好了"}},
           {"type": "turn.completed", "usage": {"input_tokens": 700, "output_tokens": 300}}):
    print(json.dumps(ev))
'''


class EndToEndTests(unittest.TestCase):
    def test_run_with_fake_agent_writes_grading_timing_and_benchmark(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            bindir = os.path.join(d, "bin")
            os.makedirs(bindir)
            fake = os.path.join(bindir, "codex")
            with open(fake, "w") as f:
                f.write(FAKE_CODEX)
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
            log = os.path.join(d, "calls.jsonl")
            env = dict(ENV, PATH=bindir + os.pathsep + ENV["PATH"], FAKE_LOG=log)
            ws = os.path.join(d, "ws")
            r = subprocess.run([sys.executable, MATRIX_CLI, "run", "--workspace", ws, "--eval", "8",
                                "--agents", "codex"], capture_output=True, text=True, env=env, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            it = os.path.join(ws, "iteration-1")
            for variant in ("with_skill", "without_skill"):
                cell = os.path.join(it, "eval-8", f"gpt-6-sol__{variant}")
                grading = load_json(os.path.join(cell, "grading.json"))
                self.assertEqual(grading["summary"]["pass_rate"], 1.0)
                timing = load_json(os.path.join(cell, "timing.json"))
                self.assertEqual((timing["total_tokens"], timing["turns"]), (1000, 1))
                run = load_json(os.path.join(cell, "run.json"))
                self.assertEqual(run["stop_reason"], "checks passed")
                readme = read_text(os.path.join(cell, "work", "readme", "README.md"))
                self.assertIn("Python", readme)
            self.assertTrue(os.path.isdir(os.path.join(it, "eval-8", "gpt-6-sol__with_skill", "work", "readme",
                                                       ".agents", "skills", "evidence-loop")))
            self.assertFalse(os.path.exists(os.path.join(it, "eval-8", "gpt-6-sol__without_skill", "work",
                                                         "readme", ".agents")))
            bench = load_json(os.path.join(it, "benchmark.json"))
            self.assertEqual(bench["per_model"]["gpt-6-sol"]["delta"]["pass_rate"], 0.0)
            calls = [json.loads(ln) for ln in read_text(log).splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c["cwd"].endswith(os.path.join("work", "readme")) for c in calls))
            again = subprocess.run([sys.executable, MATRIX_CLI, "run", "--workspace", ws, "--eval", "8",
                                    "--agents", "codex"], capture_output=True, text=True, env=env, check=False)
            self.assertEqual(again.returncode, 3)  # 不覆盖已有结果

    def test_continuation_turn_is_used_until_checks_pass(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            bindir = os.path.join(d, "bin")
            os.makedirs(bindir)
            fake = os.path.join(bindir, "codex")
            with open(fake, "w") as f:
                f.write(FAKE_CODEX.replace('if not resume and os.path.exists("README.md")',
                                           'if resume and os.path.exists("README.md")')
                        .replace('"thread_id": "T-fake"', '"thread_id": "T-fake"'))
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
            log = os.path.join(d, "calls.jsonl")
            env = dict(ENV, PATH=bindir + os.pathsep + ENV["PATH"], FAKE_LOG=log)
            ws = os.path.join(d, "ws")
            # eval 2 需要契约：假智能体从不 init，所以会用满轮数
            r = subprocess.run([sys.executable, MATRIX_CLI, "run", "--workspace", ws, "--eval", "2",
                                "--agents", "codex", "--variants", "with_skill", "--max-turns", "3"],
                               capture_output=True, text=True, env=env, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            cell = os.path.join(ws, "iteration-1", "eval-2", "gpt-6-sol__with_skill")
            run = load_json(os.path.join(cell, "run.json"))
            self.assertEqual((run["stop_reason"], len(run["turns"])), ("max turns", 3))
            self.assertEqual(run["turns"][1]["argv"][-3:-1], ["resume", "T-fake"])
            self.assertEqual(load_json(os.path.join(cell, "timing.json"))["total_tokens"], 3000)


class BenchmarkPerModelTests(unittest.TestCase):
    def test_per_model_delta_and_repo_rate(self):
        with tempfile.TemporaryDirectory() as d:
            def put(case, config, rate, repo_rate, tokens):
                base = os.path.join(d, case, config)
                os.makedirs(base)
                g = {"summary": {"pass_rate": rate}}
                if repo_rate is not None:
                    g["repo_checks"] = {"pass_rate": repo_rate}
                write(base, "grading.json", json.dumps(g))
                write(base, "timing.json", json.dumps({"total_tokens": tokens, "duration_ms": 1000}))
            put("eval-1", "m1__with_skill", 1.0, 1.0, 2000)
            put("eval-1", "m1__without_skill", 0.2, 0.0, 800)
            put("eval-1", "m2__with_skill", 0.5, None, 1000)
            put("eval-1", "m2__without_skill", 0.5, None, 1000)
            put("eval-1", "m3__with_skill", 0.5, None, 1000)
            out = evals.benchmark(d)
        self.assertEqual(out["per_model"]["m1"]["delta"],
                         {"pass_rate": 0.8, "tokens": 1200.0, "time_seconds": 0.0, "repo_pass_rate": 1.0})
        self.assertEqual(out["per_model"]["m2"]["delta"]["pass_rate"], 0.0)
        self.assertNotIn("repo_pass_rate", out["per_model"]["m2"]["delta"])
        self.assertNotIn("m3", out["per_model"])
        self.assertNotIn("delta", out["run_summary"])
        self.assertEqual(out["run_summary"]["m1__with_skill"]["repo_pass_rate"]["mean"], 1.0)


if __name__ == "__main__":
    unittest.main()
