#!/usr/bin/env python3
"""下载分离所需模型（带 SHA256 校验，国内镜像回退）"""
import hashlib
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "models")

REPO_PATH = "Politrees/UVR_resources/resolve/main/models/MDXNet"
# 下载源按顺序尝试。VOICESPLIT_MODEL_BASE 可指向自建 Release（见 publish_models.py），
# 例如 https://github.com/<用户名>/<仓库>/releases/download/models-v1/
# 官方源在国内常连不上，因此镜像优先。
BASES = [b for b in [
    os.environ.get("VOICESPLIT_MODEL_BASE", "").strip(),
    "https://hf-mirror.com/" + REPO_PATH + "/",
    "https://huggingface.co/" + REPO_PATH + "/",
] if b]

MODELS = {
    "Kim_Vocal_2.onnx":
        "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b",
    "kuielab_b_vocals.onnx":
        "9b7dcb9d878acb0e3f64ff3fd27750faae96577013f6d50f5996875bf4250713",
    "UVR-MDX-NET-Inst_HQ_3.onnx":
        "317554b07fe1ea5279a77f2b1520a41ea4b93432560c4ffd08792c30fddf9adc",
    "UVR-MDX-NET-Voc_FT.onnx":
        "534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111",
    "UVR-MDX-NET-Inst_HQ_4.onnx":
        "3c4b5b9b05090fdf238f38ba5046813982d50e2a652e9cb3324ea79720c3c9c8",
    "UVR-MDX-NET-Inst_Main.onnx":
        "8ab401dfe4a548b87deb64f975294bd56ff946aa32903f53b4b24bb13b2cce1e",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(name, base):
    dst = os.path.join(MODELS_DIR, name)
    tmp = dst + ".part"
    req = urllib.request.Request(base + name, headers={"User-Agent": "VoiceSplit"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write("\r  %s  %5.1f%%  (%.1f/%.1f MB)"
                                 % (name, 100 * done / total, done / 1e6, total / 1e6))
                sys.stdout.flush()
    sys.stdout.write("\n")
    os.replace(tmp, dst)
    return dst


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    failed = []
    for name, want in MODELS.items():
        dst = os.path.join(MODELS_DIR, name)
        if os.path.exists(dst) and sha256(dst) == want:
            print("已存在且校验通过: %s" % name)
            continue
        ok = False
        for base in BASES:
            try:
                print("下载 %s  来源 %s" % (name, base.split("/")[2]))
                download(name, base)
                got = sha256(dst)
                if got != want:
                    print("  SHA256 不匹配，删除重试\n    期望 %s\n    实际 %s" % (want, got))
                    os.remove(dst)
                    continue
                print("  [OK] 校验通过")
                ok = True
                break
            except Exception as e:
                print("  失败：%s" % str(e)[:120])
        if not ok:
            failed.append(name)
    if failed:
        print("\n以下模型未能下载：%s" % "、".join(failed))
        print("可手动下载后放入 models/ 目录（文件名需一致）")
        return 1
    print("\n全部就绪，可以运行 python gui.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
