#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
symbols.py — 笔记符号管理面板（交互式）

直接运行本脚本即进入数字面板，可多选（英文逗号分隔，如 1,3,5）：

    1. 设置笔记文件夹并扫描目录结构  设置根目录；扫描并记录目录结构（有哪些子文件夹、
                                      每个子文件夹包含哪些文件），与上次记录对比，
                                      只更新有差异的部分
    2. 显示子文件夹结构           按英文名排序并编号，输入编号（可多选）查看结构详情
    3. 提取各子文件夹的符号       收集子文件夹中模板没有的新符号，记入提取档案
    4. 回填提取的符号             先写入 structure.sty，再刷新 custom.cwl
    5. 检验并删除未使用的符号     检验各子文件夹正文未引用的符号，确认后删除
    6. 引入新的记号               向 [模块 VI] 插入定义：先选归属子段（代数 / 几何 /
                                  分析，可输入数字，也可新建子段），再写入模板、
                                  分发到各子文件夹，并自动刷新 custom.cwl
    7. 退出

配置文件：脚本同目录 symbols.conf（root / template / cwl），命令行参数优先。
提取档案：脚本同目录 symbols_extract.json（本机使用，不入版本控制）
          结构：{ "子文件夹": { "年-月-日": { "命令名": "定义行" } } }
结构档案：脚本同目录 notes_tree.json（记录目录结构，用于对比差异）

命令行模式（不进面板，便于批处理）：
    python symbols.py --all --write        回填 + 刷新补全 + 分发
    python symbols.py --cwl --write        只刷新 TeXStudio 补全
    python symbols.py --distribute --write 只分发
    python symbols.py --drop NAME --write  删除指定符号

维护提示：本脚本在根目录（本机运行）与 tex_note_manager 仓库（发布副本）
          各存一份，改完后请到 tex_note_manager 目录运行 commit.py 同步发布。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
CONF_NAME = "symbols.conf"
EXTRACT_NAME = "symbols_extract.json"
TREE_NAME = "notes_tree.json"

DEF_RE = re.compile(r"^[ \t]*\\(?:re)?newcommand\{\\([A-Za-z@]+)\}")
SEC_START = "[模块 VI]"
SEC_END = "[模块 VII]"
CMD_NAME_RE = re.compile(r"^[A-Za-z]+$")
# [模块 VI] 内的编号子段标记，如「% -------- 6.1 代数 --------」
# 要求带 x.y 编号，故不会误匹配「% ---- 射影空间 ----」这类三级标记。
SUB_SEC_RE = re.compile(r"^%[ \t]*-{3,}[ \t]*(\d+\.\d+)[ \t]+(.+?)[ \t]*-{3,}[ \t]*$")

AUTO_MARKERS = [
    "# ============ 自动生成段：structure.sty 数学符号 (symbols.py) ============",
    "# ============ 自动生成段：structure.sty 数学符号 (update_cwl.py) ============",
    "# Algebra symbols.",
]


# ================================================================ 基础 IO

def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def split_comment(line):
    """拆成 (代码, 注释)，注释指第一个未被转义的 % 之后的内容。"""
    for i, ch in enumerate(line):
        if ch == "%" and (i == 0 or line[i - 1] != "\\"):
            return line[:i].rstrip(), line[i + 1:].strip()
    return line.rstrip(), ""


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def today():
    return datetime.date.today().strftime("%Y-%m-%d")


def norm(line):
    return " ".join(line.split())


def backup(path, tag=None):
    """备份文件。structure.sty 不做备份（按用户要求，其改动可随时由模板重新分发）。"""
    if pathlib.Path(path).name == "structure.sty":
        return None
    name = f"{path.name}.bak-{tag or stamp()}"
    target = path.with_name(name)
    shutil.copy2(path, target)
    return target


# ================================================================ 配置

def load_config():
    conf = SCRIPT_DIR / CONF_NAME
    cfg = {}
    if conf.is_file():
        for line in read_text(conf).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                cfg[key.strip().lower()] = os.path.expandvars(value)
    return cfg, conf


def save_config(cfg, conf_path):
    lines = [
        "# symbols.py 配置",
        "# 每行格式：键 = 值  以 # 或 ; 开头的行是注释",
        "# 本文件含本机路径，已加入 .gitignore，不上传",
        "",
        "# 笔记根目录：其下每个含 structure.sty 的子目录都被视为一本笔记",
        f"root = {cfg.get('root', '')}",
        "",
        "# 符号来源（模板的 structure.sty）",
        f"template = {cfg.get('template', '')}",
        "",
        "# TeXStudio 补全文件（支持 %APPDATA% 等环境变量）",
        f"cwl = {cfg.get('cwl', '')}",
        "",
        "# 额外忽略的目录名（逗号分隔）：隐藏目录与下划线开头的目录已自动忽略",
        f"ignore = {cfg.get('ignore', '')}",
        "",
    ]
    write_text(conf_path, "\n".join(lines))


def default_cwl():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return str(pathlib.Path(appdata) / "texstudio" / "completion" / "user" / "custom.cwl")
    return str(SCRIPT_DIR / "custom.cwl")


