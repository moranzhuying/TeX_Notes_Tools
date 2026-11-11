#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_setup.py — Git 基本信息设置

从 manager.py 剥离出来的「新环境准备」部分：检测环境、配置全局账户、配置 SSH。
这三项只在**首次配置**时用一次，而仓库管理是日常操作，所以分开：
放在一起会让日常工作区的面板长期挂着几条几乎不用的选项。

三者都操作**全局**配置（`git config --global`、`~/.ssh/`），与具体笔记区无关。

用法：
    python git_setup.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

# 账户名从 manager 的配置里取（仅用于生成密钥时的注释），取不到就用默认值
MANAGER_CONF = Path(__file__).resolve().parent.parent / "manager" / "manager.conf"

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
    """清屏，使画面只保留当前选项的内容（与其它工具保持一致）。"""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def pause():
    print()
    try:
        input("按回车返回面板…")
    except EOFError:
        pass


def load_account():
    """从 manager.conf 读账户名（用作密钥注释），读不到返回空串。"""
    if not MANAGER_CONF.is_file():
        return ""
    for line in MANAGER_CONF.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "account":
            return v.strip()
    return ""


# ---------------------------------------------------------------- 功能

def check_env():
    print("【一】环境检测\n")
    ok, out, _ = run(["git", "--version"])
    print(f"  Git 安装　　　：{out if ok else '✗ 未安装或不在 PATH 中'}")

    if ok:
        _, name, _ = git(["config", "--global", "user.name"])
        _, mail, _ = git(["config", "--global", "user.email"])
        print(f"  用户名　　　　：{name or '✗ 未配置'}")
        print(f"  邮箱　　　　　：{mail or '✗ 未配置'}")
        if not name or not mail:
            print("     ↓ 可用本面板选项 2 配置")

    ssh_dir = Path.home() / ".ssh"
    keys = sorted(p.name for p in ssh_dir.glob("*.pub")) if ssh_dir.is_dir() else []
    print(f"  SSH 公钥　　　：{', '.join(keys) if keys else '✗ 未找到'}")

    cfg_file = ssh_dir / "config"
    has_cfg = cfg_file.is_file() and "ssh.github.com" in cfg_file.read_text(
        encoding="utf-8", errors="replace")
    print(f"  SSH 配置　　　：{'已指向 ssh.github.com:443 ✓' if has_cfg else '✗ 未配置 443 端口'}")
    if not has_cfg:
        print("     ↓ 可用本面板选项 3 配置")

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


def config_git():
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


def config_ssh():
    print("【三】配置 SSH\n")
    account = load_account()
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)

    key = ssh_dir / "id_ed25519"
    if key.is_file():
        print(f"  密钥已存在：{key.name}")
    else:
        ans = input("  未找到 ed25519 密钥，现在生成？[y/N] ").strip().lower()
        if ans in ("y", "yes"):
            ok, out, err = run(["ssh-keygen", "-t", "ed25519", "-N", "",
                                "-C", account or "note", "-f", str(key)])
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


# ---------------------------------------------------------------- 面板

def show_menu():
    print("=" * 62)
    print("  Git 基本信息设置")
    print("=" * 62)
    print("  1. 检测环境（git 安装 / 用户配置 / SSH 密钥 / 远程连通性）")
    print("  2. 配置 Git 账户（用户名、邮箱）")
    print("  3. 配置 SSH（生成密钥 / 写 config / 显示公钥 / 测试连通）")
    print("-" * 62)
    print("  0. 退出")
    print("=" * 62)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    actions = {"1": check_env, "2": config_git, "3": config_ssh}

    while True:
        clear()
        show_menu()
        try:
            c = input("\n  可多选，用英文逗号分隔（如 1,3）：").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not c or c == "0":
            break

        for part in re.split(r"[,，\s]+", c):
            if part in actions:
                clear()
                actions[part]()
                pause()

    clear()
    print("  已退出 Git 基本信息设置。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
