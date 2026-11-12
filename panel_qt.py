#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_qt.py — 工具集图形面板（Qt 桌面窗口）

菜单来自 `panel_core`（它再 import `launcher.MENU`），所以命令行面板、Qt 面板
与网页备用版共用同一份工具清单。

- **交互面板类**（多数工具）→ 弹出独立控制台窗口，`input()` 行为与命令行一致
- **一次性命令类**（check_sensitive / sync_paths）→ 捕获输出，结果显示在下方输出区

    python panel_qt.py

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

CARD_MIN_WIDTH = 340
GAP = 12

QSS = """
QMainWindow, QWidget#Root { background: #0d1117; }

QLabel { color: #e6edf3; background: transparent; }
QLabel#AppTitle { font-size: 15px; font-weight: 600; }
QLabel#WorkPath { color: #6e7681; font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px; }
QLabel#GroupTitle {
    color: #8b949e; font-size: 11px; font-weight: 600;
    letter-spacing: 1.4px; padding: 2px 0 2px 2px;
}
QLabel#Badge {
    color: #8b949e; border: 1px solid #30363d; border-radius: 4px;
    padding: 2px 6px; font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px;
}
QLabel#CardTitle { font-size: 13px; font-weight: 600; }
QLabel#CardScript { color: #6e7681; font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px; }
QLabel#CardDesc { color: #8b949e; font-size: 12px; }
QLabel#CardStatus { color: #6e7681; font-size: 11px; }
QLabel#CardStatus[running="true"] { color: #3fb950; }
QLabel#CardStatus[done="true"] { color: #d29922; }
QLabel#CardStatus[failed="true"] { color: #f85149; }
QLabel#Star { color: #d29922; font-size: 11px; }

QFrame#Card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
}
QFrame#Card[running="true"] { border-color: rgba(63, 185, 80, 120); }
QFrame#Card[done="true"] { border-color: rgba(210, 153, 34, 90); }
QFrame#Card[failed="true"] { border-color: rgba(248, 81, 73, 90); }
QFrame#Card[missing="true"] { border-color: #21262d; }

QLineEdit {
    background: #0d1117; color: #e6edf3;
    border: 1px solid #30363d; border-radius: 5px;
    padding: 5px 8px; selection-background-color: #1f6feb;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px;
}
QLineEdit:focus { border-color: #58a6ff; }

QLineEdit#Search {
    padding: 6px 10px; border-radius: 6px;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 12px;
}

QPushButton {
    background: transparent; color: #8b949e;
    border: 1px solid #30363d; border-radius: 6px;
    padding: 5px 12px; font-size: 12px;
}
QPushButton:hover { color: #e6edf3; border-color: #6e7681; }
QPushButton:disabled { color: #484f58; border-color: #21262d; }

QPushButton#Primary {
    color: #0d1117; background: #8b949e; border: none; font-weight: 600;
}
QPushButton#Primary:hover { background: #e6edf3; }
QPushButton#Primary:disabled { background: #21262d; color: #484f58; }

QPushButton#Danger { color: #f85149; border-color: rgba(248, 81, 73, 90); }
QPushButton#Danger:hover { background: rgba(248, 81, 73, 26); border-color: #f85149; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #30363d; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #484f58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QFrame#OutputBox {
    background: #0b0f14; border: 1px solid #21262d; border-radius: 8px;
}
QPlainTextEdit#Output {
    background: transparent; color: #c9d1d9;
    border: none; selection-background-color: #1f6feb;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px;
}
QFrame#Separator { background: #21262d; max-height: 1px; border: none; }
"""


def rel_time(ts):
    secs = max(0, int(QtCore.QDateTime.currentSecsSinceEpoch() - ts))
    if secs < 60:
        return "{} 秒前".format(secs)
    if secs < 3600:
        return "{} 分钟前".format(secs // 60)
    return "{} 小时前".format(secs // 3600)


class ToolCard(QtWidgets.QFrame):
    """一个工具卡片。"""

    run_requested = QtCore.Signal(str, str)
    stop_requested = QtCore.Signal(str)
    output_requested = QtCore.Signal(str)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("Card")
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setMaximumWidth(680)   # 结果很少时不要把卡片拉成横幅
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)
        self.setProperty("missing", "true" if not tool["exists"] else "false")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 11)
        outer.setSpacing(7)

        # 第一行：编号 + 标题 + 星标
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        badge = QtWidgets.QLabel(tool["id"])
        badge.setObjectName("Badge")
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setFixedWidth(24)
        head.addWidget(badge, 0, QtCore.Qt.AlignTop)

        title = QtWidgets.QLabel(tool["title"])
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if tool["submit"]:
            star = QtWidgets.QLabel("★")
            star.setObjectName("Star")
            star.setToolTip("提交项")
            head.addWidget(star, 0, QtCore.Qt.AlignTop)
        outer.addLayout(head)

        script = QtWidgets.QLabel(tool["script"])
        script.setObjectName("CardScript")
        outer.addWidget(script)

        desc = QtWidgets.QLabel(tool["desc"])
        desc.setObjectName("CardDesc")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        self.args = None
        if tool["oneoff"]:
            self.args = QtWidgets.QLineEdit(tool["defaultArgs"])
            self.args.setPlaceholderText("追加参数（可空）")
            outer.addWidget(self.args)

        outer.addStretch(1)

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(6)
        self.status = QtWidgets.QLabel("未启动")
        self.status.setObjectName("CardStatus")
        foot.addWidget(self.status, 1)

        self.out_btn = QtWidgets.QPushButton("输出")
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
        outer.addLayout(foot)

        if not tool["exists"]:
            self.status.setText("脚本缺失")

    def _on_run(self):
        extra = self.args.text() if self.args is not None else ""
        self.run_requested.emit(self.tool["id"], extra)

    def apply(self, run):
        """按运行快照刷新外观。"""
        for prop in ("running", "done", "failed"):
            self.setProperty(prop, "false")
        self.status.setProperty("running", "false")
        self.status.setProperty("done", "false")
        self.status.setProperty("failed", "false")

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

        self._repolish()

    def _repolish(self):
        for w in (self, self.status):
            w.style().unpolish(w)
            w.style().polish(w)


