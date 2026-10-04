# -*- coding: utf-8 -*-
"""
人声 / 背景音乐分离核心库（MDX-Net）
"""
import os
import subprocess
import sys
import threading
import wave

import numpy as np

SR = 44100
N_FFT = 6144                       # 默认值（dim_f=3072 系列模型）；实际按模型自动适配
HOP = 1024
DIM_F = N_FFT // 2
SEGMENT = 256
OVERLAP = 0.25
WINDOW_CACHE = {}
CEIL = 10 ** (-1.0 / 20.0)

# 模型组合：速度/质量档位
MODEL_SETS = {
    "标准（推荐）": ("Kim_Vocal_2.onnx", "UVR-MDX-NET-Inst_HQ_3.onnx"),
    "人声突显（歌曲）": ("kuielab_b_vocals.onnx", "UVR-MDX-NET-Inst_HQ_3.onnx"),
    "高精度": ("UVR-MDX-NET-Voc_FT.onnx", "UVR-MDX-NET-Inst_HQ_4.onnx"),
    "轻量快速": ("Kim_Vocal_2.onnx", "UVR-MDX-NET-Inst_Main.onnx"),
}
# 推荐用于「人声突显」模式的人声模型（对歌曲人声提取更彻底）
VOCAL_FIRST_MODELS = ("kuielab_b_vocals.onnx", "UVR-MDX-NET-Voc_FT.onnx", "Kim_Vocal_2.onnx")
CENTER_PRIOR_DEFAULT = 0.7      # 多声道素材的中置先验强度（只参与权重，不改动音频）


class Cancelled(Exception):
    """用户中止"""


