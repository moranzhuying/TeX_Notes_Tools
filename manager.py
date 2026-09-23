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
DEFAULT_MSG = "更新笔记"

PANEL = """==============================================================
  笔记工作区管理面板
==============================================================
  笔记根目录：{root}
  已识别仓库：{n_repo} 个 / 子文件夹 {n_dir} 个
  远程账户　：{account}
--------------------------------------------------------------
  1. 检测环境（git 安装 / 用户配置 / SSH 密钥 / 远程连通性）
  2. 配置 Git 账户（用户名、邮箱）
  3. 配置 SSH（生成密钥 / 写 config / 测试连通 / 显示公钥）
  4. 设置笔记根目录（扫描子文件夹，识别仓库）
  5. 显示各仓库状态（远程 / 分支 / 改动数 / 领先落后）
  6. 批量提交并推送（对所有有改动的仓库）
  7. 为未入版本控制的文件夹创建仓库并首次推送
  8. 退出
--------------------------------------------------------------
  9. 符号库管理（进入 symbols.py 的面板）
 10. 笔记工具（选一本笔记 → 提交 / 切换习题模式）
 11. 写作进度追踪表（启动本地服务，用浏览器查看写作进度）
--------------------------------------------------------------
  可多选，用英文逗号分隔（如 1,3,5）
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

SSH_CONFIG_BLOCK = """Host github.com
    HostName ssh.github.com
    Port 443
    User git
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


# ---------------------------------------------------------------- 功能


def check_env(cfg):
    print("【一】环境检测\n")
    ok, out, _ = run(["git", "--version"])
    print(f"  Git 安装　　　：{out if ok else '✗ 未安装或不在 PATH 中'}")

    if ok:
        _, name, _ = git(["config", "--global", "user.name"])
        _, mail, _ = git(["config", "--global", "user.email"])
        print(f"  用户名　　　　：{name or '✗ 未配置'}")
        print(f"  邮箱　　　　　：{mail or '✗ 未配置'}")
        if not name or not mail:
            print("     ↓ 可用面板选项 2 配置")

    ssh_dir = Path.home() / ".ssh"
    keys = sorted(p.name for p in ssh_dir.glob("*.pub")) if ssh_dir.is_dir() else []
    print(f"  SSH 公钥　　　：{', '.join(keys) if keys else '✗ 未找到'}")

    cfg_file = ssh_dir / "config"
    has_cfg = cfg_file.is_file() and "ssh.github.com" in cfg_file.read_text(
        encoding="utf-8", errors="replace")
    print(f"  SSH 配置　　　：{'已指向 ssh.github.com:443 ✓' if has_cfg else '✗ 未配置 443 端口'}")
    if not has_cfg:
        print("     ↓ 可用面板选项 3 配置")

    print("\n  连通性测试（可能需要几秒）…")
    ok, out, err = run(["ssh", "-T", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=accept-new",
                        "git@github.com"], timeout=30)
    msg = (out + " " + err).strip()
    if "successfully authenticated" in msg.lower():
        print("  GitHub 连接　　：✓ 认证成功")
        m = re.search(r"Hi\s+([^!\s]+)", msg)
        if m:
            print(f"  远程账户　　　：{m.group(1)}")
    else:
        print("  GitHub 连接　　：✗ 失败")
        print(f"      {msg[:200]}")


def config_git(cfg):
    print("【二】配置 Git 账户\n")
    _, name, _ = git(["config", "--global", "user.name"])
    _, mail, _ = git(["config", "--global", "user.email"])
    print(f"  当前用户名：{name or '（空）'}")
    print(f"  当前邮箱　：{mail or '（空）'}\n")

    new_name = input("新的用户名（回车保持不变）：").strip()
    new_mail = input("新的邮箱（回车保持不变）：").strip()

    if new_name:
        ok, _, err = git(["config", "--global", "user.name", new_name])
        print(f"  用户名已设为 {new_name}" if ok else f"  ✗ 设置失败：{err}")
    if new_mail:
        ok, _, err = git(["config", "--global", "user.email", new_mail])
        print(f"  邮箱已设为 {new_mail}" if ok else f"  ✗ 设置失败：{err}")
    if not new_name and not new_mail:
        print("  未作改动。")