def resolve_root(cli_root, cfg):
    if cli_root:
        return pathlib.Path(cli_root)
    if cfg.get("root"):
        return pathlib.Path(cfg["root"])
    parent = SCRIPT_DIR.parent
    try:
        subs = [d for d in parent.iterdir() if d.is_dir() and (d / "structure.sty").is_file()]
    except OSError:
        subs = []
    return parent if len(subs) >= 2 else SCRIPT_DIR


def resolve_template(cli_template, cfg):
    if cli_template:
        return pathlib.Path(cli_template)
    if cfg.get("template"):
        return pathlib.Path(cfg["template"])
    src = SCRIPT_DIR / ".cwl_source"
    if src.is_file():
        for line in read_text(src).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return pathlib.Path(os.path.expandvars(line))
    same = SCRIPT_DIR / "structure.sty"
    return same if same.is_file() else None


def resolve_cwl(cli_cwl, cfg):
    if cli_cwl:
        return pathlib.Path(cli_cwl)
    if cfg.get("cwl"):
        return pathlib.Path(cfg["cwl"])
    return pathlib.Path(default_cwl())


# ================================================================ 目录结构档案

COMPILED_SUFFIXES = (
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk",
    ".synctex.gz", ".synctex", ".bbl", ".blg", ".nav", ".snm", ".vrb",
    ".idx", ".ind", ".ilg", ".xdv", ".run.xml", ".pdf",
)


def is_compiled(name):
    """LaTeX 编译产物：不属于笔记的组成文件。"""
    lower = name.lower()
    return any(lower.endswith(s) for s in COMPILED_SUFFIXES)


def is_backup(name):
    """备份文件、编译产物与本工具自身的档案：不计入目录结构。"""
    if ".bak" in name or name.endswith("~"):
        return True
    if name in (CONF_NAME, EXTRACT_NAME, TREE_NAME):
        return True
    return is_compiled(name)


IGNORE_EXTRA = set()


def is_ignored_dir(name):
    """不参与扫描的目录：隐藏目录（.git）、下划线开头（__pycache__、_备份 等），
    以及 symbols.conf 中 ignore 项指定的名字。"""
    if name.startswith(".") or name.startswith("_"):
        return True
    return name in IGNORE_EXTRA


def count_files(base):
    """统计 base 下文件数，跳过忽略目录与备份文件。"""
    total = 0
    try:
        for item in base.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(base)
            if any(is_ignored_dir(part) for part in rel.parts):
                continue
            if is_backup(item.name):
                continue
            total += 1
    except OSError:
        pass
    return total


def scan_tree(root):
    """扫描根目录结构：子文件夹、顶层文件、子目录、文件总数。"""
    folders = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or is_ignored_dir(d.name):
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        top_files = sorted(f.name for f in entries
                           if f.is_file() and not is_backup(f.name))
        subdirs = {}
        for f in entries:
            if f.is_dir() and not is_ignored_dir(f.name):
                subdirs[f.name] = count_files(f)
        folders[d.name] = {
            "note": (d / "structure.sty").is_file(),
            "top_files": top_files,
            "subdirs": subdirs,
            "file_count": count_files(d),
        }
    return {
        "scanned": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "folders": folders,
    }


def load_tree():
    path = SCRIPT_DIR / TREE_NAME
    if not path.is_file():
        return {}, path
    try:
        return json.loads(read_text(path)), path
    except Exception:
        print("  ! 目录结构档案损坏，按空处理")
        return {}, path


def save_tree(tree, path):
    write_text(path, json.dumps(tree, ensure_ascii=False, indent=2) + "\n")


def compare_tree(old, new):
    """返回 (新增文件夹, 消失文件夹, 有变化的文件夹列表)。"""
    old_f = old.get("folders", {})
    new_f = new.get("folders", {})
    added = sorted(set(new_f) - set(old_f))
    removed = sorted(set(old_f) - set(new_f))
    changed = []
    for name in sorted(set(old_f) & set(new_f)):
        o, n = old_f[name], new_f[name]
        add_f = sorted(set(n.get("top_files", [])) - set(o.get("top_files", [])))
        del_f = sorted(set(o.get("top_files", [])) - set(n.get("top_files", [])))
        if (add_f or del_f
                or o.get("file_count") != n.get("file_count")
                or o.get("subdirs") != n.get("subdirs")):
            changed.append((name, add_f, del_f, o.get("file_count"), n.get("file_count")))
    return added, removed, changed


# ================================================================ 提取档案

def load_extract():
    path = SCRIPT_DIR / EXTRACT_NAME
    if not path.is_file():
        return {}, path
    try:
        return json.loads(read_text(path)), path
    except Exception:
        print("  ! 提取档案损坏，按空处理")
        return {}, path


def save_extract(data, path):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# ================================================================ 符号解析

def parse_symbols(sty_path):
    """返回 {命令名: (原行, 代码, 注释)}，范围 [模块 VI] 到 [模块 VII]。"""
    text = read_text(sty_path)
    start = text.find(SEC_START)
    seg = text[start:] if start != -1 else text
    end = seg.find(SEC_END)
    if end != -1:
        seg = seg[:end]
    out = {}
    for line in seg.splitlines():
        m = DEF_RE.match(line)
        if not m:
            continue
        code, comment = split_comment(line)
        out[m.group(1)] = (line.rstrip(), code, comment)
    return out


