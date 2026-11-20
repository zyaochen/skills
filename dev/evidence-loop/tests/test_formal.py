"""形式化设计验证：用假的检查器（按 -tool 格式打印消息）覆盖解析、门槛、复用、验证与交付包。"""
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile

from helpers import Harness, write
from evloop import formal as fm

TEST = "import sys; sys.path.insert(0, 'src'); import impl; raise SystemExit(0 if impl.add(2, 2) == 4 else 1)\n"

# 假检查器：读配置里的不变式 / 性质；模型里写 "\* BROKEN 名字" 就为它打印反例，
# "\* ZERO" 统计 0 个状态，"\* BADSEV" 让完成消息带错误级别，"\* PARSEFAIL" 模拟语法错误。
CHECKER = r'''import os, sys
args = sys.argv[1:]
assert "-tool" in args and "-noGenerateSpecTE" in args
cfg = args[args.index("-config") + 1]
meta = args[args.index("-metadir") + 1]
model = args[-1]
os.makedirs(os.path.dirname(meta), exist_ok=True)
with open(os.path.join(os.path.dirname(meta), "calls.log"), "a") as f:
    f.write(os.path.basename(meta) + "\n")
text = open(model).read()
names = [ln.split()[1] for ln in open(cfg) if ln.startswith(("INVARIANT", "PROPERTY"))]
def msg(code, sev, body):
    print("@!@!@STARTMSG %d:%d @!@!@\n%s\n@!@!@ENDMSG %d @!@!@" % (code, sev, body, code))
msg(2262, 0, "TLC2 fake")
msg(2401, 3, "Please run the Java VM with a larger heap")
if "\\* PARSEFAIL" in text:
    print("Parse error in module")
    sys.exit(150)
for n in names:
    if "\\* BROKEN " + n in text:
        msg(2110, 1, "Invariant %s is violated." % n)
        msg(2121, 1, "The behavior up to this point is:")
        msg(2217, 4, "1: <Initial predicate>\n/\\ stored = 0")
        msg(2217, 4, "2: <Write line 9>\n/\\ stored = 2")
        sys.exit(12)
states = 0 if "\\* ZERO" in text else 42
msg(2193, 1 if "\\* BADSEV" in text else 0, "Model checking completed. No error has been found.")
msg(2199, 0, "%d states generated, %d distinct states found, 0 states left on queue." % (states * 2, states))
'''

MODEL = """---- MODULE Lease ----
EXTENDS Naturals
CONSTANTS Workers, MaxToken
VARIABLES token, stored
{marks}
Init == token = 0 /\\ stored = 0
Acquire == token < MaxToken /\\ token' = token + 1 /\\ UNCHANGED stored
Expire == UNCHANGED <<token, stored>>
Write == stored' = token /\\ UNCHANGED token
Next == Acquire \\/ Expire \\/ Write
Monotonic == stored <= token
SingleBeliever == TRUE
====
"""

DESIGN = "# 租约写入\n\nR1：存储里的 token 不超过已发放的最大 token。故障：Expire（租约过期后旧持有者迟到写入）。\n"

CMD = sys.executable + " {checker} -tool -noGenerateSpecTE -metadir {metadir} -workers 1 -config {cfg} {model}"


def spec(**over):
    base = {
        "design": "specs/design.md",
        "screening": {"triggers": ["ownership", "retry_timeout"], "rationale": "租约过期后旧持有者可能迟到写入"},
        "unmodeled": ["时钟漂移与网络分区"],
        "assumptions": ["存储按 token 比较是原子的"],
        "faults": ["Expire"],
        "cases": [
            {"id": "fence", "kind": "contract", "model": "models/Lease.tla", "init": "Init", "next": "Next",
             "constants": {"Workers": '{"a", "b"}', "MaxToken": 3}, "invariants": ["Monotonic"]},
            {"id": "single", "kind": "probe", "model": "models/Lease.tla", "init": "Init", "next": "Next",
             "constants": {"Workers": '{"a", "b"}', "MaxToken": 3}, "invariants": ["SingleBeliever"],
             "question": "同一时刻是否只有一个执行者自认为持有租约？"}],
        "coverage": [{"id": "R1", "requirement": "存储里的 token 不超过已发放的最大 token",
                      "properties": ["Monotonic"], "code": ["src/impl.py"], "tests": ["tests/t.py"]}]}
    base.update(over)
    return base


