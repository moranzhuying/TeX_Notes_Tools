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
    bases.append(Path(__file__).resolve().parent.parent
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
    """windowed exe 没有标准流，需要自己开一个控制台并接回 CONOUT$/CONIN$。

    为什么不是靠 CREATE_NEW_CONSOLE：那个标志只对**控制台子系统**程序有效，
    GUI 子系统（PyInstaller --windowed）会直接忽略它，进程仍然没有控制台，
    CONOUT$ 打开报「句柄无效」，input() 立刻 EOF、窗口一闪而过。
    所以这里自己 AllocConsole，再绑标准流。
    """
    if sys.stdout is not None and sys.stdin is not None:
        _dbg("bind: 标准流已就绪（重定向场景），跳过")
        return

    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            if not kernel32.GetConsoleWindow():
                if not kernel32.AllocConsole():
                    _dbg("AllocConsole 返回失败")
        except Exception as exc:  # noqa: BLE001 —— 开控制台失败不该拖垮工具
            _dbg("AllocConsole 异常: {}".format(exc))

    try:
        if sys.stdout is None:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace",
                              buffering=1)
        if sys.stderr is None:
            sys.stderr = sys.stdout
        if sys.stdin is None:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _dbg("绑定标准流失败: {}".format(exc))
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = sys.stdout
    _dbg("bind 之后: stdout={!r} stdin={!r}".format(sys.stdout, sys.stdin))


def exec_tool(argv):
    """以自身当解释器执行一个 .py —— 打包成 exe 后，工具子进程走这条路。

    工具脚本必须从磁盘上的真实 Tools 目录跑（它们要操作真实工作区），
    不能塞进 exe 的解包临时目录，所以这里是「解释器」而不是「导入器」。
    """
    import runpy
    import traceback

    _bind_console()
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
        try:
            input("\n按回车关闭…")
        except (EOFError, OSError):
            pass
        return 1
    return 0


def selftest():
    """打包后自检：确认工具根定位正确、且 exe 能用 --exec 拉起子工具。"""
    import time as _time

    _bind_console()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import panel_core

    print("exe            :", sys.executable)
    print("frozen         :", getattr(sys, "frozen", False))
    print("工具根         :", panel_core.TOOLS_ROOT)
    print("工作区         :", panel_core.WORKSPACE)
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

CARD_MIN_WIDTH = 360
CARD_MAX_WIDTH = 660
GAP = 12

#: 每个工具的图标（用彩色 emoji，不依赖字形码点，换机器也不会变方块）
ICONS = {
    "1": "⚙️", "2": "📚", "3": "🔤", "4": "🖥️",
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
        "field": "#1F1F1F", "icon_bg": "rgba(96,205,255,0.14)",
    },
    "light": {
        "bg": "#F3F3F3", "layer": "#EAEAEA", "card": "#FFFFFF",
        "card_hover": "#FAFAFA", "stroke": "#E1E1E1", "stroke_strong": "#CCCCCC",
        "fg": "#1A1A1A", "fg2": "#5D5D5D", "fg3": "#8A8A8A",
        "accent": "#0067C0", "accent_hover": "#1975C5", "accent_fg": "#FFFFFF",
        "subtle": "rgba(0,0,0,0.04)", "subtle_hover": "rgba(0,0,0,0.07)",
        "nav_sel": "rgba(0,0,0,0.06)",
        "ok": "#0F7B0F", "warn": "#9D5D00", "bad": "#C42B1C",
        "field": "#FFFFFF", "icon_bg": "rgba(0,103,192,0.10)",
    },
}


