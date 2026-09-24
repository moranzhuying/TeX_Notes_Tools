#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — 工具集总面板

Tools 下每个工具各占一个子目录，本脚本是它们的统一入口：

| 目录        | 工具                                                       |
|-------------|------------------------------------------------------------|
| `manager/`  | 笔记工作区管理（仓库状态 / 批量提交 / 建仓库）              |
| `symbols/`  | 符号库管理（提取 / 回填 / 刷新补全 / 分发）                 |
| `progress/` | 写作进度追踪表（浏览器查看）                                |
| `maintain/` | 新建笔记、大纲工具、笔记工具、清理编译产物、仓库体检、检索   |
| `guard/`    | 环境配置、提交前扫描、路径检查、提交脚本                    |

除「提交前本机信息扫描」「配置路径检查」两项是直接带参数跑完之后回到面板，
其余各项都是**进入自己的交互面板**，在里面就能完成操作（不必再敲命令行参数）。

用法：
    python launcher.py
"""
import os
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent
WORKSPACE = TOOLS_ROOT.parent

# (序号, 标题, 相对脚本路径, 运行方式, 分组)
#   面板 = 前台运行，退出后回到本面板
#   后台 = 启动后立即返回（服务类）
#   参数 = 前台运行并附加命令行参数
MENU = [
    ("1", "设置 git 基本信息（环境检测 / 账户 / SSH）", "guard/git_setup.py", "面板", "核心工具"),
    ("2", "笔记工作区管理（仓库状态 / 批量提交 / 建仓库）", "manager/manager.py", "面板", "核心工具"),
    ("3", "符号库管理", "symbols/symbols.py", "面板", "核心工具"),
    ("4", "写作进度追踪表", "progress/progress.py", "后台", "核心工具"),

    ("5", "从模板新建笔记", "maintain/new_note.py", "面板", "创建与维护"),
    ("6", "大纲工具（创建 / 导出 / 校验）", "maintain/outline_tool.py", "面板", "创建与维护"),
    ("7", "笔记工具（提交 / 切换习题编排模式）", "maintain/note_tools.py", "面板", "创建与维护"),
    ("8", "清理编译产物（aux / log / xdv …）", "maintain/clean_aux.py", "面板", "创建与维护"),
    ("9", "仓库体检（规范 / 误跟踪 / 未提交）", "maintain/repo_check.py", "面板", "创建与维护"),
    ("10", "本地全文检索", "maintain/search_notes.py", "面板", "创建与维护"),

    ("11", "提交前本机信息扫描（全量体检）", "guard/check_sensitive.py", "参数:--tracked", "信息安全与提交"),
    ("12", "配置路径检查与修复", "guard/sync_paths.py", "参数:", "信息安全与提交"),
    ("13", "提交本工具集到 GitHub", "guard/commit.py", "面板", "信息安全与提交"),
]

SUBMIT_NO = "13"          # 打 * 标记的那一项


def clear():
    """清屏，使画面只保留当前内容（与 symbols.py / manager.py 保持一致）。"""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def show_menu():
    print("=" * 64)
    print("  LaTeX 笔记工具集")
    print("=" * 64)
    print(f"  工作区：{WORKSPACE}")
    print(f"  工具根：{TOOLS_ROOT}")
    print("-" * 64)
    group = None
    for no, title, _rel, _mode, grp in MENU:
        if grp != group:
            print(f"  ── {grp} ──")
            group = grp
        mark = "*" if no == SUBMIT_NO else " "
        print(f" {mark}{no:>2}. {title}")
    print("-" * 64)
    print("   0. 退出")
    print("=" * 64)


def run(item):
    """执行菜单项。返回 False 表示无需等待回车。"""
    _no, _title, rel, mode, _grp = item
    script = TOOLS_ROOT / rel
    if not script.is_file():
        print(f"  ✗ 未找到 {rel}")
        return True

    args = [sys.executable, str(script)]
    if mode.startswith("参数"):
        extra = mode.split(":", 1)[1].strip() if ":" in mode else ""
        if extra:
            args += extra.split()

    try:
        if mode == "后台":
            subprocess.Popen(args, cwd=str(script.parent))
            print("  已在后台启动，本面板可继续使用。")
            return False
        subprocess.run(args, cwd=str(script.parent))
    except KeyboardInterrupt:
        print("\n  已中断。")
    except OSError as e:
        print(f"  ✗ 启动失败：{e}")
    return True


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    while True:
        clear()
        show_menu()
        try:
            choice = input("\n  选择（回车退出）: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not choice or choice == "0":
            break

        item = next((m for m in MENU if m[0] == choice), None)
        if item is None:
            continue

        clear()
        print("=" * 64)
        print(f"  【{item[0]}】{item[1]}")
        print("=" * 64)
        print()

        if run(item):
            try:
                input("\n  按回车返回面板…")
            except (EOFError, KeyboardInterrupt):
                break

    clear()
    print("  已退出工具集面板。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