def model(*marks):
    return MODEL.format(marks="\n".join("\\* " + m for m in marks))


def msg(code, sev, body):
    return f"@!@!@STARTMSG {code}:{sev} @!@!@\n{body}\n@!@!@ENDMSG {code} @!@!@\n"


class ParseTests(unittest.TestCase):
    def test_verified_needs_success_message_and_states(self):
        out = msg(2401, 3, "heap") + msg(2193, 0, "done") + msg(2199, 0, "84 states generated, 42 distinct states found")
        self.assertEqual(fm.parse(out, 0), {"result": "verified", "states": 42})

    def test_counterexample_with_trace(self):
        out = (msg(2110, 1, "Invariant Monotonic is violated.") + msg(2121, 1, "The behavior up to this point is:")
               + msg(2217, 4, "1: <Initial predicate>\n/\\ x = 0") + msg(2217, 4, "2: <Step>\n/\\ x = 1"))
        r = fm.parse(out, 12)
        self.assertEqual(r["result"], "counterexample")
        self.assertEqual(r["violation"], "Invariant Monotonic is violated.")
        self.assertIn("/\\ x = 1", r["trace"])

    def test_deadlock_exit_without_errors_is_counterexample(self):
        self.assertEqual(fm.parse(msg(2114, 1, "Deadlock reached."), 11)["result"], "counterexample")

    def test_zero_states_is_error(self):
        out = msg(2193, 0, "done") + msg(2199, 0, "0 distinct states found")
        r = fm.parse(out, 0)
        self.assertEqual(r["result"], "error")
        self.assertIn("没有统计到", r["reason"])

    def test_success_code_with_nonzero_severity_is_not_verified(self):
        out = msg(2193, 1, "done") + msg(2199, 0, "5 distinct states found")
        self.assertEqual(fm.parse(out, 0)["result"], "error")

    def test_parse_failure_and_timeout(self):
        self.assertEqual(fm.parse("Parse error", 150)["result"], "error")
        self.assertEqual(fm.parse(msg(2229, 1, "undefined"), 151)["result"], "error")
        self.assertEqual(fm.parse("", 0, timed_out=True)["reason"], "检查器超时")

    def test_missing_tool_output(self):
        self.assertIn("-tool", fm.parse("Model checking completed. 3 distinct states found", 0)["reason"])


