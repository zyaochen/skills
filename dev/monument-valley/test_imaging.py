from __future__ import annotations

import shutil
import unittest

from imaging_support import (IVORY, POTATO, RED, SCRIPTS, Canvas, character_scene, config,
                             custom_png, minimal_jpeg, png)
from valley_manifest import imaging

ASSETS = SCRIPTS.parent / "assets" / "style"
BOUNDS = config.DEFAULT_SCALE_BOUNDS


def has_jpeg_reader() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return shutil.which("sips") is not None


class PngCodecTest(unittest.TestCase):
    def test_roundtrip_rgb(self) -> None:
        image = Canvas(7, 3).rect(1, 1, 4, 2, RED).image()
        decoded = png.decode(png.encode(image))
        self.assertEqual((decoded.width, decoded.height, decoded.pixels), (7, 3, image.pixels))

    def test_every_filter_type_decodes(self) -> None:
        rows = [bytes((x * 37 + y * 11 + c * 5) % 256 for x in range(5) for c in range(3)) for y in range(5)]
        data = custom_png(rows, 5, 5, 2, [0, 1, 2, 3, 4])
        self.assertEqual(png.decode(data).pixels, b"".join(rows))

    def test_rgba_gray_and_palette_decode_to_rgb(self) -> None:
        rgba = custom_png([bytes((10, 20, 30, 99, 40, 50, 60, 0))], 2, 1, 6, [4])
        self.assertEqual(png.decode(rgba).pixels, bytes((10, 20, 30, 40, 50, 60)))
        gray = custom_png([bytes((0, 200))], 2, 1, 0, [1])
        self.assertEqual(png.decode(gray).pixels, bytes((0, 0, 0, 200, 200, 200)))
        indexed = custom_png([bytes((1, 0))], 2, 1, 3, [0], palette=bytes((9, 9, 9, 1, 2, 3)))
        self.assertEqual(png.decode(indexed).pixels, bytes((1, 2, 3, 9, 9, 9)))

    def test_unsupported_png_is_rejected(self) -> None:
        data = bytearray(png.encode(Canvas(2, 2).image()))
        data[24] = 16
        with self.assertRaises(png.ImageError):
            png.decode(bytes(data))

    def test_read_size_png_and_jpeg(self) -> None:
        self.assertEqual(png.read_size(png.encode(Canvas(9, 4).image())), ("png", 9, 4))
        self.assertEqual(png.read_size(minimal_jpeg(2560, 1440)), ("jpeg", 2560, 1440))
        with self.assertRaises(png.ImageError):
            png.read_size(b"GIF89a")

    def test_resize_nearest(self) -> None:
        image = Canvas(4, 2).rect(2, 0, 4, 2, RED).image()
        small = png.resize(image, 2, 1)
        self.assertEqual(small.pixels, bytes(IVORY) + bytes(RED))


class PaletteMetricTest(unittest.TestCase):
    def test_palette_colors_pass(self) -> None:
        canvas = Canvas(40, 20)
        for n, value in enumerate(list(config.PALETTE.values())[:8]):
            canvas.rect(n * 5, 0, n * 5 + 5, 20, imaging.hex_rgb(value))
        self.assertEqual(imaging.palette_metrics(canvas.image())["verdict"], "pass")

    def test_saturated_off_palette_fails(self) -> None:
        metrics = imaging.palette_metrics(Canvas(20, 10, fill=RED).image())
        self.assertEqual(metrics["verdict"], "fail")
        self.assertLess(metrics["coverage"], config.PALETTE_FAIL_COVERAGE)

    def test_grey_zone_is_review(self) -> None:
        canvas = Canvas(100, 10).rect(0, 0, 30, 10, (0x20, 0x90, 0x30))
        self.assertEqual(imaging.palette_metrics(canvas.image())["verdict"], "review")

    def test_verdict_thresholds(self) -> None:
        self.assertEqual(imaging.palette_verdict(0.75, 0.33), "pass")
        self.assertEqual(imaging.palette_verdict(0.9, 0.41), "fail")
        self.assertEqual(imaging.palette_verdict(0.59, 0.1), "fail")
        self.assertEqual(imaging.palette_verdict(0.7, 0.2), "review")


