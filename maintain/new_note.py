#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_note.py — 从模板创建一本新笔记

把「开始一本新笔记」的一串手工操作收敛成一步：复制骨架 → 清理模板自带的测试内容
→ `git init` → 首次提交 →（可选）建远程并推送。

之所以值得做成工具：手工复制最容易漏掉 `.gitignore` / `.gitattributes` /
脚本三件套，而后补这些东西往往是在「已经提交过一批文件」之后 —— 清理成本远高于
一开始就复制齐全。

用法
----
    python new_note.py <笔记名>                    # 只建本地仓库
    python new_note.py <笔记名> --push             # 同时建 GitHub 仓库并推送
    python new_note.py <笔记名> --template <目录>  # 指定模板（默认 Math-Note）
    python new_note.py <笔记名> --dry-run          # 只显示将要做什么

说明
----
- 只复制**源码与配置**，不复制编译产物与 `__pycache__`。
- 模板里带 `Test` 字样的章节会被剔除，并同步移除 `main.tex` 中的对应 `\\input`。
- 仓库分支用 `master`（与既有的笔记仓库保持一致）。
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

# 顶层要复制的文件（模板里这些是会随笔记分发的素材）
COPY_FILES = [
    ".gitignore", ".gitattributes",
    "structure.sty", "quiver.sty", "main.tex",
    "README.md", "ChangeLog.md",
    "commit.py", "commit.sh", "commit.md",
    "setup_mode.py", "setup_mode.md",
    "symbols.md", "术语对照表.md", "模板使用规范.md", "正文写作规范.md",
]
# 要复制的目录
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


def copy_item(src, dst, dry):
    """复制文件或目录，跳过编译产物与缓存。"""
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


def strip_test_sections(root, dry):
    """删除含 Test 字样的章节目录，并移除 main.tex 里对应的 \\input。"""
    removed = []
    for p in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
        if p.is_dir() and "Test" in p.name:
            removed.append(p)
            if not dry:
                shutil.rmtree(p)
    if dry:
        return [str(p.relative_to(root)) for p in removed]

    # 同步清理 main.tex / index.tex 中指向被删目录的 \input
    for tex in root.rglob("*.tex"):
        try:
            text = tex.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines(keepends=True)
        kept = []
        for ln in lines:
            m = re.search(r"\\input\{(.+?)\}", ln)
            if m and "Test" in m.group(1):
                continue
            kept.append(ln)
        new = "".join(kept)
        # 折叠因删除产生的连续空行
        new = re.sub(r"\n{3,}", "\n\n", new)
        if new != text:
            tex.write_text(new, encoding="utf-8", newline="")
    return [str(p.relative_to(root)) for p in removed]


def retitle(main_tex, name, dry):
    """把模板的标题与首个 \\part 改成笔记名。"""
    if not main_tex.is_file():
        return False
    text = main_tex.read_text(encoding="utf-8")
    # 标题里含 \textbf{}，此处必须用**贪婪**匹配到行尾最后一个 }，
    # 否则会在内层 } 处截断，替换后多出一个花括号。
    new = re.sub(r"\\title\{.*\}", f"\\\\title{{\\\\Huge\\\\textbf{{{name}}}}}",
                 text, count=1)
    new = new.replace("\\part{测试部分}", f"\\part{{{name}}}")
    if new == text:
        return False
    if not dry:
        main_tex.write_text(new, encoding="utf-8", newline="")
    return True


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    do_push = "--push" in sys.argv

    template = None
    if "--template" in sys.argv:
        i = sys.argv.index("--template")
        if i + 1 < len(sys.argv):
            template = Path(sys.argv[i + 1])
    if template is None:
        template = WORKSPACE / "Template" / "Math-Note"

    if not argv:
        print(__doc__)
        return 1
    name = argv[0]

    root = notes_root()
    if not root:
        print("✗ 未找到笔记根目录")
        return 1
    target = root / name

    print(f"模板　　：{template}")
    print(f"目标　　：{target}")
    print(f"模式　　：{'预演（不写任何文件）' if dry else '执行'}")
    print(f"远程　　：{'创建并推送' if do_push else '不创建'}")
    print()

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

    print("复制骨架：")
    n_files = 0
    for f in COPY_FILES:
        src = template / f
        if src.is_file():
            copy_item(src, target / f, dry)
            n_files += 1
            print(f"  {f}")
    for d in COPY_DIRS:
        src = template / d
        if src.is_dir():
            copy_item(src, target / d, dry)
            print(f"  {d}/")

    print("\n清理模板自带的测试内容：")
    removed = strip_test_sections(target, dry)
    print("  （无）" if not removed else "\n".join(f"  已移除 {r}" for r in removed))

    print("\n调整标题：")
    if retitle(target / "main.tex", name, dry):
        print(f"  main.tex 标题 → {name}")
    else:
        print("  （未找到 \\title{}，跳过）")

    if dry:
        print("\n[预演] 未写入任何文件。")
        return 0

    print("\ngit init：")
    ok, _, err = sh(["git", "init", "-q", "-b", "master"], cwd=str(target))
    if not ok:
        print(f"  ✗ 失败：{err}")
        return 1
    print("  分支 master")

    ok, _, err = sh(["git", "add", "-A"], cwd=str(target))
    if ok:
        ok, _, err = sh(["git", "commit", "-q", "-m", f"初始化笔记：{name}"], cwd=str(target))
    print("  ✓ 首次提交" if ok else f"  ✗ 提交失败：{err}")

    if do_push:
        print("\n创建远程仓库：")
        ok, out, err = sh(["gh", "repo", "create", name, "--public",
                           "--description", f"{name} 自学笔记（LaTeX 源码）"])
        if not ok:
            print(f"  ✗ 创建失败：{err}")
            print(f"  本地仓库已就绪，可稍后手动推送。")
            return 1
        print(f"  {out}")
        ok, _, err = sh(["git", "remote", "add", "origin",
                         f"git@github.com:{read_conf(MANAGER_CONF).get('account', '')}/{name}.git"],
                        cwd=str(target))
        if ok:
            ok, _, err = sh(["git", "push", "-u", "origin", "master"], cwd=str(target))
        print("  ✓ 已推送" if ok else f"  ✗ 推送失败：{err}")

    print(f"\n完成：{target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
