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


def _build_symbols(v):
    action = v["action"]
    if action.startswith("回填"):
        args = ["--merge"]
    elif action.startswith("分发"):
        args = ["--distribute"]
    elif action == "刷新补全":
        args = ["--cwl"]
    elif action == "删除符号":
        args = ["--drop"]
        if v["drop"]:
            args += [w for w in v["drop"].split() if w]
    elif action == "提取到档案":
        # 只写工具自己的提取档案，不动模板
        return ["--extract"]
    elif action == "引入新记号":
        args = ["--add-name", v["add_name"], "--add-def", v["add_def"]]
        if v["add_comment"]:
            args += ["--add-comment", v["add_comment"]]
        if v["add_overwrite"]:
            args.append("--add-overwrite")
        return args
    else:
        args = ["--all"]
    if v["write"]:
        args.append("--write")
    return args


def _build_progress(v):
    args = ["--root", v["root"], "--port", str(v["port"])]
    if v["allow_write"]:
        args.append("--allow-write")
        for book in v["books"].split(","):
            if book.strip():
                args += ["--write-book", book.strip()]
    if v["allow_open"]:
        args.append("--allow-open")
    return args


def _build_video2text(v):
    op = v["op"]
    if op == "列出合集":
        return ["--collections"]
    if op == "补做失败项":
        return ["--only-failed"]
    if op == "锁状态诊断":
        return ["--lock-status"]
    if op == "导出合集 ZIP":
        args = ["--export-collection", v["collection_id"]]
        if v["export_to"]:
            args += ["--export-to", v["export_to"]]
        return args
    if op == "同步标题文件夹":
        return ["--sync-titles", v["collection_id"]]

    args = []
    if v["url"]:
        args.append(v["url"])
    if v["mode"] != "默认":
        args += ["--mode", v["mode"]]
    if v["lang"]:
        args += ["--lang", v["lang"]]
    if v["model"]:
        args += ["--model", v["model"]]
    if v["model_dir"]:
        args += ["--model-dir", v["model_dir"]]
    if v["whisper_lang"]:
        args += ["--whisper-language", v["whisper_lang"]]
    if v["device"] != "默认":
        args += ["--device", v["device"]]
    if v["compute_type"]:
        args += ["--compute-type", v["compute_type"]]
    if v["outdir"]:
        args += ["-o", v["outdir"]]
    if v["cookies"]:
        args += ["--cookies", v["cookies"]]
    if v["refresh"]:
        args.append("--refresh")
    if v["single"]:
        args.append("--single")
    if v["all_parts"]:
        args.append("--all-parts")
    if v["force_whisper"]:
        args.append("--force-whisper")
    if v["keep_audio"]:
        args.append("--keep-audio")
    if v["no_vad"]:
        args.append("--no-vad")
    if v["no_cookies"]:
        args.append("--no-cookies")
    if v["browser_cookies"]:
        args.append("--use-browser-cookies")
    return args


def _build_manager(v):
    op = v["op"]
    if op == "显示各仓库状态":
        return ["--status"]
    if op == "批量提交并推送":
        args = ["--commit-all"]
        if v["msg"]:
            args += ["--msg", v["msg"]]
        return args
    if op == "只推送、不提交":
        args = ["--commit-all", "--push-only"]
        if v["msg"]:
            args += ["--msg", v["msg"]]
        return args
    if op == "为未入库的文件夹建仓库":
        args = ["--create-repo"]
        if v["selection"]:
            args += ["--selection", v["selection"]]
        if v["account"]:
            args += ["--account", v["account"]]
        return args
    args = ["--set-root", v["root"]]
    if v["account"]:
        args += ["--account", v["account"]]
    return args


def _build_note_tools(v):
    args = ["--note", v["note"]]
    action = v["action"]
    if action == "提交并推送":
        args += ["--action", "commit"]
    elif action == "切换习题编排模式":
        args += ["--action", "exercise"]
    else:
        args += ["--action", "intro-summary"]
        args += ["--scope", v["scope"]]
        if v["yes"]:
            args.append("--yes")
    return args


def _build_git_setup(v):
    op = v["op"]
    if op == "检测环境":
        return ["--check"]
    if op == "配置 Git 账户":
        args = ["--account"]
        if v["name"]:
            args += ["--name", v["name"]]
        if v["email"]:
            args += ["--email", v["email"]]
        return args
    args = ["--ssh"]
    if v["gen_key"]:
        args.append("--gen-key")
    if v["write_443"]:
        args.append("--write-443")
    if v["test"]:
        args.append("--test")
    return args


def _note_choices():
    """LaTeX_Notes 下含 main.tex 的笔记目录名。"""
    root = core.WORKSPACE / "LaTeX_Notes"
    if not root.is_dir():
        return []
    names = [p.name for p in sorted(root.iterdir())
             if p.is_dir() and (p / "main.tex").is_file()]
    return names


# ---------------------------------------------------------------- 表单规格

