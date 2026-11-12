#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_notes.py — 笔记目录监测与滚动 git 历史压缩

对指定的笔记仓库目录做两件事：

1. 定时检测目录改动，有变化就提交并推送；
2. 按另一个间隔把历史**裁剪到固定条数**（内容与提交信息保留，历史重写），
   让历史长度收敛而不是无限增长。

为什么不是「每次删掉最早一条」：提交也在按检测间隔不断产生，一次只删一条时
净增长永远为正，历史只会变慢地涨下去。按上限裁剪（``--keep``，默认 20）才收敛。

不带参数运行就是交互面板：列出工作区 ``LaTeX_Notes`` 下的仓库，选一个、
设好间隔与保留条数后启动。状态与日志写在工具目录下的 ``_state/`` 与 ``_logs/``。

    python watch_notes.py                        # 交互面板
    python watch_notes.py --list                 # 只列可监测仓库
    python watch_notes.py --dir Algebra          # 直接监测（相对 LaTeX_Notes）
    python watch_notes.py --dir Algebra --once   # 只跑一轮后退出
    python watch_notes.py --dir Algebra --fresh  # 丢弃上次状态，重新开始
    python watch_notes.py --dir Algebra --keep 5 # 历史只留最新 5 条

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

TOOL_DIR = Path(__file__).resolve().parent        # <Tools>/src/watch_notes/
TOOLS_ROOT = TOOL_DIR.parent.parent               # <Tools>/
WORKSPACE = TOOLS_ROOT.parent                     # 工作区根
NOTES_ROOT = WORKSPACE / "LaTeX_Notes"

STATE_DIR = TOOL_DIR / "_state"
LOG_DIR = TOOL_DIR / "_logs"

DEFAULT_INTERVAL = 300      # 检测间隔（秒）
DEFAULT_PRUNE_INTERVAL = 900  # 裁剪检查间隔（秒）
DEFAULT_KEEP = 20           # 历史保留条数上限
MIN_INTERVAL = 10           # 下限：再小就是空转，每次都跑 git 只会把 CPU 打满
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


