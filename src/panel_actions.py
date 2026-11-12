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
import os
import re
import subprocess
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

import panel_core as core

def _clean_output(text):
    """去掉命令行回显、压缩空行，让结果区只剩信息本身。"""
    lines = []
    for line in text.splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if stripped.startswith(("python ", "python3 ", "用法：", "Usage:")):
            continue
        lines.append(s)
    out, blank = [], 0
    for s in lines:
        if not s.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(s)
    return "\n".join(out).strip()


def _parse_status_rows(text):
    """把 manager --status 的输出拆成表行。"""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("【") or s.startswith("文件") or set(s) <= set("- "):
            continue
        parts = s.split(None, 4)
        if len(parts) >= 4:
            rows.append(parts)
    return rows


def _status_summary(rows):
    dirty = sum(1 for r in rows if len(r) > 2 and r[2] not in ("0", "?"))
    if dirty:
        return "{} 个仓库，{} 个有未提交改动".format(len(rows), dirty)
    return "{} 个仓库，全部干净".format(len(rows))


def _parse_repo_rows(text):
    """把 repo_check 的巡检结果拆成表行。"""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("["):
            continue
        m = re.match(r"\[(.+?)\]\s+(\S+)\s+(.+)", s)
        if m:
            rows.append([m.group(1), m.group(2), m.group(3)])
    return rows


def _repo_summary(rows):
    bad = [r for r in rows if "✓" not in r[2]]
    if bad:
        return "{} 个仓库，{} 个有问题".format(len(rows), len(bad))
    return "{} 个仓库，全部通过".format(len(rows))


def _parse_clean_rows(text):
    """把 clean_aux 的清单拆成表行（目录行 + 下一行详情）。"""
    rows = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        m = re.match(r"^\d+\.\s+(.+)$", s)
        if not m:
            continue
        path = m.group(1)
        detail = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # 详情行形如「5 个文件  256 KB   .aux, .gz, .log」
        # 大小占几个 token 不定（256 KB / 1.2 MB），类型段从第一个以 . 开头的 token 起
        tokens = detail.split()
        count = " ".join(tokens[:2])
        size_parts, kinds = [], ""
        for tok in tokens[2:]:
            if kinds or tok.startswith("."):
                kinds = (kinds + " " + tok).strip()
            else:
                size_parts.append(tok)
        rows.append([path, count, " ".join(size_parts), kinds])
    return rows


def _clean_summary(rows):
    total = 0
    for row in rows:
        digits = re.match(r"^(\d+)", row[1]) if len(row) > 1 else None
        if digits:
            total += int(digits.group(1))
    if not rows:
        return "没有需要清理的编译产物"
    return "{} 个目录，共 {} 个文件".format(len(rows), total)


# ---------------------------------------------------------------- 输出解析
#
# 工具的输出大多是「一行一条」的键值或列表，逐个写成表格比给一坨文本好用。
# 解析不出结构时返回空列表，界面自动退回文本模式。


def _kv_rows(text):
    """「键：值」逐行 → 两列表。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or "：" not in s:
            continue
        key, _, value = s.partition("：")
        key, value = key.strip(), value.strip()
        if key and value:
            rows.append([key, value])
    return rows


def _fallback_summary(text):
    """表格解析不出内容时，从输出里捞一句结论当摘要。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return "无输出"
    for line in reversed(lines):
        if any(k in line for k in ("没有", "已取消", "通过", "一致", "完成",
                                   "无改动", "跳过", "失败")):
            return line[:90]
    return lines[-1][:90]


