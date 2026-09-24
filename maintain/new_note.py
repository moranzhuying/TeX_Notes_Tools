#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_note.py — 从模板创建一本新笔记

把「开始一本新笔记」的一串手工操作收敛成一步：复制骨架 → 按录入的章节结构生成
`Content/` 骨架 → `git init` → 装提交前钩子 → 首次提交 →（可选）建远程并推送。

`git init` 之后会自动把 `guard/hooks/pre-commit` 装进新仓库，把「提交前本机信息扫描」
一并带过去，不必事后手工补装。钩子靠相对路径逐级查找 `guard/check_sensitive.py`，
找不到时放行，所以不会因为换机器而阻断提交。

**不带参数运行会进入交互式引导**（推荐，从总面板进来就是这条路）：依次询问
笔记名、是否建远程、用哪个模板，然后让你粘贴章节结构。

用法
----
    python new_note.py                        # 交互式引导
    python new_note.py <笔记名>                # 只建本地仓库（不生成章节骨架）
    python new_note.py <笔记名> --push         # 同时建 GitHub 仓库并推送
    python new_note.py <笔记名> --template <目录>
    python new_note.py <笔记名> --outline <文件>   # 从文件读章节结构
    python new_note.py <笔记名> --dry-run      # 只显示将要做什么

章节结构格式
------------
用**缩进**表示层级，用 `|` 分隔「目录名」与「中译名」（中译名可省，省了就不写标题）：

    1_Modules_over_Rings | 环上的模
      1_Basic_definitions | 基本定义
        1_Modules | 模
        2_Homomorphisms | 同态
      2_Exact_sequences | 正合列

对应生成（遵循本模板系的既有约定）：

    Content/1_Modules_over_Rings/index.tex              → \\input 各节
    Content/1_Modules_over_Rings/1_Basic_definitions/index.tex   → \\input 各小节
    .../1_Basic_definitions/1_Modules.tex               → \\chapter{环上的模} + \\section{模}
    .../1_Basic_definitions/2_Homomorphisms.tex         → \\section{同态}

注意：`\\chapter{}` 只写在该**章第一个节的第一个小节**里，「节」这一层本身不带标题。
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


# ---------------------------------------------------------------- 章节结构

def parse_outline(text):
    """把缩进大纲解析成树：[{name, label, children}, ...]"""
    # 注意：stack[0][1] 本身就是根列表，不要再另建 tree 变量 ——
    # 那样两者不是同一个对象，往里 append 的内容不会出现在返回值里（踩过）。
    stack = [(-1, [])]
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        body = raw.strip()
        name, sep, label = body.partition("|")
        node = {
            "name": re.sub(r"\s+", "_", name.strip()),
            "label": label.strip() if sep else "",
            "children": [],
        }
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((indent, node["children"]))
    return stack[0][1]


def outline_files(tree):
    """列出结构将产生的文件（用于预览）。"""
    out = []
    for chap in tree:
        for j, sec in enumerate(chap["children"], 1):
            for k, sub in enumerate(sec["children"], 1):
                marks = []
                if j == 1 and k == 1 and chap["label"]:
                    marks.append("\\chapter")
                marks.append("\\section")
                out.append(f"Content/{chap['name']}/{sec['name']}/{sub['name']}.tex"
                           f"   {'+'.join(marks)}")
    return out


def build_content(content_dir, tree):
    """按树生成章节目录、index.tex 与小节文件。返回章名列表。"""
    chapters = []
    for chap in tree:
        cdir = content_dir / chap["name"]
        cdir.mkdir(parents=True, exist_ok=True)
        c_inputs = []

        for j, sec in enumerate(chap["children"], 1):
            sdir = cdir / sec["name"]
            sdir.mkdir(parents=True, exist_ok=True)
            s_inputs = []

            for k, sub in enumerate(sec["children"], 1):
                body = []
                if j == 1 and k == 1 and chap["label"]:
                    body.append(f"\\chapter{{{chap['label']}}}")
                    body.append("")
                body.append(f"\\section{{{sub['label'] or sub['name']}}}")
                body.append("")
                body.append("")
                (sdir / f"{sub['name']}.tex").write_text(
                    "\n".join(body), encoding="utf-8", newline="")
                s_inputs.append(
                    f"\\input{{./Content/{chap['name']}/{sec['name']}/{sub['name']}}}")

            (sdir / "index.tex").write_text(
                "\n".join(s_inputs) + "\n", encoding="utf-8", newline="")
            c_inputs.append(f"\\input{{./Content/{chap['name']}/{sec['name']}/index}}")

        (cdir / "index.tex").write_text(
            "\n".join(c_inputs) + "\n", encoding="utf-8", newline="")
        chapters.append(chap["name"])
    return chapters


