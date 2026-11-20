"""检查器准备：jar 检视、Java 探测、区域设置、失败诊断、确定性合并、自检流程（用假 java，不需要真 JDK）。

设置 EVLOOP_TLC_CHECKER=<tla2tools-full.jar> 与 EVLOOP_TLC_JAVA=<java> 时，额外用真实 TLC 跑一遍自检。
"""
import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import helpers  # noqa: F401 —— 把 scripts/ 加入 sys.path
from evloop import formal as fm
from evloop import tlc
from evloop.util import EvloopError


def cls(major):
    return b"\xca\xfe\xba\xbe\x00\x00" + major.to_bytes(2, "big") + b"\x00" * 8


def make_jar(path, manifest="Manifest-Version: 1.0\r\n", entries=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", manifest)
        for name, data in (entries or {}).items():
            z.writestr(name, data)
    return path


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# 假 java：-version 打印版本；否则按自检模型的内容模拟 TLC 的 -tool 输出。
FAKE_JAVA = r'''#!{python}
import os, sys
args = sys.argv[1:]
if args == ["-version"]:
    sys.stderr.write('openjdk version "{version}" 2026-10-20\nOpenJDK Runtime Environment\n')
    sys.exit(0)
assert "-tool" in args and "-noGenerateSpecTE" in args, args
checker, model, cfg = args[args.index("-cp") + 1], args[-1], args[args.index("-config") + 1]
for p in (checker, model, cfg):
    assert os.path.exists(p), p
def msg(code, sev, body):
    print("@!@!@STARTMSG %d:%d @!@!@\n%s\n@!@!@ENDMSG %d @!@!@" % (code, sev, body, code))
text = open(model, encoding="utf-8").read()
msg(2262, 0, "TLC2 fake")
if "SequencesExt" in text and os.environ.get("FAKE_NO_EXT"):
    msg(1000, 1, "Cannot find source file for module SequencesExt imported in module EvSelfExt.")
    msg(3002, 1, "Parsing or semantic analysis failed.")
    sys.exit(150)
if "Inv == x < 2" in text:
    msg(2110, 1, "Invariant Inv is violated.")
    msg(2121, 1, "The behavior up to this point is:")
    msg(2217, 4, "1: <Initial predicate>\nx = 0")
    msg(2217, 4, "2: <Next>\nx = 2")
    sys.exit(12)
msg(2193, 0, "Model checking completed. No error has been found.")
msg(2199, 0, "8 states generated, 4 distinct states found, 0 states left on queue.")
'''


def fake_java(directory, version="17.0.21"):
    path = os.path.join(directory, "java")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_JAVA.replace("{python}", sys.executable).replace("{version}", version))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._t.name)

    def tearDown(self):
        self._t.cleanup()


