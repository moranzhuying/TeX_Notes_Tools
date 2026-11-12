#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_notes.py — 笔记目录监测与滚动 git 历史压缩

对指定的笔记仓库目录做两件事：

1. 定时检测目录改动，有变化就提交并推送；
2. 按另一个间隔删除该目录**最早一条** git 记录（内容保留，历史重写），
   让历史长度滚动收敛，而不是无限增长。

不带参数运行就是交互面板：列出工作区 ``LaTeX_Notes`` 下的仓库，选一个、
设好两个间隔后启动。状态与日志写在工具目录下的 ``_state/`` 与 ``_logs/``。

    python watch_notes.py                        # 交互面板
    python watch_notes.py --list                 # 只列可监测仓库
    python watch_notes.py --dir Algebra          # 直接监测（相对 LaTeX_Notes）
    python watch_notes.py --dir Algebra --once   # 只跑一轮后退出
    python watch_notes.py --dir Algebra --fresh  # 丢弃上次状态，重新开始

``--dir`` 也可以给绝对路径。中断（Ctrl+C）后再次启动默认沿用上次状态；
加 ``--fresh`` 则清空状态从头开始。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
TOOLS_ROOT = TOOL_DIR.parent
WORKSPACE = TOOLS_ROOT.parent
NOTES_ROOT = WORKSPACE / "LaTeX_Notes"

STATE_DIR = TOOL_DIR / "_state"
LOG_DIR = TOOL_DIR / "_logs"

DEFAULT_INTERVAL = 300      # 检测间隔（秒）
DEFAULT_PRUNE_INTERVAL = 900  # 删历史间隔（秒）
GIT_TIMEOUT = 60

_GIT_CANDIDATES = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def utf8_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def sanitize(text, limit=600):
    if not text:
        return ""
    text = re.sub(r"//[^/@\s]*@", "//***@", text)
    text = text.replace("\\", "/")
    return text[:limit]


def resolve_git():
    for p in _GIT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return shutil.which("git") or "git"


GIT_EXE = resolve_git()


def log(log_path, msg, level="INFO"):
    line = "[{}][{}][{}] {}".format(
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        os.getpid(), level, msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    if log_path:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8", errors="replace",
                      newline="") as f:
                f.write(line + "\n")
        except Exception:
            pass


def git(repo, *args, timeout=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = (
        "ssh -o BatchMode=yes -o ConnectTimeout=15 "
        "-o ServerAliveInterval=10 -o ServerAliveCountMax=2")
    py_dir = os.path.dirname(sys.executable)
    if py_dir:
        env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [GIT_EXE] + list(args)
    try:
        return subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT if timeout is None else timeout,
            env=env, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1, stdout="", stderr=str(exc))


