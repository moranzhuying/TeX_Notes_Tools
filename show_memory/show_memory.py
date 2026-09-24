#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
show_memory.py — 查看工作记录

工作区里的 `.workbuddy/memory/` 存着按日期归档的工作日志和一份长期记忆
（`MEMORY.md`）。这些记录平时不看，但「上次改到哪儿了」「为什么当初这么定」
往往只能从这里找。

    python show_memory.py                # 列出所有记录（按日期倒序）
    python show_memory.py --last 3       # 看最近 3 天
    python show_memory.py 2026-09-24     # 看某一天
    python show_memory.py MEMORY         # 看长期记忆
    python show_memory.py --list         # 只列文件名

只读。
"""
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/show_memory/
TOOLS_DIR = TOOL_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MEM_DIR = WORKSPACE / ".workbuddy" / "memory"


def entries():
    if not MEM_DIR.is_dir():
        return []
    return sorted((p for p in MEM_DIR.glob("*.md")), key=lambda p: p.name, reverse=True)


def show(path, limit=None):
    print("=" * 62)
    print(f"  {path.name}    （{path.stat().st_size} 字节）")
    print("=" * 62)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if limit and len(lines) > limit:
        for ln in lines[:limit]:
            print(ln)
        print(f"\n…（共 {len(lines)} 行，已显示前 {limit} 行）")
    else:
        for ln in lines:
            print(ln)
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    items = entries()

    if not items:
        print(f"✗ 未找到记录目录：{MEM_DIR}")
        return 1

    if "--list" in argv:
        for p in items:
            print(f"  {p.name}")
        return 0

    if not argv:
        print(f"记录目录：{MEM_DIR}\n")
        for i, p in enumerate(items, 1):
            print(f"  {i:>2}. {p.name:<18} {p.stat().st_size:>7} 字节")
        print("\n用法：python show_memory.py <日期|编号|MEMORY>  |  --last N  |  --list")
        return 0

    if "--last" in argv:
        i = argv.index("--last")
        n = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 1
        for p in items[:n]:
            show(p)
        return 0

    key = argv[0]
    if key.upper() == "MEMORY":
        for p in items:
            if p.stem.upper() == "MEMORY":
                show(p)
                return 0
        print("✗ 未找到 MEMORY.md")
        return 1

    for p in items:
        if p.stem == key or p.name == key:
            show(p)
            return 0

    if key.isdigit() and 1 <= int(key) <= len(items):
        show(items[int(key) - 1])
        return 0

    print(f"✗ 没有匹配的记录：{key}")
    print("   可用：--list 查看全部，或直接给日期（如 2026-09-24）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
