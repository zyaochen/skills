"""测试用的合成图片：已知答案的色块、描边与 PNG 变体。"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "skills" / "monument-valley" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from valley_manifest import config, png  # noqa: E402

IVORY = (0xF8, 0xF5, 0xEE)
POTATO = (0xFD, 0xD2, 0x77)
OUTLINE = (0x3A, 0x2A, 0x20)
RED = (0xE0, 0x10, 0x20)


class Canvas:
    def __init__(self, width: int, height: int, fill=IVORY) -> None:
        self.width, self.height = width, height
        self.pixels = bytearray(bytes(fill) * (width * height))

    def rect(self, x0: int, y0: int, x1: int, y1: int, color) -> "Canvas":
        for y in range(y0, y1):
            start = (y * self.width + x0) * 3
            self.pixels[start:(y * self.width + x1) * 3] = bytes(color) * (x1 - x0)
        return self

    def outlined(self, x0: int, y0: int, x1: int, y1: int, fill=POTATO, border: int = 2) -> "Canvas":
        self.rect(x0 - border, y0 - border, x1 + border, y1 + border, OUTLINE)
        return self.rect(x0, y0, x1, y1, fill)

    def image(self) -> png.Image:
        return png.Image(self.width, self.height, bytes(self.pixels))

    def save(self, path: Path) -> Path:
        path.write_bytes(png.encode(self.image()))
        return path


def character_scene(height_ratio: float, width: int = 320, height: int = 180) -> Canvas:
    body = max(2, round(height * height_ratio))
    top = (height - body) // 2
    return Canvas(width, height).outlined(150, top, 150 + max(2, body * 2 // 3), top + body)


def custom_png(rows: list[bytes], width: int, height: int, color: int, filters: list[int],
               palette: bytes = b"") -> bytes:
    """按指定行过滤类型编码 PNG；rows 为未过滤的原始行。"""
    bpp = config_channels(color)
    out, prev = bytearray(), bytes(len(rows[0]))
    for row, kind in zip(rows, filters):
        out.append(kind)
        out += apply_filter(kind, row, prev, bpp)
        prev = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    body = chunk(b"IHDR", header) + (chunk(b"PLTE", palette) if palette else b"")
    return png.SIGNATURE + body + chunk(b"IDAT", zlib.compress(bytes(out))) + chunk(b"IEND", b"")


def config_channels(color: int) -> int:
    return png.CHANNELS[color]


def apply_filter(kind: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    out = bytearray()
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        up, up_left = prev[i], prev[i - bpp] if i >= bpp else 0
        predictor = (0, left, up, (left + up) >> 1, png.paeth(left, up, up_left))[kind]
        out.append((value - predictor) & 0xFF)
    return bytes(out)


def minimal_jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


__all__ = ["Canvas", "IVORY", "OUTLINE", "POTATO", "RED", "character_scene", "config",
           "custom_png", "minimal_jpeg", "png"]