class InspectTests(Tmp):
    def test_manifest_continuation_lines(self):
        jar = make_jar(os.path.join(self.dir, "a.jar"),
                       "Manifest-Version: 1.0\r\nClass-Path: CommunityModules-deps.jar Commu\r\n nityModules.jar\r\n")
        with zipfile.ZipFile(jar) as z:
            self.assertEqual(tlc.manifest(z)["Class-Path"], "CommunityModules-deps.jar CommunityModules.jar")

    def test_required_java_ignores_versioned_and_module_info(self):
        jar = make_jar(os.path.join(self.dir, "a.jar"), entries={
            "a/A.class": cls(52), "b/B.class": cls(55), "module-info.class": cls(61),
            "META-INF/versions/17/c/C.class": cls(61), "x.txt": b"x"})
        with zipfile.ZipFile(jar) as z:
            self.assertEqual(tlc.required_java(z), 11)
        empty = make_jar(os.path.join(self.dir, "e.jar"))
        with zipfile.ZipFile(empty) as z:
            self.assertIsNone(tlc.required_java(z))

    def test_inspect_reports_missing_and_present_companions(self):
        jar = make_jar(os.path.join(self.dir, "tla2tools.jar"),
                       "Manifest-Version: 1.0\r\nMain-class: tlc2.TLC\r\nX-Git-Tag: v1.8.0\r\n"
                       "Class-Path: deps.jar\r\n",
                       {"tla2sany/StandardModules/Naturals.tla": "x", "tla2sany/StandardModules/TLC.tla": "x",
                        "tlc2/TLC.class": cls(55)})
        info = tlc.inspect(jar)
        self.assertEqual((info["main"], info["version"], info["required_java"]), ("tlc2.TLC", "v1.8.0", 11))
        self.assertEqual(info["companions"], {"deps.jar": {"present": False}})
        self.assertEqual(info["standard_modules"], ["Naturals", "TLC"])
        self.assertEqual(info["community_modules"], [])
        make_jar(os.path.join(self.dir, "deps.jar"), entries={"SequencesExt.tla": "x", "Functions.tla": "x"})
        info = tlc.inspect(jar)
        self.assertTrue(info["companions"]["deps.jar"]["present"])
        self.assertEqual(info["community_modules"], ["Functions", "SequencesExt"])
        self.assertIsNone(tlc.inspect(os.path.join(self.dir, "nope.jar")))
        helpers.write(self.dir, "plain.py", "print(1)\n")
        self.assertIsNone(tlc.inspect(os.path.join(self.dir, "plain.py")))

    def test_imported_modules_skip_comments(self):
        text = ("---- MODULE M ----\nEXTENDS Naturals, Sequences,\n        SequencesExt\n"
                "(* EXTENDS Hidden *)\n\\* EXTENDS AlsoHidden\nI == INSTANCE Other\n====\n")
        self.assertEqual(tlc.imported_modules(text), {"Naturals", "Sequences", "SequencesExt", "Other"})

    def test_missing_modules_counts_local_modules(self):
        helpers.write(self.dir, "m/M.tla", "---- MODULE M ----\nEXTENDS Naturals, Helper, SequencesExt\n====\n")
        helpers.write(self.dir, "m/Helper.tla", "---- MODULE Helper ----\n====\n")
        info = {"standard_modules": ["Naturals"], "community_modules": []}
        path = os.path.join(self.dir, "m", "M.tla")
        self.assertEqual(tlc.missing_modules([path], info), {path: ["SequencesExt"]})
        info["community_modules"] = ["SequencesExt"]
        self.assertEqual(tlc.missing_modules([path], info), {})
        self.assertEqual(tlc.missing_modules([path], None), {})


