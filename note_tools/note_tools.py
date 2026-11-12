#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
note_tools.py — 单本笔记的工具入口

笔记目录里各有两个脚本，但它们必须在**笔记目录内**运行（`commit.py` 依赖同目录的
`.git`，`setup_mode.py` 读写同目录的 `Content/` 与 `ExerciseBook/`）。写笔记时
直接 `cd` 进去跑最顺手；本工具是给「想在面板里操作」的场合用的。

除上面两个脚本外，这里还有一项**补导引与小结**：按 new_note.py 的规则，给选中的
笔记补 `intro.tex`（本章导引）与各级 `Summary/`（小结），并把 `\input` 插进对应的
`index.tex`。只补缺、不覆盖，可以反复跑。

    python note_tools.py
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/note_tools/
TOOLS_DIR = TOOL_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MANAGER_CONF = TOOLS_DIR / "manager" / "manager.conf"

# 导引与小结的实现只在 new_note.py 里有一份，这里复用它，避免两边规则跑偏
sys.path.insert(0, str(TOOLS_DIR / "new_note"))
try:
    import new_note  # noqa: E402
except ImportError as _exc:   # 缺文件/语法错误不应让「提交并推送」这类无关功能一起崩
    new_note = None
    _NEW_NOTE_IMPORT_ERROR = _exc


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


def pick_note(root, name=None):
    """选一本笔记。给了 name 就直接用（图形面板没有标准输入可提问）。"""
    if name:
        cand = root / str(name).strip()
        if cand.is_dir():
            print(f"  笔记根目录：{root}")
            print(f"  选定笔记：{cand.name}")
            return cand
        print(f"  ✗ 在 {root} 下没有笔记「{name}」")
        return None
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
    # 打包成 exe 时没有外部 Python，让 exe 自己当解释器（--exec 模式）
    cmd = ([sys.executable, "--exec", script_name]
           if getattr(sys, "frozen", False) else [sys.executable, script_name])
    try:
        subprocess.run(cmd, cwd=str(note))
    except KeyboardInterrupt:
        print("\n  已中断。")
    except OSError as e:
        print(f"  ✗ 启动失败：{e}")


# ---------------------------------------------------------------- 补导引与小结

def pick_intro_summary_scope(choice=None):
    """问加哪些。返回 (do_intro, do_summary)；取消返回 None。

    给了 choice 就直接用：both/intro/summary，或 1/2/3。
    """
    if choice is not None:
        c = str(choice).strip().lower()
        if c in ("", "1", "both"):
            return True, True
        if c in ("2", "intro"):
            return True, False
        if c in ("3", "summary"):
            return False, True
        return None
    print("    1. 导引＋小结（默认）")
    print("    2. 只加导引（各章 intro.tex）")
    print("    3. 只加小结（各级 Summary/）")
    print("    0. 返回")
    while True:
        try:
            c = input("\n  选择：").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if c == "0":
            return None
        if c in ("", "1"):
            return True, True
        if c == "2":
            return True, False
        if c == "3":
            return False, True
        print("  请回答 1 / 2 / 3 / 0。")


def _quiet(_msg):
    """干跑时吞掉明细，只留我们自己排版的摘要。"""


def action_intro_summary(note, scope=None, assume_yes=False):
    """按 new_note.py 的规则给一本笔记补导引与小结（只补缺、不覆盖）。"""
    clear()
    print("=" * 62)
    print(f"  补导引与小结：{note.name}")
    print("=" * 62)
    if new_note is None:
        print(f"  ✗ 无法导入 new_note.py：{_NEW_NOTE_IMPORT_ERROR}")
        print("    请检查 Tools/new_note/ 是否存在且无语法错误。")
        return

    if scope is None:
        scope = pick_intro_summary_scope()
    elif isinstance(scope, str):
        # 图形面板直接给 "both"/"intro"/"summary"
        scope = pick_intro_summary_scope(scope)
    if scope is None:
        return
    do_intro, do_summary = scope

    try:
        levels, _depth, created, touched, skipped = new_note.add_intro_summary(
            note, do_intro=do_intro, do_summary=do_summary, dry=True, log=_quiet)
    except new_note.OutlineError as e:
        print(f"\n  ✗ {e}")
        return

    print(f"\n  层级模式：{new_note.describe_levels(levels)}")
    if not created and not touched:
        print(f"  没有要动的 —— 导引与小结都在，跳过已存在 {len(skipped)} 处。")
        return
    print(f"  将新建 {len(created)} 个文件，改动 {len(touched)} 个 index.tex，"
          f"跳过已存在 {len(skipped)} 处")
    for r in created[:20]:
        print(f"    ＋ {r}")
    if len(created) > 20:
        print(f"    …（其余 {len(created) - 20} 个文件）")
    for r in touched[:10]:
        print(f"    ~ {r}")
    if len(touched) > 10:
        print(f"    …（其余 {len(touched) - 10} 个 index.tex）")

    try:
        ans = input("\n  确认执行？[y/N]：").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    if ans not in ("y", "yes"):
        print("  已取消。")
        return

    try:
        levels, _depth, created, touched, _skipped = new_note.add_intro_summary(
            note, levels=levels, do_intro=do_intro, do_summary=do_summary,
            dry=False, log=_quiet)
    except (new_note.OutlineError, OSError) as e:
        print(f"\n  ✗ 写入失败：{e}")
        return

    print(f"\n  完成：新建 {len(created)} 个文件，改动 {len(touched)} 个 index.tex。")
    print("  改动尚未提交 —— 用「提交并推送」或笔记目录里的 commit.py。")


def parse_cli(argv):
    """解析非交互子命令（图形面板用）。"""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--note", help="笔记目录名；给了就跳过选本菜单")
    ap.add_argument("--action", choices=("commit", "exercise", "intro-summary"),
                    help="要做的动作；给了就只做这一件事")
    ap.add_argument("--scope", choices=("both", "intro", "summary"),
                    help="补导引小结的范围")
    ap.add_argument("--yes", action="store_true", help="补导引小结免确认")
    known, _unknown = ap.parse_known_args(argv)
    return known


def run_action(note, cli):
    """执行一个指定动作（非交互）。"""
    if cli.action == "commit":
        run_in_note(note, "commit.py")
    elif cli.action == "exercise":
        run_in_note(note, "setup_mode.py")
    elif cli.action == "intro-summary":
        action_intro_summary(note, scope=cli.scope, assume_yes=cli.yes)
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cli = parse_cli(sys.argv[1:])
    root = notes_root()
    clear()
    print("=" * 62)
    print("  笔记工具")
    print("=" * 62)
    if not root:
        print("  ✗ 未找到笔记根目录（请在 manager 里设置，或确认 LaTeX_Notes 存在）")
        return 1

    note = pick_note(root, cli.note)
    if note is None:
        clear()
        return 0

    if cli.action:
        return run_action(note, cli)

    while True:
        clear()
        print("=" * 62)
        print(f"  {note.name}")
        print("=" * 62)
        print("    1. 提交并推送（调用该笔记的 commit.py）")
        print("    2. 切换习题编排模式（调用该笔记的 setup_mode.py）")
        print("    3. 补导引与小结（章导引 / 各级小结，只补缺）")
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
        elif c == "3":
            action_intro_summary(note)
            pause()

    clear()
    return 0


if __name__ == "__main__":
    sys.exit(main())
