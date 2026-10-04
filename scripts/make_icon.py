# -*- coding: utf-8 -*-
"""
生成工具图标：一个被“分离”成两半的声波
左半 = 人声（暖白），右半 = 背景音乐（青蓝），中间一道缝隙表示分离
输出：icon.ico（多尺寸）+ 图标预览.png
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4                                  # 超采样倍数
S = 1024                                # 设计尺寸
OUT = os.path.dirname(os.path.abspath(__file__))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def main():
    W = S * SS
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    # ---- 背景：深蓝到青色的对角渐变 ----
    top = (24, 38, 74)
    bot = (16, 92, 122)
    grad = Image.new("RGB", (W, W))
    gd = grad.load()
    for y in range(W):
        for x in range(0, W, 8):        # 每 8 像素一算，够平滑
            t = (x / W * 0.35 + y / W * 0.65)
            c = lerp(top, bot, t)
            for k in range(8):
                if x + k < W:
                    gd[x + k, y] = c
    img.paste(grad, (0, 0))
    img.putalpha(rounded_mask(W, int(W * 0.22)))

    # ---- 内侧高光边 ----
    hl = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    inset = int(W * 0.045)
    hd.rounded_rectangle([inset, inset, W - inset, W - inset],
                         radius=int(W * 0.18), outline=(255, 255, 255, 42),
                         width=int(W * 0.012))
    img = Image.alpha_composite(img, hl)

    d = ImageDraw.Draw(img)
    cx = W / 2
    gap = W * 0.030                      # 中间的“分离”缝隙
    base_y = W * 0.50
    max_h = W * 0.34
    n = 5                                # 每侧条数（小尺寸下仍可分辨）
    span = W * 0.355 / n                 # 条中心间距
    bw = W * 0.058                       # 声波条宽度

    # 条高：中间高两边低，带不规则起伏，像真实波形
    profile = [0.32, 0.66, 1.00, 0.72, 0.40]

    left_col = (252, 252, 254)           # 人声：暖白
    right_col = (88, 216, 238)           # 伴奏：青蓝

    for i in range(n):
        h = max_h * profile[i]
        r = bw / 2
        xr = cx + gap + i * span
        xl = cx - gap - i * span
        d.rounded_rectangle([xr - bw / 2, base_y - h / 2, xr + bw / 2, base_y + h / 2],
                            radius=r, fill=right_col + (255,))
        d.rounded_rectangle([xl - bw / 2, base_y - h / 2, xl + bw / 2, base_y + h / 2],
                            radius=r, fill=left_col + (255,))

    # ---- 缝隙里的柔光，强化“分离”感 ----
    glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(glow)
    gdr.rectangle([cx - gap * 0.55, base_y - max_h * 0.62,
                   cx + gap * 0.55, base_y + max_h * 0.62],
                  fill=(255, 255, 255, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.012))
    img = Image.alpha_composite(img, glow)

    # ---- 缩回目标尺寸 ----
    icon = img.resize((S, S), Image.LANCZOS)

    preview = os.path.join(OUT, "图标预览.png")
    icon.save(preview)

    ico = os.path.join(OUT, "icon.ico")
    icon.save(ico, format="ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)])
    print("已生成:", ico)
    print("预览:", preview)

    # 顺便输出一张小尺寸预览拼图，便于检查小图标可读性
    strip = Image.new("RGBA", (16 + 24 + 32 + 48 + 64 + 20 * 6, 80), (245, 246, 248, 255))
    x = 10
    for s in (16, 24, 32, 48, 64):
        ic = icon.resize((s, s), Image.LANCZOS)
        strip.paste(ic, (x, 10 + (64 - s) // 2), ic)
        x += s + 20
    sp = os.path.join(OUT, "图标小尺寸检查.png")
    strip.resize((strip.width * 2, strip.height * 2), Image.NEAREST).save(sp)
    print("小尺寸检查:", sp)


if __name__ == "__main__":
    main()
