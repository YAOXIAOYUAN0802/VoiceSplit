#!/usr/bin/env python3
"""
三档分离强度对比：对同一段音频分别跑 normal / strong / isolate，
输出客观指标（背景音乐残留、人声频段保留），用于判断该选哪一档。

用法：python scripts/demo_strength.py <音频或视频文件> [起始秒] [时长秒]
"""
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


def rd(path):
    with wave.open(path, "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        return (np.frombuffer(w.readframes(n), dtype="<i2")
                .reshape(-1, ch).T.astype(np.float64) / 32768.0)


def band_rms(x, lo, hi, sr=core.SR):
    from numpy.fft import rfft, rfftfreq
    y = x.mean(axis=0) * np.hanning(x.shape[-1])
    f = rfftfreq(y.size, 1.0 / sr)
    sp = np.abs(rfft(y))
    m = (f >= lo) & (f < hi)
    return float(np.sqrt((sp[m] ** 2).mean()))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 25.0
    if not os.path.exists(src):
        print("找不到文件：%s" % src)
        return 1

    ref, _ = core.read_audio(src, start=start, dur=dur)
    lo_ref, mid_ref = band_rms(ref, 30, 120), band_rms(ref, 300, 3000)
    print("素材 %s  第 %.0f~%.0f 秒" % (os.path.basename(src), start, start + dur))
    print("原曲：低频(音乐) %.1f   中频(人声+音乐) %.1f" % (lo_ref, mid_ref))
    print()
    print("%-10s %-14s %-14s %-10s %s"
          % ("强度", "音乐残留", "人声频段保留", "人声RMS", "耗时"))

    out_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out_demo")
    for strength in ("normal", "strong", "isolate"):
        d = os.path.join(out_root, strength)
        os.makedirs(d, exist_ok=True)
        t0 = time.time()
        files = core.separate(src, d, model_set="标准（推荐）", fmt=(), preview=False,
                              start=start, dur=dur, vocal_boost=True, strength=strength,
                              log=lambda s: None)
        dt = time.time() - t0
        voc, _ = rd([f for f in files if "人声" in f][0])
        res = band_rms(voc, 30, 120) / max(lo_ref, 1e-12)
        keep = band_rms(voc, 300, 3000) / max(mid_ref, 1e-12)
        print("%-10s %-14.4f %-14.3f %-10.4f %.0fs"
              % (strength, res, keep, np.sqrt((voc ** 2).mean()), dt))
    print("\n各档人声/伴奏输出在 out_demo/ 下，可直接试听对比")
    return 0


if __name__ == "__main__":
    sys.exit(main())
