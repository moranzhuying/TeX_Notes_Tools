#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_sensitive.py — 提交/推送前的本机信息把关

目的：让「别把本机信息推到公开仓库」从「靠记性」变成「靠机制」。

用法：
    python check_sensitive.py                # 扫暂存区（pre-commit 钩子用）
    python check_sensitive.py --tracked      # 全量体检：扫所有已跟踪文件
    python check_sensitive.py --dir <路径>   # 扫指定目录（非 git 目录也可用）

退出码：0 = 干净；1 = 命中（用作 git 钩子时会中止提交）。

词表：从脚本所在目录逐级向上（最多 4 级）合并沿途所有 .sensitive-words.txt。
      词表文件本身不入版本控制。
"""
import os
import re
import subprocess
import sys
import pathlib

# 内置模式：只放「任何机器上都算本机特征」的通用形态。
# 具体到本机的词（用户名、目录名等）写进 .sensitive-words.txt，
# 这样本文件自身不会变成新的泄露源。
SENSITIVE_PATTERNS = (
    (r"[A-Za-z]:\\+Users\\+[^\\\s\"'）)，。]+", "Windows 用户目录路径"),
    (r"/(?:Users|home)/[A-Za-z0-9._-]{2,}", "Unix 用户目录路径"),
)

BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
              ".exe", ".dll", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".svgz",
              ".synctex", ".pyc"}

SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "node_modules"}
MAX_UP = 4


def sh(args):
    r = subprocess.run(["git"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0, r.stdout, r.stderr


def repo_root():
    ok, out, _ = sh(["rev-parse", "--show-toplevel"])
    return out.strip() if ok and out.strip() else None


def load_words(start=None):
    """逐级向上收集 .sensitive-words.txt（最多 4 级），返回词列表。"""
    words, seen = [], set()
    d = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    for _ in range(MAX_UP):
        f = os.path.join(d, ".sensitive-words.txt")
        if os.path.isfile(f):
            try:
                with open(f, encoding="utf-8", errors="ignore") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if ln and not ln.startswith("#") and ln not in seen:
                            seen.add(ln)
                            words.append(ln)
            except OSError:
                pass
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return words


def match_line(text, words):
    for pat, label in SENSITIVE_PATTERNS:
        m = re.search(pat, text)
        if m:
            return f"{label}：{m.group(0)}"
    for w in words:
        if w in text:
            return f"专有词「{w}」"
    return None


def scan_staged(words):
    """只扫暂存区的**新增行**。

    被删除的内容不会造成泄露，因此「清理本机信息」这类提交不会被误拦。
    """
    ok, out, _ = sh(["diff", "--cached", "--unified=0"])
    if not ok or not out:
        return []
    hits, cur = [], ""
    for ln in out.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
            continue
        if not ln.startswith("+") or ln.startswith("+++"):
            continue
        text = ln[1:]
        why = match_line(text, words)
        if why:
            hits.append((cur, why, text.strip()))
    return hits


def scan_file(path, label, words):
    hits = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for i, ln in enumerate(fh, 1):
                why = match_line(ln, words)
                if why:
                    hits.append((f"{label}:{i}", why, ln.strip()))
    except OSError:
        pass
    return hits


def scan_tracked(words):
    """全量体检：扫描当前所有已跟踪文件。"""
    root = repo_root()
    ok, out, _ = sh(["ls-files"])
    if not ok or not root:
        return []
    hits = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel or pathlib.Path(rel).suffix.lower() in BINARY_EXT:
            continue
        hits += scan_file(os.path.join(root, rel), rel, words)
    return hits


def scan_dir(root, words):
    """扫描任意目录（非 git 仓库也可用）。"""
    hits, root_p = [], pathlib.Path(root)
    for p in sorted(root_p.rglob("*")):
        if not p.is_file() or p.suffix.lower() in BINARY_EXT:
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        hits += scan_file(p, str(p.relative_to(root_p)), words)
    return hits


def report(hits, scope):
    if not hits:
        print(f"[通过] {scope}：未发现本机信息。")
        return 0
    print(f"[拦截] {scope}：发现 {len(hits)} 处疑似本机信息\n")
    for where, why, text in hits[:60]:
        print(f"  {where}")
        print(f"      {why}")
        print(f"      {text[:120]}")
    if len(hits) > 60:
        print(f"  …（其余 {len(hits) - 60} 处已省略）")
    print("\n处理建议：")
    print("  · 本机路径改写为 %APPDATA% / %USERPROFILE% 等环境变量形式，或用脚本同目录相对解析")
    print("  · 配置类文件（*.conf）应移入 .gitignore，不入库")
    print("  · 确认无误时，单次提交可用 git commit --no-verify 跳过本检查")
    return 1


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    start = os.path.dirname(os.path.abspath(__file__))
    words = load_words(start)

    if "--dir" in argv:
        i = argv.index("--dir")
        target = argv[i + 1] if i + 1 < len(argv) else "."
        return report(scan_dir(target, words), f"目录 {target}")

    if not repo_root():
        print("[提示] 当前不在 git 仓库内；可用 --dir <路径> 扫描普通目录。")
        return 0

    if "--tracked" in argv:
        return report(scan_tracked(words), "全部已跟踪文件")
    return report(scan_staged(words), "暂存区新增内容")


if __name__ == "__main__":
    sys.exit(main())
