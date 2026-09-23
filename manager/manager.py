#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manager.py — 笔记工作区管理面板

用于在新环境中准备 Git 环境、配置远程账户，并统一管理笔记根目录下
各子文件夹的仓库（查看状态、批量提交推送、为新建文件夹创建仓库）。

用法：
    python manager.py          # 进入交互式面板
    python manager.py --help   # 显示用法

配置保存在脚本同目录的 manager.conf（含本机路径，请勿入库）。
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CONF_NAME = "manager.conf"

# 本脚本在 <Tools>/manager/ 下，向上两级即工作区根
TOOLS_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = TOOLS_DIR.parent

# 本脚本在 <Tools>/manager/ 下，向上两级即工作区根
TOOLS_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = TOOLS_DIR.parent

PANEL = """==============================================================
  笔记工作区管理面板
==============================================================
  笔记根目录：{root}
  已识别仓库：{n_repo} 个 / 子文件夹 {n_dir} 个
  远程账户　：{account}
--------------------------------------------------------------
  1. 设置笔记根目录（扫描子文件夹，识别仓库）
  2. 显示各仓库状态（远程 / 分支 / 改动数 / 领先落后）
  3. 批量提交并推送（对所有有改动的仓库）
  4. 为未入版本控制的文件夹创建仓库并首次推送
  0. 退出
--------------------------------------------------------------
  可多选，用英文逗号分隔（如 1,3）
"""

GITIGNORE = """# ===== LaTeX 编译中间产物 =====
*.aux
*.log
*.out
*.toc
*.lof
*.lot
*.fls
*.fdb_latexmk
*.synctex.gz
*.synctex
*.bbl
*.blg
*.nav
*.snm
*.vrb
*.idx
*.ind
*.ilg
*.xdv
*.run.xml
*-blx.bib

# ===== 编译输出 PDF =====
/main.pdf

# ===== 备份文件 =====
*.bak
*.bak-*
*.old

# ===== 编辑器与系统文件 =====
.DS_Store
Thumbs.db
desktop.ini
*.swp
*~

# ===== 本地工具配置（含本机路径，不入版本控制） =====
.cwl_source
symbols.conf
symbols_extract.json
notes_tree.json
manager.conf
"""

GITATTRIBUTES = """# 统一使用 LF 换行符，避免 Windows 编辑后产生全文件差异
* text=auto eol=lf

# 明确声明二进制文件
*.pdf binary
*.synctex.gz binary
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
"""

# ---------------------------------------------------------------- 基础


def run(cmd, cwd=None, timeout=120):
    """执行外部命令，返回 (是否成功, 标准输出, 标准错误)。"""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, "", f"未找到命令：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "", "命令超时"


def git(args, cwd=None):
    return run(["git"] + args, cwd=cwd)


def clear():
    """清屏，使画面只保留当前选项的内容。"""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def push_with_fallback(d, name):
    """推送，失败时自动重试并尝试备选通道。返回 (是否成功, 说明)。"""
    delays = [3, 6]
    for i, delay in enumerate([0] + delays):
        if delay:
            print(f"    …等待 {delay} 秒后重试（第 {i} 次）")
            time.sleep(delay)
        ok, _, err = git(["push"], cwd=d)
        if ok:
            return True, "已推送" if i == 0 else f"已推送（第 {i + 1} 次尝试成功）"
        last = err or "未知原因"

    # 备选通道：SSH 换端口（443 不通时试 22，反之亦然）
    if "ssh" in (git(["remote", "get-url", "origin"], cwd=d)[1] or "").lower():
        print("    …尝试备选通道：改用 22 端口")
        env_old = os.environ.get("GIT_SSH_COMMAND")
        os.environ["GIT_SSH_COMMAND"] = "ssh -p 22 -o StrictHostKeyChecking=accept-new"
        try:
            ok, _, err = git(["push"], cwd=d)
        finally:
            if env_old is None:
                os.environ.pop("GIT_SSH_COMMAND", None)
            else:
                os.environ["GIT_SSH_COMMAND"] = env_old
        if ok:
            print("    ✓ 已通过 22 端口推送。若长期有效，可把 ~/.ssh/config 里的 Port 改为 22")
            return True, "已推送（22 端口）"
        last = err or last

    return False, diagnose(last)


