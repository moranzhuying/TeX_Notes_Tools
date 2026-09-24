#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
outline_tool.py — 大纲 md 的创建 / 导出 / 校验

`new_note.py` 按 Markdown 大纲建笔记骨架；本工具负责**把大纲本身弄出来**，
三个入口：

    1. 新建大纲   —— 粘一份「缩进清单」，转成规范的大纲 md
    2. 导出大纲   —— 读现有笔记的 main.tex / index.tex 链，反推出大纲 md
    3. 校验大纲   —— 读一份 md，报错并预览它会生成哪些文件

用法：
    python outline_tool.py                      # 面板
    python outline_tool.py --check <大纲.md>     # 只校验（不弹提问）
    python outline_tool.py --check <大纲.md> --write-levels   # 顺手把推断的 levels 写进 md
    python outline_tool.py --export <笔记目录> [输出.md]
    python outline_tool.py --from-text <清单.txt> [输出.md]    # 层级按层数自动推断

大纲 md 里 `levels:` 怎么写的规范，见 new_note.py 的模块文档与 Tools/README.md；
本工具不重复实现解析，直接 `import new_note` 复用（同一目录，两个脚本共享一套规则）。
"""
import os
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/outline_tool/
TOOLS_DIR = TOOL_DIR.parent                       # <Tools>/
WORKSPACE = TOOLS_DIR.parent                      # 工作区根

# 复用 new_note.py 的解析与生成规则（同一套，别抄两份）
sys.path.insert(0, str(TOOLS_DIR / "new_note"))
import new_note as nn          # noqa: E402

INPUT_RE = re.compile(r"^\s*%?\s*\\input\{(.+?)\}\s*$")
CMD_RE = re.compile(r"\\(part|chapter|appendixchapter|section|subsection|subsubsection)"
                    r"\*?\{([^}]*)\}")
#: `\appendixchapter` 是模板里的自定义命令，语义等同 chapter
ALIAS = {"appendixchapter": "chapter"}


def cmd_name(name):
    return ALIAS.get(name, name)


def find_title(tex_path, want):
    """在文件里找第一个「命令名 == want」的标题，返回标题文本（找不到返回空串）。

    两个判断都不能少：
      · 遇到比 want **更深**的命令就放弃 —— 说明本层标题不在这个文件里，
        否则会把正文里的 `\\subsection{...}` 当成标题（导出 Algebra 时踩过）；
      · 不因「正文行」而停 —— 真实笔记里有把节引言写在标题之前的写法。
    """
    if not tex_path or not tex_path.is_file():
        return ""
    want_depth = nn.SECTION_CMDS.index(want)
    for ln in tex_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.strip().startswith("%"):
            continue
        for m in CMD_RE.finditer(ln):
            name = cmd_name(m.group(1))
            if name == want:
                return m.group(2).strip()
            if nn.SECTION_CMDS.index(name) > want_depth:
                return ""
    return ""


def find_title_before_inputs(tex_path, want):
    """同上，但只看 `\\input` 之前的部分 —— 目录层常把标题写在 index.tex 顶部。"""
    if not tex_path.is_file():
        return ""
    want_depth = nn.SECTION_CMDS.index(want)
    for ln in tex_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.strip().startswith("%"):
            if re.match(r"^\s*%\s*\\input\b", ln):     # 被注释掉的 \\input 也算界
                return ""
            continue
        if re.match(r"^\s*\\input\b", ln):
            return ""
        for m in CMD_RE.finditer(ln):
            name = cmd_name(m.group(1))
            if name == want:
                return m.group(2).strip()
            if nn.SECTION_CMDS.index(name) > want_depth:
                return ""
    return ""


def first_leaf_tex(note, rel):
    """该目录子树里第一个叶子文件的路径（没有就 None）。"""
    idx = note / rel / "index.tex"
    if not idx.is_file():
        return None
    for ln in idx.read_text(encoding="utf-8").splitlines():
        m = INPUT_RE.match(ln)
        if not m:
            continue
        target = m.group(1).lstrip("./")
        if target.endswith("/index"):
            return first_leaf_tex(note, target[: -len("/index")])
        return note / f"{target}.tex"
    return None


def scan_note(note, rel, level):
    """只按 \\input 的形状搭出结构（不读标题），每个节点带上 rel 与是否叶子。"""
    idx = note / rel / "index.tex"
    nodes = []
    if not idx.is_file():
        return nodes
    for ln in idx.read_text(encoding="utf-8").splitlines():
        m = INPUT_RE.match(ln)
        if not m:
            continue
        target = m.group(1).lstrip("./")
        if target.endswith("/index"):
            srel = target[: -len("/index")]
            nodes.append({
                "name": Path(srel).name, "_rel": srel, "_leaf": False,
                "label": "", "children": scan_note(note, srel, level + 1),
            })
        else:
            nodes.append({"name": Path(target).name, "_rel": target, "_leaf": True,
                          "label": "", "children": []})
    return nodes


def first_title_any(tex_path, before_inputs=False):
    """文件里第一条标题命令（不论什么命令），返回 (命令名, 标题)。没有就 (\"\", \"\")。

    只用于诊断：查不到期望命令时，把「文件里其实写的是什么」告诉用户。
    """
    if not tex_path or not tex_path.is_file():
        return "", ""
    for ln in tex_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.strip().startswith("%"):
            continue
        if before_inputs and re.match(r"^\s*\\input\b", ln):
            return "", ""
        m = CMD_RE.search(ln)
        if m:
            return cmd_name(m.group(1)), m.group(2).strip()
    return "", ""


def fill_titles(note, node, level, levels, miss):
    """给节点补中译名：目录层先看自己的 index.tex，再看子树第一个叶子文件；
    叶子层看自己的文件。找不到就留空（md 里只写目录名）。"""
    want = levels[level] if level < len(levels) else ""
    label = ""
    if want:
        if node["_leaf"]:
            label = find_title(note / f"{node['_rel']}.tex", want)
        else:
            label = find_title_before_inputs(note / node["_rel"] / "index.tex", want)
            if not label:
                label = find_title(first_leaf_tex(note, node["_rel"]), want)
    node["label"] = label
    if not label:
        seen, where = "", ""
        if want:
            if node["_leaf"]:
                seen, _ = first_title_any(note / f"{node['_rel']}.tex")
                where = f"{node['_rel']}.tex"
            else:
                seen, _ = first_title_any(note / node["_rel"] / "index.tex",
                                          before_inputs=True)
                where = f"{node['_rel']}/index.tex"
        if seen and seen != want:
            miss.append(f"{where} 里是 \\{seen}，本层应为 \\{want}")
        else:
            miss.append(f"{node['_rel']}（层{level + 1}，文件里没有标题）")
    for child in node["children"]:
        fill_titles(note, child, level + 1, levels, miss)
    node.pop("_rel", None)
    node.pop("_leaf", None)
    return node


def top_cmds_from_main(note):
    """从 main.tex 的正文主体里读 [(命令, 标题), \\input 路径, 是否被 % 注释掉, ...]。

    **`%` 注释掉的章照样收** —— 导出的是「计划」，笔记里用 `%` 关掉的多半是还没写的章，
    正是新笔记蓝本里需要的；报告时单独提示条数。
    """
    main = Path(note) / "main.tex"
    if not main.is_file():
        return []
    t = main.read_text(encoding="utf-8")
    i, j = t.find("\\mainmatter"), t.find("\\backmatter")
    seg = t[i:j] if i >= 0 and j > i else t
    out, last = [], None
    for ln in seg.splitlines():
        commented = ln.strip().startswith("%")
        for m in CMD_RE.finditer(ln):
            last = (cmd_name(m.group(1)), m.group(2).strip())
        m = INPUT_RE.match(ln)
        if m:
            out.append((last, m.group(1).lstrip("./"), commented))
            last = None
    return out


def export_note(note):
    """导出笔记 → (树, levels, 警告列表)。

    层级模式按**结构**推：最外层命令取自 main.tex，其余按 LaTeX 章节命令的固定次序
    （part → chapter → section → subsection …）顺延到最大层数 —— 不去「投票」各层读到
    什么命令，那会被「叶子没有自己的标题」这类写法带偏。
    """
    note = Path(note)
    warn, miss = [], []
    tops = top_cmds_from_main(note)
    if not tops:
        raise nn.OutlineError("main.tex 的正文主体里没找到「标题命令 + \\input」对")

    branches = []
    for cmd_pair, rel, commented in tops:
        if not rel.endswith("/index"):
            raise nn.OutlineError(f"正文主体里的 \\input 不是目录：{rel}")
        srel = rel[: -len("/index")]
        branches.append((cmd_pair, srel, scan_note(note, srel, 1), commented))

    depth = max(1 + nn.tree_depth(kids) for _cp, _rel, kids, _c in branches)
    for _cp, srel, kids, _c in branches:
        d = 1 + nn.tree_depth(kids)
        if d != depth:
            warn.append(f"{Path(srel).name} 只有 {d} 层（其余分支 {depth} 层），"
                        f"按占位空节点处理")

    top_cmd = tops[0][0][0] if tops[0][0] else ""
    if not top_cmd:
        warn.append("main.tex 里没有标题命令，层级序列按 chapter 起算")
        idx0 = 1
    else:
        idx0 = nn.SECTION_CMDS.index(top_cmd)
    if idx0 + depth > len(nn.SECTION_CMDS):
        raise nn.OutlineError(f"层数 {depth} 超出 LaTeX 章节层级上限")
    levels = nn.SECTION_CMDS[idx0: idx0 + depth]
    warn.append(f"层级模式按结构推断为 {', '.join(levels)}，请核对")

    off = sum(1 for _cp, _rel, _k, c in branches if c)
    if off:
        warn.append(f"有 {off} 个顶层节点在 main.tex 里被 % 注释掉（未启用），已一并保留")

    tree = []
    for cmd_pair, srel, kids, _c in branches:
        for child in kids:
            fill_titles(note, child, 1, levels, miss)
        tree.append({"name": Path(srel).name,
                     "label": cmd_pair[1] if cmd_pair else "",
                     "children": kids})

    if miss:
        warn.append(f"{len(miss)} 处没读到中译名（md 里只写目录名）："
                    + "、".join(miss[:5]) + ("…" if len(miss) > 5 else ""))
    unnumbered = _count_unnumbered(tree)
    if unnumbered:
        warn.append(f"{unnumbered} 处目录名原本没有编号前缀（如 Appendix_…）；"
                    f"这些名字进 md 后，新建笔记时会被自动补号")
    return tree, levels, warn


def _count_unnumbered(nodes):
    n = 0
    for node in nodes:
        if not re.match(r"^\d+_", node["name"]):
            n += 1
        n += _count_unnumbered(node["children"])
    return n


def clear():
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def pause():
    print()
    try:
        input("按回车返回…")
    except (EOFError, KeyboardInterrupt):
        pass


def ask(prompt, default=""):
    hint = f"（回车＝{default}）" if default else ""
    try:
        ans = input(f"  {prompt}{hint}：").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return ans or default


# ---------------------------------------------------------------- 写 md

def render_md(tree, levels, name="", template="", comment=""):
    """把树渲染成大纲 md 文本（层级用 Markdown 标题）。"""
    lines = ["---"]
    if name:
        lines.append(f"name: {name}")
    if template:
        lines.append(f"template: {template}")
    lines.append(f"levels: {', '.join(levels)}")
    lines.append("---")
    lines.append("")
    if comment:
        lines.append("<!--")
        lines.extend(comment.splitlines())
        lines.append("-->")
        lines.append("")

    def walk(node, depth):
        head = "#" * depth
        body = f"{node['name']} | {node['label']}" if node["label"] else node["name"]
        lines.append(f"{head} {body}")
        for child in node["children"]:
            walk(child, depth + 1)

    for node in tree:
        walk(node, 1)
    return "\n".join(lines) + "\n"


def write_md(path, text):
    """写 md（顺带建父目录）。写不进去就返回 None 并提示，不抛栈。"""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
    except OSError as e:
        print(f"  ✗ 写不进去：{e}")
        return None
    return p.resolve()


def save(path, text, prefix=""):
    """写 + 报一行。写失败返回 None。"""
    resolved = write_md(path, text)
    if resolved:
        print(f"{prefix}已写入 {resolved}")
    return resolved


# ---------------------------------------------------------------- 三个入口

def read_skeleton():
    """读一段缩进清单（目录名 | 中译名）。"""
    print(f"  每行 `目录名 | 中译名`（中译可省），用**缩进**表示层级；")
    print("  单独一行 `END` 结束，直接回车＝放弃。示例：")
    print("      Modules_over_Rings | 环上的模")
    print("        Basic_definitions | 基本定义")
    print("          Modules | 模")
    print()
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
    return "\n".join(lines)


def entry_new():
    print("=" * 64)
    print("  新建大纲（缩进清单 → 规范 md）")
    print("=" * 64)
    print()
    print("  先把大纲列出来（下一步）。层级模式不用你记，脚本会按清单的层数推断，")
    print("  连同 `levels:` 一起写进 md 头部 —— 事后想改，直接编辑那一行即可。")
    print()
    text = read_skeleton()
    if not text.strip():
        print("  已取消。")
        return
    try:
        tree = nn.parse_indent_outline(text)
    except nn.OutlineError as e:
        print(f"  ✗ {e}")
        return

    levels, why = nn.infer_levels(tree)
    if levels is None:
        print(f"  ✗ {why}")
        print("    调整清单的层数后重试，或直接手写 md 并在头部写一行 levels: …")
        return
    print(f"\n  按结构（{nn.tree_depth(tree)} 层）推断层级：{nn.describe_levels(levels)}")
    print(f"  依据：{why}")

    name = ask("\n笔记名（写进 md 的 name，可回车跳过）", "")
    out = ask("输出路径", str(WORKSPACE / f"{name or 'outline'}.md"))
    if not out:
        print("  已取消。")
        return
    path = write_md(out, render_md(tree, levels, name=name))
    if not path:
        return
    print(f"\n  ✓ 已写入 {path}")
    print(f"    头部已写上 `levels: {', '.join(levels)}`；要换层级就改这一行")
    print("    （可用简写名 bourbaki / textbook / two-level / article / grouped，")
    print("      或按由外到内列命令、用 `-` 表示该层只作分组）")
    files = nn.content_files(tree, levels)
    print(f"  它会生成 {len(files)} 个文件：")
    for f in files[:12]:
        print(f"      {f}")
    if len(files) > 12:
        print(f"      ……（其余 {len(files) - 12} 个）")
    print(f"\n  接着可以：python new_note.py {name or '<笔记名>'} "
          f"--outline \"{path}\"")


def entry_export():
    root = nn.notes_root()
    if not root:
        print("  ✗ 未找到笔记根目录")
        return
    notes = [d for d in sorted(root.iterdir())
             if d.is_dir() and (d / "main.tex").is_file()
             and not d.name.startswith(".") and "Archieved" not in d.name]
    if not notes:
        print(f"  ✗ {root} 下没有找到笔记")
        return

    print("=" * 64)
    print("  从现有笔记导出大纲")
    print("=" * 64)
    print(f"  笔记根目录：{root}\n")
    for i, n in enumerate(notes, 1):
        print(f"    {i}. {n.name}")
    print("    0. 返回\n")
    try:
        ans = input("  选择笔记编号：").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not ans.isdigit() or not (1 <= int(ans) <= len(notes)):
        return
    note = notes[int(ans) - 1]

    print()
    try:
        tree, levels, warn = export_note(note)
    except nn.OutlineError as e:
        print(f"  ✗ {e}")
        return
    print(f"  层级模式：{', '.join(levels)}")
    print(f"  顶层节点：{len(tree)} 个，共 {len(nn.content_files(tree, levels))} 个文件")
    for w in warn:
        print(f"  ⚠ {w}")

    out = ask("\n输出路径", str(WORKSPACE / f"{note.name}_outline.md"))
    if not out:
        print("  已取消。")
        return
    comment = ("由 outline_tool.py 从现有笔记导出。\n"
               "中译名读不到的地方会只留目录名，请按需补全后再用。")
    path = write_md(out, render_md(tree, levels, name=note.name, comment=comment))
    if not path:
        return
    print(f"\n  ✓ 已写入 {path}")
    # 回读校验：导出的 md 必须能重新解析出同一棵树
    try:
        meta, tree2, levels2 = nn.read_outline_file(path)
        same = (levels2 == levels
                and [f for f in nn.content_files(tree2, levels2)]
                == [f for f in nn.content_files(tree, levels)])
        print(f"  回读校验：{'一致 ✓' if same else '不一致 ✗（请检查中译名与层级）'}")
    except nn.OutlineError as e:
        print(f"  回读校验失败：{e}")


def entry_check(path=None, interact=True, fix=False):
    """校验一份大纲 md。返回 0 = 完全没问题；1 = 有需要你处理的地方。

    `interact`：面板里为真（缺 levels / 层数不符时会问「用不用推断值、要不要写回 md」）；
    命令行里一律为假 —— 只给结论与改法，不弹提问。
    `fix`：命令行加 `--write-levels` 时为真，直接把推断/修正后的 levels 写进 md。
    """
    if not path:
        path = ask("大纲 md 路径")
    if not path:
        return 1
    p = Path(path)
    print("=" * 64)
    print(f"  校验 {p}")
    print("=" * 64)
    try:
        meta, tree, levels = nn.read_outline_file(p)
        text = Path(p).read_text(encoding="utf-8")
    except OSError as e:
        print(f"  ✗ 读不到：{e}")
        return 1
    except nn.OutlineError as e:
        print(f"  ✗ {e}")
        return 1
    if not tree:
        print("  ✗ 大纲里没有任何标题")
        return 1

    todo = 0
    depth = nn.tree_depth(tree)
    if not levels or len(levels) != depth:
        if interact:
            levels = nn.resolve_levels_for_md(p, meta, tree, interact=True)
            if not levels:
                print("  （改好 md 后再校验一次即可）")
                return 1
        else:
            cand, why = nn.infer_levels(tree, text)
            if cand is None:
                print(f"  ✗ {why}")
                return 1
            print(f"  ⚠ {'md 里没写 levels' if not levels else 'md 写的 levels 与结构不符'}")
            print(f"    按结构（{depth} 层）推断为：{nn.describe_levels(cand)}")
            print(f"    依据：{why}")
            if fix:
                ok, info = nn.set_levels_in_md(p, cand)
                print(f"    {'✓' if ok else '✗'} {info}")
                todo = 0 if ok else 1
            else:
                print(f"    要固定就改 md 头部那行为：levels: {', '.join(cand)}")
                print("    （也可以加 --write-levels 让脚本代写）")
                todo = 1
            levels = cand
    bad = nn.check_depth(tree, levels)
    if bad:
        print(f"  ✗ {bad}")
        return 1

    if not todo:
        print("  ✓ 格式正确")
    else:
        print("  —— 以下预览按推断的层级给出 ——")
    print(f"  元信息   ：{meta if meta else '（无）'}")
    print(f"  层级模式 ：{nn.describe_levels(levels)}")
    print(f"  结构     ：{len(tree)} 个顶层节点 / {len(nn.content_files(tree, levels))} 个文件")
    print()
    for f in nn.content_files(tree, levels):
        print(f"    {f}")
    return todo


# ---------------------------------------------------------------- 面板

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    OPT_NAMES = ("--check", "--export", "--from-text", "--levels")

    def opt(name):
        i = argv.index(name) if name in argv else -1
        return argv[i + 1] if 0 <= i < len(argv) - 1 else None

    def positional():
        """剩下的自由参数（要剔掉被各选项吃掉的值，否则会把它当成输出路径）。"""
        consumed = {v for v in (opt(n) for n in OPT_NAMES) if v is not None}
        return [a for a in argv if not a.startswith("--") and a not in consumed]

    if "--check" in argv:
        # 命令行一律不弹提问：只给结论与改法；加 --write-levels 才动 md
        return entry_check(opt("--check"), interact=False,
                           fix="--write-levels" in argv)
    if "--export" in argv:
        note = opt("--export")
        try:
            tree, levels, warn = export_note(note)
        except (nn.OutlineError, TypeError) as e:
            print(f"✗ {e}")
            return 1
        rest = positional()
        out = rest[0] if rest else str(WORKSPACE / f"{Path(note).name}_outline.md")
        for w in warn:
            print(f"⚠ {w}")
        save(out, render_md(tree, levels, name=Path(note).name), prefix="✓ ")
        return 0
    if "--from-text" in argv:
        src = opt("--from-text")
        if not src or not Path(src).is_file():
            print(f"✗ 找不到清单文件：{src}")
            return 1
        spec = opt("--levels")
        try:
            levels = nn.resolve_levels(spec) if spec else None
        except nn.OutlineError as e:
            print(f"✗ {e}")
            return 1
        text = Path(src).read_text(encoding="utf-8")
        try:
            tree = nn.parse_indent_outline(text)
        except nn.OutlineError as e:
            print(f"✗ {e}")
            return 1
        if levels is None:
            levels, why = nn.infer_levels(tree)
            if levels is None:
                print(f"✗ {why}")
                print("  先调整清单的层数，或直接手写 md 并在头部写一行 levels: …")
                return 1
            print(f"按结构（{nn.tree_depth(tree)} 层）推断层级："
                  f"{nn.describe_levels(levels)}（{why}）")
        bad = nn.check_depth(tree, levels)
        if bad:
            print(f"✗ {bad}")
            return 1
        rest = positional()
        out = rest[0] if rest else str(WORKSPACE / "outline.md")
        save(out, render_md(tree, levels), prefix="✓ ")
        return 0

    while True:
        clear()
        print("=" * 64)
        print("  大纲工具（创建 / 导出 / 校验）")
        print("=" * 64)
        print("    1. 新建大纲：粘缩进清单 → 规范 md")
        print("    2. 从现有笔记导出大纲")
        print("    3. 校验大纲（并预览会生成哪些文件）")
        print("    0. 退出")
        print("=" * 64)
        try:
            c = input("\n  选择（回车退出）: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not c or c == "0":
            break
        clear()
        if c == "1":
            entry_new()
        elif c == "2":
            entry_export()
        elif c == "3":
            entry_check()
        else:
            continue
        pause()

    clear()
    return 0


if __name__ == "__main__":
    sys.exit(main())
