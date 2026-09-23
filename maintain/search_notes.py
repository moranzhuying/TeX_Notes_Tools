#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_notes.py — 在笔记里搜索

跨多本笔记找关键字。写作时最常见的需求是「这个词我在哪本里写过」，逐个打开
笔记翻很慢，这里直接给文件 + 行号 + 上下文。

    python search_notes.py 谱序列                    # 默认搜全部笔记的 .tex
    python search_notes.py compact --note Algebra    # 限定某本笔记
    python search_notes.py 定理 --ext tex,md         # 限定扩展名
    python search_notes.py "R^{n}" --regex           # 按正则匹配

默认区分大小写；加 `-i` / `--ignore-case` 忽略大小写。
只读，不改动任何文件。
"""
import os
import re
import sys
from pathlib import Path

MAINTAIN_DIR = Path(__file__).resolve().parent
TOOLS_DIR = MAINTAIN_DIR.parent
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


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 1

    keyword = argv[0]
    use_regex = "--regex" in argv
    ignore_case = "-i" in argv or "--ignore-case" in argv

    only_note = None
    if "--note" in argv:
        i = argv.index("--note")
        if i + 1 < len(argv):
            only_note = argv[i + 1]

    exts = {".tex"}
    if "--ext" in argv:
        i = argv.index("--ext")
        if i + 1 < len(argv):
            exts = {("." + e.strip().lstrip(".")) for e in argv[i + 1].split(",") if e.strip()}

    root = notes_root()
    if not root:
        print("✗ 未找到笔记根目录")
        return 1

    flags = re.IGNORECASE if ignore_case else 0
    try:
        pat = re.compile(keyword if use_regex else re.escape(keyword), flags)
    except re.error as e:
        print(f"✗ 正则无效：{e}")
        return 1

    print(f"搜索：{keyword}" + ("（正则）" if use_regex else "")
          + (f"  笔记：{only_note}" if only_note else "  范围：全部笔记")
          + f"  扩展名：{', '.join(sorted(exts))}\n")

    total = 0
    hit_files = 0
    for note in sorted(root.iterdir()):
        if not note.is_dir() or note.name.startswith((".", "_")):
            continue
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
        for rel, i, text in hits[:12]:
            print(f"    {str(rel)}:{i}")
            print(f"        {text}")
        if len(hits) > 12:
            print(f"    …（其余 {len(hits) - 12} 处）")
        print()

    print(f"共 {total} 处，分布在 {hit_files} 本笔记。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
