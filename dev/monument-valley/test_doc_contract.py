from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "monument-valley"
REFERENCES = SKILL_DIR / "references"
EVALS = Path(__file__).resolve().parent / "fixtures" / "evals.json"


def load_config():
    path = SKILL_DIR / "scripts" / "valley_manifest" / "config.py"
    spec = importlib.util.spec_from_file_location("monument_valley_config", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MonumentValleyDocContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.frontmatter = cls.skill_text.split("---", 2)[1]
        cls.config = load_config()

    def test_frontmatter_declares_runtime_dependency(self) -> None:
        self.assertRegex(self.frontmatter, r"(?m)^name: monument-valley$")
        self.assertRegex(self.frontmatter, r'bins: \["python3"\]')
        description = re.search(r'^description: "(.+)"$', self.frontmatter, re.MULTILINE).group(1)
        self.assertIn("USE WHEN", description)
        self.assertIn("DO NOT USE", description)

    def test_latest_skill_log_entry_matches_version(self) -> None:
        version = re.search(r"^version:\s*(\S+)$", self.frontmatter, re.MULTILINE).group(1)
        log = self.skill_text.split("## Skill Log", 1)[1]
        first = re.search(r"^- \d{4}-\d{2}-\d{2} \((v\d+\.\d+\.\d+)\):", log, re.MULTILINE)
        self.assertEqual(first.group(1), version)

    def test_reference_table_matches_files(self) -> None:
        listed = set(re.findall(r"`references/([\w-]+\.md)`", self.skill_text))
        on_disk = {path.name for path in REFERENCES.glob("*.md")}
        self.assertEqual(listed, on_disk)

    def test_documented_entrypoint_exists(self) -> None:
        self.assertIn("skills/monument-valley/scripts/validate_manifest.py", self.skill_text)
        self.assertTrue((SKILL_DIR / "scripts" / "validate_manifest.py").is_file())

    def test_documented_exit_codes_match_config(self) -> None:
        contract = self.skill_text.split("## Failure contract", 1)[1]
        for code in (self.config.EXIT_PASSED, self.config.EXIT_FAILED, self.config.EXIT_UNREADABLE):
            self.assertIn(f"`{code}`", contract)

    def test_delivery_limits_agree_across_docs(self) -> None:
        cfg = self.config
        width_range = f"{cfg.DELIVERY_MIN_WIDTH}–{cfg.DELIVERY_MAX_WIDTH}"
        size_limit = f"{cfg.DELIVERY_MAX_BYTES / 1_000_000:g} MB"
        for name in ("SKILL.md", "references/visual-guide.md", "references/state-contract.md"):
            text = (SKILL_DIR / name).read_text(encoding="utf-8")
            self.assertIn(width_range, text, name)
            self.assertIn(size_limit, text, name)

    def test_state_contract_lists_every_final_check(self) -> None:
        text = (REFERENCES / "state-contract.md").read_text(encoding="utf-8")
        for key in self.config.FINAL_CHECKS_V12 + self.config.MIRROR_PARITY_KEYS:
            self.assertIn(f"`{key}`", text, key)

    def test_palette_table_matches_config(self) -> None:
        text = (REFERENCES / "visual-guide.md").read_text(encoding="utf-8")
        documented = dict(re.findall(r"\| (\S+) \| `#([0-9A-F]{6})`", text))
        self.assertEqual(documented, self.config.PALETTE)

    def test_subject_kind_table_matches_config(self) -> None:
        text = (REFERENCES / "workflow.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\w+) \S+ \|", text, re.MULTILINE)
        self.assertEqual(tuple(rows), self.config.SUBJECT_KINDS)
        contract = (REFERENCES / "state-contract.md").read_text(encoding="utf-8")
        for kind in self.config.SUBJECT_KINDS:
            self.assertIn(f"`{kind}`", contract)

    def test_aesthetic_canon_clauses_are_checkable(self) -> None:
        text = (REFERENCES / "aesthetic-canon.md").read_text(encoding="utf-8")
        clauses = re.findall(r"^\| ([A-Z]\d) \| .+ \| (度量|评审) ([\w.]+) \|$", text, re.MULTILINE)
        ids = [c[0] for c in clauses]
        self.assertGreaterEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        metrics = {"palette", "scale", "file", "composition.space", "composition.tone", "composition.placement"}
        for cid, owner, target in clauses:
            allowed = metrics if owner == "度量" else set(self.config.SCORE_DIMENSIONS)
            self.assertIn(target, allowed, cid)
        reviewed = {target for _, owner, target in clauses if owner == "评审"}
        self.assertEqual(reviewed, set(self.config.SCORE_DIMENSIONS))
        import imaging_support  # noqa: F401  -- 把技能 scripts 目录放上 sys.path
        from valley_manifest.analyze_cli import HINTS
        cited = set(re.findall(r"\b([A-Z]\d)\b", " ".join(HINTS.values())))
        self.assertTrue(cited and cited <= set(ids))
        rubric = (REFERENCES / "review-rubric.md").read_text(encoding="utf-8")
        self.assertIn("aesthetic-canon.md", rubric)
        for cid in set(re.findall(r"\b([A-Z]\d)\b", rubric)):
            self.assertIn(cid, ids)

    def test_rubric_matches_score_config(self) -> None:
        text = (REFERENCES / "review-rubric.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\w+) \S+ \|", text, re.MULTILINE)
        self.assertEqual(tuple(rows), self.config.SCORE_DIMENSIONS)
        floors = {k for k, v in self.config.SCORE_FLOORS.items() if v == 4}
        self.assertEqual(floors, {"identity", "scale"})
        self.assertIn("identity 与 scale 不低于 4，其余不低于 3", text)

    def test_listed_assets_exist(self) -> None:
        listed = re.findall(r"`(assets/[\w/-]+\.\w+)`", self.skill_text)
        self.assertTrue(listed)
        for rel in listed:
            self.assertTrue((SKILL_DIR / rel).is_file(), rel)

    def test_documented_scale_bounds_match_config(self) -> None:
        low, high = self.config.DEFAULT_SCALE_BOUNDS
        self.assertIn(f"默认 {low},{high}", self.skill_text)
        guide = (REFERENCES / "visual-guide.md").read_text(encoding="utf-8")
        self.assertIn(f"默认范围 {low}–{high}", guide)

    def test_no_legacy_potato_mode_in_published_docs(self) -> None:
        for path in [SKILL_DIR / "SKILL.md", *REFERENCES.glob("*.md")]:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"mode[\"'`:\s]+potato", path.name)

    def test_evals_are_well_formed(self) -> None:
        data = json.loads(EVALS.read_text(encoding="utf-8"))
        self.assertEqual(data["skill_name"], "monument-valley")
        ids = [case["id"] for case in data["evals"]]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))
        for case in data["evals"]:
            for field in ("name", "prompt", "expected_output"):
                self.assertTrue(case[field], (case["id"], field))
            self.assertGreaterEqual(len(case["expectations"]), 3, case["id"])


if __name__ == "__main__":
    unittest.main()