class CardGrid(QtWidgets.QWidget):
    """按可用宽度自动换列的卡片网格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        # 列数只按可用宽度算，不压到卡片数：否则只剩一两个结果时会被拉满整行
        cols = max(1, (width + GAP) // (CARD_MIN_WIDTH + GAP))
        if cols == self._cols:
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // cols, i % cols, QtCore.Qt.AlignTop)
        total = max(cols, self.grid.columnCount())
        for c in range(total):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LaTeX 笔记工具集")
        self.resize(1280, 880)
        self.tools = core.describe_tools()
        self.cards = {}
        self.output_key = None
        self._out_lines = -1

        root = QtWidgets.QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        outer.addLayout(self._build_header())
        outer.addWidget(self._hrule())

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 4, 6, 8)
        self.body_layout.setSpacing(14)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        self.output_box = self._build_output()
        self.output_box.hide()
        outer.addWidget(self.output_box, 0)

        self._build_sections()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_states)
        self.timer.start(1500)
        self.refresh_states()

    # ---------- 构建 ----------

    def _build_header(self):
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(16)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(2)
        title = QtWidgets.QLabel("LaTeX 笔记工具集")
        title.setObjectName("AppTitle")
        left.addWidget(title)
        path = QtWidgets.QLabel(str(core.WORKSPACE))
        path.setObjectName("WorkPath")
        path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        left.addWidget(path)
        head.addLayout(left, 1)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索工具 · 按 / 聚焦")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self.apply_filter)
        head.addWidget(self.search, 0, QtCore.Qt.AlignVCenter)
        return head

    def _hrule(self):
        line = QtWidgets.QFrame()
        line.setObjectName("Separator")
        line.setFixedHeight(1)
        return line

    def _build_sections(self):
        groups = []
        for tool in self.tools:
            if not groups or groups[-1][0] != tool["group"]:
                groups.append((tool["group"], []))
            groups[-1][1].append(tool)

        for name, tools in groups:
            section = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(section)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            label = QtWidgets.QLabel(name.upper())
            label.setObjectName("GroupTitle")
            lay.addWidget(label)

            grid = CardGrid()
            cards = []
            for tool in tools:
                card = ToolCard(tool)
                card.run_requested.connect(self.on_run)
                card.stop_requested.connect(self.on_stop)
                card.output_requested.connect(self.on_output)
                self.cards[tool["id"]] = card
                cards.append(card)
            grid.set_cards(cards)
            lay.addWidget(grid)
            section.grid = grid
            section.cards = cards
            self.body_layout.addWidget(section)

        self.body_layout.addStretch(1)

    def _build_output(self):
        box = QtWidgets.QFrame()
        box.setObjectName("OutputBox")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 10)
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
        refresh.setCursor(QtCore.Qt.PointingHandCursor)
        refresh.clicked.connect(self.reload_output)
        bar.addWidget(refresh)
        close = QtWidgets.QPushButton("关闭")
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.clicked.connect(lambda: box.hide())
        bar.addWidget(close)
        lay.addLayout(bar)

        self.out_view = QtWidgets.QPlainTextEdit()
        self.out_view.setObjectName("Output")
        self.out_view.setReadOnly(True)
        self.out_view.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.out_view.setMinimumHeight(180)
        self.out_view.setMaximumHeight(320)
        lay.addWidget(self.out_view)
        return box

    # ---------- 行为 ----------

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
        for i in range(self.body_layout.count()):
            item = self.body_layout.itemAt(i)
            section = item.widget() if item else None
            if section is None or not hasattr(section, "cards"):
                continue
            visible = []
            for card in section.cards:
                t = card.tool
                hay = " ".join((t["title"], t["desc"], t["script"], t["group"])).lower()
                hit = (not q) or (q in hay)
                card.setVisible(hit)
                if hit:
                    visible.append(card)
            section.grid.set_cards(visible)
            section.setVisible(bool(visible))

    def toast(self, text, bad=False):
        bar = self.statusBar()
        bar.setStyleSheet(
            "QStatusBar { background: #161b22; color: %s; border-top: 1px solid #21262d; }"
            % ("#ffb4ae" if bad else "#8b949e"))
        bar.showMessage(text, 4000)

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
    app.setApplicationName("LaTeX 笔记工具集")
    app.setStyle("Fusion")
    font = QtGui.QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    return app.exec()


def _report_crash(exc):
    """pythonw 启动时没有 stderr，异常要落盘再弹窗，否则表现成「双击没反应」。"""
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
            None, "面板启动失败",
            text[-1500:] + "\n\n已写入 " + str(log))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 兜底只为留下痕迹
        _report_crash(exc)
        sys.exit(1)
