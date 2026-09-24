#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
new_note.py — 从模板创建一本新笔记

把「开始一本新笔记」的一串手工操作收敛成一步：复制骨架 → 按 Markdown 大纲生成
`Content/` 骨架 → `git init` → 装提交前钩子 → 首次提交 →（可选）建远程并推送。

`git init` 之后会自动把 `guard/hooks/pre-commit` 装进新仓库，把「提交前本机信息扫描」
一并带过去，不必事后手工补装。钩子靠相对路径逐级查找 `guard/check_sensitive.py`，
找不到时放行，所以不会因为换机器而阻断提交。

**不带参数运行会进入交互式引导**（推荐，从总面板进来就是这条路）：依次询问笔记名、
模板、是否建远程、大纲 md 文件，然后给出确认预览。

用法
----
    python new_note.py                        # 交互式引导
    python new_note.py <笔记名>                # 只建本地仓库（不生成章节骨架）
    python new_note.py <笔记名> --push         # 同时建 GitHub 仓库并推送
    python new_note.py <笔记名> --template <目录>
    python new_note.py <笔记名> --outline <大纲.md>  # 按 md 大纲生成骨架
    python new_note.py <笔记名> --outline <大纲.md> --levels textbook
    python new_note.py <笔记名> --dry-run      # 只显示将要做什么

大纲 md 的写法
--------------
文件头是可省的元信息块（`---` 包围、`键: 值`），随后用 **Markdown 标题的层级**表示
目录层级：最浅的一层就是最外层，`#` / `##` / `###` … 依次往下，行内用 `|` 分隔
「目录名」与「中译名」（中译名可省，省了就退用目录名）：

    ---
    name: Algebra
    template: Math-Note
    levels: part, chapter, section
    ---

    # Description_of_Formal_Mathematic | 数学的形式化描述
    ## Terms_and_relations | 项与关系
    ### Terms | 项
    ### Formative_constructions | 合式构造

元信息块里可写的键：`name`（笔记名）、`template`（模板目录名）、`levels`（层级命令）。

层级命令（levels）
------------------
**写在 md 头部**（`levels: …`），工具不会另外问你。它决定每层目录用哪个 LaTeX 标题
命令：命令按**由外到内**排列，必须是 LaTeX 章节命令的合法递降，管几个命令就是几层
目录；末层是 `.tex` 文件，前面各层是目录。

    levels: part, chapter, section      # 1 级 \part、2 级 \chapter、3 级 \section

也可以写下面这些简写名：

| 简写名          | 等价于                                | 适用                            |
|-----------------|---------------------------------------|---------------------------------|
| `bourbaki`      | `part, chapter, section`              | 层1 目录＝原书章（现有笔记写法）|
| `textbook`      | `chapter, section, subsection`        | 常见教材：层1 目录＝章          |
| `textbook-part` | `part, chapter, section, subsection`  | 分「部」的大部头                |
| `two-level`     | `chapter, section`                    | 两层：讲义 / 小册子             |
| `article`       | `section, subsection`                 | 文章式：不分章                  |
| `grouped`       | `chapter, -, section`                 | 中间层只作分组、不产生标题      |

`-` 表示「这一层只作分组、不产生标题」：

    levels: part, chapter, section, subsection
    levels: chapter, -, section          # ＝ grouped

**不写 levels 也能跑**：脚本按标题层数推一个最接近的（1 层→`section`、2 层→`chapter,
section`、3 层及以上→`part` 起顺延），交互式会问一句「用不用 / 要不要代写进 md」，
命令行则打印推断值并提示怎么写进 md。**写了但与结构层数不符**时同理：会告诉你按结构
应该是什么，让你决定改 md 还是照推断走。层数实在凑不出合法序列时，才会请你改 md。
（`--levels` 可以命令行覆盖，一般用不着。）

标题命令的落点（本模板系既有约定）：

    main.tex                          \part{层1中译} 之类 ＋ 紧跟其 \input
    Content/<层1>/index.tex           只有 \input（指向各层2）
    Content/<层1>/<层2>/index.tex     只有 \input（指向各层3）
    Content/…/<层3>.tex               \chapter{层2中译} ＋ \section{层3中译}
                                      （层2 的标题写在「它第一个子项的第一个叶子」里）

其余规则：

- **最外层的标题命令写在 `main.tex` 里**（`\part{…}` 与它的 `\input` 配成一对），
  与现有笔记的 main.tex 完全一致；层2 及更深层的标题写进内容文件。
- **编号自动补**：目录名里不用手写 `1_`，脚本按出现顺序补；写了 `3_xxx` 就照用。
- 目录名限 ASCII（字母/数字/下划线/连字符），中文只出现在 `|` 右侧。
- 某层节点下面没有更细的标题时，它的标题写进**该层自己的 index.tex**（占位，便于先建骨架）。
- 标题层级数必须与 levels 的命令数相同，且不能跳级（`#` 之后只能接 `##`）。
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAINTAIN_DIR = Path(__file__).resolve().parent
TOOLS_DIR = MAINTAIN_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MANAGER_CONF = TOOLS_DIR / "manager" / "manager.conf"
HOOK_SRC = TOOLS_DIR / "guard" / "hooks" / "pre-commit"

