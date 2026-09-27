#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Material Design 3 のトーナルパレットとカラーロールを生成する。

  使い方:  python scripts/build_m3_theme.py [--seed "#5C7A5F"]

M3 は「ひとつのソースカラーから5つのキーカラーを作り、
それぞれのトーナルパレットからロールにトーンを割り当てる」という組み立て方をする
（m3.material.io/styles/color/system/how-the-system-works）。
ソースカラーは設計者が手で選んでよいとされているので、
このアプリがこれまで使ってきたセージ色をそのまま種にする。
そうすれば M3 の体系に乗りつつ、アプリの見た目の素性は変わらない。

トーンは CIELAB の L* に対応させ、色域からはみ出す分は彩度を落として収める。
Material Color Utilities は HCT（CAM16 ベース）を使うが、
ここでは外部依存なしで近い結果が出る CIELCH で代用している。
"""

import argparse
import json
import math
from pathlib import Path

# ---------------------------------------------------------------- 色変換
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


D65 = (0.95047, 1.0, 1.08883)


def hex_to_lch(hex_color):
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    r, g, b = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / D65[0]), f(y / D65[1]), f(z / D65[2])
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    C = math.hypot(a, bb)
    H = math.degrees(math.atan2(bb, a)) % 360
    return L, C, H


def lch_to_rgb(L, C, H):
    """色域外なら None。呼び出し側で彩度を落として再試行する。"""
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200

    def finv(t):
        return t ** 3 if t ** 3 > 216 / 24389 else (108 / 841) * (t - 4 / 29)

    x = finv(fx) * D65[0]
    y = finv(fy) * D65[1]
    z = finv(fz) * D65[2]
    r = x * 3.2404542 + y * -1.5371385 + z * -0.4985314
    g = x * -0.9692660 + y * 1.8760108 + z * 0.0415560
    bl = x * 0.0556434 + y * -0.2040259 + z * 1.0572252
    out = []
    for v in (r, g, bl):
        v = linear_to_srgb(v)
        if v < -0.0008 or v > 1.0008:
            return None
        out.append(min(1.0, max(0.0, v)))
    return out


def tone(hue, chroma, t):
    """指定トーンの色を出す。収まるまで彩度を落とす。"""
    c = chroma
    while c >= 0:
        rgb = lch_to_rgb(t, c, hue)
        if rgb:
            return '#%02X%02X%02X' % tuple(round(v * 255) for v in rgb)
        c -= 0.5
    return '#000000'


TONES = [0, 4, 5, 6, 10, 12, 17, 20, 22, 24, 30, 35, 40, 50, 60, 70, 80, 87, 90, 92, 94, 95, 96, 98, 99, 100]


def palette(hue, chroma):
    return {t: tone(hue, chroma, t) for t in TONES}


# ---------------------------------------------------------------- ロール割当
# M3 のロールは、明るい配色と暗い配色でパレットの別のトーンを指す。
ROLES = {
    'primary':                      ('P', 40, 80),
    'on-primary':                   ('P', 100, 20),
    'primary-container':            ('P', 90, 30),
    'on-primary-container':         ('P', 10, 90),
    'inverse-primary':              ('P', 80, 40),
    'secondary':                    ('S', 40, 80),
    'on-secondary':                 ('S', 100, 20),
    'secondary-container':          ('S', 90, 30),
    'on-secondary-container':       ('S', 10, 90),
    'tertiary':                     ('T', 40, 80),
    'on-tertiary':                  ('T', 100, 20),
    'tertiary-container':           ('T', 90, 30),
    'on-tertiary-container':        ('T', 10, 90),
    'error':                        ('E', 40, 80),
    'on-error':                     ('E', 100, 20),
    'error-container':              ('E', 90, 30),
    'on-error-container':           ('E', 10, 90),
    'surface':                      ('N', 98, 6),
    'on-surface':                   ('N', 10, 90),
    'surface-dim':                  ('N', 87, 6),
    'surface-bright':               ('N', 98, 24),
    'surface-container-lowest':     ('N', 100, 4),
    'surface-container-low':        ('N', 96, 10),
    'surface-container':            ('N', 94, 12),
    'surface-container-high':       ('N', 92, 17),
    'surface-container-highest':    ('N', 90, 22),
    'inverse-surface':              ('N', 20, 90),
    'inverse-on-surface':           ('N', 95, 20),
    'surface-variant':              ('V', 90, 30),
    'on-surface-variant':           ('V', 30, 80),
    'outline':                      ('V', 50, 60),
    'outline-variant':              ('V', 80, 30),
    'scrim':                        ('N', 0, 0),
    'shadow':                       ('N', 0, 0),
}


def build(seed):
    L, C, H = hex_to_lch(seed)
    # Material Color Utilities の既定スキームにならった彩度の取り方
    pals = {
        'P': palette(H, max(48.0, C)),
        'S': palette(H, 16.0),
        'T': palette((H + 60) % 360, 24.0),
        # ニュートラルはソースの色相をわずかに帯びる。
        # M3 の既定は4/8だが、緑の色相では面全体が緑に寄って見えるため少し抑えた。
        'N': palette(H, 2.5),
        'V': palette(H, 6.0),
        'E': palette(25.0, 84.0),
    }
    light = {k: pals[p][lt] for k, (p, lt, dk) in ROLES.items()}
    dark = {k: pals[p][dk] for k, (p, lt, dk) in ROLES.items()}
    return pals, light, dark, (L, C, H)


def contrast(hex1, hex2):
    def lum(h):
        h = h.lstrip('#')
        c = [srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = lum(hex1), lum(hex2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = [
    ('on-surface', 'surface'), ('on-surface-variant', 'surface'),
    ('on-primary', 'primary'), ('on-primary-container', 'primary-container'),
    ('on-secondary-container', 'secondary-container'),
    ('on-tertiary-container', 'tertiary-container'),
    ('on-error-container', 'error-container'),
    ('on-surface', 'surface-container'), ('on-surface', 'surface-container-high'),
    ('outline', 'surface'),
]


def css(light, dark):
    def block(d, indent='  '):
        return '\n'.join('%s--md-%s: %s;' % (indent, k, v) for k, v in d.items())
    return (':root{\n' + block(light) + '\n}\n\n'
            '@media (prefers-color-scheme: dark){\n  :root:not([data-theme="light"]){\n'
            + block(dark, '    ') + '\n  }\n}\n\n'
            ':root[data-theme="dark"]{\n' + block(dark) + '\n}\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', default='#5C7A5F',
                    help='ソースカラー（既定はこのアプリが使ってきたセージ）')
    ap.add_argument('--out', default='data/m3-theme.json')
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    pals, light, dark, (L, C, H) = build(args.seed)

    print('ソースカラー %s  →  L*=%.1f  C=%.1f  H=%.1f°' % (args.seed, L, C, H))
    print('キーカラー（トーン40 / 80）')
    for k, name in [('P', 'primary'), ('S', 'secondary'), ('T', 'tertiary'),
                    ('N', 'neutral'), ('V', 'neutral variant'), ('E', 'error')]:
        print('  %-16s %s / %s' % (name, pals[k][40], pals[k][80]))

    print('\nコントラスト比（前景 / 背景）')
    ok = True
    for fg, bg in PAIRS:
        for label, scheme in (('明', light), ('暗', dark)):
            r = contrast(scheme[fg], scheme[bg])
            mark = 'OK ' if r >= 4.5 else ('3:1' if r >= 3.0 else 'NG ')
            if r < 3.0:
                ok = False
            print('  %s %-4s %-26s on %-26s %5.2f  %s' % (label, '', fg, bg, r, mark))

    out = root / args.out
    out.write_text(json.dumps({
        'seed': args.seed, 'lch': {'L': L, 'C': C, 'H': H},
        'palettes': pals, 'light': light, 'dark': dark,
    }, ensure_ascii=False, indent=1), encoding='utf-8')

    cssout = root / 'data' / 'm3-theme.css'
    cssout.write_text(css(light, dark), encoding='utf-8')
    print('\n%s と %s を書き出しました' % (args.out, 'data/m3-theme.css'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
