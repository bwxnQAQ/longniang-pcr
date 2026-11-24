"""用 assets/logo.png 做 exe 的图标 launcher.ico（16 ~ 256 七个尺寸）。
小尺寸按老规矩存成位图（带透明遮罩），256 的存成 PNG——这是 Windows 图标的标准写法。
用法：python make_ico.py <logo.png> <launcher.ico>
"""
import io
import struct
import sys

from PIL import Image

SIZES = (16, 24, 32, 48, 64, 128, 256)


def dib(im: Image.Image) -> bytes:
    w, h = im.size
    px = im.tobytes("raw", "BGRA")
    rows = [px[y * w * 4:(y + 1) * w * 4] for y in range(h)]
    xor = b"".join(reversed(rows))                       # 位图是从下往上存的
    stride = (w + 31) // 32 * 4
    alpha = im.getchannel("A").tobytes()
    mask_rows = []
    for y in range(h):
        row = bytearray(stride)
        for x in range(w):
            if alpha[y * w + x] == 0:                    # 全透明的点：遮罩位 = 1
                row[x // 8] |= 0x80 >> (x % 8)
        mask_rows.append(bytes(row))
    mask = b"".join(reversed(mask_rows))
    head = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0)
    return head + xor + mask


def png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def build(src: str, dst: str) -> None:
    logo = Image.open(src).convert("RGBA")
    blobs = []
    for s in SIZES:
        im = logo.resize((s, s), Image.LANCZOS)
        blobs.append(png(im) if s >= 256 else dib(im))
    out = struct.pack("<HHH", 0, 1, len(SIZES))
    off = 6 + 16 * len(SIZES)
    for s, b in zip(SIZES, blobs):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    with open(dst, "wb") as f:
        f.write(out + b"".join(blobs))


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