def build_qss(t):
    return """
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
""".format(**t)


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

    run_requested = QtCore.Signal(str, str)
    stop_requested = QtCore.Signal(str)
    output_requested = QtCore.Signal(str)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("Card")
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setMaximumWidth(CARD_MAX_WIDTH)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)
        self.setProperty("missing", "true" if not tool["exists"] else "false")

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(14, 13, 14, 12)
        row.setSpacing(12)

        icon = QtWidgets.QLabel(ICONS.get(tool["id"], "•"))
        icon.setObjectName("CardIcon")
        icon.setFixedSize(40, 40)
        icon.setAlignment(QtCore.Qt.AlignCenter)
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

        self.args = None
        if tool["oneoff"]:
            self.args = QtWidgets.QLineEdit(tool["defaultArgs"])
            self.args.setObjectName("Args")
            self.args.setPlaceholderText("追加参数（可空）")
            col.addWidget(self.args)

        col.addSpacing(2)

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(6)
        self.status = QtWidgets.QLabel("未启动")
        self.status.setObjectName("CardStatus")
        foot.addWidget(self.status, 1)

        self.out_btn = QtWidgets.QPushButton("输出")
        self.out_btn.setObjectName("Ghost")
        self.out_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.out_btn.clicked.connect(lambda: self.output_requested.emit(tool["id"]))
        self.out_btn.hide()
        foot.addWidget(self.out_btn)

        self.stop_btn = QtWidgets.QPushButton("停止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(tool["id"]))
        self.stop_btn.hide()
        foot.addWidget(self.stop_btn)

        self.run_btn = QtWidgets.QPushButton("启动")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.run_btn.setEnabled(tool["exists"])
        self.run_btn.clicked.connect(self._on_run)
        foot.addWidget(self.run_btn)
        col.addLayout(foot)

        row.addLayout(col, 1)

        if not tool["exists"]:
            self.status.setText("脚本缺失")

    def _on_run(self):
        extra = self.args.text() if self.args is not None else ""
        self.run_requested.emit(self.tool["id"], extra)

    def apply(self, run):
        """按运行快照刷新外观。"""
        for prop in ("running", "done", "failed"):
            self.setProperty(prop, "false")
            self.status.setProperty(prop, "false")

        if run and run["alive"]:
            self.setProperty("running", "true")
            self.status.setProperty("running", "true")
            where = "控制台运行中" if run["mode"] == "console" else "运行中"
            self.status.setText("● {} · {}".format(where, rel_time(run["started"])))
            self.run_btn.setText("运行中")
            self.run_btn.setEnabled(False)
            self.stop_btn.show()
            self.out_btn.setVisible(bool(run["hasOutput"]))
        elif run:
            rc = run["returncode"]
            ok = (rc == 0)
            self.setProperty("done" if ok else "failed", "true")
            self.status.setProperty("done" if ok else "failed", "true")
            self.status.setText("● 已结束 · 退出码 {}".format("?" if rc is None else rc))
            self.run_btn.setText("重新运行")
            self.run_btn.setEnabled(self.tool["exists"])
            self.stop_btn.hide()
            self.out_btn.setVisible(bool(run["hasOutput"]))
        else:
            self.status.setText("● 未启动" if self.tool["exists"] else "脚本缺失")
            self.run_btn.setText("启动")
            self.run_btn.setEnabled(self.tool["exists"])
            self.stop_btn.hide()
            self.out_btn.hide()

        for w in (self, self.status):
            w.style().unpolish(w)
            w.style().polish(w)


class CardGrid(QtWidgets.QWidget):
    """按可用宽度自动换列的卡片网格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GAP)
        self.cards = []
        self._cols = 0

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
        cols = max(1, (width + GAP) // (CARD_MIN_WIDTH + GAP))
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
    """左侧导航：品牌区 + 分组按钮 + 底部主题切换。"""

    group_selected = QtCore.Signal(str)
    theme_toggled = QtCore.Signal()

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(214)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 16, 0, 12)
        lay.setSpacing(0)

        brand_row = QtWidgets.QHBoxLayout()
        brand_row.setContentsMargins(16, 0, 16, 0)
        brand_row.setSpacing(10)
        logo = QtWidgets.QLabel("🧰")
        logo.setObjectName("CardIcon")
        logo.setFixedSize(34, 34)
        logo.setAlignment(QtCore.Qt.AlignCenter)
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

        self.theme_btn = QtWidgets.QPushButton("🌙  深色主题")
        self.theme_btn.setObjectName("NavBtn")
        self.theme_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self.theme_toggled.emit)
        lay.addWidget(self.theme_btn)

    def select(self, group):
        btn = self.buttons.get(group)
        if btn is not None:
            btn.setChecked(True)

    def set_theme_label(self, dark):
        self.theme_btn.setText("🌙  深色主题" if dark else "☀️  浅色主题")


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
        self.resize(1200, 780)
        self.tools = core.describe_tools()
        self.cards = {}
        self.groups = []
        for tool in self.tools:
            if tool["group"] not in self.groups:
                self.groups.append(tool["group"])
        self.output_key = None
        self._out_lines = -1
        self._dark = system_is_dark()

        root = QtWidgets.QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        shell = QtWidgets.QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.sidebar = Sidebar(self.groups)
        self.sidebar.group_selected.connect(self.show_group)
        self.sidebar.theme_toggled.connect(self.toggle_theme)
        shell.addWidget(self.sidebar)

        right = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right)
        right_lay.setContentsMargins(24, 16, 24, 12)
        right_lay.setSpacing(10)
        right_lay.addLayout(self._build_toolbar())

        self.stack = QtWidgets.QStackedWidget()
        right_lay.addWidget(self.stack, 1)

        self.output_box = self._build_output()
        self.output_box.hide()
        right_lay.addWidget(self.output_box, 0)

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

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_states)
        self.timer.start(1500)
        self.refresh_states()

    # ---------- 构建 ----------

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
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(self.search, 0, QtCore.Qt.AlignVCenter)
        return bar

    def _build_pages(self):
        self.pages = {}
        self.group_cards = {}
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
            inner_lay.addWidget(grid)
            inner_lay.addStretch(1)
            scroll.setWidget(inner)
            lay.addWidget(scroll)

            cards = []
            for tool in self.tools:
                if tool["group"] != group:
                    continue
                card = ToolCard(tool)
                card.run_requested.connect(self.on_run)
                card.stop_requested.connect(self.on_stop)
                card.output_requested.connect(self.on_output)
                self.cards[tool["id"]] = card
                cards.append(card)
            grid.set_cards(cards)
            self.group_cards[group] = cards
            self.pages[group] = page
            self.stack.addWidget(page)

    def _build_output(self):
        box = QtWidgets.QFrame()
        box.setObjectName("OutputBox")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.out_title = QtWidgets.QLabel("输出")
        self.out_title.setObjectName("CardTitle")
        bar.addWidget(self.out_title)
        self.out_meta = QtWidgets.QLabel("")
        self.out_meta.setObjectName("CardScript")
        bar.addWidget(self.out_meta)
        bar.addStretch(1)
        refresh = QtWidgets.QPushButton("刷新")
        refresh.setObjectName("Secondary")
        refresh.setCursor(QtCore.Qt.PointingHandCursor)
        refresh.clicked.connect(self.reload_output)
        bar.addWidget(refresh)
        close = QtWidgets.QPushButton("关闭")
        close.setObjectName("Ghost")
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.clicked.connect(lambda: box.hide())
        bar.addWidget(close)
        lay.addLayout(bar)

        self.out_view = QtWidgets.QPlainTextEdit()
        self.out_view.setObjectName("Output")
        self.out_view.setReadOnly(True)
        self.out_view.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.out_view.setMinimumHeight(170)
        self.out_view.setMaximumHeight(300)
        lay.addWidget(self.out_view)
        return box

    # ---------- 主题 ----------

    def apply_theme(self):
        tokens = TOKENS["dark" if self._dark else "light"]
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(tokens))
        self.sidebar.set_theme_label(self._dark)
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(tokens["bg"]))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(tokens["fg"]))
        self.setPalette(palette)

    def toggle_theme(self):
        self._dark = not self._dark
        self.apply_theme()

    # ---------- 交互 ----------

    def show_group(self, group):
        if self.search.text().strip():
            self.search.clear()
        page = self.pages.get(group)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.page_title.setText(group)
        self.page_desc.setText(self.GROUP_DESC.get(group, ""))
        self.sidebar.select(group)

    def on_run(self, key, extra):
        try:
            core.launch(key, extra)
        except core.PanelError as exc:
            self.toast(str(exc), bad=True)
            return
        tool = next((t for t in self.tools if t["id"] == key), None)
        if tool and tool["oneoff"]:
            self.toast("已开始运行：" + tool["title"])
        elif tool:
            self.toast("已打开控制台窗口：" + tool["title"])
        self.refresh_states()

    def on_stop(self, key):
        try:
            msg = core.stop(key)
        except core.PanelError as exc:
            self.toast(str(exc), bad=True)
            return
        self.toast(msg)
        self.refresh_states()

    def on_output(self, key):
        tool = next((t for t in self.tools if t["id"] == key), None)
        self.output_key = key
        self._out_lines = -1
        self.out_title.setText(tool["title"] if tool else "输出")
        self.output_box.show()
        self.reload_output()

    def reload_output(self):
        if not self.output_key:
            return
        lines = core.output_of(self.output_key)
        self._out_lines = len(lines)
        self.out_view.setPlainText("\n".join(lines) if lines else "（还没有输出）")
        self.out_meta.setText("{} 行".format(len(lines)))
        bar = self.out_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh_states(self):
        for key, card in self.cards.items():
            card.apply(core.run_state(key))
        if self.output_key and self.output_box.isVisible():
            run = core.run_state(self.output_key)
            # 行数变化就刷新：进程跑完时最后一批输出也要落进面板
            if run and run["lines"] != self._out_lines:
                self.reload_output()

    def apply_filter(self, text):
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
            if self.output_box.isVisible():
                self.output_box.hide()
            elif self.search.text():
                self.search.clear()
            return
        super().keyPressEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("LaTeX 工具箱")
    app.setStyle("Fusion")
    font = QtGui.QFont("Segoe UI Variable Text", 9)
    font.setFamilies(["Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI"])
    app.setFont(font)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 兜底只为留下痕迹
        import traceback
        text = traceback.format_exc()
        log = Path(__file__).with_name("_panel_error.log")
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
