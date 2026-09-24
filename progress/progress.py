# -*- coding: utf-8 -*-
"""写作进度追踪表 —— 本地服务

扫描 LaTeX 笔记的写作进度，在浏览器中查看。设计依据见 progress_design.md。

用法：
    python progress.py                 启动服务并自动打开浏览器
    python progress.py --rescan        仅扫描并打印统计（调试用）
    python progress.py --report FILE   导出 Markdown 报告到指定文件
    python progress.py --port 8766     指定端口

配置见同目录 progress.conf（首次运行自动生成）。
"""

import configparser
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
CONF_PATH = SCRIPT_DIR / "progress.conf"
MARKS_PATH = SCRIPT_DIR / "progress_marks.json"
SETTINGS_PATH = SCRIPT_DIR / "progress_settings.json"
UI_PATH = SCRIPT_DIR / "progress_ui.html"

VERSION = "0.1.0"

# ---------------------------------------------------------------- 常量

# structure.sty 定义的 17 个定理环境
THEOREM_ENVS = {
    "definition", "axiom", "hypothesis", "theorem", "lemma", "proposition",
    "corollary", "metatheorem", "criteria", "problem", "example", "remark",
    "exercise", "algorithm", "convention", "alarm", "sketch",
}
# 用于追踪「证明」维度的环境
PROOF_ENVS = {"proof", "sketch"}

# 判定「有内容」的字符阈值
MIN_CHARS = 50
# 空环境的判定阈值
EMPTY_ENV_CHARS = 20

TITLE_RE = re.compile(r"^\s*\\(part|chapter|section|subsection|subsubsection"
                      r"|appendixchapter|appendixsubsection)\b")
COMMENT_RE = re.compile(r"^\s*%")
BEGIN_RE = re.compile(r"\\begin\{([^}]*)\}")
END_RE = re.compile(r"\\end\{([^}]*)\}")
TITLE_CMD_RE = re.compile(r"\\title\{(.*)\}\s*$")
INPUT_PREFIX = "\\input{"

# ---------------------------------------------------------------- 层级模式

#: LaTeX 章节命令，由外到内。层级模式必须是它的**保持次序的子序列**。
SECTION_CMDS = ["part", "chapter", "section", "subsection",
                "subsubsection", "paragraph", "subparagraph"]

#: 各层的层名，用于界面文案（「未启用章」还是「未启用部分」）。
LEVEL_CN = {"part": "部分", "chapter": "章", "section": "节",
            "subsection": "小节", "subsubsection": "小小节",
            "paragraph": "段", "subparagraph": "子段"}

#: 模板自定义的附录命令。按**目录结构里的位置**归属，而不按它在正文里的渲染层级：
#: 附录目录本身就是章下的一个子目录，所以 `\appendixchapter` 写在「节位」、
#: 它下面的 `\appendixsubsection` 写在「小节位」（与 outline_tool 的 ALIAS 同一口径）。
APX_FOR = {"section": "appendixchapter", "subsection": "appendixsubsection"}

#: 会被识别为标题的命令（含附录命令）。键是命令名，值是标题文本。
TITLE_KEYS = ("part", "chapter", "section", "subsection", "subsubsection",
              "appendixchapter", "appendixsubsection")

#: 标题命令的层级次序，由外到内；附录命令按它所在的**结构位置**排
#: （`\appendixchapter` 在节位、`\appendixsubsection` 在小节位）。
TITLE_ORDER = ["part", "chapter", "section", "appendixchapter",
               "subsection", "appendixsubsection", "subsubsection"]

#: 各标题命令的匹配式：贪婪匹配到行尾的 `}`，
#: 这样标题里嵌 `\texorpdfstring{$\R^{n}$}{Rn}` 这类花括号也不会截断。
_TITLE_RES = {k: re.compile(r"\\" + k + r"\*?\{(.*)\}\s*$") for k in TITLE_KEYS}

#: 「新建大纲」（new_note.py）里的层级模式，运行时读它，保证两处是同一套。
NEW_NOTE_PATH = SCRIPT_DIR.parent / "new_note" / "new_note.py"

#: 读不到 new_note.py 时的兜底（本目录被单独拷走也能跑），内容与它保持一致。
FALLBACK_LEVEL_PRESETS = {
    "textbook":      ("chapter,section,subsection", "常见教材：层1 目录＝章"),
    "textbook-part": ("part,chapter,section,subsection", "分「部」的大部头"),
    "two-level":     ("chapter,section", "两层：讲义 / 小册子"),
    "article":       ("section,subsection", "文章式：不分章"),
    "grouped":       ("chapter,-,section", "中间层只作分组、不产生标题"),
}

#: 以 `\part` 开头的序列在「新建大纲」里没有简写名（直接写命令即可），
#: 但设置页需要能选到 —— 「部分-章-节」这类显示需求是真实存在的。
EXTRA_LEVEL_MODES = [
    ("part,chapter,section", "部分-章-节：以 \\part 归组，部分不占章号"),
    ("part,chapter", "部分-章：两层"),
]


def load_level_presets():
    """层级模式清单 —— 直接读 new_note.py 的 LEVEL_PRESETS，与「新建大纲」一套。"""
    if NEW_NOTE_PATH.is_file():
        try:
            spec = importlib.util.spec_from_file_location("_nn_levels", NEW_NOTE_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            presets = getattr(mod, "LEVEL_PRESETS", None)
            if presets:
                return dict(presets)
        except Exception:
            pass
    return dict(FALLBACK_LEVEL_PRESETS)


def parse_levels(spec):
    """命令序列字符串 -> 命令列表（含 `-` 表示分组层）。非法返回 []。"""
    cmds = [c.strip().lower() for c in (spec or "").split(",") if c.strip()]
    if not cmds:
        return []
    pos = []
    for c in cmds:
        if c == "-":
            continue
        if c not in SECTION_CMDS:
            return []
        pos.append(SECTION_CMDS.index(c))
    if not pos or pos != sorted(pos) or len(set(pos)) != len(pos):
        return []
    return cmds


def level_cmd(levels, depth):
    """树里第 depth 层对应的 LaTeX 命令。

    depth 超出已声明的层数时（层次比模式更深）按 LaTeX 次序继续往下顺延，
    而不是硬套末一层 —— 这样把三层的笔记临时设成两层模式，深出来的那层仍能取到标题。
    """
    if not levels:
        return ""
    if depth < len(levels):
        return levels[depth]
    base = next((SECTION_CMDS.index(c) for c in levels if c != "-"),
                len(SECTION_CMDS))
    i = min(base + depth, len(SECTION_CMDS) - 1)
    return SECTION_CMDS[i]


def level_names(levels):
    """`chapter,section,subsection` -> `章-节-小节`（界面上用的短名）。"""
    out = []
    for c in levels or []:
        out.append("分组" if c == "-" else LEVEL_CN.get(c, c))
    return "-".join(out)


def title_candidates(cmd):
    """该层标题可能写在哪些命令里 —— 附录目录的标题用 `\\appendixchapter` 写在节位上。"""
    if not cmd or cmd == "-":
        return ()
    alt = APX_FOR.get(cmd)
    return (cmd,) if not alt else (cmd, alt)


# ---------------------------------------------------------------- 配置层

DEFAULT_CONF_TEXT = """\
# 写作进度追踪表 —— 配置
# 修改后重启服务生效。

[paths]
# 笔记工作区根目录。留空则使用本脚本所在目录。
root =
# TeXStudio 可执行文件路径。留空则自动探测。
texstudio =

[server]
# 监听地址。127.0.0.1 表示仅本机可访问。
host = 127.0.0.1
# 端口。被占用时自动顺延。
port = 8765
# 启动后是否自动打开浏览器。
auto_open = true

[scan]
# 额外忽略的目录名，逗号分隔（以 . 或 _ 开头的目录已自动忽略）。
ignore =
# 判定「有内容」的字符阈值。
min_chars = 50
# 停滞提醒：超过这么多天没改动则标出。
stagnant_days = 14
# 续写区显示的最近改动文件数。
recent_count = 6
"""


def load_conf():
    """读取配置；文件不存在则按默认值创建。"""
    if not CONF_PATH.exists():
        CONF_PATH.write_text(DEFAULT_CONF_TEXT, encoding="utf-8", newline="")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONF_PATH, encoding="utf-8")

    paths = cfg["paths"] if "paths" in cfg else {}
    server = cfg["server"] if "server" in cfg else {}
    scan = cfg["scan"] if "scan" in cfg else {}

    root_raw = (paths.get("root") or "").strip() if paths else ""
    root = Path(root_raw) if root_raw else SCRIPT_DIR

    ignore_raw = (scan.get("ignore") or "") if scan else ""
    ignore = [x.strip() for x in ignore_raw.split(",") if x.strip()]

    def _int(section, key, default):
        try:
            return int(section.get(key, default))
        except (ValueError, AttributeError):
            return default

    return {
        "root": root,
        "texstudio": ((paths.get("texstudio") or "").strip() if paths else ""),
        "host": ((server.get("host") or "127.0.0.1").strip() if server else "127.0.0.1"),
        "port": _int(server, "port", 8765),
        "auto_open": ((server.get("auto_open") or "true").strip().lower()
                      in ("1", "true", "yes", "on")) if server else True,
        "ignore": ignore,
        "min_chars": _int(scan, "min_chars", MIN_CHARS),
        "stagnant_days": _int(scan, "stagnant_days", 14),
        "recent_count": _int(scan, "recent_count", 6),
    }


