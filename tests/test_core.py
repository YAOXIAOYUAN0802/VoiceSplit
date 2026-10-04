# -*- coding: utf-8 -*-
"""
核心链路自检：不需要任何音频素材，用合成信号验证 STFT/推理/掩蔽/限幅/片段替换。

    python tests/test_core.py

需要 models/ 里至少有一对人声/伴奏模型（scripts/download_models.py）。
"""
import os
import shutil
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core

FAILED = []


def check(name, cond, detail=""):
    print("  %s %s%s" % ("[OK]" if cond else "[X ]", name, ("  " + detail) if detail else ""))
    if not cond:
        FAILED.append(name)


def tone(sec=4.0, sr=core.SR, noise=True):
    """合成信号：低频"音乐" + 中频"人声" + 高频泛音。
    噪声用于打散周期性（60Hz 与 110Hz 是谐波关系，会让整段信号恰好每秒重复，
    导致对齐搜索出现多个等优解，无法验证对齐逻辑）；验证 STFT 往返精度时用
    noise=False，因为宽带噪声会把重建误差推到 float32 累加极限。"""
    t = np.arange(int(sr * sec)) / sr
    rng = np.random.default_rng(0)
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    if noise:
        env = env + 0.15 * rng.standard_normal(t.size)
    music = 0.30 * np.sin(2 * np.pi * 60 * t) + 0.10 * np.sin(2 * np.pi * 137 * t)
    voice = 0.25 * np.sin(2 * np.pi * 700 * t) * env
    hi = 0.05 * np.sin(2 * np.pi * 6000 * t)
    x = (music + voice + hi).astype(np.float32)
    return np.vstack([x, x])


def main():
    print("=" * 58)
    print("VoiceSplit 核心自检")
    print("=" * 58)
    sets = {}
    for name, (v, i) in core.MODEL_SETS.items():
        if core.resolve_model(v) and core.resolve_model(i):
            sets[name] = (v, i)
    print("可用档位：%s" % ("、".join(sets) or "无"))
    check("至少有一个可用模型档位", bool(sets))
    if not sets:
        return 1

    print("\nffmpeg")
    ff = core.find_ffmpeg()
    ok = os.path.exists(ff) or shutil.which(ff)
    check("ffmpeg 可用", ok, ff)
    if ok:
        try:
            core.run_ffmpeg(["-version"])
            check("ffmpeg 可执行", True)
        except Exception as e:
            check("ffmpeg 可执行", False, str(e)[:80])

    print("\n模型维度自适应")
    for name, (v, i) in sets.items():
        try:
            nv, dv, hv, _ = core.mdx_params(core.resolve_model(v))
            ni, di, hi, _ = core.mdx_params(core.resolve_model(i))
            check("%s：人声 n_fft=%d / 伴奏 n_fft=%d" % (name, nv, ni), dv > 0 and di > 0)
        except Exception as e:
            check("%s 读取维度" % name, False, str(e)[:80])

    print("\nSTFT / 反 STFT 往返")
    x = tone(1.0, noise=False)          # 无宽带噪声，才能测出真实重建精度
    nfft, dim_f, hop, win = core.mdx_params(core.resolve_model(sets[list(sets)[0]][0]))
    y = core.istft(core.stft(x, nfft, dim_f, hop, win), x.shape[-1], nfft, dim_f, hop, win)
    err = float(np.abs(y[:, 3000:-3000] - x[:, 3000:-3000]).max())
    check("重建误差 < 1e-5", err < 1e-5, "max=%.2e" % err)

    print("\n完整分离流程（合成信号 3 秒）")
    tmp = tempfile.mkdtemp(prefix="voicesplit_test_")
    src = os.path.join(tmp, "in.wav")
    core.write_wav(src, tone(3.0))
    mix, _ = core.read_audio(src)
    for strength in ("normal", "strong"):
        try:
            files = core.separate(src, os.path.join(tmp, strength), model_set=list(sets)[0],
                                  fmt=("flac",), preview=True, strength=strength,
                                  log=lambda s: None)
            voc = [f for f in files if "人声" in f and f.endswith(".wav")][0]
            inst = [f for f in files if "伴奏" in f and f.endswith(".wav")][0]
            v, _ = core.read_audio(voc)
            i, _ = core.read_audio(inst)
            check("%s：生成 %d 个文件" % (strength, len(files)), len(files) >= 4)
            # 互补性：人声+伴奏 应等于 原曲×输出电平（量化级误差）
            q = np.abs(np.round(v * 32767) + np.round(i * 32767)
                       - np.round(mix[:, :v.shape[-1]] * 0.95 * 32767))
            check("%s：人声+伴奏 保持互补（中位偏差 ≤ 2 级）" % strength,
                  float(np.median(q)) <= 2, "中位=%.1f" % np.median(q))
            check("%s：无削顶（峰值 < 0.999）" % strength,
                  max(np.abs(v).max(), np.abs(i).max()) < 0.999,
                  "峰值=%.4f" % max(np.abs(v).max(), np.abs(i).max()))
        except Exception as e:
            check("%s 流程" % strength, False, str(e)[:100])

    print("\n片段替换")
    try:
        # 用白噪声做主音频：相关度曲面唯一，才能真正验证"对齐到正确位置"
        rng = np.random.default_rng(7)
        n = 4 * core.SR
        noise = (rng.standard_normal(n) * 0.18).astype(np.float32)
        full = np.vstack([noise, noise])
        main_wav = os.path.join(tmp, "main.wav")
        core.write_wav(main_wav, full)
        # 补丁 = 主音频 1.0~2.0 秒那一段的 0.5 倍。整体电平留足余量，
        # 避免拼接后触达限幅门限而导致全文件被统一微衰减（那样"之前未改动"就不成立了）
        patch = os.path.join(tmp, "patch.wav")
        core.write_wav(patch, full[:, core.SR:2 * core.SR] * 0.5)
        before, _ = core.read_audio(main_wav)
        core.patch_segment(main_wav, patch, 1.0, log=lambda s: None)
        after, _ = core.read_audio(main_wav)
        cut = int(1.0 * core.SR)
        check("替换区之前未被改动",
              float(np.abs(after[:, :cut - 100] - before[:, :cut - 100]).max()) < 1e-4)
        check("替换区已写入新片段（对齐到 1.0 秒）",
              float(np.abs(after[:, cut + 3000:cut + 6000]).max()) > 0.01
              and float(np.abs(after[:, cut + 3000:cut + 6000]
                               - before[:, cut + 3000:cut + 6000]).max()) > 0.005)
        check("替换后无削顶", float(np.abs(after).max()) < 0.999,
              "峰值=%.4f" % float(np.abs(after).max()))
        # 内容完全不匹配时应拒绝改动
        other = os.path.join(tmp, "other.wav")
        core.write_wav(other, tone(1.0, noise=False))
        snapshot, _ = core.read_audio(main_wav)
        try:
            core.patch_segment(main_wav, other, 1.0, log=lambda s: None)
            rejected = False
        except RuntimeError:
            rejected = True
        again, _ = core.read_audio(main_wav)
        check("不匹配的片段被拒绝且未改动文件",
              rejected and float(np.abs(again - snapshot).max()) < 1e-6)
    except Exception as e:
        check("片段替换", False, str(e)[:120])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 58)
    print("结果：%s" % ("全部通过" if not FAILED else "失败项 %s" % "、".join(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