def _module_bounds(lines):
    """返回 [模块 VI] 与 [模块 VII] 的行索引 (start, end)；结构异常返回 None。"""
    start = next((i for i, l in enumerate(lines) if SEC_START in l), None)
    end = next((i for i, l in enumerate(lines) if SEC_END in l), None)
    if start is None or end is None or end <= start:
        return None
    return start, end


def _section_marks(lines, start, end):
    """在 lines[start:end] 内查找编号子段，返回 [(编号, 标题, 标题行索引)]。"""
    marks = []
    for i in range(start, end):
        m = SUB_SEC_RE.match(lines[i].rstrip("\r\n"))
        if m:
            marks.append((m.group(1), m.group(2), i))
    return marks


def parse_sections(sty_path):
    """返回 [模块 VI] 内的编号子段：[(编号, 标题, 标题行索引, 段结束行索引)]。"""
    lines = read_text(sty_path).splitlines(keepends=True)
    bounds = _module_bounds(lines)
    if bounds is None:
        return []
    start, end = bounds
    marks = _section_marks(lines, start, end)
    out = []
    for k, (num, title, i) in enumerate(marks):
        nxt = marks[k + 1][2] if k + 1 < len(marks) else end
        out.append((num, title, i, nxt))
    return out


def next_section_number(sections):
    """按已有子段编号递增，返回新子段应使用的编号（如 6.3 -> 6.4）。"""
    if not sections:
        return "6.1"
    major, minor = sections[-1][0].split(".")
    return f"{major}.{int(minor) + 1}"


def find_notes(root, template, only=None, exclude=None):
    notes = []
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        print(f"  无法读取目录 {root}：{exc}")
        return notes
    for d in entries:
        if not d.is_dir() or is_ignored_dir(d.name):
            continue
        sty = d / "structure.sty"
        if not sty.is_file():
            continue
        try:
            if template is not None and sty.resolve() == template.resolve():
                continue
        except OSError:
            pass
        if only and d.name not in only:
            continue
        if exclude and d.name in exclude:
            continue
        notes.append((d.name, sty))
    return notes


def diff_notes(template_symbols, notes):
    """比对各笔记与模板，返回 additions / comments / conflicts / missing。"""
    additions, comments, conflicts, missing = {}, {}, [], {}
    for note, sty in notes:
        try:
            symbols = parse_symbols(sty)
        except Exception as exc:
            print(f"  跳过 {note}：解析失败（{exc}）")
            continue
        for name, (line, code, _) in symbols.items():
            if name in template_symbols:
                tline, tcode, _ = template_symbols[name]
                if norm(code) != norm(tcode):
                    conflicts.append((name, note, line, tline))
                elif norm(line) != norm(tline):
                    if name in comments and norm(comments[name]["line"]) != norm(line):
                        conflicts.append((name, note, line, comments[name]["line"]))
                        continue
                    comments.setdefault(name, {"line": line, "sources": []})["sources"].append(note)
                continue
            if name in additions:
                if norm(line) != norm(additions[name]["line"]):
                    conflicts.append((name, note, line, additions[name]["line"]))
                else:
                    additions[name]["sources"].append(note)
            else:
                additions[name] = {"line": line, "sources": [note]}
        for name in template_symbols:
            if name not in symbols:
                missing.setdefault(name, []).append(note)
    return {"additions": additions, "comments": comments,
            "conflicts": conflicts, "missing": missing}


def rewrite_comment(line, marker):
    """把一行重新拼上注释标记，返回新行。"""
    code, comment = split_comment(line)
    if comment:
        return f"{code}    % {comment} {marker}"
    return f"{code}    % {marker}"


def insert_into_symbol_lib(sty_path, new_lines, replace_map=None, section=None):
    """向 [模块 VI] 插入 new_lines；replace_map 为 {命令名: 新行}。

    section=None              -> 追加到 [模块 VI] 末尾（默认）
    section=("num", "6.3")    -> 插到编号 6.3 的子段内最后一个定义之后
    section=("new", "6.4 拓扑") -> 在 [模块 VI] 末尾新建该子段并在其中写入
    """
    text = read_text(sty_path)
    lines = text.splitlines(keepends=True)
    bounds = _module_bounds(lines)
    if bounds is None:
        return False
    start, end = bounds
    if replace_map:
        for i in range(start, end):
            m = DEF_RE.match(lines[i])
            if m and m.group(1) in replace_map:
                keep = "\r\n" if lines[i].endswith("\r\n") else "\n"
                lines[i] = replace_map[m.group(1)] + keep
    eol = "\r\n" if "\r\n" in text else "\n"
    payload = [(l.rstrip("\r\n") + eol) for l in new_lines]

    if section and section[0] == "num" and payload:
        marks = _section_marks(lines, start, end)
        hit = next((m for m in marks if m[0] == section[1]), None)
        if hit is None:
            return False
        idx = marks.index(hit)
        sec_end = marks[idx + 1][2] if idx + 1 < len(marks) else end
        defs = [i for i in range(hit[2], sec_end) if DEF_RE.match(lines[i])]
        at = (max(defs) if defs else hit[2]) + 1
    elif section and section[0] == "new" and payload:
        at = end
        while at - 1 > start and lines[at - 1].lstrip().startswith("% ==="):
            at -= 1
        while at - 1 > start and not lines[at - 1].strip():
            at -= 1
        # 前置一个空行；原有空行留在 payload 之后，保持模块 VI 的收尾风格
        payload = [eol, f"% -------- {section[1]} --------" + eol] + payload
    else:
        defs = [i for i in range(start, end) if DEF_RE.match(lines[i])]
        at = (max(defs) + 1) if defs else end

    if not payload:
        write_text(sty_path, "".join(lines))
        return True
    lines = lines[:at] + payload + lines[at:]
    write_text(sty_path, "".join(lines))
    return True


