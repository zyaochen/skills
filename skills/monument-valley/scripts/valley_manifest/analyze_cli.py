"""画面度量命令行：stdout 输出单个 JSON；退出码 0 全部通过 / 1 有图未通过或待评审 / 2 输入或依赖错误。"""

import argparse
import json
import os
from pathlib import Path

from . import config, imaging, png

ORDER = config.VERDICT_ORDER
HINTS = {
    "composition:fail": "构图明显跑偏（画面杂乱或整体过暗）：按 aesthetic-canon 的 C2 / L2 重做，留出大片安静平面并提亮。",
    "composition:review": "构图处于灰区或主角偏边：交给独立评审按 aesthetic-canon 判断，评审 style 不低于 4 才保留。",
    "palette:fail": "色彩偏离风格色板：按 visual-guide 的色板色值重新生成或同图编辑调色，不要只改提示词形容词。",
    "palette:review": "色板覆盖处于灰区：交给独立评审按 style 维度打分，低于下限就重做。",
    "scale:fail": "主角比例超出范围：用同图编辑按相对比例缩小（例如缩到当前约 60%），不要重画整张。",
    "scale:review": "存在相近候选色块：让独立评审在接触表上给出主角框，写进 --boxes 后重跑。",
    "scale:unmeasured": "无法按颜色量主角（默认白袍角色或主色不独特）：由独立评审给出主角框后重跑。",
}


def worst(verdicts):
    return max(verdicts, key=ORDER.index)


def parse_bounds(text):
    low, high = (float(v) for v in text.split(","))
    if not 0 < low < high <= 1:
        raise ValueError("--bounds 须为 0–1 之间的 low,high")
    return low, high