def _parse_env_rows(text):
    """git_setup --check：环境检测项。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        if "：" not in s or s.startswith("【"):
            continue
        key, _, value = s.partition("：")
        key = key.strip()
        if key and value.strip():
            rows.append([key, value.strip()])
    return rows


def _env_summary(rows):
    bad = [r for r in rows if "✗" in r[1]]
    if bad:
        return "{} 项检查，{} 项有问题".format(len(rows), len(bad))
    return "{} 项检查，全部正常".format(len(rows))


def _parse_symbols_rows(text):
    """symbols：根目录 / 符号数 / 差异统计。"""
    return _kv_rows(text)


def _symbols_summary(rows):
    for key, value in rows:
        if key.startswith("模板符号"):
            return "模板符号 " + value
    return "{} 项检查".format(len(rows))


def _parse_new_note_rows(text):
    """new_note：按「复制骨架 / 清理测试内容」等小节分组列条目。"""
    rows = []
    section = "概览"
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        s = raw.strip()
        if not indented and s.endswith("："):
            section = s[:-1]
            continue
        rows.append([section, s])
    return rows


def _new_note_summary(rows):
    return "{} 个条目".format(len(rows))


def _parse_outline_rows(text):
    """outline_tool --check：✗ 第 N 行：问题。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^✗\s*第\s*(\d+)\s*行：(.+)$", s)
        if m:
            rows.append([m.group(1), m.group(2)])
    if not rows and "✓ 格式正确" in text:
        rows.append(["整体", "✓ 格式正确"])
    return rows


def _outline_summary(rows):
    if not rows:
        return "没有解析出问题"
    if len(rows) == 1 and rows[0][1].startswith("✓"):
        return "格式正确"
    return "{} 处问题".format(len(rows))


def _parse_note_files(text):
    """note_tools：＋ 新建 / ~ 修改 的文件清单。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("＋"):
            rows.append(["新建", s[1:].strip()])
        elif s.startswith("~"):
            rows.append(["修改", s[1:].strip()])
    return rows


def _note_summary(rows):
    return "{} 个文件有变动".format(len(rows))


def _parse_sync_rows(text):
    """sync_paths：[OK] 文件:行 键 = 值 / [OK] 文件 -> 值。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^\[([^\]]+)\]\s+(.*)$", s)
        if not m:
            continue
        status, rest = m.group(1), m.group(2)
        if "->" in rest:
            item, _, value = rest.partition("->")
            rows.append([status, item.strip(), "→", value.strip()])
        elif "=" in rest:
            item, _, value = rest.partition("=")
            parts = item.strip().split(None, 1)
            where = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            rows.append([status, where, key, value.strip()])
        else:
            rows.append([status, rest, "", ""])
    return rows


def _sync_summary(rows):
    bad = [r for r in rows if r[0] != "OK"]
    if bad:
        return "{} 项检查，{} 项异常".format(len(rows), len(bad))
    return "{} 项检查，全部正常".format(len(rows))


def _parse_commit_rows(text):
    """commit --dry-run：待提交文件清单。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^([?MADRCU!]{1,2})\s+(.+)$", s)
        if m:
            rows.append([m.group(1), m.group(2).strip()])
    return rows


def _commit_summary(rows):
    if not rows:
        return "没有待提交的改动"
    return "{} 个文件待提交".format(len(rows))


def _parse_collection_rows(text):
    """video2text --collections：ID | 标题 | 进度。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        if "|" not in s:
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) >= 3:
            rows.append(parts[:3])
    return rows


def _collection_summary(rows):
    return "{} 个合集".format(len(rows))


def _parse_spec_rows(text):
    """spec_sync --check：状态 / 原件 / 副本与哈希。"""
    rows = []
    cur = None
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^\[([^\]]+)\]\s+(.+)$", s)
        if m:
            cur = [m.group(1), m.group(2), ""]
            rows.append(cur)
            continue
        if cur is None or not s:
            continue
        if s.startswith("↔"):
            cur[2] = s.lstrip("↔ ").strip()
        elif s.startswith("sha256"):
            cur[2] = (cur[2] + "　" + s).strip()
    return rows


def _spec_summary(rows):
    bad = [r for r in rows if r[0] not in ("一致", "OK")]
    if bad:
        return "{} 份副本，{} 份不一致".format(len(rows), len(bad))
    return "{} 份副本，全部一致".format(len(rows))