def distribute(template_path, notes, quiet=False):
    """模板 -> 各笔记（逐个备份）。返回同步数量。"""
    template_text = read_text(template_path)
    changed = []
    for note, sty in notes:
        try:
            if read_text(sty) != template_text:
                changed.append((note, sty))
        except Exception:
            continue
    if not changed:
        if not quiet:
            print(f"  已一致，无需同步（共 {len(notes)} 个）。")
        return 0
    tag = stamp()
    for note, sty in changed:
        backup(sty, tag)
        write_text(sty, template_text)
        if not quiet:
            print(f"  [已同步] {note}")
    return len(changed)


def refresh_cwl(template_path, cwl_path):
    symbols = parse_symbols(template_path)
    entries = []
    for name in sorted(symbols):
        _, _, comment = symbols[name]
        entries.append(r"\{}#m {}".format(name, comment) if comment else r"\{}#m".format(name))
    section = "\n".join([AUTO_MARKERS[0]] + entries)

    cwl = pathlib.Path(cwl_path)
    content = read_text(cwl) if cwl.is_file() else ""
    head = content
    for marker in AUTO_MARKERS:
        if marker in content:
            head = content.split(marker)[0]
            break
    eol = "\r\n" if "\r\n" in content else ("\n" if content else os.linesep)
    cwl.parent.mkdir(parents=True, exist_ok=True)
    backup(cwl) if cwl.is_file() else None
    write_text(cwl, head.rstrip() + eol + eol + section + eol)
    print(f"  已刷新补全：{len(symbols)} 个符号 -> {cwl}")
    return len(symbols)


# ================================================================ 输入辅助

def clear_screen():
    """清屏，使画面只保留当前选项的内容。"""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def ask(prompt, default=None, required=True):
    while True:
        tip = prompt
        if default:
            tip += f"（回车保持 {default}）"
        elif not required:
            tip += "（可选，回车跳过）"
        try:
            value = input(f"  {tip}：").strip()
        except EOFError:
            # 输入流已结束（Ctrl+D 或管道耗尽）：向上抛出，由面板统一退出，
            # 避免「读出空串 -> 重新提问」造成的死循环。
            print()
            raise
        if value:
            return value
        if default:
            return default
        if not required:
            return ""
        print("  ! 该项为必填，请重新输入。")


def ask_yes_no(prompt):
    while True:
        try:
            value = input(f"  {prompt} (Y/N)：").strip().upper()
        except EOFError:
            print()
            raise
        if value in ("Y", "YES", "是"):
            return True
        if value in ("N", "NO", "否"):
            return False
        print("  ! 请输入 Y 或 N。")


def parse_choices(text, max_n):
    parts = [p for p in re.split(r"[,，、\s]+", text.strip()) if p]
    if not parts:
        return None, "没有识别到任何选项"
    out = []
    for p in parts:
        if not p.isdigit():
            return None, f"无法识别：{p}"
        n = int(p)
        if not 1 <= n <= max_n:
            return None, f"选项超出范围：{n}"
        if n not in out:
            out.append(n)
    return out, None


# ================================================================ 各选项动作

def action_setup(ctx):
    """1. 设置笔记文件夹并扫描目录结构（记录结构，只更新有差异的部分）。"""
    print("\n[1] 设置笔记文件夹并扫描目录结构")
    current = str(ctx["root"])
    path = ask("请输入笔记文件夹路径", default=current)
    target = pathlib.Path(path.strip('"').strip("'"))
    if not target.is_dir():
        print(f"  ! 目录不存在：{target}")
        return
    ctx["root"] = target
    if str(target) != current:
        ctx["cfg"]["root"] = str(target)
        save_config(ctx["cfg"], ctx["conf"])
        print(f"  已保存笔记根目录：{target}")
    else:
        print(f"  笔记根目录保持：{target}")

    tree = scan_tree(target)
    old, archive = load_tree()
    added, removed, changed = compare_tree(old, tree)

    print(f"\n  目录结构（{len(tree['folders'])} 个子文件夹）：")
    for name in sorted(tree["folders"]):
        info = tree["folders"][name]
        tag = "笔记" if info["note"] else "非笔记"
        print(f"    [{tag}] {name}")
        print(f"        顶层文件 {len(info['top_files'])} 个，"
              f"子目录 {len(info['subdirs'])} 个，合计 {info['file_count']} 个文件")
        if info["subdirs"]:
            brief = "、".join(f"{k}({v})" for k, v in list(info["subdirs"].items())[:4])
            more = " …" if len(info["subdirs"]) > 4 else ""
            print(f"        {brief}{more}")

    if not old:
        print("\n  首次扫描，已建立目录结构档案。")
    elif not (added or removed or changed):
        print("\n  目录结构与上次记录一致，无需更新。")
    else:
        print("\n  与上次记录对比，发现以下差异：")
        for name in added:
            print(f"    [新增] {name}")
        for name in removed:
            print(f"    [消失] {name}")
        for name, add_f, del_f, old_n, new_n in changed:
            print(f"    [变化] {name}：文件数 {old_n} -> {new_n}")
            if add_f:
                shown = "、".join(add_f[:8]) + (" …" if len(add_f) > 8 else "")
                print(f"        新增文件：{shown}")
            if del_f:
                shown = "、".join(del_f[:8]) + (" …" if len(del_f) > 8 else "")
                print(f"        消失文件：{shown}")
        print("  正在更新有差异的部分……")

    save_tree(tree, archive)
    print(f"  目录结构档案已更新：{archive.name}")

    notes = find_notes(target, ctx["template"])
    if notes:
        template_symbols = parse_symbols(ctx["template"])
        diff = diff_notes(template_symbols, notes)
        if diff["additions"]:
            names = "、".join("\\" + k for k in sorted(diff["additions"]))
            print(f"  提示：另有 {len(diff['additions'])} 个新符号待提取（{names}），见选项 3")


