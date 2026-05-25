"""片刻 · 启动器（Python 部分）

由 启动_macOS.command / 启动_Windows.bat 调用。
本脚本只用标准库，可以在任何 Python 3.10+ 下运行。

职责：
1. 检查 GitHub 是否有新版本，有则拉取覆盖
2. 询问用户启用哪些模式（首次），按选择装依赖
3. 启动 app.py，等待退出

约定：
- 项目根目录 = 本脚本所在目录的父目录
- venv 位于项目根目录的 .venv/
- 依赖安装记录在 .pic_selecter_install.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_OWNER = "zhaoyue4810"
GITHUB_REPO = "pianke"
GITHUB_BRANCH = "main"

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
INSTALL_INFO = ROOT / ".pic_selecter_install.json"

IS_WIN = os.name == "nt"
PY_IN_VENV = VENV / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")

# 国内镜像源（pip / HuggingFace）。设 PIANKE_NO_MIRROR=1 关闭。
USE_MIRROR = os.environ.get("PIANKE_NO_MIRROR", "0") != "1"
PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple/"
PYPI_MIRROR_HOST = "pypi.tuna.tsinghua.edu.cn（清华大学）"
HF_MIRROR = "https://hf-mirror.com"  # HuggingFace 镜像（DINOv2、NIMA 等模型）

# 依赖定义见项目根目录 pyproject.toml（由 uv 安装/sync）
# fast → 仅 [project].dependencies
# expert → + optional-dependencies.expert
# tycoon → + optional-dependencies.tycoon
MODE_EXTRAS = {
    "fast": [],
    "expert": ["expert"],
    "tycoon": ["tycoon"],
}

MODE_LABELS = {
    "fast": "极速模式（纯本地，约 200MB，下载 1-3 分钟）",
    "expert": "专家模式（深度学习，约 2-3GB，下载 5-15 分钟）",
    "tycoon": "土豪模式（LLM 判图，约 5MB，需自备 API key）",
}

ALL_MODES = ["fast", "expert", "tycoon"]


# ---------- 输出 ----------

def banner(text: str) -> None:
    print()
    print("━" * 56)
    print(f"  {text}")
    print("━" * 56)


def step(idx: int, total: int, text: str) -> None:
    print(f"\n[{idx}/{total}] {text}")


def info(text: str) -> None:
    print(f"  • {text}")


def warn(text: str) -> None:
    print(f"  ⚠ {text}")


def die(text: str) -> None:
    print(f"\n❌ {text}", file=sys.stderr)
    print("\n按回车键退出...", file=sys.stderr)
    try:
        input()
    except EOFError:
        pass
    sys.exit(1)


# ---------- 安装信息持久化 ----------

def load_install() -> dict:
    if INSTALL_INFO.exists():
        try:
            return json.loads(INSTALL_INFO.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_install(data: dict) -> None:
    INSTALL_INFO.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- 模式选择 ----------

def ask_modes(previous: list[str] | None) -> list[str]:
    print()
    if previous:
        print(f"上次启用的模式：{', '.join(previous)}")
        print("直接回车 = 沿用；否则请重新选择。")
    else:
        print("第一次运行，请选择要启用的模式（可多选，逗号或空格分隔）：")

    print()
    keys = ["fast", "expert", "tycoon"]
    for i, key in enumerate(keys, 1):
        print(f"  {i}) {MODE_LABELS[key]}")
    print(f"  4) 全部")

    while True:
        try:
            raw = input("\n> ").strip()
        except EOFError:
            raw = ""

        if not raw and previous:
            return previous
        if not raw:
            print("请至少选一个。")
            continue

        # 解析：支持 "1,2"、"1 2"、"123"、"4" 等
        tokens = re.findall(r"[1-4]", raw)
        if not tokens:
            print("无法识别，请输入 1-4 的数字。")
            continue

        if "4" in tokens:
            return keys[:]

        chosen = []
        for t in tokens:
            k = keys[int(t) - 1]
            if k not in chosen:
                chosen.append(k)
        if not chosen:
            print("请至少选一个。")
            continue
        return chosen


def parse_modes_arg(raw: str) -> list[str]:
    """解析 --modes：fast,expert,tycoon / all。"""
    text = raw.strip().lower()
    if text in ("all", "4", "*"):
        return ALL_MODES[:]
    chosen: list[str] = []
    for token in re.split(r"[\s,]+", text):
        token = token.strip()
        if not token:
            continue
        if token in ("4", "all"):
            return ALL_MODES[:]
        if token in ("1", "fast"):
            key = "fast"
        elif token in ("2", "expert"):
            key = "expert"
        elif token in ("3", "tycoon"):
            key = "tycoon"
        elif token in MODE_EXTRAS:
            key = token
        else:
            die(f"无法识别的模式：{token}（可用 fast, expert, tycoon, all）")
        if key not in chosen:
            chosen.append(key)
    if not chosen:
        die(f"无效 --modes：{raw}")
    return chosen


def resolve_modes(modes_arg: str | None, install: dict) -> list[str]:
    if modes_arg:
        return parse_modes_arg(modes_arg)
    prev = install.get("modes") or []
    if prev:
        return prev
    return ALL_MODES[:]


# ---------- GitHub 更新检查 ----------

def http_get(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pianke-launcher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def remote_commit_sha() -> str | None:
    info("正在向 GitHub 询问最新版本号...")
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
    try:
        data = json.loads(http_get(url).decode("utf-8"))
        return data.get("sha")
    except Exception as e:
        warn(f"无法连接 GitHub 检查更新（{e.__class__.__name__}），跳过此步")
        warn("不影响本地启动；下次有网时会再试。")
        return None


def download_tarball(sha: str, dest: Path) -> bool:
    url = f"https://codeload.github.com/{GITHUB_OWNER}/{GITHUB_REPO}/tar.gz/{sha}"
    try:
        info("下载新版本...")
        data = http_get(url, timeout=60.0)
        dest.write_bytes(data)
        return True
    except Exception as e:
        warn(f"下载失败：{e}")
        return False


# 不会被更新覆盖的文件 / 目录（用户私有数据 + 体积大的依赖）
PRESERVE = {
    ".venv",
    "pyproject.toml",
    "uv.lock",
    ".pic_selecter_install.json",
    "__pycache__",
    ".git",
    "pic_test",     # 开发用的测试图，可能用户也存了私货
    "aaa",
    "aaa copy 2",
    "aaa copy 3",
    ".DS_Store",
}


def apply_update(tar_path: Path) -> bool:
    """把 tarball 解压到 ROOT，覆盖代码文件，但保留 PRESERVE 列表。"""
    tmp = ROOT / ".update_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(tmp)
        # tarball 顶层是 pianke-<sha>/，取里面内容
        children = [p for p in tmp.iterdir() if p.is_dir()]
        if len(children) != 1:
            warn("更新包结构异常，跳过")
            return False
        src = children[0]

        for item in src.iterdir():
            target = ROOT / item.name
            if item.name in PRESERVE:
                continue
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            tar_path.unlink()
        except OSError:
            pass


def check_and_apply_update(install: dict) -> None:
    local_sha = install.get("commit_sha")
    remote_sha = remote_commit_sha()
    if not remote_sha:
        return  # 离线，跳过
    if local_sha == remote_sha:
        info(f"已是最新版本（{remote_sha[:8]}）")
        return

    if local_sha:
        info(f"发现新版本 {remote_sha[:8]}（当前 {local_sha[:8]}），正在更新...")
    else:
        info(f"标记当前版本为 {remote_sha[:8]}")
        # 首次启动且没有 SHA 记录：只记录，不强制覆盖
        # （因为代码本身就是这次 sha 解压出来的）
        install["commit_sha"] = remote_sha
        save_install(install)
        return

    tar_path = ROOT / ".update.tar.gz"
    if not download_tarball(remote_sha, tar_path):
        return
    if apply_update(tar_path):
        install["commit_sha"] = remote_sha
        # 代码变了，requirements 可能也变了，触发重装检查
        install.pop("requirements_hash", None)
        save_install(install)
        info("代码已更新")
    else:
        warn("更新应用失败，继续使用当前版本")


# ---------- venv + 依赖 ----------

def have_uv() -> str | None:
    for path in (shutil.which("uv"),
                 str(Path.home() / ".local" / "bin" / ("uv.exe" if IS_WIN else "uv")),
                 str(Path.home() / ".cargo" / "bin" / ("uv.exe" if IS_WIN else "uv"))):
        if path and Path(path).exists():
            return path
    return None


def require_uv() -> str:
    uv = have_uv()
    if not uv:
        die(
            "片刻使用 uv 管理 Python 依赖，未找到 uv。\n"
            "  macOS/Linux: curl -LSf https://astral.sh/uv/install.sh | sh\n"
            "  Windows: powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\""
        )
    return uv


def _modes_sync_sig(modes: list[str]) -> str:
    """用于判断是否需要重新 uv sync 的签名。"""
    extras: list[str] = []
    for m in modes:
        extras.extend(MODE_EXTRAS.get(m, []))
    return "uv:" + ",".join(sorted(set(extras))) + "|" + ",".join(sorted(modes))


# 每个模式的预估安装时间（用于打印让用户心里有数）
MODE_TIME_ESTIMATE = {
    "fast": "1-3 分钟",
    "expert": "5-15 分钟（取决于网速；torch/insightface 加起来 ~2GB）",
    "tycoon": "约 30 秒",
}


def _uv_sync_cmd(uv: str, modes: list[str]) -> list[str]:
    """构造 uv sync 命令（按模式启用 optional-dependencies）。"""
    cmd = [uv, "sync", "--python", ">=3.10"]
    seen_extras: set[str] = set()
    for m in modes:
        for extra in MODE_EXTRAS.get(m, []):
            if extra not in seen_extras:
                seen_extras.add(extra)
                cmd += ["--extra", extra]
    if USE_MIRROR:
        cmd += [
            "--index-url", PYPI_MIRROR,
            "--extra-index-url", "https://pypi.org/simple/",
        ]
    return cmd


def _ensure_opencv_single() -> None:
    """OpenCV 三个发行包（opencv-python / opencv-python-headless / opencv-contrib-python）
    共存会导致 cv2 主包覆盖 contrib 的子模块（saliency 等失效）。

    insightface / pyiqa 等传递依赖经常偷偷拉进来 opencv-python——
    每次 install 之后强制做一次清理，再 force-reinstall contrib 版恢复 cv2 文件。
    """
    py = str(PY_IN_VENV)
    # 检查是否有冲突包
    rc = subprocess.run(
        [py, "-c",
         "import importlib.metadata as m; "
         "names={'opencv-python', 'opencv-python-headless'}; "
         "found=[n for n in names if any(d.metadata['Name'].lower()==n for d in m.distributions())]; "
         "print('|'.join(found))"],
        capture_output=True, text=True,
    )
    conflicts = [s for s in (rc.stdout or "").strip().split("|") if s]
    if not conflicts:
        return
    info(f"检测到冲突的 OpenCV 包：{', '.join(conflicts)}，正在清理...")
    uv = require_uv()
    subprocess.call([uv, "pip", "uninstall", "--python", py, "-y", *conflicts])
    cmd = [uv, "pip", "install", "--python", py, "--force-reinstall", "--no-deps"]
    if USE_MIRROR:
        cmd += ["--index-url", PYPI_MIRROR, "--extra-index-url", "https://pypi.org/simple/"]
    cmd += ["opencv-contrib-python>=4.9"]
    subprocess.check_call(cmd)
    info("OpenCV 已修复（只保留 contrib 版） ✓")


def ensure_dependencies(modes: list[str], install: dict, force: bool) -> None:
    """用 uv sync 按模式安装 pyproject.toml 中的依赖。"""
    uv = require_uv()
    sig = _modes_sync_sig(modes)
    last_sig = install.get("packages_sig")
    if not force and last_sig == sig and PY_IN_VENV.exists():
        info("依赖已是最新，跳过 uv sync")
        return

    if not (ROOT / "pyproject.toml").is_file():
        die(f"未找到 pyproject.toml（期望路径：{ROOT / 'pyproject.toml'}）")

    est = "、".join(f"{m}（{MODE_TIME_ESTIMATE[m]}）" for m in modes)
    info(f"uv sync（pyproject.toml）预计耗时：{est}")
    if USE_MIRROR:
        info(f"使用国内镜像源：{PYPI_MIRROR_HOST}")
        info("（海外用户请 `export PIANKE_NO_MIRROR=1` 后重试）")
    info("看到下载进度滚动是正常的，请耐心等待。")
    print()
    subprocess.check_call(_uv_sync_cmd(uv, modes), cwd=str(ROOT))
    print()
    _ensure_opencv_single()
    install["packages_sig"] = sig
    install["modes"] = modes
    save_install(install)
    info("依赖安装完成 ✓")


# ---------- 启动 app ----------

def run_app(port: int) -> int:
    info(f"启动 Flask 服务于 http://localhost:{port}")
    if "expert" in (load_install().get("modes") or []):
        info("专家模式首次启动会加载 DINOv2/NIMA/InsightFace 模型（约 10-30 秒）...")
        if USE_MIRROR:
            info(f"使用 HuggingFace 镜像 {HF_MIRROR}（如已下载过模型则跳过）")
    print()
    print("=" * 56)
    print("  服务启动后浏览器会自动打开。")
    print("  ⚠ 关闭本窗口 = 停止服务。挑完片再关。")
    print("=" * 56)
    print()
    env = os.environ.copy()
    if USE_MIRROR:
        # 让 transformers / huggingface_hub 走国内镜像
        env.setdefault("HF_ENDPOINT", HF_MIRROR)
    cmd = [str(PY_IN_VENV), "app.py", "--port", str(port)]
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


# ---------- 仅安装环境（供 Makefile / CI） ----------

def run_setup_only(*, no_update: bool, modes_arg: str | None) -> int:
    banner("片刻 · 环境准备")
    if USE_MIRROR:
        print("  国内镜像：清华 PyPI + hf-mirror.com（PIANKE_NO_MIRROR=1 可关闭）")
    print()

    if not (ROOT / "app.py").exists():
        die(f"未找到 app.py（期望路径：{ROOT / 'app.py'}）")

    install = load_install()
    if not no_update:
        step(1, 2, "检查 GitHub 更新")
        check_and_apply_update(install)
    else:
        info("跳过 GitHub 更新检查（--no-update）")

    step(2, 2, "准备 Python 虚拟环境与依赖")
    modes = resolve_modes(modes_arg, install)
    info(f"本次启用：{', '.join(modes)}")
    install["modes"] = modes
    save_install(install)
    ensure_dependencies(modes, install, force=False)
    info("环境准备完成 ✓")
    return 0


# ---------- 主流程 ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="片刻 · 启动器")
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="仅创建 .venv 并安装依赖，不启动 app（供 make / CI）",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="跳过 GitHub 更新检查",
    )
    parser.add_argument(
        "--modes",
        default=None,
        metavar="MODES",
        help="非交互指定模式：fast,expert,tycoon 或 all（默认：上次记录，否则全部）",
    )
    args = parser.parse_args()

    if args.setup_only:
        return run_setup_only(no_update=args.no_update, modes_arg=args.modes)

    banner("片刻 · 启动器")
    print()
    print("  本启动器会自动：检查更新 → 选模式 → 装依赖 → 起服务 → 开浏览器")
    if USE_MIRROR:
        print("  当前已开启国内镜像加速（清华 PyPI + hf-mirror.com）")
        print("  海外网络环境请关闭：export PIANKE_NO_MIRROR=1 后重启")
    print()

    if not (ROOT / "app.py").exists():
        die(f"未找到 app.py（期望路径：{ROOT / 'app.py'}）。请确认启动器放在项目根目录。")

    install = load_install()

    # 步骤 1：检查更新
    step(1, 4, "检查 GitHub 更新")
    if not args.no_update:
        check_and_apply_update(install)
    else:
        info("跳过 GitHub 更新检查（--no-update）")

    # 步骤 2：选择模式
    step(2, 4, "选择运行模式")
    if args.modes:
        modes = parse_modes_arg(args.modes)
    else:
        prev_modes = install.get("modes") or []
        modes = ask_modes(prev_modes)
    info(f"本次启用：{', '.join(modes)}")
    install["modes"] = modes
    save_install(install)

    # 步骤 3：venv + 依赖
    step(3, 4, "准备 Python 虚拟环境与依赖")
    ensure_dependencies(modes, install, force=False)

    # 步骤 4：启动
    step(4, 4, "启动应用")
    port = int(os.environ.get("PIC_SELECTER_PORT", "5057"))
    rc = run_app(port)

    if rc != 0:
        warn(f"app.py 以非零状态退出（{rc}）")
        try:
            input("按回车键退出...")
        except EOFError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
