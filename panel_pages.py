# -*- coding: utf-8 -*-
"""给 panel_qt 加「设置页」与「帮助页」两个面板。

拆成独立文件是为了让 panel_qt.py 不至于膨胀到两千行 —— 这两块是纯展示逻辑，
和主窗口的卡片流、主题切换互不相干。
"""
from PySide6 import QtCore, QtGui, QtWidgets

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
    """内置帮助页：用法说明 + 工具清单。"""

    def __init__(self, tokens=None, parent=None):
        super().__init__(parent)
        self.tokens = tokens or {}
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 6, 4)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 12)
        lay.setSpacing(12)

        # 用 QTextBrowser 显示帮助。
        # 走 HTML 而不是 Markdown：Qt 的 Markdown 解析器只支持标题/粗体/代码块，
        # 表格和列表的样式几乎不可调，中文长文排出来很粗糙。
        doc = QtWidgets.QTextBrowser()
        doc.setObjectName("HelpDoc")
        doc.setOpenExternalLinks(True)
        doc.setHtml(self._html(self.tokens))
        doc.setMinimumHeight(400)
        lay.addWidget(doc, 1)

        # 工具清单表
        table = QtWidgets.QTableWidget()
        table.setObjectName("ResultTable")
        rows = cfg.tool_help_rows()
        table.setRowCount(len(rows))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["分组", "工具", "用途"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        for r, (group, title, desc) in enumerate(rows):
            for c, value in enumerate((group, title, desc)):
                table.setItem(r, c, QtWidgets.QTableWidgetItem(str(value)))
        lay.addWidget(table)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    @staticmethod
    def _html(tokens=None):
        """拼出完整的帮助页 HTML（含内联样式，QTextBrowser 不吃外部 CSS）。"""
        t = tokens or {}
        style = """
        <style>
          body { color: %(fg2)s; font-size: 13px; line-height: 170%%; }
          h1 { color: %(fg)s; font-size: 19px; margin: 0 0 14px 0; }
          h2 { color: %(fg)s; font-size: 14px; margin: 22px 0 8px 0;
               padding-bottom: 5px; border-bottom: 1px solid %(stroke)s; }
          b { color: %(fg)s; }
          ul { margin: 4px 0 10px 0; }
          li { margin-bottom: 6px; }
          code { color: %(fg)s; background: %(subtle)s;
                 padding: 1px 5px; border-radius: 3px;
                 font-family: "Cascadia Mono", Consolas, monospace; }
          table.keys { border-collapse: collapse; margin: 6px 0 12px 0; }
          table.keys td { padding: 4px 14px 4px 0; vertical-align: top; }
          table.keys td:first-child { white-space: nowrap; }
        </style>
        """ % t
        return ("<html><head>" + style + "</head><body>"
                + cfg.HELP_HTML
                + "<h2>工具一览</h2><p>" + cfg.HELP_TOOLS_LEAD + "</p>"
                + "</body></html>")