# ---------------------------------------------------------------- 设置层

DEFAULT_SETTINGS = {
    "version": 1,
    "updated": "",
    #: 明细页默认是否把未启用的章一并显示在树里（灰显、不计入统计）。
    "show_unused": True,
    #: 每本笔记的层级模式：{笔记目录名: "chapter,section,subsection"}。
    #: 没写的笔记按结构自动识别；写 `auto` 或删掉该项即恢复自动。
    "note_levels": {},
}


def settings_bak_path():
    return SETTINGS_PATH.parent / (SETTINGS_PATH.name + ".bak")


def load_settings():
    """读取设置。文件不存在返回默认值；损坏时尝试从 .bak 恢复。"""
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("结构不是对象")
    except Exception:
        try:
            data = json.loads(settings_bak_path().read_text(encoding="utf-8"))
            print("  [提示] 设置文件损坏，已从 .bak 恢复。")
        except Exception:
            print("  [提示] 设置文件损坏且无备份，已用默认设置。")
            return dict(DEFAULT_SETTINGS)
    out = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        if k in data:
            out[k] = data[k]
    if not isinstance(out.get("note_levels"), dict):
        out["note_levels"] = {}
    return out


def save_settings(data):
    """原子写入设置：先写临时文件再替换；旧文件留作 .bak。"""
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = SETTINGS_PATH.parent / (SETTINGS_PATH.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    if SETTINGS_PATH.exists():
        try:
            os.replace(SETTINGS_PATH, settings_bak_path())
        except OSError:
            pass
    os.replace(tmp, SETTINGS_PATH)


def public_settings(settings):
    """下发到页面的设置。"""
    return {
        "show_unused": bool(settings.get("show_unused", True)),
        "note_levels": dict(settings.get("note_levels") or {}),
    }


def level_mode_choices():
    """设置页的下拉项：自动识别 ＋ 各层级模式。

    各预设直接来自「新建大纲」（new_note.py 的 LEVEL_PRESETS），两处同一套；
    以 `\\part` 开头的序列在那边没有简写名，这里另列（EXTRA_LEVEL_MODES）。
    """
    out = [{"id": "auto", "cmds": "", "names": "自动识别", "name": "auto",
            "desc": "按 main.tex 最外层的标题命令与树的层数推断"}]
    seen = set()
    groups = [(n, v[0], v[1]) for n, v in load_level_presets().items()]
    groups += [(m, m, d) for m, d in EXTRA_LEVEL_MODES]
    for name, seq, desc in groups:
        cmds = parse_levels(seq)
        key = ",".join(cmds)
        if not cmds or key in seen:
            continue
        seen.add(key)
        out.append({"id": key, "cmds": key, "names": level_names(cmds),
                    "name": name, "desc": desc})
    return out


# ---------------------------------------------------------------- 解析层

def parse_inputs(line):
    r"""提取一行中所有 \input{...} 的目标路径。

    必须做花括号配对：路径可能含 LaTeX 花括号，
    例如 ./Content/7_The_additive_groups_R^{n}/index
    """
    out = []
    idx = 0
    while True:
        pos = line.find(INPUT_PREFIX, idx)
        if pos < 0:
            break
        i = pos + len(INPUT_PREFIX)
        start = i
        depth = 1
        while i < len(line) and depth > 0:
            if line[i] == "{":
                depth += 1
            elif line[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            out.append(line[start:i - 1].strip())
        idx = i
    return out


def take_group(s, start):
    """s[start] 应为 '{'。返回配对组内的内容与结束位置。"""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    return s[start + 1:], len(s)


def unwrap_cmd(s, cmd):
    r"""反复把 \cmd{...} 替换为其参数内容，保留内部文本。"""
    token = cmd + "{"
    for _ in range(200):
        p = s.find(token)
        if p < 0:
            return s
        inner, end = take_group(s, p + len(cmd))
        s = s[:p] + inner + s[end:]
    return s


def clean_label(text):
    r"""清理 LaTeX 标题中的装饰命令，得到可显示的纯文本。

    处理 \texorpdfstring{A}{B} -> A、\textbf{} 等装饰命令、数集宏与残留括号。
    """
    if not text:
        return ""
    s = text.strip()

    # \texorpdfstring{A}{B} -> A。两个参数是各自独立的括号组，第二个须整体跳过。
    for _ in range(200):
        p = s.find("\\texorpdfstring{")
        if p < 0:
            break
        first, pos = take_group(s, p + len("\\texorpdfstring"))
        if pos < len(s) and s[pos] == "{":
            _, pos = take_group(s, pos)
        s = s[:p] + first + s[pos:]

    for cmd in ("\\textbf", "\\textit", "\\emph", "\\mathrm", "\\mathbf",
                "\\mathsf", "\\text", "\\ensuremath", "\\mbox"):
        s = unwrap_cmd(s, cmd)

    # 数学字体宏一类 \cmd{X} -> X（如 \mathcal{L} -> L、\mathfrak{S} -> S）
    for _ in range(60):
        before = s
        s = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", s)
        if s == before:
            break

    for cmd in ("\\Huge", "\\huge", "\\Large", "\\large", "\\normalsize",
                "\\footnotesize", "\\small", "\\!"):
        s = s.replace(cmd, "")

    s = s.replace("$", "")
    for _ in range(200):
        before = s
        s = re.sub(r"\{([^{}]*)\}", r"\1", s)
        if s == before:
            break
    s = s.replace("{", "").replace("}", "")
    # 残留的 \R \N 等宏去掉反斜杠
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    return " ".join(s.split())


def natural_key(p):
    """按路径名开头的数字自然排序（1_、2_、10_…），不用字符串序。"""
    m = re.match(r"(\d+)", p.name)
    return (int(m.group(1)) if m else 9999, p.name)


def strip_num_prefix(name):
    """去掉目录 / 文件名开头的编号前缀（如 1_、010_）。"""
    return re.sub(r"^\d+_", "", name)


def pretty_name(path):
    """节点的人类可读名：index.tex 取父目录名，其余取文件名。

    去掉编号前缀，并把下划线换成空格 —— 笔记的目录名 / 文件名取英译加下划线，
    在未填中文标题时以它兜底，转换后可读性明显更好。
    """
    base = path.parent.name if path.stem == "index" else path.stem
    return strip_num_prefix(base).replace("_", " ")


def tree_depth(node):
    """节点所在子树的层数（叶子记 1 层）。"""
    kids = node.get("children") or []
    if node.get("type") == "leaf" or not kids:
        return 1
    return 1 + max(tree_depth(c) for c in kids)


def find_node_title(node, cmds):
    r"""按顺序在节点自身及其子树里找第一个属于 cmds 的标题。

    返回 (标题文本, 实际命令)；找不到返回 ("", "")。
    标题的落点在本笔记体系里有约定：**每一层的标题只写在「它子树里的第一个文件」里**
    （`\section` 写在节目录第一个叶子中、`\appendixchapter` 同此），所以目录的标题
    必须往子树里找，而叶子自己的标题只看自己 —— 两者用同一函数，区别只在有没有子节点。

    ⚠️ 判据是**命令出现过**（`titles` 里有没有这个键），不是标题文本非空 ——
    `\appendixchapter{}` 这种「留空标题」（模板会只渲染「附录 A」）同样要认出来，
    否则那个附录会被当成普通节、编号也跟着错。

    模式与实际命令对不上时（例如把 `chapter,section,subsection` 的笔记显示成
    `part,chapter,section`）退回 fallback_title，仍能取出可读的标题。
    """
    own = node.get("titles") or {}
    for c in cmds:
        if c in own:
            return own[c], c
    for ch in node.get("children", []):
        t, c = find_node_title(ch, cmds)
        if c:
            return t, c
    return "", ""


def _own_pick(node, keys):
    """在节点**自己**那个文件里按 keys 顺序取第一个标题（同样以「命令出现过」为准）。"""
    own = node.get("titles") or {}
    for c in keys:
        if c in own:
            return own[c], c
    return "", ""


def fallback_title(node):
    r"""标题命令与层级模式对不上时的兜底：按「叶子取最深、目录取最浅」取。

    一个文件里可能出现多个标题命令（节目录的标题 `\section` 写在它第一个叶子中，
    该叶子自己的标题是 `\subsection`）。所以：
      · 叶子 —— 它的标题是文件里**最深**的那个命令；
      · 目录 —— 它的标题是子树里第一个文件**最浅**的那个命令。
    """
    if node.get("type") == "leaf" or not node.get("children"):
        return _own_pick(node, list(reversed(TITLE_ORDER)))
    t = _own_pick(node, TITLE_ORDER)
    if t[1]:
        return t
    for ch in node.get("children", []):
        if ch.get("type") == "leaf" or not ch.get("children"):
            t = _own_pick(ch, TITLE_ORDER)      # 子树里的文件：取最浅的那个命令
        else:
            t = fallback_title(ch)
        if t[1]:
            return t
    return "", ""


def detect_outer_cmd(entries):
    r"""main.tex 里最外层的标题命令：part / chapter / section（取不到返回空串）。

    `\part` 名只对应一个 `\input` 时，顶层才是「部分」；先 `\part` 再并列多个 `\input`
    的写法里，那些 `\input` 各自是章 —— 与编号口径保持一致。
    """
    parts = {}
    for e in entries:
        if e.get("part"):
            parts[e["part"]] = parts.get(e["part"], 0) + 1
    if parts and len(parts) == len(entries) and all(v == 1 for v in parts.values()):
        return "part"
    for e in entries:
        if e.get("chapter"):
            return "chapter"
    for e in entries:
        if e.get("section"):
            return "section"
    return ""


def detect_levels(entries, tops):
    """按结构自动识别层级模式：最外层命令取自 main.tex，其余按 SECTION_CMDS 顺延。

    顺延的层数取「树的层数」而非各层实际读到什么命令 —— 后者会被「某层没有自己的
    标题」这类写法带偏（与 outline_tool 导出大纲的口径一致）。
    """
    depth = max([tree_depth(t) for t in tops] or [1])
    outer = detect_outer_cmd(entries)
    if outer:
        idx = SECTION_CMDS.index(outer)
    else:
        # main.tex 里没有标题命令：两层以上按「章」起算，只有一层时当「节」
        idx = 1 if depth >= 2 else 2
    idx = max(0, min(idx, len(SECTION_CMDS) - depth))
    return SECTION_CMDS[idx: idx + depth]


def apply_levels(tops, levels, headings):
    r"""按层级模式给每个节点定「层名 + 标题 + 显示名」。

    headings：main.tex 里「\input 目标 → {命令: 标题}」。顶层（部分 / 章）的标题
    写在 main.tex 里而非目录中的文件，只能从这里取；取不到才退回往子树里找。
    """
    def walk(node, depth):
        cmd = level_cmd(levels, depth)
        cmds = title_candidates(cmd)
        h = headings.get(node["id"]) or {}
        title = cmd_t = ""
        for c in cmds:                       # ① 该层命令（main.tex 里的顶层标题优先）
            if h.get(c):
                title, cmd_t = h[c], c
                break
        if not title and h:                  # ② main.tex 里就是标题的来源，命令对不上也照用
            for c in TITLE_ORDER:
                if h.get(c):
                    title, cmd_t = h[c], c
                    break
        if not title and cmds:               # ③ 往子树里找该层的标题（目录 / 叶子各按约定）
            title, cmd_t = find_node_title(node, cmds)
        if not title and cmds:               # ④ 层级模式与实际命令对不上时的兜底
            title, cmd_t = fallback_title(node)
        node["title"], node["title_cmd"] = title, cmd_t
        node["level"] = cmd
        node["level_cn"] = LEVEL_CN.get(cmd, "")
        node["view_title"] = title or node["name"]
        for c in node.get("children", []):
            walk(c, depth + 1)

    for t in tops:
        walk(t, 0)


def resolve_target(note_dir, target):
    r"""把 \input 的目标路径解析为实际文件路径。

    不能拿 `Path.suffix` 判断是否要补 `.tex`：`\input` 允许省略扩展名，而文件名
    本身可能含点（如 `1_The_complexes_Ku,_K.u,_C,_Ku,_C`），后缀会算成
    `.u,_C,_Ku,_C` 这种伪后缀，于是漏补 `.tex`，真实存在的文件被误判成「未建」。
    """
    rel = target.strip()
    while rel.startswith("./"):
        rel = rel[2:]
    p = note_dir / rel
    if p.name.lower().endswith(".tex"):
        return p
    return note_dir / (rel + ".tex")


def file_metrics(path, min_chars=MIN_CHARS, text=None):
    """统计单个 tex 文件的指标。

    返回 dict，含状态、字符构成、定理环境统计、配对情况等。
    text 可传入已读入的内容，避免重复读取磁盘。
    """
    m = {
        "status": "empty",
        "chars": 0,            # 剔除标题/注释/空行后的实质字符数
        "body_chars": 0,       # 环境之外的陈述性文字
        "inner_chars": 0,      # 定理环境内部的字符
        "total_chars": 0,
        "lines": 0,
        "envs": 0,
        "empty_envs": 0,
        "env_names": {},
        "has_proof": False,
        "has_sketch": False,
        "unpaired": False,
        #: 本文件里各标题命令的第一次出现（命令名 → 标题文本），
        #: 供上层按「这本笔记的层级模式」取用：`\section` 写在某个目录的第一个叶子里
        #: 时，那个叶子自己的标题是 `\subsection`，两者不能混为一谈。
        "titles": {},
    }
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            m["status"] = "missing"
            return m

    m["total_chars"] = len(text)
    lines = text.splitlines()
    m["lines"] = len(lines)

    depth = 0              # 当前定理环境嵌套深度
    buf = 0                # 当前环境累积字符
    env_stack = []

    for ln in lines:
        raw = ln.rstrip("\n")
        stripped = raw.strip()

        # 环境开闭：先做廉价的字符串预检查，避免多数行进入正则
        has_env_tag = "\\begin{" in raw or "\\end{" in raw
        if has_env_tag:
            for mm in BEGIN_RE.finditer(raw):
                name = mm.group(1)
                if name in THEOREM_ENVS:
                    if depth == 0:
                        buf = 0
                    depth += 1
                    env_stack.append(name)
                    m["envs"] += 1
                    m["env_names"][name] = m["env_names"].get(name, 0) + 1
                    if name == "proof":
                        m["has_proof"] = True
                    elif name == "sketch":
                        m["has_sketch"] = True
            for mm in END_RE.finditer(raw):
                name = mm.group(1)
                if name in THEOREM_ENVS and depth > 0:
                    depth -= 1
                    if env_stack:
                        env_stack.pop()
                    if depth == 0:
                        if buf < EMPTY_ENV_CHARS:
                            m["empty_envs"] += 1
                        buf = 0

        if not stripped or stripped[:1] == "%":
            continue

        # 标题行：先收集各命令的标题（每本笔记按自己的层级模式取用），再跳过不计字数
        # 「命令出现过」本身是有用信息（`\appendixchapter{}` 留空标题也是附录），
        # 所以只要匹配到就记下来，哪怕标题文本是空串。
        if stripped[:1] == "\\":
            for _k, _rx in _TITLE_RES.items():
                if _k in m["titles"]:
                    continue
                _mt = _rx.search(raw)
                if _mt:
                    m["titles"][_k] = clean_label(_mt.group(1))
            if TITLE_RE.match(stripped):
                continue

        if has_env_tag:
            core = END_RE.sub("", BEGIN_RE.sub("", raw)).strip()
        else:
            core = stripped

        n = len(core)
        if depth > 0:
            buf += n
            m["inner_chars"] += n
        else:
            m["body_chars"] += n
        m["chars"] += n

    if depth != 0:
        m["unpaired"] = True

    m["status"] = "written" if m["chars"] > min_chars else "empty"
    return m


def content_fingerprint(path):
    """文件内容指纹，用于目录改名后的标记迁移（同名文件时辅助判定）。"""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    compact = re.sub(rb"\s+", b"", data)
    return hashlib.sha1(compact).hexdigest()[:12]


# ---------------------------------------------------------------- 扫描层

SKIP_DIR_PREFIX = ("_", ".")
SKIP_SUFFIX = {
    ".aux", ".log", ".out", ".toc", ".pdf", ".synctex", ".gz", ".bak",
    ".fls", ".fdb_latexmk", ".bbl", ".blg", ".idx", ".ilg", ".ind", ".nav",
    ".snm", ".vrb", ".xdv", ".dvi", ".lof", ".lot", ".run.xml", ".bcf",
}


def list_notes(cfg):
    """列出工作区中的笔记目录（含 main.tex 且有 Content/）。"""
    root = cfg["root"]
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        if d.name.startswith(SKIP_DIR_PREFIX):
            continue
        if d.name in cfg["ignore"]:
            continue
        if (d / "main.tex").exists() and (d / "Content").is_dir():
            out.append(d)
    return out


def note_title(note_dir):
    """从 main.tex 的 \\title{} 提取笔记中文名。"""
    mt = note_dir / "main.tex"
    if not mt.exists():
        return note_dir.name
    for ln in mt.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if COMMENT_RE.match(s):
            continue
        g = TITLE_CMD_RE.search(s)
        if g:
            t = clean_label(g.group(1))
            if t:
                return t
    return note_dir.name


def build_tree(note_dir, target, seen, cfg, depth=0, included=True):
    r"""从一个 \input 目标出发递归构建子树。层级不硬编码。

    included 表示该节点是否纳入编译：main.tex 与各 index.tex 里被 `%` 注释掉的
    \input 同样是一棵子树的入口，必须照常建树（否则界面上那部分**整块消失**），
    只是往下传的 included 为 False，交由四象限规则决定计不计入进度。
    """
    path = resolve_target(note_dir, target)
    try:
        rel = str(path.relative_to(note_dir)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")

    node = {
        "id": rel,
        "name": pretty_name(path),
        "path": str(path),
        "depth": depth,
        "type": "missing",
        "children": [],
        "num": "",
        "included": included,
    }

    if not path.exists():
        node["view_title"] = node["name"]
        return node
    if path in seen:
        return None
    seen.add(path)

    text = path.read_text(encoding="utf-8", errors="ignore")
    subs = []                      # [(目标路径, 该条引用是否纳入编译)]
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if COMMENT_RE.match(s):
            # 被注释掉的 \input 仍是笔记结构的一部分，照常建树
            for t in parse_inputs(re.sub(r"^%+\s*", "", s)):
                subs.append((t, False))
        else:
            for t in parse_inputs(ln):
                subs.append((t, included))

    # index.tex 若没有任何 \input，先看同目录下是否还有其他 .tex
    # （结构已建好、但索引文件还没写内容的情形）
    if path.stem == "index" and not subs:
        peers = sorted(
            [f for f in path.parent.glob("*.tex") if f.name != "index.tex"],
            key=natural_key)
        subs = [("./" + str(f.relative_to(note_dir)).replace("\\", "/")[:-4],
                 included)
                for f in peers]

    # 节点形态判定：
    #   · 普通 .tex 文件              -> 叶子（就是一层内容单元）
    #   · index.tex 且引到了子项      -> 目录（章 / 节 …）
    #   · index.tex 且子项为空        -> 它自己就是这一层的内容单元，按叶子处理
    #       （「内容直接写在节目录自己的 index.tex 里」的写法；按叶子处理才能像小节
    #        一样展开三维标记与备注。目录的标题仍按层级模式从它自己文件里取。）
    if path.stem != "index" or not subs:
        node["type"] = "leaf"
        node.update(file_metrics(path, cfg["min_chars"], text=text))
    else:
        node["type"] = "dir"
        for t, inc in subs:
            child = build_tree(note_dir, t, seen, cfg, depth + 1, inc)
            if child is not None:
                node["children"].append(child)
        self_m = file_metrics(path, cfg["min_chars"], text=text)
        node["titles"] = self_m["titles"]
        if not node["children"]:
            node["self_metrics"] = self_m
    st = path.stat()
    node["mtime"] = st.st_mtime
    node["mtime_str"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    return node


def collect_paths(node, acc=None):
    """收集子树（含目录节点自身）的文件路径，用于识别游离文件。

    这里用 Path 直接比较、不做 resolve()：两者都基于同一个 note_dir 拼出来，
    前缀天然一致，而 resolve() 在 Windows 上每个文件要跑好几次系统调用。
    """
    if acc is None:
        acc = set()
    acc.add(Path(node["path"]))
    for c in node.get("children", []):
        collect_paths(c, acc)
    return acc


def find_orphans(note_dir, tops, cfg):
    r"""找出既没被任何 \input 引用、也没进树的 tex 文件。

    两种来历：写好了但还没写进 index.tex 的小节，以及改名后忘删的旧文件。
    它们不属于笔记结构，所以不进树；但必须在界面上列出来 ——
    否则用户会以为是「工作台没把小节显示全」。
    """
    known = collect_paths_from_tops(tops)
    out = []
    for f in sorted(note_dir.rglob("*.tex"), key=natural_key):
        rel = f.relative_to(note_dir)
        parts = rel.parts
        if any(p[:1] in SKIP_DIR_PREFIX for p in parts):
            continue
        if any(p in cfg["ignore"] for p in parts[:-1]):
            continue
        if rel.name == "main.tex" or f in known:
            continue
        m = file_metrics(f, cfg["min_chars"])
        st = f.stat()
        out.append({
            "id": str(rel).replace("\\", "/"),
            "name": f.stem,
            "path": str(f),
            "status": m["status"],
            "chars": m["chars"],
            "mtime": st.st_mtime,
            "mtime_str": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def collect_paths_from_tops(tops):
    acc = set()
    for t in tops:
        collect_paths(t, acc)
    return acc


def aggregate(node):
    """自下而上汇总统计。"""
    if node["type"] == "leaf":
        st = node["status"]
        node["stats"] = {
            "planned": 1,
            "written": 1 if st == "written" else 0,
            "empty": 1 if st == "empty" else 0,
            "missing": 1 if st == "missing" else 0,
            "envs": node.get("envs", 0),
            "chars": node.get("chars", 0),
            "body_chars": node.get("body_chars", 0),
            "proofs": 1 if node.get("has_proof") or node.get("has_sketch") else 0,
            "empty_envs": node.get("empty_envs", 0),
            "unpaired": 1 if node.get("unpaired") else 0,
            "leaves": 1,
        }
        node["last_mtime"] = node.get("mtime") or 0.0
        return node["stats"]

    if node["type"] == "missing":
        node["stats"] = {
            "planned": 1, "written": 0, "empty": 0, "missing": 1, "envs": 0,
            "chars": 0, "body_chars": 0, "proofs": 0, "empty_envs": 0,
            "unpaired": 0, "leaves": 1,
        }
        return node["stats"]

    total = {
        "planned": 0, "written": 0, "empty": 0, "missing": 0, "envs": 0,
        "chars": 0, "body_chars": 0, "proofs": 0, "empty_envs": 0,
        "unpaired": 0, "leaves": 0,
    }
    newest = 0.0
    for c in node["children"]:
        cs = aggregate(c)
        for k in total:
            total[k] += cs[k]
        newest = max(newest, c.get("last_mtime") or 0.0)

    # 内容直接写在 index.tex 里的章：把自身算作一个内容单元
    sm = node.get("self_metrics")
    if sm:
        total["planned"] += 1
        total["leaves"] += 1
        total["envs"] += sm["envs"]
        total["chars"] += sm["chars"]
        total["body_chars"] += sm["body_chars"]
        total["empty_envs"] += sm["empty_envs"]
        if sm["unpaired"]:
            total["unpaired"] += 1
        if sm["has_proof"] or sm["has_sketch"]:
            total["proofs"] += 1
        if sm["status"] == "written":
            total["written"] += 1
        elif sm["status"] == "empty":
            total["empty"] += 1

    node["stats"] = total
    node["last_mtime"] = newest
    return total


CN_DIGITS = "零一二三四五六七八九"


def cn_number(n):
    """把 1..99 转成中文数字，用于「第X部分」。"""
    if n <= 0:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + CN_DIGITS[n - 10]
    tens, ones = divmod(n, 10)
    return CN_DIGITS[tens] + "十" + (CN_DIGITS[ones] if ones else "")


def alpha_number(n):
    """1→A、2→B … 27→AA（附录编号；超过 26 个附录时按表格列名继续）。"""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def assign_numbers(tops, levels):
    r"""按层级模式给节点编号：顶层 1、2…，其下依次 `1.1`、`1.1.2`。

    · 顶层是「部分」：部分号用中文数字并写入显示名（`第一部分：集合论`），
      其下的章仍用全书统一的章号（`\part` 不占章号）；
    · 顶层是「章」：章号写进显示名（`第1章：集合论`），其下为 `1.1`、`1.1.2`；
    · 附录章（`\appendixchapter`）走附录自己的计数器、用字母编号，显示成
      「附录 A：…」；其下的附录小节（`\appendixsubsection`）为 `A.1`。
      这正是 structure.sty 里 `\theapx` / `\theapxsec` 的算法。
    · **被注释掉的 \input 同样参与编号** —— 编号反映笔记的**完整结构**，而不是 LaTeX
      编译后的计数器（后者不含被注释的部分，会让「拓扑结构」这类被注释的首章拿不到
      「第一章」，反而把第 7 章排成第一章）。是否纳入编译另由「未编译」标注体现。
    """
    apx = 0

    def walk(node, depth, prefix, idx, pno):
        nonlocal apx
        cmd = level_cmd(levels, depth)
        title_cmd = node.get("title_cmd") or ""
        if title_cmd == "appendixchapter":
            # 附录章：字母编号，不带父节点的章号（附录与正文互不占用编号）
            apx += 1
            node["num"] = f"{pno}.{apx}" if pno else alpha_number(apx)
            # 标题留空的附录（`\appendixchapter{}`）只显示「附录 A」—— 与模板一致，
            # 不要拿目录名去兜底（那会显示成「附录 A：Appendix」）
            base = node.get("title") or ""
            node["view_title"] = (f"附录 {node['num']}：{base}" if base
                                  else f"附录 {node['num']}")
            # 编号已写进显示名（「附录 A：…」），行首不再重复标一次
            child_prefix = node["num"] + "."
            node["num"] = ""
        else:
            # 附录小节与普通各级同一套：编号 = 父编号 + 自己的序号（A.1 / 1.1.2）
            node["num"] = f"{prefix}{idx}"
            if depth == 0 and cmd == "part":
                node["part_no"] = idx
                node["view_title"] = f"第{cn_number(idx)}部分：{node['view_title']}"
                node["num"] = ""
            elif depth == 0 and cmd == "chapter":
                node["view_title"] = f"第{idx}章：{node['view_title']}"
                node["num"] = ""
            # 顶层把编号写进了显示名（第X部分 / 第X章），子节点仍按它的序号续编
            child_prefix = (node["num"] or str(idx)) + "."
        # 未建的文件在 PDF 里不占编号，所以只对实际存在的子项递增（沿用原有口径）
        n = 0
        for c in node.get("children", []):
            if c.get("type") == "missing":
                c["num"] = ""
                continue
            n += 1
            walk(c, depth + 1, child_prefix, n, pno)

    for i, t in enumerate(tops, 1):
        part_mode = level_cmd(levels, 0) == "part"
        walk(t, 0, "", i, i if part_mode else 0)

def scan_main(note_dir, cfg):
    r"""解析 main.tex 的顶层 \input，附带其上方最近的 \part / \chapter / \section 标题。

    顶层（部分 / 章）的标题写在 main.tex 里而不是目录中的文件，所以必须在这里取 ——
    否则树上那一行只能显示英文目录名。三个命令都记下来，由层级模式决定用哪个
    （`\part` 下挂多个 `\input` 的写法里，那些 `\input` 用的是 `\chapter` 名）。
    """
    mt = note_dir / "main.tex"
    entries = []
    if not mt.exists():
        return entries
    cur = {k: "" for k in ("part", "chapter", "section")}
    for ln in mt.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = ln.strip()
        for k in cur:
            mh = _TITLE_RES[k].search(ln)
            if mh:
                cur[k] = clean_label(mh.group(1))
        for t in parse_inputs(ln):
            entries.append({
                "target": t,
                "part": cur["part"],
                "chapter": cur["chapter"],
                "section": cur["section"],
                "included": not COMMENT_RE.match(stripped),
            })
    return entries


def main_headings(note_dir, entries):
    r"""main.tex 里「\input 目标 → 该处各标题命令的值」。

    键与节点的 id 同形（笔记目录内的相对路径），供 apply_levels 按层级模式取用。
    """
    out = {}
    for e in entries:
        vals = {k: e[k] for k in ("part", "chapter", "section") if e.get(k)}
        if not vals:
            continue
        p = resolve_target(note_dir, e["target"])
        try:
            rid = str(p.relative_to(note_dir)).replace("\\", "/")
        except ValueError:
            rid = str(p).replace("\\", "/")
        out[rid] = vals
    return out


def detect_note_levels(note_dir, entries, tops, settings):
    """定这本笔记的层级模式：(命令列表, 'manual'/'auto', 依据说明)。

    设置里手动指定的优先（层级模式记在工作区里的设置文件中，键是笔记目录名）；
    没指定就按结构自动识别。
    """
    manual = (settings.get("note_levels") or {}).get(note_dir.name, "")
    if manual:
        cmds = parse_levels(manual)
        if cmds:
            return cmds, "manual", f"在「设置」里指定：{', '.join(cmds)}"
    levels = detect_levels(entries, tops)
    depth = max([tree_depth(t) for t in tops] or [1])
    outer = detect_outer_cmd(entries)
    how = (f"main.tex 用 \\{outer}、树 {depth} 层" if outer
           else f"main.tex 里没有标题命令、树 {depth} 层")
    return levels, "auto", f"自动识别（{how} → {', '.join(levels)}）"


def scan_note(note_dir, cfg, settings=None):
    """扫描一本笔记，返回含顶层节点与汇总的 dict。

    三步：先建树（层级模式要按树层数定），再定层级模式并套标题与编号。
    """
    entries = scan_main(note_dir, cfg)
    tops = []
    seen = set()
    for e in entries:
        node = build_tree(note_dir, e["target"], seen, cfg, 0, e["included"])
        if node is None:
            continue
        node["part"] = e["part"]
        aggregate(node)
        tops.append(node)

    levels, source, hint = detect_note_levels(note_dir, entries, tops,
                                              settings or {})
    apply_levels(tops, levels, main_headings(note_dir, entries))
    assign_numbers(tops, levels)

    total = zero_stats()
    for t in tops:
        add_stats(total, t["stats"])

    return {
        "name": note_dir.name,
        "title": note_title(note_dir),
        "path": str(note_dir),
        "tops": tops,
        "totals": total,
        "orphans": find_orphans(note_dir, tops, cfg),
        # 层级模式：levels 是命令序列，供界面显示与编号使用
        "levels": levels,
        "level_mode": ",".join(levels),
        "level_names": level_names(levels),
        "level_source": source,
        "level_hint": hint,
        "top_name": LEVEL_CN.get(levels[0] if levels else "", ""),
    }


def scan_all(cfg, settings=None):
    """扫描全部笔记。"""
    notes = []
    for d in list_notes(cfg):
        notes.append(scan_note(d, cfg, settings))
    g = {
        "planned": 0, "written": 0, "empty": 0, "missing": 0, "envs": 0,
        "chars": 0, "body_chars": 0, "proofs": 0, "leaves": 0,
    }
    for n in notes:
        for k in g:
            g[k] += n["totals"][k]
    return {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(cfg["root"]),
        "notes": notes,
        "global": g,
    }


# ---------------------------------------------------------------- 标记层

MARK_DONE = "done"
MARK_TODO = "todo"
MARK_DIMS = ("env", "body", "proof")

# 提示规则（设计 6.2 / 6.3）：
#   · 硬提示 —— 确定的问题，与别的小节无关，单文件即可判定；
#   · 软提示 —— 只在「同一节内的各小节」之间横向比较，绝不用绝对阈值。
#     正文以外的文字占比本就偏低，按绝对阈值判断会让几乎每一节都亮灯，
#     噪声淹没信号；若整节都没有正文，那是写法风格，不是异常。
HINT_HARD = "hard"
HINT_SOFT = "soft"


def median_int(nums):
    """中位数（取整）。空列表返回 0。"""
    if not nums:
        return 0
    s = sorted(nums)
    n = len(s)
    return s[n // 2] if n % 2 else int((s[n // 2 - 1] + s[n // 2]) / 2)


def leaf_hard_hints(leaf):
    """硬提示：与同节其他小节无关，单独看这个文件就能确定的问题。"""
    out = []
    if leaf.get("unpaired"):
        out.append("有 \\begin 未配对，编译会报错")
    if leaf.get("empty_envs"):
        out.append(f"存在 {leaf['empty_envs']} 个空环境")
    return out


def attach_hints(children):
    """给一个目录节点的**直接子小节**挂提示。

    「同一节」= 同一个父节点下的叶子；软提示以「其余小节」为参照 ——
    环境数比其余小节的中位数低到 1/3 以下、其余小节都有 proof/sketch 而此节没有、
    其余小节都有陈述文字而此节没有。其余小节少于 2 个时不比较（样本太小）。
    """
    for c in children:
        if c.get("type") != "leaf":
            continue
        hard = leaf_hard_hints(c)
        soft = []
        others = [o for o in children
                  if o is not c and o.get("type") == "leaf"
                  and o.get("status") != "missing"]
        if c.get("status") == "written" and len(others) >= 2:
            med = median_int([o.get("envs", 0) for o in others])
            if med >= 3 and c.get("envs", 0) < med / 3:
                soft.append(f"环境 {c.get('envs', 0)} 个，本节其他小节中位数 {med} 个")
            if all(o.get("has_proof") or o.get("has_sketch") for o in others) \
                    and not (c.get("has_proof") or c.get("has_sketch")):
                soft.append("本节其他小节都有 proof / sketch，此节没有")
            if all((o.get("body_chars") or 0) > 0 for o in others) \
                    and not (c.get("body_chars") or 0):
                soft.append("本节其他小节都有陈述文字，此节没有")
        hints = ([{"level": HINT_HARD, "text": t} for t in hard]
                 + [{"level": HINT_SOFT, "text": t} for t in soft])
        c["hints"] = hints
        c["hint_level"] = (HINT_HARD if hard else (HINT_SOFT if soft else ""))


def marks_bak_path():
    return MARKS_PATH.parent / (MARKS_PATH.name + ".bak")


def default_marks():
    return {"version": 1, "updated": "", "nodes": {}, "entries": {}}


def load_marks():
    """读取标记数据。文件不存在返回空结构；损坏时尝试从 .bak 恢复。"""
    if not MARKS_PATH.exists():
        return default_marks()

    def _read(p):
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("结构不是对象")
        return data

    try:
        data = _read(MARKS_PATH)
    except Exception:
        bak = marks_bak_path()
        if bak.exists():
            try:
                data = _read(bak)
                print("  [提示] 标记文件损坏，已从 .bak 恢复。")
            except Exception:
                print("  [提示] 标记文件与备份均损坏，已重置为空。")
                return default_marks()
        else:
            print("  [提示] 标记文件损坏且无备份，已重置为空。")
            return default_marks()

    base = default_marks()
    for k in base:
        data.setdefault(k, base[k])
    # 兼容旧版：chapters 已更名为 nodes（现在章 / 节 / 小节任意层级都可覆盖）
    old = data.pop("chapters", None)
    if isinstance(old, dict):
        for k, v in old.items():
            data["nodes"].setdefault(k, v)
    return data


def save_marks(data):
    """原子写入标记数据：先写临时文件，再替换；旧文件留作 .bak。"""
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = MARKS_PATH.parent / (MARKS_PATH.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    if MARKS_PATH.exists():
        try:
            os.replace(MARKS_PATH, marks_bak_path())
        except OSError:
            pass
    os.replace(tmp, MARKS_PATH)


def node_mode(marks, node_id):
    """取节点的手动覆盖模式：auto / force_include / force_exclude。"""
    rec = (marks.get("nodes") or {}).get(node_id) or {}
    mode = rec.get("mode", "auto")
    return mode if mode in ("force_include", "force_exclude") else "auto"


def chapter_decision(node, marks):
    """顶层章的自动判定（四象限）。返回 (计入?, 原因)。

    手动覆盖不在这里处理 —— 由 apply_marks 的遍历统一优先处理，
    这样章 / 节 / 小节任意层级都能被覆盖。
    """
    has_content = node["stats"]["written"] > 0
    if node["included"]:
        return True, "included"
    if has_content:
        return True, "not_compiled"    # 未纳入编译但有内容 -> 计入
    return False, "empty_uncompiled"   # 未纳入编译且无内容 -> 排除


def entry_marks(marks, node_id):
    """取某小节的三个维度标记，缺省为已完成。"""
    rec = marks["entries"].get(node_id) or {}
    m = rec.get("marks") or {}
    out = {}
    for d in MARK_DIMS:
        v = m.get(d, MARK_DONE)
        out[d] = v if v in (MARK_DONE, MARK_TODO) else MARK_DONE
    return out


def collect_leaves(node, acc=None):
    """收集子树中的全部叶子节点。"""
    if acc is None:
        acc = []
    if node["type"] == "leaf":
        acc.append(node)
    else:
        for c in node.get("children", []):
            collect_leaves(c, acc)
    return acc


STAT_KEYS = ("planned", "written", "empty", "missing", "envs", "chars",
             "body_chars", "proofs", "empty_envs", "unpaired", "leaves")


def zero_stats():
    return {k: 0 for k in STAT_KEYS}


def add_stats(target, src):
    for k in STAT_KEYS:
        target[k] += src.get(k, 0)


def apply_marks(data, marks, cfg):
    """把标记应用到扫描结果。

    计入判定**按层级递归**：章 / 节 / 小节都可以有手动覆盖
    （force_include / force_exclude）；父节点被排除时整棵子树一并排除。
    顶层章另走四象限自动判定（未纳入编译且无内容 -> 排除）。
    """
    now = datetime.now()
    recent = []
    stagnant = []
    pending = []
    suspects = []
    chapter_pending = []

    for note in data["notes"]:
        counted = zero_stats()
        overall = zero_stats()
        n_pending = 0
        n_todo_marks = 0
        n_chapter_todo = 0
        n_hints = 0
        last_mtime = 0.0
        planned_next = []

        def walk(node, parent_excluded, is_top):
            nonlocal n_pending, n_todo_marks, n_chapter_todo, n_hints, last_mtime

            mode = node_mode(marks, node["id"])
            if mode == "force_exclude":
                ex, reason = True, "manual_exclude"
            elif mode == "force_include":
                ex, reason = False, "manual_include"
            elif parent_excluded:
                ex, reason = True, "parent_excluded"
            elif is_top or not node.get("included", True):
                # 顶层章与「索引里被注释掉的节 / 小节」走同一套四象限：
                # 有已写内容 -> 计入并标注「未编译」；整枝全空 -> 排除。
                inc, r = chapter_decision(node, marks)
                ex, reason = (not inc), r
            else:
                ex, reason = False, "included"

            node["excluded"] = ex
            node["excluded_reason"] = reason
            node["manual"] = mode != "auto"
            if is_top:
                node["decision"] = not ex
                node["decision_reason"] = reason

            if node["type"] == "leaf":
                # 展示字段与被排除与否无关：未启用章 / 被注释掉的节下面挂着的小节
                # 同样要能展开、点开、看三维标记与备注，只是不参与进度统计。
                em = entry_marks(marks, node["id"])
                rec = marks["entries"].get(node["id"]) or {}
                node["marks"] = em
                node["note"] = rec.get("note", "")
                node["todos"] = rec.get("todos", [])
                node["planned"] = bool(rec.get("planned"))
                n_todo = sum(1 for d in MARK_DIMS if em[d] == MARK_TODO)
                node["todo_count"] = n_todo
                if ex:
                    return
                # 顶层就是叶子（结构扁平）时不会经过父目录的 attach_hints，
                # 这里补上硬提示，保证提示字段始终存在。
                if "hints" not in node:
                    hh = leaf_hard_hints(node)
                    node["hints"] = [{"level": HINT_HARD, "text": t} for t in hh]
                    node["hint_level"] = HINT_HARD if hh else ""
                add_stats(counted, node["stats"])
                n_todo_marks += n_todo
                label = node.get("view_title") or node["name"]
                if node.get("num"):
                    label = f"{node['num']} {label}"
                if n_todo:
                    n_pending += 1
                    pending.append({
                        "note": note["name"], "title": label,
                        "id": node["id"], "path": node["path"],
                        "dims": [d for d in MARK_DIMS if em[d] == MARK_TODO],
                    })
                if node["hint_level"]:
                    n_hints += 1
                    suspects.append({
                        "note": note["name"], "title": label,
                        "id": node["id"], "path": node["path"],
                        "level": node["hint_level"],
                        "texts": [x["text"] for x in node["hints"]],
                    })
                if node["planned"]:
                    planned_next.append({
                        "note": note["name"], "title": label,
                        "id": node["id"], "path": node["path"],
                    })
                if node.get("mtime", 0) > last_mtime:
                    last_mtime = node["mtime"]
                if node["status"] == "written":
                    recent.append({
                        "note": note["name"], "title": label,
                        "id": node["id"], "path": node["path"],
                        "mtime": node["mtime"],
                        "mtime_str": node.get("mtime_str", ""),
                    })
                return

            # 目录节点：提示与章级标记先算 —— 与是否计入无关，
            # 未启用章下面的小节同样要能看到提示、能翻看章级标记。
            attach_hints(node.get("children", []))
            cm = bool(((marks.get("nodes") or {}).get(node["id"]) or {})
                      .get("chapter_mark"))
            node["chapter_mark"] = cm
            if cm and not ex:
                n_chapter_todo += 1
                chapter_pending.append({
                    "note": note["name"],
                    "title": node.get("view_title") or node["name"],
                    "id": node["id"], "path": node["path"],
                })
            if ex:
                # 继续下探仅为把整棵子树标记为「排除」，便于界面灰显
                for c in node.get("children", []):
                    walk(c, True, False)
                return
            sm = node.get("self_metrics")
            if sm and not node.get("children"):
                add_stats(counted, node["stats"])
            for c in node.get("children", []):
                walk(c, False, False)

        for top in note["tops"]:
            add_stats(overall, top["stats"])
            walk(top, False, True)

        note["counted"] = counted
        note["overall"] = overall
        note["excluded_count"] = sum(1 for t in note["tops"]
                                     if t.get("excluded"))
        note["todo_count"] = n_todo_marks
        note["pending_count"] = n_pending
        note["chapter_todo_count"] = n_chapter_todo
        note["hint_count"] = n_hints
        note["last_mtime"] = last_mtime
        note["last_mtime_str"] = (
            datetime.fromtimestamp(last_mtime).strftime("%Y-%m-%d %H:%M")
            if last_mtime else "")
        note["percent"] = round(
            counted["written"] / counted["planned"] * 100
            if counted["planned"] else 0, 1)
        note["confirmed_percent"] = round(
            (counted["written"] - n_pending) / counted["planned"] * 100
            if counted["planned"] else 0, 1)
        note["planned_next"] = planned_next

        if last_mtime:
            days = (now - datetime.fromtimestamp(last_mtime)).days
            if days >= cfg["stagnant_days"]:
                stagnant.append({"name": note["name"], "days": days})

    recent.sort(key=lambda x: x["mtime"], reverse=True)

    g = {k: 0 for k in ("planned", "written", "empty", "missing", "envs",
                        "chars", "body_chars", "proofs")}
    for note in data["notes"]:
        for k in g:
            g[k] += note["counted"][k]
    g["notes"] = len(data["notes"])
    total_todo = sum(n["pending_count"] for n in data["notes"])

    data["global"] = g
    data["recent"] = recent[:cfg["recent_count"]]
    data["stagnant"] = stagnant
    data["pending"] = pending
    data["pending_count"] = total_todo
    data["percent"] = round(g["written"] / g["planned"] * 100 if g["planned"] else 0, 1)
    # 确认完成率：从「已写」里扣掉被标为待补的小节（三维标记里任一维度待补即算）
    conf_written = sum(max(n["counted"]["written"] - n["pending_count"], 0)
                       for n in data["notes"])
    data["confirmed_written"] = conf_written
    data["confirmed_percent"] = round(
        conf_written / g["planned"] * 100 if g["planned"] else 0, 1)
    data["chapter_todo_count"] = sum(n["chapter_todo_count"] for n in data["notes"])
    data["hint_count"] = sum(n["hint_count"] for n in data["notes"])
    data["suspects"] = suspects
    data["chapter_pending"] = chapter_pending
    return data


def migrate_marks(marks, data):
    """目录改名后迁移标记：先按文件名唯一匹配，再按内容指纹。

    匹配不到的保留记录并标记失效，不自动删除。
    """
    leaves = {}
    by_name = {}
    for note in data["notes"]:
        for top in note["tops"]:
            for leaf in collect_leaves(top):
                leaves[leaf["id"]] = leaf
                by_name.setdefault(Path(leaf["path"]).name, []).append(leaf)

    entries = marks["entries"]
    moved = 0
    stale = []
    for old_id in list(entries.keys()):
        if old_id in leaves:
            continue
        rec = entries[old_id]
        base = Path(old_id).name
        cands = by_name.get(base, [])
        target = None
        if len(cands) == 1:
            target = cands[0]
        elif len(cands) > 1:
            fp = rec.get("fingerprint")
            if fp:
                for c in cands:
                    if content_fingerprint(Path(c["path"])) == fp:
                        target = c
                        break
        if target is not None and target["id"] not in entries:
            entries[target["id"]] = rec
            del entries[old_id]
            moved += 1
        else:
            stale.append(old_id)

    marks["stale"] = stale
    return moved


def merge_marks(local, incoming):
    """把导入的标记并入本地（设计 8.3：按时间戳合并，不丢任一侧记录）。

    条目级没有各自的时间戳，所以冲突时以**整体 updated 较新的一方**为准；
    只有一侧存在的条目一律保留（并集）。stale 列表取并集。
    """
    local = local if isinstance(local, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    newer = str(incoming.get("updated") or "") >= str(local.get("updated") or "")
    out = default_marks()
    for sec in ("entries", "nodes"):
        a = local.get(sec) or {}
        b = incoming.get(sec) or {}
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        merged = {}
        for k in set(a) | set(b):
            if k in a and k in b:
                merged[k] = b[k] if newer else a[k]
            elif k in b:
                merged[k] = b[k]
            else:
                merged[k] = a[k]
        out[sec] = merged
    out["stale"] = sorted(set(local.get("stale") or [])
                          | set(incoming.get("stale") or []))
    return out


# ---------------------------------------------------------------- 导出层

DIM_NAME = {"env": "环境", "body": "正文", "proof": "证明"}
REASON_TEXT = {
    "included": "已纳入编译",
    "not_compiled": "未纳入编译但有内容",
    "empty_uncompiled": "未纳入编译且无内容",
    "manual_include": "手动强制计入",
    "manual_exclude": "手动强制排除",
    "parent_excluded": "因上级被排除",
}


def build_report(data):
    """生成 Markdown 进度报告。"""
    out = []
    out.append("# 写作进度报告")
    out.append("")
    out.append(f"生成时间：{data['scanned_at']}")
    out.append(f"工作区：`{data['root']}`")
    out.append("")

    g = data["global"]
    out.append("## 全库概况")
    out.append("")
    out.append("| 指标 | 数值 |")
    out.append("| --- | --- |")
    out.append(f"| 笔记数 | {g['notes']} |")
    out.append(f"| 规划小节 | {g['planned']} |")
    out.append(f"| 已写小节 | {g['written']} |")
    out.append(f"| 已建空壳 | {g['empty']} |")
    out.append(f"| 未建 | {g['missing']} |")
    out.append(f"| 定理环境 | {g['envs']} |")
    out.append(f"| 结构进度 | {data['percent']}% |")
    out.append(f"| 确认完成率 | {data['confirmed_percent']}% |")
    out.append(f"| 待补小节 | {data['pending_count']} |")
    out.append(f"| 整章待补 | {data['chapter_todo_count']} |")
    out.append(f"| 值得留意 | {data['hint_count']} |")
    out.append("")

    out.append("## 各笔记进度")
    out.append("")
    out.append("| 笔记 | 计入/排除章 | 规划 | 已写 | 进度 | 确认 | 待补 | 未编译章 |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for n in data["notes"]:
        c = n["counted"]
        inc = len(n["tops"]) - n["excluded_count"]
        nc = sum(1 for t in n["tops"]
                 if t.get("decision_reason") == "not_compiled")
        out.append(f"| {n['title']} | {inc} / {n['excluded_count']} | "
                   f"{c['planned']} | {c['written']} | {n['percent']}% | "
                   f"{n['confirmed_percent']}% | "
                   f"{n['pending_count']} | {nc} |")
    out.append("")

    out.append("## 待补清单")
    out.append("")
    if data["pending"]:
        cur = None
        for p in data["pending"]:
            if p["note"] != cur:
                cur = p["note"]
                out.append(f"### {cur}")
                out.append("")
            dims = " / ".join(DIM_NAME.get(d, d) for d in p["dims"])
            out.append(f"- {p['title']} —— {dims}")
        out.append("")
    else:
        out.append("暂无。")
        out.append("")

    out.append("## 整章待补")
    out.append("")
    if data.get("chapter_pending"):
        cur = None
        for p in data["chapter_pending"]:
            if p["note"] != cur:
                cur = p["note"]
                out.append(f"### {cur}")
                out.append("")
            out.append(f"- {p['title']}")
        out.append("")
    else:
        out.append("暂无。")
        out.append("")

    out.append("## 值得留意")
    out.append("")
    if data.get("suspects"):
        cur = None
        for s in data["suspects"]:
            if s["note"] != cur:
                cur = s["note"]
                out.append(f"### {cur}")
                out.append("")
            mark = "（编译层面）" if s["level"] == HINT_HARD else ""
            out.append(f"- {s['title']}{mark} —— " + "；".join(s["texts"]))
        out.append("")
    else:
        out.append("暂无。")
        out.append("")

    out.append("## 未启用章节（不计入进度）")
    out.append("")
    rows = []
    for n in data["notes"]:
        for t in n["tops"]:
            if not t.get("decision"):
                rows.append((n["name"], t))
    if rows:
        out.append("| 笔记 | 章 | 文件数 | 原因 |")
        out.append("| --- | --- | --- | --- |")
        for name, t in rows:
            out.append(f"| {name} | {t.get('view_title') or t['name']} | "
                       f"{t['stats']['leaves']} | "
                       f"{REASON_TEXT.get(t.get('decision_reason'), '')} |")
    else:
        out.append("无。")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 服务层

STATE = {
    "cfg": None,
    "data": None,
    "marks": None,
    "settings": None,
    "lock": threading.Lock(),
}


def detect_texstudio():
    """探测 TeXStudio 可执行文件路径：先查注册表，再查常见位置。"""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r".tex") as k:
                progid = winreg.QueryValueEx(k, "")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                progid + r"\shell\open\command") as k:
                cmd = winreg.QueryValueEx(k, "")[0]
            m = re.search(r'"([^"]+\.exe)"', cmd)
            if m and Path(m.group(1)).exists():
                return m.group(1)
        except Exception:
            pass
    for cand in (r"C:\Program Files\texstudio\texstudio.exe",
                 r"C:\Program Files (x86)\texstudio\texstudio.exe"):
        if Path(cand).exists():
            return cand
    return ""


def open_in_texstudio(cfg, target):
    """用 TeXStudio 打开工作区内的文件。返回 (成功?, 说明)。"""
    p = Path(target)
    if not p.is_absolute():
        p = cfg["root"] / target
    try:
        p.resolve().relative_to(cfg["root"].resolve())
    except ValueError:
        return False, "路径不在工作区范围内，已拒绝"
    except OSError:
        return False, "路径解析失败"
    if not p.exists():
        return False, f"文件不存在：{p.name}"
    exe = cfg.get("texstudio") or detect_texstudio()
    if not exe:
        return False, "未找到 TeXStudio，请在 progress.conf 中指定 texstudio 路径"
    try:
        subprocess.Popen([exe, str(p)])
    except OSError as e:
        return False, f"调起失败：{e}"
    return True, "已在 TeXStudio 中打开"


def ensure_view(force=False):
    """确保已有扫描结果；force 时重新扫描。

    层级模式是一次扫描的输入（决定标题落在哪个命令、怎么编号），所以改设置后
    必须重扫 —— 调用方把 force 置真即可。设置本身每回都重新下发，
    免得页面拿到上一次扫描时的旧值。
    """
    with STATE["lock"]:
        if STATE["settings"] is None:
            STATE["settings"] = load_settings()
        if STATE["data"] is None or force:
            data = scan_all(STATE["cfg"], STATE["settings"])
            marks = load_marks()
            moved = migrate_marks(marks, data)
            if moved:
                save_marks(marks)
            apply_marks(data, marks, STATE["cfg"])
            STATE["data"] = data
            STATE["marks"] = marks
        STATE["data"]["settings"] = public_settings(STATE["settings"])
        STATE["data"]["level_modes"] = level_mode_choices()
    return STATE["data"]


def reapply_view():
    """标记变更后重新计算，不重扫磁盘。"""
    with STATE["lock"]:
        apply_marks(STATE["data"], STATE["marks"], STATE["cfg"])
    return STATE["data"]


def entry_slot(marks, node_id):
    """取（或创建）某小节的标记记录。"""
    return marks["entries"].setdefault(node_id, {})


class Handler(BaseHTTPRequestHandler):
    server_version = "ProgressTracker/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    # -- 工具

    def _send(self, body, ctype="application/json; charset=utf-8", status=200,
              extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False), status=status)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _cfg(self):
        return STATE["cfg"]

    # -- 路由

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if path in ("/", "/index.html"):
            self._serve_ui()
        elif path == "/api/data":
            self._json(ensure_view(force="refresh" in qs))
        elif path == "/api/refresh":
            self._json(ensure_view(force=True))
        elif path == "/api/report":
            self._serve_report()
        elif path == "/api/marks/export":
            self._serve_marks_export()
        elif path == "/api/ping":
            self._json({"ok": True, "app": "progress", "version": VERSION})
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/entry":
            self._api_entry(body)
        elif path == "/api/chapter":
            self._api_chapter(body)
        elif path == "/api/marks/import":
            self._api_marks_import(body)
        elif path == "/api/open":
            ok, msg = open_in_texstudio(self._cfg(), body.get("path", ""))
            self._json({"ok": ok, "message": msg})
        elif path == "/api/settings":
            self._api_settings(body)
        elif path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json({"error": "not found"}, status=404)

    # -- 具体处理

    def _serve_ui(self):
        if not UI_PATH.exists():
            self._send("<h1>progress_ui.html 缺失</h1>",
                       ctype="text/html; charset=utf-8", status=500)
            return
        self._send(UI_PATH.read_text(encoding="utf-8"),
                   ctype="text/html; charset=utf-8")

    def _serve_report(self):
        data = ensure_view()
        md = build_report(data)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        self._send(md, ctype="text/markdown; charset=utf-8", extra={
            "Content-Disposition":
                f'attachment; filename="progress-report-{stamp}.md"'})

    def _apply_entry(self, slot, body):
        """把一次请求的内容写进某条小节记录，返回该记录是否还有内容。"""
        if "marks" in body and isinstance(body["marks"], dict):
            cur = slot.setdefault("marks", {})
            for d in MARK_DIMS:
                v = body["marks"].get(d)
                if v in (MARK_DONE, MARK_TODO):
                    cur[d] = v
        if "note" in body:
            slot["note"] = str(body["note"])[:2000]
        if "todos" in body and isinstance(body["todos"], list):
            todos = []
            for t in body["todos"][:100]:
                if isinstance(t, dict) and t.get("text"):
                    todos.append({"text": str(t["text"])[:300],
                                  "done": bool(t.get("done"))})
            slot["todos"] = todos
        if "planned" in body:
            slot["planned"] = bool(body["planned"])
        return bool(slot.get("marks") or slot.get("note")
                    or slot.get("todos") or slot.get("planned"))

    def _api_entry(self, body):
        """写小节的标记 / 备注 / 待办 / 计划。

        支持批量：body 里给 `ids`（数组）即把同一份内容应用到全部小节 ——
        用于「把整章无 proof 的小节一次标为证明待补」这类操作。
        """
        ids = body.get("ids")
        if isinstance(ids, list):
            ids = [str(i) for i in ids if str(i)][:2000]
        else:
            one = body.get("id") or ""
            ids = [one] if one else []
        if not ids:
            self._json({"ok": False, "message": "缺少 id"}, status=400)
            return
        with STATE["lock"]:
            for node_id in ids:
                slot = entry_slot(STATE["marks"], node_id)
                if not self._apply_entry(slot, body):
                    STATE["marks"]["entries"].pop(node_id, None)
            save_marks(STATE["marks"])
        data = reapply_view()
        if len(ids) > 1:
            data["changed"] = len(ids)
        self._json(data)

    def _api_chapter(self, body):
        """写顶层 / 目录节点的手动覆盖（计入范围）与章级标记。

        mode = auto / force_include / force_exclude；mark = true / false
        （章级「整章待补」，与小节级待补汇总并存、语义不同）。
        """
        node_id = body.get("id") or ""
        mode = body.get("mode")
        mark = body.get("mark")
        if not node_id or (mode is None and mark is None):
            self._json({"ok": False, "message": "参数不合法"}, status=400)
            return
        if mode is not None and mode not in ("auto", "force_include",
                                             "force_exclude"):
            self._json({"ok": False, "message": "参数不合法"}, status=400)
            return
        with STATE["lock"]:
            nodes = STATE["marks"]["nodes"]
            rec = dict(nodes.get(node_id) or {})
            if mode is not None:
                if mode == "auto":
                    rec.pop("mode", None)
                    rec.pop("manual", None)
                else:
                    rec["mode"] = mode
                    rec["manual"] = True
            if mark is not None:
                if mark:
                    rec["chapter_mark"] = True
                else:
                    rec.pop("chapter_mark", None)
            if rec:
                nodes[node_id] = rec
            else:
                nodes.pop(node_id, None)
            save_marks(STATE["marks"])
        self._json(reapply_view())

    def _serve_marks_export(self):
        """导出标记数据（进度标记 / 备注 / 待办 / 章级设置）为 JSON 文件。"""
        ensure_view()
        with STATE["lock"]:
            payload = json.dumps(STATE["marks"], ensure_ascii=False, indent=2)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        self._send(payload, ctype="application/json; charset=utf-8", extra={
            "Content-Disposition":
                f'attachment; filename="progress-marks-{stamp}.json"'})

    def _api_marks_import(self, body):
        """导入标记数据，与本地按时间戳合并（不丢任一侧记录）。"""
        incoming = body.get("marks") if isinstance(body.get("marks"), dict) else body
        if not isinstance(incoming, dict) or not any(
                k in incoming for k in ("entries", "nodes")):
            self._json({"ok": False, "message": "文件内容不是标记数据"},
                       status=400)
            return
        with STATE["lock"]:
            before = len(STATE["marks"]["entries"])
            STATE["marks"] = merge_marks(STATE["marks"], incoming)
            if STATE["data"] is not None:
                migrate_marks(STATE["marks"], STATE["data"])
            save_marks(STATE["marks"])
            after = len(STATE["marks"]["entries"])
            added = max(after - before, 0)
        data = reapply_view()
        data["merged"] = {"entries": after, "added": added}
        self._json(data)

    def _api_settings(self, body):
        """保存设置。层级模式变了要重扫（标题与编号都随之改变）。"""
        changed_levels = False
        with STATE["lock"]:
            settings = STATE["settings"] or load_settings()
            if "show_unused" in body:
                settings["show_unused"] = bool(body["show_unused"])
            lv = body.get("note_levels")
            if isinstance(lv, dict):
                saved = settings.setdefault("note_levels", {})
                before = dict(saved)
                for k, v in lv.items():
                    name = str(k)
                    spec = str(v or "")
                    if not spec or spec == "auto":
                        saved.pop(name, None)
                    elif parse_levels(spec):
                        saved[name] = spec
                    else:
                        self._json({"ok": False,
                                    "message": f"层级模式不合法：{spec}"}, status=400)
                        return
                changed_levels = (before != saved)
            save_settings(settings)
            STATE["settings"] = settings
        self._json(ensure_view(force=changed_levels))


def make_server(cfg):
    """创建服务；端口被占用时顺延。"""
    host = cfg["host"]
    port = cfg["port"]
    for i in range(10):
        try:
            srv = ThreadingHTTPServer((host, port + i), Handler)
            return srv, port + i
        except OSError:
            continue
    raise OSError("连续 10 个端口均被占用，无法启动服务")


def service_alive(cfg):
    """探测是否已有本服务在运行。"""
    import urllib.request
    import urllib.error
    for i in range(10):
        url = f"http://{cfg['host']}:{cfg['port'] + i}/api/ping"
        try:
            with urllib.request.urlopen(url, timeout=0.35) as r:
                info = json.loads(r.read().decode("utf-8"))
            if info.get("app") == "progress":
                return cfg["port"] + i
        except Exception:
            continue
    return 0


# ---------------------------------------------------------------- CLI（调试）

def cmd_rescan(cfg):
    data = scan_all(cfg, load_settings())
    marks = load_marks()
    moved = migrate_marks(marks, data)
    if moved:
        save_marks(marks)
        print(f"  [迁移] {moved} 条标记已跟随目录改名。")
    apply_marks(data, marks, cfg)

    print("=" * 98)
    print("写作进度扫描（已应用计入规则与手动覆盖）")
    print("=" * 98)
    print(f"{'笔记':<34}{'计入/排除':>11}{'规划':>7}{'已写':>7}{'空壳':>6}"
          f"{'未建':>6}{'环境':>7}{'进度':>9}{'待补':>6}")
    for n in data["notes"]:
        c = n["counted"]
        inc = len(n["tops"]) - n["excluded_count"]
        tag = f"{inc} / {n['excluded_count']}"
        print(f"{n['name']:<34}{tag:>11}{c['planned']:>7}{c['written']:>7}"
              f"{c['empty']:>6}{c['missing']:>6}{c['envs']:>7}"
              f"{n['percent']:>8.1f}%{n['pending_count']:>6}")
    g = data["global"]
    print("-" * 98)
    print(f"{'合计':<34}{'':>11}{g['planned']:>7}{g['written']:>7}"
          f"{g['empty']:>6}{g['missing']:>6}{g['envs']:>7}"
          f"{data['percent']:>8.1f}%{data['pending_count']:>6}")

    print("\n层级模式（自动识别；可在设置页里逐本指定）：")
    for n in data["notes"]:
        src = "指定" if n.get("level_source") == "manual" else "自动"
        print(f"  {n['name']:<34}{src}  {n.get('level_mode', ''):<30}"
              f"{n.get('level_names', '')}")

    if data["stagnant"]:
        line = "、".join(f"{s['name']}（{s['days']} 天）" for s in data["stagnant"])
        print(f"\n停滞提醒：{line}")


def parse_argv(argv):
    opt = {"rescan": False, "report": "", "port": 0, "no_browser": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--rescan":
            opt["rescan"] = True
        elif a == "--report":
            opt["report"] = (argv[i + 1] if i + 1 < len(argv)
                             else "progress_report.md")
            i += 1
        elif a == "--port":
            try:
                opt["port"] = int(argv[i + 1])
                i += 1
            except (IndexError, ValueError):
                pass
        elif a in ("--no-browser", "-n"):
            opt["no_browser"] = True
        i += 1
    return opt


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    opt = parse_argv(argv)
    cfg = load_conf()
    if opt["port"]:
        cfg["port"] = opt["port"]
    STATE["cfg"] = cfg
    STATE["settings"] = load_settings()

    if opt["rescan"]:
        t0 = time.time()
        cmd_rescan(cfg)
        print(f"\n耗时 {time.time() - t0:.3f} 秒")
        return 0

    if opt["report"]:
        data = ensure_view()
        out = Path(opt["report"])
        out.write_text(build_report(data), encoding="utf-8", newline="")
        print(f"报告已导出：{out}")
        return 0

    print(f"写作进度追踪表 v{VERSION}")
    print(f"  工作区：{cfg['root']}")

    running = service_alive(cfg)
    if running:
        url = f"http://{cfg['host']}:{running}/"
        print(f"  服务已在运行：{url}")
        if not opt["no_browser"]:
            webbrowser.open(url)
        return 0

    try:
        srv, port = make_server(cfg)
    except OSError as e:
        print(f"  启动失败：{e}")
        return 1

    url = f"http://{cfg['host']}:{port}/"
    print(f"  服务地址：{url}")
    print("  按 Ctrl+C，或用页面上的「退出服务」结束。")

    t0 = time.time()
    data = ensure_view()
    print(f"  首次扫描完成，耗时 {time.time() - t0:.2f} 秒，"
          f"共 {data['global']['notes']} 本笔记。")

    if cfg["auto_open"] and not opt["no_browser"]:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
