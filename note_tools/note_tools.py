#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
note_tools.py — 单本笔记的工具入口

笔记目录里各有两个脚本，但它们必须在**笔记目录内**运行（`commit.py` 依赖同目录的
`.git`，`setup_mode.py` 读写同目录的 `Content/` 与 `ExerciseBook/`）。写笔记时
直接 `cd` 进去跑最顺手；本工具是给「想在面板里操作」的场合用的。

    python note_tools.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/note_tools/
TOOLS_DIR = TOOL_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MANAGER_CONF = TOOLS_DIR / "manager" / "manager.conf"


def clear():
    """清屏，使画面只保留当前内容（与其它工具保持一致）。"""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def pause():
    print()
    try:
        input("按回车返回…")
    except EOFError:
        pass


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
    """笔记根目录：优先取 manager.conf 的 root，其次用工作区下的 LaTeX_Notes。"""
    cfg = read_conf(MANAGER_CONF)
    root = cfg.get("root", "")
    if root:
        p = Path(os.path.expandvars(root))
        if p.is_dir():
            return p
    guess = WORKSPACE / "LaTeX_Notes"
    return guess if guess.is_dir() else None


def list_notes(root):
    ignore = {s for s in read_conf(MANAGER_CONF).get("ignore", "").split(",") if s}
    out = []
    for e in sorted(root.iterdir()):
        if not e.is_dir() or e.name.startswith(".") or e.name.startswith("_"):
            continue
        if e.name in ignore or "Archieved" in e.name:
            continue
        if not (e / "main.tex").is_file():
            continue
        out.append(e)
    return out


def changed_count(note):
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=str(note),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return len([ln for ln in r.stdout.splitlines() if ln.strip()])
    except Exception:
        return -1


def pick_note(root):
    notes = list_notes(root)
    if not notes:
        print(f"  ✗ 在 {root} 下没有找到笔记（需含 main.tex 的子目录）")
        return None

    print(f"  笔记根目录：{root}\n")
    for i, n in enumerate(notes, 1):
        c = changed_count(n)
        tag = "未提交改动" if c > 0 else "无改动"
        print(f"    {i}. {n.name:<42} {c if c >= 0 else '?'} 项（{tag}）")
    print("    0. 返回\n")

    while True:
        try:
            ans = input("  选择笔记编号：").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if ans == "0" or not ans:
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(notes):
            return notes[int(ans) - 1]


def run_in_note(note, script_name):
    script = note / script_name
    if not script.is_file():
        print(f"  ✗ {note.name} 下没有 {script_name}")
        return
    try:
        subprocess.run([sys.executable, script_name], cwd=str(note))
    except KeyboardInterrupt:
        print("\n  已中断。")
    except OSError as e:
        print(f"  ✗ 启动失败：{e}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    root = notes_root()
    clear()
    print("=" * 62)
    print("  笔记工具")
    print("=" * 62)
    if not root:
        print("  ✗ 未找到笔记根目录（请在 manager 里设置，或确认 LaTeX_Notes 存在）")
        return 1

    note = pick_note(root)
    if note is None:
        clear()
        return 0

    while True:
        clear()
        print("=" * 62)
        print(f"  {note.name}")
        print("=" * 62)
        print("    1. 提交并推送（调用该笔记的 commit.py）")
        print("    2. 切换习题编排模式（调用该笔记的 setup_mode.py）")
        print("    0. 返回")
        print("=" * 62)
        try:
            c = input("\n  选择：").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if c == "0" or not c:
            break
        if c == "1":
            run_in_note(note, "commit.py")
            pause()
        elif c == "2":
            run_in_note(note, "setup_mode.py")
            pause()

    clear()
    return 0


if __name__ == "__main__":
    sys.exit(main())