def diagnose(err):
    """把 git 的报错归类成可读的提示。"""
    low = (err or "").lower()
    if "permission denied" in low or "publickey" in low:
        return "认证失败 —— SSH 密钥未被 GitHub 接受。请用面板选项 3 检查密钥与连通性。"
    if "could not resolve" in low or "name or service not known" in low:
        return "域名解析失败 —— 检查网络与 DNS 设置。"
    if "timed out" in low or "timeout" in low or "connection refused" in low:
        return "连接超时或被拒 —— 检查网络；若使用代理，请确认 git 的 http.proxy 设置。"
    if "no configured push destination" in low or "no remote" in low:
        return "未配置远程仓库 —— 请先执行 git remote add origin <仓库地址>。"
    if "repository not found" in low or "does not exist" in low:
        return "仓库不存在或无权限 —— 检查仓库名与账户，确认远程仓库已创建。"
    if "non-fast-forward" in low or "rejected" in low:
        return "远程有新提交，本地落后 —— 先执行 git pull --rebase 再推送。"
    return f"推送失败：{err.splitlines()[0][:120] if err else '未知原因'}"


def pause():
    print()
    try:
        input("按回车返回面板…")
    except EOFError:
        pass


def load_conf():
    d = {"root": "", "account": ""}
    p = Path(__file__).with_name(CONF_NAME)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def save_conf(d):
    p = Path(__file__).with_name(CONF_NAME)
    with open(p, "w", encoding="utf-8", newline="") as f:
        for k, v in d.items():
            f.write(f"{k} = {v}\n")


def subdirs(root):
    """根目录下的子文件夹（忽略隐藏目录与常见非仓库目录）。"""
    if not root or not Path(root).is_dir():
        return []
    out = []
    for e in sorted(Path(root).iterdir()):
        if not e.is_dir() or e.name.startswith(".") or e.name.startswith("_"):
            continue
        out.append(e)
    return out


def repos(root):
    return [d for d in subdirs(root) if (d / ".git").is_dir()]


def zones(cfg):
    """列出所有「区域」：[(区域名, 路径), ...]

    笔记区取 manager.conf 的 root；工作区下的其它目录若其子目录里有 git 仓库，
    也算一个区域（模板区、工具区）。这样状态总览与批量提交就能覆盖整个工作区，
    而不只是笔记区。
    """
    out = []
    notes = cfg.get("root", "")
    notes_p = Path(notes) if notes else None
    if notes_p and notes_p.is_dir():
        out.append(("笔记区", notes_p))

    if not WORKSPACE.is_dir():
        return out
    for e in sorted(WORKSPACE.iterdir()):
        if not e.is_dir() or e.name.startswith(".") or e.name.startswith("_"):
            continue
        if notes_p and e == notes_p:
            continue
        if e == TOOLS_DIR:
            out.append(("工具区", e))
            continue
        try:
            has_repo = any(sub.is_dir() and (sub / ".git").is_dir() for sub in e.iterdir())
        except OSError:
            has_repo = False
        if has_repo:
            out.append((e.name, e))
    return out


def zone_repos(zpath):
    """区域内的仓库列表。

    除了「其下有 .git 的子目录」，还要看**该目录自身**是不是仓库 ——
    工具区（Tools/）本身就是仓库，没有夹一层子目录。
    """
    out = []
    if (zpath / ".git").is_dir():
        out.append(zpath)
    out += [d for d in subdirs(zpath) if (d / ".git").is_dir()]
    return out


def zones(cfg):
    """列出所有「区域」：[(区域名, 路径), ...]

    笔记区取 manager.conf 的 root；工作区下的其它目录若其子目录里有 git 仓库，
    也算一个区域（模板区、工具区）。这样状态总览与批量提交就能覆盖整个工作区，
    而不只是笔记区。
    """
    out = []
    notes = cfg.get("root", "")
    notes_p = Path(notes) if notes else None
    if notes_p and notes_p.is_dir():
        out.append(("笔记区", notes_p))

    if not WORKSPACE.is_dir():
        return out
    for e in sorted(WORKSPACE.iterdir()):
        if not e.is_dir() or e.name.startswith(".") or e.name.startswith("_"):
            continue
        if notes_p and e == notes_p:
            continue
        if e == TOOLS_DIR:
            out.append(("工具区", e))
            continue
        try:
            has_repo = any(sub.is_dir() and (sub / ".git").is_dir() for sub in e.iterdir())
        except OSError:
            has_repo = False
        if has_repo:
            out.append((e.name, e))
    return out


# ---------------------------------------------------------------- 功能


def set_root(cfg):
    print("【一】设置笔记根目录\n")
    print(f"  当前：{cfg.get('root') or '（未设置）'}\n")
    new = input("新的根目录（回车保持不变）：").strip().strip('"')
    if not new:
        print("  未作改动。")
        return cfg
    if not Path(new).is_dir():
        print(f"  ✗ 目录不存在：{new}")
        return cfg
    cfg["root"] = new
    save_conf(cfg)
    ds = subdirs(new)
    rs = [d for d in ds if (d / ".git").is_dir()]
    print(f"  ✓ 已设为 {new}")
    print(f"    子文件夹 {len(ds)} 个，其中 git 仓库 {len(rs)} 个")

    acct = input("\n  远程账户名（如 GitHub 用户名，回车保持不变）：").strip()
    if acct:
        cfg["account"] = acct
        save_conf(cfg)
        print(f"  ✓ 远程账户设为 {acct}")
    return cfg