class BundleTests(Tmp):
    def jars(self):
        tla = make_jar(os.path.join(self.dir, "tla2tools.jar"),
                       "Manifest-Version: 1.0\r\nMain-class: tlc2.TLC\r\nClass-Path: CommunityModules-deps.jar Co\r\n"
                       " mmunityModules.jar\r\n\r\n",
                       {"tlc2/TLC.class": cls(55), "shared/Dup.class": b"from-tla",
                        "tla2sany/StandardModules/Naturals.tla": "n", "tlc2/": b""})
        deps = make_jar(os.path.join(self.dir, "CommunityModules-deps.jar"),
                        "Manifest-Version: 1.0\r\nX-Other: 1\r\n",
                        {"SequencesExt.tla": "s", "shared/Dup.class": b"from-deps", "org/x/Y.class": cls(52)})
        return tla, deps

    def test_bundle_is_deterministic_and_self_contained(self):
        tla, deps = self.jars()
        a = tlc.bundle(tla, deps, os.path.join(self.dir, "a.jar"))
        os.utime(tla, (1, 1))
        b = tlc.bundle(tla, deps, os.path.join(self.dir, "b.jar"))
        self.assertEqual(sha(a), sha(b))
        with zipfile.ZipFile(a) as z:
            names = z.namelist()
            self.assertEqual(names[0], "META-INF/MANIFEST.MF")
            self.assertEqual(names[1:], sorted(names[1:]))
            self.assertEqual(z.read("shared/Dup.class"), b"from-tla", "同名条目必须以 tla2tools.jar 为准")
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED and i.date_time == tlc.ZIP_EPOCH
                                for i in z.infolist()))
            man = tlc.manifest(z)
        self.assertNotIn("Class-Path", man)
        self.assertEqual(man["Main-class"], "tlc2.TLC")
        self.assertEqual(man["X-Evloop-Bundle"], tlc.BUNDLE_TAG)
        info = tlc.inspect(a)
        self.assertEqual((info["companions"], info["community_modules"], info["required_java"]),
                         ({}, ["SequencesExt"], 11))
        self.assertFalse(os.path.exists(a + ".part"))

    def test_build_pins_inputs_and_output(self):
        tla, deps = self.jars()
        src = self.dir
        out_dir = os.path.join(self.dir, "out")
        pins = {"tla2tools.jar": {"url": "", "size": 1, "sha256": sha(tla)},
                "CommunityModules-deps.jar": {"url": "", "size": 1, "sha256": sha(deps)}}
        expected = sha(tlc.bundle(tla, deps, os.path.join(self.dir, "ref.jar")))
        with mock.patch.dict(tlc.ARTIFACTS, pins), mock.patch.object(tlc, "BUNDLE_SHA256", expected):
            out = tlc.build(out_dir, src)
            self.assertEqual(sha(out), expected)
            self.assertEqual(tlc.build(out_dir, src), out)  # 已存在且哈希对：直接复用
        with mock.patch.dict(tlc.ARTIFACTS, pins), mock.patch.object(tlc, "BUNDLE_SHA256", "0" * 64):
            with self.assertRaises(EvloopError) as e:
                tlc.build(os.path.join(self.dir, "out2"), src)
            self.assertIn("合并后", str(e.exception))
        bad = dict(pins, **{"tla2tools.jar": {"url": "", "size": 1, "sha256": "1" * 64}})
        with mock.patch.dict(tlc.ARTIFACTS, bad):
            with self.assertRaises(EvloopError) as e:
                tlc.build(os.path.join(self.dir, "out3"), src)
            self.assertIn("哈希不符", str(e.exception))
            self.assertEqual(e.exception.code, tlc.INVALID)

    def test_pins_look_sane(self):
        for name, pin in tlc.ARTIFACTS.items():
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$", name)
            self.assertTrue(pin["url"].startswith("https://") and pin["url"].endswith("/" + name))
        self.assertRegex(tlc.BUNDLE_SHA256, r"^[0-9a-f]{64}$")


class JavaTests(Tmp):
    def test_parse_java_version(self):
        cases = {'java version "1.8.0_392"': 8, 'openjdk version "11.0.32.1" 2026-08-18': 11,
                 'openjdk version "17" 2021-09-14': 17, 'openjdk version "21-ea"': 21, "garbage": None, None: None}
        for text, want in cases.items():
            self.assertEqual(tlc.parse_java_version(text), want, text)

    def test_pick_java_enforces_minimum(self):
        old = fake_java(os.path.join(self.dir), "1.8.0_392")
        java, major, why = tlc.pick_java(11, old)
        self.assertIsNone(java)
        self.assertIn("Java 8", why)
        self.assertIn("--jre", why)
        new_dir = os.path.join(self.dir, "new")
        os.makedirs(new_dir)
        new = fake_java(new_dir, "17.0.21")
        java, major, why = tlc.pick_java(11, new)
        self.assertEqual((java, major), (new, 17))
        java, major, why = tlc.pick_java(11, os.path.join(self.dir, "missing-java"))
        self.assertIsNone(java)

    def test_find_java_uses_downloaded_jre(self):
        bin_dir = os.path.join(self.dir, "jre", "jdk-17-jre", "bin")
        os.makedirs(bin_dir)
        java = fake_java(bin_dir)
        with mock.patch.dict(os.environ, {"PATH": "", "JAVA_HOME": ""}):
            self.assertEqual(tlc.find_java(None, self.dir), [(java, "下载的 JRE")])
        mac = os.path.join(self.dir, "m", "jre", "jdk-17.jre", "Contents", "Home", "bin")
        os.makedirs(mac)
        java = fake_java(mac)
        self.assertEqual(tlc.jre_java(os.path.join(self.dir, "m")), java)

    def test_model_cmd_for_satisfies_judge_rules(self):
        cmd = tlc.model_cmd_for("/opt/my jdk/bin/java")
        fm.check_model_cmd(cmd)
        self.assertEqual(tlc.java_of(cmd), "/opt/my jdk/bin/java")
        self.assertIsNone(tlc.java_of(sys.executable + " {checker} -tool"))
        self.assertEqual(tlc.java_of("java -cp {checker} tlc2.TLC"), "java")
        self.assertIsNone(tlc.java_of("'unterminated"))


