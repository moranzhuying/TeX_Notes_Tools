#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_qt.py — 工具集图形面板（Qt 桌面窗口，Fluent / WinUI 风格）

布局参照 Watt Toolkit：左侧竖向导航把工具分组，右侧是当前组的卡片流，
顶部一条工具栏放标题、搜索与主题切换。深浅主题跟随系统，可手动切换。

菜单来自 `panel_core`（它再 import `launcher.MENU`），命令行面板、Qt 面板
与网页备用版共用同一份清单。

- **交互面板类**（多数工具）→ 弹出独立控制台，`input()` 行为与命令行一致
- **一次性命令类** → 捕获输出，结果显示在下方输出面板

    python panel_qt.py                 # 打开面板
    python panel_qt.py --selftest      # 打包后自检

依赖 PySide6（装在 .workbuddy 的 venv 里，不进系统 Python）。
"""
import os
import re
import subprocess
import sys
from pathlib import Path


def _venv_python():
    """找装了 PySide6 的工具 venv 解释器；没有就返回 None。

    为什么要在脚本里自找：双击 .py、从别的目录 `python panel_qt.py`、
    或者 bat 的路径判断被系统环境影响时，拉起的都是系统那个精简 Python，
    它没有 PySide6。与其让用户自己配环境，不如换解释器重启一次。

    注意 venv 在**用户主目录**下的 .workbuddy（工具数据区），
    不是工作区里的那个 .workbuddy（项目数据区），两者同名但不同处。
    """
    override = os.environ.get("PANEL_PYTHON")
    if override and Path(override).is_file():
        return Path(override)
    bases = [Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default"]
    # 工作区里也放一份的机器：Tools/src/panel_qt.py → 上溯三级到工作区
    bases.append(Path(__file__).resolve().parents[2]
                 / ".workbuddy" / "binaries" / "python" / "envs" / "default")
    for base in bases:
        if not (base / "Lib" / "site-packages" / "PySide6").is_dir():
            continue
        for name in ("pythonw.exe", "python.exe"):
            cand = base / "Scripts" / name
            if cand.is_file():
                return cand
    return None


def _dbg(msg):
    """PANEL_DEBUG=1 时把诊断写进文件（windowed 模式没有控制台可看）。"""
    if not os.environ.get("PANEL_DEBUG"):
        return
    try:
        log = Path(os.environ.get("PANEL_DEBUG_LOG", "panel_debug.log"))
        with open(log, "a", encoding="utf-8", errors="replace", newline="") as fh:
            fh.write("{}\n".format(msg))
    except OSError:
        pass


def _bind_console():
    """把标准流接回来。windowed exe 启动时 stdout/stdin 是 None。

    两种来源，按优先级：
    1. **继承来的句柄**（父进程给的管道）：直接接管 fd 0/1。QProcess 启动时
       就是这种，交互工具的 input() 要靠它。
    2. **自己开控制台**：双击 exe、没有管道时，AllocConsole 后绑 CONOUT$/CONIN$。
       注意 `CREATE_NEW_CONSOLE` 对 GUI 子系统程序无效，不能指望它。
    """
    if sys.stdout is not None and sys.stdin is not None:
        _dbg("bind: 标准流已就绪，跳过")
        return

    if sys.stdout is None:
        try:
            sys.stdout = open(1, "w", encoding="utf-8", errors="replace",
                              buffering=1, closefd=False)
        except OSError as exc:
            _dbg("接管 fd 1 失败: {}".format(exc))
    if sys.stdin is None:
        try:
            sys.stdin = open(0, "r", encoding="utf-8", errors="replace",
                             closefd=False)
        except OSError as exc:
            _dbg("接管 fd 0 失败: {}".format(exc))

    if sys.stdout is None or sys.stdin is None:
        if os.name == "nt":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                if not kernel32.GetConsoleWindow():
                    if not kernel32.AllocConsole():
                        _dbg("AllocConsole 返回失败")
            except Exception as exc:  # noqa: BLE001 —— 开控制台失败不该拖垮工具
                _dbg("AllocConsole 异常: {}".format(exc))
        if sys.stdout is None:
            try:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8",
                                  errors="replace", buffering=1)
            except OSError:
                sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stdin is None:
            try:
                sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
            except OSError:
                pass
    if sys.stderr is None:
        sys.stderr = sys.stdout
    _dbg("bind 之后: stdout={!r} stdin={!r}".format(sys.stdout, sys.stdin))


def error_log_path():
    """崩溃日志的落点。日志统一进「日志目录」（便携版 `Tools/logs/`，
    安装版 `%LOCALAPPDATA%\\LaTeX-Toolbox\\logs\\`）—— 别写进解包临时目录，
    也别写程序目录（安装后只读）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import app_paths
        return app_paths.log_dir() / "_panel_error.log"
    except Exception:  # noqa: BLE001 —— 拿不到路径也要能留痕
        base = (Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent.parent)
        return base / "_panel_error.log"


def _pause(msg):
    """崩溃后等一次回车。只在真的有终端时才停 —— 被面板捕获输出时停住
    会让子进程永远不退出。"""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input(msg)
    except (EOFError, OSError, ValueError):
        pass


