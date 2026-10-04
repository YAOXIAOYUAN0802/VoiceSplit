#!/usr/bin/env python3
"""
把模型权重发布到 GitHub Release 附件。

为什么不用仓库文件：模型是第三方权重，塞进 git 历史会让仓库膨胀且授权不清；
Release 附件不进入代码历史，用户按需下载，是更干净的分发方式。

前置：安装并登录 gh CLI（https://cli.github.com），或设置 GH_TOKEN 环境变量。

用法：
    python scripts/publish_models.py --repo <用户名>/<仓库名> --tag models-v1
    python scripts/publish_models.py --repo me/VoiceSplit --dry-run

发布后，把这个 Release 的下载地址告诉使用者，或写进环境变量：
    VOICESPLIT_MODEL_BASE=https://github.com/<用户名>/<仓库名>/releases/download/models-v1/
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "models")


def run(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit("命令失败：%s\n%s" % (" ".join(args), (r.stderr or r.stdout)[:500]))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="形如 用户名/仓库名")
    ap.add_argument("--tag", default="models-v1", help="Release 标签（默认 models-v1）")
    ap.add_argument("--title", default=None, help="Release 标题")
    ap.add_argument("--dry-run", action="store_true", help="只列出将上传的文件")
    args = ap.parse_args()

    if not os.path.isdir(MODELS_DIR):
        print("找不到 models/ 目录")
        return 1
    files = sorted(f for f in os.listdir(MODELS_DIR) if f.endswith(".onnx"))
    if not files:
        print("models/ 里没有 .onnx 文件，先运行：python scripts/download_models.py")
        return 1

    total = sum(os.path.getsize(os.path.join(MODELS_DIR, f)) for f in files)
    print("将发布 %d 个模型，共 %.1f MB：" % (len(files), total / 1e6))
    for f in files:
        print("  %-32s %5.1f MB" % (f, os.path.getsize(os.path.join(MODELS_DIR, f)) / 1e6))
    base = "https://github.com/%s/releases/download/%s/" % (args.repo, args.tag)
    print("\n发布后下载地址前缀：\n  %s" % base)
    if args.dry_run:
        print("\n（--dry-run，未实际上传）")
        return 0

    if not shutil.which("gh"):
        print("\n未找到 gh CLI。请先安装：https://cli.github.com")
        print("或手动把上面这些文件上传为 Release 附件。")
        return 1

    r = run(["gh", "release", "view", args.tag, "--repo", args.repo], check=False)
    if r.returncode != 0:
        print("\n创建 Release %s ..." % args.tag)
        run(["gh", "release", "create", args.tag, "--repo", args.repo,
             "--title", args.title or ("模型权重 " + args.tag),
             "--notes", "第三方模型权重（非本仓库代码授权范围）。来源与许可见 README。"])

    print("\n上传附件 ...")
    paths = [os.path.join(MODELS_DIR, f) for f in files]
    run(["gh", "release", "upload", args.tag, "--repo", args.repo, "--clobber"] + paths)

    print("\n完成。使用者可这样指定下载源：")
    print("  set VOICESPLIT_MODEL_BASE=%s   (Windows)" % base)
    print("  export VOICESPLIT_MODEL_BASE=%s  (Linux/macOS)" % base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
