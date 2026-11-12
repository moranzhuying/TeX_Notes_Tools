#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_core.py — 面板的共用逻辑（工具清单、启动、停止、状态）

`panel_qt.py`（桌面窗口）与 `panel_gui.py`（本地网页备用）都调用这里，
避免同一套启动规则写两遍。菜单本身来自 `launcher.py` 的 `MENU`，只有一处定义。
"""
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包成 exe 后 __file__ 指向解包临时目录，工具脚本仍在 exe 旁边；
    # exe 约定放在 Tools/ 下，所以取 exe 所在目录作为工具根。
    TOOLS_ROOT = Path(sys.executable).resolve().parent
else:
    TOOLS_ROOT = Path(__file__).resolve().parent
WORKSPACE = TOOLS_ROOT.parent
MAX_LINES = 4000

sys.path.insert(0, str(TOOLS_ROOT))
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
            "exists": (TOOLS_ROOT / rel).is_file(),
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


def _spawn_prefix(script):
    """「用什么命令执行这个 .py」的前缀。

    打包成 exe 时没有外部 Python 可用，让 exe 自己充当解释器（`--exec` 模式）；
    源码运行时用当前解释器。`--` 之后一律原样传给目标脚本。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--exec", str(script), "--"]
    return [PYTHON, str(script)]


def launch(key, extra=""):
    """启动一个工具并登记运行记录。extra 是追加参数（仅一次性命令用得上）。"""
    item = tool_by_id(key)
    if item is None:
        raise PanelError("未知工具编号")
    _no, _title, rel, mode, _grp = item
    script = TOOLS_ROOT / rel
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

    if mode.startswith("参数:"):
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rec = {"proc": proc, "mode": "capture", "started": time.time(),
               "output": deque(maxlen=MAX_LINES), "returncode": None}
        threading.Thread(target=_pump, args=(rec, proc), daemon=True).start()
    else:
        # 交互面板必须有真终端：这些工具都是 input() 循环，无控制台直接 OSError
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
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
