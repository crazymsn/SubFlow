"""Build deterministic transparent macOS icons from the original SubFlow artwork."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'assets/brand'


def black_mark(source: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    alpha = ImageOps.invert(source.crop(box).convert('L'))
    # Remove the near-white texture of the supplied paper without changing the mark.
    alpha = alpha.point(lambda value: max(0, min(255, round((value - 8) * 255 / 247))))
    mark = Image.new('RGBA', alpha.size, (12, 13, 15, 0))
    mark.putalpha(alpha)
    return mark


def render_icon(source: Image.Image, *, compact: bool = False) -> Image.Image:
    scale, side = 4, 4096
    mask = Image.new('L', (side, side))
    ImageDraw.Draw(mask).rounded_rectangle((100*scale, 100*scale, 924*scale, 924*scale),
                                           radius=184*scale, fill=255)
    shadow = Image.new('L', (side, side))
    shadow.paste(mask, (0, 9*scale))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10*scale)).point(lambda x: round(x * .16))
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    shade = Image.new('RGBA', (side, side), (18, 22, 28, 0))
    shade.putalpha(shadow)
    canvas.alpha_composite(shade)
    tile = Image.new('RGBA', (side, side))
    draw = ImageDraw.Draw(tile)
    for y in range(side):
        t = max(0, min(1, (y/scale - 100) / 824))
        level = round(255 - 14 * t*t)
        draw.line((0, y, side, y), fill=(level, level, min(255, level+1), 255))
    tile.putalpha(mask)
    canvas.alpha_composite(tile)
    cloud = black_mark(source, (202, 216, 1047, 792))
    width = 680 if compact else 610
    height = round(width * cloud.height/cloud.width)
    cloud = cloud.resize((width*scale, height*scale), Image.Resampling.LANCZOS)
    y = (1024-height)//2 if compact else 250
    canvas.alpha_composite(cloud, ((side-cloud.width)//2, y*scale))
    if not compact:
        word = black_mark(source, (214, 886, 1074, 1055))
        width = 530
        word = word.resize((width*scale, round(width*word.height/word.width)*scale), Image.Resampling.LANCZOS)
        canvas.alpha_composite(word, ((side-word.width)//2, 715*scale))
    return canvas.resize((1024, 1024), Image.Resampling.LANCZOS)


def build(output: Path, preview: Path | None = None) -> None:
    source = Image.open(BRAND/'subflow-macos-original.png').convert('RGBA')
    if source.size != (1254, 1254):
        raise ValueError('The original 1254×1254 SubFlow artwork is required')
    normal, compact = render_icon(source), render_icon(source, compact=True)
    for icon in (normal, compact):
        assert icon.getpixel((0, 0))[3] == 0
        assert icon.getpixel((1023, 1023))[3] == 0
    normal.save(BRAND/'subflow-macos.png')
    compact.save(BRAND/'subflow-macos-small.png')
    output.mkdir(parents=True, exist_ok=True)
    iconset = output/'SubFlow.iconset'
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        base = compact if size <= 32 else normal
        for factor in (1, 2):
            suffix = '@2x' if factor == 2 else ''
            base.resize((size*factor, size*factor), Image.Resampling.LANCZOS).save(
                iconset/f'icon_{size}x{size}{suffix}.png')
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(output/'SubFlow.icns')], check=True)
    if preview:
        sheet = Image.new('RGB', (900, 550), '#eceef1')
        ImageDraw.Draw(sheet).rectangle((0, 275, 900, 550), fill='#24262b')
        for row in range(2):
            x = 24
            for size in (16, 32, 64, 128, 256):
                base = compact if size <= 64 else normal
                icon = base.resize((size, size), Image.Resampling.LANCZOS)
                sheet.paste(icon, (x, row*275+(275-size)//2), icon)
                x += size + 45
        preview.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(preview)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build')
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args()
    build(args.output, args.preview)