COPY_FILES = [
    ".gitignore", ".gitattributes",
    "structure.sty", "quiver.sty", "main.tex",
    "README.md", "ChangeLog.md",
    "commit.py", "commit.sh", "commit.md",
    "setup_mode.py", "setup_mode.md",
    "symbols.md", "术语对照表.md", "模板使用规范.md", "正文写作规范.md",
]
COPY_DIRS = ["Content", "ExerciseBook", "Figures"]

SKIP_NAMES = {"__pycache__"}
SKIP_SUFFIX = {".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls",
               ".fdb_latexmk", ".synctex.gz", ".xdv", ".listing", ".pdf", ".nav",
               ".snm", ".vrb"}

# ---------------------------------------------------------------- 层级模式

# LaTeX 章节命令，由外到内。levels 必须是它的**保持次序的子序列**，
# 否则 \\chapter 出现在 \\section 之后这类顺序错误会让编号彻底乱掉。
SECTION_CMDS = ["part", "chapter", "section", "subsection",
                "subsubsection", "paragraph", "subparagraph"]

#: 层级预设：(命令序列, 说明)。面板与报错提示都读这里，改预设只动这一处。
LEVEL_PRESETS = {
    "bourbaki":      ("part,chapter,section",
                      "层1 目录＝原书章（现有笔记的写法）"),
    "textbook":      ("chapter,section,subsection",
                      "常见教材：层1 目录＝章"),
    "textbook-part": ("part,chapter,section,subsection",
                      "分「部」的大部头"),
    "two-level":     ("chapter,section",
                      "两层：讲义 / 小册子"),
    "article":       ("section,subsection",
                      "文章式：不分章"),
    "grouped":       ("chapter,-,section",
                      "中间层只作分组、不产生标题"),
}


class OutlineError(Exception):
    """大纲文件本身有问题（格式 / 层级 / 目录名），由调用方打印提示。"""


def print_level_presets():
    print("  层级模式（levels）写在 md 头部，它决定每层目录用哪个 LaTeX 标题命令。")
    print("  写法是「由外到内」列命令，或写下面的简写名：")
    print()
    for name, (seq, desc) in LEVEL_PRESETS.items():
        print(f"    {name:<14} = {seq:<36} {desc}")
    print()
    print("  例：md 头部加一行 `levels: part, chapter, section`（＝ bourbaki），")
    print("      意思是一级目录 \\part、二级 \\chapter、三级 \\section。")
    print("      `-` 表示该层只作分组、不产生标题命令。")
    print("  不写也行：脚本会按标题层数推一个最接近的，推不出才要你补。")


def resolve_levels(spec):
    """把 levels 字段（预设名 / 逗号命令序列）解析成命令列表。

    返回 [cmd, ...]，其中 `-` 表示该层不产生标题命令。
    """
    raw = (spec or "").strip()
    if not raw:
        raise OutlineError("没有指定层级模式 levels")
    if raw.lower() in LEVEL_PRESETS:
        raw = LEVEL_PRESETS[raw.lower()][0]
    cmds = [c.strip().lower() for c in raw.split(",") if c.strip()]
    if not cmds:
        raise OutlineError(f"levels 解析为空：{spec!r}")
    for c in cmds:
        if c == "-":
            continue
        if c not in SECTION_CMDS:
            raise OutlineError(
                f"不认识的章节命令 {c!r}；可用：{'、'.join(SECTION_CMDS)}（或用 `-` 表示分组层）")
    pos = [SECTION_CMDS.index(c) for c in cmds if c != "-"]
    if pos != sorted(pos) or len(set(pos)) != len(pos):
        raise OutlineError(f"层级命令顺序不对（应由外到内、不重复）：{', '.join(cmds)}")
    return cmds


# ------------------------------------------- 层级模式的「读懂 / 推断 / 写回 md」

#: 按层数套用惯例起点：1 层→section，2 层→chapter，3 层及以上→part 起顺延。
#: 3 层给 part/chapter/section 是照现有笔记的写法（Bourbaki 式）。
LEVEL_START_BY_DEPTH = {1: 2, 2: 1, 3: 0}


def describe_levels(levels):
    """`part, chapter, section` → 带人话说明的一行。"""
    named = "、".join(f"{i} 级 \\{c}" for i, c in enumerate(levels, 1) if c != "-")
    dash = [str(i) for i, c in enumerate(levels, 1) if c == "-"]
    out = ", ".join(levels) + (f"（{named}）" if named else "")
    if dash:
        out += f"；第 {'、'.join(dash)} 层只作分组、不产生标题"
    return out


