#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_core.py — 面板的共用逻辑（工具清单、启动、停止、状态）

`panel_qt.py`（桌面窗口）与 `panel_gui.py`（本地网页备用）都调用这里，
避免同一套启动规则写两遍。菜单本身来自 `launcher.py` 的 `MENU`，只有一处定义。
"""
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包成 exe 后 __file__ 指向解包临时目录，程序目录取 exe 所在处。
    TOOLS_ROOT = Path(sys.executable).resolve().parent
else:
    TOOLS_ROOT = Path(__file__).resolve().parent.parent      # 源码在 <程序目录>/src/

#: 工具脚本所在：<程序目录>/tools/。老布局把脚本摆在程序目录下，回退过去仍能跑。
SCRIPTS_DIR = TOOLS_ROOT / "tools"
if not SCRIPTS_DIR.is_dir():
    SCRIPTS_DIR = TOOLS_ROOT

MAX_LINES = 4000

#: 启动子进程时不弹控制台窗口。
#: GUI 子系统程序（windowed exe）调控制台子程序时，Windows 会新分配控制台
#: 并弹黑窗。所有外部命令都要带上这个标志。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 面板代码自己（源码是 src/，打包后与 exe 同源）；tools/ 下是工具与公共模块。
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS_DIR))
import app_paths  # noqa: E402 —— 工作区与数据落点的唯一来源
WORKSPACE = app_paths.workspace()
import launcher  # noqa: E402  —— 复用 MENU / split_args

MENU = launcher.MENU
SUBMIT_NO = launcher.SUBMIT_NO

#: 每个工具的一句话说明（卡片上显示；MENU 里的标题偏长，需要更短的补充）
DESCRIPTIONS = {
    "1": "检测 python / git / ssh 版本，配置账户与 443 端口",
    "2": "查看各笔记仓库状态、批量提交推送、新建远程仓库",
    "3": "符号的提取 / 回填 / 删除 / 修改，并分发到各笔记",
    "4": "写作工作台服务器，默认只读，按书单独授权写入",
    "5": "从模板复制骨架建一本新笔记，可套大纲生成章节",
    "6": "从 main.tex 导出大纲、校验大纲与目录是否一致",
    "7": "单本笔记的快捷入口：提交、习题模式、补导引与小结",
    "8": "清理 aux / log / xdv / synctex 等编译产物",
    "9": "检查规范副本、误跟踪文件、未提交改动",
    "10": "扫描仓库里是否混入本机路径、密钥、用户名",
    "11": "检查配置里的路径是否有效，并按需修复",
    "12": "把本工具集仓库 add → commit → push",
    "13": "视频转文字：字幕优先，无字幕走本地 whisper",
    "14": "项目规范在多个仓库之间的副本一致性检查与同步",
    "15": "把横躺的课件 PDF 就地转正为 16:9，不重编码",
    "16": "监测笔记目录，有改动自动提交推送，并按上限裁剪历史",
}

LOCK = threading.Lock()
RUNNING = {}  # id -> {"proc", "mode", "started", "output": deque, "returncode"}


class PanelError(ValueError):
    """可直接展示给用户的错误（不是程序缺陷）。"""


def python_exe():
    """拿 python.exe 而不是 pythonw.exe：后者没有控制台，交互工具会看不见输出。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        alt = exe.with_name("python.exe")
        if alt.is_file():
            return str(alt)
    return str(exe)


PYTHON = python_exe()


def _normpath(p):
    """统一大小写与 8.3 短名，供路径前缀比较。

    PyInstaller 往 PATH 里写的是长名（`%USERPROFILE%\\AppData\\...`），
    而 `_MEIPASS` 常是短名（`%USERPROFILE%` 折成 8.3 形式），
    直接 startswith 会比不中。
    """
    try:
        return os.path.normcase(os.path.realpath(str(p)))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(str(p)))


def tool_python():
    """装了工具依赖的那个解释器（用户主目录的 venv default）。

    exe 自带的解释器只有标准库和 PySide6；pymupdf / numpy / faster-whisper
    都在 venv 里。打包后必须用 venv 的 python 跑工具，否则这些工具一启动
    就 ImportError —— 或者更糟：被 PyInstaller 的 python DLL 混着加载而挂死。
    """
    override = os.environ.get("PANEL_PYTHON")
    if override and Path(override).is_file():
        return Path(override)
    base = Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default"
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        cand = base.joinpath(*rel)
        if cand.is_file():
            return cand
    return None


def child_env():
    """给子进程一份干净环境：剥掉 PyInstaller 为打包解释器注入的东西。

    exe 会把 `_MEIPASS` 塞进 PATH 最前面，并设 `QT_PLUGIN_PATH` / `_PYI_*`。
    子进程若是**另一个**解释器（venv 的 python），这些项会让它加载 exe 解包
    目录里的 python313.dll 与 Qt 插件 —— 版本对不上就静默挂死，症状是「点了
    没反应」。清掉之后子进程只用自己的环境。
    """
    env = dict(os.environ)
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE",
                "_PYI_PARENT_PROCESS_LEVEL", "_PYI_SPLASH_IPC",
                "_PYI_ONEFILE_PARENT"):
        env.pop(key, None)

    mei = getattr(sys, "_MEIPASS", "")
    if mei:
        target = _normpath(mei)
        kept = [p for p in env.get("PATH", "").split(os.pathsep)
                if p and not _normpath(p).startswith(target)]
        env["PATH"] = os.pathsep.join(kept)
    return env


