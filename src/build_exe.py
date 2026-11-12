#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_exe.py — 把图形面板打包成 exe（双击即用，不需要装 Python）

    <venv>/Scripts/python.exe build_exe.py              # 单文件（启动稍慢）
    <venv>/Scripts/python.exe build_exe.py --onedir     # 目录模式（启动快，产物是文件夹）

产物落在 Tools/ 下（与 src/ 同级）。工具脚本留在 src/ 里、不塞进 exe 的解包临时
目录 —— 它们要操作真实工作区；exe 只负责带运行环境和界面。
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent          # <程序目录>/src/
TOOLS = SRC.parent                             # <程序目录>
RES = TOOLS / "resources"                      # 图标等资源
DEFAULT_NAME = "LaTeX-Toolbox"
BUILD = TOOLS / "_build"


def flatten(dist_dir, name):
    """把 `dist/<name>/` 里的 exe 与 `_internal/` 摊到程序目录根。

    安装形态要的是 `App.exe` + `_internal/` 同级，而不是再套一层同名目录。
    覆盖前先清掉旧的 `_internal`，否则上一次构建残留的 dll 会混进来。
    """
    moved = []
    for item in sorted(dist_dir.iterdir()):
        dst = TOOLS / item.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(item), str(dst))
        moved.append(item.name)
    try:
        dist_dir.rmdir()
    except OSError:
        pass
    return moved


def main():
    ap = argparse.ArgumentParser(description="打包工具集面板为 exe")
    ap.add_argument("--onefile", action="store_true",
                    help="单文件：每次启动解包约 90 MB，慢；仅在需要单文件分发时用")
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--clean", action="store_true", help="清掉缓存重新打包")
    args = ap.parse_args()

    try:
        import importlib.util
        if importlib.util.find_spec("PyInstaller") is None:
            raise ImportError
    except ImportError:
        print("缺少 PyInstaller。装到工具环境：\n"
              "  <venv>/Scripts/python.exe -m pip install pyinstaller "
              "--index-url https://mirrors.aliyun.com/pypi/simple/")
        return 1

    if not (SRC / "panel_qt.py").is_file():
        print("找不到 panel_qt.py")
        return 1
    if args.clean and BUILD.exists():
        shutil.rmtree(BUILD)

    # 正在运行的旧产物会锁住文件，PyInstaller 覆盖时报 PermissionError
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/IM", args.name + ".exe", "/F"],
                       capture_output=True, stdin=subprocess.DEVNULL)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",                      # 无控制台窗口；--exec 模式再挂新控制台
        "--name", args.name,
        "--distpath", str(TOOLS),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        # 面板模块都在 src/ 下，入口也在那儿；把 src 加进搜索路径，
        # 否则 panel_core 里「先改 sys.path 再 import launcher」这条链
        # 静态分析看不到。
        "--paths", str(SRC),
        "--hidden-import", "launcher",
        # 窗口与 exe 图标（make_icon.py 生成，产物在 src/）
        "--icon", str(RES / "tools.ico"),
        # 运行时窗口图标要从包里读，所以要把 ico 也打进去
        "--add-data", "{};.".format(RES / "tools.ico"),
        # 没用到的大件，明确排掉以免被间接拉进来
        "--exclude-module", "tkinter",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtDataVisualization",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml",
    ]
    if args.onefile:
        cmd.append("--onefile")
    cmd.append(str(SRC / "panel_qt.py"))

    print("开始打包…（首次会慢一些）")
    print(" ".join(cmd[:8]) + " …")
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(SRC))
    if proc.returncode != 0:
        print("\n打包失败，退出码 {}".format(proc.returncode))
        return proc.returncode

    dist_dir = TOOLS / args.name
    if not args.onefile and dist_dir.is_dir():
        moved = flatten(dist_dir, args.name)
        print("\n已摊平到程序目录：", ", ".join(moved))

    target = TOOLS / (args.name + ".exe")
    if target.exists():
        size = target.stat().st_size / (1024 * 1024)
        extra = ""
        if not args.onefile:
            internal = TOOLS / "_internal"
            if internal.is_dir():
                total = sum(f.stat().st_size for f in internal.rglob("*") if f.is_file())
                extra = "，_internal {:.0f} MB".format(total / 1024 / 1024)
        print("\n产物：{}（{:.1f} MB{}，用时 {:.0f} 秒）".format(
            target, size, extra, time.time() - started))
    else:
        print("\n打包命令成功，但没找到预期产物：{}".format(target))
        return 1
    print("双击即可打开面板；exe 在程序目录根，工具脚本在它旁边的 tools/ 下。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
