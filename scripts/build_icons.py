#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PWA用のアイコンを icons/ に生成する。

  使い方:  python scripts/build_icons.py
  必要:    pip install Pillow
"""

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow が必要です:  pip install Pillow", file=sys.stderr)
    sys.exit(1)

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]
BG = (61, 87, 64)          # --sage-dark
RING = (237, 217, 138)     # --ochre-light
MARK = (253, 250, 245)     # --warm-white


def draw_icon(size):
    """濃緑の角丸地に、消防の纏（まとい）を思わせる縦のしるしを置く。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)

    # 外周のリング
    m = int(s * 0.14)
    d.ellipse([m, m, s - m, s - m], outline=RING, width=max(2, int(s * 0.022)))

    # 中央の縦棒と横帯
    bar_w = int(s * 0.085)
    d.rounded_rectangle(
        [(s - bar_w) // 2, int(s * 0.29), (s + bar_w) // 2, int(s * 0.74)],
        radius=bar_w // 2, fill=MARK,
    )
    band_w, band_h = int(s * 0.34), int(s * 0.075)
    d.rounded_rectangle(
        [(s - band_w) // 2, int(s * 0.32), (s + band_w) // 2, int(s * 0.32) + band_h],
        radius=band_h // 2, fill=MARK,
    )
    dot = int(s * 0.055)
    d.ellipse([(s - dot) // 2, int(s * 0.77), (s + dot) // 2, int(s * 0.77) + dot], fill=RING)

    return img.resize((size, size), Image.LANCZOS)


def main():
    out = Path(__file__).resolve().parent.parent / "icons"
    out.mkdir(exist_ok=True)
    for size in SIZES:
        path = out / "icon-{}.png".format(size)
        draw_icon(size).save(path)
        print("生成: {} ({} bytes)".format(path.name, path.stat().st_size))
    print("完了: {} 個のアイコンを生成しました".format(len(SIZES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