def rewrite_main_tex(main_tex, name, chapters):
    r"""更新 main.tex：标题、\part，以及各章的 \input。

    `\mainmatter` 与 `\backmatter` 之间是正文主体：其中的 `\part` **保留并改名**成
    笔记名，其余内容由新的章节 `\input` 链取代。不能把整段直接替换掉 ——
    那样刚改好名的 `\part` 会被一起吃掉，所以这里分两步处理。
    """
    if not main_tex.is_file():
        return False
    text = main_tex.read_text(encoding="utf-8")
    # 标题里含 \textbf{}，必须贪婪匹配到行尾最后一个 }
    new = re.sub(r"\\title\{.*\}", f"\\\\title{{\\\\Huge\\\\textbf{{{name}}}}}",
                 text, count=1)
    new = new.replace("\\part{测试部分}", f"\\part{{{name}}}")

    inputs = [f"\\input{{./Content/{c}/index}}" for c in chapters]
    m = re.search(r"(\\mainmatter[ \t]*\n)(.*?)(\s*\\backmatter)", new, flags=re.S)
    if m:
        seg = []
        if re.search(r"\\part\{", m.group(2)):     # 正文主体里带 \part
            seg.append(f"\\part{{{name}}}")
        if inputs:
            seg.append("\n".join(inputs))          # 各章 \input 连续成行，同模板写法
        if seg:
            # 首行补一个空行，\part 与 \input 块之间空一行；尾部空行由末组自带
            new = new[:m.start()] + m.group(1) + "\n" + "\n\n".join(seg) \
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


def read_outline_interactive():
    print("  粘贴章节结构，用缩进表示层级，`|` 分隔目录名与中译名。")
    print("  例：")
    print("      1_Modules_over_Rings | 环上的模")
    print("        1_Basic_definitions | 基本定义")
    print("          1_Modules | 模")
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
    return "\n".join(lines)


def interactive():
    print("=" * 64)
    print("  从模板新建笔记")
    print("=" * 64)
    print()

    name = ask("笔记名（字母开头，可含数字/下划线/连字符）")
    if not name:
        print("  已取消。")
        return 1

    templates = []
    tdir = WORKSPACE / "Template"
    if tdir.is_dir():
        templates = [d.name for d in sorted(tdir.iterdir())
                     if d.is_dir() and (d / "main.tex").is_file()]
    default_tpl = "Math-Note" if "Math-Note" in templates else (templates[0] if templates else "")
    if templates:
        print(f"\n  可用模板：{', '.join(templates)}")
    tpl = ask("模板目录名", default_tpl)
    if not tpl:
        print("  已取消。")
        return 1

    print()
    push = ask("同时建 GitHub 仓库并推送？[y/N]", "N").lower() in ("y", "yes")

    print()
    outline_text = read_outline_interactive()
    tree = parse_outline(outline_text) if outline_text.strip() else []

    target = notes_root() / name if notes_root() else None
    template = tdir / tpl

    print()
    print("-" * 64)
    print(f"  笔记名   ：{name}")
    print(f"  模板     ：{template}")
    print(f"  目标     ：{target}")
    print(f"  远程     ：{'创建并推送' if push else '不创建'}")
    if tree:
        files = outline_files(tree)
        print(f"  章节结构 ：{len(tree)} 章 / {len(files)} 个小节")
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

    return run(name, template, target, push, tree, dry=False)


# ---------------------------------------------------------------- 主流程

def run(name, template, target, do_push, tree, dry):
    if not template.is_dir():
        print(f"✗ 模板目录不存在：{template}")
        return 1
    if target.exists():
        print(f"✗ 目标已存在：{target}")
        return 1
    if not re.fullmatch(r"[A-Za-z][\w\-]*", name):
        print("✗ 笔记名建议用字母开头、仅含字母数字下划线连字符（会作为仓库名）")
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
    chapters = [c["name"] for c in tree] if tree else []
    if dry:
        print(f"  标题 → {name}" + (f"；\\mainmatter 下写入 {len(chapters)} 个章节引用"
                                  if chapters else ""))
    elif rewrite_main_tex(target / "main.tex", name, chapters):
        print(f"  标题 → {name}" + (f"；\\mainmatter 下写入 {len(chapters)} 个章节引用"
                                  if chapters else ""))
    else:
        print("  （未找到 main.tex，跳过）")

    if tree:
        print("\n生成章节骨架：")
        if dry:
            for f in outline_files(tree):
                print(f"  {f}")
        else:
            content = target / "Content"
            content.mkdir(parents=True, exist_ok=True)
            for c in build_content(content, tree):
                print(f"  Content/{c}/index.tex")
                print(f"  Content/{c}/…/index.tex")
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
    positional = [a for a in argv if not a.startswith("--")]

    template = None
    if "--template" in argv:
        i = argv.index("--template")
        if i + 1 < len(sys.argv):
            template = Path(sys.argv[i + 1])
    if template is None:
        template = WORKSPACE / "Template" / "Math-Note"

    outline_file = None
    if "--outline" in argv:
        i = argv.index("--outline")
        if i + 1 < len(sys.argv):
            outline_file = argv[i + 1]

    # 无参数 → 交互式引导
    if not argv:
        return interactive()

    if not positional:
        print(__doc__)
        return 1
    name = positional[0]

    tree = []
    if outline_file:
        p = Path(outline_file)
        if not p.is_file():
            print(f"✗ 大纲文件不存在：{p}")
            return 1
        tree = parse_outline(p.read_text(encoding="utf-8"))

    root = notes_root()
    if not root:
        print("✗ 未找到笔记根目录")
        return 1

    return run(name, template, root / name, do_push, tree, dry)


if __name__ == "__main__":
    sys.exit(main())
