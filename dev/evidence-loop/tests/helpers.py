"""端到端测试的公共夹具：在临时目录里搭 git 仓库与循环工作区，以子进程方式调用裁判。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# 测试与评测用例不随技能发布：技能在 skills/evidence-loop，测试在 dev/evidence-loop/tests；
# 需要测别处的技能副本时用 EVLOOP_SKILL_DIR 指过去
SKILL = os.path.realpath(os.environ.get("EVLOOP_SKILL_DIR")
                         or os.path.join(HERE, "..", "..", "..", "skills", "evidence-loop"))
EVALS_DIR = os.path.realpath(os.path.join(HERE, "..", "evals"))
SCRIPTS = os.path.join(SKILL, "scripts")
JUDGE = os.path.join(SCRIPTS, "evloop.py")
RENDER = os.path.join(SCRIPTS, "evloop_render.py")
sys.path.insert(0, SCRIPTS)

# Fixture repos must not inherit the developer's global hooks: a commit-msg hook that demands a trailer
# rejects `git commit -m base`. Set on the test process as well, so code that runs git in-process with the
# inherited environment is covered too.
os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0=os.devnull)

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_NOSYSTEM="1",
           LC_ALL="C.UTF-8")
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    ENV.pop(_k, None)

# 基准脚本：读取 src/impl.py 中的 N 作为分数
BENCH = 'import sys; sys.path.insert(0, "src"); import impl; print("latency=" + str(impl.N))\n'


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, env=ENV, check=False)


def git(cwd, *args):
    r = sh(cwd, "git", "-c", "commit.gpgsign=false", *args)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


class Harness(unittest.TestCase):
    scenario = "optimization"
    opt_args = ("--score-regex", r"latency=([0-9.]+)", "--unit", "ms", "--direction", "lower",
                "--delta-pct", "5", "--target", "150")
    budget = ("--budget-minutes", "10")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.root, "repo")
        self.wt = os.path.join(self.root, "wt")
        self.home = os.path.join(self.repo, ".evloop", "runs", "task")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        write(self.repo, ".gitignore", "__pycache__/\n")
        self.seed()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        self.route_n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        write(self.repo, "src/impl.py", "N=200\n")
        write(self.repo, "bench/run.py", BENCH)

    # ------------------------------------------------------------ 调用
    def run_j(self, *args, home=None):
        return sh(self.root, sys.executable, JUDGE, "--home", home or self.home, *args)

    def init(self, *extra, scenario=None, editable="src", frozen="bench", test_cmd="python3 bench/run.py"):
        scen = scenario or self.scenario
        args = ["init", "--repo", self.repo, "--scenario", scen, "--editable", editable]
        if frozen is not None:
            args += ["--frozen", frozen]
        if test_cmd is not None:
            args += ["--test-cmd", test_cmd]
        if scen == "optimization":
            args += [*self.budget, *self.opt_args]
        return self.run_j(*args, *extra)

    def add_worktree(self, path=None, branch="evloop/task"):
        git(self.repo, "worktree", "add", "-q", "-b", branch, path or self.wt, "HEAD")

    def start(self, *extra):
        self.add_worktree()
        r = self.run_j("start", "--worktree", self.wt, *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def ready(self, *extra):
        r = self.init(*extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()

    def commit(self, files, msg="attempt", root=None):
        root = root or self.wt
        for rel, text in files.items():
            if text is None:
                os.remove(os.path.join(root, rel))
            else:
                write(root, rel, text)
        git(root, "add", "-A")
        git(root, "commit", "-qm", msg)
        return git(root, "rev-parse", "HEAD")

    def attempt(self, files=None, *extra, route=None, note=""):
        if files:
            self.commit(files)
        args = ["attempt", "--note", note]
        if self.scenario == "optimization":
            self.route_n += 1
            args += ["--route", route or f"r{self.route_n}"]
        r = self.run_j(*args, *extra)
        rec = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
        return r.returncode, rec

    # ------------------------------------------------------------ 读取
    def contract(self):
        with open(os.path.join(self.home, "contract.json"), encoding="utf-8") as f:
            return json.load(f)

    def records(self):
        with open(os.path.join(self.home, "attempts.jsonl"), encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def status(self):
        r = self.run_j("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def head(self):
        return git(self.wt, "rev-parse", "HEAD")

    def clean(self):
        return git(self.wt, "status", "--porcelain") == ""

    def json_out(self, r):
        self.assertTrue(r.stdout.strip(), r.stderr)
        return json.loads(r.stdout)

    def review(self):
        """verify → report → approve，全部要求成功。"""
        for cmd in (["verify"], ["report"], ["approve", "--note", "ok"]):
            r = self.run_j(*cmd)
            self.assertEqual(r.returncode, 0, f"{cmd}: {r.stderr}{r.stdout}")