def list_subfolders(root):
    """按英文名称排序列出根目录下的子文件夹。"""
    items = []
    try:
        for d in root.iterdir():
            if d.is_dir() and not is_ignored_dir(d.name):
                items.append(d)
    except OSError:
        pass
    return sorted(items, key=lambda p: p.name)


def print_subtree(path, prefix=""):
    """递归打印子文件夹树（只列文件夹），直到没有子文件夹为止。"""
    try:
        subs = [d for d in sorted(path.iterdir())
                if d.is_dir() and not is_ignored_dir(d.name)]
    except OSError:
        return
    for i, d in enumerate(subs):
        last = (i == len(subs) - 1)
        branch = "└─ " if last else "├─ "
        print(f"{prefix}{branch}{d.name}/  （{count_files(d)} 个文件）")
        print_subtree(d, prefix + ("    " if last else "│   "))


def show_folder_detail(path):
    """打印一个子文件夹的结构详情（含递归子文件夹树）。"""
    print(f"\n  ══ {path.name} ══")
    try:
        entries = sorted(path.iterdir())
    except OSError as exc:
        print(f"    ! 无法读取：{exc}")
        return
    files = [e for e in entries
             if e.is_file() and not e.name.startswith(".") and not is_backup(e.name)]
    compiled = [e for e in entries
                if e.is_file() and not e.name.startswith(".") and is_compiled(e.name)]
    dirs = [e for e in entries if e.is_dir() and not is_ignored_dir(e.name)]
    if files:
        print(f"    顶层文件 {len(files)} 个：")
        for f in files:
            try:
                size = f.stat().st_size
                print(f"      {f.name}  ({size:,} B)")
            except OSError:
                print(f"      {f.name}")
    else:
        print("    顶层文件：无")
    if compiled:
        print(f"    （另有 {len(compiled)} 个编译产物已忽略："
              f"{'、'.join(e.name for e in compiled[:6])}"
              f"{' …' if len(compiled) > 6 else ''}）")

    if dirs:
        print("    子文件夹树：")
        print_subtree(path)
    else:
        print("    （无子文件夹）")


def action_show_folder(ctx):
    """2. 显示子文件夹结构（按英文名排序编号，可多选查看）。"""
    print("\n[2] 显示子文件夹结构")
    folders = list_subfolders(ctx["root"])
    if not folders:
        print(f"  ! {ctx['root']} 下未发现子文件夹。")
        return
    print(f"  笔记根目录：{ctx['root']}")
    for i, d in enumerate(folders, 1):
        tag = "笔记" if (d / "structure.sty").is_file() else "非笔记"
        print(f"    【{i}】{d.name}    [{tag}]")

    try:
        raw = input("  请输入编号（可多选，英文逗号分隔；直接回车返回）：").strip()
    except EOFError:
        return
    if not raw:
        return
    choices, err = parse_choices(raw, len(folders))
    if err:
        print(f"  ! 输入有误：{err}")
        return
    if not choices:
        return
    for idx in choices:
        show_folder_detail(folders[idx - 1])


def action_extract(ctx):
    """2. 提取各子文件夹的符号，记入提取档案。"""
    print("\n[3] 提取各子文件夹的符号")
    notes = find_notes(ctx["root"], ctx["template"])
    if not notes:
        print("  ! 未扫描到子文件夹。")
        return {}
    template_symbols = parse_symbols(ctx["template"])
    diff = diff_notes(template_symbols, notes)
    additions = diff["additions"]
    if not additions:
        print("  没有可提取的新符号（各子文件夹与模板一致）。")
        return {}

    data, path = load_extract()
    day = today()
    total = 0
    for note in sorted({s for info in additions.values() for s in info["sources"]}):
        bucket = data.setdefault(note, {}).setdefault(day, {})
        for name in sorted(additions):
            if note not in additions[name]["sources"]:
                continue
            bucket[name] = additions[name]["line"]
            total += 1
        print(f"  [{note}] {day} 提取 {len(bucket)} 个符号")
    save_extract(data, path)
    print(f"  已写入提取档案：{path.name}（本次合计 {total} 条）")
    return additions


