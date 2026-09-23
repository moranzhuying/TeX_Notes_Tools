#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_aux.py — 清理 LaTeX 编译产物

编译一次就会留下 `.aux/.log/.xdv/.fls/...` 一堆中间文件。它们都被各仓库的
`.gitignore` 忽略、不会误提交，但会一直堆积占地方（实测 Template + 笔记区
已积到几十个文件、数 MB）。

本工具按仓库分组列出占用，确认后再删。

    python clean_aux.py                # 只列出（默认）
    python clean_aux.py --write        # 删除（会先确认）
    python clean_aux.py --write --yes  # 删除且不确认
    python clean_aux.py --with-pdf     # 连同 PDF 一起清
    python clean_aux.py --area notes   # 只处理某区域：notes / template / tools / all

安全性：只按**扩展名**匹配编译产物，绝不触碰源码；默认不动 PDF（那通常是
你真正想留的东西）。
"""
import os
import sys
from pathlib import Path

# <工作区>/Tools/maintain/ → 工作区根
WORKSPACE = Path(__file__).resolve().parent.parent.parent

# 编译中间产物（可再生，删了没关系）
AUX_EXT = {
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk",
    ".synctex.gz", ".synctex", ".bbl", ".blg", ".dvi", ".xdv", ".listing",
    ".nav", ".snm", ".vrb", ".idx", ".ind", ".ilg", ".run.xml",
}
PDF_EXT = {".pdf"}

# 区域名 → 相对工作区的目录（"all" 表示扫整个工作区）
AREAS = {
    "notes": "LaTeX_Notes",
    "template": "Template",
    "tools": "Tools",
}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".workbuddy"}


def human(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def collect(root, with_pdf):
    """扫描 root 下的编译产物，返回 {仓库相对路径: [(文件, 大小), ...]}。"""
    targets = {".pdf"} if with_pdf else set()
    exts = AUX_EXT | targets
    found = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            # 处理 .synctex.gz / .run.xml 这类双段后缀
            low = name.lower()
            if not (p.suffix.lower() in exts
                    or low.endswith(".synctex.gz")
                    or low.endswith(".run.xml")):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            try:
                key = str(p.parent.relative_to(WORKSPACE))
            except ValueError:
                key = str(p.parent)
            found.setdefault(key, []).append((p, size))
    return found


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    do_write = "--write" in argv
    assume_yes = "--yes" in argv
    with_pdf = "--with-pdf" in argv

    area = "all"
    if "--area" in argv:
        i = argv.index("--area")
        if i + 1 < len(argv):
            area = argv[i + 1]

    if area not in ("all", *AREAS):
        print(f"未知区域：{area}（可选 all / {' / '.join(AREAS)}）")
        return 1

    scan_root = WORKSPACE if area == "all" else (WORKSPACE / AREAS[area])
    if not scan_root.is_dir():
        print(f"目录不存在：{scan_root}")
        return 1

    print(f"工作区：{WORKSPACE}")
    print(f"区域　：{area}" + ("（整个工作区）" if area == "all" else f" → {AREAS[area]}"))
    print(f"模式　：{'删除' if do_write else '仅列出（加 --write 才删除）'}"
          + ("，含 PDF" if with_pdf else "，保留 PDF"))
    print()

    found = collect(scan_root, with_pdf)
    if not found:
        print("没有找到编译产物，已经是干净的。")
        return 0

    total_files = total_size = 0
    for key in sorted(found):
        items = found[key]
        n = len(items)
        size = sum(s for _, s in items)
        total_files += n
        total_size += size
        kinds = sorted({(f.suffix.lower() or f.name.split(".")[-1]) for f, _ in items})
        print(f"  {key}")
        print(f"      {n} 个文件  {human(size)}   {', '.join(kinds[:8])}")

    print()
    print(f"合计：{total_files} 个文件，{human(total_size)}")

    if not do_write:
        print("\n以上仅列出。加 --write 执行删除。")
        return 0

    if not assume_yes:
        try:
            ans = input("\n确认删除以上编译产物？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 0
        if ans not in ("y", "yes"):
            print("已取消。")
            return 0

    removed = failed = 0
    freed = 0
    for items in found.values():
        for p, size in items:
            try:
                p.unlink()
                removed += 1
                freed += size
            except OSError as e:
                failed += 1
                print(f"  ✗ 删除失败：{p}（{e}）")

    print(f"\n完成：删除 {removed} 个文件，释放 {human(freed)}"
          + (f"，{failed} 个失败" if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