def _parse_watch_rows(text):
    """watch_notes：[时间][pid][级别] 消息。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^\[([^\]]+)\]\[\d+\]\[(\w+)\]\s*(.*)$", s)
        if m:
            rows.append([m.group(1), m.group(2), m.group(3)])
    return rows


def _watch_summary(rows):
    if not rows:
        return "没有输出"
    return rows[-1][2][:60]


def _parse_pdf_rows(text):
    """pdf_upright：序号 文件 页数 尺寸 结论。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^(\d+)\.\s+(.+?)\s{2,}(\d+)\s*页\s*(.*)$", s)
        if not m:
            continue
        name, pages, rest = m.group(2), m.group(3), m.group(4).strip()
        # 尺寸与结论之间是全角空格
        parts = [p.strip() for p in rest.split("　") if p.strip()]
        size = parts[0] if parts else ""
        verdict = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
        if len(parts) == 1:
            size, verdict = "", parts[0]
        rows.append([name, pages, size, verdict])
    return rows


def _pdf_summary(rows):
    if not rows:
        return "没有扫描到 PDF"
    need = [r for r in rows if "跳过" not in r[3]]
    if need:
        return "{} 个 PDF，{} 个需要转正".format(len(rows), len(need))
    return "{} 个 PDF，都不需要转正".format(len(rows))


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
        "result": {
            "kind": "table",
            "columns": ['检查项', '结果'],
            "parse": _parse_symbols_rows,
            "summary": _symbols_summary,
        },
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
             "choices": ["列出合集", "转写视频", "补做失败项", "导出合集 ZIP",
                         "同步标题文件夹", "锁状态诊断"],
             "default": "列出合集"},
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
        "result": {
            "kind": "table",
            "columns": ['ID', '标题', '进度'],
            "parse": _parse_collection_rows,
            "summary": _collection_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['类别', '条目'],
            "parse": _parse_new_note_rows,
            "summary": _new_note_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['位置', '问题'],
            "parse": _parse_outline_rows,
            "summary": _outline_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['项目', '值'],
            "parse": _parse_env_rows,
            "summary": _env_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ["文件夹", "分支", "改动", "领先/落后", "远程"],
            "parse": _parse_status_rows,
            "summary": _status_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['动作', '文件'],
            "parse": _parse_note_files,
            "summary": _note_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ["目录", "文件数", "大小", "类型"],
            "parse": _parse_clean_rows,
            "summary": _clean_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ["区域", "仓库", "结果"],
            "parse": _parse_repo_rows,
            "summary": _repo_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['状态', '位置', '键', '值'],
            "parse": _parse_sync_rows,
            "summary": _sync_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['状态', '文件'],
            "parse": _parse_commit_rows,
            "summary": _commit_summary,
        },
    },
    "14": {
        "title": "项目规范副本一致性",
        "desc": "比对「项目规范.md」与各副本是否逐字节一致，方向恒为 原件 → 副本。",
        "fields": [
            {"key": "mode", "label": "模式", "type": "choice",
             "choices": ["只检查", "直接同步", "防呆同步"], "default": "只检查"},
        ],
        "build": _build_spec_sync,
        "result": {
            "kind": "table",
            "columns": ['状态', '原件', '副本'],
            "parse": _parse_spec_rows,
            "summary": _spec_summary,
        },
    },
    "15": {
        "title": "PDF 转正",
        "desc": "把横躺的课件 PDF 转正为 16:9，不重编码。默认预演。",
        "fields": [
            {"key": "input", "label": "PDF 文件或目录", "type": "path", "required": True,
             "default": str(core.WORKSPACE / "Exam"),
             "placeholder": "例如 D:/某处/课件.pdf"},
            {"key": "recursive", "label": "含子目录", "type": "check", "default": True},
            {"key": "outdir", "label": "另存目录", "type": "path",
             "placeholder": "留空则就地覆盖原文件"},
            {"key": "ccw", "label": "逆时针转正（转出来是倒立时用）", "type": "check",
             "default": False},
            {"key": "dry", "label": "预演（不真的转）", "type": "check", "default": True},
        ],
        "build": _build_pdf_upright,
        "result": {
            "kind": "table",
            "columns": ["文件", "页数", "尺寸", "结论"],
            "parse": _parse_pdf_rows,
            "summary": _pdf_summary,
        },
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
        "result": {
            "kind": "table",
            "columns": ['时间', '级别', '消息'],
            "parse": _parse_watch_rows,
            "summary": _watch_summary,
        },
    },
}