def levels_mentioned(text):
    """md 文本里**字面提到**的章节命令（如注释里写了 `\\chapter`），由外到内去重。"""
    names = {("chapter" if m.group(1) == "appendixchapter" else m.group(1))
             for m in re.finditer(r"\\(part|chapter|appendixchapter|section"
                                  r"|subsection|subsubsection)\b", text)}
    return [c for c in SECTION_CMDS if c in names]


def infer_levels(tree, text=""):
    """按结构推一个「尽量匹配」的层级模式。返回 (levels 或 None, 依据说明)。

    None 表示确实推不出来（层数超出 LaTeX 章节层级上限），只能请用户改 md。
    """
    depth = tree_depth(tree)
    if not depth:
        return None, "大纲里没有任何标题"
    if depth > len(SECTION_CMDS):
        return None, f"标题有 {depth} 层，超过 LaTeX 章节层级上限（{len(SECTION_CMDS)} 个）"

    mentioned = levels_mentioned(text)
    if len(mentioned) == depth:
        return mentioned, f"md 文本里正好提到这 {depth} 个命令"

    start = LEVEL_START_BY_DEPTH.get(depth, 0)
    levels = SECTION_CMDS[start:start + depth]
    if len(levels) != depth:
        return None, f"标题有 {depth} 层，凑不出合法的层级命令序列"
    how = "与现有笔记的写法一致" if levels == ["part", "chapter", "section"] else "按层数套用"
    return levels, f"按结构（{depth} 层）推断，{how}"


def set_levels_in_md(path, levels):
    """把 `levels:` 写进 md 头部（没有元信息块就补一个）。返回 (是否成功, 说明)。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读不到：{e}"
    line = "levels: " + ", ".join(levels)
    lines = text.splitlines()

    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            return False, "md 头部的 `---` 没有配对的结束标记，先手工补上"
        for k in range(1, end):
            if re.match(r"^\s*levels\s*:", lines[k]):
                lines[k] = line
                break
        else:
            lines.insert(end, line)
    else:
        lines = ["---", line, "---", ""] + lines

    try:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    except OSError as e:
        return False, f"写不进去：{e}"
    return True, f"已把 `{line}` 写进 {p.name}"


def ask_levels_choice():
    """采用推断值 / 写回 md / 先去改 md。返回 'use' / 'write' / 'skip'。"""
    while True:
        try:
            ans = input("  采用这个层级？[Y] 用 / [w] 写进 md 再用 / [n] 先去改 md"
                        "（回车＝Y）：")
        except (EOFError, KeyboardInterrupt):
            return "skip"
        a = ans.strip().lower()
        if a in ("", "y", "yes"):
            return "use"
        if a in ("w", "write"):
            return "write"
        if a in ("n", "no"):
            return "skip"
        print("  请回答 Y / w / n。")


def resolve_levels_for_md(path, meta, tree, interact=True):
    """确定这份大纲 md 用哪个层级模式。返回 levels；None 表示需要用户先改 md。

    顺序：md 里写的 levels → 结构推断。两者冲突或推断不出时，交互式交给人选
    （可以代写回 md），命令行则给出明确的改法。
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        text = ""

    def need_fix(msg):
        print(f"  ✗ {msg}")
        print("    请在 md 头部（`---` 之间）补一行，例如：")
        print("        levels: part, chapter, section")
        print("    含义：一级目录用 \\part、二级用 \\chapter、三级用 \\section。")
        print("    也可写简写名（bourbaki / textbook / two-level / article / grouped），")
        print("    或 `-` 表示某层只作分组。完整清单见 new_note.py 的模块文档。")
        return None

    written = (meta.get("levels") or "").strip()
    cand, why = infer_levels(tree, text)
    depth = tree_depth(tree)

    if written:
        try:
            levels = resolve_levels(written)
        except OutlineError as e:
            if interact:
                return need_fix(f"md 里的 levels 有问题：{e}")
            print(f"✗ md 里的 levels 有问题：{e}")
            return None
        if len(levels) == depth:
            print(f"  层级模式：{describe_levels(levels)}（写在 md 头部）")
            return levels
        msg = (f"md 写了 {len(levels)} 个命令（{', '.join(levels)}），"
               f"但标题有 {depth} 层，两者必须一致")
        if not interact:
            print(f"✗ {msg}")
            if cand:
                print(f"  按结构应为：{', '.join(cand)}（{why}）")
            print("  请改 md 的 levels 行，或用 --levels 指定。")
            return None
        print(f"  ⚠ {msg}")
        if cand is None:
            return need_fix(f"{msg}；而且{why}")
        print(f"  按结构推断应为：{describe_levels(cand)}")
        print(f"  依据：{why}")
        choice = ask_levels_choice()
        if choice == "use":
            return cand
        if choice == "write":
            ok, info = set_levels_in_md(path, cand)
            print(f"  {'✓' if ok else '✗'} {info}")
            return cand if ok else None
        return need_fix("你选择先去改 md")

    # md 里没写 levels
    if cand is None:
        return need_fix(f"md 里没写 levels，而且{why}")
    print("  md 里没写 levels（层级模式）——")
    print(f"    按结构推断为：{describe_levels(cand)}")
    print(f"    依据：{why}")
    if not interact:
        print(f"    （想固定下来就在 md 头部加一行：levels: {', '.join(cand)}）")
        return cand
    choice = ask_levels_choice()
    if choice == "use":
        return cand
    if choice == "write":
        ok, info = set_levels_in_md(path, cand)
        print(f"  {'✓' if ok else '✗'} {info}")
        return cand if ok else None
    return need_fix("你选择先去改 md")


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout or "").strip(), (r.stderr or "").strip()


