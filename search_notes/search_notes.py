#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_notes.py — 在笔记里搜索

跨多本笔记找关键字。写作时最常见的需求是「这个词我在哪本里写过」，逐个打开
笔记翻很慢，这里直接给文件 + 行号 + 上下文。

**不带参数运行就是交互面板**（从总面板进来就是这条路）：输入关键字即出结果，
可以连着搜；选项直接跟在关键字后面，不必记。

    python search_notes.py                           # 交互面板
    python search_notes.py 谱序列                     # 默认搜全部笔记的 .tex
    python search_notes.py compact -n MyNote          # 限定某本笔记
    python search_notes.py 定理 -e tex,md             # 限定扩展名
    python search_notes.py "R^{n}" -r                 # 按正则匹配
    python search_notes.py 模 -i                      # 忽略大小写

参数：`-n/--note` 笔记名　`-e/--ext` 扩展名（逗号分隔，默认 tex）
      `-r/--regex` 正则　`-i/--ignore-case` 忽略大小写
默认区分大小写；只读，不改动任何文件。
"""
import os
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/search_notes/
TOOLS_DIR = TOOL_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MANAGER_CONF = TOOLS_DIR / "manager" / "manager.conf"

SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "node_modules"}


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


def parse_query(argv):
    """解析命令行参数 → (keyword, use_regex, ignore_case, only_note, exts)。"""
    keyword = argv[0]
    use_regex = "--regex" in argv
    ignore_case = "-i" in argv or "--ignore-case" in argv

    only_note = None
    if "--note" in argv or "-n" in argv:
        i = argv.index("--note") if "--note" in argv else argv.index("-n")
        if i + 1 < len(argv):
            only_note = argv[i + 1]

    exts = {".tex"}
    if "--ext" in argv or "-e" in argv:
        i = argv.index("--ext") if "--ext" in argv else argv.index("-e")
        if i + 1 < len(argv):
            exts = {("." + e.strip().lstrip(".")) for e in argv[i + 1].split(",") if e.strip()}
    return keyword, use_regex, ignore_case, only_note, exts


def run_search(keyword, use_regex=False, ignore_case=False, only_note=None,
               exts=None, per_note=12):
    """执行一次检索并打印结果。返回 (命中总数, 涉及笔记数)；出错返回 None。"""
    exts = exts or {".tex"}
    root = notes_root()
    if not root:
        print("✗ 未找到笔记根目录")
        return None

    flags = re.IGNORECASE if ignore_case else 0
    try:
        pat = re.compile(keyword if use_regex else re.escape(keyword), flags)
    except re.error as e:
        print(f"✗ 正则无效：{e}")
        return None

    print(f"搜索：{keyword}" + ("（正则）" if use_regex else "")
          + ("（忽略大小写）" if ignore_case else "")
          + (f"  笔记：{only_note}" if only_note else "  范围：全部笔记")
          + f"  扩展名：{', '.join(sorted(exts))}\n")

    total = 0
    hit_files = 0
    notes = [d for d in sorted(root.iterdir())
             if d.is_dir() and not d.name.startswith((".", "_"))]
    if only_note and only_note not in {d.name for d in notes}:
        print(f"✗ 没有找到笔记「{only_note}」；现有："
              + "、".join(d.name for d in notes))
        return None

    for note in notes:
        if only_note and note.name != only_note:
            continue

        hits = []
        for p in sorted(note.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            if SKIP_DIRS & set(p.parts):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines, 1):
                if pat.search(ln):
                    hits.append((p.relative_to(note), i, ln.strip()[:100]))

        if not hits:
            continue
        hit_files += 1
        total += len(hits)
        print(f"  【{note.name}】{len(hits)} 处")
        for rel, i, text in hits[:per_note]:
            print(f"    {str(rel)}:{i}")
            print(f"        {text}")
        if len(hits) > per_note:
            print(f"    …（其余 {len(hits) - per_note} 处）")
        print()

    print(f"共 {total} 处，分布在 {hit_files} 本笔记。")
    return total, hit_files


def interactive():
    """没有参数时的交互面板：反复问关键字，就地出结果。"""
    root = notes_root()
    print("=" * 64)
    print("  笔记全文检索")
    print("=" * 64)
    if not root:
        print("  ✗ 未找到笔记根目录（manager.conf 的 root，或确认 LaTeX_Notes 存在）")
        return 1
    names = [d.name for d in sorted(root.iterdir())
             if d.is_dir() and not d.name.startswith((".", "_"))]
    print(f"  笔记根目录：{root}")
    print(f"  现有笔记  ：{'、'.join(names)}")
    print()
    print("  直接输入关键字即可（默认搜全部笔记的 .tex，区分大小写）。")
    print("  也可以跟选项：-i 忽略大小写／-r 正则／-n MyNote 限定笔记／-e tex,md 扩展名")
    print("  例：紧算子 -i      或      compact -n MyNote")
    print("  回车（或 q）退出。")
    print()

    while True:
        try:
            line = input("  关键字：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line.lower() in ("q", "quit", "exit"):
            break

        argv = line.split()
        if argv[0].startswith("-"):
            print("  ✗ 第一个词要是关键字（选项跟在后面）。\n")
            continue
        print()
        run_search(*parse_query(argv))
        print()
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    if not argv:                      # 无参数 → 交互面板
        return interactive()
    if argv[0].startswith("-"):       # 明显是选项写在了前面 → 给用法
        print(__doc__)
        return 1

    return 0 if run_search(*parse_query(argv)) else 1


if __name__ == "__main__":
    sys.exit(main())