def current_branch(repo):
    r = git(repo, "symbolic-ref", "--short", "HEAD")
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def verify_repo(repo):
    """返回 (状态, 描述)：0 通过，1 配置不符，2 瞬时故障。"""
    if not os.path.isdir(str(repo)):
        return 1, "目录不存在"
    r = git(repo, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        if r.returncode == -1:
            return 2, "git 暂时不可用"
        return 1, "不是 git 仓库: " + sanitize(r.stderr)
    top = os.path.normcase(os.path.realpath(r.stdout.strip()))
    want = os.path.normcase(os.path.realpath(str(repo)))
    if top != want:
        return 1, "不是仓库根目录（实际根为 {}）".format(sanitize(top))
    if current_branch(repo) is None:
        return 1, "HEAD 处于游离状态"
    return 0, ""


def status_text(repo):
    r = git(repo, "status", "--porcelain")
    if r.returncode != 0:
        return None
    return r.stdout


def sync(repo, do_push=True):
    """检测并提交目录改动。返回 (changed, ok, msg)。"""
    st = status_text(repo)
    if st is None:
        return False, False, "git status 失败"
    if not st.strip():
        return False, True, "无改动"

    r = git(repo, "add", "-A")
    if r.returncode != 0:
        return True, False, "git add 失败: " + sanitize(r.stderr)

    ns = git(repo, "diff", "--cached", "--name-status")
    if ns.returncode != 0:
        return True, False, "git diff --cached 失败: " + sanitize(ns.stderr)
    if not ns.stdout.strip():
        return False, True, "暂存后无差异（可能为换行符归一化）"

    msg = "自动同步 {} {}".format(
        repo.name, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    r = git(repo, "commit", "-m", msg)
    if r.returncode != 0:
        return True, False, "git commit 失败: " + sanitize(r.stderr)

    if not do_push:
        return True, True, "已提交（未推送）"

    branch = current_branch(repo)
    if not branch:
        return True, False, "无法确定当前分支"
    r = git(repo, "push", "--force-with-lease", "origin", branch)
    if r.returncode != 0:
        return True, False, "git push 失败: " + sanitize(r.stderr)
    return True, True, "已提交并推送"


def prune_oldest(repo, do_push=True):
    """删除最早一条 commit（内容保留）。返回 (ok, msg)。"""
    r = git(repo, "rev-list", "--reverse", "HEAD")
    if r.returncode != 0:
        return False, "无法读取历史: " + sanitize(r.stderr)
    commits = r.stdout.split()
    if len(commits) < 2:
        return True, "历史不足两条，跳过"

    root, second = commits[0], commits[1]

    tree = git(repo, "rev-parse", second + "^{tree}")
    if tree.returncode != 0:
        return False, "读取第二条的树失败: " + sanitize(tree.stderr)
    msg = git(repo, "log", "-1", "--format=%B", second)
    new_root = git(repo, "commit-tree", tree.stdout.strip(),
                   "-m", msg.stdout.rstrip())
    if new_root.returncode != 0 or not new_root.stdout.strip():
        return False, "commit-tree 失败: " + sanitize(new_root.stderr)
    new_root_sha = new_root.stdout.strip()

    branch = current_branch(repo)
    if not branch:
        return False, "无法确定当前分支"

    r = git(repo, "rebase", "--onto", new_root_sha, second, branch)
    if r.returncode != 0:
        git(repo, "rebase", "--abort")
        return False, "rebase 失败（已回滚）: " + sanitize(r.stderr)

    if do_push:
        r = git(repo, "push", "--force-with-lease", "origin", branch)
        if r.returncode != 0:
            return False, "已删本地历史但推送失败: " + sanitize(r.stderr)

        # 彻底清除：让旧 commit 从 reflog 与对象库消失。
        # 仅在推送成功后执行：--no-push 时保留现场，便于回退对比。
        git(repo, "reflog", "expire", "--expire=now", "--all")
        git(repo, "gc", "--prune=now", "--quiet")

    return True, "已删除最早一条 {}（新 root {}）".format(
        root[:8], new_root_sha[:8])


def dir_key(path):
    return hashlib.sha256(
        os.path.normcase(os.path.realpath(str(path))).encode("utf-8")
    ).hexdigest()[:12]


def state_path_for(repo):
    return STATE_DIR / "watch-{}.json".format(dir_key(repo))


def log_path_for(repo):
    return LOG_DIR / "watch-{}.log".format(dir_key(repo))


def load_state(path, fresh):
    if fresh:
        try:
            path.unlink()
        except OSError:
            pass
        return {"cycles": 0, "last_prune_ts": 0.0, "last_commit": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        return {
            "cycles": int(data.get("cycles", 0)),
            "last_prune_ts": float(data.get("last_prune_ts", 0)),
            "last_commit": str(data.get("last_commit", "")),
        }
    except (OSError, ValueError):
        return {"cycles": 0, "last_prune_ts": 0.0, "last_commit": ""}


def save_state(path, state):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(path))
        return True
    except OSError:
        return False


def acquire_lock(repo):
    lock_path = STATE_DIR / "watch-{}.lock".format(dir_key(repo))
    if os.name != "nt":
        return True, None
    try:
        import msvcrt
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "r+") if lock_path.exists() else open(lock_path, "w+")
        if lock_path.stat().st_size == 0:
            fh.write("0")
            fh.flush()
            fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True, fh
    except OSError:
        return False, None


def list_repos():
    """列出 LaTeX_Notes 下的 git 仓库。"""
    repos = []
    if NOTES_ROOT.is_dir():
        for p in sorted(NOTES_ROOT.iterdir()):
            if p.is_dir() and (p / ".git").exists():
                repos.append(p)
    return repos


def resolve_repo(arg):
    """--dir 既可为绝对路径，也可为 LaTeX_Notes 下的仓库名。"""
    p = Path(arg)
    if p.is_absolute():
        return p
    candidate = NOTES_ROOT / arg
    if candidate.is_dir():
        return candidate
    return Path(arg).resolve()


def run_loop(repo, interval, prune_interval, fresh, once, no_push, lg):
    sp = state_path_for(repo)
    ok, _lock = acquire_lock(repo)
    if not ok:
        log(lg, "已有实例在监测 {}，退出".format(repo), "ERROR")
        return 0

    state = load_state(sp, fresh)
    cycle = state["cycles"]
    last_prune = state["last_prune_ts"]
    if last_prune <= 0:
        # 首次运行不做历史压缩，等满一个 prune 周期再触发
        last_prune = time.time()

    log(lg, "启动 dir={} interval={}s prune={}s cycles={} fresh={}".format(
        repo, interval, prune_interval, cycle, fresh))

    status, msg = verify_repo(repo)
    if status != 0:
        log(lg, "仓库校验失败: {}（等待重试）".format(msg), "ERROR")

    while True:
        if status == 0:
            try:
                changed, ok_sync, s_msg = sync(repo, not no_push)
                if changed or not ok_sync:
                    log(lg, s_msg, "INFO" if ok_sync else "ERROR")

                now = time.time()
                if now - last_prune >= prune_interval:
                    st = status_text(repo)
                    if st is None:
                        log(lg, "无法读取工作区状态，跳过删历史", "WARN")
                    elif st.strip():
                        log(lg, "工作区仍有未提交改动，跳过删历史", "WARN")
                    else:
                        ok_prune, p_msg = prune_oldest(repo, not no_push)
                        log(lg, p_msg, "INFO" if ok_prune else "ERROR")
                        if ok_prune:
                            last_prune = now

                r = git(repo, "rev-parse", "--short", "HEAD")
                state["last_commit"] = r.stdout.strip() if r.returncode == 0 else ""
                cycle += 1
                state["cycles"] = cycle
                state["last_prune_ts"] = last_prune
                save_state(sp, state)
            except Exception:
                log(lg, "本轮异常:\n{}".format(traceback.format_exc()), "ERROR")
        else:
            status, msg = verify_repo(repo)
            if status != 0:
                log(lg, "仓库仍不可用: {}".format(msg), "WARN")

        if once:
            break
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log(lg, "收到中断，状态已保存（cycles={}）".format(cycle))
            break

    log(lg, "进程退出 cycles={} last_commit={}".format(
        cycle, state.get("last_commit", "")))
    return 0


def interactive():
    """交互面板：选仓库、设间隔、启动。"""
    repos = list_repos()
    if not repos:
        print("  LaTeX_Notes 下未找到 git 仓库：{}".format(NOTES_ROOT))
        return 1

    print("=" * 60)
    print("  笔记目录监测（自动提交 / 滚动删历史）")
    print("=" * 60)
    print("  笔记根：{}".format(NOTES_ROOT))
    print("-" * 60)
    for i, p in enumerate(repos, 1):
        print("  {:>2}. {}".format(i, p.name))
    print("   0. 退出")
    print("-" * 60)

    try:
        sel = input("\n  选择: ").strip()
    except (EOFError, KeyboardInterrupt):
        return 0
    if not sel or sel == "0":
        return 0
    try:
        repo = repos[int(sel) - 1]
    except (ValueError, IndexError):
        print("  无效选择")
        return 1

    def ask_int(prompt, default):
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if not raw:
            return default
        try:
            v = int(raw)
            return v if v > 0 else default
        except ValueError:
            return default

    interval = ask_int(
        "  检测间隔（秒，默认 {}）: ".format(DEFAULT_INTERVAL), DEFAULT_INTERVAL)
    prune = ask_int(
        "  删历史间隔（秒，默认 {}）: ".format(DEFAULT_PRUNE_INTERVAL),
        DEFAULT_PRUNE_INTERVAL)

    try:
        fresh_raw = input("  从头开始（丢弃上次状态）？(y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        fresh_raw = ""
    fresh = fresh_raw in ("y", "yes")

    print("\n  开始监测 {}（Ctrl+C 停止）\n".format(repo.name))
    return run_loop(repo, interval, prune, fresh, False, False,
                    log_path_for(repo))


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="笔记目录监测 + 滚动 git 历史压缩",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", help="监测目录（绝对路径或 LaTeX_Notes 下仓库名）")
    p.add_argument("--list", action="store_true", help="列出可监测仓库后退出")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                   help="检测间隔秒数（默认 %(default)s）")
    p.add_argument("--prune-interval", type=int, default=DEFAULT_PRUNE_INTERVAL,
                   help="删历史间隔秒数（默认 %(default)s）")
    p.add_argument("--fresh", action="store_true",
                   help="忽略上次状态，重新开始")
    p.add_argument("--once", action="store_true", help="只跑一轮后退出")
    p.add_argument("--no-push", action="store_true", help="只提交不推送")
    return p.parse_args(argv)


def main(argv=None):
    utf8_streams()
    args = parse_args(argv)

    if args.list:
        repos = list_repos()
        if not repos:
            print("LaTeX_Notes 下未找到 git 仓库：{}".format(NOTES_ROOT))
            return 1
        for p in repos:
            print(p.name)
        return 0

    if not args.dir:
        return interactive()

    repo = resolve_repo(args.dir)
    return run_loop(repo, args.interval, args.prune_interval,
                    args.fresh, args.once, args.no_push,
                    log_path_for(repo))


if __name__ == "__main__":
    try:
        code = main() or 0
    except KeyboardInterrupt:
        code = 0
    except BaseException:
        # SystemExit 不在此列（它不会被 Exception 捕获，也不会走到这里，
        # 因为 sys.exit 已移出 try）；这里只兜真正的异常
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / "watch-fatal.log", "a", encoding="utf-8",
                      errors="replace", newline="") as f:
                f.write("[{}] FATAL\n{}\n".format(
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    traceback.format_exc()))
        except Exception:
            pass
        raise
    sys.exit(code)
