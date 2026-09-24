#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_aux.py — 清理 LaTeX 编译产物

编译一次就会留下 `.aux/.log/.xdv/.fls/...` 一堆中间文件。它们都被各仓库的
`.gitignore` 忽略、不会误提交，但会一直堆积占地方。

本工具按仓库分组列出占用，确认后再删。

**不带参数运行就是交互面板**（从总面板进来就是这条路）：列出各仓库占用后，
直接填序号选要清的（`a` 全部、`1,3` 或 `2-4` 选几个），不用记选项。

    python clean_aux.py                # 交互面板
    python clean_aux.py --write        # 删除全部（会先确认）
    python clean_aux.py --write --yes  # 删除且不确认
    python clean_aux.py --with-pdf     # 连同 PDF 一起清
    python clean_aux.py --area notes   # 只处理某区域：notes / template / tools / all

安全性：只按**扩展名**匹配编译产物，绝不触碰源码；默认不动 PDF（那通常是
你真正想留的东西）。
"""
import os
import sys
from pathlib import Path

# <工作区>/Tools/clean_aux/ → 工作区根
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


def scan(root, with_pdf):
    """扫描 + 打印分组。返回有序的 [(仓库相对路径, [(文件, 大小), ...]), ...]。"""
    found = collect(root, with_pdf)
    groups = [(k, found[k]) for k in sorted(found)]
    if not groups:
        print("没有找到编译产物，已经是干净的。")
        return []

    total_files = total_size = 0
    for i, (key, items) in enumerate(groups, 1):
        n = len(items)
        size = sum(s for _, s in items)
        total_files += n
        total_size += size
        kinds = sorted({(f.suffix.lower() or f.name.split(".")[-1]) for f, _ in items})
        print(f"  {i}. {key}")
        print(f"       {n} 个文件  {human(size)}   {', '.join(kinds[:8])}")

    print()
    print(f"合计：{total_files} 个文件，{human(total_size)}")
    return groups


def parse_selection(text, n):
    """`1,3` / `2-4` / `a` → 序号列表（1 基）。空串或非法返回 None。"""
    t = text.strip().lower()
    if t in ("a", "all", "*"):
        return list(range(1, n + 1))
    picked = []
    for piece in t.replace(" ", "").split(","):
        if not piece:
            continue
        if "-" in piece:
            lo, _, hi = piece.partition("-")
            if not (lo.isdigit() and hi.isdigit()):
                return None
            picked += list(range(int(lo), int(hi) + 1))
        elif piece.isdigit():
            picked.append(int(piece))
        else:
            return None
    picked = sorted({i for i in picked if 1 <= i <= n})
    return picked or None


def delete_items(items):
    """删除给定文件，返回 (成功数, 失败数, 释放字节)。"""
    removed = failed = freed = 0
    for p, size in items:
        try:
            p.unlink()
            removed += 1
            freed += size
        except OSError as e:
            failed += 1
            print(f"  ✗ 删除失败：{p}（{e}）")
    return removed, failed, freed


def confirm(prompt):
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return False


def interactive():
    """没有参数时的交互面板：列出来，直接选着删。"""
    area, with_pdf = "all", False
    while True:
        scan_root = WORKSPACE if area == "all" else (WORKSPACE / AREAS[area])
        print("=" * 64)
        print("  清理 LaTeX 编译产物")
        print("=" * 64)
        print(f"  区域：{area}" + ("（整个工作区）" if area == "all" else f" → {AREAS[area]}")
              + f"　　PDF：{'一起清理' if with_pdf else '保留'}")
        print()
        if not scan_root.is_dir():
            print(f"  ✗ 目录不存在：{scan_root}")
            return 1
        groups = scan(scan_root, with_pdf)
        if not groups:
            return 0

        print()
        print("  要删哪些？")
        print("     a        全部删除（下面这些仓库目录里的编译产物）")
        print("     1 或 1,3 或 2-4   只删这几个序号")
        print("     p        连 PDF 一起处理（再列一次）")
        print("     notes / template / tools / all   换区域")
        print("     回车     什么都不删，退出")
        try:
            ans = input("\n  选择：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        low = ans.lower()
        if not low:
            break
        if low == "p":
            with_pdf = not with_pdf
            continue
        if low in ("all", *AREAS):
            area = low
            continue
        picked = parse_selection(low, len(groups))
        if not picked:
            print("  ✗ 没看懂，用 a / 序号 / p / 区域名 / 回车。")
            continue

        targets = [it for i in picked for it in groups[i - 1][1]]
        size = sum(s for _, s in targets)
        if not confirm(f"\n  确认删除 {len(targets)} 个文件（{human(size)}）？"):
            continue
        removed, failed, freed = delete_items(targets)
        print(f"\n  ✓ 删除 {removed} 个文件，释放 {human(freed)}"
              + (f"，{failed} 个失败" if failed else ""))
        input("\n  按回车继续（重新扫描）…")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    if not argv:                      # 无参数 → 交互面板
        return interactive()

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

    groups = scan(scan_root, with_pdf)
    if not groups:
        return 0

    if not do_write:
        print("\n以上仅列出。加 --write 执行删除（不带参数运行则是交互面板）。")
        return 0

    if not assume_yes and not confirm("\n确认删除以上编译产物？"):
        print("已取消。")
        return 0

    removed, failed, freed = delete_items([it for _k, items in groups for it in items])
    print(f"\n完成：删除 {removed} 个文件，释放 {human(freed)}"
          + (f"，{failed} 个失败" if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
