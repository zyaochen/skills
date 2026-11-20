"""标准库 PNG 编解码与 PNG/JPEG 尺寸读取；只支持 8 位、非隔行 PNG。"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class ImageError(ValueError):
    """图片无法按本模块支持的格式读取。"""


class Image:
    """RGB 像素：pixels 为 width*height*3 的 bytes，行优先。"""

    def __init__(self, width, height, pixels):
        self.width, self.height, self.pixels = width, height, pixels

    def rgb(self, x, y):
        i = (y * self.width + x) * 3
        return self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]


def read_chunks(data):
    if not data.startswith(SIGNATURE):
        raise ImageError("不是 PNG 文件")
    pos = len(SIGNATURE)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IEND":
            return


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def unfilter_row(kind, row, prev, bpp):
    out = bytearray(row)
    if kind == 1:
        for i in range(bpp, len(out)):
            out[i] = (out[i] + out[i - bpp]) & 0xFF
    elif kind == 2:
        for i in range(len(out)):
            out[i] = (out[i] + prev[i]) & 0xFF
    elif kind == 3:
        for i in range(len(out)):
            left = out[i - bpp] if i >= bpp else 0
            out[i] = (out[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif kind == 4:
        for i in range(len(out)):
            left = out[i - bpp] if i >= bpp else 0
            up_left = prev[i - bpp] if i >= bpp else 0
            out[i] = (out[i] + paeth(left, prev[i], up_left)) & 0xFF
    elif kind != 0:
        raise ImageError(f"未知 PNG 行过滤类型 {kind}")
    return out


def parse_header(chunks):
    header, palette, idat = None, None, []
    for kind, body in chunks:
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat.append(body)
    if header is None:
        raise ImageError("PNG 缺少 IHDR")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or interlace != 0 or color not in CHANNELS:
        raise ImageError("只支持 8 位、非隔行的 PNG")
    if color == 3 and palette is None:
        raise ImageError("索引色 PNG 缺少调色板")
    return width, height, color, palette, b"".join(idat)


def to_rgb(row, color, palette):
    if color == 2:
        return bytes(row)
    if color == 6:
        return bytes(b for i, b in enumerate(row) if i % 4 != 3)
    if color == 3:
        return b"".join(palette[i * 3:i * 3 + 3] for i in row)
    step = CHANNELS[color]
    return bytes(v for g in row[::step] for v in (g, g, g))


def decode(data):
    width, height, color, palette, compressed = parse_header(read_chunks(data))
    bpp = CHANNELS[color]
    stride = width * bpp
    raw = zlib.decompress(compressed)
    if len(raw) < (stride + 1) * height:
        raise ImageError("PNG 像素数据不完整")
    prev, rows = bytearray(stride), []
    for y in range(height):
        start = y * (stride + 1)
        prev = unfilter_row(raw[start], raw[start + 1:start + 1 + stride], prev, bpp)
        rows.append(to_rgb(prev, color, palette))
    return Image(width, height, b"".join(rows))


def encode(image):
    stride = image.width * 3
    raw = b"".join(b"\x00" + image.pixels[y * stride:(y + 1) * stride] for y in range(image.height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
    return SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def jpeg_size(data):
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if marker in JPEG_SOF:
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return width, height
        pos += 2 + length
    raise ImageError("JPEG 缺少尺寸段")


def read_size(data):
    """返回 (格式, 宽, 高)；只读头部，不解码像素。"""
    if data.startswith(SIGNATURE):
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:2] == b"\xff\xd8":
        return ("jpeg",) + jpeg_size(data)
    raise ImageError("不是 PNG 或 JPEG")


def crop(image, left, top, right, bottom):
    left, top = max(0, left), max(0, top)
    right, bottom = min(image.width, right), min(image.height, bottom)
    if right <= left or bottom <= top:
        raise ImageError("裁剪框为空")
    stride = image.width * 3
    rows = [image.pixels[y * stride + left * 3:y * stride + right * 3] for y in range(top, bottom)]
    return Image(right - left, bottom - top, b"".join(rows))


def resize(image, width, height):
    """最近邻缩放；只用于接触表缩略图与抽样分析。"""
    xs = [x * image.width // width for x in range(width)]
    out = bytearray()
    for y in range(height):
        base = (y * image.height // height) * image.width
        for x in xs:
            i = (base + x) * 3
            out += image.pixels[i:i + 3]
    return Image(width, height, bytes(out))