def read_conf(path):
    d = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def notes_root():
    cfg = read_conf(MANAGER_CONF)
    root = cfg.get("root", "")
    if root:
        p = Path(os.path.expandvars(root))
        if p.is_dir():
            return p
    guess = WORKSPACE / "LaTeX_Notes"
    return guess if guess.is_dir() else None


# ---------------------------------------------------------------- 大纲解析

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*\S)[ \t]*$")

#: 目录/文件名允许的形态：ASCII 开头，不含 Windows 非法字符与空白、反斜杠。
#: （允许点与逗号 —— 真实笔记里有 `1_K.u,_C` 这类文件名。）
DIR_NAME_RE = re.compile(r"^[A-Za-z0-9][^\\/:*?\"<>|\s]*$")

#: 旧「缩进 + |」格式的层级语义，等价于 grouped 预设（中间层只作分组）。
LEGACY_LEVELS = ["chapter", "-", "section"]


def parse_front_matter(text):
    """解析 md 头部的 `---` 元信息块，返回 (meta, 正文)。

    只认 `键: 值` 的单行写法，不引入 YAML 依赖；文件头没有 `---` 就当成没有元信息。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            meta = {}
            for ln in lines[1:i]:
                if ln.strip().startswith("#") or ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip("\"'")
            return meta, "\n".join(lines[i + 1:])
    raise OutlineError("开头的 `---` 没有配对的结束 `---`")


def make_node(body, where):
    """`目录名 | 中译名` → 节点。中译名可省，省了退用目录名。"""
    name, sep, label = body.partition("|")
    name = re.sub(r"\s+", "_", name.strip())
    label = label.strip() if sep else ""
    if not name:
        raise OutlineError(f"{where}：`|` 左边没写目录名")
    if not DIR_NAME_RE.match(name):
        raise OutlineError(
            f"{where}：目录名 {name!r} 不合规 —— 只能用英文/数字/下划线/连字符/点/逗号，"
            f"中文请写在 `|` 右边（如 `Terms | 项`）")
    return {"name": name, "label": label, "children": []}


def parse_md_outline(text):
    """解析 Markdown 大纲。返回 (树, 层级数)。

    `#` 是最外层，逐级往下（不跳级、必须从最浅的一层开始）。
    """
    heads = []
    for line_no, ln in enumerate(text.splitlines(), 1):
        m = HEADING_RE.match(ln)
        if m:
            heads.append((len(m.group(1)), m.group(2), line_no))
    if not heads:
        raise OutlineError("没有找到任何 Markdown 标题（形如 `# 标题`）")

    base = min(lv for lv, _, _ in heads)
    if heads[0][0] != base:
        raise OutlineError(f"第 {heads[0][2]} 行的标题不是最外层 —— "
                           f"大纲应从 `{'#' * base}` 开始写")
    depth = max(lv for lv, _, _ in heads) - base + 1

    root = []
    stack = [(base - 1, root)]      # stack[0][1] 就是根列表（别另建变量，见旧注释）
    for lv, body, line_no in heads:
        while len(stack) > 1 and lv <= stack[-1][0]:
            stack.pop()
        if lv > stack[-1][0] + 1:
            raise OutlineError(f"第 {line_no} 行跳级了：`{'#' * lv}` 前面缺 "
                               f"`{'#' * (lv - 1)}`")
        node = make_node(body, f"第 {line_no} 行")
        stack[-1][1].append(node)
        stack.append((lv, node["children"]))
    return root, depth


def parse_indent_outline(text):
    """旧格式（缩进 + `|`）解析成同样的树。"""
    stack = [(-1, [])]
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        node = make_node(raw.strip(), f"第 {line_no} 行")
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((indent, node["children"]))
    return stack[0][1]


def read_outline_file(path):
    """读大纲文件并解析。返回 (meta, 树, 层级命令列表 或 None)。

    Markdown 标题式与旧的缩进式都认：文件里有 `# 标题` 就是前者。
    md 里写了 levels 就直接解析出来返回（**层数是否与结构相符留给调用方判定** ——
    那里能给出「按结构应为 X」的建议，比在这里硬报错有用）；没写则返回 None。
    """
    text = Path(path).read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    if any(HEADING_RE.match(ln) for ln in text.splitlines()):
        tree, _depth = parse_md_outline(body)
        spec = meta.get("levels", "")
        return meta, tree, (resolve_levels(spec) if spec else None)

    tree = parse_indent_outline(body)
    return meta, tree, list(LEGACY_LEVELS)


def numbered_name(node, index):
    """给目录/文件名补编号前缀：显式写了 `3_xxx` 就照用，否则按层内序号补。"""
    return node["name"] if re.match(r"^\d+_", node["name"]) else f"{index}_{node['name']}"


def title_cmd(level, label):
    """该层的标题命令；`-`（分组层）或标题为空时返回 None。"""
    if level == "-" or not label:
        return None
    return f"\\{level}{{{label}}}"


def content_files(tree, levels):
    """列出结构将产生的文件（预览用）。"""
    out, depth = [], len(levels)

    def walk(node, prefix, i, index):
        name = numbered_name(node, index)
        here = f"{prefix}/{name}" if prefix else name
        if i == depth - 1:
            mark = f"   \\{levels[i]}" if levels[i] != "-" else "   （无标题）"
            out.append(f"Content/{here}.tex{mark}")
            return
        out.append(f"Content/{here}/index.tex")
        for k, child in enumerate(node["children"], 1):
            walk(child, here, i + 1, k)

    for j, chap in enumerate(tree, 1):
        walk(chap, "", 0, j)
    return out


def top_chapters(tree, levels):
    """main.tex 里每一组的 (\\input 路径, 中译名)。

    逐层目录时输入各自目录的 index；只有一层时，顶层节点本身就是叶子文件。
    """
    single = len(levels) == 1
    out = []
    for j, node in enumerate(tree, 1):
        name = numbered_name(node, j)
        path = f"./Content/{name}" if single else f"./Content/{name}/index"
        out.append((path, node["label"] or name))
    return out


def tree_depth(tree):
    """树的最大层数（顶层算 1 层）。"""
    if not tree:
        return 0
    return 1 + max((tree_depth(n["children"]) for n in tree), default=0)


def build_content(content_dir, tree, levels):
    """按树与层级命令生成章节目录、index.tex 与叶子文件。

    标题命令的落点：层1 的进 main.tex（见 rewrite_main_tex）；层2 及更深层的
    标题只在**该子树的第一个文件**里出现一次 —— 所以 `pending` 是所有兄弟共用
    的一个列表，被第一个叶子取走后清空。若某层节点下面没有更细的标题，
    它自己的标题就落在它自己的 index.tex 里（占位，便于先建骨架）。
    """
    depth = len(levels)

    def emit(node, prefix, i, index, pending):
        name = numbered_name(node, index)
        label = node["label"] or name
        here = f"{prefix}/{name}" if prefix else name
        title = title_cmd(levels[i], label)

        if i == depth - 1:                                    # 叶子：一个 .tex
            body = pending + ([title] if title else [])
            pending.clear()
            path = content_dir / f"{here}.tex"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(("\n".join(body) + "\n\n") if body else "",
                            encoding="utf-8", newline="")
            return f"\\input{{./Content/{here}}}"

        cur = content_dir / here                              # 目录
        cur.mkdir(parents=True, exist_ok=True)
        if title and i > 0:
            pending.append(title)
        inputs = [emit(child, here, i + 1, k, pending)
                  for k, child in enumerate(node["children"], 1)]
        if inputs:
            text = "\n".join(inputs) + "\n"
        elif pending:                                         # 空节点：就地落标题
            text = "\n".join(pending) + "\n"
            pending.clear()
        else:
            text = ""
        (cur / "index.tex").write_text(text, encoding="utf-8", newline="")
        return f"\\input{{./Content/{here}/index}}"

    for j, chap in enumerate(tree, 1):
        emit(chap, "", 0, j, [])


def rewrite_main_tex(main_tex, name, chapters, top_cmd=None):
    r"""更新 main.tex：标题，以及正文主体（`\mainmatter` … `\backmatter`）的章节骨架。

    `chapters` 是 [(层1目录名, 层1中译名), ...]，`top_cmd` 是最外层的标题命令
    （`-` 表示该层不产生标题）。有大纲时正文主体被重写成「标题命令 + `\input`」的
    成对分组，逐行对应现有笔记的 main.tex；**没有大纲时正文主体原样不动**，
    只把模板里那行 `\part{测试部分}` 改名成笔记名。
    """
    if not main_tex.is_file():
        return False
    text = main_tex.read_text(encoding="utf-8")
    # 标题里含 \textbf{}，必须贪婪匹配到行尾最后一个 }
    new = re.sub(r"\\title\{.*\}", f"\\\\title{{\\\\Huge\\\\textbf{{{name}}}}}",
                 text, count=1)
    new = new.replace("\\part{测试部分}", f"\\part{{{name}}}")

    m = re.search(r"(\\mainmatter[ \t]*\n)(.*?)(\s*\\backmatter)", new, flags=re.S)
    if m and chapters:
        groups = []
        for path, label in chapters:
            block = []
            if top_cmd and top_cmd != "-":
                block.append(f"\\{top_cmd}{{{label}}}")
            block.append(f"\\input{{{path}}}")
            groups.append("\n\n".join(block))
        # 首行补一个空行；尾部的空行由末组（含 \backmatter）自带
        new = new[:m.start()] + m.group(1) + "\n" + "\n\n".join(groups) \
            + m.group(3) + new[m.end():]

    main_tex.write_text(new, encoding="utf-8", newline="")
    return True


# ---------------------------------------------------------------- 复制

def copy_item(src, dst, dry):
    if src.is_file():
        if src.suffix.lower() in SKIP_SUFFIX or src.name in SKIP_NAMES:
            return
        if not dry:
            shutil.copy2(src, dst)
        return
    if not dry:
        dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        if child.name in SKIP_NAMES:
            continue
        copy_item(child, dst / child.name, dry)


def install_hook(target, dry):
    """把提交前扫描钩子装进新仓库的 `.git/hooks/`。

    钩子本身是纯 sh 脚本，靠相对路径逐级查找 `guard/check_sensitive.py`，
    不含任何本机路径，所以可以直接复制过去。

    返回 (ok, 说明)。装不上不算致命 —— 只提示，不中断建仓库流程。
    """
    dst = target / ".git" / "hooks" / "pre-commit"
    if not HOOK_SRC.is_file():
        return False, f"未找到钩子源文件，跳过：{HOOK_SRC}"
    if dry:
        return True, ".git/hooks/pre-commit（提交前本机信息扫描）"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK_SRC, dst)
        try:
            os.chmod(dst, 0o755)      # Windows 上近乎空操作，POSIX 上必需
        except OSError:
            pass
    except OSError as e:
        return False, f"安装失败：{e}"
    return True, ".git/hooks/pre-commit（提交前本机信息扫描）"


def strip_test_sections(root, dry):
    removed = []
    for p in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
        if p.is_dir() and "Test" in p.name:
            removed.append(p)
            if not dry:
                shutil.rmtree(p)
    if dry:
        return [str(p.relative_to(root)) for p in removed]
    for tex in root.rglob("*.tex"):
        try:
            text = tex.read_text(encoding="utf-8")
        except OSError:
            continue
        kept = [ln for ln in text.splitlines(keepends=True)
                if not (re.search(r"\\input\{(.+?)\}", ln)
                        and "Test" in re.search(r"\\input\{(.+?)\}", ln).group(1))]
        new = re.sub(r"\n{3,}", "\n\n", "".join(kept))
        if new != text:
            tex.write_text(new, encoding="utf-8", newline="")
    return [str(p.relative_to(root)) for p in removed]


# ---------------------------------------------------------------- 交互式引导

def ask(prompt, default=""):
    hint = f"（回车＝{default}）" if default else ""
    try:
        ans = input(f"  {prompt}{hint}：").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return ans or default


def read_outline_paste():
    """旧的手动粘贴入口（缩进 + `|`），语义等同 grouped 预设。"""
    print("  粘贴章节结构，用缩进表示层级，`|` 分隔目录名与中译名：")
    print("      Modules_over_Rings | 环上的模")
    print("        Basic_definitions | 基本定义")
    print("          Modules | 模")
    print("  单独一行 `END` 结束输入（直接回车表示不用结构）。\n")
    lines = []
    while True:
        try:
            ln = input("  > ")
        except (EOFError, KeyboardInterrupt):
            break
        if ln.strip().upper() == "END":
            break
        if not ln.strip() and not lines:
            break
        lines.append(ln)
    text = "\n".join(lines)
    return parse_indent_outline(text) if text.strip() else []


def choose_levels(default_spec=""):
    """手工挑层级模式（只在「手动粘贴大纲」这条路上用）。返回命令列表；取消返回 None。"""
    print()
    print_level_presets()
    for _ in range(3):
        spec = ask("\n写哪个层级模式（简写名或命令序列）", default_spec)
        if not spec:
            return None
        try:
            return resolve_levels(spec)
        except OutlineError as e:
            print(f"  ✗ {e}")
    return None


def check_depth(tree, levels):
    """标题层数必须与层级命令个数相同；不符时返回报错文本。"""
    depth = tree_depth(tree)
    if depth != len(levels):
        return (f"大纲有 {depth} 层，但层级模式给了 {len(levels)} 个命令"
                f"（{', '.join(levels)}）—— 两者必须相同")
    return None


def interactive():
    print("=" * 64)
    print("  从模板新建笔记")
    print("=" * 64)
    print()

    meta, tree, levels = {}, [], None
    outline_path = ask("大纲 md 文件路径（回车＝不生成骨架，输入 paste＝手动粘贴大纲）")
    paste = bool(outline_path) and outline_path.lower() == "paste"

    if outline_path and not paste:
        try:
            meta, tree, levels = read_outline_file(outline_path)
        except OSError as e:
            print(f"  ✗ 读不到大纲文件：{e}")
            return 1
        except OutlineError as e:
            print(f"  ✗ 大纲有问题：{e}")
            return 1
        if tree:
            # md 里没写 levels、或写的与结构不符 → 推断 + 让用户定
            if not levels or len(levels) != tree_depth(tree):
                levels = resolve_levels_for_md(outline_path, meta, tree, interact=True)
                if not levels:
                    return 1
            print(f"  已读入 {len(tree)} 个顶层节点，共 "
                  f"{len(content_files(tree, levels))} 个文件")
        else:
            print("  ⚠ 大纲里没有任何标题，按「不生成骨架」处理。")
    levels = levels or []

    name = ask("\n笔记名（字母开头，可含数字/下划线/连字符）", meta.get("name", ""))
    if not name:
        print("  已取消。")
        return 1

    templates = []
    tdir = WORKSPACE / "Template"
    if tdir.is_dir():
        templates = [d.name for d in sorted(tdir.iterdir())
                     if d.is_dir() and (d / "main.tex").is_file()]
    default_tpl = meta.get("template") or ("Math-Note" if "Math-Note" in templates
                                           else (templates[0] if templates else ""))
    if templates:
        print(f"\n  可用模板：{', '.join(templates)}")
    tpl = ask("模板目录名", default_tpl)
    if not tpl:
        print("  已取消。")
        return 1

    push = ask("\n同时建 GitHub 仓库并推送？[y/N]", "N").lower() in ("y", "yes")

    if paste:
        print()
        tree = read_outline_paste()
        if tree:
            cand, why = infer_levels(tree)
            if cand:
                print(f"  按结构（{tree_depth(tree)} 层）推断层级为：{describe_levels(cand)}")
                print(f"  依据：{why}")
                try:
                    a = input("  采用？[Y/n]（选 n 就手工挑）：").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    a = "n"
                levels = cand if a in ("", "y", "yes") else choose_levels()
            else:
                print(f"  ⚠ {why}")
                levels = choose_levels()
            if not levels:
                print("  已取消。")
                return 1
    levels = levels or []

    if tree:
        bad = check_depth(tree, levels)
        if bad:
            print(f"  ✗ {bad}")
            return 1

    target = notes_root() / name if notes_root() else None
    template = tdir / tpl

    print()
    print("-" * 64)
    print(f"  笔记名   ：{name}")
    print(f"  模板     ：{template}")
    print(f"  目标     ：{target}")
    print(f"  远程     ：{'创建并推送' if push else '不创建'}")
    if tree:
        files = content_files(tree, levels)
        print(f"  层级模式 ：{', '.join(levels)}")
        print(f"  章节结构 ：{len(tree)} 个顶层节点 / {len(files)} 个文件")
        for f in files[:12]:
            print(f"             {f}")
        if len(files) > 12:
            print(f"             …（其余 {len(files) - 12} 个）")
    else:
        print("  章节结构 ：不生成（模板自带的示例章会被删除，"
              "\\mainmatter 下留一个空 \\part）")
    print("-" * 64)

    if ask("\n  确认执行？[y/N]", "N").lower() not in ("y", "yes"):
        print("  已取消。")
        return 1

    return run(name, template, target, push, tree, levels, dry=False)


# ---------------------------------------------------------------- 主流程

def run(name, template, target, do_push, tree, levels, dry):
    levels = levels or []
    if not template.is_dir():
        print(f"✗ 模板目录不存在：{template}")
        return 1
    if target.exists():
        print(f"✗ 目标已存在：{target}")
        return 1
    if not re.fullmatch(r"[A-Za-z][\w\-]*", name):
        print("✗ 笔记名建议用字母开头、仅含字母数字下划线连字符（会作为仓库名）")
        return 1
    if tree:
        bad = check_depth(tree, levels)
        if bad:
            print(f"✗ {bad}")
            return 1

    if not dry:
        target.mkdir(parents=True)

    print("\n复制骨架：")
    for f in COPY_FILES:
        if (template / f).is_file():
            copy_item(template / f, target / f, dry)
            print(f"  {f}")
    for d in COPY_DIRS:
        if (template / d).is_dir():
            copy_item(template / d, target / d, dry)
            print(f"  {d}/")

    print("\n清理模板自带的测试内容：")
    removed = strip_test_sections(target, dry)
    print("  （无）" if not removed else "\n".join(f"  已移除 {r}" for r in removed))

    print("\n调整 main.tex：")
    chapters = top_chapters(tree, levels) if tree else []
    top_cmd = levels[0] if levels else None
    if dry:
        print(f"  标题 → {name}" + (f"；正文主体写成 {len(chapters)} 组"
                                  f"（\\{top_cmd} ＋ \\input）" if chapters else ""))
    elif rewrite_main_tex(target / "main.tex", name, chapters, top_cmd):
        print(f"  标题 → {name}" + (f"；正文主体写成 {len(chapters)} 组"
                                  f"（\\{top_cmd} ＋ \\input）" if chapters else ""))
    else:
        print("  （未找到 main.tex，跳过）")

    if tree:
        files = content_files(tree, levels)
        print(f"\n生成章节骨架（层级：{', '.join(levels)}）：")
        if not dry:
            content = target / "Content"
            content.mkdir(parents=True, exist_ok=True)
            build_content(content, tree, levels)
        for f in files:
            print(f"  {f}")
    else:
        print("\n章节骨架：未提供大纲，不生成；模板自带的示例章已删除，"
              "\\mainmatter 下只剩空的 \\part")

    if dry:
        print("\n[预演] 未写入任何文件。")
        return 0

    print("\ngit init：")
    ok, _, err = sh(["git", "init", "-q", "-b", "master"], cwd=str(target))
    if not ok:
        print(f"  ✗ 失败：{err}")
        return 1
    print("  ✓ 分支 master")

    print("\n安装提交前钩子：")
    hook_ok, hook_msg = install_hook(target, dry)
    print(f"  {'✓' if hook_ok else '⚠'} {hook_msg}")

    # 钩子装完后才提交 —— 首次提交也要过一遍本机信息扫描
    ok, out, err = sh(["git", "add", "-A"], cwd=str(target))
    if ok:
        ok, out, err = sh(["git", "commit", "-q", "-m", f"初始化笔记：{name}"], cwd=str(target))
    print("  ✓ 首次提交完成" if ok else f"  ✗ 提交失败：{err or out}")

    if do_push:
        print("\n创建远程仓库：")
        account = read_conf(MANAGER_CONF).get("account", "")
        ok, out, err = sh(["gh", "repo", "create", name, "--public",
                           "--description", f"{name} 自学笔记（LaTeX 源码）"])
        if not ok:
            print(f"  ✗ 创建失败：{err}")
            print("  本地仓库已就绪，可稍后手动推送。")
            return 1
        print(f"  {out}")
        if sh(["git", "remote", "add", "origin",
               f"git@github.com:{account}/{name}.git"], cwd=str(target))[0]:
            ok, _, err = sh(["git", "push", "-u", "origin", "master"], cwd=str(target))
        print("  ✓ 已推送" if ok else f"  ✗ 推送失败：{err}")

    print(f"\n完成：{target}")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    do_push = "--push" in argv

    def opt(name, default=None):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return default

    template = opt("--template")
    template = Path(template) if template else WORKSPACE / "Template" / "Math-Note"
    outline_file = opt("--outline")
    levels_spec = opt("--levels")

    # 无参数 → 交互式引导
    if not argv:
        return interactive()

    positional = [a for a in argv if not a.startswith("--")]
    # 剔除被 --xxx 消费掉的值，剩下的第一个才是笔记名
    for opt_name in ("--template", "--outline", "--levels"):
        val = opt(opt_name)
        if val in positional:
            positional.remove(val)

    meta, tree, levels = {}, [], []
    if outline_file:
        p = Path(outline_file)
        if not p.is_file():
            print(f"✗ 大纲文件不存在：{p}")
            return 1
        try:
            meta, tree, levels = read_outline_file(p)
        except OutlineError as e:
            print(f"✗ 大纲有问题：{e}")
            print_level_presets()
            return 1
    if levels_spec:
        try:
            levels = resolve_levels(levels_spec)
        except OutlineError as e:
            print(f"✗ {e}")
            print_level_presets()
            return 1

    name = positional[0] if positional else meta.get("name", "")
    if not name:
        print("✗ 没给笔记名 —— 写在命令行（`new_note.py 笔记名 …`）或 md 头部的 `name:` 里")
        print(__doc__)
        return 1

    # 层级模式：md 里写的 → 没写就按结构推；写了但与结构不符也交给它给建议
    # （只有 --levels 是用户显式指定，直接生效，冲突时由下面的 check_depth 兜底）
    if tree and not levels_spec:
        if not levels or len(levels) != tree_depth(tree):
            levels = resolve_levels_for_md(outline_file, meta, tree, interact=False)
            if not levels:
                return 1
    if tree:
        bad = check_depth(tree, levels)
        if bad:
            print(f"✗ {bad}")
            return 1

    root = notes_root()
    if not root:
        print("✗ 未找到笔记根目录")
        return 1

    return run(name, template, root / name, do_push, tree, levels, dry)


if __name__ == "__main__":
    sys.exit(main())