def action_backfill(ctx):
    """3. 回填提取的符号：先 structure.sty，再 custom.cwl。"""
    print("\n[4] 回填提取的符号")
    data, path = load_extract()
    pending = {note: days for note, days in data.items() if any(days.values())}
    if not pending:
        print("  ! 尚无提取记录。")
        if ask_yes_no("是否现在提取各子文件夹的符号？"):
            action_extract(ctx)
            data, path = load_extract()
            pending = {note: days for note, days in data.items() if any(days.values())}
        if not pending:
            print("  已跳过回填。")
            return

    template_symbols = parse_symbols(ctx["template"])
    new_lines, replace_map, skipped = [], {}, []
    for note in sorted(pending):
        for day in sorted(pending[note]):
            marker = f"提取自 {note}-{day}"
            for name in pending[note][day]:
                line = pending[note][day][name]
                if name in template_symbols:
                    tline = template_symbols[name][0]
                    if marker not in tline:
                        replace_map[name] = rewrite_comment(line, marker)
                    else:
                        skipped.append(name)
                    continue
                new_lines.append(rewrite_comment(line, marker))

    if not new_lines and not replace_map:
        print("  提取档案中的符号均已在模板中，无需回填。")
    else:
        backup(ctx["template"])
        ok = insert_into_symbol_lib(ctx["template"], new_lines, replace_map)
        if not ok:
            print("  ! 模板结构异常，已中止。")
            return
        print(f"  已写入模板 structure.sty：新增 {len(new_lines)} 个，"
              f"补注来源 {len(replace_map)} 个")
        notes = find_notes(ctx["root"], ctx["template"])
        n = distribute(ctx["template"], notes, quiet=False)
        if n == 0:
            print("  各子文件夹均已包含这些符号。")
    if skipped:
        print(f"  （{len(skipped)} 个符号已标注过来源，未重复处理）")

    refresh_cwl(ctx["template"], ctx["cwl"])


def choose_symbols_to_remove(candidates):
    """让用户选择要删除的符号：逐项确认，或批量按编号多选。返回选中的符号列表。"""
    print(f"\n  可安全删除的符号（所有子文件夹正文均未引用）：{len(candidates)} 个")
    for i, name in enumerate(candidates, 1):
        print(f"    【{i}】\\{name}")
    print()
    print("  删除方式：")
    print("    1. 逐项确认删除（逐个符号询问 Y/N）")
    print("    2. 批量选择删除（输入编号，可多选，英文逗号分隔）")
    print("    0. 取消，不删除")

    while True:
        try:
            choice = input("  请选择（0/1/2，直接回车取消）：").strip()
        except EOFError:
            return []
        if choice in ("", "0"):
            return []
        if choice == "1":
            picked = []
            for name in candidates:
                if ask_yes_no(f"    删除 \\{name} ？"):
                    picked.append(name)
                else:
                    print("      -> 保留")
            return picked
        if choice == "2":
            try:
                raw = input("  请输入要删除的编号（可多选，英文逗号分隔）：").strip()
            except EOFError:
                return []
            if not raw:
                return []
            idxs, err = parse_choices(raw, len(candidates))
            if err:
                print(f"    ! 输入有误：{err}")
                continue
            return [candidates[i - 1] for i in idxs]
        print("    ! 请输入 0、1 或 2。")


def action_unused(ctx):
    """5. 检验并删除未使用的符号。"""
    print("\n[5] 检验并删除未使用的符号")
    notes = find_notes(ctx["root"], ctx["template"])
    if not notes:
        print("  ! 未扫描到子文件夹。")
        return

    per_note = {}
    for note, sty in notes:
        try:
            symbols = parse_symbols(sty)
        except Exception:
            continue
        chunks = []
        main = sty.parent / "main.tex"
        if main.is_file():
            chunks.append(read_text(main))
        content = sty.parent / "Content"
        if content.is_dir():
            for tex in sorted(content.rglob("*.tex")):
                try:
                    chunks.append(read_text(tex))
                except Exception:
                    pass
        blob = "\n".join(chunks)
        unused = []
        for name in symbols:
            if not re.search(r"\\" + re.escape(name) + r"(?![A-Za-z])", blob):
                unused.append(name)
        per_note[note] = unused

    print("  各子文件夹正文未引用的符号：")
    for note in sorted(per_note):
        names = sorted(per_note[note])
        if names:
            print(f"    [{note}] {len(names)} 个：")
            for n in names:
                print(f"        \\{n}")
        else:
            print(f"    [{note}] 无")

    common = None
    for names in per_note.values():
        s = set(names)
        common = s if common is None else (common & s)
    common = sorted(common or [])
    if not common:
        print("\n  没有「所有子文件夹都未使用」的符号，无需删除。")
        return

    picked = choose_symbols_to_remove(common)
    if not picked:
        print("\n  已取消，未删除任何符号。")
        return

    lines = read_text(ctx["template"]).splitlines(keepends=True)
    keep_lines, removed = [], []
    for line in lines:
        m = DEF_RE.match(line)
        if m and m.group(1) in picked:
            removed.append(m.group(1))
            continue
        keep_lines.append(line)
    if not removed:
        print("  模板中未找到这些符号。")
        return

    write_text(ctx["template"], "".join(keep_lines))
    print(f"\n  已从符号库删除 {len(removed)} 个符号：")
    for n in removed:
        print(f"      \\{n}")
    distribute(ctx["template"], notes, quiet=False)
    refresh_cwl(ctx["template"], ctx["cwl"])


