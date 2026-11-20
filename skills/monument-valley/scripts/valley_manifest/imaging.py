"""确定性画面度量：色板覆盖、主角比例、接触表；不做审美判断。"""

import os
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path

from . import config, png

_LAB_CACHE = {}


class DependencyError(RuntimeError):
    """缺少把 JPEG 转成 PNG 的能力。"""


def hex_rgb(value):
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"颜色必须是 6 位十六进制: {value}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _linear(c):
    c /= 255.0
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _f(t):
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116


def lab(rgb):
    cached = _LAB_CACHE.get(rgb)
    if cached is None:
        r, g, b = (_linear(float(v)) for v in rgb)
        x = _f((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047)
        y = _f(0.2126 * r + 0.7152 * g + 0.0722 * b)
        z = _f((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
        cached = (116 * y - 16, 500 * (x - y), 200 * (y - z))
        _LAB_CACHE[rgb] = cached
    return cached


def delta_e(a, b):
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def load_image(path):
    data = Path(path).read_bytes()
    kind = png.read_size(data)[0]
    if kind == "png":
        try:
            return png.decode(data)
        except png.ImageError:
            pass
    return png.decode(_convert_to_png(path))


def _convert_to_png(path):
    try:
        from PIL import Image as PilImage  # type: ignore
    except ImportError:
        PilImage = None
    if PilImage is not None:
        with PilImage.open(path) as im:
            rgb = im.convert("RGB")
            return png.encode(png.Image(rgb.width, rgb.height, rgb.tobytes()))
    if shutil.which("sips"):
        with tempfile.TemporaryDirectory(prefix="mv_img_") as scratch:
            out = os.path.join(scratch, "frame.png")
            subprocess.run(["sips", "-s", "format", "png", path, "--out", out],
                           check=True, capture_output=True)
            return Path(out).read_bytes()
    raise DependencyError("读取 JPEG 需要 Pillow 或 macOS sips")


def analysis_frame(image):
    width = min(config.ANALYSIS_WIDTH, image.width)
    height = max(1, round(image.height * width / image.width))
    return png.resize(image, width, height)


def palette_metrics(frame, palette=None):
    anchors = [lab(hex_rgb(h)) for h in (palette or config.PALETTE.values())]
    hits = total = 0
    saturation = 0.0
    for i in range(0, len(frame.pixels), 3 * config.PALETTE_SAMPLE_STEP):
        rgb = tuple(frame.pixels[i:i + 3])
        total += 1
        point = lab(rgb)
        hits += min(delta_e(point, a) for a in anchors) < config.PALETTE_DELTA_E
        high, low = max(rgb), min(rgb)
        saturation += (high - low) / high if high else 0.0
    coverage, saturation = hits / total, saturation / total
    return {"coverage": round(coverage, 3), "meanSaturation": round(saturation, 3),
            "verdict": palette_verdict(coverage, saturation)}


def palette_verdict(coverage, saturation):
    if coverage < config.PALETTE_FAIL_COVERAGE or saturation > config.PALETTE_FAIL_SATURATION:
        return "fail"
    if coverage >= config.PALETTE_PASS_COVERAGE and saturation <= config.PALETTE_PASS_SATURATION:
        return "pass"
    return "review"


def band(value, pass_at, fail_below):
    if value < fail_below:
        return "fail"
    return "pass" if value >= pass_at else "review"


def composition_metrics(frame, box=None):
    w, h = frame.width, frame.height
    light = [lab(tuple(frame.pixels[i:i + 3]))[0] for i in range(0, len(frame.pixels), 3)]
    quiet = total = 0
    for y in range(h - 1):
        for x in range(w - 1):
            at = y * w + x
            total += 1
            quiet += abs(light[at + 1] - light[at]) + abs(light[at + w] - light[at]) < config.QUIET_GRADIENT
    space = quiet / total if total else 0.0
    tone = sum(light) / len(light)
    checks = {"space": band(space, config.SPACE_PASS, config.SPACE_FAIL),
              "tone": band(tone, config.TONE_PASS, config.TONE_FAIL), "placement": "unmeasured"}
    result = {"negativeSpace": round(space, 3), "meanLightness": round(tone, 1), "center": None}
    if box:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        left, top, right, bottom = config.SAFE_ZONE
        checks["placement"] = "pass" if left <= cx <= right and top <= cy <= bottom else "review"
        result["center"] = [round(cx, 3), round(cy, 3)]
    measured = [v for v in checks.values() if v != "unmeasured"]
    result.update(checks=checks, verdict=max(measured, key=config.VERDICT_ORDER.index))
    return result


def color_mask(frame, color, tolerance):
    target = lab(hex_rgb(color))
    return [delta_e(lab(tuple(frame.pixels[i:i + 3])), target) < tolerance
            for i in range(0, len(frame.pixels), 3)]


def dark_mask(frame):
    return [lab(tuple(frame.pixels[i:i + 3]))[0] < config.OUTLINE_MAX_LIGHTNESS
            for i in range(0, len(frame.pixels), 3)]


def components(mask, width, height):
    seen = bytearray(len(mask))
    found = []
    for start, on in enumerate(mask):
        if on and not seen[start]:
            found.append(_flood(mask, seen, start, width, height))
    return found


def _flood(mask, seen, start, width, height):
    queue, pixels = deque([start]), []
    seen[start] = 1
    while queue:
        index = queue.popleft()
        pixels.append(index)
        y, x = divmod(index, width)
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            neighbour = ny * width + nx
            if 0 <= ny < height and 0 <= nx < width and mask[neighbour] and not seen[neighbour]:
                seen[neighbour] = 1
                queue.append(neighbour)
    return pixels


def outline_score(pixels, mask, dark, width, height):
    radius, edge, hit = config.OUTLINE_RADIUS, 0, 0
    for index in pixels:
        y, x = divmod(index, width)
        if all(0 <= ny < height and 0 <= nx < width and mask[ny * width + nx]
               for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1))):
            continue
        edge += 1
        hit += any(dark[yy * width + xx]
                   for yy in range(max(y - radius, 0), min(y + radius + 1, height))
                   for xx in range(max(x - radius, 0), min(x + radius + 1, width)))
    return hit / edge if edge else 0.0


def describe(pixels, width, height, score):
    ys = [i // width for i in pixels]
    xs = [i % width for i in pixels]
    return {"outline": round(score, 2), "areaRatio": round(len(pixels) / (width * height), 4),
            "heightRatio": round((max(ys) - min(ys) + 1) / height, 3),
            "box": [min(xs) / width, min(ys) / height, (max(xs) + 1) / width, (max(ys) + 1) / height]}


def character_candidates(frame, color, tolerance=None):
    width, height = frame.width, frame.height
    mask = color_mask(frame, color, tolerance or config.CHARACTER_DELTA_E)
    dark = dark_mask(frame)
    minimum = config.CHARACTER_MIN_AREA * width * height
    blobs = [p for p in components(mask, width, height) if len(p) >= minimum]
    blobs.sort(key=len, reverse=True)
    scored = [describe(p, width, height, outline_score(p, mask, dark, width, height))
              for p in blobs[:config.CHARACTER_MAX_CANDIDATES]]
    scored.sort(key=lambda c: (-c["outline"], -c["areaRatio"]))
    return scored


def scale_verdict(height_ratio, bounds):
    low, high = bounds
    return "pass" if low <= height_ratio <= high else "fail"


def scale_from_mask(frame, color, bounds, tolerance=None):
    candidates = character_candidates(frame, color, tolerance)
    top = candidates[0] if candidates else None
    if top is None or top["outline"] < config.OUTLINE_MIN_SCORE:
        return {"method": "color_mask", "verdict": "unmeasured", "reason": "没有带深色描边的主角色块",
                "candidates": candidates}
    rival = next((c for c in candidates[1:] if c["outline"] >= config.OUTLINE_MIN_SCORE
                  and c["areaRatio"] >= config.CHARACTER_RIVAL_AREA * top["areaRatio"]), None)
    result = {"method": "color_mask", "heightRatio": top["heightRatio"], "box": top["box"],
              "candidates": candidates}
    if rival is not None:
        result.update(verdict="review", reason="存在相近的候选色块，需要评审给出主角框")
        return result
    result["verdict"] = scale_verdict(top["heightRatio"], bounds)
    return result


def scale_from_box(box, bounds):
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("主角框须为 0–1 的 [x0, y0, x1, y1]")
    height_ratio = round(y1 - y0, 3)
    return {"method": "box", "heightRatio": height_ratio, "box": list(box),
            "verdict": scale_verdict(height_ratio, bounds)}


def locate(image, color=None, box=None, tolerance=None):
    """返回主角的 0–1 相对框；给了框就用框，否则按颜色找带描边的色块；找不到返回 None。"""
    if box is not None:
        return list(box)
    if not color:
        return None
    candidates = character_candidates(analysis_frame(image), color, tolerance)
    if candidates and candidates[0]["outline"] >= config.OUTLINE_MIN_SCORE:
        return candidates[0]["box"]
    return None


def expand(box, factor, aspect=None):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = (x1 - x0) * factor / 2, (y1 - y0) * factor / 2
    if aspect:
        half_w = max(half_w, half_h * aspect)
        half_h = max(half_h, half_w / aspect)
    return [cx - half_w, cy - half_h, cx + half_w, cy + half_h]


def crop_relative(image, box):
    x0, y0, x1, y1 = box
    return png.crop(image, int(x0 * image.width), int(y0 * image.height),
                    round(x1 * image.width), round(y1 * image.height))


def character_crop(image, box, size):
    """主角特写：按框放大一圈后裁剪，缩放到边长 size 的正方形，用来看清本相细节。"""
    square = expand(box, config.CROP_MARGIN, aspect=image.height / image.width)
    region = crop_relative(image, square)
    return png.resize(region, size, size)


def canary(image, box, zoom):
    """对照样本：以主角为中心放大 zoom 倍，得到一张已知比例不合格的图。"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = 0.5 / zoom, 0.5 / zoom
    cx = min(max(cx, half_w), 1 - half_w)
    cy = min(max(cy, half_h), 1 - half_h)
    region = crop_relative(image, [cx - half_w, cy - half_h, cx + half_w, cy + half_h])
    return png.resize(region, image.width, image.height)


def contact_sheet(images, columns, thumb_width):
    thumb_height = max(round(thumb_width * images[0].height / images[0].width), 1)
    gap, rows = config.SHEET_GAP, -(-len(images) // columns)
    width = columns * thumb_width + (columns + 1) * gap
    height = rows * thumb_height + (rows + 1) * gap
    canvas = bytearray(bytes(config.SHEET_BACKGROUND) * (width * height))
    for n, image in enumerate(images):
        thumb = png.resize(image, thumb_width, thumb_height)
        left = gap + (n % columns) * (thumb_width + gap)
        top = gap + (n // columns) * (thumb_height + gap)
        _paste(canvas, width, thumb, left, top)
        _label(canvas, width, str(n + 1), left + 6, top + 6)
    return png.Image(width, height, bytes(canvas))


def _paste(canvas, width, thumb, left, top):
    stride = thumb.width * 3
    for y in range(thumb.height):
        start = ((top + y) * width + left) * 3
        canvas[start:start + stride] = thumb.pixels[y * stride:(y + 1) * stride]


def _label(canvas, width, text, left, top):
    scale = config.SHEET_DIGIT_SCALE
    box_w, box_h = (len(text) * 4 + 1) * scale, 6 * scale
    for y in range(top - scale, top + box_h):
        start = (y * width + left - scale) * 3
        canvas[start:start + (box_w + scale) * 3] = bytes(config.SHEET_LABEL_BG) * (box_w + scale)
    for k, digit in enumerate(text):
        for row, bits in enumerate(config.DIGITS[digit]):
            for col in range(3):
                if bits >> (2 - col) & 1:
                    _fill(canvas, width, left + (k * 4 + col) * scale, top + row * scale, scale)


def _fill(canvas, width, x, y, size):
    for yy in range(y, y + size):
        start = (yy * width + x) * 3
        canvas[start:start + size * 3] = bytes(config.SHEET_LABEL_FG) * size