def git(repo, *args, timeout=None, extra_env=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = (
        "ssh -o BatchMode=yes -o ConnectTimeout=15 "
        "-o ServerAliveInterval=10 -o ServerAliveCountMax=2")
    py_dir = os.path.dirname(sys.executable)
    if py_dir:
        env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
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


def prune_to(repo, keep, do_push=True):
    """把历史裁剪到最新 keep 条（内容与提交信息保留）。返回 (ok, msg)。

    为什么不是「删掉最早一条」：每轮检测都在产生新提交，一次只删一条时
    净增长永远为正，历史只会变慢地涨下去。按上限裁剪才真的收敛。

    用 commit-tree 逐条重建，不碰 rebase：新 root 之后的每条提交沿用原来的
    树、消息、作者与时间，只断掉最早的父链。
    """
    r = git(repo, "rev-list", "--reverse", "HEAD")
    if r.returncode != 0:
        return False, "无法读取历史: " + sanitize(r.stderr)
    commits = r.stdout.split()
    total = len(commits)
    if total <= keep:
        return True, "历史 {} 条，未超过上限 {}".format(total, keep)

    kept = commits[-keep:]
    parent = None
    rebuilt = None
    for sha in kept:
        tree = git(repo, "rev-parse", sha + "^{tree}")
        meta = git(repo, "log", "-1", "--date=raw",
                   "--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd", sha)
        msg = git(repo, "log", "-1", "--format=%B", sha)
        if tree.returncode != 0 or meta.returncode != 0 or msg.returncode != 0:
            return False, "读取提交失败: " + sha[:8]
        fields = meta.stdout.rstrip("\n").split("\x00")
        if len(fields) < 6:
            return False, "提交信息格式异常: " + sha[:8]
        env = {
            "GIT_AUTHOR_NAME": fields[0], "GIT_AUTHOR_EMAIL": fields[1],
            "GIT_AUTHOR_DATE": fields[2], "GIT_COMMITTER_NAME": fields[3],
            "GIT_COMMITTER_EMAIL": fields[4], "GIT_COMMITTER_DATE": fields[5],
        }
        args = ["commit-tree", tree.stdout.strip()]
        if parent:
            args += ["-p", parent]
        new = git(repo, *args, "-m", msg.stdout.rstrip("\n"), extra_env=env)
        if new.returncode != 0 or not new.stdout.strip():
            return False, "commit-tree 失败: " + sanitize(new.stderr)
        rebuilt = new.stdout.strip()
        parent = rebuilt

    branch = current_branch(repo)
    if not branch:
        return False, "无法确定当前分支"
    old_head = commits[-1]
    # CAS：旧 head 在这期间被改动就放弃，避免覆盖别人的提交
    r = git(repo, "update-ref", "refs/heads/" + branch, rebuilt, old_head)
    if r.returncode != 0:
        return False, "更新分支失败: " + sanitize(r.stderr)
    # 树没变，reset 只是让 HEAD/index 跟上新指针（调用方已确认工作区干净）
    r = git(repo, "reset", "--hard", rebuilt)
    if r.returncode != 0:
        return False, "同步工作区失败: " + sanitize(r.stderr)

    if do_push:
        r = git(repo, "push", "--force-with-lease", "origin", branch)
        if r.returncode != 0:
            return False, "已裁剪本地历史但推送失败: " + sanitize(r.stderr)
        # 彻底清除：让旧 commit 从 reflog 与对象库消失。
        # 仅在推送成功后执行：--no-push 时保留现场，便于回退对比。
        git(repo, "reflog", "expire", "--expire=now", "--all")
        git(repo, "gc", "--prune=now", "--quiet")

    return True, "已裁剪历史 {} → {} 条（新 head {}）".format(
        total, keep, rebuilt[:8])


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


def run_loop(repo, interval, prune_interval, keep, fresh, once, no_push, lg):
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

    log(lg, "启动 dir={} interval={}s prune={}s keep={} cycles={} fresh={}".format(
        repo, interval, prune_interval, keep, cycle, fresh))

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
                        log(lg, "无法读取工作区状态，跳过裁剪", "WARN")
                    elif st.strip():
                        log(lg, "工作区仍有未提交改动，跳过裁剪", "WARN")
                    else:
                        ok_prune, p_msg = prune_to(repo, keep, not no_push)
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
    print("  笔记目录监测（自动提交 / 历史裁剪）")
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
    if not sel.isdigit() or not (1 <= int(sel) <= len(repos)):
        print("  无效选择")
        return 1
    repo = repos[int(sel) - 1]

    def ask_int(prompt, default, floor=MIN_INTERVAL):
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return default
        if not raw:
            return default
        try:
            v = int(raw)
            return max(floor, v) if v > 0 else default
        except ValueError:
            return default

    interval = ask_int(
        "  检测间隔（秒，默认 {}）: ".format(DEFAULT_INTERVAL), DEFAULT_INTERVAL)
    prune = ask_int(
        "  裁剪检查间隔（秒，默认 {}）: ".format(DEFAULT_PRUNE_INTERVAL),
        DEFAULT_PRUNE_INTERVAL)
    keep = ask_int(
        "  历史保留条数（默认 {}）: ".format(DEFAULT_KEEP), DEFAULT_KEEP,
        floor=1)

    try:
        fresh_raw = input("  从头开始（丢弃上次状态）？(y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        fresh_raw = ""
    fresh = fresh_raw in ("y", "yes")

    print("\n  开始监测 {}（Ctrl+C 停止）\n".format(repo.name))
    return run_loop(repo, interval, prune, keep, fresh, False, False,
                    log_path_for(repo))


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="笔记目录监测 + 滚动 git 历史压缩",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", help="监测目录（绝对路径或 LaTeX_Notes 下仓库名）")
    p.add_argument("--list", action="store_true", help="列出可监测仓库后退出")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                   help="检测间隔秒数（默认 %(default)s，最少 {}）".format(MIN_INTERVAL))
    p.add_argument("--prune-interval", type=int, default=DEFAULT_PRUNE_INTERVAL,
                   help="裁剪检查间隔秒数（默认 %(default)s，最少 {}）".format(MIN_INTERVAL))
    p.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                   help="历史保留条数（默认 %(default)s，最少 1）")
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
    interval = max(MIN_INTERVAL, args.interval)
    prune = max(MIN_INTERVAL, args.prune_interval)
    keep = max(1, args.keep)
    if (interval, prune) != (args.interval, args.prune_interval):
        print("  间隔过小，已按 {} 秒起算（再小就是空转）".format(MIN_INTERVAL))
    return run_loop(repo, interval, prune, keep,
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