def show_status(cfg):
    print("【二】各仓库状态\n")
    zs = zones(cfg)
    if not zs:
        print("  ✗ 没有找到任何区域（请先用选项 1 设置笔记根目录）。")
        return

    total = 0
    for zname, zpath in zs:
        rs = zone_repos(zpath)
        print(f"  【{zname}】{zpath}")
        if not rs:
            print("    （没有 git 仓库）\n")
            continue
        print(f"    {'文件夹':<34} {'分支':<8} {'改动':>4} {'领先/落后':>10}  远程")
        print("    " + "-" * 84)
        for d in rs:
            _, br, _ = git(["branch", "--show-current"], cwd=d)
            _, st, _ = git(["status", "--porcelain"], cwd=d)
            _, rem, _ = git(["remote", "get-url", "origin"], cwd=d)
            ahead = behind = "-"
            if rem:
                ok, out, _ = git(["rev-list", "--left-right", "--count",
                                  f"origin/{br or 'master'}...HEAD"], cwd=d)
                if ok and out:
                    parts = out.split()
                    if len(parts) == 2:
                        behind, ahead = parts[0], parts[1]
            repo = rem.rstrip("/").split("/")[-1].replace(".git", "") if rem else "✗ 无远程"
            n = len(st.splitlines()) if st else 0
            mark = "✓" if (rem and n == 0 and ahead in ("0", "-")) else ("!" if n else "")
            track = f"{ahead}/{behind}" if ahead != "-" else "—"
            print(f"    {d.name:<34} {br or '-':<8} {n:>4} {track:>9}  {repo} {mark}")
        total += len(rs)
        print()

    print(f"  合计 {total} 个仓库")
def pick_repos(cfg, skip_clean=False):
    """让用户选择要操作的仓库（跨所有区域）；返回选中的目录列表。"""
    items = []
    for zname, zpath in zones(cfg):
        for d in zone_repos(zpath):
            if skip_clean and not git(["status", "--porcelain"], cwd=d)[1]:
                continue
            items.append((zname, d))

    if not items:
        print("  没有符合条件的仓库。")
        return []

    print("  可操作的仓库：")
    cur = None
    for i, (zname, d) in enumerate(items, 1):
        if zname != cur:
            print(f"    [{zname}]")
            cur = zname
        n = len(git(["status", "--porcelain"], cwd=d)[1].splitlines())
        print(f"    {i:>2}. {d.name:<38} {n} 项改动")

    print("\n  输入编号（英文逗号分隔，回车＝全选，0＝取消）：")
    sel = input("  > ").strip()
    if sel == "0":
        return []
    if not sel:
        return [d for _, d in items]
    out = []
    for s in sel.replace("，", ",").split(","):
        s = s.strip()
        if s.isdigit() and 1 <= int(s) <= len(items):
            out.append(items[int(s) - 1][1])
    return out


def commit_push_all(cfg):
    print("【三】批量提交并推送\n")
    targets = pick_repos(cfg, skip_clean=True)
    if not targets:
        return
    print(f"\n  将对 {len(targets)} 个仓库执行：add → commit → push")

    msg = input(f"  统一提交说明（回车＝「{DEFAULT_MSG}」）：").strip() or DEFAULT_MSG
    only_push = input("  只推送、不提交？[y/N] ").strip().lower() in ("y", "yes")

    print()
    done, pushed, failed = 0, 0, []
    for d in targets:
        print(f"  ▶ {d.name}")
        if not only_push:
            ok, _, err = git(["add", "-A"], cwd=d)
            if not ok:
                print(f"    ✗ 暂存失败：{err[:120]}")
                failed.append((d.name, "暂存失败"))
                continue
            ok, _, err = git(["commit", "-m", msg], cwd=d)
            if not ok:
                print(f"    ✗ 提交失败：{err[:120]}")
                failed.append((d.name, "提交失败"))
                continue
            done += 1
            print("    ✓ 已提交")
        ok, info = push_with_fallback(d, d.name)
        if ok:
            pushed += 1
            print(f"    ✓ {info}")
        else:
            print(f"    ⚠ {info}")
            failed.append((d.name, info))

    print(f"\n  汇总：提交 {done} 个，推送成功 {pushed} 个")
    if failed:
        print("  未完成：")
        for name, why in failed:
            print(f"    {name}：{why}")
        print("  推送失败的仓库，本地提交已成功，网络恢复后重跑本选项即可。")