def config_ssh(cfg):
    print("【三】配置 SSH\n")
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)

    key = ssh_dir / "id_ed25519"
    if key.is_file():
        print(f"  密钥已存在：{key.name}")
    else:
        ans = input("  未找到 ed25519 密钥，现在生成？[y/N] ").strip().lower()
        if ans in ("y", "yes"):
            ok, out, err = run(["ssh-keygen", "-t", "ed25519", "-N", "",
                                "-C", cfg.get("account") or "note", "-f", str(key)])
            print("  ✓ 已生成密钥" if ok else f"  ✗ 生成失败：{err}")
        else:
            print("  跳过密钥生成。")

    cfg_file = ssh_dir / "config"
    content = cfg_file.read_text(encoding="utf-8", errors="replace") if cfg_file.is_file() else ""
    if "ssh.github.com" in content:
        print("  SSH config 已指向 ssh.github.com:443 ✓")
    else:
        ans = input("  为 github.com 配置 443 端口？（国内网络通常需要）[y/N] ").strip().lower()
        if ans in ("y", "yes"):
            with open(cfg_file, "a", encoding="utf-8", newline="") as f:
                f.write(("\n" if content and not content.endswith("\n") else "") + SSH_CONFIG_BLOCK)
            print("  ✓ 已写入 ~/.ssh/config")

    pub = key.with_suffix(".pub")
    if pub.is_file():
        print("\n  公钥内容（复制到 GitHub → Settings → SSH keys）：\n")
        print("  " + "-" * 60)
        for line in pub.read_text(encoding="utf-8").strip().splitlines():
            print(f"  {line}")
        print("  " + "-" * 60)

    ans = input("\n  现在测试连通性？[y/N] ").strip().lower()
    if ans in ("y", "yes"):
        ok, out, err = run(["ssh", "-T", "-o", "BatchMode=yes",
                            "-o", "StrictHostKeyChecking=accept-new",
                            "git@github.com"], timeout=30)
        msg = (out + " " + err).strip()
        print("  ✓ 认证成功：" + msg.splitlines()[0] if "successfully authenticated" in msg.lower()
              else "  ✗ 失败：" + msg[:200])


def set_root(cfg):
    print("【四】设置笔记根目录\n")
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
    root = cfg.get("root")
    print("【五】各仓库状态\n")
    if not root or not Path(root).is_dir():
        print("  ✗ 尚未设置有效的笔记根目录（请先用选项 4）。")
        return
    ds = subdirs(root)
    rs = [d for d in ds if (d / ".git").is_dir()]
    if not rs:
        print("  未找到 git 仓库。")
        return

    print(f"  {'文件夹':<36} {'分支':<8} {'改动':>4} {'领先/落后':>10}  远程")
    print("  " + "-" * 88)
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
        print(f"  {d.name:<36} {br or '-':<8} {n:>4} {track:>9}  {repo} {mark}")

    skip = set(cfg.get("ignore", "").replace("，", ",").split(","))
    skip.discard("")
    no_repo = [d for d in ds
               if not (d / ".git").is_dir()
               and d.name not in skip
               and "rchieved" not in d.name]
    if no_repo:
        print(f"\n  未入版本控制的子文件夹（{len(no_repo)} 个）：")
        for d in no_repo:
            print(f"    {d.name}")
        print("    ↓ 可用面板选项 7 为其创建仓库")


def pick_repos(cfg, skip_clean=False):
    """让用户选择要操作的仓库；返回选中的目录列表。"""
    root = cfg.get("root")
    rs = [d for d in subdirs(root) if (d / ".git").is_dir()] if root else []
    if skip_clean:
        rs = [d for d in rs if git(["status", "--porcelain"], cwd=d)[1]]
    if not rs:
        print("  没有符合条件的仓库。")
        return []
    print("  可操作的仓库：")
    for i, d in enumerate(rs, 1):
        n = len(git(["status", "--porcelain"], cwd=d)[1].splitlines())
        print(f"    {i:>2}. {d.name:<38} {n} 项改动")
    print("\n  输入编号（英文逗号分隔，回车＝全选，0＝取消）：")
    sel = input("  > ").strip()
    if sel == "0":
        return []
    if not sel:
        return rs
    out = []
    for s in sel.replace("，", ",").split(","):
        s = s.strip()
        if s.isdigit() and 1 <= int(s) <= len(rs):
            out.append(rs[int(s) - 1])
    return out


def commit_push_all(cfg):
    print("【六】批量提交并推送\n")
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
    print("【七】为未入版本控制的文件夹创建仓库\n")
    root = cfg.get("root")
    if not root or not Path(root).is_dir():
        print("  ✗ 尚未设置有效的笔记根目录（请先用选项 4）。")
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


