from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "skills" / "monument-valley" / "scripts" / "validate_manifest.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "manifest_final_v11.json"
RESULT_KEYS = {"passed", "phase", "schemaVersion", "errors", "error", "stage", "actionableHints", "fallback"}


def load_entrypoint():
    spec = importlib.util.spec_from_file_location("monument_valley_validate", ENTRYPOINT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def downgrade_to_v10(data: dict) -> dict:
    data["schema_version"] = "1.0"
    for key in ("scale_rule", "identity_traits"):
        data["character"].pop(key)
    for image in data["images"]:
        for key in ("scale_checked", "pixel_width", "pixel_height", "bytes"):
            image.pop(key)
    for key in ("scale_matched", "proofread"):
        data["validation"].pop(key)
    return data


def upgrade_to_v12(data: dict) -> dict:
    data["schema_version"] = "1.2"
    data["character"].update(color_anchor="FDD277", scale_bounds=[0.04, 0.32])
    for image in data["images"]:
        image.update(
            generator="image-model-a",
            metrics={"palette": "pass", "scale": "pass", "height_ratio": 0.18},
            review={"reviewer": "reviewer-model-b", "verdict": "pass", "batch": "batch-1",
                    "seen": "主角站在拱门下，左手扶栏杆",
                    "scores": {"identity": 5, "scale": 4, "style": 4, "clarity": 4, "narrative": 3}},
        )
    data["review_batches"] = [{
        "id": "batch-1", "reviewer": "reviewer-model-b", "images_visible": True, "canary_scale": 2,
        "anchor_scores": {"identity": 5, "scale": 4, "style": 4, "clarity": 5, "narrative": 4},
    }]
    data["validation"].update(metrics_checked=True, independent_review=True)
    return data


def upgrade_to_v13(data: dict, kind: str = "person") -> dict:
    data = upgrade_to_v12(data)
    data["schema_version"] = "1.3"
    data["subject_kind"] = kind
    return data


class ValidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = load_entrypoint()
        cls.validate = staticmethod(module.validate)
        from valley_manifest.checks import hints_for
        cls.hints_for = staticmethod(hints_for)

    def errors(self, data: dict, phase: str = "final") -> list[str]:
        return self.validate(data, phase)

    def test_fixture_passes_draft_and_final(self) -> None:
        self.assertEqual(self.errors(fixture(), "draft"), [])
        self.assertEqual(self.errors(fixture(), "final"), [])

    def test_v10_manifest_stays_valid_without_new_fields(self) -> None:
        self.assertEqual(self.errors(downgrade_to_v10(fixture())), [])

    def test_unknown_schema_is_rejected(self) -> None:
        data = fixture()
        data["schema_version"] = "2.0"
        self.assertIn("schema_version 必须为 1.0、1.1、1.2、1.3 之一", self.errors(data))

    def test_potato_mode_is_rejected(self) -> None:
        data = fixture()
        data["character"]["mode"] = "potato"
        errors = self.errors(data, "draft")
        self.assertIn("主角模式不合法", errors)
        self.assertTrue(any("主角不一致" in e for e in errors))

    def test_custom_character_requires_identity_traits_in_v11(self) -> None:
        data = fixture()
        data["character"]["identity_traits"] = []
        self.assertIn("自定义主角缺少本相特征 identity_traits", self.errors(data, "draft"))

    def test_default_character_does_not_need_identity_traits(self) -> None:
        data = fixture()
        data["character"].update(mode="default", identity_traits=None, reference_asset=None)
        for image in data["images"]:
            image["character_mode"] = "default"
        self.assertEqual(self.errors(data), [])

    def test_scale_rule_required_in_v11(self) -> None:
        data = fixture()
        del data["character"]["scale_rule"]
        self.assertIn("主角缺少比例规则 scale_rule", self.errors(data, "draft"))

    def test_final_requires_scale_check_per_image(self) -> None:
        data = fixture()
        data["images"][0]["scale_checked"] = False
        self.assertIn("图片 img-cover 未核对主角比例", self.errors(data))
        self.assertEqual(self.errors(data, "draft"), [])

    def test_oversized_delivery_is_rejected(self) -> None:
        data = fixture()
        data["images"][1].update(pixel_width=5120, pixel_height=2880, bytes=2_830_000)
        errors = self.errors(data)
        self.assertTrue(any("交付宽度 5120" in e for e in errors))
        self.assertTrue(any("交付体积 2830000" in e for e in errors))

    def test_blurry_delivery_is_rejected(self) -> None:
        data = fixture()
        data["images"][0].update(pixel_width=1280, pixel_height=720)
        self.assertTrue(any("交付宽度 1280" in e for e in self.errors(data)))

    def test_missing_delivery_size_is_reported(self) -> None:
        data = fixture()
        del data["images"][0]["bytes"]
        self.assertIn("图片 img-cover 缺少交付尺寸 pixel_width/pixel_height/bytes", self.errors(data))

    def test_mirror_parity_must_be_checked_at_final(self) -> None:
        data = fixture()
        data["mirrors"][0]["parity"]["captions"] = False
        self.assertIn("镜像 #1 未核对一致性: captions", self.errors(data))
        self.assertEqual(self.errors(data, "draft"), [])

    def test_mirror_requires_feishu_address(self) -> None:
        data = fixture()
        data["mirrors"][0]["url"] = "https://example.com/wiki/x"
        self.assertIn("镜像 #1 缺少有效飞书 docx 或 wiki 地址", self.errors(data, "draft"))

    def test_wiki_document_url_is_accepted(self) -> None:
        data = fixture()
        data["document"]["url"] = "https://example.larkoffice.com/wiki/fixturewiki"
        self.assertEqual(self.errors(data), [])

    def test_lookalike_host_is_rejected(self) -> None:
        data = fixture()
        data["document"]["url"] = "https://feishu.cn.evil.example/docx/x"
        self.assertIn("文档：缺少有效形态的飞书 docx 或 wiki 地址", self.errors(data))

    def test_v11_final_requires_proofread(self) -> None:
        data = fixture()
        data["validation"]["proofread"] = False
        self.assertIn("最终验收未通过: proofread", self.errors(data))

    def test_uncertain_operation_blocks_final(self) -> None:
        data = fixture()
        data["operations"][0]["status"] = "uncertain"
        self.assertIn("操作 op1 未回读确认", self.errors(data))

    def test_unverified_quote_is_rejected(self) -> None:
        data = fixture()
        data["claims"][1]["quote_verified"] = False
        self.assertIn("命题 c2 的引语未逐字核验", self.errors(data, "draft"))

    def test_claim_on_unread_source_is_rejected(self) -> None:
        data = fixture()
        data["sources"][0]["status"] = "unavailable"
        data["coverage"].update(read=0, unavailable=1)
        data["gaps"] = ["博客无法访问"]
        self.assertIn("命题 c1 使用了未读取来源 s1", self.errors(data, "draft"))

    def test_info_image_needs_label_plan(self) -> None:
        data = fixture()
        data["images"][1]["label_mode"] = "none"
        self.assertIn("信息图 img-map 没有标注方案", self.errors(data, "draft"))

    def test_v12_manifest_passes(self) -> None:
        self.assertEqual(self.errors(upgrade_to_v12(fixture())), [])

    def test_v11_manifest_does_not_need_v12_fields(self) -> None:
        self.assertEqual(self.errors(fixture()), [])

    def test_v13_accepts_non_person_subjects(self) -> None:
        for kind in ("project", "team", "organization", "product", "event", "topic", "other"):
            data = upgrade_to_v13(fixture(), kind)
            self.assertEqual(self.errors(data), [], kind)

    def test_v13_requires_subject_kind(self) -> None:
        data = upgrade_to_v13(fixture())
        del data["subject_kind"]
        self.assertTrue(any("subject_kind" in e for e in self.errors(data)))

    def test_unknown_subject_kind_is_rejected_in_any_version(self) -> None:
        data = fixture()
        data["subject_kind"] = "pet"
        self.assertTrue(any("subject_kind" in e for e in self.errors(data)))

    def test_blank_subject_is_rejected(self) -> None:
        data = upgrade_to_v13(fixture(), "project")
        data["subject"] = "  "
        self.assertIn("缺少主题称呼 subject", self.errors(data))

    def test_subject_hint_is_returned(self) -> None:
        data = upgrade_to_v13(fixture())
        data["subject_kind"] = "pet"
        self.assertTrue(any("subject_kind" in h for h in self.hints_for(self.errors(data))))

    def test_v12_self_review_is_rejected(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["review"]["reviewer"] = "image-model-a"
        self.assertIn("图片 img-cover 评审 reviewer 须独立于出图 generator", self.errors(data))

    def test_v12_requires_generator(self) -> None:
        data = upgrade_to_v12(fixture())
        del data["images"][0]["generator"]
        self.assertIn("图片 img-cover 缺少出图来源 generator", self.errors(data))

    def test_v12_identity_floor_is_four(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][1]["review"]["scores"]["identity"] = 3
        self.assertIn("图片 img-map 评审 identity 分数缺失或低于 4", self.errors(data))

    def test_v12_boolean_score_is_rejected(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][1]["review"]["scores"]["clarity"] = True
        self.assertIn("图片 img-map 评审 clarity 分数缺失或低于 3", self.errors(data))

    def test_v12_review_verdict_must_pass(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["review"]["verdict"] = "fail"
        self.assertIn("图片 img-cover 评审结论不是 pass", self.errors(data))

    def test_v12_palette_grey_zone_needs_style_four(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["metrics"]["palette"] = "review"
        self.assertEqual(self.errors(data), [])
        data["images"][0]["review"]["scores"]["style"] = 3
        self.assertTrue(any("色板度量为 review" in e for e in self.errors(data)))

    def test_v12_palette_fail_cannot_be_overridden_by_review(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["metrics"]["palette"] = "fail"
        data["images"][0]["review"]["scores"]["style"] = 5
        self.assertTrue(any("色板度量为 fail" in e for e in self.errors(data)))

    def test_v12_composition_is_optional_and_checked(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["metrics"]["composition"] = "pass"
        self.assertEqual(self.errors(data), [])
        data["images"][0]["metrics"]["composition"] = "fail"
        data["images"][0]["review"]["scores"]["style"] = 5
        self.assertTrue(any("构图度量为 fail" in e for e in self.errors(data)))

    def test_v12_composition_grey_zone_needs_style_four(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["metrics"]["composition"] = "review"
        self.assertEqual(self.errors(data), [])
        data["images"][0]["review"]["scores"]["style"] = 3
        self.assertTrue(any("构图度量为 review" in e for e in self.errors(data)))

    def test_v12_unmeasured_scale_blocks_final(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][1]["metrics"]["scale"] = "unmeasured"
        self.assertTrue(any("主角比例度量为 unmeasured" in e for e in self.errors(data)))
        self.assertEqual(self.errors(data, "draft"), [])

    def test_v12_missing_metrics_reported(self) -> None:
        data = upgrade_to_v12(fixture())
        del data["images"][0]["metrics"]
        self.assertIn("图片 img-cover 缺少度量结论 metrics.palette / metrics.scale", self.errors(data))

    def test_v12_color_anchor_and_bounds_are_validated(self) -> None:
        data = upgrade_to_v12(fixture())
        data["character"].update(color_anchor="yellow", scale_bounds=[0.5, 0.2])
        errors = self.errors(data, "draft")
        self.assertIn("主角 color_anchor 须为 6 位十六进制色值", errors)
        self.assertIn("主角比例 scale_bounds 须为 0–1 之间的 [low, high]", errors)

    def test_v12_review_needs_seen_evidence(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["review"]["seen"] = " "
        self.assertIn("图片 img-cover 评审缺少可核对的所见细节 seen", self.errors(data))

    def test_v12_canary_not_failed_invalidates_batch(self) -> None:
        data = upgrade_to_v12(fixture())
        data["review_batches"][0]["canary_scale"] = 4
        errors = self.errors(data)
        self.assertTrue(any("对照样本 canary_scale" in e for e in errors))
        self.assertIn("图片 img-cover 评审未指向已校准的评审批次 batch", errors)

    def test_v12_anchor_below_floor_invalidates_batch(self) -> None:
        data = upgrade_to_v12(fixture())
        data["review_batches"][0]["anchor_scores"]["identity"] = 3
        self.assertTrue(any("基准图 anchor_scores" in e for e in self.errors(data)))

    def test_v12_invisible_images_invalidate_batch(self) -> None:
        data = upgrade_to_v12(fixture())
        data["review_batches"][0]["images_visible"] = False
        self.assertTrue(any("images_visible" in e for e in self.errors(data)))

    def test_v12_batch_reviewer_must_match(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["review"]["reviewer"] = "reviewer-model-c"
        self.assertIn("图片 img-cover 评审人与批次 batch 不一致", self.errors(data))

    def test_v12_duplicate_batch_id_is_rejected(self) -> None:
        data = upgrade_to_v12(fixture())
        data["review_batches"].append(dict(data["review_batches"][0]))
        self.assertIn("评审批次缺少唯一 id", self.errors(data))

    def test_v12_batch_hint_is_returned(self) -> None:
        data = upgrade_to_v12(fixture())
        data["review_batches"][0]["canary_scale"] = 5
        self.assertTrue(any("canary" in h for h in self.hints_for(self.errors(data))))

    def test_v12_final_requires_new_validation_keys(self) -> None:
        data = upgrade_to_v12(fixture())
        data["validation"]["independent_review"] = False
        self.assertIn("最终验收未通过: independent_review", self.errors(data))

    def test_input_is_not_mutated(self) -> None:
        data = fixture()
        before = copy.deepcopy(data)
        self.errors(data)
        self.assertEqual(data, before)


class CliContractTest(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, dict]:
        proc = subprocess.run(
            [sys.executable, str(ENTRYPOINT), *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        return proc.returncode, json.loads(proc.stdout)

    def write(self, data) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            handle.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_help_launches(self) -> None:
        proc = subprocess.run([sys.executable, str(ENTRYPOINT), "--help"],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--phase", proc.stdout)

    def test_pass_shape_and_exit_zero(self) -> None:
        code, result = self.run_cli(str(FIXTURE), "--phase", "final")
        self.assertEqual(code, 0)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertTrue(result["passed"])
        self.assertEqual(result["schemaVersion"], "1.1")
        self.assertIsNone(result["error"])
        self.assertEqual(result["actionableHints"], [])

    def test_failure_shape_and_exit_one(self) -> None:
        data = fixture()
        data["images"][0]["pixel_width"] = 5120
        data["validation"]["proofread"] = False
        code, result = self.run_cli(self.write(data), "--phase", "final")
        self.assertEqual(code, 1)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertFalse(result["passed"])
        self.assertEqual(result["stage"], "validate")
        self.assertEqual(result["error"], f"{len(result['errors'])} 项检查未通过")
        self.assertTrue(any("交付" in hint for hint in result["actionableHints"]))
        self.assertTrue(any("validation" in hint for hint in result["actionableHints"]))

    def test_v12_failure_points_to_independent_review(self) -> None:
        data = upgrade_to_v12(fixture())
        data["images"][0]["review"]["reviewer"] = "image-model-a"
        code, result = self.run_cli(self.write(data), "--phase", "final")
        self.assertEqual(code, 1)
        self.assertTrue(any("评审" in hint for hint in result["actionableHints"]))
        self.assertTrue(result["fallback"])

    def test_unreadable_manifest_exits_two(self) -> None:
        code, result = self.run_cli(self.write("{not json"))
        self.assertEqual(code, 2)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["stage"], "read")
        self.assertTrue(result["actionableHints"])

    def test_missing_file_exits_two(self) -> None:
        code, result = self.run_cli(str(REPO_ROOT / "does-not-exist.json"))
        self.assertEqual(code, 2)
        self.assertFalse(result["passed"])

    def test_non_object_root_fails_cleanly(self) -> None:
        code, result = self.run_cli(self.write("[]"))
        self.assertEqual(code, 1)
        self.assertEqual(result["errors"], ["根节点必须为对象"])
        self.assertIsNone(result["schemaVersion"])


if __name__ == "__main__":
    unittest.main()
