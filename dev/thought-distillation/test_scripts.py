from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "thought-distillation"
SCRIPTS = SKILL_DIR / "scripts"

GOOD_BOARD = '<whiteboard type="mermaid">flowchart LR\n  A --> B\n</whiteboard>\n'


def run_script(name: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class FrontmatterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.frontmatter = text.split("---", 2)[1]
        self.body = text

    def test_frontmatter_declares_boundaries_and_dependencies(self) -> None:
        self.assertRegex(self.frontmatter, r"(?m)^name: thought-distillation$")
        description = re.search(r'^description: "(.+)"$', self.frontmatter, re.MULTILINE).group(1)
        self.assertIn("USE WHEN", description)
        self.assertIn("DO NOT USE", description)
        self.assertIn("monument-valley", description)
        self.assertRegex(self.frontmatter, r'bins: \["python3", "bash", "lark-cli"\]')

    def test_referenced_files_exist(self) -> None:
        refs = re.findall(r"\]\((references/[^)]+)\)", self.body)
        self.assertGreaterEqual(len(refs), 3)
        for ref in refs:
            self.assertTrue((SKILL_DIR / ref).is_file(), ref)
        for script in re.findall(r"scripts/([a-z_]+\.(?:py|sh))", self.body):
            self.assertTrue((SCRIPTS / script).is_file(), script)


class CheckXmlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_clean_document_passes(self) -> None:
        self.write("svg/a.svg", '<svg viewBox="0 0 10 10"><text>甲</text></svg>')
        svg_board = '<whiteboard type="svg" path="@./svg/a.svg"></whiteboard>\n'
        body = "<title>T</title>\n<h1>一</h1>\n<p>A &amp; B</p>\n" + GOOD_BOARD * 9 + svg_board * 3
        self.write("doc.xml", body)
        result = run_script("check_xml.py", "doc.xml", cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("whiteboards=12 svg=3", result.stdout)
        self.assertNotIn("WARN", result.stdout)

    def test_known_mistakes_are_errors(self) -> None:
        body = (
            "<title>T</title>\n<p>A & B</p>\n"
            '<checkbox checked="false">x</checkbox>\n'
            '<grid cols="2"><column>x</column></grid>\n'
            '<callout emoji="x"><table></table></callout>\n'
            '<whiteboard type="svg" path="@./svg/missing.svg"></whiteboard>\n'
        )
        self.write("doc.xml", body)
        result = run_script("check_xml.py", "doc.xml", cwd=self.dir)
        self.assertEqual(result.returncode, 1)
        for needle in ("unescaped '&'", "checkbox", "grid cols", "callout contains", "missing.svg"):
            self.assertIn(needle, result.stdout)

    def test_too_few_diagrams_only_warns(self) -> None:
        self.write("doc.xml", "<title>T</title>\n" + GOOD_BOARD * 2)
        result = run_script("check_xml.py", "doc.xml", cwd=self.dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("only 2 whiteboards", result.stdout)

    def test_invalid_utf8_is_rejected(self) -> None:
        (self.dir / "doc.xml").write_bytes(b"<title>\xff\xfe</title>")
        result = run_script("check_xml.py", "doc.xml", cwd=self.dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("UTF-8", result.stdout)


class SplitCollectionTest(unittest.TestCase):
    def test_splits_on_numbered_h2_headings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "c.md"
            src.write_text(
                "# 合集\n\n| 索引 |\n\n## 1. 第一篇\n正文一\n\n## 2. 第二篇\n正文二\n",
                encoding="utf-8",
            )
            out = Path(tmp) / "out"
            result = run_script("split_collection.py", str(src), str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(os.listdir(out)), ["doc01.md", "doc02.md"])
            self.assertIn("正文二", (out / "doc02.md").read_text(encoding="utf-8"))
            self.assertNotIn("索引", (out / "doc01.md").read_text(encoding="utf-8"))
            self.assertIn("2 articles", result.stdout)

    def test_no_headings_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "c.md"
            src.write_text("no headings here\n", encoding="utf-8")
            result = run_script("split_collection.py", str(src), str(Path(tmp) / "out"))
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