class EnvTests(unittest.TestCase):
    def test_locale_env(self):
        zh = ["/tmp/中文/Lease.tla"]
        self.assertEqual(tlc.locale_env(zh, {"LC_ALL": "C"}, "linux"), {"LC_ALL": "C.UTF-8"})
        self.assertEqual(tlc.locale_env(zh, {"LANG": "POSIX"}, "linux"), {"LC_ALL": "C.UTF-8"})
        self.assertEqual(tlc.locale_env(zh, {}, "linux"), {"LC_ALL": "C.UTF-8"})
        self.assertIsNone(tlc.locale_env(zh, {"LANG": "en_US.UTF-8"}, "linux"))
        self.assertIsNone(tlc.locale_env(zh, {"LC_ALL": "zh_CN.utf8"}, "linux"))
        self.assertIsNone(tlc.locale_env(["/tmp/a/Lease.tla"], {"LC_ALL": "C"}, "linux"))
        self.assertIsNone(tlc.locale_env(zh, {"LC_ALL": "C"}, "darwin"))

    def test_diagnose(self):
        cases = {
            "Exception in thread main java.lang.UnsupportedClassVersionError: tlc2/TLC": "Java 11",
            "Cannot find source file for module SequencesExt imported in module M.": "SequencesExt",
            "java.nio.file.InvalidPathException: Malformed input or input contains unmappable characters": "UTF-8",
            "sh: 1: java: not found": "找不到 java",
            "java.lang.OutOfMemoryError: Java heap space": "-Xmx",
            "Error: Could not find or load main class tlc2.TLC": "tlc2.TLC",
        }
        for text, needle in cases.items():
            self.assertIn(needle, tlc.diagnose(text) or "", text)
        self.assertIsNone(tlc.diagnose("Model checking completed."))
        self.assertIsNone(tlc.diagnose(None))

    def test_platform_key(self):
        self.assertEqual(tlc.platform_key("darwin", "arm64"), ("mac", "aarch64"))
        self.assertEqual(tlc.platform_key("win32", "AMD64"), ("windows", "x64"))
        self.assertIn(tlc.platform_key("linux", "x86_64")[0], ("linux", "alpine-linux"))
        with self.assertRaises(EvloopError):
            tlc.platform_key("sunos5", "x86_64")
        with self.assertRaises(EvloopError):
            tlc.platform_key("linux", "mips")

    def test_jre_packages_accepts_both_api_shapes(self):
        pkg = {"name": "a.tar.gz", "link": "https://x/a.tar.gz", "checksum": "c" * 64}
        by_name = {"binaries": [{"image_type": "jdk", "package": pkg}, {"image_type": "jre", "package": pkg}]}
        latest = [{"binary": {"image_type": "jre", "package": pkg}, "release_name": "jdk-17"}]
        self.assertEqual(tlc.jre_packages(by_name), [pkg])
        self.assertEqual(tlc.jre_packages(latest), [pkg])
        for junk in (None, "rate limited", {"binaries": [{"image_type": "jre", "package": {"name": "x"}}]}, [1]):
            self.assertEqual(tlc.jre_packages(junk), [])