def has_form(tool_id):
    return tool_id in SPECS


# ---------------------------------------------------------------- 控件


def _hide_console(proc):
    """让 QProcess 启动的子进程**不弹控制台窗口**。

    面板是 GUI 程序（windowed exe），它启动的 python.exe 是控制台程序。
    Windows 看到父进程没有控制台，就会给子进程新分配一个并弹出来。

    **PySide6 没有暴露 `setCreateProcessArgumentsModifier`**，所以 Qt 层的
    定制走不通。但 Qt 自己的 QProcess 在 Windows 上默认就用 `CREATE_NO_WINDOW`
    起子进程（管道模式尤其如此），所以这里实际上无需干预 —— 保留这个函数
    是为了将来 PySide6 补上这个 API 时能直接生效，也为了把「不弹窗」这件事
    写在明处，别让下一个人以为没人管。

    真正会弹窗的是**工具内部**再开的孙进程（git / cmd / python），
    那些在各自的工具脚本里用 `creationflags=CREATE_NO_WINDOW` 处理过了。
    """
    modifier = getattr(proc, "setCreateProcessArgumentsModifier", None)
    if modifier is None:
        # PySide6 没暴露这个 API：Qt 默认已用 CREATE_NO_WINDOW，无需干预
        return
    if os.name != "nt":
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flags:
        return

    def apply(args):
        args["creationflags"] = args.get("creationflags", 0) | flags

    modifier(apply)