def choose_section(sections):
    """选择新记号的归属子段。返回 (insert_into_symbol_lib 的 section 参数, 位置描述)。"""
    print()
    print("  归属子段（[模块 VI] 数学符号定义库）：")
    for idx, (num, title, _, _) in enumerate(sections, 1):
        print(f"    {idx}. {num} {title}")
    new_idx = len(sections) + 1
    print(f"    {new_idx}. 新建子段")
    print("    0. 不分段，直接追加到 [模块 VI] 末尾")
    while True:
        try:
            raw = input("  请选择：").strip()
        except EOFError:
            print()
            raise
        if raw in ("", "0"):
            return None, "末尾（未分段）"
        if not raw.isdigit():
            print("  ! 请输入数字。")
            continue
        n = int(raw)
        if 1 <= n <= len(sections):
            num, title, _, _ = sections[n - 1]
            return ("num", num), f"{num} {title}（段内末尾）"
        if n == new_idx:
            default_num = next_section_number(sections)
            num = ask("新子段编号", default=default_num)
            title = ask("新子段标题（如 拓扑）")
            return ("new", f"{num} {title}"), f"新建子段 {num} {title}"
        print(f"  ! 选项超出范围（0-{new_idx}）。")


def action_add(ctx):
    """6. 引入新的记号（交互录入，规则同 LaTeX 的 \\newcommand）。"""
    print("\n[6] 引入新的记号")
    print("  说明：命令名只允许字母；定义不能为空；注释可选。")

    name = ""
    overwrite = False
    while not name:
        raw = ask("命令名（不含反斜杠，必填）")
        if not raw:
            continue
        candidate = raw.lstrip("\\")
        if not CMD_NAME_RE.match(candidate):
            print("  ! 命令名只允许英文字母（与 LaTeX 规则一致），请重新输入。")
            continue
        template_symbols = parse_symbols(ctx["template"])
        if candidate in template_symbols:
            print(f"  ! 命令 \\{candidate} 已存在：{template_symbols[candidate][0]}")
            if not ask_yes_no("  是否覆盖它的定义？"):
                continue
            overwrite = True
        name = candidate

    definition = ""
    while not definition:
        raw = ask("定义（必填，例如 \\operatorname{Orb}）")
        if not raw:
            print("  ! 定义为必填，请重新输入。")
            continue
        if raw.count("{") != raw.count("}"):
            print("  ! 花括号不配对，请重新输入。")
            continue
        definition = raw.strip()

    comment = ask("注释", required=False)

    line = f"\\newcommand{{\\{name}}}{{{definition}}}"
    if comment:
        line += f"    % {comment}"

    if overwrite:
        section, where = None, "原位置（覆盖已有定义）"
    else:
        section, where = choose_section(parse_sections(ctx["template"]))

    notes = find_notes(ctx["root"], ctx["template"])
    if not notes:
        print("  ! 未扫描到子文件夹，已中止。")
        return
    backup(ctx["template"])
    ok = insert_into_symbol_lib(
        ctx["template"],
        [] if overwrite else [line],
        replace_map={name: line} if overwrite else None,
        section=section,
    )
    if not ok:
        print("  ! 模板结构异常（未找到指定子段？），已中止。")
        return
    print()
    print(f"  已写入模板 [模块 VI]：{where}")
    print(f"    {line}")
    n = distribute(ctx["template"], notes, quiet=True)
    print(f"  已同步到 {n} 个子文件夹的 structure.sty")
    refresh_cwl(ctx["template"], ctx["cwl"])
    print("  提示：重启 TeXStudio 后即可补全（编辑器只在启动时读取补全文件）。")


# ================================================================ 面板

def show_panel(ctx):
    notes = find_notes(ctx["root"], ctx["template"])
    data, _ = load_extract()
    pending = sum(len(v) for days in data.values() for v in days.values())

    print()
    print("=" * 62)
    print("  笔记符号管理面板")
    print("=" * 62)
    print(f"  笔记根目录：{ctx['root']}")
    print(f"  符号来源　：{ctx['template']}")
    print(f"  补全文件　：{ctx['cwl']}")
    print(f"  子文件夹　：{len(notes)} 个")
    if pending:
        print(f"  待回填　　：提取档案中累计 {pending} 条记录")
    print("-" * 62)
    print("  1. 设置笔记文件夹并扫描目录结构（记录结构，只更新有差异的部分）")
    print("  2. 显示子文件夹结构（按英文名排序编号，可多选查看）")
    print("  3. 提取各子文件夹的符号")
    print("  4. 回填提取的符号（先 structure.sty，再 custom.cwl）")
    print("  5. 检验并删除未使用的符号")
    print("  6. 引入新的记号（选归属子段，自动刷新补全）")
    print("  7. 退出")
    print("-" * 62)
    print("  可多选，用英文逗号分隔（如 1,3,5）")