# ---------------------------------------------------------------- 子工具入口


def open_symbols():
    """进入 symbols.py 的面板（退出后返回本面板）。"""
    print("【九】符号库管理\n")
    sp = Path(__file__).with_name("symbols.py")
    if not sp.is_file():
        print(f"  ✗ 未找到 symbols.py（应与本脚本同目录：{Path(__file__).parent}）")
        return
    print("  即将进入符号库管理面板，退出后将返回本面板。\n")
    try:
        subprocess.run([sys.executable, str(sp)])
    except KeyboardInterrupt:
        print("\n  已返回。")


def open_progress():
    """启动「写作进度追踪表」本地服务（后台运行，不阻塞本面板）。"""
    print("【十一】写作进度追踪表\n")
    pp = Path(__file__).with_name("progress.py")
    if not pp.is_file():
        print(f"  ✗ 未找到 progress.py（应与本脚本同目录：{Path(__file__).parent}）")
        return
    print("  正在启动本地服务，稍后会自动打开浏览器。")
    print("  服务在后台运行；结束时请用页面右上角的「退出」按钮。\n")
    try:
        subprocess.Popen([sys.executable, str(pp)], cwd=str(pp.parent))
    except OSError as e:
        print(f"  ✗ 启动失败：{e}")
        return
    print("  已发出启动指令。若浏览器未自动打开，请访问 http://127.0.0.1:8765/")


def note_tools(cfg):
    """选一本笔记，对其实施提交或切换习题编排模式。"""
    print("【十】笔记工具\n")
    root = cfg.get("root")
    if not root or not Path(root).is_dir():
        print("  ✗ 尚未设置有效的笔记根目录（请先用选项 4）。")
        return
    rs = [d for d in subdirs(root) if (d / ".git").is_dir()]
    if not rs:
        print("  未找到 git 仓库。")
        return

    print("  选择笔记：")
    for i, d in enumerate(rs, 1):
        n = len(git(["status", "--porcelain"], cwd=d)[1].splitlines())
        print(f"    {i:>2}. {d.name:<38} {n} 项改动")
    print("\n  输入编号（0＝取消）：")
    sel = input("  > ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(rs)):
        return
    note = rs[int(sel) - 1]

    print(f"\n  对「{note.name}」的操作：")
    print("    1. 提交并推送（调用 commit.py）")
    print("    2. 切换习题编排模式（调用 setup_mode.py）")
    print("    0. 取消")
    op = input("  > ").strip()

    py = sys.executable
    try:
        if op == "1":
            cp = note / "commit.py"
            if not cp.is_file():
                print(f"  ✗ {note.name} 下没有 commit.py")
                return
            msg = input("  提交说明（回车＝「更新笔记」）：").strip()
            cmd = [py, "commit.py"] + ([msg] if msg else [])
            print()
            subprocess.run(cmd, cwd=note)
        elif op == "2":
            sp = note / "setup_mode.py"
            if not sp.is_file():
                print(f"  ✗ {note.name} 下没有 setup_mode.py")
                return
            print()
            subprocess.run([py, "setup_mode.py"], cwd=note)
        else:
            print("  已取消。")
    except KeyboardInterrupt:
        print("\n  已中断。")


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
        print(PANEL.format(root=root or "（未设置，请选 4）",
                           n_repo=len(rs), n_dir=len(ds),
                           account=cfg.get("account") or "（未设置）"))
        sel = input("  请输入选项：").strip()
        if not sel:
            continue
        choices = [s.strip() for s in sel.replace("，", ",").split(",")]
        if "8" in choices:
            print("  已退出。")
            return 0

        for c in choices:
            if c == "1":
                clear()
                check_env(cfg)
                pause()
            elif c == "2":
                clear()
                config_git(cfg)
                pause()
            elif c == "3":
                clear()
                config_ssh(cfg)
                pause()
            elif c == "4":
                clear()
                cfg = set_root(cfg)
                pause()
            elif c == "5":
                clear()
                show_status(cfg)
                pause()
            elif c == "6":
                clear()
                commit_push_all(cfg)
                pause()
            elif c == "7":
                clear()
                create_repo(cfg)
                pause()
            elif c == "9":
                clear()
                open_symbols()
                pause()
            elif c == "10":
                clear()
                note_tools(cfg)
                pause()
            elif c == "11":
                clear()
                open_progress()
                pause()


if __name__ == "__main__":
    sys.exit(main())
