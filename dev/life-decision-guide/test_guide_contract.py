"""Offline contract tests for the life-decision-guide stable entrypoint."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "life-decision-guide"
ENTRYPOINT = SKILL / "scripts" / "guide.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAILURE_KEYS = {
    "schema_version", "status", "error", "errorCode", "stage",
    "actionableHints", "dependencySummary", "fallback",
}

sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
from life_decision_guide import cli, config, corpus  # noqa: E402


def invoke(*args, entrypoint=ENTRYPOINT):
    proc = subprocess.run(
        [sys.executable, str(entrypoint), *args],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout, proc.stderr


def invoke_ok(*args):
    code, out, err = invoke(*args)
    if code != 0:
        raise AssertionError(f"exit {code}: {err}")
    return json.loads(out)


def invoke_error(*args, entrypoint=ENTRYPOINT):
    code, out, err = invoke(*args, entrypoint=entrypoint)
    if code != 2 or out:
        raise AssertionError(f"expected exit 2 with empty stdout, got {code}: {out}")
    return json.loads(err)


class EntrypointTest(unittest.TestCase):
    def test_help_is_plain_text_and_exits_zero(self):
        code, out, _ = invoke("--help")
        self.assertEqual(code, 0)
        for command in ("list", "search", "search-docs", "glossary", "show", "rank"):
            self.assertIn(command, out)

    def test_list_covers_every_chapter_with_entries(self):
        data = invoke_ok("list")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["schema_version"], config.SCHEMA_VERSION)
        meta = json.loads((SKILL / "references" / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], meta["commit"])
        sections = [c["section"] for c in data["chapters"]]
        self.assertEqual(sections, list(range(1, meta["chapter_count"] + 1)))
        for chapter in data["chapters"]:
            self.assertGreater(chapter["entry_count"], 0, chapter["title"])
            self.assertTrue((config.SOURCE_ROOT / chapter["file"]).is_file(), chapter["file"])


class SearchAndShowTest(unittest.TestCase):
    def test_search_is_locator_only_and_omits_raw(self):
        data = invoke_ok("search", "--section", "15", "--keywords", "押金", "--limit", "3")
        self.assertEqual(data["entries"][0]["id"], "15:1")
        self.assertTrue(all("raw" not in e for e in data["entries"]))
        self.assertIn("show", data["notice"])

    def test_empty_search_points_to_next_step(self):
        data = invoke_ok("search", "--keywords", "zzqqxx")
        self.assertEqual(data["matched_count"], 0)
        self.assertEqual(data["notice"], config.NOTICES["search_empty"])

    def test_show_returns_full_entry_pinned_to_snapshot(self):
        data = invoke_ok("show", "--id", "2:9", "--id", "2:9")
        self.assertEqual(len(data["entries"]), 1)
        entry = data["entries"][0]
        self.assertIn("低钠盐", entry["raw"])
        self.assertIn("备注", entry["raw"])
        self.assertIn("/blob/24e3d67e4befe0969857616f954410736b417e2f/book/", entry["url"])
        self.assertRegex(entry["url"], r"#L\d+-L\d+$")

    def test_offline_tool_never_claims_independent_checks(self):
        for entry in corpus.entries():
            state = entry["evidence_state"]
            self.assertEqual(state["independent_source_check"]["status"], "not_checked")
            self.assertEqual(state["current_applicability_check"]["status"], "not_checked")


class RankTest(unittest.TestCase):
    def test_ratio_matches_author_algorithm(self):
        spec = json.loads((SKILL / "references" / "ranking.json").read_text(encoding="utf-8"))
        cases = [
            ({"钱": "0", "时间": "少", "毅力": "否", "收益": "大"}, (0, "极高")),
            ({"钱": "少", "时间": "中", "毅力": "否", "收益": "大"}, (2, "高")),
            ({"钱": "多", "时间": "中", "毅力": "否", "收益": "大"}, (3, "一般")),
            ({"钱": "0", "时间": "少", "毅力": "否", "收益": "中"}, (0, "高")),
            ({"钱": "少", "时间": "少", "毅力": "否", "收益": "中"}, (1, "一般")),
            ({"钱": "0", "时间": "少", "毅力": "否", "收益": "小"}, (0, "一般")),
            ({"钱": "0", "时间": "少", "毅力": "否", "收益": "?"}, (0, None)),
            ({"钱": "0", "时间": "少"}, (None, None)),
        ]
        for tags, expected in cases:
            self.assertEqual(corpus.ratio_for(tags, spec), expected, tags)

    def test_rank_groups_by_metric_and_excludes_pending(self):
        data = invoke_ok("rank", "--id", "15:1", "--id", "15:3", "--id", "2:9", "--id", "7:15", "--id", "1:4")
        groups = {g["metric"]: [e["id"] for e in g["entries"]] for g in data["groups"]}
        self.assertEqual(groups, {"金钱": ["7:15", "15:3", "15:1"], "死亡率": ["2:9"]})
        self.assertEqual([e["id"] for e in data["excluded_pending_or_missing_tags"]], ["1:4"])


class FailureContractTest(unittest.TestCase):
    def assert_failure(self, payload, code):
        self.assertEqual(set(payload), FAILURE_KEYS)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["errorCode"], code)
        self.assertEqual(payload["stage"], config.ERRORS[code]["stage"])
        self.assertTrue(payload["actionableHints"])
        self.assertEqual(payload["dependencySummary"]["network"], "not_used")

    def test_unknown_id(self):
        self.assert_failure(invoke_error("show", "--id", "99:1"), "ENTRY_NOT_FOUND")

    def test_argparse_errors_are_json(self):
        self.assert_failure(invoke_error("search"), "INVALID_ARGUMENT")
        self.assert_failure(invoke_error("nope"), "INVALID_ARGUMENT")

    def test_bad_limit_and_blank_keywords(self):
        self.assert_failure(invoke_error("search", "--keywords", "盐", "--limit", "0"), "INVALID_ARGUMENT")
        self.assert_failure(invoke_error("search", "--keywords", " "), "INVALID_ARGUMENT")

    def test_error_catalog_is_complete(self):
        for code, spec in config.ERRORS.items():
            self.assertEqual(set(spec), {"stage", "hints", "fallback"}, code)
            self.assertEqual(set(cli.failure(code, "x")), FAILURE_KEYS)

    def test_unexpected_exception_still_emits_contract(self):
        import contextlib
        import io
        from unittest import mock

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "entries", side_effect=TypeError("boom")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["list"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        payload = json.loads(stderr.getvalue())
        self.assert_failure(payload, "INTERNAL_ERROR")
        self.assertEqual(payload["error"], "TypeError: boom")

    def test_snapshot_tampering_and_loss_refuse_to_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "life-decision-guide"
            shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
            entrypoint = copy / "scripts" / "guide.py"
            for rel, command in (("README.md", ["glossary"]),
                                 ("docs/结婚划不划算.md", ["search-docs", "--keywords", "结婚"])):
                target = copy / "references" / "source" / rel
                target.write_text(target.read_text(encoding="utf-8") + "\n篡改\n", encoding="utf-8")
                self.assert_failure(invoke_error(*command, entrypoint=entrypoint), "SNAPSHOT_INTEGRITY")
            chapter = copy / "references" / "source" / "book" / "02-不要慢慢死.md"
            chapter.write_text(chapter.read_text(encoding="utf-8") + "\n篡改\n", encoding="utf-8")
            self.assert_failure(invoke_error("list", entrypoint=entrypoint), "SNAPSHOT_INTEGRITY")
            chapter.unlink()
            self.assert_failure(invoke_error("list", entrypoint=entrypoint), "SNAPSHOT_MISSING")
            shutil.rmtree(copy / "references" / "source" / "book")
            self.assert_failure(invoke_error("list", entrypoint=entrypoint), "SNAPSHOT_MISSING")


class ReferenceConsistencyTest(unittest.TestCase):
    def test_routes_markdown_mirrors_routes_json(self):
        routes = json.loads((SKILL / "references" / "routes.json").read_text(encoding="utf-8"))
        text = (SKILL / "references" / "routes.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (.+?) \| \[(.+?)\]\((.+?)\) \|$", text, re.M)
        self.assertEqual(
            rows,
            [(r["question"], r["title"], "source/" + r["file"]) for r in routes],
        )
        for _, _, link in rows:
            self.assertTrue((SKILL / "references" / link).is_file(), link)

    def test_skill_md_commands_use_real_entrypoint(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        commands = re.findall(r'python3 "SKILL_DIR/(scripts/[^"]+)" (\w+)', text)
        self.assertTrue(commands)
        for path, command in commands:
            self.assertTrue((SKILL / path).is_file(), path)
            self.assertIn(command, {"list", "search", "search-docs", "glossary", "show", "rank"})

    def test_eval_fixture_ids_exist_and_are_cited_correctly(self):
        evals = json.loads((FIXTURES / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(evals["skill_name"], "life-decision-guide")
        index = {e["id"]: e for e in corpus.entries()}
        cited = 0
        for case in evals["evals"]:
            self.assertTrue(case["prompt"] and case["assertions"], case["id"])
            for assertion in case["assertions"]:
                for section, item in re.findall(r"第 (\d+) 节第 (\d+) 条", assertion):
                    entry = index[f"{section}:{item}"]
                    grade = re.search(r"作者证据 ([ABC])", assertion)
                    if grade:
                        self.assertEqual(entry["author_grade"], grade.group(1))
                    cited += 1
        self.assertGreaterEqual(cited, 3)


if __name__ == "__main__":
    unittest.main()
