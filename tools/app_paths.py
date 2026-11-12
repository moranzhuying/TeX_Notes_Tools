#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app_paths.py — 运行期路径：工作区在哪、数据写在哪。

工具集有两种形态，同一个模块都要伺候：

**便携**（整个 `Tools/` 躺在工作区里，本机就是这种）
    数据留在程序目录旁，工作区由「程序目录的父级」推出，零配置。

**安装**（程序装在 `Program Files` 或 `%LOCALAPPDATA%\\Programs`）
    程序目录只读，配置进 `%APPDATA%`、大件进 `%LOCALAPPDATA%`，
    工作区由 `config.json` 指定。

判定顺序：环境变量 `LATEX_TOOLBOX_PORTABLE` → 程序目录下的 `portable.flag`
→ 程序目录的父级是否像个工作区（有 `LaTeX_Notes` 或 `Template`）。
读配置不会反过来影响这个判定，避免自引用。

本模块不 import 任何工具代码：18 个工具都从它取路径，它自己必须最轻。
"""
import json
import os
import sys
from pathlib import Path

#: 程序目录（含 `LaTeX-Toolbox.exe` 与 `tools/` 的那一层）。
APP_DIR = Path(__file__).resolve().parent.parent

APP_NAME = "LaTeX-Toolbox"
CONFIG_NAME = "config.json"


def _env_dir(name, fallback):
    raw = os.environ.get(name)
    return Path(raw) if raw else Path.home() / fallback


def roaming_dir():
    """配置根：`%APPDATA%\\LaTeX-Toolbox`（跟着域账户漫游，只放小文件）。"""
    return _env_dir("APPDATA", ".config") / APP_NAME


def local_dir():
    """大件根：`%LOCALAPPDATA%\\LaTeX-Toolbox`（模型、缓存、日志）。"""
    return _env_dir("LOCALAPPDATA", ".local/share") / APP_NAME


def _looks_like_workspace(p):
    return (p / "LaTeX_Notes").is_dir() or (p / "Template").is_dir()


def portable():
    """程序是不是住在工作区里。"""
    env = (os.environ.get("LATEX_TOOLBOX_PORTABLE") or "").strip().lower()
    if env in ("0", "1"):
        return env == "1"
    if (APP_DIR / "portable.flag").is_file():
        return True
    return _looks_like_workspace(APP_DIR.parent)


def config_path():
    """配置文件位置。便携态就在程序目录，安装态在 `%APPDATA%`。"""
    return (APP_DIR / CONFIG_NAME) if portable() else roaming_dir() / CONFIG_NAME


def config():
    """读配置；文件不存在或坏了都返回空字典，不让工具起不来。"""
    path = config_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def save_config(data):
    """写配置。写不了也不能让工具崩，只返回 False。"""
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return True
    except OSError:
        return False


def data_root():
    """数据根。

    便携形态 = `tools/`（各工具目录就在里面，配置文件照旧躺在自己的目录里）；
    安装形态 = `%LOCALAPPDATA%\\LaTeX-Toolbox`，每个工具一个子目录。
    配置里给了 `data_dir` 就听配置（模型可以挪到别的盘）。
    """
    custom = (config().get("data_dir") or "").strip()
    if custom:
        p = Path(os.path.expandvars(custom)).expanduser()
        if not p.is_absolute():
            p = (config_path().parent / p).resolve()
        return p
    return (APP_DIR / "tools") if portable() else local_dir()


def data_dir(name=None, ensure=False):
    """某个工具的数据目录；`ensure=True` 时顺手建出来。"""
    root = data_root() / name if name else data_root()
    if ensure:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return root


def conf_file(tool, name, ensure=False):
    """某个工具的配置文件：数据目录下的 `<tool>/<name>`。

    读方不止一个（`new_note` / `note_tools` / `repo_check` / `sync_paths`
    都要读 `manager.conf`），所以位置只在这里定义一次。
    """
    return data_dir(tool, ensure=ensure) / name


def config_dir():
    """应用级配置目录（面板设置这类小文件）。"""
    return APP_DIR if portable() else roaming_dir()


def settings_file(name):
    """应用级配置文件路径，例如面板的 `_panel_config.json`。"""
    return config_dir() / name


def log_dir(ensure=True):
    """日志目录。便携形态在程序目录的 `logs/`，安装形态进 `%LOCALAPPDATA%`。"""
    d = (APP_DIR / "logs") if portable() else (local_dir() / "logs")
    if ensure:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return d


def workspace():
    """工作区根。

    配置里有 `workspace` 就用它（相对路径按配置文件所在目录解析）；
    没有则回退「程序目录的父级」——于是便携形态仍然零配置。
    返回的路径**不保证存在**，调用方要自己判断。
    """
    raw = (config().get("workspace") or "").strip()
    if raw:
        p = Path(os.path.expandvars(raw)).expanduser()
        if not p.is_absolute():
            p = (config_path().parent / p).resolve()
        return p
    return APP_DIR.parent


def workspace_ok():
    """工作区是否可用（存在且像个工作区目录）。"""
    ws = workspace()
    return ws.is_dir()


def describe():
    """给自检 / 设置页看的一份快照。"""
    return {
        "程序目录": APP_DIR,
        "形态": "便携" if portable() else "安装",
        "配置文件": config_path(),
        "数据根": data_root(),
        "工作区": workspace(),
        "工作区可用": workspace_ok(),
    }


def _bootstrap_tool():
    """让工具目录里的脚本能直接 `from app_paths import ...`。

    工具都在 `<程序目录>/tools/<名字>/` 下，父级就是本文件所在目录。
    """
    me = Path(__file__).resolve().parent
    if str(me) not in sys.path:
        sys.path.insert(0, str(me))


if __name__ == "__main__":
    for k, v in describe().items():
        print(f"{k}: {v}")
