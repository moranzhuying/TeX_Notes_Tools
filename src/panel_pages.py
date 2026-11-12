# -*- coding: utf-8 -*-
"""给 panel_qt 加「设置页」与「帮助页」两个面板。

拆成独立文件是为了让 panel_qt.py 不至于膨胀到两千行 —— 这两块是纯展示逻辑，
和主窗口的卡片流、主题切换互不相干。
"""
from PySide6 import QtCore, QtGui, QtWidgets

import re
import sys
from pathlib import Path

import panel_config as cfg


class SettingsPage(QtWidgets.QWidget):
    """全局设置页。"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.config = cfg.load()

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 6, 4)
        outer.setSpacing(10)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 12)
        lay.setSpacing(12)

        lay.addWidget(self._section("外观"))

        # 主题
        theme_box = self._card()
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("跟随系统", "auto")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        idx = self.theme_combo.findData(self.config.get("theme", "auto"))
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        self._row(theme_box, "主题", self.theme_combo,
                  "深浅跟随 Windows 的应用主题设置")

        # 字号
        size_box = self._card()
        self.size_combo = QtWidgets.QComboBox()
        self.size_combo.addItem("较小", 0.9)
        self.size_combo.addItem("标准", 1.0)
        self.size_combo.addItem("较大", 1.15)
        self.size_combo.addItem("很大", 1.3)
        scale = float(self.config.get("font_scale", 1.0))
        idx = max(0, self.size_combo.findData(scale))
        if idx < 0:
            idx = 1
        self.size_combo.setCurrentIndex(idx)
        self.size_combo.currentIndexChanged.connect(self._on_size)
        self._row(size_box, "界面字号", self.size_combo,
                  "放大整个界面的文字与控件")
        lay.addWidget(theme_box)
        lay.addWidget(size_box)

        lay.addWidget(self._section("行为"))
        behavior = self._card()
        self.confirm_check = QtWidgets.QCheckBox("破坏性操作执行前弹出确认")
        self.confirm_check.setChecked(bool(self.config.get("confirm_danger", True)))
        self.confirm_check.toggled.connect(self._on_confirm)
        self._row(behavior, "二次确认", self.confirm_check,
                  "删除、提交、覆盖这类操作先问一句")

        self.columns_check = QtWidgets.QCheckBox("记住表格列宽")
        self.columns_check.setChecked(bool(self.config.get("remember_columns", True)))
        self.columns_check.toggled.connect(self._on_columns)
        self._row(behavior, "列宽记忆", self.columns_check,
                  "拖过的列宽下次打开还在")
        lay.addWidget(behavior)

        lay.addWidget(self._section("数据"))
        data = self._card()
        self.path_label = QtWidgets.QLabel(str(cfg.CONFIG_PATH))
        self.path_label.setObjectName("PathText")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._row(data, "配置文件", self.path_label,
                  "删掉这个文件即可恢复默认设置")

        reset = QtWidgets.QPushButton("恢复默认设置")
        reset.setObjectName("Secondary")
        reset.setCursor(QtCore.Qt.PointingHandCursor)
        reset.clicked.connect(self._on_reset)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(reset)
        row.addStretch(1)
        data_box = QtWidgets.QFrame()
        data_box.setObjectName("Card")
        data_lay = QtWidgets.QVBoxLayout(data_box)
        data_lay.setContentsMargins(18, 16, 18, 16)
        data_lay.setSpacing(10)
        data_lay.addLayout(self._label_row("配置文件", self.path_label))
        data_lay.addLayout(row)
        lay.addWidget(data_box)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ---------- 构件 ----------

    def _section(self, title):
        label = QtWidgets.QLabel(title)
        label.setObjectName("SectionTitle")
        return label

    def _card(self):
        box = QtWidgets.QFrame()
        box.setObjectName("Card")
        self._card_lay = QtWidgets.QVBoxLayout(box)
        self._card_lay.setContentsMargins(18, 16, 18, 16)
        self._card_lay.setSpacing(10)
        return box

    def _label_row(self, label, widget):
        """一行：左边标题，右边控件。"""
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        lab = QtWidgets.QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(120)
        lab.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        row.addWidget(lab, 0)
        row.addWidget(widget, 1)
        return row

    def _row(self, box, label, widget, hint=""):
        """往卡片里加一行控件 + 说明。控件不必铺满整行，太宽反而空。"""
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        lab = QtWidgets.QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(120)
        lab.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        top.addWidget(lab, 0)
        if isinstance(widget, QtWidgets.QComboBox):
            widget.setFixedWidth(200)
            top.addWidget(widget, 0)
        elif isinstance(widget, QtWidgets.QCheckBox):
            # 复选框自带文字，固定宽度让各行的勾选框上下对齐
            widget.setFixedWidth(260)
            top.addWidget(widget, 0)
        else:
            top.addWidget(widget, 1)
        top.addStretch(1)
        lay.addLayout(top)
        if hint:
            note = QtWidgets.QLabel(hint)
            note.setObjectName("StatusText")
            note.setWordWrap(True)
            # 说明文字缩进到控件起点，跟控件左对齐
            note.setContentsMargins(132, 0, 0, 0)
            lay.addWidget(note)
        box.layout().addWidget(wrap)
        return wrap

    # ---------- 回调 ----------

    def _save(self, **kwargs):
        self.config.update(kwargs)
        cfg.save(self.config)

    def _on_theme(self, _index):
        value = self.theme_combo.currentData()
        self._save(theme=value)
        self.main.apply_theme(preference=value)

    def _on_size(self, _index):
        value = float(self.size_combo.currentData())
        self._save(font_scale=value)
        self.main.apply_font_scale(value)

    def _on_confirm(self, checked):
        self._save(confirm_danger=bool(checked))

    def _on_columns(self, checked):
        self._save(remember_columns=bool(checked))

    def _on_reset(self):
        self.config = dict(cfg.DEFAULTS)
        cfg.save(self.config)
        self.main.apply_theme(preference=self.config["theme"])
        self.main.apply_font_scale(float(self.config["font_scale"]))
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.config["theme"])))
        self.size_combo.setCurrentIndex(
            max(0, self.size_combo.findData(float(self.config["font_scale"]))))
        self.confirm_check.setChecked(self.config["confirm_danger"])
        self.columns_check.setChecked(self.config["remember_columns"])
        self.main.toast("已恢复默认设置")


class HelpPage(QtWidgets.QWidget):
    """帮助页：直接渲染 resources/help/ 下的文档，站内链接在页面内跳转。

    文档是磁盘上的 HTML（由 `src/make_help.py` 生成），不进 Python 字符串 ——
    一篇工具文档两三千字，塞进代码里既难改也难读。图片用相对路径 `img/xx.png`，
    靠 `setSearchPaths` 解析，打包后从 `_MEIPASS/help` 读。
    """

    #: 文档是浅色写死的，深色主题下按这张表换色（源色 → 目标色）。
    #: 只在「深色」时做字符串替换 —— 重新生成一份深色文档没必要，
    #: 而且 QTextBrowser 不认 CSS 变量，没有更干净的办法。
    DARK_SWAP = {
        "#ffffff": "#1f1f1f",   # 纸底
        "#24292f": "#e6e6e6",   # 正文
        "#0f172a": "#ffffff",   # 标题
        "#3d4653": "#c5c5c5",   # 副文
        "#6b7280": "#9a9a9a",   # 弱化
        "#5c6470": "#a0a0a0",   # 表头文字
        "#0067c0": "#60cdff",   # 链接
        "#f6f8fa": "#262626",   # 浅底块
        "#f2f4f7": "#303030",   # 表头 / 行内代码底
        "#8a2b06": "#e8b48c",   # 行内代码字
        "#e6e8eb": "#3a3a3a",   # 分隔线
        "#e1e4e8": "#3a3a3a",   # 表格边框
        "#fff8e6": "#3a3220",   # 提示底
        "#f0d29a": "#7a6640",   # 提示边
        "#fdecea": "#3a1e1c",   # 危险底
        "#f3b6b0": "#7a3b36",   # 危险边
        "#eef7f0": "#1e2e22",   # 建议底
        "#b7dcc1": "#3e6b49",   # 建议边
        "#c42b1c": "#ff99a4",   # 错误文字
    }

    def __init__(self, tokens=None, parent=None):
        super().__init__(parent)
        self._dark = False
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 6, 4)
        outer.setSpacing(0)

        self.doc = QtWidgets.QTextBrowser()
        self.doc.setObjectName("HelpDoc")
        self.doc.setOpenLinks(False)        # 站内链接自己处理，否则会当文件打开
        self.doc.setOpenExternalLinks(True)
        self.doc.anchorClicked.connect(self._go)
        self.doc.setSearchPaths([str(help_dir())])
        outer.addWidget(self.doc, 1)
        self.show_doc("index.html")

    def show_doc(self, name):
        """加载 help 目录下的一篇文档；失败时给一句人话。"""
        path = help_dir() / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.doc.setHtml(
                f'<p style="color:#c42b1c">帮助文档缺失：{path}<br>{exc}</p>')
            return
        self._name = name
        text = self._fit_images(text)
        if self._dark:
            # 配图也换深色那一套 —— 只改文字颜色不改图，暗色下会很刺眼
            text = text.replace("img/light/", "img/dark/")
            for src, dst in self.DARK_SWAP.items():
                text = text.replace(src, dst)
        self.doc.setHtml(text)
        self.doc.moveCursor(QtGui.QTextCursor.Start)

    def _fit_images(self, text):
        """按当前视口宽度等比缩放图片。

        HTML 里的宽高是「设计宽度」（1000），窗口窄了会出横向滚动条、宽了图又偏小。
        这里统一换成实测宽度再按原比例算高度 —— 只给宽度不给高度时 Qt 会按图片
        DPI 另算高度，图下会留一大块空白。
        """
        avail = max(520, self.doc.viewport().width() - 40)
        if avail == getattr(self, "_img_w", None):
            return text
        self._img_w = avail

        def repl(m):
            w, h = int(m.group(1)), int(m.group(2))
            return f'width="{avail}" height="{max(1, round(h * avail / w))}"'

        return re.sub(r'width="(\d+)" height="(\d+)"', repl, text)

    def resizeEvent(self, event):
        """窗口宽度变得够多时重排一次图片（防抖，避免拖动时反复重渲染）。"""
        super().resizeEvent(event)
        now = self.doc.viewport().width()
        if abs(now - getattr(self, "_last_w", 0)) > 60:
            self._last_w = now
            QtCore.QTimer.singleShot(220, self.reload)

    def set_dark(self, dark):
        """主题切换时重算文档配色。"""
        if dark == self._dark:
            return
        self._dark = dark
        self.reload()

    def _go(self, url):
        """站内链接跳转；点到图片就用系统看图器打开原图。"""
        name = url.fileName() or "index.html"
        if name.endswith(".html") and (help_dir() / name).is_file():
            self.show_doc(name)
            return
        local = help_dir() / url.toString().lstrip("/")
        if local.is_file():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(local)))
        else:
            QtGui.QDesktopServices.openUrl(url)

    def reload(self):
        """主题切换时不用重算（文档固定浅色），但保持接口一致。"""
        self.show_doc(getattr(self, "_name", "index.html"))


def help_dir():
    """帮助文档目录：打包后在解包目录的 `help/`，源码运行时在 `resources/help/`。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "help"
    return Path(__file__).resolve().parent.parent / "resources" / "help"
