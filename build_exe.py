#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_exe.py — 把图形面板打包成 exe（双击即用，不需要装 Python）

    <venv>/Scripts/python.exe build_exe.py              # 单文件（启动稍慢）
    <venv>/Scripts/python.exe build_exe.py --onedir     # 目录模式（启动快，产物是文件夹）

产物落在 Tools/ 下。exe 必须与工具脚本同目录，因为工具要操作真实工作区，
不能塞进 exe 的解包临时目录 —— exe 只负责带运行环境和界面。
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
DEFAULT_NAME = "LaTeX-Toolbox"
BUILD = TOOLS / "_build"


def main():
    ap = argparse.ArgumentParser(description="打包工具集面板为 exe")
    ap.add_argument("--onedir", action="store_true",
                    help="目录模式：启动更快，但产物是一个文件夹")
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--clean", action="store_true", help="清掉缓存重新打包")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller。装到工具环境：\n"
              "  <venv>/Scripts/python.exe -m pip install pyinstaller "
              "--index-url https://mirrors.aliyun.com/pypi/simple/")
        return 1

    if not (TOOLS / "panel_qt.py").is_file():
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
        # panel_core 里是「先改 sys.path 再 import」，静态分析看不到
        "--hidden-import", "launcher",
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
    if not args.onedir:
        cmd.append("--onefile")
    cmd.append(str(TOOLS / "panel_qt.py"))

    print("开始打包…（首次会慢一些）")
    print(" ".join(cmd[:8]) + " …")
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(TOOLS))
    if proc.returncode != 0:
        print("\n打包失败，退出码 {}".format(proc.returncode))
        return proc.returncode

    target = TOOLS / (args.name + (".exe" if not args.onedir else ""))
    if args.onedir:
        target = TOOLS / args.name / (args.name + ".exe")
    if target.exists():
        size = target.stat().st_size / (1024 * 1024)
        print("\n产物：{}（{:.1f} MB，用时 {:.0f} 秒）".format(
            target, size, time.time() - started))
    else:
        print("\n打包命令成功，但没找到预期产物：{}".format(target))
        return 1
    print("双击即可打开面板；exe 需要和工具脚本放在同一个目录（默认就是 Tools/）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
