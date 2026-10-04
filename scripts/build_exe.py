#!/usr/bin/env python3
"""把工具打包成 Windows 单文件夹 exe（需先 pip install pyinstaller）"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "VoiceSplit"


def main():
    icon = os.path.join(ROOT, "icon.ico")
    models = os.path.join(ROOT, "models")
    if not os.path.isdir(models) or not os.listdir(models):
        print("models/ 为空，请先运行 scripts/download_models.py")
        return 1
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--windowed", "--onedir", "--name", NAME,
            "--add-data", "%s%smodels" % (models, os.pathsep),
            "--hidden-import", "onnxruntime", "--collect-submodules", "onnxruntime",
            "--exclude-module", "matplotlib", "--exclude-module", "pandas",
            "--exclude-module", "IPython"]
    if os.path.exists(icon):
        args += ["--icon", icon]
    # 目录里有 ffmpeg.exe 就一并打包
    ff = os.path.join(ROOT, "ffmpeg")
    if os.path.isdir(ff):
        args += ["--add-data", "%s%sffmpeg" % (ff, os.pathsep)]
    args.append(os.path.join(ROOT, "gui.py"))
    print(" ".join(args))
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode == 0:
        print("\n完成：dist/%s/" % NAME)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
