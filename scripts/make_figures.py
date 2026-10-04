# -*- coding: utf-8 -*-
"""生成 README 配图：波形对比 + 频谱对比（合成示例，可复现）"""
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import core

OUT = os.path.join(ROOT, "docs", "images")
os.makedirs(OUT, exist_ok=True)
SR = core.SR
DUR = 4.0


def font(sz):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\segoeui.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def make_demo():
    """合成示例：单音低频"伴奏" + 中频谐波"人声"（1~2、3~4 秒有声，2~3 秒间奏）"""
    n = int(SR * DUR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(11)

    # 伴奏：单一 70Hz 低音 + 少量 3kHz 宽频噪声（模拟底鼓/镲片），不与人声频段重叠
    music = 0.40 * np.sin(2 * np.pi * 70 * t)
    music += 0.035 * rng.standard_normal(n) * np.sin(2 * np.pi * 3000 * t)
    # 人声：中频谐波（300Hz 基频），带颤音与句子包络，间奏时段静音
    vib = 1.0 + 0.01 * np.sin(2 * np.pi * 5 * t)
    env = np.zeros(n)
    env[int(0.15 * SR):int(1.9 * SR)] = 1.0
    env[int(3.0 * SR):int(3.85 * SR)] = 1.0
    voice = sum(a * np.sin(2 * np.pi * 300 * k * t * vib) for k, a in
                ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.10)))
    voice = 0.20 * voice * env
    x = (music + voice).astype(np.float32)
    x = x / max(np.abs(x).max(), 1e-9) * 0.85
    return np.vstack([x, x])


def draw_wave(rows, labels, colors, path, title, note, w=1200, h=520):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.text((28, 18), title, font=font(24), fill="#111111")
    d.text((28, 52), note, font=font(14), fill="#777777")
    left, right = 210, w - 40
    top, rh, ph = 96, 118, 82
    n = right - left
    for i, (row, lab, col) in enumerate(zip(rows, labels, colors)):
        y0 = top + i * rh
        ymid = y0 + ph // 2
        d.text((28, ymid - 9), lab, font=font(15), fill="#222222")
        d.line([(left, y0), (right, y0)], fill="#f0f0f0")
        d.line([(left, ymid), (right, ymid)], fill="#e8e8e8")
        m = row.mean(axis=0)
        env = m[np.linspace(0, m.size - 1, n).astype(int)]
        pk = max(np.abs(env).max(), 1e-9)
        zs = ymid - (env / pk) * (ph / 2 - 4)
        for x in range(1, n):
            d.line([(left + x - 1, zs[x - 1]), (left + x, zs[x])], fill=col)
    ax = top + len(rows) * rh
    for sec in range(0, int(DUR) + 1):
        x = left + int(sec / DUR * n)
        d.line([(x, ax), (x, ax + 5)], fill="#bbbbbb")
        d.text((x - 4, ax + 9), "%ds" % sec, font=font(12), fill="#888888")
    img.save(path)
    print("  已生成", path)