def load_boxes(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("--boxes 文件须为 {图片文件名: [x0, y0, x1, y1]}")
    return data


def file_info(path):
    data = Path(path).read_bytes()
    kind, width, height = png.read_size(data)
    return {"format": kind, "width": width, "height": height, "bytes": len(data)}


def measure_scale(frame, args, bounds, box):
    measured = None
    if args.character_color:
        measured = imaging.scale_from_mask(frame, args.character_color, bounds, args.tolerance)
    if box is None:
        return measured or {"method": "none", "verdict": "unmeasured", "reason": "未提供主角颜色或主角框"}
    boxed = imaging.scale_from_box(box, bounds)
    if measured and measured["verdict"] in {"pass", "fail"} and measured["verdict"] != boxed["verdict"]:
        boxed.update(verdict="review", reason="颜色度量与主角框结论不一致", colorMask=measured)
    return boxed


def analyze_one(path, args, bounds, boxes):
    frame = imaging.analysis_frame(imaging.load_image(path))
    palette = imaging.palette_metrics(frame)
    box = boxes.get(os.path.basename(path), boxes.get(path))
    scale = measure_scale(frame, args, bounds, box)
    composition = imaging.composition_metrics(frame, scale.get("box"))
    return {"path": path, "file": file_info(path), "palette": palette, "scale": scale, "composition": composition,
            "verdict": worst([palette["verdict"], scale["verdict"], composition["verdict"]])}


def hints_for(results):
    keys = []
    for r in results:
        for part in ("palette", "scale", "composition"):
            key = f"{part}:{r[part]['verdict']}"
            if key in HINTS and key not in keys:
                keys.append(key)
    return [HINTS[k] for k in keys]


def run_metrics(args):
    bounds = parse_bounds(args.bounds) if args.bounds else config.DEFAULT_SCALE_BOUNDS
    boxes = load_boxes(args.boxes)
    results = [analyze_one(p, args, bounds, boxes) for p in args.images]
    summary = {v: sum(r["verdict"] == v for r in results) for v in ORDER}
    passed = summary["pass"] == len(results)
    return passed, {"results": results, "summary": summary, "bounds": list(bounds),
                    "actionableHints": hints_for(results)}


def run_sheet(args):
    images = [imaging.load_image(p) for p in args.images]
    sheet = imaging.contact_sheet(images, args.columns, args.thumb_width)
    Path(args.out).write_bytes(png.encode(sheet))
    legend = [{"number": n + 1, "path": p} for n, p in enumerate(args.images)]
    return True, {"results": [{"path": args.out, "width": sheet.width, "height": sheet.height}],
                  "legend": legend, "actionableHints": []}


def run_crops(args):
    boxes = load_boxes(args.boxes)
    crops, legend = [], []
    for n, path in enumerate(args.images, start=1):
        image = imaging.load_image(path)
        box = imaging.locate(image, args.character_color, boxes.get(os.path.basename(path), boxes.get(path)),
                             args.tolerance)
        legend.append({"number": n, "path": path, "box": box, "located": box is not None})
        if box is not None:
            crops.append(imaging.character_crop(image, box, config.CROP_SIZE))
    missing = [e["path"] for e in legend if not e["located"]]
    if crops:
        sheet = imaging.contact_sheet(crops, args.columns, config.CROP_SIZE)
        Path(args.out).write_bytes(png.encode(sheet))
    hints = ["定位不到主角的图由独立评审给出主角框，写进 --boxes 后重跑。"] if missing else []
    body = {"results": [{"path": args.out if crops else None, "located": len(crops), "missing": missing}],
            "legend": legend, "actionableHints": hints}
    return not missing, body


def parse_box(text):
    values = [float(v) for v in text.split(",")]
    if len(values) != 4:
        raise ValueError("--box 须为 x0,y0,x1,y1")
    return values


def run_canary(args):
    image = imaging.load_image(args.baseline)
    box = imaging.locate(image, args.character_color, parse_box(args.box) if args.box else None, args.tolerance)
    if box is None:
        raise ValueError("定位不到主角：请传 --character-color 或 --box")
    Path(args.out).write_bytes(png.encode(imaging.canary(image, box, args.zoom)))
    return True, {"results": [{"path": args.out, "baseline": args.baseline, "zoom": args.zoom, "box": box}],
                  "actionableHints": []}


def run_palette_card(args):
    Path(args.out).write_bytes(png.encode(palette_card()))
    return True, {"results": [{"path": args.out, "palette": config.PALETTE}], "actionableHints": []}


def palette_card(swatch=80):
    colors = [imaging.hex_rgb(h) for h in config.PALETTE.values()]
    columns = 10
    rows = -(-len(colors) // columns)
    width, height = columns * swatch, rows * swatch
    pixels = bytearray(width * height * 3)
    for n, rgb in enumerate(colors):
        left, top = (n % columns) * swatch, (n // columns) * swatch
        for y in range(top, top + swatch):
            start = (y * width + left) * 3
            pixels[start:start + swatch * 3] = bytes(rgb) * swatch
    return png.Image(width, height, bytes(pixels))


def build_parser():
    parser = argparse.ArgumentParser(description="山谷插画的确定性度量：色板覆盖、主角比例、接触表。不做审美判断。")
    sub = parser.add_subparsers(dest="command", required=True)
    metrics = sub.add_parser("metrics", help="逐图度量色板覆盖与主角比例")
    metrics.add_argument("images", nargs="+")
    metrics.add_argument("--character-color", help="主角主色，如 FDD277；默认白袍角色不要传")
    metrics.add_argument("--tolerance", type=float, help="主角主色 ΔE 阈值")
    metrics.add_argument("--bounds", help="主角高度占画面比例 low,high，默认 0.04,0.32")
    metrics.add_argument("--boxes", help="独立评审给出的主角框 JSON：{文件名: [x0,y0,x1,y1]}，0–1 相对坐标")
    sheet = sub.add_parser("sheet", help="生成带编号的接触表 PNG")
    sheet.add_argument("images", nargs="+")
    sheet.add_argument("--out", required=True)
    sheet.add_argument("--columns", type=int, default=3)
    sheet.add_argument("--thumb-width", type=int, default=400)
    crops = sub.add_parser("crops", help="生成主角特写接触表，用于评审本相细节")
    crops.add_argument("images", nargs="+")
    crops.add_argument("--out", required=True)
    crops.add_argument("--character-color")
    crops.add_argument("--tolerance", type=float)
    crops.add_argument("--boxes")
    crops.add_argument("--columns", type=int, default=4)
    canary_cmd = sub.add_parser("canary", help="由已验收基准图生成放大主角的对照样本（已知比例不合格）")
    canary_cmd.add_argument("baseline")
    canary_cmd.add_argument("--out", required=True)
    canary_cmd.add_argument("--character-color")
    canary_cmd.add_argument("--tolerance", type=float)
    canary_cmd.add_argument("--box", help="主角框 x0,y0,x1,y1（0–1 相对坐标）")
    canary_cmd.add_argument("--zoom", type=float, default=config.CANARY_ZOOM)
    card = sub.add_parser("palette-card", help="按 config 色板生成色卡 PNG")
    card.add_argument("--out", required=True)
    return parser


RUNNERS = {"metrics": run_metrics, "sheet": run_sheet, "crops": run_crops, "canary": run_canary,
           "palette-card": run_palette_card}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        passed, body = RUNNERS[args.command](args)
        code = config.EXIT_PASSED if passed else config.EXIT_FAILED
        error, stage, fallback = None, "analyze", None
        if not passed:
            summary = body.get("summary")
            error = (f"{len(body['results']) - summary['pass']} 张图未通过或待评审" if summary
                     else f"{len(body['results'][0]['missing'])} 张图定位不到主角")
            fallback = "按 actionableHints 处理后重跑；度量只是底线，不替代独立评审。"
    except imaging.DependencyError as exc:
        body, code = {"results": [], "actionableHints": ["pip install pillow，或在 macOS 上使用自带 sips；也可先把图片转成 PNG。"]}, config.EXIT_UNREADABLE
        passed, error, stage, fallback = False, str(exc), "dependency", "先把图片转成 8 位 PNG 再运行。"
    except (OSError, ValueError, png.ImageError) as exc:
        body, code = {"results": [], "actionableHints": ["确认图片路径存在、是 PNG 或 JPEG，参数格式正确。"]}, config.EXIT_UNREADABLE
        passed, error, stage, fallback = False, str(exc), "input", "修正输入后重跑。"
    result = {"ok": passed, "command": args.command, "results": [], "summary": {}, "actionableHints": [],
              **body, "error": error, "stage": stage, "fallback": fallback}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code
