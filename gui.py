# -*- coding: utf-8 -*-
"""
人声 / 背景音乐分离工具 —— 图形界面
"""
import os
import queue
import shutil
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core

APP = "人声 / 背景音乐分离工具"
VER = "v1.1"
BG = "#f5f6f8"
LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "人声伴奏分离工具_运行日志.txt")


def boot_log(msg):
    """窗口模式没有控制台，把启动信息与异常写进日志文件"""
    try:
        import datetime
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def available_model_sets():
    """只列出模型齐全的档位"""
    ok = {}
    for name, (v, i) in core.MODEL_SETS.items():
        if core.resolve_model(v) and core.resolve_model(i):
            ok[name] = (v, i)
    return ok


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.cancel_flag = False
        self.last_out = None

        root.title("%s %s" % (APP, VER))
        root.geometry("940x720")
        root.minsize(860, 640)
        root.configure(bg=BG)
        for p in (core.resource("icon.ico"), core.resource("图标预览.png")):
            if p and os.path.exists(p):
                try:
                    root.iconbitmap(default=p)
                    break
                except Exception as e:
                    boot_log("设置窗口图标失败(%s)：%s" % (p, e))

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Big.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=8)
        style.configure("TLabel", background=BG, font=("Microsoft YaHei UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Microsoft YaHei UI", 10))
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=(16, 8))

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        self.tab_sep = ttk.Frame(nb, padding=14)
        self.tab_patch = ttk.Frame(nb, padding=14)
        nb.add(self.tab_sep, text="  音频分离  ")
        nb.add(self.tab_patch, text="  片段替换  ")

        self.build_sep(self.tab_sep)
        self.build_patch(self.tab_patch)
        self.build_bottom(root)

        self.root.after(120, self.pump)
        self.root.after(3000, self.heartbeat)
        self.log("%s %s 已启动" % (APP, VER))
        self.log("ffmpeg: %s" % core.find_ffmpeg())
        sets = available_model_sets()
        if not sets:
            self.log("⚠ 未找到模型文件，请确认 models 文件夹与程序在同一目录")
        else:
            self.log("可用模型档位：%s" % "、".join(sets.keys()))

    # ---------------- 界面搭建 ----------------

    def build_sep(self, p):
        # 输入
        g1 = ttk.LabelFrame(p, text=" 1. 选择文件 ", padding=12)
        g1.pack(fill="x", pady=(0, 10))
        ttk.Label(g1, text="输入视频 / 音频：").grid(row=0, column=0, sticky="w")
        self.in_path = tk.StringVar()
        ttk.Entry(g1, textvariable=self.in_path).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(g1, text="浏览…", command=self.pick_input, width=9).grid(row=0, column=2)
        ttk.Label(g1, text="输出文件夹：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.out_dir = tk.StringVar()
        ttk.Entry(g1, textvariable=self.out_dir).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(g1, text="浏览…", command=self.pick_outdir, width=9).grid(row=1, column=2, pady=(8, 0))
        g1.columnconfigure(1, weight=1)

        # 选项
        g2 = ttk.LabelFrame(p, text=" 2. 分离设置 ", padding=12)
        g2.pack(fill="x", pady=(0, 10))
        ttk.Label(g2, text="分离内容：").grid(row=0, column=0, sticky="w")
        self.ck_voc = tk.BooleanVar(value=True)
        self.ck_inst = tk.BooleanVar(value=True)
        f = ttk.Frame(g2)
        f.grid(row=0, column=1, columnspan=3, sticky="w", padx=8)
        ttk.Checkbutton(f, text="人声", variable=self.ck_voc).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(f, text="伴奏（背景音乐）", variable=self.ck_inst).pack(side="left")

        ttk.Label(g2, text="模型档位：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.model_set = tk.StringVar()
        self.cmb_model = ttk.Combobox(g2, textvariable=self.model_set, state="readonly", width=20)
        sets = list(available_model_sets().keys())
        self.cmb_model["values"] = sets
        if sets:
            self.model_set.set(sets[0])
        self.cmb_model.grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(g2, text="（标准档最快，高精度档更干净但更慢）",
                  foreground="#777").grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(g2, text="附加格式：").grid(row=2, column=0, sticky="w", pady=(8, 0))
        f2 = ttk.Frame(g2)
        f2.grid(row=2, column=1, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        self.fmt = {}
        for k, t in (("flac", "FLAC 无损"), ("m4a", "M4A 压缩")):
            v = tk.BooleanVar(value=(k == "flac"))
            self.fmt[k] = v
            ttk.Checkbutton(f2, text=t, variable=v).pack(side="left", padx=(0, 16))
        self.ck_preview = tk.BooleanVar(value=True)
        ttk.Checkbutton(f2, text="试听片段", variable=self.ck_preview).pack(side="left")

        # 分离方式（核心：背景音乐去除彻底程度）
        ttk.Label(g2, text="分离方式：").grid(row=3, column=0, sticky="w", pady=(8, 0))
        f3 = ttk.Frame(g2)
        f3.grid(row=3, column=1, columnspan=3, sticky="w", padx=8, pady=(8, 0))
        self.mode = tk.StringVar(value="mask")
        ttk.Radiobutton(f3, text="干净优先（掩蔽式，背景音乐去得更彻底）",
                        variable=self.mode, value="mask").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(f3, text="快速（互补式）",
                        variable=self.mode, value="complement").pack(side="left")

        # 人声优先（歌曲素材推荐）
        self.ck_boost = tk.BooleanVar(value=False)
        ttk.Checkbutton(g2, text="人声优先 / 突显人声（歌曲素材推荐：换用更强的人声模型，"
                                 "多声道素材自动用中置声道做先验）",
                        variable=self.ck_boost).grid(row=4, column=1, columnspan=3,
                                                     sticky="w", padx=8, pady=(6, 0))
        # 强度
        ttk.Label(g2, text="分离强度：").grid(row=5, column=0, sticky="w", pady=(6, 0))
        f4 = ttk.Frame(g2)
        f4.grid(row=5, column=1, columnspan=3, sticky="w", padx=8, pady=(6, 0))
        self.strength = tk.StringVar(value="normal")
        ttk.Radiobutton(f4, text="常规", variable=self.strength, value="normal").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(f4, text="强分离", variable=self.strength, value="strong").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(f4, text="纯人声（极端隔离，背景音乐接近消失）",
                        variable=self.strength, value="isolate").pack(side="left")
        ttk.Label(g2, text="纯人声模式耗时约为常规的 2 倍，人声会有轻微处理感；"
                           "建议同时勾选「人声优先」",
                  foreground="#777").grid(row=6, column=1, columnspan=3, sticky="w",
                                          padx=8, pady=(2, 0))

        ttk.Label(g2, text="输出电平：").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.trim = tk.DoubleVar(value=0.95)
        sc = ttk.Scale(g2, from_=0.70, to=1.0, variable=self.trim, orient="horizontal",
                       length=220, command=lambda e: self.trim_lbl.config(
                           text="%.2f 倍（%.1f dB）" % (self.trim.get(), 20 * __import__("math").log10(self.trim.get()))))
        sc.grid(row=7, column=1, sticky="w", padx=8, pady=(8, 0))
        self.trim_lbl = ttk.Label(g2, text="0.95 倍（-0.4 dB）")
        self.trim_lbl.grid(row=7, column=2, sticky="w", pady=(8, 0))
        self.ck_limit = tk.BooleanVar(value=True)
        ttk.Checkbutton(g2, text="启用软限幅（防削顶，推荐）", variable=self.ck_limit).grid(
            row=8, column=1, columnspan=3, sticky="w", padx=8, pady=(4, 0))

        # 范围
        g3 = ttk.LabelFrame(p, text=" 3. 处理范围 ", padding=12)
        g3.pack(fill="x", pady=(0, 10))
        self.ck_full = tk.BooleanVar(value=True)
        ttk.Checkbutton(g3, text="处理整个文件", variable=self.ck_full,
                        command=self.toggle_range).grid(row=0, column=0, sticky="w")
        ttk.Label(g3, text="起始（秒）：").grid(row=0, column=1, sticky="e", padx=(20, 4))
        self.t_start = tk.StringVar(value="0")
        self.e_start = ttk.Entry(g3, textvariable=self.t_start, width=8)
        self.e_start.grid(row=0, column=2, sticky="w")
        ttk.Label(g3, text="时长（秒）：").grid(row=0, column=3, sticky="e", padx=(16, 4))
        self.t_dur = tk.StringVar(value="30")
        self.e_dur = ttk.Entry(g3, textvariable=self.t_dur, width=8)
        self.e_dur.grid(row=0, column=4, sticky="w")
        self.toggle_range()

        # 运行
        g4 = ttk.Frame(p)
        g4.pack(fill="x", pady=(4, 0))
        self.btn_run = ttk.Button(g4, text="开始分离", style="Big.TButton", command=self.start_sep)
        self.btn_run.pack(side="left")
        ttk.Button(g4, text="打开输出文件夹", command=self.open_out).pack(side="left", padx=10)

    def build_patch(self, p):
        g1 = ttk.LabelFrame(p, text=" 用一段新音频替换主音频中的对应区间 ", padding=12)
        g1.pack(fill="x", pady=(0, 10))
        ttk.Label(g1, text="主音频：").grid(row=0, column=0, sticky="w")
        self.p_main = tk.StringVar()
        ttk.Entry(g1, textvariable=self.p_main).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(g1, text="浏览…", width=9, command=lambda: self.pick_file(self.p_main, "音频",
                   [("音频", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.wma"), ("所有文件", "*.*")])
                   ).grid(row=0, column=2)
        ttk.Label(g1, text="替换片段：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.p_patch = tk.StringVar()
        ttk.Entry(g1, textvariable=self.p_patch).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(g1, text="浏览…", width=9, command=lambda: self.pick_file(self.p_patch, "音频",
                   [("音频", "*.mp3 *.wav *.flac *.m4a *.aac"), ("所有文件", "*.*")])
                   ).grid(row=1, column=2, pady=(8, 0))
        ttk.Label(g1, text="插入起点（秒）：").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.p_start = tk.StringVar(value="125")
        ttk.Entry(g1, textvariable=self.p_start, width=12).grid(row=2, column=1, sticky="w", padx=8, pady=(8, 0))
        g1.columnconfigure(1, weight=1)

        g2 = ttk.LabelFrame(p, text=" 说明 ", padding=12)
        g2.pack(fill="x", pady=(0, 10))
        ttk.Label(g2, justify="left", foreground="#555", text=(
            "· 程序会自动测量两个音频之间的对齐偏移（补偿 MP3 编码延时），不会错位。\n"
            "· 拼接边界做 20ms 交叉淡化，不会有爆音；替换区间之外不会改动任何样本。\n"
            "· 相关度低于 0.90 时判定内容不匹配并中止，不改动原文件。\n"
            "· 原文件会先备份为 *_替换前备份.wav，并同步更新同名 FLAC。")).pack(anchor="w")

        g3 = ttk.Frame(p)
        g3.pack(fill="x")
        self.btn_patch = ttk.Button(g3, text="执行替换", style="Big.TButton", command=self.start_patch)
        self.btn_patch.pack(side="left")

    def build_bottom(self, root):
        b = ttk.Frame(root, padding=(12, 0, 12, 12))
        b.pack(fill="both", expand=True)
        self.pb = ttk.Progressbar(b, mode="determinate", maximum=100)
        self.pb.pack(fill="x")
        self.status = ttk.Label(b, text="就绪", foreground="#444")
        self.status.pack(anchor="w", pady=(4, 6))
        lf = ttk.LabelFrame(b, text=" 运行日志 ", padding=6)
        lf.pack(fill="both", expand=True)
        self.logbox = tk.Text(lf, height=8, wrap="word", state="disabled",
                              bg="#ffffff", relief="flat", font=("Consolas", 9))
        sb = ttk.Scrollbar(lf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---------------- 交互 ----------------

    def toggle_range(self):
        st = "disabled" if self.ck_full.get() else "normal"
        self.e_start.configure(state=st)
        self.e_dur.configure(state=st)

    def pick_input(self):
        p = filedialog.askopenfilename(
            title="选择视频或音频文件",
            filetypes=[("视频 / 音频", "*.mp4 *.mov *.mkv *.avi *.flv *.wmv *.ts *.m4v *.webm "
                                     "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma"),
                       ("所有文件", "*.*")])
        if p:
            self.in_path.set(p)
            if not self.out_dir.get():
                self.out_dir.set(os.path.join(os.path.dirname(p), "分离结果"))
            self.log("已选择输入：%s" % os.path.basename(p))

    def pick_outdir(self):
        p = filedialog.askdirectory(title="选择输出文件夹")
        if p:
            self.out_dir.set(p)

    def pick_file(self, var, title, types):
        p = filedialog.askopenfilename(title="选择%s文件" % title, filetypes=types)
        if p:
            var.set(p)

    def open_out(self):
        d = self.last_out or self.out_dir.get()
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showinfo(APP, "还没有输出文件夹")

    def log(self, s):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", s + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def set_status(self, s, pct=None):
        self.status.configure(text=s)
        if pct is not None:
            self.pb["value"] = pct

    # ---------------- 线程与任务 ----------------

    def _progress(self, pct, txt=""):
        self.q.put(("p", pct, txt))

    def _log(self, txt):
        self.q.put(("l", txt))

    def heartbeat(self):
        """每 30 秒记录一次心跳，便于排查“窗口自动关闭”类问题"""
        try:
            self._beats = getattr(self, "_beats", 0) + 1
            if self._beats % 10 == 0:
                boot_log("心跳 %d（界面运行中，winfo_exists=%s）"
                         % (self._beats, self.root.winfo_exists()))
        except Exception:
            pass
        try:
            self.root.after(3000, self.heartbeat)
        except Exception:
            pass

    def pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "p":
                    self.pb["value"] = m[1]
                    if m[2]:
                        self.status.configure(text=m[2])
                elif m[0] == "l":
                    self.log(m[1])
                elif m[0] == "done":
                    self.busy(False)
                    self.pb["value"] = 100
                    self.status.configure(text=m[1])
                    self.last_out = m[2] if len(m) > 2 else None
                    if len(m) > 3 and m[3]:
                        self.log("输出文件夹：%s" % m[2])
                elif m[0] == "err":
                    self.busy(False)
                    self.status.configure(text="出错了")
                    self.log("✗ " + m[1])
                    messagebox.showerror(APP, m[1][:600])
        except queue.Empty:
            pass
        self.root.after(120, self.pump)

    def busy(self, b):
        st = "disabled" if b else "normal"
        self.btn_run.configure(state=st)
        self.btn_patch.configure(state=st)

    def run_task(self, fn):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP, "已有任务在运行中")
            return
        self.cancel_flag = False
        self.busy(True)
        self.pb["value"] = 0

        def wrap():
            try:
                fn()
            except core.Cancelled:
                self.q.put(("l", "已中止"))
                self.q.put(("done", "已中止", None))
            except Exception as e:
                self.q.put(("err", "%s：%s" % (type(e).__name__, e)))
                self.q.put(("l", traceback.format_exc()[-1500:]))

        self.worker = threading.Thread(target=wrap, daemon=True)
        self.worker.start()

    def start_sep(self):
        src = self.in_path.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(APP, "请先选择存在的输入文件")
            return
        out = self.out_dir.get().strip() or os.path.join(os.path.dirname(src), "分离结果")
        self.out_dir.set(out)
        stems = []
        if self.ck_voc.get():
            stems.append("vocals")
        if self.ck_inst.get():
            stems.append("instrumental")
        if not stems:
            messagebox.showwarning(APP, "请至少勾选一项分离内容")
            return
        fmt = tuple(k for k, v in self.fmt.items() if v.get())
        start = dur = None
        if not self.ck_full.get():
            try:
                start = float(self.t_start.get())
                dur = float(self.t_dur.get())
            except ValueError:
                messagebox.showwarning(APP, "起始时间与时长需要填数字")
                return
            if dur <= 0:
                messagebox.showwarning(APP, "时长必须大于 0")
                return
        ms = self.model_set.get()
        if not ms:
            messagebox.showwarning(APP, "没有可用模型档位")
            return

        self.log("=" * 54)
        self.log("开始分离：%s" % os.path.basename(src))
        self.log("档位 %s｜方式 %s｜格式 %s｜限幅 %s"
                 % (ms, "掩蔽式" if self.mode.get() == "mask" else "互补式",
                    ",".join(fmt) or "仅 WAV", "开" if self.ck_limit.get() else "关"))
        if self.ck_boost.get():
            self.log("已启用「人声优先 / 突显人声」")
        if self.strength.get() == "strong":
            self.log("分离强度：强分离（时域门控，间奏处的背景音乐会被进一步压低）")
        if start is not None:
            self.log("范围：%.1f 秒起，共 %.1f 秒" % (start, dur))

        def job():
            files = core.separate(
                src, out, stems=tuple(stems), model_set=ms, fmt=fmt,
                trim=float(self.trim.get()), soft_limit=bool(self.ck_limit.get()),
                start=start, dur=dur, preview=bool(self.ck_preview.get()),
                mode=self.mode.get(), vocal_boost=bool(self.ck_boost.get()),
                strength=self.strength.get(),
                progress=self._progress, log=self._log,
                canceller=lambda: self.cancel_flag)
            self.q.put(("done", "完成：生成 %d 个文件" % len(files), out, True))

        self.run_task(job)

    def start_patch(self):
        main = self.p_main.get().strip()
        patch = self.p_patch.get().strip()
        if not main or not os.path.exists(main):
            messagebox.showwarning(APP, "请选择存在的主音频文件")
            return
        if not patch or not os.path.exists(patch):
            messagebox.showwarning(APP, "请选择存在的替换片段")
            return
        try:
            t = float(self.p_start.get())
        except ValueError:
            messagebox.showwarning(APP, "插入起点需要填数字（秒）")
            return

        self.log("=" * 54)
        self.log("片段替换：%s → %s @ %.3f 秒"
                 % (os.path.basename(patch), os.path.basename(main), t))

        def job():
            core.patch_segment(main, patch, t, progress=self._progress, log=self._log)
            self.q.put(("done", "替换完成", os.path.dirname(main)))

        self.run_task(job)


def selftest():
    """控制台自检：验证 ffmpeg、模型、推理链路是否可用"""
    import tempfile
    import wave
    import numpy as np

    ok = True
    print("=" * 60)
    print("%s %s 自检" % (APP, VER))
    print("=" * 60)
    print("运行模式 : %s" % ("打包 exe" if getattr(sys, "frozen", False) else "源码"))
    print("程序目录 : %s" % core.app_dir())
    print("可写临时目录 : %s" % tempfile.gettempdir())

    ff = core.find_ffmpeg()
    print("ffmpeg   : %s" % ff)
    if not (os.path.exists(ff) or shutil.which(ff)):
        print("  [X] 未找到 ffmpeg（可放到 ffmpeg/ffmpeg.exe，或安装到系统 PATH）")
        ok = False
    else:
        try:
            core.run_ffmpeg(["-version"])
            print("  [OK] 可执行")
        except Exception as e:
            print("  [X] 执行失败: %s" % e)
            ok = False

    sets = available_model_sets()
    print("模型档位 : %s" % ("、".join(sets.keys()) if sets else "无"))
    for name, (v, i) in core.MODEL_SETS.items():
        pv, pi = core.resolve_model(v), core.resolve_model(i)
        mark = "[OK]" if (pv and pi) else "[X]"
        print("  %s %-10s 人声=%s 伴奏=%s" % (mark, name,
              "OK" if pv else "缺失", "OK" if pi else "缺失"))
    if not sets:
        ok = False

    try:
        import onnxruntime
        print("onnxruntime : %s" % onnxruntime.__version__)
    except Exception as e:
        print("onnxruntime : [X] %s" % e)
        ok = False

    if sets:
        try:
            print("-" * 60)
            print("推理测试（1 秒合成音频，逐个档位）…")
            sr = core.SR
            t = np.arange(sr) / sr
            tone = (0.2 * np.sin(2 * np.pi * 440 * t)
                    + 0.1 * np.sin(2 * np.pi * 3000 * t)).astype(np.float32)
            audio = np.vstack([tone, tone])
            import time as _t
            d = os.path.join(tempfile.gettempdir(), "分离工具_自检")
            os.makedirs(d, exist_ok=True)
            for name, (vm, im) in sets.items():
                out = None
                for kind, mf in (("伴奏", im), ("人声", vm)):
                    mp = core.resolve_model(mf)
                    nfft, dim_f, hop, win = core.mdx_params(mp)
                    spec = core.stft(audio, nfft, dim_f, hop, win)
                    t0 = _t.time()
                    out = core.infer(mp, spec, label=kind, length=audio.shape[-1])
                    print("  %-10s %s %-30s n_fft=%-5d dim_f=%-5d %.1fs"
                          % (name, kind, mf, nfft, dim_f, _t.time() - t0))
                p = os.path.join(d, "自检_%s.wav" % name.replace("（", "_").replace("）", ""))
                core.write_wav(p, out)
            print("  [OK] 各档位推理与写出均正常")
        except Exception as e:
            print("  [X] 推理失败：%s" % e)
            traceback.print_exc()
            ok = False

        # 端到端：走一遍完整流程（ffmpeg 解码 → 双模型 → 编码输出）
        try:
            print("-" * 60)
            print("端到端测试（3 秒，完整流程）…")
            d = os.path.join(tempfile.gettempdir(), "分离工具_自检")
            os.makedirs(d, exist_ok=True)
            sr = core.SR
            t = np.arange(sr * 3) / sr
            sig = (0.25 * np.sin(2 * np.pi * 440 * t)
                   + 0.15 * np.sin(2 * np.pi * 2200 * t)
                   + 0.05 * np.sin(2 * np.pi * 12000 * t)).astype(np.float32)
            src = os.path.join(d, "自检输入.wav")
            core.write_wav(src, np.vstack([sig, sig]))
            import time as _t
            t0 = _t.time()
            files = core.separate(src, d, stems=("vocals", "instrumental"),
                                  model_set=list(sets.keys())[0], fmt=("flac",),
                                  trim=0.95, soft_limit=True, preview=True,
                                  progress=lambda p, x: None,
                                  log=lambda s: print("    " + s))
            print("  [OK] 端到端完成，耗时 %.1fs，生成 %d 个文件" % (_t.time() - t0, len(files)))
            if len(files) < 4:
                print("  [X] 输出文件数异常")
                ok = False
        except Exception as e:
            print("  [X] 端到端失败：%s" % e)
            traceback.print_exc()
            ok = False

    print("=" * 60)
    print("自检结果：%s" % ("全部通过 [OK]" if ok else "存在失败项 [X]"))
    return 0 if ok else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("--selftest", "/selftest", "-t"):
        sys.exit(selftest())

    boot_log("启动 %s %s | frozen=%s | 程序目录=%s"
             % (APP, VER, getattr(sys, "frozen", False), core.app_dir()))
    try:
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.deiconify()
    except Exception:
        boot_log("启动失败：\n" + traceback.format_exc())
        try:
            import tkinter.messagebox as mb
            mb.showerror(APP, "启动失败：\n\n%s\n\n详细信息见：\n%s"
                         % (traceback.format_exc()[-800:], LOG_PATH))
        except Exception:
            pass
        raise

    def on_close():
        boot_log("收到窗口关闭请求（WM_DELETE_WINDOW）")
        if app.worker and app.worker.is_alive():
            if not messagebox.askokcancel(APP, "任务正在运行，确定要退出吗？"):
                return
            app.cancel_flag = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    boot_log("界面已就绪，进入主循环")
    try:
        root.mainloop()
    except Exception:
        boot_log("主循环异常：\n" + traceback.format_exc())
        raise
    boot_log("正常退出")


if __name__ == "__main__":
    main()
