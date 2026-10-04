# GUI guide / 图形界面使用说明

**English** | [中文](#中文)

Widget-by-widget guide for `python gui.py` (and for the packaged `.exe` built with
`scripts/build_exe.py`). For install steps, model tiers and separation quality, see the
[main README](../README.md).

## Tab 1 — Separate audio / 音频分离

| Field | What it does |
|---|---|
| **Input file** | Any video or audio ffmpeg can decode: mp4, mov, mkv, avi, flv, wmv, ts, webm, mp3, wav, flac, m4a, aac, ogg, wma |
| **Output folder** | Leave empty to create a `分离结果` folder next to the input |
| **Separate** | Tick *vocals* / *accompaniment*; at least one is required |
| **Model tier** | Four tiers, see the README table. Only tiers whose model pair exists in `models/` are listed |
| **Extra formats** | Optionally also write FLAC (lossless) and/or M4A (compressed); *preview clip* writes a 15 s MP3 |
| **Output level** | 0.70–1.00, default 0.95 (−0.4 dB headroom). Lower it if your editor clips after adding effects |
| **Soft limiting** | On by default. A single gain envelope is derived from the mixed signal and shared by both stems, so `vocals + accompaniment` still reconstructs the original |
| **Separation mode** | **Masking (default)** — model output becomes a 0–1 weight map applied to the original spectrum, so low-confidence regions stay in the accompaniment. **Complement** — accompaniment = model output, vocals = subtraction; faster but leaves music in the vocal track |
| **Vocal first / boost** | Switches to the strongest vocal model, and for multichannel sources uses the center channel as a prior. Recommended for songs |
| **Strength** | `normal` / `strong` / `isolate`. `isolate` runs a second iterative pass (about 2× the runtime); see the README numbers |
| **Range** | Untick *whole file* to process only a test window (start second + duration) before committing to a long file |

Progress and a live log appear at the bottom. Output files are named
`<input>_人声.wav` / `<input>_伴奏.wav`.

## Tab 2 — Segment replacement / 片段替换

Replaces a time range of a master track with a newly produced fragment.

1. **Master audio** — the full track you want to keep.
2. **Replacement fragment** — the corrected short piece.
3. **Insert position (seconds)** — e.g. `125` for 2:05.

The alignment offset is measured automatically (this compensates MP3 encoder delay, so a
re-encoded fragment does not land out of sync), boundaries get 20 ms crossfades, and nothing
outside the replaced range is touched. The original is backed up as `*_替换前备份.wav` first.
If the best correlation is below 0.90 the tool refuses and leaves the file untouched.

## Troubleshooting / 疑难

- **No tiers listed** → `models/` is empty; run `python scripts/download_models.py`.
- **"ffmpeg" not found** → put `ffmpeg.exe` in `ffmpeg/`, or install it on `PATH`.
- **Window closes immediately** (packaged build) → run
  `人声伴奏分离工具.exe --selftest` from a terminal; the startup log is written to
  `%TEMP%\人声伴奏分离工具_运行日志.txt`.
- **Background music still audible** → tick *vocal first*, set strength to `strong` or
  `isolate`. If vocals and music share the same time–frequency region, no setting fully
  separates them.

---

# 中文

`python gui.py`（以及用 `scripts/build_exe.py` 打包出的 exe）的逐控件说明。安装步骤、模型档位
与分离质量数据见[主 README](../README.md)。

## 页签一 · 音频分离

| 控件 | 作用 |
|---|---|
| **输入文件** | ffmpeg 能解码的都行：mp4、mov、mkv、avi、flv、wmv、ts、webm、mp3、wav、flac、m4a、aac、ogg、wma |
| **输出文件夹** | 留空则在源文件旁自动建「分离结果」文件夹 |
| **分离内容** | 勾选人声 / 伴奏，至少勾一项 |
| **模型档位** | 共四档，见 README 表格；只列出 `models/` 里模型成对存在的档位 |
| **附加格式** | 可另出 FLAC（无损）/ M4A（压缩）；勾「试听片段」会另出 15 秒 MP3 |
| **输出电平** | 0.70~1.00，默认 0.95（留 −0.4 dB 余量）。若剪辑软件叠加效果后爆音就调低 |
| **软限幅** | 默认开启。以混合信号计算一条共用增益包络给两条轨，因此「人声+伴奏」仍可还原原曲 |
| **分离方式** | **掩蔽式（默认）**：把模型输出当作 0~1 权值过滤原曲频谱，模型没把握处能量留在伴奏轨；**互补式**：伴奏取模型输出、人声取相减，更快但人声里会残留音乐 |
| **人声优先** | 换用最强人声模型；多声道素材还会用中置声道做先验。歌曲素材建议勾选 |
| **分离强度** | 常规 / 强分离 / 纯人声（极端隔离）。极端隔离会跑第二趟迭代，耗时约 2 倍，数据见 README |
| **处理范围** | 取消「处理整个文件」可先只跑一小段试听（起始秒 + 时长），避免长文件白等 |

进度条与运行日志在窗口下方。输出文件命名为 `<源文件名>_人声.wav` / `<源文件名>_伴奏.wav`。

## 页签二 · 片段替换

用新做好的一小段替换主音轨里的对应区间。

1. **主音频** —— 要保留的完整音轨。
2. **替换片段** —— 修正后的那一小段。
3. **插入起点（秒）** —— 例如 `125` 表示 2 分 05 秒。

程序会自动测量两者的对齐偏移（补偿 MP3 编码延时，重编码过的片段不会错位），边界做 20ms
交叉淡化，替换区间之外不改动任何样本。原文件先备份为 `*_替换前备份.wav`；若最佳相关度低于
0.90 则拒绝执行、不修改文件。

## 疑难排查

- **档位列表为空** → `models/` 里没有模型，运行 `python scripts/download_models.py`。
- **提示找不到 ffmpeg** → 把 `ffmpeg.exe` 放进 `ffmpeg/`，或安装到系统 PATH。
- **窗口一闪就退出**（打包版）→ 在终端里执行 `人声伴奏分离工具.exe --selftest`；启动日志在
  `%TEMP%\人声伴奏分离工具_运行日志.txt`。
- **背景音乐还听得见** → 勾上「人声优先」，强度改「强分离」或「纯人声（极端隔离）」。若人声与
  音乐在同一时频区域重叠，任何设置都无法完全分开。