class CharacterScaleTest(unittest.TestCase):
    def test_small_outlined_character_passes(self) -> None:
        result = imaging.scale_from_mask(character_scene(0.15).image(), "FDD277", BOUNDS)
        self.assertEqual(result["verdict"], "pass")
        self.assertAlmostEqual(result["heightRatio"], 0.15, delta=0.02)

    def test_enlarged_character_fails(self) -> None:
        result = imaging.scale_from_mask(character_scene(0.5).image(), "FDD277", BOUNDS)
        self.assertEqual(result["verdict"], "fail")

    def test_same_colored_sun_without_outline_is_ignored(self) -> None:
        canvas = character_scene(0.12).rect(10, 10, 110, 110, POTATO)
        result = imaging.scale_from_mask(canvas.image(), "FDD277", BOUNDS)
        self.assertEqual(result["verdict"], "pass")
        self.assertAlmostEqual(result["heightRatio"], 0.12, delta=0.02)
        self.assertGreater(len(result["candidates"]), 1)

    def test_two_similar_outlined_candidates_need_review(self) -> None:
        canvas = character_scene(0.15).outlined(40, 70, 58, 97)
        self.assertEqual(imaging.scale_from_mask(canvas.image(), "FDD277", BOUNDS)["verdict"], "review")

    def test_character_color_absent_is_unmeasured(self) -> None:
        result = imaging.scale_from_mask(Canvas(320, 180).image(), "FDD277", BOUNDS)
        self.assertEqual(result["verdict"], "unmeasured")

    def test_box_measurement(self) -> None:
        self.assertEqual(imaging.scale_from_box([0.4, 0.4, 0.5, 0.6], BOUNDS)["verdict"], "pass")
        self.assertEqual(imaging.scale_from_box([0.1, 0.1, 0.6, 0.9], BOUNDS)["verdict"], "fail")
        with self.assertRaises(ValueError):
            imaging.scale_from_box([0.5, 0.5, 0.4, 0.6], BOUNDS)

    def test_bad_hex_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            imaging.hex_rgb("FFF")


def busy_scene() -> Canvas:
    canvas = character_scene(0.15)
    for y in range(canvas.height):
        for x in range(0, canvas.width, 2):
            if (x // 2 + y // 2) % 2:
                canvas.rect(x, y, x + 1, y + 1, (0x80, 0x78, 0x70))
    return canvas


class CompositionMetricTest(unittest.TestCase):
    def measure(self, canvas: Canvas, box=None) -> dict:
        return imaging.composition_metrics(imaging.analysis_frame(canvas.image()), box)

    def test_calm_bright_centered_scene_passes(self) -> None:
        result = self.measure(character_scene(0.15), [0.46, 0.42, 0.54, 0.58])
        self.assertEqual(result["checks"], {"space": "pass", "tone": "pass", "placement": "pass"})
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["center"], [0.5, 0.5])

    def test_cluttered_scene_fails_space(self) -> None:
        result = self.measure(busy_scene())
        self.assertLess(result["negativeSpace"], config.SPACE_FAIL)
        self.assertEqual(result["checks"]["space"], "fail")
        self.assertEqual(result["verdict"], "fail")

    def test_dark_scene_fails_tone(self) -> None:
        result = self.measure(Canvas(320, 180, fill=(0x30, 0x34, 0x40)))
        self.assertEqual(result["checks"]["tone"], "fail")
        self.assertEqual(result["verdict"], "fail")

    def test_edge_placement_needs_review(self) -> None:
        result = self.measure(character_scene(0.15), [0.9, 0.4, 0.98, 0.6])
        self.assertEqual(result["checks"]["placement"], "review")
        self.assertEqual(result["verdict"], "review")

    def test_placement_without_box_is_unmeasured_and_ignored(self) -> None:
        result = self.measure(character_scene(0.15))
        self.assertEqual(result["checks"]["placement"], "unmeasured")
        self.assertEqual(result["verdict"], "pass")

    def test_band_thresholds(self) -> None:
        self.assertEqual(imaging.band(0.6, 0.6, 0.45), "pass")
        self.assertEqual(imaging.band(0.5, 0.6, 0.45), "review")
        self.assertEqual(imaging.band(0.44, 0.6, 0.45), "fail")


class SheetAndAssetTest(unittest.TestCase):
    def test_contact_sheet_layout(self) -> None:
        images = [Canvas(160, 90).image() for _ in range(5)]
        sheet = imaging.contact_sheet(images, 3, 100)
        gap = config.SHEET_GAP
        self.assertEqual((sheet.width, sheet.height), (3 * 100 + 4 * gap, 2 * 56 + 3 * gap))
        corner = sheet.rgb(gap + 6, gap + 6)
        self.assertIn(corner, {config.SHEET_LABEL_BG, config.SHEET_LABEL_FG})

    def test_committed_palette_card_matches_config(self) -> None:
        from valley_manifest.analyze_cli import palette_card
        self.assertEqual((ASSETS / "palette-card.png").read_bytes(), png.encode(palette_card()))

    @unittest.skipUnless(has_jpeg_reader(), "需要 Pillow 或 sips 读取 JPEG")
    def test_style_reference_is_on_palette_and_character_free(self) -> None:
        frame = imaging.analysis_frame(imaging.load_image(str(ASSETS / "scene-reference.jpg")))
        self.assertEqual(imaging.palette_metrics(frame)["verdict"], "pass")
        self.assertEqual(imaging.scale_from_mask(frame, "FDD277", BOUNDS)["verdict"], "unmeasured")
        self.assertEqual(imaging.composition_metrics(frame)["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