def create_repo(cfg):
    print("【四】为未入版本控制的文件夹创建仓库\n")
    root = cfg.get("root")
    if not root or not Path(root).is_dir():
        print("  ✗ 尚未设置有效的笔记根目录（请先用选项 1）。")
        return
    skip = set(cfg.get("ignore", "").replace("，", ",").split(","))
    skip.discard("")
    todo = [d for d in subdirs(root)
            if not (d / ".git").is_dir()
            and d.name not in skip
            and "rchieved" not in d.name]
    if not todo:
        print("  没有需要创建仓库的子文件夹。")
        return

    print("  未入版本控制的文件夹：")
    for i, d in enumerate(todo, 1):
        print(f"    {i:>2}. {d.name}")
    print("\n  输入编号（英文逗号分隔，回车＝全选，0＝取消）：")
    sel = input("  > ").strip()
    if sel == "0":
        return
    if not sel:
        idxs = list(range(1, len(todo) + 1))
    else:
        idxs = [int(s) for s in sel.replace("，", ",").split(",") if s.strip().isdigit()]
    targets = [todo[i - 1] for i in idxs if 1 <= i <= len(todo)]

    acct = cfg.get("account") or input("  GitHub 账户名：").strip()
    if not acct:
        print("  ✗ 需要账户名才能创建远程仓库。")
        return

    # 检测 gh 是否可用
    ok, out, _ = run(["gh", "--version"])
    gh_ok = ok
    if gh_ok:
        ok2, out2, _ = run(["gh", "auth", "status"], timeout=30)
        gh_ok = ok2
    print(f"\n  gh 命令行：{'✓ 可用，将自动创建远程仓库' if gh_ok else '✗ 不可用，将只做本地准备'}")

    if not gh_ok:
        print("  （如需自动创建，请先安装并登录 gh；否则按下面的提示在网页上建仓库）")

    print()
    for d in targets:
        print(f"  ▶ {d.name}")
        for name, content in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES)):
            p = d / name
            if not p.is_file():
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
                print(f"    已创建 {name}")

        ok, _, err = git(["init", "-b", "master"], cwd=d)
        if not ok:
            ok, _, err = git(["init"], cwd=d)
        if not ok:
            print(f"    ✗ git init 失败：{err[:120]}")
            continue
        git(["add", "-A"], cwd=d)
        ok, _, err = git(["commit", "-m", "初始提交：LaTeX 笔记源码"], cwd=d)
        if not ok and "nothing to commit" not in (err + "").lower():
            print(f"    ⚠ 首次提交未完成：{err.splitlines()[0][:100] if err else '未知'}")
        else:
            print("    ✓ 已建立本地仓库并首次提交")

        if gh_ok:
            ok, out, err = run(["gh", "repo", "create", d.name, "--public",
                                "--source", ".", "--remote", "origin", "--push"],
                               cwd=d, timeout=180)
            if ok:
                print(f"    ✓ 已在 GitHub 创建 {acct}/{d.name} 并推送")
            else:
                print(f"    ⚠ 自动创建失败：{(err or out).splitlines()[0][:100] if (err or out) else '未知'}")
                print(f"      可在 {d} 下手动执行：")
                print(f"        git remote add origin git@github.com:{acct}/{d.name}.git")
                print("        git push -u origin master")
        else:
            print("    下一步（在 GitHub 网页新建同名空仓库后执行）：")
            print(f"        cd \"{d}\"")
            print(f"        git remote add origin git@github.com:{acct}/{d.name}.git")
            print("        git push -u origin master")


# ---------------------------------------------------------------- 主循环


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cfg = load_conf()
    while True:
        root = cfg.get("root", "")
        ds = subdirs(root) if root else []
        rs = [d for d in ds if (d / ".git").is_dir()] if ds else []
        clear()
        print(PANEL.format(root=root or "（未设置，请选 1）",
                           n_repo=len(rs), n_dir=len(ds),
                           account=cfg.get("account") or "（未设置）"))
        sel = input("  请输入选项：").strip()
        if not sel:
            continue
        choices = [s.strip() for s in sel.replace("，", ",").split(",")]
        if "0" in choices:
            print("  已退出。")
            return 0

        for c in choices:
            if c == "1":
                clear()
                cfg = set_root(cfg)
                pause()
            elif c == "2":
                clear()
                show_status(cfg)
                pause()
            elif c == "3":
                clear()
                commit_push_all(cfg)
                pause()
            elif c == "4":
                clear()
                create_repo(cfg)
                pause()

if __name__ == "__main__":
    sys.exit(main())