def tool_by_id(key):
    return next((m for m in MENU if m[0] == key), None)


def describe_tools():
    """给界面用的工具清单（不含运行状态）。"""
    tools = []
    for no, title, rel, mode, grp in MENU:
        tools.append({
            "id": no,
            "title": title,
            "script": rel,
            "mode": mode,
            "group": grp,
            "desc": DESCRIPTIONS.get(no, ""),
            "submit": no == SUBMIT_NO,
            "oneoff": mode.startswith("参数:"),
            "defaultArgs": mode.split(":", 1)[1] if mode.startswith("参数:") else "",
            "exists": (SCRIPTS_DIR / rel).is_file(),
        })
    return tools


def _pump(rec, proc):
    """一次性命令：把输出读进环形缓冲，结束后记退出码。"""
    try:
        for line in proc.stdout:
            rec["output"].append(line.rstrip("\n"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        rec["returncode"] = proc.poll()


def spawn_command(script, args=()):
    """返回 (program, argv)：执行某个 .py 的命令行。

    打包成 exe 后**优先用 venv 里的 python** 跑脚本：exe 的解释器没有工具依赖
    （pymupdf、faster-whisper 等），拿它跑等于让工具一启动就 ImportError。
    只有找不到 venv 时才退回「exe 自己当解释器」（`--exec`）。
    供启动器与「可视化表单」两条路径共用，避免各写一套。
    """
    script = Path(script)
    extra = [str(a) for a in args]
    if getattr(sys, "frozen", False):
        py = tool_python()
        if py is not None:
            return str(py), [str(script)] + extra
        return sys.executable, ["--exec", str(script), "--"] + extra
    return PYTHON, [str(script)] + extra


def _spawn_prefix(script):
    """「用什么命令执行这个 .py」的前缀（`--` 之后原样传给目标脚本）。"""
    if getattr(sys, "frozen", False):
        py = tool_python()
        if py is not None:
            return [str(py), str(script)]
        return [sys.executable, "--exec", str(script), "--"]
    return [PYTHON, str(script)]


def launch(key, extra=""):
    """启动一个工具并登记运行记录。extra 是追加参数（仅一次性命令用得上）。"""
    item = tool_by_id(key)
    if item is None:
        raise PanelError("未知工具编号")
    _no, _title, rel, mode, _grp = item
    script = SCRIPTS_DIR / rel
    if not script.is_file():
        raise PanelError("找不到脚本：{}".format(rel))

    tool_args = []
    if mode.startswith(("参数:", "后台:")):
        tool_args += launcher.split_args(mode.split(":", 1)[1])
    if extra and extra.strip():
        if not mode.startswith(("参数:", "后台:")):
            raise PanelError("该工具是交互面板，不接受追加参数")
        tool_args += launcher.split_args(extra)
    args = _spawn_prefix(script) + tool_args
    env = child_env()

    if mode.startswith("参数:"):
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW, env=env)
        rec = {"proc": proc, "mode": "capture", "started": time.time(),
               "output": deque(maxlen=MAX_LINES), "returncode": None}
        threading.Thread(target=_pump, args=(rec, proc), daemon=True).start()
    else:
        # 交互面板必须有真终端：这些工具都是 input() 循环，无控制台直接 OSError。
        # CREATE_NEW_CONSOLE 会开一个**新的**控制台窗口（不是隐藏），所以这个
        # 标志与「不要弹命令行窗口」冲突。网页备用版需要真终端，桌面版不用，
        # 由调用方通过 env 里的 PANEL_HIDE_CONSOLE 决定。
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        if os.environ.get("PANEL_HIDE_CONSOLE") == "1":
            # 桌面版：复用当前控制台（若父进程有），不新开窗口。
            # 父进程是 GUI 程序没有控制台时，子进程会因 input() 拿不到输入而
            # 立刻 EOF —— 这正是「点一下就结束」的表现，所以这条路只给网页版用。
            flags = 0
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            creationflags=flags, env=env)
        rec = {"proc": proc, "mode": "console", "started": time.time(),
               "output": deque(maxlen=MAX_LINES), "returncode": None}

    with LOCK:
        RUNNING[key] = rec
    return rec


def stop(key):
    """终止该工具最近一次启动的进程（连子进程）。"""
    with LOCK:
        rec = RUNNING.get(key)
    if rec is None:
        raise PanelError("该工具当前没有运行")
    proc = rec["proc"]
    if proc.poll() is not None:
        return "已结束，无需停止"
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()
    return "已发送停止信号"


def record(key):
    with LOCK:
        return RUNNING.get(key)


def forget(key):
    with LOCK:
        RUNNING.pop(key, None)


def output_of(key):
    rec = record(key)
    return list(rec["output"]) if rec else []


def run_state(key):
    """返回该工具的运行快照；没跑过则 None。"""
    rec = record(key)
    if rec is None:
        return None
    rc = rec["returncode"] if rec["returncode"] is not None else rec["proc"].poll()
    return {
        "pid": rec["proc"].pid,
        "mode": rec["mode"],
        "started": rec["started"],
        "alive": rc is None,
        "returncode": rc,
        "hasOutput": rec["mode"] == "capture",
        "lines": len(rec["output"]),
    }
