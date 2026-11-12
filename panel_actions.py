#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_actions.py — 工具的可视化表单（真正 GUI 化的那一层）

做法不是把工具重写一遍，而是**给每个工具的既有命令行接口配一张表单**：
界面上填参数 → 拼成命令行 → 后台跑 → 输出留在面板里。
工具本身一行不改，它的命令行接口就是稳定 API。

只有具备完整命令行参数的才能这么接；纯 `input()` 循环的工具先在卡片上
保留「控制台」入口，后续再逐个把交互层抽出来。

字段类型：text / int / path / file / choice / check
字段可带 show_if=(字段名, 取值)，不满足时整行隐藏、且不参与拼参数。
"""
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

import panel_core as core

# ---------------------------------------------------------------- 参数拼装


def _build_new_note(v):
    args = [v["name"]]
    if v["abbreviation"]:
        args += ["--abbreviation", v["abbreviation"]]
    if v["outline"]:
        args += ["--outline", v["outline"]]
    if v["levels"]:
        args += ["--levels", v["levels"]]
    if v["template"]:
        args += ["--template", v["template"]]
    if v["dry"]:
        args.append("--dry-run")
    if v["intro"]:
        args.append("--intro")
    if v["summary"]:
        args.append("--summary")
    if v["push"]:
        args.append("--push")
    return args


def _build_clean_aux(v):
    areas = {"整个工作区": "all", "LaTeX_Notes": "notes",
             "Template": "template", "Tools": "tools"}
    args = ["--area", areas.get(v["area"], "all")]
    if v["with_pdf"]:
        args.append("--with-pdf")
    if v["write"]:
        # GUI 里点按钮本身就是确认，不勾 --yes 会卡在 input()
        args += ["--write", "--yes"]
    return args


def _build_outline(v):
    mode = v["mode"]
    if mode == "校验大纲":
        args = ["--check", v["md"]]
        if v["fix"]:
            args.append("--write-levels")
        return args
    if mode == "导出大纲":
        args = ["--export", v["note"]]
        if v["out"]:
            args.append(v["out"])
        return args
    return ["--from-text", v["list"]]


def _build_repo_check(v):
    areas = {"整个工作区": "all", "LaTeX_Notes": "notes",
             "Template": "template", "Tools": "tools"}
    return ["--area", areas.get(v["area"], "all")]


def _build_check_sensitive(v):
    return ["--tracked"] if v["tracked"] else []


def _build_sync_paths(_v):
    return []


def _build_commit(v):
    args = []
    if v["dry"]:
        args.append("--dry-run")
    if v["yes"]:
        args.append("-y")
    if v["msg"]:
        args.append(v["msg"])
    return args


def _build_spec_sync(v):
    return {"只检查": ["--check"], "直接同步": ["--write"],
            "防呆同步": ["--sync-if-safe"]}.get(v["mode"], ["--check"])


def _build_pdf_upright(v):
    args = [v["input"]]
    if v["recursive"]:
        args.append("-r")
    if v["outdir"]:
        args += ["-o", v["outdir"]]
    if v["ccw"]:
        args.append("--ccw")
    if v["dry"]:
        args.append("--dry")
    return args


def _build_watch_notes(v):
    args = []
    if v["dir"]:
        args += ["--dir", v["dir"]]
    args += ["--interval", str(v["interval"])]
    args += ["--prune-interval", str(v["prune"])]
    args += ["--keep", str(v["keep"])]
    if v["once"]:
        args.append("--once")
    if v["no_push"]:
        args.append("--no-push")
    return args


def _watch_repo_choices():
    """LaTeX_Notes 下带 .git 的仓库名。"""
    root = core.WORKSPACE / "LaTeX_Notes"
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir()) if (p / ".git").is_dir()]


# ---------------------------------------------------------------- 表单规格

SPECS = {
    "5": {
        "title": "新建笔记",
        "desc": "从模板复制骨架、清掉测试内容、初始化 git。默认只预演，确认无误再去掉勾选。",
        "fields": [
            {"key": "name", "label": "笔记名", "type": "text",
             "placeholder": "例如 General_Topology", "required": True},
            {"key": "abbreviation", "label": "缩写", "type": "text",
             "placeholder": "ASCII，例如 GT", "required": True},
            {"key": "outline", "label": "大纲文件", "type": "file",
             "placeholder": "可空；给了就按大纲生成章节骨架"},
            {"key": "levels", "label": "层级", "type": "text",
             "placeholder": "可空；例如 part,section"},
            {"key": "template", "label": "模板目录", "type": "path",
             "placeholder": "可空；默认 Template/Math-Note"},
            {"key": "dry", "label": "只预演，不写文件", "type": "check", "default": True},
            {"key": "intro", "label": "骨架里建最外层导引", "type": "check", "default": False},
            {"key": "summary", "label": "骨架里建各级小结", "type": "check", "default": False},
            {"key": "push", "label": "建好后推送到远程", "type": "check", "default": False},
        ],
        "build": _build_new_note,
    },
    "6": {
        "title": "大纲工具",
        "desc": "校验已有大纲 md、从笔记导出大纲、或把缩进清单转成规范 md。",
        "fields": [
            {"key": "mode", "label": "操作", "type": "choice",
             "choices": ["校验大纲", "导出大纲", "从清单新建"], "default": "校验大纲"},
            {"key": "md", "label": "大纲文件", "type": "file", "show_if": ("mode", "校验大纲")},
            {"key": "fix", "label": "把推断的层级写回 md", "type": "check", "default": False,
             "show_if": ("mode", "校验大纲")},
            {"key": "note", "label": "笔记目录", "type": "path", "show_if": ("mode", "导出大纲")},
            {"key": "out", "label": "输出文件", "type": "path", "show_if": ("mode", "导出大纲"),
             "placeholder": "可空；默认写到工作区"},
            {"key": "list", "label": "清单文件", "type": "file", "show_if": ("mode", "从清单新建")},
        ],
        "build": _build_outline,
    },
    "8": {
        "title": "清理编译产物",
        "desc": "先看清单，确认后再勾「真正删除」跑一次。删除只针对有 .tex 源的目录。",
        "fields": [
            {"key": "area", "label": "扫描区域", "type": "choice",
             "choices": ["整个工作区", "LaTeX_Notes", "Template", "Tools"],
             "default": "LaTeX_Notes"},
            {"key": "with_pdf", "label": "连 PDF 一起删（仅同目录有同名 .tex 的）",
             "type": "check", "default": False},
            {"key": "write", "label": "真正删除（不勾只列清单）", "type": "check", "default": False,
             "danger": True},
        ],
        "build": _build_clean_aux,
    },
    "9": {
        "title": "仓库体检",
        "desc": "检查规范副本、误跟踪的编译产物、是否有未提交改动。",
        "fields": [
            {"key": "area", "label": "检查区域", "type": "choice",
             "choices": ["整个工作区", "LaTeX_Notes", "Template", "Tools"],
             "default": "整个工作区"},
        ],
        "build": _build_repo_check,
    },
    "10": {
        "title": "本机信息扫描",
        "desc": "扫仓库里是否混入本机路径、用户名或密钥。提交前的最后一道关。",
        "fields": [
            {"key": "tracked", "label": "只扫已跟踪文件（快）", "type": "check", "default": True},
        ],
        "build": _build_check_sensitive,
    },
    "11": {
        "title": "配置路径检查与修复",
        "desc": "检查配置里的路径是否有效，并按需修复。没有参数，直接跑即可。",
        "fields": [],
        "build": _build_sync_paths,
    },
    "12": {
        "title": "提交本工具集",
        "desc": "add → commit → push。默认预演，确认无误再去掉勾选。",
        "fields": [
            {"key": "msg", "label": "提交说明", "type": "text",
             "placeholder": "可空；留空用默认消息"},
            {"key": "dry", "label": "预演（不真的提交）", "type": "check", "default": True},
            {"key": "yes", "label": "跳过确认直接提交", "type": "check", "default": False,
             "danger": True},
        ],
        "build": _build_commit,
    },
    "14": {
        "title": "项目规范副本一致性",
        "desc": "比对「项目规范.md」与各副本是否逐字节一致，方向恒为 原件 → 副本。",
        "fields": [
            {"key": "mode", "label": "模式", "type": "choice",
             "choices": ["只检查", "直接同步", "防呆同步"], "default": "只检查"},
        ],
        "build": _build_spec_sync,
    },
    "15": {
        "title": "PDF 转正",
        "desc": "把横躺的课件 PDF 转正为 16:9，不重编码。默认预演。",
        "fields": [
            {"key": "input", "label": "PDF 文件或目录", "type": "path", "required": True,
             "placeholder": "例如 D:/某处/课件.pdf"},
            {"key": "recursive", "label": "含子目录", "type": "check", "default": True},
            {"key": "outdir", "label": "另存目录", "type": "path",
             "placeholder": "留空则就地覆盖原文件"},
            {"key": "ccw", "label": "逆时针转正（转出来是倒立时用）", "type": "check",
             "default": False},
            {"key": "dry", "label": "预演（不真的转）", "type": "check", "default": True},
        ],
        "build": _build_pdf_upright,
    },
    "16": {
        "title": "笔记目录监测",
        "desc": "定时提交推送，并按条数上限裁剪历史。测一次用「只跑一轮」。",
        "fields": [
            {"key": "dir", "label": "监测仓库", "type": "choice",
             "choices": _watch_repo_choices, "default": ""},
            {"key": "interval", "label": "检测间隔（秒）", "type": "int", "default": 300},
            {"key": "prune", "label": "裁剪检查间隔（秒）", "type": "int", "default": 900},
            {"key": "keep", "label": "历史保留条数", "type": "int", "default": 20},
            {"key": "once", "label": "只跑一轮就退出", "type": "check", "default": True},
            {"key": "no_push", "label": "只提交不推送", "type": "check", "default": False},
        ],
        "build": _build_watch_notes,
    },
}


def has_form(tool_id):
    return tool_id in SPECS


# ---------------------------------------------------------------- 控件


class FormPanel(QtWidgets.QWidget):
    """一张表单 + 执行按钮 + 输出区。"""

    def __init__(self, tool_id, tool, parent=None):
        super().__init__(parent)
        self.tool_id = tool_id
        self.tool = tool
        self.spec = SPECS[tool_id]
        self.widgets = {}
        self.rows = {}
        self.proc = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        desc = QtWidgets.QLabel(self.spec["desc"])
        desc.setObjectName("PageDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        form_box = QtWidgets.QFrame()
        form_box.setObjectName("Card")
        form = QtWidgets.QGridLayout(form_box)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        row = 0
        for field in self.spec["fields"]:
            container = QtWidgets.QWidget()
            box = QtWidgets.QHBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
            label = QtWidgets.QLabel(field["label"])
            label.setObjectName("FieldLabel")
            label.setFixedWidth(168)
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            box.addWidget(label, 0)
            widget = self._make_widget(field)
            box.addWidget(widget, 1)
            form.addWidget(container, row, 0, 1, 2)
            self.widgets[field["key"]] = widget
            self.rows[field["key"]] = container
            row += 1
        lay.addWidget(form_box)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("StatusText")
        actions.addWidget(self.hint, 1)
        self.run_btn = QtWidgets.QPushButton("执行")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self.start)
        actions.addWidget(self.run_btn)
        self.stop_btn = QtWidgets.QPushButton("中止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.abort)
        self.stop_btn.hide()
        actions.addWidget(self.stop_btn)
        lay.addLayout(actions)

        self.out = QtWidgets.QPlainTextEdit()
        self.out.setObjectName("FormOutput")
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("执行后输出显示在这里")
        lay.addWidget(self.out, 1)

        self._sync_visibility()

    # ---------- 控件 ----------

    def _make_widget(self, field):
        kind = field["type"]
        if kind == "check":
            box = QtWidgets.QCheckBox()
            box.setChecked(bool(field.get("default")))
            if field.get("danger"):
                box.setToolTip("破坏性操作，确认清单无误再勾")
            return box
        if kind == "choice":
            choices = field.get("choices", [])
            if callable(choices):
                choices = choices()
            combo = QtWidgets.QComboBox()
            combo.addItems([str(c) for c in choices])
            default = field.get("default")
            if default is None and choices:
                default = str(choices[0])
            if default is not None and str(default) in [str(c) for c in choices]:
                combo.setCurrentText(str(default))
            combo.currentTextChanged.connect(self._sync_visibility)
            return combo
        if kind in ("path", "file"):
            holder = QtWidgets.QWidget()
            box = QtWidgets.QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(6)
            edit = QtWidgets.QLineEdit(str(field.get("default", "")))
            edit.setObjectName("Args")
            edit.setPlaceholderText(field.get("placeholder", ""))
            box.addWidget(edit, 1)
            btn = QtWidgets.QPushButton("浏览…")
            btn.setObjectName("Secondary")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, e=edit, f=field: self._browse(e, f))
            box.addWidget(btn)
            holder.edit = edit
            return holder
        edit = QtWidgets.QLineEdit(str(field.get("default", "")))
        edit.setObjectName("Args")
        edit.setPlaceholderText(field.get("placeholder", ""))
        if kind == "int":
            edit.setValidator(QtGui.QIntValidator(0, 1000000, edit))
        return edit

    def _browse(self, edit, field):
        if field["type"] == "file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "选择文件", str(core.WORKSPACE),
                "Markdown (*.md);;所有文件 (*)")
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择目录", str(core.WORKSPACE))
        if path:
            edit.setText(path)

    # ---------- 取值 ----------

    def _read(self, field):
        widget = self.widgets[field["key"]]
        kind = field["type"]
        if kind == "check":
            return widget.isChecked()
        if kind == "choice":
            return widget.currentText()
        if kind in ("path", "file"):
            return widget.edit.text().strip()
        return widget.text().strip()

    def values(self):
        raw = {f["key"]: self._read(f) for f in self.spec["fields"]}
        out = dict(raw)
        for field in self.spec["fields"]:
            cond = field.get("show_if")
            if cond:
                key, want = cond
                if str(raw.get(key)) != str(want):
                    out[field["key"]] = ""
        return out

    def _sync_visibility(self):
        raw = {f["key"]: self._read(f) for f in self.spec["fields"]}
        for field in self.spec["fields"]:
            cond = field.get("show_if")
            visible = True
            if cond:
                key, want = cond
                visible = str(raw.get(key)) == str(want)
            self.rows[field["key"]].setVisible(visible)

    # ---------- 执行 ----------

    def start(self):
        if self.proc is not None:
            return
        values = self.values()
        for field in self.spec["fields"]:
            if field.get("required") and not values[field["key"]]:
                self.hint.setText("请填写：{}".format(field["label"]))
                return

        script = core.TOOLS_ROOT / self.tool["script"]
        if not script.is_file():
            self.hint.setText("找不到脚本：{}".format(self.tool["script"]))
            return

        args = self.spec["build"](values)
        program, argv = core.spawn_command(script, args)
        self.out.clear()
        self.hint.setText("运行中…")
        self.run_btn.setEnabled(False)
        self.stop_btn.show()

        proc = QtCore.QProcess(self)
        proc.setProgram(program)
        proc.setArguments(argv)
        proc.setWorkingDirectory(str(script.parent))
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read_output)
        proc.finished.connect(self._finished)
        proc.errorOccurred.connect(self._failed)
        self.proc = proc
        proc.start()

    def _read_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = data.decode("utf-8", "replace")
        self.out.moveCursor(QtGui.QTextCursor.End)
        self.out.insertPlainText(text)
        self.out.moveCursor(QtGui.QTextCursor.End)

    def _finished(self, code, _status):
        self._read_output()
        self.hint.setText("完成，退出码 {}".format(code))
        self._cleanup()

    def _failed(self, _err):
        if self.proc is not None:
            self.hint.setText("启动失败：{}".format(self.proc.errorString()))
        self._cleanup()

    def _cleanup(self):
        if self.proc is not None:
            self.proc.deleteLater()
            self.proc = None
        self.run_btn.setEnabled(True)
        self.stop_btn.hide()

    def abort(self):
        if self.proc is not None:
            self.proc.kill()
            self.hint.setText("已中止")
            self._cleanup()


class TerminalPanel(QtWidgets.QWidget):
    """内嵌终端：把交互式工具直接开在面板里。

    没有表单规格的工具（纯 `input()` 循环）用这个兜底 —— 输出留在面板下方，
    输入从输入行送进子进程的 stdin。不再弹外部控制台窗口。
    """

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.proc = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        desc = QtWidgets.QLabel("交互式运行：输出显示在这里，输入回车送进工具。")
        desc.setObjectName("PageDesc")
        head.addWidget(desc, 1)
        self.stop_btn = QtWidgets.QPushButton("中止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.abort)
        self.stop_btn.hide()
        head.addWidget(self.stop_btn)
        self.restart_btn = QtWidgets.QPushButton("启动")
        self.restart_btn.setObjectName("Primary")
        self.restart_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.restart_btn.clicked.connect(self.start)
        head.addWidget(self.restart_btn)
        lay.addLayout(head)

        self.out = QtWidgets.QPlainTextEdit()
        self.out.setObjectName("FormOutput")
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("点「启动」开始")
        lay.addWidget(self.out, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self.input = QtWidgets.QLineEdit()
        self.input.setObjectName("Args")
        self.input.setPlaceholderText("输入内容后回车发送（工具在等输入时可用）")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        send = QtWidgets.QPushButton("发送")
        send.setObjectName("Secondary")
        send.setCursor(QtCore.Qt.PointingHandCursor)
        send.clicked.connect(self._send)
        row.addWidget(send)
        lay.addLayout(row)

    def start(self):
        if self.proc is not None:
            return
        script = core.TOOLS_ROOT / self.tool["script"]
        if not script.is_file():
            self.out.setPlainText("找不到脚本：{}".format(self.tool["script"]))
            return
        program, argv = core.spawn_command(script, [])
        self.out.clear()
        env = QtCore.QProcessEnvironment.systemEnvironment()
        # 工具往 stdout 写 UTF-8，stdin 也要 UTF-8，否则中文输入会乱码
        env.insert("PYTHONIOENCODING", "utf-8")
        proc = QtCore.QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setProgram(program)
        proc.setArguments(argv)
        proc.setWorkingDirectory(str(script.parent))
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read_output)
        proc.finished.connect(self._finished)
        self.proc = proc
        proc.start()
        self.stop_btn.show()
        self.restart_btn.setEnabled(False)
        self.input.setFocus()

    def _read_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = data.decode("utf-8", "replace")
        self.out.moveCursor(QtGui.QTextCursor.End)
        self.out.insertPlainText(text)
        self.out.moveCursor(QtGui.QTextCursor.End)

    def _send(self):
        if self.proc is None:
            return
        text = self.input.text()
        self.input.clear()
        self.proc.write((text + "\n").encode("utf-8"))

    def _finished(self, code, _status):
        self._read_output()
        self.out.appendPlainText("\n[进程已退出，退出码 {}]".format(code))
        self.stop_btn.hide()
        self.restart_btn.setEnabled(True)
        self.restart_btn.setText("重新启动")
        if self.proc is not None:
            self.proc.deleteLater()
            self.proc = None

    def abort(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.waitForFinished(1500)
            self._finished(self.proc.exitCode() if self.proc else 1, None)


def build(tool_id, tool):
    """给某个工具造面板：有表单规格给表单，否则给内嵌终端。"""
    if has_form(tool_id):
        return FormPanel(tool_id, tool)
    return TerminalPanel(tool)