def exec_tool(argv):
    """以自身当解释器执行一个 .py —— 打包成 exe 且找不到 venv python 时走这里。

    工具脚本必须从磁盘上的真实 Tools 目录跑（它们要操作真实工作区），
    不能塞进 exe 的解包临时目录，所以这里是「解释器」而不是「导入器」。

    注意这条路是兜底：exe 的解释器没有工具依赖（pymupdf / numpy /
    faster-whisper 都在 venv 里），正常情况下 panel_core 直接用 venv 的
    python 跑工具，不会走到这儿。
    """
    import runpy
    import traceback

    _bind_console()

    # 先洗掉 PyInstaller 注入的环境：目标脚本可能再派生解释器（pdf_upright、
    # video2text 都会），那些子进程若继承了 _MEIPASS 的 PATH，会去加载 exe
    # 解包目录里的 python313.dll，然后静默挂死。
    try:
        import panel_core as _core
        clean = _core.child_env()
        os.environ.clear()
        os.environ.update(clean)
    except Exception:  # noqa: BLE001 —— 环境清理失败不该挡住工具
        pass

    if not argv:
        print("用法：<exe> --exec <脚本.py> [-- 参数...]")
        return 2
    script = Path(argv[0]).resolve()
    rest = argv[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not script.is_file():
        print("找不到脚本：{}".format(script))
        return 2

    sys.argv = [str(script)] + rest
    os.chdir(str(script.parent))
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        return 0 if code is None else 1
    except BaseException:  # noqa: BLE001 —— 子工具崩了要留下栈，别静默退出
        traceback.print_exc()
        _pause("\n按回车关闭…")
        return 1
    return 0


#: 工具依赖的第三方包。自检时用工具解释器逐个探，缺了就是「点了没反应」的根。
TOOL_DEPS = ("pymupdf", "numpy", "yt_dlp", "faster_whisper", "playwright")


def selftest():
    """打包后自检：工具根、工具解释器、依赖、子进程环境、能否拉起子工具。"""
    import time as _time

    _bind_console()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import panel_core

    print("exe            :", sys.executable)
    print("frozen         :", getattr(sys, "frozen", False))
    print("工具根         :", panel_core.TOOLS_ROOT)
    print("脚本根         :", panel_core.SCRIPTS_DIR)
    print("工作区         :", panel_core.WORKSPACE)

    py = panel_core.tool_python()
    print("工具解释器     :", py or "（未找到 venv —— 回退 exe --exec，依赖会缺）")

    env = panel_core.child_env()
    mei = _normcase(getattr(sys, "_MEIPASS", ""))
    dirty = [p for p in env.get("PATH", "").split(os.pathsep)
             if p and mei and _normcase(p).startswith(mei)]
    print("子进程环境     :", "干净" if not dirty else "仍含 _MEIPASS：{}".format(dirty))
    if "QT_PLUGIN_PATH" in env:
        print("                 QT_PLUGIN_PATH 未清除")

    if py:
        probe = ("import importlib.util as u, sys;"
                 "missing=[n for n in %r if u.find_spec(n) is None];"
                 "print(','.join(missing) if missing else '无')" % (list(TOOL_DEPS),))
        r = subprocess.run([str(py), "-c", probe], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print("缺依赖         :", (r.stdout or "").strip() or r.stderr.strip()[:200])

    tools = panel_core.describe_tools()
    missing = [t["id"] for t in tools if not t["exists"]]
    print("工具数         :", len(tools), "缺失:", missing or "无")
    if missing:
        return 1

    rec = panel_core.launch("11")
    print("子进程         :", rec["proc"].pid, rec["mode"])
    for _ in range(120):
        _time.sleep(0.5)
        state = panel_core.run_state("11")
        if state and not state["alive"]:
            break
    state = panel_core.run_state("11") or {}
    lines = len(panel_core.output_of("11"))
    print("退出码         :", state.get("returncode"))
    print("输出行数       :", lines)
    if state.get("returncode") != 0 or lines <= 0:
        print("第一行         :", (panel_core.output_of("11") or ["(空)"])[0][:120])
        return 1
    print("自检通过")
    return 0


def _normcase(p):
    """大小写 + 8.3 短名归一，供前缀比较（PATH 里长名短名混用）。"""
    try:
        return os.path.normcase(os.path.realpath(str(p)))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(str(p)))


if __name__ == "__main__" and len(sys.argv) > 1:
    if sys.argv[1] == "--exec":
        sys.exit(exec_tool(sys.argv[2:]))
    if sys.argv[1] == "--selftest":
        sys.exit(selftest())


try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover - 只在环境缺包时触发
    if os.environ.get("PANEL_QT_REEXEC") != "1":
        alt = _venv_python()
        if alt is not None and Path(sys.executable).resolve() != alt.resolve():
            env = dict(os.environ, PANEL_QT_REEXEC="1")
            subprocess.Popen([str(alt), str(Path(__file__).resolve()), *sys.argv[1:]],
                             env=env)
            raise SystemExit(0)
    sys.stderr.write(
        "缺少 PySide6，且没找到可用的工具 venv。装到工具专用环境：\n"
        "  <venv>/Scripts/python.exe -m pip install PySide6-Essentials "
        "--index-url https://mirrors.aliyun.com/pypi/simple/\n")
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_core as core  # noqa: E402
import panel_actions as actions  # noqa: E402
import panel_config as config  # noqa: E402
import panel_pages as pages  # noqa: E402

#: 界面总缩放（系统文本大小 × 用户档位）。所有写死的尺寸都经 px() 换算，
#: 控件构造时读一次即可 —— 改档位会重建 QSS 并重设固定尺寸。
_UI_SCALE = 1.0


def text_scale():
    """Windows「辅助功能 → 文本大小」的倍率。

    Qt 只跟随显示缩放（devicePixelRatio），**不理会**这个独立设置：
    用户把文本调到 125%，Qt 应用一律不变。这是 DPI 适配里唯一真正缺的一环，
    读的是 HKCU\\Software\\Microsoft\\Accessibility 的 TextScaleFactor（100 = 100%）。
    """
    if os.name != "nt":
        return 1.0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Accessibility") as key:
            value = winreg.QueryValueEx(key, "TextScaleFactor")[0]
    except (OSError, ValueError):
        return 1.0
    try:
        factor = float(value) / 100.0
    except (TypeError, ValueError):
        return 1.0
    return min(2.0, max(0.8, factor))


def dpi_scale():
    """按屏幕物理像素密度给出的建议字号倍率。

    Qt 已经把逻辑 px 按 devicePixelRatio 放大到物理 px，所以「物理尺寸」是
    恒定的。但同样 19px 的字，在 20 吋 2880 宽的屏上比在 24 吋 1920 宽的屏上
    看着小一圈 —— 屏大了、视距没变。所以按物理 DPI 给一点补偿：
    普通屏 1.0，高密度屏略放大，克制地分三档。
    """
    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    dpi = screen.physicalDotsPerInch()
    if dpi <= 0:
        return 1.0
    if dpi >= 180:          # 4K / 高分屏
        return 1.18
    if dpi >= 130:          # 2K 及典型的 150% 缩放屏
        return 1.10
    return 1.0


def ui_scale():
    """当前生效的界面倍率，供其它模块算固定尺寸。"""
    return _UI_SCALE


def px(value):
    """把设计稿里的逻辑像素换算成当前倍率下的逻辑像素。"""
    return max(1, int(round(value * _UI_SCALE)))


def scale_px(text, scale):
    """把一段样式表里的 px 数值统一乘倍率。

    1px、2px 不动 —— 那是边框与分隔线，放大后线条变粗会显得笨重，
    而且 1px 逻辑在高 DPI 下本来就会被渲染成 1~2 物理像素。
    """
    def repl(m):
        value = int(m.group(1))
        if value <= 2:
            return m.group(0)
        return "{}px".format(max(1, int(round(value * scale))))

    return re.sub(r"(\d+)px", repl, text)


CARD_MIN_WIDTH = 360
CARD_MAX_WIDTH = 660
GAP = 12

#: 每个工具的图标（用彩色 emoji，不依赖字形码点，换机器也不会变方块）
ICONS = {
    "1": "🔀", "2": "📚", "3": "🔤", "4": "🖥️",
    "5": "➕", "6": "📋", "7": "📝", "8": "🧹",
    "9": "🔍", "10": "🛡️", "11": "🔗", "12": "⬆️",
    "13": "🎬", "14": "🧩", "15": "📄", "16": "👁️",
}

#: Fluent 色板。dark / light 两套，QSS 由 token 生成，切换主题只换样式表。
TOKENS = {
    "dark": {
        "bg": "#1F1F1F", "layer": "#272727", "card": "#2C2C2C",
        "card_hover": "#323232", "stroke": "#3A3A3A", "stroke_strong": "#4A4A4A",
        "fg": "#FFFFFF", "fg2": "#C5C5C5", "fg3": "#9A9A9A",
        "accent": "#60CDFF", "accent_hover": "#8AD8FF", "accent_fg": "#003A5C",
        "subtle": "rgba(255,255,255,0.06)", "subtle_hover": "rgba(255,255,255,0.10)",
        "nav_sel": "rgba(255,255,255,0.09)",
        "ok": "#6CCB5F", "warn": "#FCE100", "bad": "#FF99A4",
        "field": "#1F1F1F",
        # 图标块底色：实色而非半透明 —— 半透明底 + 淡色 emoji 在浅色主题下
        # 整块发白，认不出是什么图标。
        "icon_bg": "#0F4C75",
        "row_alt": "#23272D",
        # 表头底色：必须不透明。半透明色在 windows11 样式下会被
        # QHeaderView 当成「透明」并回落到系统色，浅色主题下就变黑底白字。
        "head_bg": "#383838",
    },
    "light": {
        "bg": "#F3F3F3", "layer": "#EAEAEA", "card": "#FFFFFF",
        "card_hover": "#FAFAFA", "stroke": "#E1E1E1", "stroke_strong": "#CCCCCC",
        "fg": "#1A1A1A", "fg2": "#5D5D5D", "fg3": "#8A8A8A",
        "accent": "#0067C0", "accent_hover": "#1975C5", "accent_fg": "#FFFFFF",
        "subtle": "rgba(0,0,0,0.04)", "subtle_hover": "rgba(0,0,0,0.07)",
        "nav_sel": "rgba(0,0,0,0.06)",
        "ok": "#0F7B0F", "warn": "#9D5D00", "bad": "#C42B1C",
        "field": "#FFFFFF", "icon_bg": "#B8D8F0",
        "row_alt": "#F5F6F8",
        "head_bg": "#EFEFEF",
    },
}


def build_qss(t, scale=1.0):
    """生成样式表。scale 是界面倍率（系统文本大小 × 用户档位）。

    尺寸全写成 px，缩放时统一乘一遍 —— 不只字号，padding / margin /
    border-radius / min-height 都得跟着走。只放字号的话，字一大就把
    容器挤满，行距、内边距、按钮高度都还是按小字量的，看着很憋。
    """
    qss = """
QMainWindow, QWidget#Root {{ background: {bg}; }}
QWidget {{ color: {fg}; }}

/* ---------- 左侧导航 ---------- */
QWidget#Sidebar {{
    background: {layer};
    border-right: 1px solid {stroke};
}}
QLabel#Brand {{ font-size: 14px; font-weight: 600; color: {fg}; }}
QLabel#BrandSub {{ font-size: 11px; color: {fg3}; }}
QLabel#NavGroup {{ font-size: 11px; color: {fg3}; padding: 10px 14px 4px 14px; }}

QPushButton#NavBtn {{
    text-align: left;
    padding: 0 12px;
    height: 38px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    background: transparent;
    color: {fg2};
    font-size: 13px;
}}
QPushButton#NavBtn:hover {{ background: {subtle}; color: {fg}; }}
QPushButton#NavBtn:checked {{
    background: {nav_sel};
    border-left: 3px solid {accent};
    color: {fg};
    font-weight: 600;
}}

/* ---------- 顶部工具栏 ---------- */
QLabel#PageTitle {{ font-size: 20px; font-weight: 600; color: {fg}; }}
QLabel#PageDesc {{ font-size: 12px; color: {fg2}; }}

QLineEdit#Search {{
    background: {field};
    border: 1px solid {stroke};
    border-radius: 4px;
    padding: 7px 10px;
    color: {fg};
    font-size: 13px;
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QLineEdit#Search:focus {{ border-color: {accent}; }}

/* ---------- 卡片 ---------- */
QFrame#Card {{
    background: {card};
    border: 1px solid {stroke};
    border-radius: 8px;
}}
QFrame#Card:hover {{ background: {card_hover}; border-color: {stroke_strong}; }}
QFrame#Card[running="true"] {{ border-color: {ok}; }}
QFrame#Card[failed="true"] {{ border-color: {bad}; }}
QFrame#Card[done="true"] {{ border-color: {warn}; }}

QLabel#CardIcon {{
    background: {icon_bg};
    border-radius: 8px;
    font-family: "Segoe UI Emoji", "Segoe UI Symbol", "Segoe UI";
    font-size: 19px;
}}
QLabel#CardTitle {{ font-size: 13px; font-weight: 600; color: {fg}; }}
QLabel#CardScript {{ font-size: 11px; color: {fg3};
    font-family: "Cascadia Mono", Consolas, monospace; }}
QLabel#CardDesc {{ font-size: 12px; color: {fg2}; }}
QLabel#CardStatus {{ font-size: 11px; color: {fg3}; }}
QLabel#CardStatus[running="true"] {{ color: {ok}; }}
QLabel#CardStatus[done="true"] {{ color: {warn}; }}
QLabel#CardStatus[failed="true"] {{ color: {bad}; }}
QLabel#Star {{ color: {warn}; font-size: 11px; }}

/* ---------- 控件 ---------- */
QPushButton#Primary {{
    background: {accent}; color: {accent_fg};
    border: none; border-radius: 4px;
    padding: 6px 16px; font-size: 12px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Primary:disabled {{ background: {subtle}; color: {fg3}; }}

QPushButton#Secondary {{
    background: {subtle}; color: {fg};
    border: 1px solid {stroke}; border-radius: 4px;
    padding: 6px 12px; font-size: 12px;
}}
QPushButton#Secondary:hover {{ background: {subtle_hover}; border-color: {stroke_strong}; }}

QPushButton#IconBtn {{
    background: {subtle}; color: {fg2};
    border: 1px solid {stroke}; border-radius: 15px;
    font-size: 15px; font-weight: 600;
}}
QPushButton#IconBtn:hover {{ background: {subtle_hover}; color: {fg}; border-color: {stroke_strong}; }}

QPushButton#Danger {{
    background: transparent; color: {bad};
    border: 1px solid {bad}; border-radius: 4px;
    padding: 6px 12px; font-size: 12px;
}}
QPushButton#Danger:hover {{ background: {subtle_hover}; }}

QPushButton#Ghost {{
    background: transparent; color: {fg2};
    border: none; border-radius: 4px;
    padding: 6px 10px; font-size: 12px;
}}
QPushButton#Ghost:hover {{ background: {subtle}; color: {fg}; }}

QLineEdit#Args {{
    background: {field}; border: 1px solid {stroke};
    border-radius: 4px; padding: 5px 9px;
    color: {fg}; font-size: 12px;
    font-family: "Cascadia Mono", Consolas, monospace;
}}
QLineEdit#Args:focus {{ border-color: {accent}; }}

/* ---------- 结果表格 ---------- */
QTableWidget#ResultTable {{
    background: {card};
    alternate-background-color: {row_alt};
    gridline-color: {stroke};
    color: {fg};
    font-size: 12px;
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QTableWidget#ResultTable::item {{ padding: 5px 8px; border: none; }}
QTableWidget#ResultTable::item:selected {{ background: {accent}; color: {accent_fg}; }}
QHeaderView {{
    background: {head_bg};
    border: none;
}}
QHeaderView::section {{
    background: {head_bg}; color: {fg2};
    padding: 6px 8px;
    border: none; border-right: 1px solid {stroke};
    font-size: 11px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {head_bg}; border: none; }}

/* ---------- 表单 ---------- */
QLabel#FieldLabel {{ font-size: 12px; color: {fg2}; }}
QPlainTextEdit#FormOutput {{
    background: {field}; color: {fg2};
    border: 1px solid {stroke}; border-radius: 8px;
    padding: 8px;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px;
    selection-background-color: {accent};
}}

/* ---------- 输出面板 ---------- */
QFrame#OutputBox {{
    background: {card};
    border: 1px solid {stroke};
    border-radius: 8px;
}}
QPlainTextEdit#Output {{
    background: transparent; color: {fg2};
    border: none; selection-background-color: {accent};
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px;
}}

/* ---------- 滚动区 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {stroke_strong}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {fg3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ---------- 底部状态条 ---------- */
QLabel#StatusText {{ font-size: 11px; color: {fg3}; }}
QFrame#Divider {{ background: {stroke}; max-height: 1px; border: none; }}

/* ---------- 设置页 / 帮助页 ---------- */
QLabel#SectionTitle {{
    font-size: 12px; font-weight: 600; color: {fg};
    padding: 4px 2px 0px 2px;
}}
QLabel#PathText {{
    font-size: 11px; color: {fg3};
    font-family: "Cascadia Mono", Consolas, monospace;
}}
QTextBrowser#HelpDoc {{
    /* 文档正文的颜色由 HTML 自带（会随主题重算），这里只管容器 */
    background: {card};
    border: 1px solid {stroke}; border-radius: 8px;
    padding: 10px 12px;
    color: {fg2};
    font-size: 13px;
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QComboBox {{
    background: {field}; color: {fg};
    border: 1px solid {stroke}; border-radius: 4px;
    padding: 5px 10px; font-size: 12px;
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {stroke_strong}; }}
QComboBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {card}; color: {fg};
    border: 1px solid {stroke};
    selection-background-color: {accent};
    selection-color: {accent_fg};
    font-size: 12px;
}}
QCheckBox {{ font-size: 12px; color: {fg}; spacing: 8px; }}
""".format(**t)
    # 兜底夹一遍：传 0（「跟随画面」的存储值）会让所有尺寸乘成 1px，字直接看不见
    scale = min(2.0, max(0.8, float(scale or 1.0)))
    if abs(scale - 1.0) > 0.001:
        qss = scale_px(qss, scale)
    return qss


def rel_time(ts):
    secs = max(0, int(QtCore.QDateTime.currentSecsSinceEpoch() - ts))
    if secs < 60:
        return "{} 秒前".format(secs)
    if secs < 3600:
        return "{} 分钟前".format(secs // 60)
    return "{} 小时前".format(secs // 3600)


def system_is_dark():
    """读 Windows 的应用主题偏好；读不到就按深色处理（面板的主要使用场景）。"""
    if os.name != "nt":
        return True
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


class ToolCard(QtWidgets.QFrame):
    """一张工具卡片：图标 + 标题 + 说明 + 状态 + 操作。"""

    panel_requested = QtCore.Signal(str)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("Card")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)
        self.setProperty("missing", "true" if not tool["exists"] else "false")

        row = QtWidgets.QHBoxLayout(self)
        self._row = row

        icon = QtWidgets.QLabel(ICONS.get(tool["id"], "•"))
        icon.setObjectName("CardIcon")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        self._icon = icon
        row.addWidget(icon, 0, QtCore.Qt.AlignTop)

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(3)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        title = QtWidgets.QLabel(tool["title"])
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if tool["submit"]:
            star = QtWidgets.QLabel("★")
            star.setObjectName("Star")
            star.setToolTip("提交项")
            head.addWidget(star, 0, QtCore.Qt.AlignTop)
        col.addLayout(head)

        desc = QtWidgets.QLabel(tool["desc"])
        desc.setObjectName("CardDesc")
        desc.setWordWrap(True)
        col.addWidget(desc)

        col.addSpacing(2)

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(6)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("CardStatus")
        foot.addWidget(self.status, 1)

        self.has_form = actions.has_form(tool["id"])
        self.panel_btn = QtWidgets.QPushButton("打开")
        self.panel_btn.setObjectName("Primary")
        self.panel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.panel_btn.setEnabled(tool["exists"])
        self.panel_btn.clicked.connect(
            lambda _c=False: self.panel_requested.emit(tool["id"]))
        foot.addWidget(self.panel_btn)
        col.addLayout(foot)

        row.addLayout(col, 1)

        if not tool["exists"]:
            self.status.setText("脚本缺失")

        self.resize_parts()

    def resize_parts(self):
        """按当前倍率重设写死的尺寸。

        QSS 管不到 setFixedSize / setContentsMargins；不改这里的话，
        字号放大后图标和边距还是原尺寸，卡片会显得挤。
        """
        self.setMinimumWidth(px(CARD_MIN_WIDTH))
        self.setMaximumWidth(px(CARD_MAX_WIDTH))
        self._row.setContentsMargins(px(14), px(13), px(14), px(12))
        self._row.setSpacing(px(12))
        self._icon.setFixedSize(px(40), px(40))
        # 显式指定 emoji 字体：QSS 里的 font-family 会被 QLabel 的字体覆盖，
        # 不显式设的话会落到默认的西文字体，彩色 emoji 就变 monochrome 了。
        emoji_font = QtGui.QFont("Segoe UI Emoji")
        emoji_font.setFamilies(["Segoe UI Emoji", "Segoe UI Symbol", "Segoe UI"])
        emoji_font.setPixelSize(px(17))
        self._icon.setFont(emoji_font)

    def set_status(self, text):
        """表单页执行时把状态同步到卡片。"""
        self.status.setText(text)
        running = "运行" in text or "执行" in text
        self.setProperty("running", "true" if running else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class CardGrid(QtWidgets.QWidget):
    """按可用宽度自动换列的卡片网格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(px(GAP))
        self.cards = []
        self._cols = 0

    def refresh_spacing(self):
        """倍率变了：间距与换列阈值都要跟着走，否则卡片间距还是老样子。"""
        self.grid.setSpacing(px(GAP))
        self._cols = 0
        self._relayout()

    def set_cards(self, cards):
        self.cards = list(cards)
        self._cols = 0
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = self.width()
        if width < 80 or not self.cards:
            return
        gap = px(GAP)
        min_width = px(CARD_MIN_WIDTH)
        cols = max(1, (width + gap) // (min_width + gap))
        if cols == self._cols:
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        # 不带 AlignTop：同一行的卡片由 grid 拉到等高，视觉上才齐
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // cols, i % cols)
        total = max(cols, self.grid.columnCount())
        for c in range(total):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)


class Sidebar(QtWidgets.QWidget):
    """左侧导航：品牌区 + 分组按钮 + 底部帮助/设置。"""

    group_selected = QtCore.Signal(str)
    special_selected = QtCore.Signal(str)

    def __init__(self, groups, icon=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(px(214))
        self._icon = icon

        lay = QtWidgets.QVBoxLayout(self)
        self._lay = lay
        lay.setContentsMargins(0, px(16), 0, px(12))
        lay.setSpacing(0)

        brand_row = QtWidgets.QHBoxLayout()
        self._brand_row = brand_row
        brand_row.setContentsMargins(px(16), 0, px(16), 0)
        brand_row.setSpacing(px(10))
        logo = QtWidgets.QLabel()
        self._logo = logo
        if icon is not None and not icon.isNull():
            logo.setPixmap(icon.pixmap(QtCore.QSize(px(30), px(30))))
        else:
            logo.setText("🧰")
            logo.setAlignment(QtCore.Qt.AlignCenter)
        logo.setFixedSize(px(34), px(34))
        brand_row.addWidget(logo, 0)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(0)
        name = QtWidgets.QLabel("LaTeX 工具箱")
        name.setObjectName("Brand")
        sub = QtWidgets.QLabel("笔记维护工具集")
        sub.setObjectName("BrandSub")
        texts.addWidget(name)
        texts.addWidget(sub)
        brand_row.addLayout(texts, 1)
        lay.addLayout(brand_row)
        lay.addSpacing(14)

        self.buttons = {}
        for i, group in enumerate(groups):
            btn = QtWidgets.QPushButton(group)
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, g=group: self.group_selected.emit(g))
            lay.addWidget(btn)
            self.buttons[group] = btn
            if i == 0:
                btn.setChecked(True)

        lay.addStretch(1)
        line = QtWidgets.QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        lay.addWidget(line)
        lay.addSpacing(6)

        # 「工具」与「其他」之间的分隔：让底部的帮助/设置不像是又一个分组
        cap = QtWidgets.QLabel("其他")
        cap.setObjectName("NavGroup")
        lay.addWidget(cap)

        # 帮助与设置：和分组按钮同款，但不走 group_selected。
        # 不用 emoji —— ⚙️/🔧 在 Segoe UI Emoji 下分别是紫灰色齿轮和浅色扳手，
        # 浅色主题里几乎看不见。纯文字更稳，换机器也不会变样。
        self.special_buttons = {}
        for key, text in (("帮助", "使用帮助"), ("设置", "设置")):
            btn = QtWidgets.QPushButton(text)
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda _c=False, k=key: self.special_selected.emit(k))
            lay.addWidget(btn)
            self.special_buttons[key] = btn

        # 主题切换只放在设置页 —— 侧栏底部只留「帮助 / 设置」两个入口。

    def resize_parts(self):
        """倍率变了：侧栏宽、品牌区留白、Logo 尺寸一起改。"""
        self.setFixedWidth(px(214))
        self._lay.setContentsMargins(0, px(16), 0, px(12))
        self._brand_row.setContentsMargins(px(16), 0, px(16), 0)
        self._brand_row.setSpacing(px(10))
        self._logo.setFixedSize(px(34), px(34))
        if self._icon is not None and not self._icon.isNull():
            self._logo.setPixmap(self._icon.pixmap(QtCore.QSize(px(30), px(30))))

    def select(self, group):
        """选中某个分组按钮。

        组按钮和特殊按钮（帮助/设置）分属两个 QButtonGroup，autoExclusive
        不会互相取消，所以这里要手动把另一边清掉 —— 否则会出现
        「核心工具」和「运行监测」同时显示选中态。
        """
        btn = self.buttons.get(group)
        if btn is not None:
            btn.setChecked(True)
        for other, other_btn in self.buttons.items():
            if other != group:
                other_btn.setChecked(False)
        for other in self.special_buttons.values():
            other.setChecked(False)

    def select_special(self, key):
        """选中帮助或设置按钮，其余全部取消。"""
        btn = self.special_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)
        for other in self.special_buttons.values():
            if other is not btn:
                other.setChecked(False)
        for other in self.buttons.values():
            other.setChecked(False)



class MainWindow(QtWidgets.QMainWindow):
    GROUP_DESC = {
        "核心工具": "日常最常用的四件事：Git 环境、仓库管理、符号库、写作工作台",
        "创建与维护": "建新笔记、导出大纲、清理编译产物",
        "信息安全与提交": "扫描本机信息、检查路径、体检仓库、提交",
        "素材与转写": "视频转文字，字幕优先，无字幕走本地 whisper",
        "PDF 处理": "横躺的课件 PDF 就地转正",
        "运行监测": "监测笔记目录，有改动自动提交推送并裁剪历史",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LaTeX 工具箱")
        self.tools = core.describe_tools()
        self.cards = {}
        self.groups = []
        for tool in self.tools:
            if tool["group"] not in self.groups:
                self.groups.append(tool["group"])
        # 配置：主题偏好与字号缩放。0 表示「跟随画面」——按屏幕物理密度自动定档，
        # 高 DPI 屏开箱就是合适大小，普通屏仍是原样。
        self._config = config.load()
        self._theme_pref = self._config.get("theme", "auto")
        self._font_scale = float(self._config.get("font_scale", 0.0) or 0.0)
        self._dark = system_is_dark()
        self._apply_scale_value()

        root = QtWidgets.QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        shell = QtWidgets.QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.icon = app_icon()
        if not self.icon.isNull():
            self.setWindowIcon(self.icon)
        self.sidebar = Sidebar(self.groups, self.icon)
        self.sidebar.group_selected.connect(self.show_group)
        self.sidebar.special_selected.connect(self.show_special)
        shell.addWidget(self.sidebar)

        right = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right)
        right_lay.setContentsMargins(24, 16, 24, 12)
        right_lay.setSpacing(10)
        right_lay.addLayout(self._build_toolbar())

        self.stack = QtWidgets.QStackedWidget()
        right_lay.addWidget(self.stack, 1)

        self.detail_host = QtWidgets.QWidget()
        self.detail_lay = QtWidgets.QVBoxLayout(self.detail_host)
        self.detail_lay.setContentsMargins(0, 2, 6, 2)
        self.detail_lay.setSpacing(8)
        self.stack.addWidget(self.detail_host)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(8)
        self.status_text = QtWidgets.QLabel(
            "工作区 {}".format(core.WORKSPACE))
        self.status_text.setObjectName("StatusText")
        bottom.addWidget(self.status_text, 1)
        self.count_text = QtWidgets.QLabel("{} 个工具".format(len(self.tools)))
        self.count_text.setObjectName("StatusText")
        bottom.addWidget(self.count_text)
        right_lay.addLayout(bottom)

        shell.addWidget(right, 1)

        self._build_pages()
        self.show_group(self.groups[0])
        self.apply_theme()
        self.apply_font_scale(self._font_scale)
        self._fit_window()

    # ---------- 构建 ----------

    def _apply_scale_value(self):
        """算出界面倍率。0 = 跟随画面，其余为用户手选档位。"""
        global _UI_SCALE
        base = self._font_scale if self._font_scale > 0 else dpi_scale()
        _UI_SCALE = min(2.0, max(0.8, text_scale() * base))

    def _fit_window(self):
        """按可用屏幕定初始窗口大小。

        写死 1200×780 在 150% 缩放的 1366×768 屏上（逻辑只有 911×512）
        会直接超出屏幕，标题栏跑到屏幕外就拖不动了。取可用区域的六成，
        再夹在设计范围内。
        """
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            self.resize(px(1200), px(780))
            return
        avail = screen.availableGeometry()
        width = min(px(1200), int(avail.width() * 0.82))
        height = min(px(780), int(avail.height() * 0.86))
        self.resize(max(px(880), width), max(px(560), height))
        # 居中，且保证不出屏
        self.move(avail.left() + (avail.width() - self.width()) // 2,
                  avail.top() + (avail.height() - self.height()) // 2)
        self.setMaximumSize(avail.width(), avail.height())

    def _build_toolbar(self):
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(12)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(1)
        self.page_title = QtWidgets.QLabel("")
        self.page_title.setObjectName("PageTitle")
        self.page_desc = QtWidgets.QLabel("")
        self.page_desc.setObjectName("PageDesc")
        self.page_desc.setWordWrap(True)
        left.addWidget(self.page_title)
        left.addWidget(self.page_desc)
        bar.addLayout(left, 1)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索工具 · 按 / 聚焦")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(px(260))
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(self.search, 0, QtCore.Qt.AlignVCenter)

        # 右上角常驻一个「?」：按当前页面给对应帮助（工具页 → 该工具，
        # 分组页 → 本板块全部工具）。工具页里另有就近的「查看帮助」。
        self.context_help = QtWidgets.QPushButton("?")
        self.context_help.setObjectName("IconBtn")
        self.context_help.setFixedSize(px(30), px(30))
        self.context_help.setCursor(QtCore.Qt.PointingHandCursor)
        self.context_help.setToolTip("查看当前页面相关帮助（F1）")
        self.context_help.clicked.connect(self.open_context_help)
        bar.addWidget(self.context_help, 0, QtCore.Qt.AlignVCenter)
        return bar

    def _build_pages(self):
        self.pages = {}
        self.group_cards = {}
        self.grids = {}
        for group in self.groups:
            page = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(page)
            lay.setContentsMargins(0, 4, 6, 4)
            lay.setSpacing(0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            inner = QtWidgets.QWidget()
            inner_lay = QtWidgets.QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 8)
            grid = CardGrid()
            self.grids[group] = grid
            inner_lay.addWidget(grid)
            inner_lay.addStretch(1)
            scroll.setWidget(inner)
            lay.addWidget(scroll)

            cards = []
            for tool in self.tools:
                if tool["group"] != group:
                    continue
                card = ToolCard(tool)
                card.panel_requested.connect(self.open_panel)
                self.cards[tool["id"]] = card
                cards.append(card)
            grid.set_cards(cards)
            self.group_cards[group] = cards
            self.pages[group] = page
            self.stack.addWidget(page)

        # 帮助页与设置页：不是分组，但同样占一个栈页
        self.help_page = pages.HelpPage(TOKENS["dark" if self._dark else "light"])
        self.stack.addWidget(self.help_page)
        self.settings_page = pages.SettingsPage(self)
        self.stack.addWidget(self.settings_page)

    # ---------- 主题 ----------

    def apply_theme(self, preference=None):
        """应用主题。preference 为 auto/dark/light；不给就用当前状态。"""
        if preference is None:
            preference = self._theme_pref
        if preference == "auto":
            dark = system_is_dark()
        elif preference == "light":
            dark = False
        else:
            dark = True
        self._dark = dark
        tokens = TOKENS["dark" if dark else "light"]
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(tokens, _UI_SCALE))
        # 帮助文档是磁盘 HTML，颜色按当前主题重算一遍
        if hasattr(self, "help_page"):
            self.help_page.set_dark(dark)
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(tokens["bg"]))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(tokens["fg"]))
        self.setPalette(palette)

    def apply_font_scale(self, scale):
        """改界面字号。scale=0 表示跟随画面（按屏幕密度自动），>0 为用户档位。

        倍率一路管到三处：QSS（字号与全部间距）、app 默认字体（菜单、
        消息框这些不吃 QSS 的部分）、以及写死尺寸的控件（侧栏宽、卡片图标、
        搜索框）。三处不一起动就会出现「字大了但框没大」的挤压。
        """
        scale = float(scale)
        if scale > 0:
            scale = min(1.6, max(0.8, scale))
        self._font_scale = 0.0 if scale <= 0 else scale
        self._apply_scale_value()

        app = QtWidgets.QApplication.instance()
        tokens = TOKENS["dark" if self._dark else "light"]
        if app is not None:
            app.setStyleSheet(build_qss(tokens, _UI_SCALE))
        font = QtGui.QFont("Segoe UI Variable Text", 9)
        font.setFamilies(["Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI"])
        font.setPointSizeF(max(7.0, 9.0 * _UI_SCALE))
        if app is not None:
            app.setFont(font)

        self._resize_fixed_parts()
        if hasattr(self, "help_page"):
            self.help_page.set_ui_scale(_UI_SCALE)

    def _resize_fixed_parts(self):
        """重设写死尺寸的控件。QSS 管不到 setFixedSize / setContentsMargins。"""
        self.sidebar.setFixedWidth(px(214))
        self.search.setFixedWidth(px(260))
        if hasattr(self, "context_help"):
            self.context_help.setFixedSize(px(30), px(30))
        self.sidebar.resize_parts()
        for card in self.cards.values():
            card.resize_parts()
        for grid in getattr(self, "grids", {}).values():
            grid.refresh_spacing()
        # 正开着工具页就按新倍率重开一遍，别把用户晾在空页上
        if hasattr(self, "detail_host"):
            tool = getattr(self, "_current_tool", None)
            on_detail = (tool is not None
                         and self.stack.currentWidget() is self.detail_host)
            self._clear_detail()
            if on_detail:
                self.open_panel(tool["id"])

    def toggle_theme(self):
        """主题按钮：在 深色/浅色 之间切，并把选择记住。"""
        new_pref = "light" if self._dark else "dark"
        self._theme_pref = new_pref
        config.update(theme=new_pref)
        self.apply_theme(preference=new_pref)

    # ---------- 交互 ----------

    def _clear_detail(self):
        while self.detail_lay.count():
            item = self.detail_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    child = sub.takeAt(0).widget()
                    if child is not None:
                        child.setParent(None)
                        child.deleteLater()
                sub.deleteLater()

    def open_panel(self, key):
        tool = next((t for t in self.tools if t["id"] == key), None)
        if tool is None:
            return
        panel = actions.build(key, tool)
        if panel is None:
            self.toast("该工具还没有可视化面板，先用控制台")
            return
        self._clear_detail()

        back = QtWidgets.QPushButton("← 返回工具列表")
        back.setObjectName("Secondary")
        back.setCursor(QtCore.Qt.PointingHandCursor)
        back.setMinimumWidth(px(132))
        back.setMinimumHeight(px(32))
        back.clicked.connect(self.close_panel)
        help_btn = QtWidgets.QPushButton("? 查看帮助")
        help_btn.setObjectName("Secondary")
        help_btn.setCursor(QtCore.Qt.PointingHandCursor)
        help_btn.setMinimumHeight(px(32))
        if not tool.get("help"):
            help_btn.setEnabled(False)
        help_btn.clicked.connect(lambda _=False, t=tool: self.show_tool_help(t))

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(help_btn)
        self.detail_lay.addLayout(row)
        self.detail_lay.addWidget(panel, 1)
        panel.status_changed.connect(
            lambda text, cid=key: self.cards[cid].set_status(text))

        self._current_tool = tool
        self.stack.setCurrentWidget(self.detail_host)
        self.page_title.setText(tool["title"])
        # 工具页不放副标题：横线上面那行小字多余，留白反而更清爽
        self.page_desc.setText("")
        # 侧栏高亮跟着工具所属的分组走，别停在「帮助」或「设置」上
        group = tool.get("group")
        if group:
            self.sidebar.select(group)

    def close_panel(self):
        self._current_tool = None
        self._clear_detail()
        group = getattr(self, "_current_group", self.groups[0])
        self.stack.setCurrentWidget(self.pages[group])
        self.page_title.setText(group)
        self.page_desc.setText(self.GROUP_DESC.get(group, ""))
        # 回到分组页，侧栏高亮也跟着回去
        self.sidebar.select(group)

    def showEvent(self, event):
        super().showEvent(event)
        # 窗口创建后才能取到 hwnd；再延一拍执行，确保盖在 Qt 自己设图标之后
        path = icon_path()
        if path is not None:
            QtCore.QTimer.singleShot(0, lambda: _apply_win32_icons(self, path))
        # 多显示器 DPI 不同：拖到另一块屏要按新屏重算自动档
        handle = self.windowHandle()
        if handle is not None and not getattr(self, "_screen_hooked", False):
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_hooked = True

    def _on_screen_changed(self, _screen):
        if self._font_scale <= 0:
            self.apply_font_scale(0.0)
            self._fit_window()

    def show_group(self, group):
        if self.search.text().strip():
            self.search.clear()
        page = self.pages.get(group)
        if page is None:
            return
        self._current_group = group
        self.stack.setCurrentWidget(page)
        self.page_title.setText(group)
        self.page_desc.setText(self.GROUP_DESC.get(group, ""))
        self.sidebar.select(group)

    def show_tool_help(self, tool):
        """跳到帮助页并直接打开这个工具那篇。"""
        slug = tool.get("help")
        if not slug:
            return
        self.show_special("帮助", title="帮助：" + tool["title"])
        self.help_page.show_doc(slug + ".html")

    def show_group_help(self, group):
        """板块级帮助：这个分组下所有工具的清单与入口。"""
        slug = core.GROUP_SLUGS.get(group)
        if not slug:
            return
        self.show_special("帮助", title="帮助：" + group)
        self.help_page.show_doc(slug + ".html")

    def open_context_help(self):
        """右上角「?」：按当前页面决定给哪份帮助。"""
        current = self.stack.currentWidget()
        tool = getattr(self, "_current_tool", None)
        if current is self.detail_host and tool is not None:
            self.show_tool_help(tool)
        elif current in self.pages.values():
            self.show_group_help(getattr(self, "_current_group", self.groups[0]))
        else:
            self.show_special("帮助")

    def show_special(self, key, title=None):
        """切到帮助页或设置页。"""
        if self.search.text().strip():
            self.search.clear()
        if key == "帮助":
            self.stack.setCurrentWidget(self.help_page)
            self.page_title.setText(title or "使用帮助")
            self.page_desc.setText("")
            self.sidebar.select_special("帮助")
        else:
            self.stack.setCurrentWidget(self.settings_page)
            self.page_title.setText("设置")
            self.page_desc.setText("")
            self.sidebar.select_special("设置")

    def apply_filter(self, text):
        if text.strip() and self.stack.currentWidget() is self.detail_host:
            self.close_panel()
        q = text.strip().lower()
        if not q:
            # 回到当前组
            for group, cards in self.group_cards.items():
                self.pages[group].findChild(CardGrid).set_cards(cards)
            current = self.stack.currentWidget()
            for group, page in self.pages.items():
                if page is current:
                    self.page_title.setText(group)
                    self.page_desc.setText(self.GROUP_DESC.get(group, ""))
                    break
            self.sidebar.show()
            return

        matched = []
        for tool in self.tools:
            hay = " ".join((tool["title"], tool["desc"], tool["script"],
                            tool["group"])).lower()
            if q in hay:
                matched.append(self.cards[tool["id"]])

        # 用当前页承载搜索结果，其余页清空，避免控件在多个布局间反复搬
        current = self.stack.currentWidget()
        grid = current.findChild(CardGrid)
        for group, page in self.pages.items():
            if page is not current:
                page.findChild(CardGrid).set_cards([])
        grid.set_cards(matched)
        self.page_title.setText("搜索结果")
        self.page_desc.setText("“{}” 命中 {} 个工具".format(text.strip(), len(matched)))
        if not matched:
            self.page_desc.setText("“{}” 没有匹配的工具".format(text.strip()))

    def toast(self, text, bad=False):
        self.status_text.setText(text)
        tokens = TOKENS["dark" if self._dark else "light"]
        color = tokens["bad"] if bad else tokens["fg2"]
        self.status_text.setStyleSheet("color: {};".format(color))

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Slash and not self.search.hasFocus():
            self.search.setFocus()
            self.search.selectAll()
            return
        if event.key() == QtCore.Qt.Key_Escape:
            if self.search.text():
                self.search.clear()
            elif self.stack.currentWidget() is self.detail_host:
                self.close_panel()
            return
        # Ctrl+1~6 跳组；Ctrl+, 打开设置
        if event.modifiers() & QtCore.Qt.ControlModifier:
            key = event.key()
            if key == QtCore.Qt.Key_Comma:
                self.show_special("设置")
                return
            if QtCore.Qt.Key_1 <= key <= QtCore.Qt.Key_9:
                index = key - QtCore.Qt.Key_1
                if index < len(self.groups):
                    self.show_group(self.groups[index])
                    return
        super().keyPressEvent(event)


def icon_path():
    """图标文件路径。打包后在解包目录里，源码运行时在 src/ 下。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent / "resources"
    for name in ("tools.ico", "tools.png"):
        path = base / name
        if path.is_file():
            return path
    return None


def app_icon():
    """应用图标。

    打包时 `--icon` 只改 exe 自身的 PE 资源（资源管理器里看到的那个），
    **标题栏与任务栏的图标来自 QWidget.windowIcon**，不设就是 Qt 的默认图标。
    """
    path = icon_path()
    return QtGui.QIcon(str(path)) if path else QtGui.QIcon()


def _apply_win32_icons(win, path):
    """把窗口标题栏与任务栏的图标换成自己的。

    两个坑：
    1. **标题栏用的是窗口类的图标**（GetClassLongPtr(GCLP_HICON)），Qt 建类时
       放的是它自己的默认图标，只调 setWindowIcon 换不掉 —— 得改类图标。
    2. Qt 的 setWindowIcon 只设了 ICON_BIG，标题栏在 Vista+ 优先取 ICON_BIG2，
       缺了就退回系统默认图标。三个尺寸都要补。
    判据用 GetClassLongPtr 读：Qt 窗口上 WM_GETICON 读不回来，不代表没设上。
    """
    if sys.platform != "win32" or path is None:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(win.winId())
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x007F
        GWL_HICON = -14
        ICON_SMALL, ICON_BIG, ICON_BIG2 = 0x00, 0x01, 0x31

        def load(size):
            return user32.LoadImageW(None, str(path), IMAGE_ICON, size, size,
                                     LR_LOADFROMFILE)

        big = load(32)
        small = load(16)
        if big:
            user32.SetClassLongPtrW(hwnd, GWL_HICON, big)      # 标题栏
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG2, big)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
    except Exception:
        pass


def _claim_taskbar_identity():
    """设 AppUserModelID。

    **故意不启用**：设了之后 Windows 11 任务栏改为取窗口级图标
    （WM_GETICON），而 Qt 会吞掉外部发的 WM_SETICON，取不到就显示
    Windows 的默认图标（一张白纸）。不设的话，任务栏直接用 exe 资源里
    的图标 —— 那份是对的。标题栏另走「改窗口类图标」的路子。
    """
    return


def _excepthook(exc_type, exc, tb):
    """未捕获的 Python 异常兜底。

    GUI 程序没有 stderr，异常默认被静默吞掉 —— 表现是「点了没反应、应用挂住」，
    很难查。这里落盘 + 弹窗，让问题看得见。
    """
    import traceback
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log = error_log_path()
    try:
        with open(log, "a", encoding="utf-8", errors="replace", newline="") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        QtWidgets.QMessageBox.critical(
            None, "面板出错了", text[-1200:] + "\n\n已写入 " + str(log))
    except Exception:
        pass


def main():
    _claim_taskbar_identity()
    sys.excepthook = _excepthook
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("LaTeX 工具箱")
    app.setStyle("Fusion")
    font = QtGui.QFont("Segoe UI Variable Text", 9)
    font.setFamilies(["Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI"])
    app.setFont(font)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 —— 兜底只为留下痕迹
        import traceback
        text = traceback.format_exc()
        log = error_log_path()
        try:
            with open(log, "a", encoding="utf-8", errors="replace", newline="") as fh:
                fh.write(text + "\n")
        except OSError:
            pass
        try:
            QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
            QtWidgets.QMessageBox.critical(
                None, "面板启动失败", text[-1500:] + "\n\n已写入 " + str(log))
        except Exception:
            pass
        sys.exit(1)
