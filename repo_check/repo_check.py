#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repo_check.py — 仓库体检

把「仓库规范」变成可自动核查项，避免每次搬家 / 改名 / 复制模板后靠肉眼盯：

1. `.gitignore` / `.gitattributes` 是否存在；
2. 有没有**被跟踪**的编译产物（这类文件一旦入库，日后的 diff 会被淹没）；
3. 有没有被跟踪的 `__pycache__`、本机配置文件（`*.conf`、`.cwl_source`、
   `.sensitive-words.txt`）、运行档案（`*_extract.json` / `notes_tree.json` /
   `progress_marks.json`）；
4. 是否有未提交改动、是否配置了远程。

只做只读检查，不改动任何文件。

    python repo_check.py              # 巡检全部区域
    python repo_check.py --area notes # 只查笔记区：notes / template / tools / all
"""
import os
import re
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/repo_check/
TOOLS_DIR = TOOL_DIR.parent
WORKSPACE = TOOLS_DIR.parent
MANAGER_CONF = TOOLS_DIR / "manager" / "manager.conf"

AREAS = {"notes": "LaTeX_Notes", "template": "Template", "tools": "Tools"}

# 不该进版本控制的编译产物
AUX_PAT = (r".*\.(aux|log|out|toc|lof|lot|fls|fdb_latexmk|synctex\.gz|xdv|listing"
           r"|nav|snm|vrb|bbl|blg|dvi)$")
# 不该进版本控制的本机 / 运行档案
LOCAL_PAT = r".*(\.conf$|\.cwl_source$|\.sensitive-words\.txt$|_extract\.json$|notes_tree\.json$|progress_marks\.json$|__pycache__)"


def sh(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout or "").strip()


def read_conf(path):
    d = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def all_repos(area):
    cfg = read_conf(MANAGER_CONF)
    repos = []
    if area in ("all", "notes"):
        notes = cfg.get("root", "")
        if notes and Path(notes).is_dir():
            root = Path(notes)
            repos += [(("笔记区" if area == "all" else ""), d)
                      for d in sorted(root.iterdir())
                      if d.is_dir() and (d / ".git").is_dir()]
    if area in ("all", "template", "tools"):
        for key in ("template", "tools"):
            if area != "all" and area != key:
                continue
            base = WORKSPACE / AREAS[key]
            if not base.is_dir():
                continue
            if key == "tools" and (base / ".git").is_dir():
                repos.append(("工具区", base))
                continue
            label = "模板区" if key == "template" else "工具区"
            repos += [(label, d) for d in sorted(base.iterdir())
                      if d.is_dir() and (d / ".git").is_dir()]
    return repos


def check_repo(d):
    """返回 (问题列表, 提示列表)。"""
    issues, notes = [], []

    for f in (".gitignore", ".gitattributes"):
        if not (d / f).is_file():
            issues.append(f"缺少 {f}")

    ok, tracked = sh(["git", "ls-files"], cwd=str(d))
    if not ok:
        issues.append("无法读取 git 索引")
        return issues, notes

    files = [ln for ln in tracked.splitlines() if ln.strip()]
    aux = [f for f in files if re.match(AUX_PAT, f)]
    local = [f for f in files if re.match(LOCAL_PAT, f)]

    if aux:
        issues.append(f"编译产物被跟踪（{len(aux)} 个）：{', '.join(aux[:3])}"
                      + (" …" if len(aux) > 3 else ""))
    if local:
        issues.append(f"本机/运行文件被跟踪（{len(local)} 个）：{', '.join(local[:3])}"
                      + (" …" if len(local) > 3 else ""))

    _, st = sh(["git", "status", "--porcelain"], cwd=str(d))
    n = len([ln for ln in st.splitlines() if ln.strip()])
    if n:
        notes.append(f"{n} 项未提交改动")

    _, rem = sh(["git", "remote", "get-url", "origin"], cwd=str(d))
    if not rem:
        notes.append("未配置远程")

    return issues, notes


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    area = "all"
    if "--area" in argv:
        i = argv.index("--area")
        if i + 1 < len(argv):
            area = argv[i + 1]
    if area not in ("all", *AREAS):
        print(f"未知区域：{area}（可选 all / {' / '.join(AREAS)}）")
        return 1

    print(f"工作区：{WORKSPACE}")
    print(f"区域　：{area}\n")

    repos = all_repos(area)
    if not repos:
        print("没有找到仓库。")
        return 1

    bad = 0
    for label, d in repos:
        issues, notes = check_repo(d)
        head = f"  {d.name}" if label in ("", "笔记区") else f"  [{label}] {d.name}"
        if issues:
            bad += 1
            print(f"{head}  ⚠ {len(issues)} 项问题")
            for x in issues:
                print(f"      ✗ {x}")
        else:
            print(f"{head}  ✓ 规范检查通过")
        for x in notes:
            print(f"      · {x}")

    print()
    if bad == 0:
        print(f"巡检 {len(repos)} 个仓库：全部通过。")
    else:
        print(f"巡检 {len(repos)} 个仓库：{bad} 个存在问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