SPECS = {
    "3": {
        "title": "符号库管理",
        "desc": "在模板与各笔记之间搬运符号，或刷新 TeXStudio 补全。默认只预览，不写文件。",
        "fields": [
            {"key": "action", "label": "操作", "type": "choice",
             "choices": ["回填（笔记 → 模板）", "分发（模板 → 笔记）", "刷新补全",
                         "删除符号", "提取到档案", "引入新记号", "全套（回填 + 补全 + 分发）"],
             "default": "回填（笔记 → 模板）"},
            {"key": "drop", "label": "要删除的符号名", "type": "text",
             "placeholder": "多个用空格分隔", "show_if": ("action", "删除符号")},
            {"key": "add_name", "label": "命令名", "type": "text",
             "placeholder": "只允许字母，不含反斜杠", "show_if": ("action", "引入新记号")},
            {"key": "add_def", "label": "定义", "type": "text",
             "placeholder": "例如 \\operatorname{Orb}", "show_if": ("action", "引入新记号")},
            {"key": "add_comment", "label": "注释", "type": "text",
             "placeholder": "可空", "show_if": ("action", "引入新记号")},
            {"key": "add_overwrite", "label": "覆盖同名已有定义", "type": "check",
             "default": False, "danger": True, "show_if": ("action", "引入新记号")},
            {"key": "write", "label": "真正写入（默认仅预览）", "type": "check", "default": False,
             "danger": True,
             "show_if": ("action", ["回填（笔记 → 模板）", "分发（模板 → 笔记）",
                                    "刷新补全", "删除符号", "全套（回填 + 补全 + 分发）"])},
        ],
        "build": _build_symbols,
    },
    "4": {
        "title": "写作工作台",
        "desc": "启动本机写作工作台（浏览器界面）。默认只读；授权写入要按书单独给。",
        "script": "progress/workbench_server.py",
        "fields": [
            {"key": "root", "label": "笔记根目录", "type": "path",
             "default": str(Path(core.WORKSPACE) / "LaTeX_Notes")},
            {"key": "port", "label": "端口", "type": "int", "default": 7656},
            {"key": "allow_write", "label": "允许写入（否则只读）", "type": "check",
             "default": False, "danger": True},
            {"key": "books", "label": "授权写入的书", "type": "text",
             "placeholder": "逗号分隔；需同时勾选允许写入", "show_if": ("allow_write", True)},
            {"key": "allow_open", "label": "允许调起 TeXstudio（不授权 TeX 写入）",
             "type": "check", "default": False},
        ],
        "build": _build_progress,
    },
    "13": {
        "title": "视频转文字",
        "desc": "字幕优先，没有字幕时用本地 whisper 转写。",
        "fields": [
            {"key": "op", "label": "操作", "type": "choice",
             "choices": ["转写视频", "列出合集", "补做失败项", "导出合集 ZIP",
                         "同步标题文件夹", "锁状态诊断"],
             "default": "转写视频"},
            {"key": "url", "label": "视频地址", "type": "text",
             "placeholder": "BV 号或视频链接", "show_if": ("op", "转写视频")},
            {"key": "mode", "label": "取源方式", "type": "choice",
             "choices": ["默认", "subtitles", "auto", "whisper"], "default": "默认",
             "show_if": ("op", "转写视频")},
            {"key": "lang", "label": "字幕语言码", "type": "text", "placeholder": "如 ai-zh",
             "show_if": ("op", "转写视频")},
            {"key": "model", "label": "whisper 模型", "type": "text", "placeholder": "默认 medium",
             "show_if": ("op", "转写视频")},
            {"key": "model_dir", "label": "本地模型目录", "type": "path",
             "placeholder": "可空", "show_if": ("op", "转写视频")},
            {"key": "whisper_lang", "label": "转写语言", "type": "text",
             "placeholder": "如 zh", "show_if": ("op", "转写视频")},
            {"key": "device", "label": "设备", "type": "choice",
             "choices": ["默认", "cpu", "cuda"], "default": "默认",
             "show_if": ("op", "转写视频")},
            {"key": "compute_type", "label": "计算精度", "type": "text",
             "placeholder": "cpu 用 int8", "show_if": ("op", "转写视频")},
            {"key": "outdir", "label": "输出根目录", "type": "path",
             "placeholder": "留空用脚本同级 _data", "show_if": ("op", "转写视频")},
            {"key": "cookies", "label": "cookie 文件", "type": "file",
             "placeholder": "Netscape 格式，可空", "show_if": ("op", "转写视频")},
            {"key": "single", "label": "只处理当前视频", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "all_parts", "label": "展开全部分 P", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "force_whisper", "label": "忽略字幕强制转写", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "keep_audio", "label": "保留音频", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "no_vad", "label": "关闭静音过滤", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "refresh", "label": "强制重做（含已成功的）", "type": "check", "default": False,
             "show_if": ("op", "转写视频")},
            {"key": "no_cookies", "label": "匿名探测（不用 cookie）", "type": "check",
             "default": False, "show_if": ("op", "转写视频")},
            {"key": "browser_cookies", "label": "借用浏览器登录态", "type": "check",
             "default": False, "show_if": ("op", "转写视频")},
            {"key": "collection_id", "label": "合集 ID", "type": "text",
             "placeholder": "见「列出合集」的输出",
             "show_if": ("op", ["导出合集 ZIP", "同步标题文件夹"])},
            {"key": "export_to", "label": "ZIP 保存路径", "type": "path",
             "placeholder": "留空用默认名", "show_if": ("op", "导出合集 ZIP")},
        ],
        "build": _build_video2text,
    },
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
    "1": {
        "title": "Git 基本信息",
        "desc": "检测环境、配置账户与 SSH。SSH 部分会显示公钥，复制到 GitHub 即可。",
        "fields": [
            {"key": "op", "label": "操作", "type": "choice",
             "choices": ["检测环境", "配置 Git 账户", "配置 SSH"], "default": "检测环境"},
            {"key": "name", "label": "用户名", "type": "text",
             "placeholder": "留空则不改动", "show_if": ("op", "配置 Git 账户")},
            {"key": "email", "label": "邮箱", "type": "text",
             "placeholder": "留空则不改动", "show_if": ("op", "配置 Git 账户")},
            {"key": "gen_key", "label": "没有密钥时生成 ed25519", "type": "check",
             "default": False, "show_if": ("op", "配置 SSH")},
            {"key": "write_443", "label": "写 ssh config 的 443 端口", "type": "check",
             "default": True, "show_if": ("op", "配置 SSH")},
            {"key": "test", "label": "测试连通性", "type": "check", "default": True,
             "show_if": ("op", "配置 SSH")},
        ],
        "build": _build_git_setup,
    },
    "2": {
        "title": "笔记工作区管理",
        "desc": "查看各仓库状态、批量提交推送、为未入库的文件夹建仓库。",
        "fields": [
            {"key": "op", "label": "操作", "type": "choice",
             "choices": ["显示各仓库状态", "批量提交并推送", "只推送、不提交",
                         "为未入库的文件夹建仓库", "设置笔记根目录"],
             "default": "显示各仓库状态"},
            {"key": "msg", "label": "提交说明", "type": "text",
             "placeholder": "留空用默认消息",
             "show_if": ("op", ["批量提交并推送", "只推送、不提交"])},
            {"key": "selection", "label": "要建仓库的编号", "type": "text",
             "placeholder": "逗号分隔；留空＝全选", "show_if": ("op", "为未入库的文件夹建仓库")},
            {"key": "account", "label": "远程账户名", "type": "text",
             "placeholder": "如 GitHub 用户名", "show_if": ("op", "为未入库的文件夹建仓库")},
            {"key": "root", "label": "笔记根目录", "type": "path",
             "default": str(Path(core.WORKSPACE) / "LaTeX_Notes"),
             "show_if": ("op", "设置笔记根目录")},
        ],
        "build": _build_manager,
    },
    "7": {
        "title": "单本笔记工具",
        "desc": "对选定的笔记提交推送、切换习题编排模式，或补导引与小结。",
        "fields": [
            {"key": "note", "label": "笔记", "type": "choice",
             "choices": _note_choices, "default": ""},
            {"key": "action", "label": "动作", "type": "choice",
             "choices": ["提交并推送", "切换习题编排模式", "补导引与小结"],
             "default": "提交并推送"},
            {"key": "scope", "label": "补哪些", "type": "choice",
             "choices": ["both", "intro", "summary"], "default": "both",
             "show_if": ("action", "补导引与小结")},
            {"key": "yes", "label": "免确认直接写入", "type": "check", "default": False,
             "danger": True, "show_if": ("action", "补导引与小结")},
        ],
        "build": _build_note_tools,
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

    @staticmethod
    def _match(cond, raw):
        """show_if 条件是否满足。want 可以是列表（任一匹配即可）。"""
        key, want = cond
        if isinstance(want, (list, tuple)):
            return str(raw.get(key)) in [str(w) for w in want]
        return str(raw.get(key)) == str(want)

    def values(self):
        raw = {f["key"]: self._read(f) for f in self.spec["fields"]}
        out = dict(raw)
        for field in self.spec["fields"]:
            cond = field.get("show_if")
            if cond and not self._match(cond, raw):
                out[field["key"]] = ""
        return out

    def _sync_visibility(self):
        raw = {f["key"]: self._read(f) for f in self.spec["fields"]}
        for field in self.spec["fields"]:
            cond = field.get("show_if")
            visible = True if not cond else self._match(cond, raw)
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

        script = core.TOOLS_ROOT / self.spec.get("script", self.tool["script"])
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
        script = core.TOOLS_ROOT / self.spec.get("script", self.tool["script"])
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