class ExtractTests(Tmp):
    def tar_with(self, name, linkname=None):
        path = os.path.join(self.dir, "a.tar.gz")
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo(name)
            if linkname:
                info.type, info.linkname = tarfile.SYMTYPE, linkname
                tf.addfile(info)
            else:
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))
        return path

    def test_rejects_escaping_entries(self):
        dest = os.path.join(self.dir, "dest")
        os.makedirs(dest)
        for name, link in (("../evil", None), ("jdk/bin/java", "/etc/passwd"), ("jdk/l", "../../x")):
            with tarfile.open(self.tar_with(name, link)) as tf:
                with self.assertRaises(EvloopError, msg=name):
                    tlc._safe_extract_tar(tf, dest)
        with tarfile.open(self.tar_with("jdk/bin/java")) as tf:
            tlc._safe_extract_tar(tf, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "jdk", "bin", "java")))


class SelftestTests(Tmp):
    def checker(self):
        return make_jar(os.path.join(self.dir, "tla2tools-full.jar"), entries={"tlc2/TLC.class": cls(55)})

    def run_main(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), redirect_stdout(out), redirect_stderr(err):
            code = tlc.main(list(argv))
        return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()

    def test_selftest_passes_through_judge_quoting_and_parsing(self):
        java = fake_java(self.dir)
        ok, rows = tlc.selftest(self.checker(), tlc.model_cmd_for(java))
        self.assertTrue(ok, rows)
        self.assertEqual({k: v["result"] for k, v in rows.items()},
                         {"EvSelfStd": "verified", "EvSelfBad": "counterexample", "EvSelfExt": "verified"})

    def test_selftest_reports_missing_community_modules(self):
        java = fake_java(self.dir)
        code, out, _ = self.run_main("selftest", "--checker", self.checker(), "--java", java,
                                     env={"FAKE_NO_EXT": "1"})
        self.assertEqual(code, tlc.REJECTED)
        row = out["selftest"]["cases"]["EvSelfExt"]
        self.assertFalse(row["ok"])
        self.assertIn(tlc.BUNDLE, row["reason"])
        self.assertNotIn("init_flags", out)

    def test_selftest_prints_init_flags_and_rejects_old_java(self):
        checker = self.checker()
        java = fake_java(self.dir)
        code, out, _ = self.run_main("selftest", "--checker", checker, "--java", java)
        self.assertEqual(code, 0)
        self.assertIn("--checker-sha256 " + sha(checker), out["init_flags"])
        self.assertEqual(out["model_cmd"], tlc.model_cmd_for(java))
        old_dir = os.path.join(self.dir, "old")
        os.makedirs(old_dir)
        code, out, err = self.run_main("selftest", "--checker", checker, "--java", fake_java(old_dir, "1.8.0_392"))
        self.assertEqual(code, tlc.PRECONDITION)
        self.assertIn("Java ≥ 11", err)

    def test_info_flags_missing_companions(self):
        jar = make_jar(os.path.join(self.dir, "tla2tools.jar"), "Manifest-Version: 1.0\r\nClass-Path: deps.jar\r\n",
                       {"tlc2/TLC.class": cls(55)})
        code, out, _ = self.run_main("info", "--checker", jar)
        self.assertEqual(code, 0)
        self.assertEqual(out["missing_companions"], ["deps.jar"])
        self.assertFalse(out["pinned_bundle"])

    @unittest.skipUnless(os.environ.get("EVLOOP_TLC_CHECKER") and os.environ.get("EVLOOP_TLC_JAVA"),
                         "未提供真实检查器与 java")
    def test_real_checker(self):
        checker = os.environ["EVLOOP_TLC_CHECKER"]
        ok, rows = tlc.selftest(checker, tlc.model_cmd_for(os.environ["EVLOOP_TLC_JAVA"]))
        self.assertTrue(ok, rows)
        self.assertEqual(sha(checker), tlc.BUNDLE_SHA256)


if __name__ == "__main__":
    unittest.main()
