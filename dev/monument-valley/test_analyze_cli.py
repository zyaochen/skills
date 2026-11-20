from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from imaging_support import RED, SCRIPTS, Canvas, character_scene, png

ENTRYPOINT = SCRIPTS / "analyze_images.py"
RESULT_KEYS = {"ok", "command", "results", "summary", "actionableHints", "error", "stage", "fallback"}


class AnalyzeCliTest(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="mv_cli_")
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def run_cli(self, *args: str) -> tuple[int, dict]:
        proc = subprocess.run([sys.executable, str(ENTRYPOINT), *args],
                              capture_output=True, text=True, encoding="utf-8", check=False)
        return proc.returncode, json.loads(proc.stdout)

    def test_help_launches(self) -> None:
        proc = subprocess.run([sys.executable, str(ENTRYPOINT), "--help"],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0)
        for command in ("metrics", "sheet", "crops", "canary", "palette-card"):
            self.assertIn(command, proc.stdout)

    def test_metrics_pass_shape(self) -> None:
        good = character_scene(0.15).save(self.dir / "good.png")
        code, result = self.run_cli("metrics", str(good), "--character-color", "FDD277")
        self.assertEqual(code, 0)
        self.assertEqual(set(result), RESULT_KEYS | {"bounds"})
        self.assertTrue(result["ok"])
        item = result["results"][0]
        self.assertEqual(item["file"], {"format": "png", "width": 320, "height": 180,
                                        "bytes": good.stat().st_size})
        self.assertEqual((item["palette"]["verdict"], item["scale"]["verdict"], item["verdict"]),
                         ("pass", "pass", "pass"))
        self.assertEqual(item["composition"]["verdict"], "pass")
        self.assertEqual(item["composition"]["checks"]["placement"], "pass")

    def test_metrics_failure_and_hints(self) -> None:
        big = character_scene(0.5).save(self.dir / "big.png")
        red = Canvas(320, 180, fill=RED).save(self.dir / "red.png")
        code, result = self.run_cli("metrics", str(big), str(red), "--character-color", "FDD277")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["summary"]["fail"], 2)
        self.assertEqual(result["stage"], "analyze")
        self.assertTrue(any("缩小" in h for h in result["actionableHints"]))
        self.assertTrue(any("色板" in h for h in result["actionableHints"]))

    def test_dark_image_fails_composition_with_canon_hint(self) -> None:
        dark = Canvas(320, 180, fill=(0x30, 0x34, 0x40)).save(self.dir / "dark.png")
        code, result = self.run_cli("metrics", str(dark))
        self.assertEqual(code, 1)
        self.assertEqual(result["results"][0]["composition"]["checks"]["tone"], "fail")
        self.assertTrue(any("aesthetic-canon" in h for h in result["actionableHints"]))

    def test_default_character_needs_box(self) -> None:
        plain = Canvas(320, 180).save(self.dir / "plain.png")
        code, result = self.run_cli("metrics", str(plain))
        self.assertEqual(code, 1)
        self.assertEqual(result["results"][0]["scale"]["verdict"], "unmeasured")
        boxes = self.dir / "boxes.json"
        boxes.write_text(json.dumps({"plain.png": [0.45, 0.4, 0.5, 0.55]}), encoding="utf-8")
        code, result = self.run_cli("metrics", str(plain), "--boxes", str(boxes))
        self.assertEqual(code, 0)
        self.assertEqual(result["results"][0]["scale"]["method"], "box")

    def test_box_disagreeing_with_mask_goes_to_review(self) -> None:
        good = character_scene(0.15).save(self.dir / "good.png")
        boxes = self.dir / "boxes.json"
        boxes.write_text(json.dumps({"good.png": [0.1, 0.05, 0.9, 0.95]}), encoding="utf-8")
        code, result = self.run_cli("metrics", str(good), "--character-color", "FDD277", "--boxes", str(boxes))
        self.assertEqual(code, 1)
        self.assertEqual(result["results"][0]["scale"]["verdict"], "review")

    def test_custom_bounds(self) -> None:
        good = character_scene(0.15).save(self.dir / "good.png")
        code, result = self.run_cli("metrics", str(good), "--character-color", "FDD277", "--bounds", "0.2,0.4")
        self.assertEqual(code, 1)
        self.assertEqual(result["bounds"], [0.2, 0.4])

    def test_sheet_writes_png(self) -> None:
        paths = [str(character_scene(0.15).save(self.dir / f"{n}.png")) for n in range(4)]
        out = self.dir / "sheet.png"
        code, result = self.run_cli("sheet", *paths, "--out", str(out), "--columns", "2", "--thumb-width", "120")
        self.assertEqual(code, 0)
        self.assertEqual(set(result), RESULT_KEYS | {"legend"})
        self.assertEqual([e["number"] for e in result["legend"]], [1, 2, 3, 4])
        self.assertEqual(png.read_size(out.read_bytes())[0], "png")

    def test_crops_writes_close_up_sheet(self) -> None:
        good = str(character_scene(0.15).save(self.dir / "good.png"))
        out = self.dir / "crops.png"
        code, result = self.run_cli("crops", good, good, "--character-color", "FDD277", "--out", str(out))
        self.assertEqual(code, 0)
        self.assertEqual(set(result), RESULT_KEYS | {"legend"})
        self.assertEqual(result["results"][0]["located"], 2)
        self.assertTrue(all(e["located"] for e in result["legend"]))
        self.assertEqual(png.read_size(out.read_bytes())[0], "png")

    def test_crops_reports_unlocated_character(self) -> None:
        plain = str(Canvas(320, 180).save(self.dir / "plain.png"))
        code, result = self.run_cli("crops", plain, "--out", str(self.dir / "crops.png"))
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["results"][0]["missing"], [plain])
        self.assertTrue(any("--boxes" in h for h in result["actionableHints"]))

    def test_canary_fails_scale_metric(self) -> None:
        good = character_scene(0.15).save(self.dir / "good.png")
        out = self.dir / "canary.png"
        code, result = self.run_cli("canary", str(good), "--character-color", "FDD277", "--out", str(out))
        self.assertEqual(code, 0)
        self.assertEqual(png.read_size(out.read_bytes())[1:], (320, 180))
        code, result = self.run_cli("metrics", str(out), "--character-color", "FDD277")
        self.assertEqual(result["results"][0]["scale"]["verdict"], "fail")

    def test_canary_without_locator_exits_two(self) -> None:
        plain = Canvas(320, 180).save(self.dir / "plain.png")
        code, result = self.run_cli("canary", str(plain), "--out", str(self.dir / "c.png"))
        self.assertEqual(code, 2)
        self.assertIn("--box", result["error"])

    def test_missing_input_exits_two(self) -> None:
        code, result = self.run_cli("metrics", str(self.dir / "absent.png"))
        self.assertEqual(code, 2)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["stage"], "input")
        self.assertTrue(result["actionableHints"])

    def test_bad_bounds_exits_two(self) -> None:
        good = character_scene(0.15).save(self.dir / "good.png")
        code, result = self.run_cli("metrics", str(good), "--bounds", "0.5,0.1")
        self.assertEqual(code, 2)
        self.assertIn("bounds", result["error"])


if __name__ == "__main__":
    unittest.main()