def run_panel(ctx):
    clear_screen()
    while True:
        show_panel(ctx)
        try:
            raw = input("\n  请输入选项：")
        except EOFError:
            print("\n  已退出。")
            return
        raw = raw.strip()
        if not raw:
            continue
        choices, err = parse_choices(raw, 7)
        if err:
            print(f"  ! 输入有误：{err}")
            try:
                input("  按回车继续…")
            except EOFError:
                return
            continue
        if 7 in choices:
            print("\n  已退出。")
            return
        for c in choices:
            clear_screen()
            try:
                if c == 1:
                    action_setup(ctx)
                elif c == 2:
                    action_show_folder(ctx)
                elif c == 3:
                    action_extract(ctx)
                elif c == 4:
                    action_backfill(ctx)
                elif c == 5:
                    action_unused(ctx)
                elif c == 6:
                    action_add(ctx)
            except KeyboardInterrupt:
                print("\n  已中断当前操作。")
            except EOFError:
                print("\n  输入已结束，已退出。")
                return
        try:
            input("\n  按回车返回面板…")
        except EOFError:
            return
        clear_screen()


# ================================================================ 命令行

def cli_run(args, ctx):
    notes = find_notes(ctx["root"], ctx["template"])
    if not notes:
        print("未扫描到子文件夹。")
        return 1
    template_symbols = parse_symbols(ctx["template"])
    diff = diff_notes(template_symbols, notes)

    print(f"笔记根目录：{ctx['root']}")
    print(f"符号来源　：{ctx['template']}")
    print(f"子文件夹　：{len(notes)} 个")
    print(f"模板符号　：{len(template_symbols)} 个")
    if diff["additions"]:
        print(f"新增待回填：{'、'.join('\\' + k for k in sorted(diff['additions']))}")
    if diff["comments"]:
        print(f"注释差异　：{len(diff['comments'])} 处")
    if diff["conflicts"]:
        print(f"定义冲突　：{len(diff['conflicts'])} 处（不会自动覆盖）")

    do_m = args.merge or args.all
    do_d = args.distribute or args.all
    do_c = args.cwl or args.all
    do_x = bool(args.drop)
    if not (do_m or do_d or do_c or do_x):
        print("\n未指定动作；直接运行脚本可进入交互面板。")
        return 0
    if not args.write:
        print("\n预览模式：加 --write 才会写入。")
        return 0

    if do_m and (diff["additions"] or diff["comments"]):
        marker = f"合并自 {'、'.join(sorted({s for i in diff['additions'].values() for s in i['sources']}))}"
        block = [rewrite_comment(i["line"], marker) for i in diff["additions"].values()]
        repl = {k: rewrite_comment(v["line"], f"更新于 {today()}") for k, v in diff["comments"].items()}
        backup(ctx["template"])
        insert_into_symbol_lib(ctx["template"], block, repl)
        print(f"已回填：新增 {len(block)} 个，注释更新 {len(repl)} 处")
    if do_x:
        text = read_text(ctx["template"])
        lines = text.splitlines(keepends=True)
        wanted = {n.lstrip("\\") for n in args.drop}
        kept, removed = [], []
        for line in lines:
            m = DEF_RE.match(line)
            if m and m.group(1) in wanted:
                removed.append(m.group(1))
                continue
            kept.append(line)
        if removed:
            backup(ctx["template"])
            write_text(ctx["template"], "".join(kept))
            print(f"已删除：{'、'.join('\\' + n for n in removed)}")
        else:
            print("未找到指定符号。")
    if do_c:
        refresh_cwl(ctx["template"], ctx["cwl"])
    if do_d:
        print("分发到各子文件夹：")
        distribute(ctx["template"], notes)
    return 0


def main():
    parser = argparse.ArgumentParser(description="笔记符号管理（直接运行进入交互面板）")
    parser.add_argument("--cwl", action="store_true", help="刷新 TeXStudio 补全")
    parser.add_argument("--merge", action="store_true", help="回填：各笔记 -> 模板")
    parser.add_argument("--distribute", action="store_true", help="分发：模板 -> 各笔记")
    parser.add_argument("--drop", nargs="*", default=None, help="从模板删除指定符号")
    parser.add_argument("--all", action="store_true", help="回填 + 刷新补全 + 分发")
    parser.add_argument("--write", action="store_true", help="真正写入（默认仅预览）")
    parser.add_argument("--root", default=None, help="笔记根目录")
    parser.add_argument("--template", default=None, help="符号来源 structure.sty")
    parser.add_argument("--cwl-path", default=None, help="TeXStudio 补全文件路径")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    cfg, conf = load_config()
    global IGNORE_EXTRA
    IGNORE_EXTRA = {n.strip() for n in cfg.get("ignore", "").split(",") if n.strip()}
    root = resolve_root(args.root, cfg)
    template = resolve_template(args.template, cfg)
    cwl = resolve_cwl(args.cwl_path, cfg)

    if template is None or not template.is_file():
        print("找不到符号来源 structure.sty。")
        print("请在 symbols.conf 中设置 template，或用 --template 指定。")
        return 1

    ctx = {"root": root, "template": template, "cwl": cwl, "cfg": cfg, "conf": conf}

    has_action = args.cwl or args.merge or args.distribute or args.drop or args.all
    if has_action:
        return cli_run(args, ctx)
    run_panel(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
