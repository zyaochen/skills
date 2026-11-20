"""Lock the offline runtime to the statistics and rules the upstream book publishes.

The upstream README states corpus-wide counts that its own index.html derives
from the same Markdown. Parsing those numbers out of the pinned README keeps
this suite honest across snapshot refreshes instead of hardcoding them.
"""

import json
import re
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "life-decision-guide"
README = SKILL / "references" / "source" / "README.md"

sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
from life_decision_guide import cli, config, corpus  # noqa: E402

README_TEXT = README.read_text(encoding="utf-8")
ENTRIES = corpus.entries()


def readme_int(pattern):
    match = re.search(pattern, README_TEXT)
    if not match:
        raise AssertionError(f"README pattern not found: {pattern}")
    return [int(g) for g in match.groups()]


class ReadmeStatisticsTest(unittest.TestCase):
    def test_entry_and_grade_counts(self):
        total, a, b, c = readme_int(r"全书 (\d+) 条中 A 级 (\d+) 条、B 级 (\d+) 条、C 级 (\d+) 条")
        self.assertEqual(len(ENTRIES), total)
        grades = Counter(e["author_grade"] for e in ENTRIES)
        self.assertEqual((grades["A"], grades["B"], grades["C"]), (a, b, c))

    def test_dispute_and_todo_counts_follow_index_html_rules(self):
        dispute, todo = readme_int(r"另有 (\d+) 条标注了争议、(\d+) 处标注了 TODO 待核实")
        self.assertEqual(sum(e["author_flags"]["dispute"] for e in ENTRIES), dispute)
        self.assertEqual(sum(e["author_flags"]["todo"] for e in ENTRIES), todo)
        self.assertEqual(
            [e["id"] for e in ENTRIES if e["controversial"]],
            [e["id"] for e in ENTRIES if e["author_flags"]["dispute"]],
        )

    def test_ratio_distribution(self):
        top, high, normal = readme_int(r"性价比极高 (\d+) 条（\d+%）、高 (\d+) 条（\d+%）、一般 (\d+) 条")
        ratios = Counter(e["author_ratio"] for e in ENTRIES)
        self.assertEqual((ratios["极高"], ratios["高"], ratios["一般"]), (top, high, normal))

    def test_glossary_row_count(self):
        (rows,) = readme_int(r"展开 (\d+) 条术语")
        self.assertEqual(len(cli.glossary()["entries"]), rows)

    def test_question_table_mirrors_routes(self):
        table = README_TEXT.split("## 这本书想回答的问题", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\| (.+?) \| \[.+?\]\((book/.+?\.md)\) \|$", table, re.M)
        routes = json.loads((SKILL / "references" / "routes.json").read_text(encoding="utf-8"))
        self.assertEqual(rows, [(r["question"], r["file"]) for r in routes])


class EntryShapeTest(unittest.TestCase):
    def test_every_entry_has_all_fields_and_a_grade(self):
        for e in ENTRIES:
            self.assertEqual(set(e["fields"]), set(config.FIELD_NAMES), e["id"])
            self.assertIn(e["author_grade"], config.GRADES, e["id"])
            self.assertIn(e["tags"].get("口径"), config.METRICS, e["id"])
            for tag, values in config.TAG_VALUES.items():
                self.assertIn(e["tags"].get(tag), values, e["id"])
            self.assertIsNotNone(e["author_ratio"], e["id"])

    def test_annotated_grades_rank_by_letter(self):
        annotated = [e for e in ENTRIES if e["author_evidence"] != e["author_grade"]]
        self.assertTrue(annotated)
        for e in annotated:
            self.assertTrue(e["author_evidence"].startswith(e["author_grade"]), e["id"])

    def test_source_links_come_from_source_field_only(self):
        entry = next(e for e in ENTRIES if e["id"] == "2:9")
        self.assertIn("https://doi.org/10.1056/NEJMoa2105675", entry["source_links"])
        for e in ENTRIES:
            for link in e["source_links"]:
                self.assertIn(link, e["fields"]["来源"], e["id"])

    def test_brief_carries_plain_language_but_not_raw(self):
        out = corpus.brief(ENTRIES[0])
        self.assertNotIn("raw", out)
        self.assertNotIn("fields", out)
        self.assertEqual(out["plain"], ENTRIES[0]["fields"]["说人话"])


class SearchFilterTest(unittest.TestCase):
    def run_search(self, keywords=(), limit=30, match="any", **filters):
        return cli.search(ENTRIES, list(keywords), filters, limit, match)

    def test_filters_are_conjunctive_and_exact(self):
        data = self.run_search(metric=["死亡率"], ratio=["极高"], grade=["A"])
        self.assertGreater(data["matched_count"], 0)
        for e in data["entries"]:
            self.assertEqual((e["tags"]["口径"], e["author_ratio"], e["author_grade"]), ("死亡率", "极高", "A"))

    def test_filter_only_search_counts_match_corpus(self):
        expected = sum(1 for e in ENTRIES if e["tags"].get("钱") == "0" and e["author_flags"]["dispute"])
        self.assertEqual(self.run_search(money=["0"], dispute=True)["matched_count"], expected)

    def test_match_all_is_subset_of_any(self):
        words = ["押金", "合同"]
        every = {e["id"] for e in self.run_search(words, match="all")["entries"]}
        some = {e["id"] for e in self.run_search(words, match="any")["entries"]}
        self.assertTrue(every)
        self.assertLess(every, some)
        for e in ENTRIES:
            if e["id"] in every:
                self.assertTrue(all(w in e["raw"] for w in words))

    def test_title_hits_rank_first(self):
        data = self.run_search(["低钠盐"], limit=3)
        self.assertIn("低钠盐", data["entries"][0]["title"])

    def test_multiple_sections(self):
        data = self.run_search(["押金"], sections=[7, 15])
        self.assertEqual({e["section"] for e in data["entries"]}, {7, 15})

    def test_invalid_filter_value_is_rejected_as_json(self):
        proc = subprocess.run(
            [sys.executable, str(SKILL / "scripts" / "guide.py"), "search", "--metric", "寿命"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stderr)["errorCode"], "INVALID_ARGUMENT")


class DocsAndGlossaryTest(unittest.TestCase):
    def test_default_scope_excludes_tooling_and_records(self):
        data = cli.search_docs(["陌生人"], limit=30)
        self.assertEqual(data["scope"], "articles")
        files = {h["file"] for h in data["hits"]}
        self.assertIn("docs/遇到陌生人出事该不该停.md", files)
        self.assertFalse(files & config.DOC_TOOLING)
        self.assertFalse(any(f.startswith(config.DOC_RECORDS_PREFIX) for f in files))

    def test_records_scope_only_returns_records(self):
        data = cli.search_docs(["陌生人"], limit=30, scope="records")
        self.assertTrue(data["hits"])
        self.assertTrue(all(h["file"].startswith(config.DOC_RECORDS_PREFIX) for h in data["hits"]))

    def test_doc_hits_point_to_pinned_lines(self):
        hit = cli.search_docs(["陌生人"], limit=1)["hits"][0]
        lines = (SKILL / "references" / "source" / hit["file"]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[hit["line"] - 1].strip(), hit["text"])
        self.assertTrue(hit["url"].endswith(f"#L{hit['line']}"))

    def test_glossary_lookup_and_aliases(self):
        data = cli.glossary(["hr", "不存在的词"])
        self.assertEqual([r["terms"] for r in data["entries"]], [["HR"]])
        self.assertEqual(data["not_found"], ["不存在的词"])
        aliased = [r for r in cli.glossary()["entries"] if len(r["terms"]) > 1]
        self.assertTrue(aliased)


if __name__ == "__main__":
    unittest.main()