class FormPanel(QtWidgets.QWidget):
    """一张表单 + 执行按钮 + 结果卡片。"""

    status_changed = QtCore.Signal(str)

    def __init__(self, tool_id, tool, parent=None):
        super().__init__(parent)
        self.tool_id = tool_id
        self.tool = tool
        self.spec = SPECS[tool_id]
        self.widgets = {}
        self.rows = {}
        self.proc = None
        self._buffer = ""
        self._saved_widths = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        desc = QtWidgets.QLabel(self.spec["desc"])
        desc.setObjectName("PageDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        form_box = None
        form = None
        if self.spec["fields"]:
            form_box = QtWidgets.QFrame()
            form_box.setObjectName("Card")
            form = QtWidgets.QGridLayout(form_box)
            form.setContentsMargins(18, 16, 18, 16)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)
        row = 0
        for field in (self.spec["fields"] if form is not None else []):
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
        if form_box is not None:
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

        lay.addWidget(self._build_result_box(), 1)

        self._sync_visibility()

    # ---------- 结果区 ----------

    def _build_result_box(self):
        """结果区是一张卡片：标题 + 摘要 + 复制按钮 + 表格或文本。

        不做成终端的样子：结果要像界面里的信息，而不是命令行的回显。
        """
        box = QtWidgets.QFrame()
        box.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 11, 14, 12)
        lay.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        self.result_title = QtWidgets.QLabel("执行结果")
        self.result_title.setObjectName("CardTitle")
        head.addWidget(self.result_title)
        self.result_summary = QtWidgets.QLabel("")
        self.result_summary.setObjectName("CardDesc")
        head.addWidget(self.result_summary, 1)
        copy_btn = QtWidgets.QPushButton("复制")
        copy_btn.setObjectName("Secondary")
        copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_result)
        head.addWidget(copy_btn)
        lay.addLayout(head)

        self.result = self.spec.get("result") or {}
        self.table = None
        self.out = None
        if self.result.get("kind") == "table":
            self.table = QtWidgets.QTableWidget()
            self.table.setObjectName("ResultTable")
            columns = self.result.get("columns", [])
            self.table.setColumnCount(len(columns))
            self.table.setHorizontalHeaderLabels(columns)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.verticalHeader().setVisible(False)
            self.table.setAlternatingRowColors(True)
            header = self.table.horizontalHeader()
            # Interactive：用户可以拖动列边界自由调列宽。
            # ResizeToContents 会锁死列宽（拖不动），Stretch 同样不能手动调。
            header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
            header.setMinimumSectionSize(48)
            # 记忆里存了列宽的列，用记录的宽度；没存的按内容给一个合适的初值。
            # 全部是 Interactive，这样每一列都能拖。
            self._saved_widths = self._load_column_widths()
            header.sectionResized.connect(self._on_column_resized)
            self._apply_column_widths()
            lay.addWidget(self.table)
        else:
            self.out = QtWidgets.QPlainTextEdit()
            self.out.setObjectName("FormOutput")
            self.out.setReadOnly(True)
            self.out.setPlaceholderText("执行后结果显示在这里")
            lay.addWidget(self.out)
        return box

    def _show_result(self, text):
        """把子进程输出转成界面上的结果。"""
        cleaned = _clean_output(text)
        if self.table is not None:
            rows = self.result.get("parse", lambda _t: [])(cleaned)
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    if c < self.table.columnCount():
                        self.table.setItem(
                            r, c, QtWidgets.QTableWidgetItem(str(val)))
            self._apply_column_widths()
            summary = self.result.get("summary")
            if rows:
                self.result_summary.setText(summary(rows) if summary else "")
            else:
                # 没解析出结构化行时，至少把工具的结论那句话显示出来
                self.result_summary.setText(_fallback_summary(cleaned))
        else:
            self.out.setPlainText(cleaned)
            lines = cleaned.splitlines()
            self.result_summary.setText("{} 行".format(len(lines)) if lines else "无输出")

    # ---------- 列宽 ----------

    def _load_column_widths(self):
        """读回上次记住的列宽。"""
        try:
            import panel_config as _cfg
            data = _cfg.load()
            if not data.get("remember_columns", True):
                return None
            widths = (data.get("columns") or {}).get(self.tool_id)
            if isinstance(widths, list) and len(widths) == self.table.columnCount():
                return [int(w) for w in widths]
        except Exception:  # noqa: BLE001 —— 读配置失败不该影响显示
            pass
        return None

    def _apply_column_widths(self):
        """给每列一个合适的初始宽度。

        优先用用户记住的宽度；没有就按内容宽度算。所有列都是 Interactive，
        用户随时能拖动边界调整。
        """
        if self.table is None:
            return
        header = self.table.horizontalHeader()
        count = self.table.columnCount()
        if count == 0:
            return

        metrics = self.table.fontMetrics()
        widths = self._saved_widths or []
        if len(widths) != count:
            widths = [0] * count

        for c in range(count):
            remembered = widths[c]
            if remembered > 0:
                header.resizeSection(c, remembered)
                continue
            if self.table.rowCount() == 0:
                # 还没数据，先按表头文字给个宽度，等有结果了再按内容细调
                head = self.table.horizontalHeaderItem(c)
                text = head.text() if head is not None else ""
                header.resizeSection(
                    c, min(520, max(72, metrics.horizontalAdvance(text) + 28)))
                continue
            # 按内容算：取该列最宽的一格，再留一点余量
            longest = 0
            for r in range(self.table.rowCount()):
                item = self.table.item(r, c)
                if item is None:
                    continue
                longest = max(longest, metrics.horizontalAdvance(item.text()))
            head = self.table.horizontalHeaderItem(c)
            if head is not None:
                longest = max(longest, metrics.horizontalAdvance(head.text()))
            header.resizeSection(c, min(520, max(72, longest + 28)))

    def _on_column_resized(self, index, _old, new):
        """用户拖动列边界后把宽度记下来。"""
        if self.table is None or index < 0:
            return
        count = self.table.columnCount()
        if index >= count or new <= 0:
            return
        try:
            import panel_config as _cfg
            data = _cfg.load()
            if not data.get("remember_columns", True):
                return
            store = data.setdefault("columns", {})
            widths = list(store.get(self.tool_id) or [])
            if len(widths) != count:
                widths = [0] * count
            widths[index] = int(new)
            store[self.tool_id] = widths
            _cfg.save(data)
        except Exception:  # noqa: BLE001 —— 存配置失败不影响使用
            pass

    def _copy_result(self):
        if self.table is not None:
            rows = []
            for r in range(self.table.rowCount()):
                rows.append("\t".join(
                    self.table.item(r, c).text() if self.table.item(r, c) else ""
                    for c in range(self.table.columnCount())))
            text = "\n".join(rows)
        else:
            text = self.out.toPlainText() if self.out is not None else ""
        QtWidgets.QApplication.clipboard().setText(text)
        self.result_summary.setText("已复制到剪贴板")

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

        # 破坏性操作二次确认：勾了「真正写入」这类字段才问
        if not self._confirm_dangerous(values):
            self.hint.setText("已取消")
            return

        script = core.SRC_ROOT / self.spec.get("script", self.tool["script"])
        if not script.is_file():
            self.hint.setText("找不到脚本：{}".format(self.tool["script"]))
            return

        args = self.spec["build"](values)
        program, argv = core.spawn_command(script, args)
        self._buffer = ""
        self._show_result("")
        self.hint.setText("运行中…")
        self.run_btn.setEnabled(False)
        self.stop_btn.show()
        self.status_changed.emit("执行中…")

        proc = QtCore.QProcess(self)
        proc.setProgram(program)
        proc.setArguments(argv)
        proc.setWorkingDirectory(str(script.parent))
        # QProcess 默认继承本进程环境；本进程是打包的 exe，环境里带着
        # PyInstaller 的 _MEIPASS / QT_PLUGIN_PATH —— 会让子解释器加载到
        # 版本不对的 DLL。换成清洗过的环境。
        qenv = QtCore.QProcessEnvironment()
        for key, value in core.child_env().items():
            qenv.insert(key, value)
        proc.setProcessEnvironment(qenv)
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        _hide_console(proc)
        proc.readyReadStandardOutput.connect(self._read_output)
        proc.finished.connect(self._finished)
        proc.errorOccurred.connect(self._failed)
        self.proc = proc
        proc.start()
        # 关掉子进程的 stdin：GUI 里没有终端可输入，任何 input() 会立刻拿到 EOF
        # 并走各自的「取消」分支。少了这一步，需要确认的工具会一直挂着不返回。
        proc.closeWriteChannel()

    def _confirm_dangerous(self, values):
        """勾了危险选项时先问一句。用户返回 False 就取消。

        危险字段都是「真正写入」「覆盖」「删除」这类，误点代价高。
        设置里可以关掉这个确认。
        """
        danger_fields = [f for f in self.spec["fields"] if f.get("danger")]
        if not danger_fields:
            return True
        triggered = [f for f in danger_fields
                     if values.get(f["key"]) not in (None, "", False, 0)]
        if not triggered:
            return True
        try:
            import panel_config as _cfg
            if not _cfg.load().get("confirm_danger", True):
                return True
        except Exception:  # noqa: BLE001 —— 读配置失败就当要确认
            pass
        labels = "、".join(f["label"] for f in triggered)
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("确认操作")
        box.setText("即将执行：{}".format(labels))
        box.setInformativeText("这一操作会真正修改文件或提交到仓库。")
        yes = box.addButton("执行", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        return box.clickedButton() is yes

    def _read_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = data.decode("utf-8", "replace")
        self._buffer += text
        self._show_result(self._buffer)

    def _finished(self, code, _status):
        self._read_output()
        self.hint.setText("完成" if code == 0 else "完成，但有错误（退出码 {}）".format(code))
        self.status_changed.emit("已完成" if code == 0 else "已完成（有错误）")
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
            self.status_changed.emit("已中止")
            self._cleanup()


def build(tool_id, tool):
    """给某个工具造面板。全部工具都有表单规格。"""
    if not has_form(tool_id):
        return None
    return FormPanel(tool_id, tool)