def spec_grid(signals, labels, path, title, note, w=1180, h=660):
    """上下排列多张频谱图（log 频率轴，低频在下）。

    关键：所有行共用同一色标，基准取第一行（原曲）的峰值——逐行各自归一化会把
    伴奏轨里仅剩的一点残响拉亮，看上去像没分离干净，与数值不符。
    """
    nfft, hop = 1024, 256
    win = np.hanning(nfft)
    freqs = np.fft.rfftfreq(nfft, 1 / SR)[:nfft // 2]
    target = np.logspace(np.log10(40), np.log10(16000), 300)
    idx = np.searchsorted(freqs, target).clip(0, len(freqs) - 1)

    raw = []
    ref = None
    for x in signals:
        m = x.mean(axis=0)
        frames = 1 + (len(m) - nfft) // hop
        S = np.empty((nfft // 2, frames))
        for i in range(frames):
            S[:, i] = np.abs(np.fft.rfft(m[i * hop:i * hop + nfft] * win))[:nfft // 2]
        S = 20 * np.log10(S + 1e-6)
        if ref is None:
            ref = S.max()
        raw.append(S[idx])
    lo, hi = ref - 78, ref                        # 共用动态范围
    rows = [np.clip((S - lo) / (hi - lo), 0, 1) for S in raw]

    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.text((26, 14), title, font=font(21), fill="#111111")
    d.text((26, 44), note, font=font(13), fill="#777777")

    left, right = 150, w - 30
    top = 78
    row_h = (h - top - 34) // len(rows)
    ph = row_h - 34
    pw = right - left
    stops = [(255, 255, 255), (176, 226, 216), (60, 158, 200), (44, 62, 132), (18, 10, 58)]

    for r, (S, lab) in enumerate(zip(rows, labels)):
        y0 = top + r * row_h
        d.text((26, y0 + ph // 2 - 8), lab, font=font(14), fill="#222222")
        nf = S.shape[0]
        for j in range(nf):
            yy0 = y0 + int((nf - 1 - j) * ph / nf)      # 低频画在下方
            yy1 = y0 + int((nf - j) * ph / nf)
            for i in range(0, pw, 2):
                v = S[j, int(i / pw * S.shape[1])]
                p = v * (len(stops) - 1)
                k = min(int(p), len(stops) - 2)
                f = p - k
                c = tuple(int(stops[k][q] + (stops[k + 1][q] - stops[k][q]) * f) for q in range(3))
                d.rectangle([left + i, yy0, left + i + 1, yy1], fill=c)
        d.rectangle([left, y0, right, y0 + ph], outline="#cccccc")
        # 频率刻度标在行的左侧外部，避免压在行名上
        for hz, lab2 in ((100, "100Hz"), (1000, "1kHz"), (10000, "10kHz")):
            j = int(np.argmin(np.abs(target - hz)))
            y = y0 + int((nf - 1 - j) * ph / nf)
            if y0 + 8 <= y <= y0 + ph - 2:
                d.line([(left - 4, y), (left, y)], fill="#aaaaaa")
                d.text((left - 46, y - 6), lab2, font=font(10), fill="#888888")
        for sec in range(0, int(DUR) + 1):
            x = left + int(sec / DUR * pw)
            d.line([(x, y0 + ph), (x, y0 + ph + 4)], fill="#999999")
            d.text((x - 4, y0 + ph + 7), "%ds" % sec, font=font(11), fill="#666666")
    d.text((18, h - 18), "纵轴频率（对数）/ 横轴时间", font=font(11), fill="#888888")
    img.save(path)
    print("  已生成", path)


def main():
    tmp = tempfile.mkdtemp(prefix="voicesplit_fig_")
    mix = make_demo()
    src = os.path.join(tmp, "demo.wav")
    core.write_wav(src, mix)
    print("合成示例已写入，开始跑分离（两种强度）…")

    res = {}
    for strength in ("normal", "strong"):
        d = os.path.join(tmp, strength)
        os.makedirs(d, exist_ok=True)
        files = core.separate(src, d, model_set="标准（推荐）", fmt=(), preview=False,
                              strength=strength, log=lambda s: None)
        voc, _ = core.read_audio([f for f in files if "人声" in f][0])
        inst, _ = core.read_audio([f for f in files if "伴奏" in f][0])
        res[strength] = (voc, inst)
        print("  %s 完成（人声 RMS %.4f）" % (strength, np.sqrt((voc ** 2).mean())))

    draw_wave([mix, res["normal"][0], res["normal"][1]],
              ["原曲（人声 + 伴奏）", "人声轨", "伴奏轨"],
              [(90, 90, 90), (192, 57, 43), (31, 111, 178)],
              os.path.join(OUT, "demo_waveform.png"),
              "VoiceSplit 分离结果（内置合成示例）",
              "4 秒合成示例：低频伴奏 + 中频人声，第 2~3 秒为无人声的间奏段")

    spec_grid([mix, res["normal"][0], res["normal"][1]],
              ["原曲", "人声轨", "伴奏轨"],
              os.path.join(OUT, "demo_spectrogram.png"),
              "频谱对比（掩蔽式，内置合成示例）",
              "人声轨保留中频谐波、低频伴奏在间奏段消失；伴奏轨反之，两者相加可还原原曲")
    print("\n完成，输出目录：%s" % OUT)


if __name__ == "__main__":
    main()
