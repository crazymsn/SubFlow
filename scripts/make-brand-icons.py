"""Build SubFlow lockup, header mark, and Windows ICO."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

CREAM = (243, 237, 226, 255)
VOID = (20, 24, 32, 255)


def _bbox_ink(im: Image.Image, threshold: int = 240) -> tuple[int, int, int, int]:
    gray = im.convert("L")
    mask = gray.point(lambda p: 255 if p < threshold else 0)
    box = mask.getbbox()
    if not box:
        raise SystemExit("logo has no ink")
    return box


def _cloud_only(im: Image.Image) -> Image.Image:
    left, top, right, bottom = _bbox_ink(im)
    region = im.crop((left, top, right, bottom))
    gray = region.convert("L")
    w, h = gray.size
    gap_start = None
    for y in range(h):
        row = list(gray.crop((0, y, w, y + 1)).convert("L").getdata())
        ink = any(p < 240 for p in row)
        if not ink and gap_start is None and y > h * 0.25:
            gap_start = y
        if gap_start is not None and ink:
            if y - gap_start >= 8:
                region = region.crop((0, 0, w, gap_start))
            break
    return region.crop(_bbox_ink(region))


def _ink_to_rgba(im: Image.Image, fill: tuple[int, int, int, int]) -> Image.Image:
    rgba = im.convert("RGBA")
    src = list(rgba.getdata())
    out = []
    fr, fg, fb, _ = fill
    for r, g, b, _a in src:
        if r > 240 and g > 240 and b > 240:
            out.append((0, 0, 0, 0))
            continue
        ink = 255 - (r + g + b) // 3
        out.append((fr, fg, fb, ink))
    rgba.putdata(out)
    return rgba


def _official_lockup_icon(im: Image.Image, size: int, pad_ratio: float = 0.08) -> Image.Image:
    """Client icon = uploaded lockup on a white plate."""
    rgb = im.convert("RGB")
    box = _bbox_ink(rgb)
    cropped = rgb.crop(box)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    pad = max(4, int(size * pad_ratio))
    inner = max(1, size - pad * 2)
    w, h = cropped.size
    scale = inner / max(w, h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    fitted = cropped.resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")
    canvas.paste(fitted, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _square(im: Image.Image, fill: tuple[int, int, int, int], pad_ratio: float) -> Image.Image:
    """Scale the mark to fill a square. Tiny pad only so Windows 16px does not clip."""
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    box = _bbox_ink(im.convert("RGB"))
    im = im.crop(box)
    w, h = im.size
    side = max(w, h)
    pad = max(1, int(side * pad_ratio))
    canvas_side = side + pad * 2
    scale = side / max(w, h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_side, canvas_side), fill)
    canvas.paste(im, ((canvas_side - nw) // 2, (canvas_side - nh) // 2), im)
    return canvas


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dest = root / "assets" / "brand"
    dest.mkdir(parents=True, exist_ok=True)
    master_path = dest / "subflow.png"
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else master_path
    if not src.is_file():
        raise SystemExit(f"missing master logo: {src}")
    if src.resolve() != master_path.resolve():
        shutil.copy2(src, master_path)

    master = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    ink = master.crop(_bbox_ink(master))
    pad = 32
    full = Image.new("RGB", (ink.size[0] + pad * 2, ink.size[1] + pad * 2), (255, 255, 255))
    full.paste(ink, (pad, pad))
    full.save(master_path, "PNG")

    cloud = _cloud_only(master)
    mark = _square(_ink_to_rgba(cloud, (20, 24, 32, 255)), (0, 0, 0, 0), 0.02)
    mark.save(dest / "subflow-mark.png", "PNG")

    ico_mark = _official_lockup_icon(master, 256)
    ico_sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_mark.save(dest / "subflow.ico", format="ICO", sizes=ico_sizes)
    ico_mark.save(dest / "subflow-icon.png", "PNG")
    print(f"wrote {master_path} {full.size}")
    print(f"wrote {dest / 'subflow-mark.png'} {mark.size}")
    print(f"wrote {dest / 'subflow.ico'} {ico_mark.size}")


if __name__ == "__main__":
    main()