def app_dir():
    """源码目录或 exe 解包目录"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource(*parts):
    return os.path.join(app_dir(), *parts)


def resolve_model(name):
    """按优先级查找模型：exe 同目录 models → 打包内置 models"""
    cands = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        cands.append(os.path.join(exe_dir, "models", name))
        cands.append(os.path.join(exe_dir, "_internal", "models", name))
    cands.append(resource("models", name))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def find_ffmpeg():
    """优先用随包/同目录的 ffmpeg.exe，否则回退到系统 PATH"""
    for c in (resource("ffmpeg", "ffmpeg.exe"), resource("ffmpeg.exe"),
              os.path.join(os.path.dirname(app_dir()), "ffmpeg.exe"), "ffmpeg"):
        if c == "ffmpeg" or os.path.exists(c):
            return c
    return "ffmpeg"


def _decode(b):
    """ffmpeg 输出为 UTF-8；中文路径下用 GBK 解码会直接报错，这里统一容错"""
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def run_ffmpeg(args):
    """调用 ffmpeg，隐藏控制台窗口；捕获原始字节后自行解码，避免编码异常中断流程"""
    exe = find_ffmpeg()
    cmd = [exe, "-hide_banner", "-y", "-v", "error"] + args
    kw = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        kw["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败（退出码 %d）：\n%s"
                           % (r.returncode, _decode(r.stderr)[:800]))
    return _decode(r.stdout)


# ---------------- 音频读写 ----------------

def probe_channels(path):
    """返回 (声道数, 有效时长秒)。多声道返回实际声道数；读取失败返回 (0, 0)"""
    import re
    try:
        exe = find_ffmpeg()
        cmd = [exe, "-hide_banner", "-i", path]
        kw = {}
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kw["startupinfo"] = si
            kw["creationflags"] = 0x08000000
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
        txt = _decode(r.stderr)
    except Exception:
        return 0, 0.0
    ch = 0
    dur = 0.0
    m = re.search(r"Audio:\s*[^\n]*?,\s*\d+\s*Hz,\s*([^,\n]+)", txt)
    if m:
        layout = m.group(1).strip().lower()
        if "5.1" in layout:
            ch = 6
        elif "7.1" in layout:
            ch = 8
        elif "quad" in layout:
            ch = 4
        elif "mono" in layout:
            ch = 1
        elif "stereo" in layout:
            ch = 2
    if not ch:
        mch = re.search(r"Audio:\s*[^\n]*?,\s*(\d+)\s*channels", txt)
        if mch:
            ch = int(mch.group(1))
    md = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", txt)
    if md:
        dur = int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3))
    return ch, dur


def is_multichannel(path):
    ch, _ = probe_channels(path)
    return ch >= 6


def read_audio(path, start=None, dur=None, center_boost=False, progress=None):
    """读取音视频为 44.1kHz 立体声 float32 (2, n)

    center_boost=True 且素材为多声道时：立体声折叠 + 中置声道×2.5 叠加
    （环绕混音里人声多在中置，叠加后模型的人声线索明显更强）
    """
    base = []
    if start:
        base += ["-ss", "%.4f" % start]
    base += ["-i", path]
    if dur:
        base += ["-t", "%.4f" % dur]

    out = os.path.join(os.environ.get("TEMP", "."), "_sep_src_%d.wav" % os.getpid())
    boost_used = False
    if center_boost:
        try:
            ch, _ = probe_channels(path)
        except Exception:
            ch = 0
        if ch >= 6:
            fc = os.path.join(os.environ.get("TEMP", "."), "_sep_fc_%d.wav" % os.getpid())
            run_ffmpeg(base + ["-filter_complex", "pan=stereo|c0=FC|c1=FC",
                               "-ar", str(SR), "-c:a", "pcm_s16le", fc])
            run_ffmpeg(base + ["-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", out])
            with wave.open(fc, "rb") as w:
                n, c = w.getnframes(), w.getnchannels()
                cen = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, c).T.astype(np.float32) / 32768.0
            try:
                os.remove(fc)
            except OSError:
                pass
            boost_used = True
        else:
            run_ffmpeg(base + ["-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", out])
    else:
        run_ffmpeg(base + ["-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", out])

    with wave.open(out, "rb") as w:
        n, chn = w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    try:
        os.remove(out)
    except OSError:
        pass
    a = np.frombuffer(raw, dtype="<i2").reshape(-1, chn).T.astype(np.float32) / 32768.0
    if a.shape[0] == 1:
        a = np.vstack([a, a])
    a = a[:2].copy()
    if boost_used:
        a = a + 2.5 * cen[:, :a.shape[-1]]
    return a, boost_used


def write_wav(path, x, sr=SR):
    d = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(d.shape[0])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(d.T.tobytes())
    return d


# ---------------- STFT / 反 STFT（按模型自动适配 FFT 参数）----------------

_params_cache = {}
_session_cache = {}


def open_session(model_path):
    """按模型路径缓存推理会话（同时用于读取维度参数）"""
    s = _session_cache.get(model_path)
    if s is None:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        s = ort.InferenceSession(model_path, sess_options=so,
                                 providers=["CPUExecutionProvider"])
        _session_cache[model_path] = s
    return s


def mdx_params(model_path):
    """读取模型输入形状，返回 n_fft / dim_f / hop / window（MDX-Net 的 hop 为窗口的 1/6）"""
    p = _params_cache.get(model_path)
    if p is None:
        shp = open_session(model_path).get_inputs()[0].shape
        dim_f = int(shp[2])
        n_fft = dim_f * 2
        hop = n_fft // 6
        p = (n_fft, dim_f, hop, window_of(n_fft))
        _params_cache[model_path] = p
    return p


def window_of(n_fft):
    w = WINDOW_CACHE.get(n_fft)
    if w is None:
        w = np.hanning(n_fft).astype(np.float32)
        WINDOW_CACHE[n_fft] = w
    return w


def stft(x, n_fft, dim_f, hop, win):
    xp = np.pad(x, ((0, 0), (0, n_fft)))
    nf = (xp.shape[-1] - n_fft) // hop + 1
    xp = xp[:, : (nf - 1) * hop + n_fft]
    idx = np.arange(n_fft)[None, :] + hop * np.arange(nf)[:, None]
    frames = xp[:, idx]
    spec = np.fft.rfft(frames * win, axis=-1)
    return spec[:, :, :dim_f].transpose(0, 2, 1).astype(np.complex64)


def istft(spec, length, n_fft, dim_f, hop, win):
    ch, _, T = spec.shape
    full = np.zeros((ch, T, dim_f + 1), dtype=np.complex64)
    full[:, :, :dim_f] = spec.transpose(0, 2, 1)
    frames = np.fft.irfft(full, n=n_fft, axis=-1) * win
    out_len = (T - 1) * hop + n_fft
    y = np.zeros((ch, out_len), dtype=np.float32)
    ws = np.zeros(out_len, dtype=np.float32)
    w2 = win ** 2
    for t in range(T):
        s = t * hop
        y[:, s:s + n_fft] += frames[:, t, :]
        ws[s:s + n_fft] += w2
    nz = ws >= 1.0                     # 边缘窗和过小处会放大数值噪声，置零处理
    y[:, nz] /= ws[nz]
    y[:, ~nz] = 0.0
    return y[:, :length]


def to_input(seg, dim_f):
    b = np.zeros((1, 4, dim_f, SEGMENT), dtype=np.float32)
    b[0, 0] = seg[0].real
    b[0, 1] = seg[1].real
    b[0, 2] = seg[0].imag
    b[0, 3] = seg[1].imag
    return b


def from_output(o):
    o = o[0]
    return (o[0] + 1j * o[2], o[1] + 1j * o[3])


# ---------------- 模型推理 ----------------

def _session(model_path, threads=None):
    return open_session(model_path)


def infer(model_path, spec_or_audio, progress=None, canceller=None, label="", length=None,
          want_spec=False):
    """按模型自适应 FFT 参数推理；三角权重重叠相加，输出浮点立体声 (2, n)
    want_spec=True 时返回累积后的复数频谱（用于掩蔽式提取）"""
    import onnxruntime as ort   # noqa: F401  (确保打包时被收集)
    n_fft, dim_f, hop, win = mdx_params(model_path)
    sess = _session(model_path)
    iname = sess.get_inputs()[0].name
    oname = sess.get_outputs()[0].name
    spec = spec_or_audio
    if spec.shape[1] != dim_f:
        raise RuntimeError("频谱维度 %d 与模型所需 %d 不一致" % (spec.shape[1], dim_f))
    _, _, T = spec.shape
    step = int(SEGMENT * (1 - OVERLAP))
    trim = SEGMENT - step
    nc = 1 if T <= SEGMENT else int(np.ceil((T - SEGMENT) / step)) + 1
    if (nc - 1) * step + min(SEGMENT, T - (nc - 1) * step) < T:
        raise RuntimeError("分段覆盖不完整")

    acc = np.zeros((2, dim_f, T), dtype=np.complex64)
    wsum = np.zeros(T, dtype=np.float32)
    rise = np.linspace(0.0, 1.0, trim + 2, dtype=np.float32)[1:-1]
    sre = rise[::-1].copy()
    import time
    t0 = last = time.time()

    for i in range(nc):
        if canceller is not None and canceller():
            raise Cancelled()
        st = i * step
        rem = T - st
        L = min(SEGMENT, max(rem, 1))
        seg = np.zeros((2, dim_f, SEGMENT), dtype=np.complex64)
        seg[:, :, :L] = spec[:, :, st:st + L]
        o = sess.run([oname], {iname: to_input(seg, dim_f)})[0]
        pred = np.stack(from_output(o), axis=0)[:, :, :L]

        # 三角权重：段首淡入、段尾淡出，重叠区权重和为 1
        w = np.ones((1, L), dtype=np.float32)
        a = min(trim, L)
        if a > 0:
            w[0, :a] = rise[:a]
        b = min(trim, L)
        if b > 0:
            w[0, L - b:] = np.minimum(w[0, L - b:], sre[-b:])
        acc[:, :, st:st + L] += pred * w
        wsum[st:st + L] += w[0]
        acc[:, :, st:st + L] /= wsum[st:st + L]

        if progress:
            now = time.time()
            if now - last > 0.2 or i == nc - 1:
                last = now
                progress(int(100 * (i + 1) / nc), "%s %d/%d 段" % (label, i + 1, nc))
    if want_spec:
        return acc
    y = istft(acc, (T - 1) * hop + n_fft, n_fft, dim_f, hop, win).astype(np.float64)
    return y[:, :length] if length else y


def infer_audio(model_path, audio, progress=None, canceller=None, label=""):
    n_fft, dim_f, hop, win = mdx_params(model_path)
    spec = stft(audio, n_fft, dim_f, hop, win)
    return infer(model_path, spec, progress=progress, canceller=canceller,
                 label=label, length=audio.shape[-1])


# ---------------- 后处理 ----------------

def edge_fade(n, n_trim=2048, n_fade=256):
    f = np.ones(max(n, 1), dtype=np.float64)
    f[:max(0, n_trim - n_fade)] = 0.0
    f[n_trim - n_fade:n_trim] = np.linspace(0.0, 1.0, n_fade)
    f[-max(0, n_trim - n_fade):] = 0.0
    f[-n_trim:-n_trim + n_fade] = np.linspace(1.0, 0.0, n_fade)
    return f[:n]


def limit_shared(voc, inst, ref, ceiling=CEIL, win_ms=30.0, release=0.9997):
    """以混合信号计算一条共用增益包络；两轨共用，严格保持互补"""
    from numpy.lib.stride_tricks import sliding_window_view
    win = max(8, int(win_ms / 1000.0 * SR)) | 1
    p = win // 2
    mag = np.abs(ref).max(axis=0)
    xp = np.pad(mag, (p, p), mode="edge")
    env = sliding_window_view(xp, win).max(axis=-1)
    g = np.ones_like(env)
    acc = env[0]
    for i in range(env.size):
        acc = env[i] if env[i] > acc * release else acc * release
        if acc > ceiling:
            g[i] = ceiling / acc
    return voc * g, inst * g, g


def true_peak(x, factor=4):
    from scipy.signal import resample_poly
    return float(np.abs(resample_poly(x, factor, 1, axis=-1)).max())


# ---------------- 对外主流程 ----------------

def _project_mask(m, dim_f, t_frames):
    """把某模型的预测幅度投影到目标频点数 / 帧数（两个模型 FFT 参数不同时使用）"""
    if m.shape[1] != dim_f:
        idx = np.linspace(0, m.shape[1] - 1, dim_f)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, m.shape[1] - 1)
        fr = (idx - lo).reshape(1, -1, 1)
        m = m[:, lo, :] * (1 - fr) + m[:, hi, :] * fr
    if m.shape[-1] != t_frames:
        ti = np.linspace(0, m.shape[-1] - 1, t_frames)
        lo = np.floor(ti).astype(int)
        hi = np.minimum(lo + 1, m.shape[-1] - 1)
        fr = (ti - lo).reshape(1, 1, -1)
        m = m[:, :, lo] * (1 - fr) + m[:, :, hi] * fr
    return m


def extract_masked(mix, voc_model, inst_model, progress=None, canceller=None, log=None,
                   center=None, center_prior=0.0,
                   sharpness=1.0, gate_db=None, gate_smooth_ms=120.0):
    """掩蔽式提取：用模型预测幅度算维纳权重，直接过滤原曲

    人声轨 = 原曲频谱 × 权重（低置信区域留给伴奏，不会糊进人声）
    伴奏轨 = 原曲 − 人声（互补）
    center/center_prior：多声道素材用中置声道做先验，进一步压低背景音乐
    sharpness：权重压缩指数，>1 让判据更果断（人声更突出）
    gate_db：时域门控门限（如 -14），人声概率低的时间帧整体衰减，消除间奏残留
    """
    vp = resolve_model(voc_model)
    ip = resolve_model(inst_model)

    def L(t):
        if log:
            log(t)

    nfft, dim_f, hop, win = mdx_params(vp)
    L("生成原曲频谱…")
    spec = stft(mix, nfft, dim_f, hop, win)
    T = spec.shape[-1]

    L("人声模型预测（%s）…" % voc_model)
    mv = np.abs(infer(vp, spec,
                      progress=(lambda p, t: progress(int(p * 0.4), "人声模型 " + t)
                                if progress else None),
                      canceller=canceller, label="人声", want_spec=True))
    L("伴奏模型预测（%s）…" % inst_model)
    nfft_i, dim_f_i, hop_i, win_i = mdx_params(ip)
    if (nfft_i, dim_f_i) == (nfft, dim_f):
        mi = np.abs(infer(ip, spec,
                          progress=(lambda p, t: progress(int(40 + p * 0.4), "伴奏模型 " + t)
                                    if progress else None),
                          canceller=canceller, label="伴奏", want_spec=True))
    else:
        spec_i = stft(mix, nfft_i, dim_f_i, hop_i, win_i)
        mi = np.abs(infer(ip, spec_i,
                          progress=(lambda p, t: progress(int(40 + p * 0.4), "伴奏模型 " + t)
                                    if progress else None),
                          canceller=canceller, label="伴奏", want_spec=True))
        mi = _project_mask(mi, dim_f, T)

    L("计算分离权重并过滤…")
    w = np.clip(mv / (mv + mi + 1e-9), 0.0, 1.0)
    if sharpness and abs(sharpness - 1.0) > 1e-6:
        w = np.clip(w ** sharpness, 0.0, 1.0)
        L("判据压缩：指数 %.2f" % sharpness)
    if center is not None and center_prior > 0:
        cm = np.abs(stft(center, *mdx_params(vp)))
        if cm.shape[-1] != T:
            cm = _project_mask(cm, dim_f, T)
        prior = cm / (cm + 0.5 * (np.abs(spec) + 1e-9))
        w = np.clip(w * (1.0 - center_prior + center_prior * prior), 0.0, 1.0)
        L("已应用中置声道先验（强度 %.1f）" % center_prior)

    if gate_db:
        # 每帧人声概率（按幅度加权），平滑后做相对门限
        from numpy.lib.stride_tricks import sliding_window_view
        prob = (w * np.abs(spec)).sum(axis=(0, 1)) / (np.abs(spec).sum(axis=(0, 1)) + 1e-9)
        k = max(1, int(gate_smooth_ms / 1000.0 * SR / hop))
        pad = np.pad(prob, (k, k), mode="edge")
        ps = sliding_window_view(pad, 2 * k + 1).mean(axis=-1)
        ref = np.percentile(ps, 90)
        rel_db = 20 * np.log10(np.maximum(ps, 1e-6) / max(ref, 1e-6))
        g = np.clip(1.0 + rel_db / abs(gate_db), 0.0, 1.0)
        w = w * g.reshape(1, 1, -1)
        L("时域门控：门限 %.0f dB，被压制的帧占比 %.1f%%"
          % (gate_db, 100 * np.mean(g < 0.999)))

    voc = istft((spec * w.astype(np.complex64)).astype(np.complex64),
                mix.shape[-1], nfft, dim_f, hop, win).astype(np.float64)
    inst = mix - voc
    return voc, inst


def separate(input_path, out_dir, stems=("vocals", "instrumental"),
             model_set="标准（推荐）", fmt=("wav",), trim=0.95, soft_limit=True,
             start=None, dur=None, preview=True, mode="mask",
             vocal_boost=False, center_prior=None, strength="normal",
             progress=None, log=None, canceller=None):
    """
    完整分离流程。
    mode: mask=掩蔽式（背景音乐去得更彻底，推荐）；complement=互补式（更快）
    vocal_boost: 人声优先（自动选用对人声提取更强的模型，并叠加中置先验）
    strength: normal=常规；strong=强分离（判据更果断 + 时域门控，背景音乐更小）
    返回 生成的文件路径列表
    """
    if strength == "isolate":
        sharpness, gate_db = 3.0, -6.0
        center_prior_default = 0.75
    elif strength == "strong":
        sharpness, gate_db = 1.3, -14.0
        center_prior_default = 0.75
    else:
        sharpness, gate_db = 1.0, None
        center_prior_default = CENTER_PRIOR_DEFAULT

    def P(pct, txt=""):
        if progress:
            progress(int(pct), txt)

    def L(txt):
        if log:
            log(txt)

    if vocal_boost and model_set not in MODEL_SETS:
        model_set = "标准（推荐）"
    voc_m, inst_m = MODEL_SETS.get(model_set, MODEL_SETS["标准（推荐）"])
    if vocal_boost:
        # 人声优先：挑选对人声提取更强的可用模型
        for cand in VOCAL_FIRST_MODELS:
            if resolve_model(cand):
                voc_m = cand
                break
        mode = "mask"

    voc_path = resolve_model(voc_m)
    inst_path = resolve_model(inst_m)
    for p in (voc_path, inst_path):
        if not p:
            raise RuntimeError("找不到模型文件：%s / %s\n请确认 models 文件夹与程序在同一目录"
                               % (voc_m, inst_m))

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]

    L("读取音频…")
    P(2, "读取音频")
    ch, total = probe_channels(input_path)
    if ch:
        L("源音频：%d 声道%s" % (ch, "（将用中置声道做先验，进一步压低背景音乐）"
                                 if ch >= 6 and (vocal_boost or center_prior) else ""))
    # 中置声道只作为先验参与权重计算，不混入音频（混入会改变模型判据反而更脏）
    mix, _ = read_audio(input_path, start=start, dur=dur, center_boost=False)
    if mix.shape[-1] < SR // 2:
        raise RuntimeError("音频太短（不足 0.5 秒）")
    L("音频长度 %.2f 秒" % (mix.shape[-1] / SR))

    # 中置声道（用于先验）
    center = None
    prior = 0.0 if center_prior is None else float(center_prior)
    if mode == "mask" and ch >= 6 and (vocal_boost or prior > 0):
        try:
            fc = os.path.join(os.environ.get("TEMP", "."), "_sep_c_%d.wav" % os.getpid())
            args = []
            if start:
                args += ["-ss", "%.4f" % start]
            args += ["-i", input_path]
            if dur:
                args += ["-t", "%.4f" % dur]
            run_ffmpeg(args + ["-filter_complex", "pan=stereo|c0=FC|c1=FC",
                               "-ar", str(SR), "-c:a", "pcm_s16le", fc])
            with wave.open(fc, "rb") as w:
                n, c = w.getnframes(), w.getnchannels()
                cc = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, c).T.astype(np.float32) / 32768.0
            try:
                os.remove(fc)
            except OSError:
                pass
            if cc.shape[-1] > SR and float(np.abs(cc).max()) > 0.01:
                center = cc[:2, :mix.shape[-1]]
                prior = center_prior_default if prior <= 0 else prior
                L("中置声道有效，先验强度 %.2f" % prior)
        except Exception as e:
            L("中置声道读取失败（忽略先验）：%s" % e)

    if mode == "mask":
        L("分离方式：掩蔽式（背景音乐去除更彻底）")
        voc, inst = extract_masked(mix, voc_m, inst_m, progress=progress,
                                   canceller=canceller, log=log,
                                   center=center, center_prior=prior,
                                   sharpness=sharpness, gate_db=gate_db)
        if strength == "isolate":
            # 二次迭代：把第一趟的人声结果再喂回模型，残留音乐可再降约 14 dB
            L("纯人声模式：第 2 趟迭代提取…")
            P(90, "第 2 趟迭代提取")
            voc2, _ = extract_masked(voc, voc_m, inst_m, progress=None,
                                     canceller=canceller, log=None,
                                     sharpness=4.0, gate_db=-6.0)
            voc, inst = voc2, mix - voc2
            L("已应用二次迭代（极端隔离）")
    else:
        L("分离方式：互补式")
        L("推理伴奏模型（%s）…" % inst_m)
        inst = infer_audio(inst_path, mix, canceller=canceller,
                           progress=lambda p, t: P(5 + p * 0.45, "伴奏模型 " + t), label="伴奏")
        L("推理人声模型（%s）…" % voc_m)
        infer_audio(voc_path, mix, canceller=canceller,
                    progress=lambda p, t: P(50 + p * 0.45, "人声模型 " + t), label="人声")
        if canceller is not None and canceller():
            raise Cancelled()

    L("后处理：边缘处理 / 软限幅 / 电平对齐…")
    P(96, "后处理")
    en = edge_fade(mix.shape[-1])
    mix_ref = mix * en
    inst = inst * en
    voc = mix_ref - inst if mode != "mask" else voc * en

    if soft_limit:
        voc, inst, g = limit_shared(voc, inst, mix_ref)
        L("软限幅：最小增益 %.2f dB，触发 %.2f%% 样本"
          % (20 * np.log10(max(g.min(), 1e-9)), 100 * np.mean(g < 0.9999)))
    else:
        g = np.ones(voc.shape[-1])
    voc, inst = voc * trim, inst * trim

    files = []
    if "vocals" in stems:
        p = os.path.join(out_dir, "%s_人声.wav" % base)
        write_wav(p, voc)
        files.append(p)
        L("已输出人声: " + os.path.basename(p))
    if "instrumental" in stems:
        p = os.path.join(out_dir, "%s_伴奏.wav" % base)
        write_wav(p, inst)
        files.append(p)
        L("已输出伴奏: " + os.path.basename(p))

    P(98, "编码其他格式")
    for f in list(files):
        if "flac" in fmt:
            fp = os.path.splitext(f)[0] + ".flac"
            run_ffmpeg(["-i", f, "-c:a", "flac", "-compression_level", "8", fp])
            files.append(fp)
            L("已输出 FLAC: " + os.path.basename(fp))
        if "m4a" in fmt:
            fp = os.path.splitext(f)[0] + ".m4a"
            run_ffmpeg(["-i", f, "-c:a", "aac", "-b:a", "256k", fp])
            files.append(fp)
            L("已输出 M4A: " + os.path.basename(fp))

    if preview:
        for f in list(files):
            if not f.endswith(".wav"):
                continue
            try:
                with wave.open(f, "rb") as w:
                    total = w.getnframes() / float(w.getframerate())
                ps = 30.0 if total > 45 else max(0.0, total * 0.25)
                pl = min(15.0, max(1.0, total - ps))
                pp = os.path.splitext(f)[0] + "_试听片段.mp3"
                run_ffmpeg(["-ss", "%.3f" % ps, "-t", "%.3f" % pl, "-i", f,
                            "-c:a", "libmp3lame", "-q:a", "2", pp])
                files.append(pp)
                L("已输出试听片段: %s（第 %.0f 秒起 %.0f 秒）"
                  % (os.path.basename(pp), ps, pl))
            except Exception as e:
                L("试听片段导出失败：%s" % e)

    P(100, "完成")
    L("全部完成，共 %d 个文件" % len(files))
    return files


def patch_segment(main_path, patch_path, start_s, out_dir=None,
                  progress=None, log=None):
    """把 patch_path 的音频替换进 main_path 的 start_s 处"""
    def L(t):
        if log:
            log(t)
    if progress:
        progress(10, "解码片段")
    tmp = os.path.join(os.environ.get("TEMP", "."), "_patch_%d.wav" % os.getpid())
    run_ffmpeg(["-i", patch_path, "-c:a", "pcm_s16le", tmp])
    with wave.open(tmp, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        patch = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, ch).T.astype(np.float64) / 32768.0
    try:
        os.remove(tmp)
    except OSError:
        pass
    with wave.open(main_path, "rb") as w:
        sr2, ch2, n2 = w.getframerate(), w.getnchannels(), w.getnframes()
        main = np.frombuffer(w.readframes(n2), dtype="<i2").reshape(-1, ch2).T.astype(np.float64) / 32768.0
    if sr != sr2:
        raise RuntimeError("采样率不一致：片段 %d Hz，主音频 %d Hz" % (sr, sr2))

    if progress:
        progress(35, "测量对齐偏移")
    guess = int(round(start_s * sr))
    # ponytail: 搜索窗口固定 ±2 秒。窗口越大越容易被周期性内容锁到错误位置，
    # 若将来需要更远的自动对齐，改为先粗搜（低采样率）再精搜。
    search = min(int(2 * sr), max(0, main.shape[-1] - patch.shape[-1]))
    Lp = patch.shape[-1]
    # span 起点会被 max(0, ...) 钳到文件开头，因此 lag 的参照系是 span 原点而非 guess，
    # 插入位置必须写成 span_origin + search + lag（写成 guess + lag 在文件开头附近会偏）
    origin = max(0, guess - search)
    span = main[:, origin:guess + Lp + search].astype(np.float64)
    best = (0, -1.0)
    a = patch[0].astype(np.float64)      # 必须转浮点：int16 上 np.dot 会溢出，把正确位置算歪
    a = a - a.mean()
    na = np.linalg.norm(a)
    for lag in range(-search, search + 1, 1):
        o = search + lag
        if o < 0 or o + Lp > span.shape[-1]:
            continue
        b = span[0, o:o + Lp]
        b = b - b.mean()
        c = float(np.dot(a, b) / (na * np.linalg.norm(b) + 1e-12))
        if c > best[1]:
            best = (lag, c)
    lag, corr = best
    L("对齐：lag=%d 样本（%.4f 秒），相关度=%.5f" % (lag, lag / sr, corr))
    if corr < 0.90:
        raise RuntimeError("相关度过低（%.3f），片段与主音频内容不匹配，未修改文件" % corr)

    start = origin + search + lag
    if start < 0 or start + Lp > main.shape[-1]:
        raise RuntimeError("插入区间超出主音频范围")

    if progress:
        progress(60, "拼接")
    xf = int(0.020 * sr)
    f = np.linspace(0.0, 1.0, xf)
    out = main.copy()
    out[:, start:start + xf] = main[:, start:start + xf] * (1 - f) + patch[:, :xf] * f
    out[:, start + xf:start + Lp] = patch[:, xf:]
    if start + Lp + xf <= out.shape[-1]:
        out[:, start + Lp:start + Lp + xf] = (patch[:, -xf:] * (1 - f)
                                              + main[:, start + Lp:start + Lp + xf] * f)
    L("替换区间：%.3f ~ %.3f 秒" % (start / sr, (start + Lp) / sr))

    peak = float(np.abs(out).max())
    if peak > CEIL:
        k = CEIL / peak * 0.999
        out = out * k
        L("峰值 %.4f 超限，整体衰减 %.2f dB" % (peak, 20 * np.log10(k)))

    if progress:
        progress(80, "写入")
    write_wav(main_path, out, sr)
    try:
        run_ffmpeg(["-i", main_path, "-c:a", "flac", "-compression_level", "8",
                    os.path.splitext(main_path)[0] + ".flac"])
    except Exception:
        pass
    if progress:
        progress(100, "完成")
    L("已更新：%s（峰值 %.4f，满刻度样本 %d）"
      % (os.path.basename(main_path), float(np.abs(out).max()),
         int(np.sum(np.abs(out) >= 0.99999))))
    return main_path