class SpecTests(unittest.TestCase):
    def test_cfg_is_deterministic(self):
        case = fm.check_spec(spec())["cases"][0]
        text = fm.cfg_text(case)
        self.assertEqual(text, fm.cfg_text(dict(case)))
        self.assertEqual(text.splitlines(), ["INIT Init", "NEXT Next", "CONSTANT MaxToken = 3",
                                             'CONSTANT Workers = {"a", "b"}', "INVARIANT Monotonic",
                                             "CHECK_DEADLOCK FALSE"])

    def test_specification_form(self):
        s = spec()
        s["cases"][0] = dict(s["cases"][0], spec="Spec", init=None, next=None, properties=["Live"])
        s["coverage"][0]["properties"] = ["Monotonic", "Live"]
        case = fm.check_spec(s)["cases"][0]
        self.assertTrue(fm.cfg_text(case).startswith("SPECIFICATION Spec\n"))
        self.assertIn("PROPERTY Live", fm.cfg_text(case))

    def test_coverage_is_checked_both_ways(self):
        s = spec()
        s["coverage"][0]["properties"] = ["SingleBeliever"]
        with self.assertRaisesRegex(ValueError, "没有任何约定案例检查"):
            fm.check_spec(s)
        s = spec()
        s["cases"][0]["invariants"] = ["Monotonic", "Extra"]
        with self.assertRaisesRegex(ValueError, "没有映射到任何需求"):
            fm.check_spec(s)

    def test_rejects_bad_specs(self):
        bad = [spec(cases=[dict(spec()["cases"][1])]), spec(unmodeled=[]), spec(screening={"triggers": ["vibes"],
               "rationale": "x"}), spec(faults=["not valid"])]
        s = spec()
        s["cases"][0]["spec"] = "Spec"
        bad.append(s)
        s = spec()
        s["cases"][1]["id"] = "fence"
        bad.append(s)
        for b in bad:
            with self.assertRaises(ValueError):
                fm.check_spec(b)

    def test_model_cmd_rules(self):
        fm.check_model_cmd(CMD)
        for cmd, word in ((CMD + " -continue", "-continue"), (CMD.replace(" {metadir}", " x"), "{metadir}"),
                          (CMD.replace(" -tool", ""), "-tool"), (CMD + " {other}", "占位符"),
                          (CMD.replace("-workers 1", "-simulate"), "-simulate")):
            with self.assertRaises(Exception) as ctx:
                fm.check_model_cmd(cmd)
            self.assertIn(word, str(ctx.exception))

    def test_static_problems(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            s = fm.check_spec(spec())
            write(root, "specs/design.md", DESIGN)
            write(root, "models/Lease.tla", model())
            self.assertEqual(fm.static_problems(s, root), [])
            write(root, "models/Lease.tla", model().replace("MODULE Lease", "MODULE Other"))
            self.assertIn("模块名", fm.static_problems(s, root)[0])
            write(root, "models/Lease.tla", model().replace("Monotonic ==", "Mono =="))
            self.assertIn("Monotonic", fm.static_problems(s, root)[0])
            write(root, "models/Lease.tla", model().replace(" \\/ Expire", ""))
            self.assertIn("没有出现在任何动作组合里", fm.static_problems(s, root)[0])
            write(root, "models/Lease.tla", model())
            write(root, "specs/design.md", "# 空\n")
            self.assertIn("R1", fm.static_problems(s, root)[0])


class FormalLoopTests(Harness):
    scenario = "bugfix"

    def seed(self):
        write(self.repo, "src/impl.py", "def add(a, b):\n    return a - b\n")
        write(self.repo, "tests/t.py", TEST)
        write(self.repo, "specs/design.md", DESIGN)
        write(self.repo, "specs/checks.json", json.dumps(spec(), ensure_ascii=False, indent=1))
        write(self.repo, "models/Lease.tla", model(*self.marks()))
        self.checker = os.path.join(self.root, "checker.py")
        write(self.root, "checker.py", CHECKER)

    def marks(self):
        return []

    def sha(self):
        with open(self.checker, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def finit(self, *extra, editable=("src",), scenario="bugfix", sha=None, formal_spec="specs/checks.json"):
        args = ["init", "--repo", self.repo, "--scenario", scenario, "--editable", *editable,
                "--frozen", "tests", "--test-cmd", "python3 tests/t.py",
                "--formal-spec", formal_spec, "--model-cmd", CMD, "--checker-path", self.checker,
                "--checker-sha256", sha or self.sha()]
        return self.run_j(*args, *extra)

    def fready(self, **kw):
        r = self.finit(**kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()

    def calls(self):
        path = os.path.join(self.home, "formal", "meta", "calls.log")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return f.read().split()

    FIX = {"src/impl.py": "def add(a, b):\n    return a + b\n"}

    # ------------------------------------------------------------ init
    def test_flags_must_come_together_and_not_in_documents(self):
        r = self.init("--formal-spec", "specs/checks.json", frozen="tests", test_cmd="python3 tests/t.py")
        self.assertEqual(r.returncode, 3)
        self.assertIn("同时给出", r.stderr)
        r = self.finit(scenario="research")
        self.assertEqual(r.returncode, 3)
        self.assertIn("研究与文档", r.stderr)

    def test_checker_hash_mismatch_blocks_init(self):
        r = self.finit(sha="0" * 64)
        self.assertEqual(r.returncode, 3)
        self.assertIn("哈希不符", r.stderr)
        r = self.finit(sha="abc")
        self.assertEqual(r.returncode, 3)

    def test_spec_must_not_be_editable(self):
        r = self.finit(editable=("src", "specs"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("不能位于 --editable 之内", r.stderr)

    def test_implement_mode_freezes_models(self):
        self.fready()
        c = self.contract()
        self.assertEqual(c["formal"]["mode"], "implement")
        for rel in ("specs/checks.json", "specs/design.md", "models/Lease.tla"):
            self.assertIn(rel, c["frozen"])
        self.assertTrue(c["baseline"]["formal"]["ok"])
        self.assertEqual(c["baseline"]["formal"]["cases"]["fence"]["states"], 42)
        code, rec = self.attempt({"models/Lease.tla": model("BROKEN Monotonic")})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))

    def test_fix_reuses_baseline_result_then_verifies_and_reports(self):
        self.fready()
        before = len(self.calls())
        code, rec = self.attempt(self.FIX)
        self.assertEqual((code, rec["verdict"]), (0, "accepted"), rec)
        self.assertEqual(rec["formal"]["reused_from"], "baseline")
        self.assertEqual(len(self.calls()), before, "同摘要不应重跑检查器")
        s = self.status()
        self.assertTrue(s["goal_met"])
        self.assertEqual(s["formal_open"], [])
        self.assertEqual(s["formal"]["findings"], [])
        r = self.run_j("verify")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(self.json_out(r)["formal"]["ok"])
        self.assertGreater(len(self.calls()), before, "verify 必须真正重跑")
        r = self.run_j("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.home, "handoff.html"), encoding="utf-8") as f:
            html = f.read()
        for word in (fm.CONCLUSION, "最终验证的重跑", "需求 → 性质 → 代码", "时钟漂移与网络分区", "R1"):
            self.assertIn(word, html)
        resume = self.json_out(self.run_j("resume"))
        self.assertEqual(resume["contract"]["formal"]["mode"], "implement")
        doctor = self.json_out(self.run_j("doctor"))
        self.assertTrue(next(x for x in doctor["checks"] if x["name"] == "formal_checker")["ok"])

    def test_checker_swapped_after_init_is_invalid(self):
        self.fready()
        write(self.root, "checker.py", CHECKER + "\n# changed\n")
        code, rec = self.attempt(self.FIX)
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))
        self.assertIn("哈希不符", rec["reason"])
        doctor = self.run_j("doctor")
        self.assertEqual(doctor.returncode, 1)


class FormalBaselineCounterexampleTests(FormalLoopTests):
    def marks(self):
        return ["BROKEN Monotonic", "BROKEN SingleBeliever"]

    def test_implement_mode_refuses_broken_design(self):
        r = self.finit()
        self.assertEqual(r.returncode, 3)
        self.assertIn("在基线上有反例", r.stderr)

    # 父类里依赖干净基线的用例在这里不适用
    test_implement_mode_freezes_models = None
    test_fix_reuses_baseline_result_then_verifies_and_reports = None
    test_checker_swapped_after_init_is_invalid = None

    def test_design_mode_counterexample_drives_revision(self):
        self.fready(editable=("src", "models"))
        c = self.contract()
        self.assertEqual(c["formal"]["mode"], "design")
        self.assertNotIn("models/Lease.tla", c["frozen"])
        self.assertEqual(c["baseline"]["formal"]["contract_open"], ["fence"])
        s = self.status()
        self.assertEqual(s["formal_open"], ["fence"])
        self.assertFalse(s["goal_met"])
        self.assertIn("建模缺陷", s["next"])
        # 代码修好了，但设计仍有反例：保留为 failing，不算完成
        code, rec = self.attempt(self.FIX)
        self.assertEqual((code, rec["verdict"]), (1, "failing"))
        self.assertIn("fence", rec["reason"])
        self.assertTrue(rec["formal"]["reused_from"] in ("baseline",))
        # 修订模型：约定 verified，探针反例只是待人裁决的发现
        code, rec = self.attempt({"models/Lease.tla": model("BROKEN SingleBeliever")})
        self.assertEqual((code, rec["verdict"]), (0, "accepted"), rec)
        self.assertNotIn("reused_from", rec["formal"])
        self.assertEqual(rec["formal"]["findings"], ["single"])
        s = self.status()
        self.assertTrue(s["goal_met"])
        self.assertEqual(s["formal"]["findings"], ["single"])
        # 回退已 verified 的约定：拒绝并回滚
        code, rec = self.attempt({"models/Lease.tla": model("BROKEN Monotonic")})
        self.assertEqual((code, rec["verdict"]), (1, "rejected"))
        self.assertIn("回退", rec["reason"])
        self.assertTrue(self.clean())
        self.review()
        with open(os.path.join(self.home, "handoff.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("探针发现（待人裁决）", html)
        self.assertIn("stored = 2", html)
        self.assertIn("同一时刻是否只有一个执行者", html)

    def test_checker_errors_are_invalid(self):
        self.fready(editable=("src", "models"))
        for mark in ("ZERO", "BADSEV", "PARSEFAIL"):
            code, rec = self.attempt({"models/Lease.tla": model(mark)})
            self.assertEqual((code, rec["verdict"]), (2, "invalid"), mark)
            self.assertEqual(rec["stage"], "formal")
        code, rec = self.attempt({"models/Lease.tla": model().replace(" \\/ Expire", "")})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))
        self.assertIn("Expire", rec["reason"])


# 假 java：-version 打印版本；否则当作 TLC 运行（复用上面的假检查器逻辑）。
FAKE_JAVA = r"""#!{python}
import os, sys
if sys.argv[1:] == ["-version"]:
    sys.stderr.write('openjdk version "{version}" 2026-10-20\n')
    sys.exit(0)
args = sys.argv[1:]
with open(args[-1]) as f:
    if "\\* MISSINGMOD" in f.read():
        print("Cannot find source file for module Foo imported in module Lease.")
        sys.exit(150)
""" + CHECKER.split("\n", 2)[2]


def jar(path, manifest, entries):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", manifest)
        for name, data in entries.items():
            z.writestr(name, data)


class JarCheckerTests(Harness):
    """检查器是真正的 jar：init 预检 Java 版本与清单旁路文件，doctor 复查，出错时给出可操作的诊断。"""
    scenario = "bugfix"
    version = "17.0.21"
    extends = "Naturals"

    def seed(self):
        write(self.repo, "src/impl.py", "def add(a, b):\n    return a - b\n")
        write(self.repo, "tests/t.py", TEST)
        write(self.repo, "specs/design.md", DESIGN)
        write(self.repo, "specs/checks.json", json.dumps(spec(), ensure_ascii=False, indent=1))
        write(self.repo, "models/Lease.tla", model().replace("EXTENDS Naturals", "EXTENDS " + self.extends))
        self.checker = os.path.join(self.root, "tla2tools.jar")
        jar(self.checker, "Manifest-Version: 1.0\r\nMain-class: tlc2.TLC\r\nClass-Path: deps.jar\r\n",
            {"tlc2/TLC.class": b"\xca\xfe\xba\xbe\x00\x00\x00\x37" + b"\x00" * 8,
             "tla2sany/StandardModules/Naturals.tla": "x"})
        self.java = os.path.join(self.root, "jdk", "java")
        self.set_java(self.version)

    def set_java(self, version):
        os.makedirs(os.path.dirname(self.java), exist_ok=True)
        with open(self.java, "w", encoding="utf-8") as f:
            f.write(FAKE_JAVA.replace("{python}", sys.executable).replace("{version}", version))
        os.chmod(self.java, os.stat(self.java).st_mode | stat.S_IXUSR)

    def finit(self, editable=("src",)):
        with open(self.checker, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        cmd = (self.java + " -cp {checker} tlc2.TLC -tool -noGenerateSpecTE -metadir {metadir} -workers 1 "
               "-config {cfg} {model}")
        return self.run_j("init", "--repo", self.repo, "--scenario", "bugfix", "--editable", *editable,
                          "--frozen", "tests", "--test-cmd", "python3 tests/t.py",
                          "--formal-spec", "specs/checks.json", "--model-cmd", cmd,
                          "--checker-path", self.checker, "--checker-sha256", digest)

    def doctor_check(self, name):
        out = json.loads(self.run_j("doctor").stdout)
        return next(x for x in out["checks"] if x["name"] == name)

    def test_runtime_recorded_doctor_and_report(self):
        r = self.finit(editable=("src", "models"))
        self.assertEqual(r.returncode, 0, r.stderr)
        rt = self.contract()["formal"]["runtime"]
        self.assertEqual((rt["required_java"], rt["java_major"]), (11, 17))
        self.start()
        check = self.doctor_check("formal_runtime")
        self.assertTrue(check["ok"], check)
        self.assertIn("17.0.21", check["detail"])
        self.set_java("1.8.0_392")
        check = self.doctor_check("formal_runtime")
        self.assertFalse(check["ok"])
        self.assertIn("Java 8", check["detail"])
        self.set_java(self.version)
        code, rec = self.attempt({"models/Lease.tla": model("MISSINGMOD")})
        self.assertEqual((code, rec["verdict"]), (2, "invalid"))
        self.assertIn("社区模块", rec["reason"])
        code, rec = self.attempt(FormalLoopTests.FIX)
        self.assertEqual((code, rec["verdict"]), (0, "accepted"), rec)
        self.review()
        with open(os.path.join(self.home, "handoff.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Java 运行时（init 时为", html)
        self.assertIn("清单之外依赖的文件不在哈希之内", html)


class OldJavaTests(JarCheckerTests):
    version = "1.8.0_392"

    def test_runtime_recorded_doctor_and_report(self):
        r = self.finit()
        self.assertEqual(r.returncode, 3)
        self.assertIn("至少需要 Java 11", r.stderr)


class CommunityModuleTests(JarCheckerTests):
    extends = "Naturals, SequencesExt"

    def test_runtime_recorded_doctor_and_report(self):
        r = self.finit()
        self.assertEqual(r.returncode, 3)
        self.assertIn("SequencesExt", r.stderr)
        self.assertIn("deps.jar", r.stderr)
        self.assertIn("evloop_tlc.py fetch", r.stderr)
        jar(os.path.join(self.root, "deps.jar"), "Manifest-Version: 1.0\r\n", {"SequencesExt.tla": "x"})
        r = self.finit()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.start()
        self.assertTrue(self.doctor_check("formal_runtime")["ok"])
        os.remove(os.path.join(self.root, "deps.jar"))
        check = self.doctor_check("formal_runtime")
        self.assertFalse(check["ok"])
        self.assertIn("SequencesExt", check["detail"])


class LocaleTests(unittest.TestCase):
    def test_case_runs_get_utf8_locale_for_non_ascii_paths(self):
        class Home:
            def __init__(self, root):
                self.root = root

            def file(self, name):
                return os.path.join(self.root, name)

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "仓库 目录")
            write(root, "models/Lease.tla", model())
            c = {"formal": {"model_cmd": CMD, "checker_path": os.path.join(tmp, "c.py")}}
            case = fm.check_spec(spec())["cases"][0]
            seen = {}

            class R:
                output, code, timed_out = "", 1, False

            def runner(cmd, raw, env=None):
                seen["env"] = env
                return R(), "raw/" + raw

            old = dict(os.environ)
            try:
                os.environ["LC_ALL"] = "C"
                res = fm._run_case(c, Home(root), root, case, "t", runner)
            finally:
                os.environ.clear()
                os.environ.update(old)
            expect = {"LC_ALL": "C.UTF-8"} if sys.platform.startswith("linux") else None
            self.assertEqual(seen["env"], expect)
            self.assertEqual(res["result"], "error")


if __name__ == "__main__":
    unittest.main()
