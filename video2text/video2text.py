#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video2text.py — 视频转文字（带时间戳纯文本）

把没有字幕的讲座视频（B站 / YouTube）转成带时间戳的纯文本，供大模型整理成
LaTeX 笔记。策略是**两段式**：

  1. 先探测该视频有没有字幕（B站 的 AI 字幕语言码是 `ai-zh`）
  2. **有字幕** → 直接下字幕转文本（秒级完成）
     **无字幕** → 默认停止该集；显式允许后才下音频 → 分块可恢复 faster-whisper 转写

> 有字幕时 1.9 秒，跑 whisper 要约 85 分钟（170 分钟视频）—— **差约 2700 倍**。
> 所以「先探测」是第一原则，不要习惯性直接开转写。

B站 字幕需要登录才可见，本工具用专用 profile 扫码登录一次后长期复用
（不借用日常浏览器的登录态，原因见 video2text.md）。所以**本工具不用 ffmpeg**：
字幕是文本不需要转码；音频走 `yt-dlp -f ba` 直接拿流，不转码。

**不带参数运行就是交互面板**（从总面板进来就是这条路）：粘贴链接即可转写，
另有批量转写、已转写列表、重新登录、环境状态。

    python video2text.py                          # 交互面板
    python video2text.py <URL>                    # 直接转写
    python video2text.py <URL> --force-whisper    # 忽略字幕，强制走 whisper
    python video2text.py <URL> --model large-v3   # 换更大的模型
    python video2text.py <URL> -o D:/某目录        # 换输出目录
    python video2text.py <URL> --no-cookies       # 匿名探测（不读登录态）

数据都在同级的 `_data/`（模型 / 登录态 / 转写产物），该目录不入版本库。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import hashlib
import tempfile
import urllib.parse
import configparser
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

# 支持直接运行及 importlib 探针加载同级模块。
_MODULE_DIR = str(Path(__file__).resolve().parent)
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

# --- 必须在 import faster_whisper 之前设好镜像与传输协议 ---
# HF_ENDPOINT 只影响传统 HTTP 分发端点；Xet 走独立端点且国内返回 401，
# 必须用 HF_HUB_DISABLE_XET 强制回退，否则会无限重试、零字节落盘。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
CONF = HERE / "video2text.conf"
DATA = HERE / "_data"
MODELS_DIR = DATA / "models"
COOKIES_DIR = DATA / "cookies"
PROFILE_DIR = DATA / "profile"
# 说明：转写产物目录不在此处固定，一律经 data_root(cp) / "transcripts" 取，
# 以便 video2text.conf 的 [paths] data 能整体重定位数据目录。

COOKIE_FILE = COOKIES_DIR / "bilibili_cookies.txt"
STATE_FILE = COOKIES_DIR / "bilibili_state.json"

# 字幕语言优先级：B站 AI 字幕是 ai-zh；其余为常见中文/英文码
LANG_PRIORITY = ["ai-zh", "zh-Hans", "zh-CN", "zh", "ai-en", "en", "en-US"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DEFAULTS = {
    "paths": {
        "python": "",
        "data": "",
    },
    "whisper": {
        "model": "medium",
        "device": "cpu",
        "compute_type": "int8",
        "vad": "true",
        "language": "zh",
        "prompt": "数学 物理 化学 公式 定理 命题 引理 证明 映射 群 环 域 函子 拓扑 线性空间",
    },
    "download": {
        "browser": "edge",
        "mode": "subtitles",
        "subtitle_retries": "2",
        "keep_audio": "true",
    },
}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_conf() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    for sec, kv in DEFAULTS.items():
        cp[sec] = kv
    if CONF.is_file():
        try:
            cp.read(CONF, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ 配置文件读取失败（用默认值）：{e}")
    return cp


def data_root(cp: configparser.ConfigParser) -> Path:
    """数据目录：conf 里指定优先，否则用同级 _data。"""
    v = (cp.get("paths", "data", fallback="") or "").strip()
    return Path(v) if v else DATA


# --------------------------------------------------------------------------- #
# 用对解释器：依赖装在专用 venv 里，若当前解释器没有就用它重新执行自己
# --------------------------------------------------------------------------- #
def deps_ok() -> bool:
    try:
        __import__("yt_dlp")
        __import__("faster_whisper")
        return True
    except ImportError:
        return False


def find_python(cp: configparser.ConfigParser) -> str | None:
    """找装了依赖的解释器：conf > 本机约定 venv > None。"""
    v = (cp.get("paths", "python", fallback="") or "").strip()
    if v and Path(v).is_file():
        return v
    # 本机约定：managed python 的 default venv（Windows 下可执行在 Scripts\）
    home = Path.home()
    for rel in ("Scripts/python.exe", "bin/python"):
        p = home / ".workbuddy" / "binaries" / "python" / "envs" / "default" / rel
        if p.is_file():
            return str(p)
    return None


def relaunch_if_needed(cp: configparser.ConfigParser) -> int | None:
    """当前解释器缺依赖时，用 venv 解释器重新执行本脚本。返回退出码或 None。"""
    if deps_ok():
        return None
    if os.environ.get("V2T_RELAUNCHED") == "1":
        print("  ✗ 已在专用解释器里运行但仍缺少依赖。")
        print("    请安装：pip install yt-dlp faster-whisper \"av<19\"")
        return 1
    py = find_python(cp)
    if not py:
        print("  ✗ 当前解释器缺少 yt-dlp / faster-whisper，且未找到专用 venv。")
        print("    请在 video2text.conf 的 [paths] python 里指定解释器路径。")
        return 1
    if Path(py).resolve() == Path(sys.executable).resolve():
        print(f"  ✗ 当前解释器（{py}）缺少依赖。")
        print("    请安装：pip install yt-dlp faster-whisper \"av<19\"")
        return 1

    env = dict(os.environ, V2T_RELAUNCHED="1")
    print(f"  当前解释器无依赖，改用专用解释器重跑：{py}", flush=True)
    try:
        return subprocess.run([py, str(Path(__file__).resolve()), *sys.argv[1:]],
                              env=env).returncode
    except OSError as e:
        print(f"  ✗ 启动失败：{e}")
        return 1


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}"


def human(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def safe_name(name: str, limit: int = 80) -> str:
    name = unicodedata.normalize("NFKC", name or "video")
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return (name[:limit] or "video").strip()


def write_text(path: Path, text: str) -> None:
    """统一 UTF-8 + LF（newline='' 防止 Windows 下写成 CRLF）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".text-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def clear() -> None:
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        print("\n" * 40)


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


# --------------------------------------------------------------------------- #
# 登录态
# --------------------------------------------------------------------------- #
def cookie_info() -> dict:
    """读 cookie 文件，返回 {exists, sessdata_len, expires}"""
    out = {"exists": COOKIE_FILE.is_file(), "sessdata_len": 0, "expires": None}
    if not out["exists"]:
        return out
    try:
        with open(COOKIE_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and parts[5] == "SESSDATA" and parts[0] == ".bilibili.com":
                    out["sessdata_len"] = len(parts[6])
                    try:
                        out["expires"] = int(parts[4])
                    except ValueError:
                        pass
                    break
    except OSError:
        pass
    return out


def cookie_status_line() -> str:
    ci = cookie_info()
    if not ci["exists"]:
        return "未登录（无 cookie 文件）"
    if not ci["sessdata_len"]:
        return "cookie 文件存在，但没有 SESSDATA"
    if ci["expires"]:
        days = (ci["expires"] - time.time()) / 86400
        when = time.strftime("%Y-%m-%d", time.localtime(ci["expires"]))
        if days <= 0:
            return f"已过期（{when}）"
        return f"有效至 {when}（还剩 {days:.0f} 天）"
    return "有 SESSDATA（未记录有效期）"


def bili_login(timeout: int = 600) -> int:
    """扫码登录，建立可长期复用的专用 profile 并导出 cookie。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ✗ 缺少 playwright，无法扫码登录：pip install playwright")
        return 1

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  B站 扫码登录")
    print("=" * 64)
    print(f"  专用 profile：{PROFILE_DIR}")
    print(f"  cookie 输出 ：{COOKIE_FILE}")
    print()
    print("  窗口打开后，用手机 B站 App 扫码：左上角头像 → 扫一扫")
    print(f"  等待上限 {timeout} 秒；成功后自动保存并关闭窗口。")
    print()

    t0 = time.time()
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="msedge",
                headless=False,
                viewport=None,
                args=["--no-first-run", "--no-default-browser-check",
                      "--window-size=1280,900",
                      "--disable-features=msEdgeFirstRunExperience"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://passport.bilibili.com/login",
                          wait_until="domcontentloaded", timeout=60000)
                print(f"  已打开登录页：{page.url}")
            except Exception as e:  # noqa: BLE001
                print(f"  导航告警：{type(e).__name__}: {str(e)[:80]}")

            print("  等待扫码中", end="", flush=True)
            sess = None
            last = time.time()
            while time.time() - t0 < timeout:
                if time.time() - last >= 5:
                    print(".", end="", flush=True)
                    last = time.time()
                try:
                    cookies = ctx.cookies()
                except Exception:  # noqa: BLE001
                    print("\n  窗口被关闭。")
                    return 3
                hit = [c for c in cookies
                       if c["name"] == "SESSDATA" and "bilibili.com" in c["domain"]
                       and c["value"]]
                if hit:
                    sess = hit[0]["value"]
                    break
                time.sleep(1.5)
            print()

            if not sess:
                print(f"  ⏱ 超时 {timeout} 秒，未检测到登录。")
                ctx.close()
                return 2

            print(f"  ✓ 检测到 SESSDATA（长度 {len(sess)}），登录成功")
            try:
                page.goto("https://www.bilibili.com/",
                          wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
            except Exception:  # noqa: BLE001
                pass

            cookies = ctx.cookies()
            n = _write_netscape(cookies)
            try:
                ctx.storage_state(path=str(STATE_FILE))
            except Exception:  # noqa: BLE001
                pass
            ctx.close()

        print(f"  ✓ 已写出 {n} 条 cookie → {COOKIE_FILE}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"\n  ✗ 运行异常：{type(e).__name__}: {str(e)[:160]}")
        return 4


def _write_netscape(cookies: list) -> int:
    lines = ["# Netscape HTTP Cookie File",
             "# 由 video2text 专用 profile 导出（浏览器自身解密）", ""]
    n = 0
    for c in cookies:
        dom = c["domain"]
        exp = c.get("expires") or -1
        exp = int(time.time()) + 30 * 24 * 3600 if (exp is None or exp < 0) else int(exp)
        lines.append("\t".join([dom,
                                "TRUE" if dom.startswith(".") else "FALSE",
                                c.get("path") or "/",
                                "TRUE" if c.get("secure") else "FALSE",
                                str(exp), c["name"], c["value"]]))
        n += 1
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return n


# --------------------------------------------------------------------------- #
# 探测字幕
# --------------------------------------------------------------------------- #
def ydl_opts(nocookie: bool, browser: str, cookies: str | None, quiet: bool) -> dict:
    opts = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noprogress": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 3,
        # 关键：不开这个开关，B站 extractor 根本不会去请求字幕接口，
        # 返回的 subtitles 永远是空 dict（即使已登录）。命令行 --list-subs
        # 之所以能拿到，正是因为它会置位该参数。
        "listsubtitles": True,
        "noplaylist": True,
    }
    if cookies:
        opts["cookiefile"] = cookies
    elif not nocookie:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def probe_subtitles(url: str, *, nocookie: bool, browser: str,
                    cookies: str | None, quiet: bool = True) -> dict:
    """探测字幕。返回 {'info', 'subtitles', 'auto'}。

    注：置了 listsubtitles 后 yt-dlp 会把字幕表直接写到 stdout，
    与调用方的输出交错；这里把它收进缓冲区，失败时再补打出来。
    """
    import contextlib
    import io
    import yt_dlp

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with yt_dlp.YoutubeDL(ydl_opts(nocookie, browser, cookies, quiet)) as ydl:
                info = ydl.extract_info(url, download=False)
    except Exception:
        # extractor 输出可能含请求信息，不回显原始日志。
        raise

    if not info or info.get("_type") == "playlist":
        raise RuntimeError("单集探测返回合集，拒绝误取首集")
    return {
        "info": info,
        "subtitles": info.get("subtitles") or {},
        "auto": info.get("automatic_captions") or {},
    }


def pick_subtitle_lang(subtitles: dict, auto: dict, prefer: str | None):
    """兼容旧调用；使用经过格式过滤的字幕选择器。"""
    from subtitle_support import pick_track
    return pick_track(subtitles, auto, prefer)


# --------------------------------------------------------------------------- #
# 字幕解析
# --------------------------------------------------------------------------- #
def cookie_header(cookiefile: str | None) -> str | None:
    """旧裸凭据接口禁用；新下载器直接接收 Cookie 文件路径。"""
    if cookiefile:
        raise ValueError("不再导出裸 Cookie 字符串，请使用安全字幕接口")
    return None


def fetch_url(url: str, cookies: str | None = None) -> bytes:
    """公开元数据下载；禁止旧接口通过裸字符串传播凭据。"""
    if cookies:
        raise ValueError("禁止裸 Cookie 请求；请使用按域匹配的字幕下载接口")
    from subtitle_support import fetch_subtitle
    return fetch_subtitle(url, retries=2)


def parse_bili_json(raw: bytes):
    """B站字幕 JSON：{"body":[{"from":0.0,"to":1.5,"content":"..."}]}"""
    data = json.loads(raw.decode("utf-8"))
    body = data.get("body") or data.get("subtitles") or []
    out = []
    for it in body:
        frm = it.get("from", it.get("start", 0))
        to = it.get("to", it.get("end", frm))
        content = (it.get("content") or it.get("text") or "").strip()
        if content:
            out.append((float(frm), float(to), content))
    return out


def _to_sec(t: str) -> float:
    h, m, rest = t.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_srt(text: str):
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d+:\d+:\d+[.,]\d+)\s*-->\s*(\d+:\d+:\d+[.,]\d+)", block)
        if not m:
            continue
        content = " ".join(lines[2:]) if lines[0].strip().isdigit() else " ".join(lines[1:])
        content = re.sub(r"<[^>]+>", "", content).strip()
        if content:
            out.append((_to_sec(m.group(1)), _to_sec(m.group(2)), content))
    return out


def parse_vtt(text: str):
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        # 定位时间戳行；cue 可能带标识行（"cue-id"），内容在时间戳行之后
        ts = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ts is None:
            continue
        m = re.search(r"(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)", lines[ts])
        if not m:
            continue
        tag = re.sub(r"<[^>]+>", "", " ".join(lines[ts + 1:])).strip()
        if not tag:
            continue
        if out and out[-1][2] == tag:      # VTT 常把上一条重打一遍
            continue
        out.append((_to_sec(m.group(1)), _to_sec(m.group(2)), tag))
    return out


def parse_subtitle_items(items: list, cookies: str | None):
    """返回 (segments, note)"""
    last_err = None
    for it in items:
        url, ext = it.get("url"), (it.get("ext") or "").lower()
        try:
            if it.get("data"):
                raw = it["data"].encode("utf-8")
            elif url:
                raw = fetch_url(url, cookies)
            else:
                continue
            if ext in ("json", "json3", "") and raw.lstrip()[:1] == b"{":
                segs = parse_bili_json(raw)
                if segs:
                    return segs, f"{ext or 'json'} 解析成功"
            text = raw.decode("utf-8", errors="replace")
            if "-->" in text:
                segs = parse_vtt(text) if (ext == "vtt" or text.startswith("WEBVTT")) \
                       else parse_srt(text)
                if segs:
                    return segs, f"{ext or 'srt/vtt'} 解析成功"
            try:
                segs = parse_bili_json(raw)
                if segs:
                    return segs, "json 兜底解析成功"
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            last_err = e
    return [], f"字幕下载/解析失败：{type(last_err).__name__}"


def segments_to_text(segments, header: str) -> str:
    lines = [header, ""]
    for frm, _to, content in segments:
        lines.append(f"[{fmt_ts(frm)}] {content}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# 音频与转写
# --------------------------------------------------------------------------- #
def download_audio(url: str, outdir: Path, *, nocookie: bool, browser: str,
                   cookies: str | None) -> Path:
    from audio_support import download_audio_cached
    print("  检查音频缓存；未命中时下载或续传", flush=True)
    return download_audio_cached(url, outdir, nocookie=nocookie, browser=browser, cookies=cookies)


def transcribe(audio: Path, *, model_name: str, model_dir: Path | None,
               device: str, compute_type: str, vad: bool,
               prompt: str, language: str | None, refresh: bool = False):
    from transcription_support import transcribe_resumable
    return transcribe_resumable(audio, model_name=model_name, model_dir=model_dir,
                                device=device, compute_type=compute_type, vad=vad,
                                prompt=prompt, language=language, refresh=refresh)


# --------------------------------------------------------------------------- #
# 单个视频转换（面板与命令行共用）
# --------------------------------------------------------------------------- #
def convert(url: str, *, cp: configparser.ConfigParser, nocookie: bool,
            force_whisper: bool, lang: str | None, model: str | None,
            outdir: Path | None, keep_audio: bool | None,
            cookies_file: Path | None = None,
            model_dir: Path | None = None,
            verbose: bool = True,
            target_dir: Path | None = None,
            mode: str | None = None, refresh_transcription: bool = False) -> dict:
    """转写一个视频。返回 {'ok', 'title', 'mode', 'path', 'segments', 'seconds', 'error'}"""
    t0 = time.time()
    res = {"ok": False, "title": "", "mode": "", "path": None,
           "segments": 0, "seconds": 0.0, "error": None}

    from subtitle_support import SubtitleFetchError, SubtitleParseError, pick_track, parse_track_items

    selected_mode = "whisper" if force_whisper else (mode or cp.get("download", "mode", fallback="subtitles"))
    if selected_mode not in ("subtitles", "auto", "whisper"):
        res.update(error="处理模式非法", error_code="invalid_mode")
        return res
    retries = max(0, min(5, cp.getint("download", "subtitle_retries", fallback=2)))
    browser = cp.get("download", "browser", fallback="edge")
    parsed_display = urllib.parse.urlsplit(url)
    display_url = urllib.parse.urlunsplit((parsed_display.scheme, parsed_display.hostname or "", parsed_display.path, "", ""))
    print(f"  模式：{selected_mode}；探测中：{display_url}（查询参数已隐藏）")
    cf = cookies_file if cookies_file is not None else COOKIE_FILE
    cookies = None
    if not nocookie and cf.is_file():
        cookies = str(cf)

    for attempt in range(retries + 1):
        try:
            probe = probe_subtitles(url, nocookie=nocookie, browser=browser,
                                   cookies=cookies, quiet=True)
            break
        except Exception as e:  # noqa: BLE001
            if attempt < retries:
                print(f"  字幕探测重试 {attempt + 1}/{retries}", flush=True)
                continue
            res.update(error=f"探测失败：{type(e).__name__}（不回显请求详情）",
                       error_code="probe_failed")
            print(f"  ✗ {res['error']}")
            return res

    info = probe["info"]
    title = safe_name(info.get("title") or "video")
    duration = info.get("duration") or 0
    res["title"] = info.get("title") or title

    print(f"  标题：{info.get('title')}")
    print(f"  时长：{fmt_ts(duration)}（{duration / 60:.1f} 分钟）")
    print(f"  字幕：人工/UP {sorted(probe['subtitles']) or '（无）'}　"
          f"AI {sorted(probe['auto']) or '（无）'}")

    base = outdir or (data_root(cp) / "transcripts")
    identity = str(info.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20])
    target = target_dir if target_dir is not None else base / (title + "--" + safe_name(identity))
    target.mkdir(parents=True, exist_ok=True)

    picked = None if selected_mode == "whisper" else pick_track(
        probe["subtitles"], probe["auto"], lang)
    if lang and not picked and selected_mode != "whisper":
        res.update(error="指定字幕语言不可用", error_code="language_unavailable")
        return res

    # ---------- 分支 A：字幕（秒级） ----------
    if picked:
        sub_lang, items = picked
        print(f"  → 走字幕路线（语言码 {sub_lang}）")
        try:
            segs, note = parse_track_items(items, cookiefile=cookies, retries=retries)
        except (SubtitleFetchError, SubtitleParseError) as exc:
            code = "subtitle_fetch_failed" if isinstance(exc, SubtitleFetchError) else "subtitle_parse_failed"
            res.update(error="字幕获取或解析失败，已保留已有文件；不自动转语音识别", error_code=code)
            print(f"  ✗ {res['error']}")
            return res
        print(f"    {note}，共 {len(segs)} 条")
        if segs:
            header = (f"# 转写来源：B站/YouTube 字幕（语言码 {sub_lang}）\n"
                      f"# 标题：{info.get('title')}\n"
                      f"# 时长：{fmt_ts(duration)}")
            txt = target / "transcript.txt"
            write_text(txt, segments_to_text(segs, header))
            res.update(ok=True, mode=f"字幕({sub_lang})", path=txt,
                       segments=len(segs), seconds=time.time() - t0)
            print(f"  ✓ 完成：{txt}")
            return res
        res.update(error="字幕内容为空，不自动转语音识别", error_code="subtitle_empty")
        return res

    if selected_mode == "subtitles":
        res.update(error="未取得可用字幕；仅字幕模式不启动语音转写", error_code="no_subtitles")
        print(f"  {res['error']}")
        return res

    if not picked:
        print("  → 已允许语音转写，走 whisper 路线")
        if duration:
            print(f"    音频 {duration / 60:.1f} 分钟；耗时取决于硬件，心跳将持续报告阶段。")

    # ---------- 分支 B：whisper ----------
    try:
        audio = download_audio(url, target, nocookie=nocookie,
                               browser=browser, cookies=cookies)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"音频下载失败：{type(e).__name__}；可用 --lock-status 检查主锁及缓存锁（不回显请求详情）"
        print(f"  ✗ {res['error']}")
        return res

    m_name = model or cp.get("whisper", "model", fallback="medium")
    local = model_dir
    if local is None:
        cand = MODELS_DIR / f"faster-whisper-{m_name}"
        local = cand if cand.is_dir() else None

    try:
        segs = transcribe(
            audio, model_name=m_name, model_dir=local,
            device=cp.get("whisper", "device", fallback="cpu"),
            compute_type=cp.get("whisper", "compute_type", fallback="int8"),
            vad=cp.getboolean("whisper", "vad", fallback=True),
            prompt=cp.get("whisper", "prompt", fallback=DEFAULTS["whisper"]["prompt"]),
            language=(cp.get("whisper", "language", fallback="") or None),
            refresh=refresh_transcription,
        )
    except Exception as e:  # noqa: BLE001
        res["error"] = f"转写失败：{type(e).__name__}（不回显请求详情）；请检查该集检查点及运行日志"
        print(f"  ✗ {res['error']}")
        return res

    if not segs:
        res["error"] = "转写结果为空（未识别到语音），不写出以免覆盖已有产物"
        print(f"  ✗ {res['error']}")
        return res

    header = (f"# 转写来源：faster-whisper ({m_name})\n"
              f"# 标题：{info.get('title')}\n"
              f"# 时长：{fmt_ts(duration)}")
    txt = target / "transcript.txt"
    write_text(txt, segments_to_text(segs, header))
    res.update(ok=True, mode=f"whisper({m_name})", path=txt,
               segments=len(segs), seconds=time.time() - t0)
    print(f"  ✓ 完成：{txt}")

    if keep_audio is None:
        keep_audio = cp.getboolean("download", "keep_audio", fallback=True)
    if not keep_audio and audio.exists():
        try:
            from audio_support import drop_cached_audio
            if ".audio-cache" in audio.parts:
                drop_cached_audio(audio)
            else:
                audio.unlink()
            print("    已删除音频（keep_audio = false）")
        except OSError:
            pass
    return res


# --------------------------------------------------------------------------- #
# 合集识别与增量状态
# --------------------------------------------------------------------------- #
def bili_input(url: str):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in ("www.bilibili.com", "bilibili.com", "m.bilibili.com"):
        return None
    match = re.fullmatch(r"/video/(BV[0-9A-Za-z]+)/*", parsed.path)
    if not match:
        return None
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    part = None
    if "p" in query:
        if len(query["p"]) != 1 or not query["p"][0].isdigit() or int(query["p"][0]) < 1:
            raise ValueError("p 必须是一个正整数")
        part = int(query["p"][0])
    return match.group(1), part


def bili_view(bvid: str) -> dict:
    raw = fetch_url("https://api.bilibili.com/x/web-interface/view?" +
                    urllib.parse.urlencode({"bvid": bvid}))
    reply = json.loads(raw)
    if reply.get("code") != 0 or not isinstance(reply.get("data"), dict):
        raise RuntimeError("B站公开 view 元数据请求失败")
    data = reply["data"]
    if data.get("bvid") != bvid:
        raise ValueError("元数据 BV 身份不匹配")
    return data


def bili_episodes(data: dict) -> list:
    bvid = data.get("bvid")
    if not isinstance(bvid, str) or not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        raise ValueError("元数据缺少有效 BV")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("元数据缺少分P列表")
    episodes = []
    for page in pages:
        cid, part = page.get("cid"), page.get("page")
        if type(cid) is not int or cid < 1 or type(part) is not int or part < 1:
            raise ValueError("分P缺少有效 cid/page")
        episodes.append({"id": f"{bvid}-cid-{cid}", "bvid": bvid, "cid": cid,
                         "part": part, "title": page.get("part") or data.get("title") or bvid,
                         "url": f"https://www.bilibili.com/video/{bvid}?p={part}"})
    if len({e["id"] for e in episodes}) != len(episodes):
        raise ValueError("分P cid 重复")
    return episodes


def discover_bili(url: str, *, all_parts: bool = False, single: bool = False) -> dict:
    selected = bili_input(url)
    if selected is None:
        identity = "url-" + hashlib.sha256(url.encode()).hexdigest()[:32]
        return {"id": identity, "title": "单集", "episodes": [
            {"id": identity, "title": "单集", "url": url}]}
    bvid, part = selected
    data = bili_view(bvid)
    own = bili_episodes(data)
    if single and part is None:
        part = 1
    if part is not None and not all_parts:
        episodes = [e for e in own if e["part"] == part]
        if not episodes:
            raise ValueError("指定 p 不在当前分P列表中")
        return {"id": "bili-video-" + bvid, "title": data.get("title"), "episodes": episodes}
    season = data.get("ugc_season")
    if season:
        sid = season.get("id")
        if type(sid) is not int or sid < 1:
            raise ValueError("ugc_season 缺少稳定 ID")
        members = []
        provided_count = 0
        for section in season.get("sections") or []:
            for episode in section.get("episodes") or []:
                provided_count += 1
                member = episode.get("bvid") or (episode.get("arc") or {}).get("bvid")
                if not member:
                    raise ValueError("ugc_season 成员缺少 BV，拒绝不完整展开")
                if member not in members:
                    members.append(member)
        expected_count = season.get("episode_count")
        if type(expected_count) is int and expected_count > provided_count:
            raise ValueError("ugc_season 成员数量少于 episode_count，拒绝不完整展开")
        if not members:
            raise ValueError("ugc_season 未提供成员列表")
        episodes = []
        for member in members:
            episodes.extend(bili_episodes(data if member == bvid else bili_view(member)))
        return {"id": f"bili-season-{sid}", "title": season.get("title"), "episodes": episodes}
    return {"id": "bili-video-" + bvid, "title": data.get("title"), "episodes": own}



def flat_playlist(url: str, *, nocookie: bool = False, browser: str = "edge",
                  cookies: str | None = None, single: bool = False) -> dict:
    """仅展开元信息；禁止下载，并完整消费分页列表，不限制集数。"""
    import yt_dlp

    opts = ydl_opts(nocookie, browser, cookies, True)
    opts.update(extract_flat="in_playlist", noplaylist=single, listsubtitles=False)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("未取得视频或合集元信息")
    if single and info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("该链接仅指向合集；--single 需要具体视频链接")
    return info


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("条目缺少有效 HTTP 视频链接")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
             if not k.startswith("utm_") and k not in ("spm_id_from", "vd_source")]
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                                   parsed.path, urllib.parse.urlencode(sorted(query)), ""))


def discover(url: str, *, all_parts: bool = False, single: bool = False,
             nocookie: bool = False, browser: str = "edge", cookies: str | None = None) -> dict:
    # BV公开view补足extractor不自动展开ugc_season的限制，并以cid跨重排识别分P。
    selected = bili_input(url)
    if selected is not None:
        return discover_bili(url, all_parts=all_parts, single=single)
    info = flat_playlist(url, nocookie=nocookie, browser=browser, cookies=cookies, single=single)
    entries = list(info.get("entries") or []) if info.get("_type") in ("playlist", "multi_video") else [info]
    if not entries:
        raise ValueError("合集为空，拒绝记录不完整成功")
    episodes, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("合集含不可访问条目，拒绝不完整展开")
        entry_url = entry.get("webpage_url") or entry.get("url")
        if not entry_url and entry is info:
            entry_url = url
        if not isinstance(entry_url, str):
            raise ValueError("合集成员缺少规范链接")
        entry_url = canonical_url(entry_url)
        bili = bili_input(entry_url)
        if bili:
            # 合集内不同BV成员也可能各自有分P，但不递归展开其所属season。
            found = discover_bili(entry_url, single=single) if bili[1] else None
            if found is None:
                data = bili_view(bili[0])
                members = bili_episodes(data)
                if single:
                    members = members[:1]
            else:
                members = found["episodes"]
        else:
            source = entry.get("ie_key") or entry.get("extractor_key") or info.get("extractor_key")
            stable = f"{source}:{entry['id']}" if source and entry.get("id") else entry_url
            key = "url-" + hashlib.sha256(stable.encode()).hexdigest()[:32]
            members = [{"id": key, "title": entry.get("title") or "单集", "url": entry_url}]
        for member in members:
            if member["id"] not in seen:
                seen.add(member["id"])
                episodes.append(member)
    source = info.get("extractor_key") or info.get("ie_key")
    stable = f"{source}:{info['id']}" if source and info.get("id") else canonical_url(url)
    identity = "playlist-" + hashlib.sha256(stable.encode()).hexdigest()[:32]
    return {"id": identity, "title": info.get("title") or "视频", "episodes": episodes}



def relative_output(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("manifest 产物路径非法")
    path = Path(value)
    if path.is_absolute() or any(p in (".", "..", "") for p in value.split("/")):
        raise ValueError("manifest 产物路径必须是安全相对路径")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("manifest 产物路径越界（含符号链接）")
    return target


def load_manifest(path: Path, root: Path) -> dict:
    if not path.exists():
        return {"version": 1, "collections": {}, "episodes": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("版本或根结构错误")
        for table in ("collections", "episodes"):
            if not isinstance(state.get(table), dict):
                raise ValueError("状态表结构错误")
        for key, entry in state["episodes"].items():
            if not re.fullmatch(r"(?:BV[0-9A-Za-z]+-cid-[1-9][0-9]*|url-[0-9a-f]{32})", key):
                raise ValueError("集 ID 非法")
            if not isinstance(entry, dict) or entry.get("status") not in ("success", "failed", "pending"):
                raise ValueError("集状态非法")
            expected = f"episodes/{key}/transcript.txt"
            if entry.get("path") != expected:
                raise ValueError("集 ID 与产物路径不匹配")
            relative_output(root, entry["path"])
        for entry in state["collections"].values():
            if not isinstance(entry, dict) or not isinstance(entry.get("episode_ids"), list):
                raise ValueError("合集结构非法")
            if any(not isinstance(k, str) or k not in state["episodes"] for k in entry["episode_ids"]):
                raise ValueError("合集引用未知集")
        return state
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("manifest 损坏或不安全，拒绝覆盖；请人工检查并恢复") from exc


def atomic_json(path: Path, state: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def process(url: str, *, cp: configparser.ConfigParser, all_parts: bool = False,
            refresh: bool = False, single: bool = False, outdir: Path | None = None,
            only_failed: bool = False, **options) -> dict:
    """识别合集并增量转写；convert 仍是单集接口。失败返回非零 exit_code。"""
    result = {"ok": False, "completed": 0, "skipped": 0, "failed": 0,
              "results": [], "error": None, "exit_code": 1}
    root = (outdir or (data_root(cp) / "transcripts")).resolve()
    lock = root / ".video2text.lock"
    locked = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        with lock.open("x", encoding="utf-8", newline="") as stream:
            locked = True
            stream.write(str(os.getpid()) + "\n")
        manifest = root / ".video2text-manifest.json"
        if manifest.is_symlink():
            raise ValueError("manifest 不得是符号链接")
        state = load_manifest(manifest, root)
        if single and all_parts:
            raise ValueError("--single 与 --all-parts 不可同时使用")
        if only_failed and refresh:
            raise ValueError("--only-failed 与 --force 不可同时使用")
        cf = options.get("cookies_file") or COOKIE_FILE
        cookie = str(cf) if not options.get("nocookie", False) and cf.is_file() else None
        collection = discover(url, all_parts=all_parts, single=single,
                              nocookie=options.get("nocookie", False),
                              browser=cp.get("download", "browser", fallback="edge"), cookies=cookie)
        episodes = collection["episodes"]
        print(f"  合集/单集：{collection['id']}，本次 {len(episodes)} 集")
        if refresh:
            print("  refresh：强制重做本次所选全部集（包括已有成功产物）")
        # 显式单集选择不抹掉同 BV 的已知其它成员；移除集记录/文件始终留存。
        old = state["collections"].get(collection["id"], {})
        known = list(dict.fromkeys(old.get("episode_ids", []) + [e["id"] for e in episodes]))
        state["collections"][collection["id"]] = {
            "title": collection["title"], "episode_ids": known,
            "selected_ids": [e["id"] for e in episodes]}
        retry_ids = {key for key, entry in state["episodes"].items()
                     if entry.get("status") in ("failed", "pending")}
        for episode in episodes:
            key = episode["id"]
            if only_failed and key not in state["episodes"]:
                continue
            state["episodes"].setdefault(key, {
                "status": "pending", "path": f"episodes/{key}/transcript.txt"})
        if only_failed:
            # 未选择的新条目不得污染为 pending，影响下一次“仅失败”处理。
            state["collections"][collection["id"]]["episode_ids"] = [
                key for key in known if key in state["episodes"]]
            state["collections"][collection["id"]]["selected_ids"] = [
                e["id"] for e in episodes if e["id"] in state["episodes"]]
        for episode_number, episode in enumerate(episodes, 1):
            key = episode["id"]
            print(f"  [{episode_number}/{len(episodes)}] {episode.get('title') or key}", flush=True)
            if only_failed and key not in retry_ids:
                result["skipped"] += 1
                continue
            path = f"episodes/{key}/transcript.txt"
            target = relative_output(root, path)
            entry = state["episodes"].setdefault(key, {"status": "pending", "path": path})
            entry.update({k: v for k, v in episode.items() if k != "url"})
            entry["path"] = path
            valid = (target.is_file() and target.stat().st_size > 0
                     and entry.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest())
            if not refresh and entry["status"] == "success" and valid:
                result["skipped"] += 1
                result["results"].append({"id": key, "ok": True, "skipped": True})
                continue
            entry["status"] = "pending"
            atomic_json(manifest, state)
            try:
                res = convert(episode["url"], cp=cp, outdir=root,
                              target_dir=target.parent, refresh_transcription=refresh, **options)
                if res["ok"] and (not target.is_file() or target.stat().st_size == 0):
                    res = {"ok": False, "error": "转换未写出非空产物"}
            except Exception as exc:
                res = {"ok": False, "error": f"单集异常：{type(exc).__name__}"}
            entry["status"] = "success" if res["ok"] else "failed"
            if res["ok"]:
                entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                entry["size"] = target.stat().st_size
            else:
                entry.pop("sha256", None)
                entry.pop("size", None)
            # 不存原始异常/请求或凭据；日志仅给出失败类别和稳定集 ID。
            safe_codes = {"invalid_mode", "probe_failed", "language_unavailable", "subtitle_fetch_failed",
                          "subtitle_parse_failed", "subtitle_empty", "no_subtitles"}
            entry["error_code"] = None if res["ok"] else (
                res.get("error_code") if res.get("error_code") in safe_codes else "conversion_failed")
            entry["error"] = None if res["ok"] else "转换失败，下一次自动重试"
            if res["ok"]:
                entry["mode"] = res.get("mode", "unknown")
                entry["segments"] = res.get("segments")
            result["completed" if res["ok"] else "failed"] += 1
            result["results"].append({"id": key, "ok": res["ok"], "skipped": False})
            atomic_json(manifest, state)
        atomic_json(manifest, state)
        # 人类可读标题层由内部哈希校验产物生成；失败不会推翻已成功的内部转写。
        from title_layout import materialize_collection
        try:
            layout = materialize_collection(root, collection["id"], lock_held=True)
            print(f"  标题目录：{layout['directory']}（新增/更新 {layout['written']}，已有 {layout['skipped']}）")
            if layout.get('stale'):
                print(f"  旧标题副本仍保留 {len(layout['stale'])} 份；请看标题视图索引，不自动删除。")
        except (OSError, ValueError, RuntimeError) as exc:
            result["error"] = f"文字已保存在内部目录，但标题视图生成失败：{type(exc).__name__}；可稍后重试"
            result["failed"] += 1
        result.update(ok=result["failed"] == 0, exit_code=0 if result["failed"] == 0 else 1)
    except Exception as exc:
        if isinstance(exc, FileExistsError) and lock.exists():
            from collection_support import inspect_lock
            diagnosis = inspect_lock(root)
            result["error"] = f"输出目录有运行锁；诊断 {diagnosis.get('status', 'unknown')}，可用 --lock-status 查看；不会自动删除锁"
        else:
            result["error"] = str(exc) if isinstance(exc, ValueError) else f"处理失败：{type(exc).__name__}"
        result["failed"] += 1
    finally:
        if locked:
            lock.unlink()
    print(f"  汇总：完成 {result['completed']}，跳过 {result['skipped']}，失败 {result['failed']}")
    for item in result["results"]:
        if not item["ok"]:
            print(f"  失败集：{item['id']}（下次自动补做）")
    if result["error"]:
        print(f"  {result['error']}")
    return result


# --------------------------------------------------------------------------- #
# 面板各项
# --------------------------------------------------------------------------- #
def panel_collections(cp) -> None:
    from collection_support import list_collections, export_collection, inspect_lock
    root = data_root(cp) / "transcripts"
    try:
        collections = list_collections(root)
        print("  合集管理（按当前选择顺序）")
        for number, item in enumerate(collections, 1):
            print(f"  {number}. {item['title']} | 完整 {item['success']}/{item['total']} | {item['id']}")
        value = ask("  输入序号查看并导出，或 l 诊断锁，回车返回：").strip()
        if value == "l":
            print(inspect_lock(root))
        elif value.isdigit() and 1 <= int(value) <= len(collections):
            selected = collections[int(value) - 1]
            for episode in selected["episodes"]:
                label = episode['status'] if episode.get('verified') else (episode.get('reason') or episode['status'])
                print(f"  {episode['number']:02d} {episode['title']} [{label}]")
            if ask("  生成/同步标题文件夹？[y/N] ").strip().lower() in ("y", "yes"):
                from title_layout import materialize_collection
                layout = materialize_collection(root, selected['id'])
                print(f"  标题目录：{layout['directory']}")
                if layout.get('stale'):
                    print(f"  提醒：旧标题副本留存 {len(layout['stale'])} 份，未自动删除。")
            destination = ask("  导出到新 ZIP 路径（回车不导出）：").strip()
            if destination:
                result = export_collection(root, selected['id'], Path(destination))
                print(f"  导出：{result['path']}；完整：{result['complete']}")
    except (OSError, ValueError, KeyError) as exc:
        print(f"  合集操作失败：{type(exc).__name__}；请检查路径或状态")
    ask("  按回车返回…")


def panel_transcribe(cp) -> None:
    print("=" * 64)
    print("  转写视频")
    print("=" * 64)
    print("  粘贴视频链接（B站 / YouTube），回车开始。")
    print()
    url = ask("  链接：").strip()
    if not url:
        return
    if not re.match(r"^https?://", url):
        print("  ✗ 看起来不是链接。")
        return

    print()
    t0 = time.time()
    process(url, cp=cp, nocookie=False, force_whisper=False,
            lang=None, model=None, outdir=None, keep_audio=None)
    print(f"  （总耗时 {time.time() - t0:.1f}s）")
    ask("\n  按回车返回…")


def panel_batch(cp) -> None:
    print("=" * 64)
    print("  批量转写")
    print("=" * 64)
    print("  一行一个链接；输入空行结束。")
    print()

    urls, i = [], 0
    while True:
        s = ask(f"  {i + 1:>2}: ").strip()
        if not s:
            break
        # 也允许一行贴多个（逗号 / 空格分隔）
        for piece in re.split(r"[,\s]+", s):
            if piece and re.match(r"^https?://", piece):
                urls.append(piece)
        i += 1

    if not urls:
        print("  没有读到链接。")
        return

    print()
    print(f"  共 {len(urls)} 个链接，开始（中途可 Ctrl+C 中断）。")
    results = []
    for n, u in enumerate(urls, 1):
        print()
        print("=" * 64)
        print(f"  [{n}/{len(urls)}] {u}")
        print("=" * 64)
        try:
            results.append((u, process(u, cp=cp, nocookie=False,
                                       force_whisper=False, lang=None,
                                       model=None, outdir=None, keep_audio=None)))
        except KeyboardInterrupt:
            print("  ⏹ 已中断。")
            break

    print()
    print("=" * 64)
    print("  汇总")
    print("=" * 64)
    ok = sum(1 for _u, r in results if r["ok"])
    for n, (u, r) in enumerate(results, 1):
        if r["ok"]:
            print(f"  {n:>2}. 完成 {r['completed']}，跳过 {r['skipped']}，失败 {r['failed']}")
        else:
            print(f"  ✗ {n:>2}. {u}")
            print(f"        {r['error']}")
    print(f"\n  成功 {ok}/{len(results)}")
    ask("\n  按回车返回…")


def panel_list(cp) -> None:
    base = data_root(cp) / "transcripts"
    while True:
        clear()
        print("=" * 64)
        print("  已转写")
        print("=" * 64)
        if not base.is_dir():
            print("  还没有任何转写产物。")
            ask("\n  按回车返回…")
            return

        # 可读标题层不计入内部已转写清单，避免同一集重复显示。
        items = sorted((base / "episodes").glob("*/transcript.txt"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        items += sorted((p for p in base.glob("*/transcript.txt") if p.is_file()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        if not items:
            print("  还没有任何转写产物。")
            ask("\n  按回车返回…")
            return

        print(f"  共 {len(items)} 个：\n")
        for i, p in enumerate(items, 1):
            with p.open(encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            first = lines[0] if lines else ""
            n_lines = sum(1 for ln in lines if ln.startswith("["))
            size = p.stat().st_size
            mtime = time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            src = "字幕" if "字幕" in first else "whisper"
            title = next((ln[len("# 标题："):].strip() for ln in lines
                          if ln.startswith("# 标题：")), p.parent.name)
            print(f"  {i:>2}. {title[:44]:<46}")
            print(f"      {n_lines:>5} 条　{human(size):>9}　{src:<7} {mtime}")
        print()
        print("     序号    看预览（前 15 条）")
        print("     删除入口已停用：先核对索引与备份，再单独处理")
        print("     回车    返回")
        ans = ask("\n  选择：").strip().lower()
        if not ans:
            return

        m = re.match(r"^d\s*(\d+)$", ans)
        if m:
            print("  删除已停用：需先核对索引、完整列出影响文件并备份。")
            ask("  按回车返回…")
            continue

        if ans.isdigit() and 1 <= int(ans) <= len(items):
            p = items[int(ans) - 1]
            clear()
            print("=" * 64)
            with p.open(encoding="utf-8", errors="replace") as f:
                title = next((ln[len("# 标题："):].strip() for ln in f
                              if ln.startswith("# 标题：")), p.parent.name)
            print(f"  {title}")
            print("=" * 64)
            with p.open(encoding="utf-8", errors="replace") as f:
                for i, ln in enumerate(f):
                    if i >= 19:
                        print("  ...")
                        break
                    print(" ", ln.rstrip())
            ask("\n  按回车返回…")


def panel_status(cp) -> None:
    clear()
    print("=" * 64)
    print("  环境与模型状态")
    print("=" * 64)
    print(f"  解释器  ：{sys.executable}")
    print(f"  工具目录：{HERE}")
    print(f"  数据目录：{data_root(cp)}")
    print(f"  登录态  ：{cookie_status_line()}")
    print()

    print("  依赖：")
    for mod, label in (("yt_dlp", "yt-dlp"), ("faster_whisper", "faster-whisper"),
                       ("av", "av (PyAV)"), ("playwright", "playwright")):
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", None)
            if not ver and mod == "yt_dlp":
                try:
                    from yt_dlp.version import __version__ as v
                    ver = v
                except Exception:  # noqa: BLE001
                    ver = None
            if not ver:
                try:
                    from importlib.metadata import version as _v
                    ver = _v(label.split()[0])
                except Exception:  # noqa: BLE001
                    ver = "?"
            warn = ""
            if mod == "av":
                try:
                    if int(str(ver).split(".")[0]) >= 19:
                        warn = "  ⚠ 必须 <19（19 移除了 metadata_errors，转写会崩）"
                except ValueError:
                    pass
            print(f"    {label:<18} {ver}{warn}")
        except ImportError:
            print(f"    {label:<18} 未安装")

    print()
    print("  本地模型：")
    if MODELS_DIR.is_dir():
        found = [d for d in sorted(MODELS_DIR.iterdir()) if d.is_dir()]
        if found:
            for d in found:
                print(f"    {d.name:<34} {human(dir_size(d)):>10}")
        else:
            print("    （无）")
    else:
        print("    （无）")

    print()
    print("  转写产物：")
    base = data_root(cp) / "transcripts"
    items = (list((base / "episodes").glob("*/transcript.txt"))
             + list(base.glob("*/transcript.txt"))) if base.is_dir() else []
    print(f"    {len(items)} 份　{human(dir_size(base))}（含标题副本）")

    print()
    print("  关键环境变量（脚本已内置，无需手动设）：")
    print(f"    HF_ENDPOINT        = {os.environ.get('HF_ENDPOINT')}")
    print(f"    HF_HUB_DISABLE_XET = {os.environ.get('HF_HUB_DISABLE_XET')}  "
          f"（这个才是强制走镜像的开关）")

    print()
    print("  说明：模型下载请优先用 ModelScope（实测比 hf-mirror 快约 47 倍）。")
    ask("\n  按回车返回…")


# --------------------------------------------------------------------------- #
# 交互面板
# --------------------------------------------------------------------------- #
MENU = [
    ("1", "转写视频（粘贴链接）"),
    ("2", "批量转写（多个链接）"),
    ("3", "已转写（查看 / 预览）"),
    ("4", "重新登录 B站（扫码）"),
    ("5", "环境与模型状态"),
    ("6", "合集管理 / 导出 / 锁诊断"),
]


def interactive(cp) -> int:
    while True:
        clear()
        print("=" * 64)
        print("  video2text — 视频转文字")
        print("=" * 64)
        print(f"  工作区  ：{HERE.parent.parent}")
        print(f"  数据目录：{data_root(cp)}")
        print(f"  登录态  ：{cookie_status_line()}")
        base = data_root(cp) / "transcripts"
        n_done = (len(list((base / "episodes").glob("*/transcript.txt")))
                  + len(list(base.glob("*/transcript.txt")))) if base.is_dir() else 0
        models = [d.name for d in MODELS_DIR.iterdir()
                  if d.is_dir()] if MODELS_DIR.is_dir() else []
        print(f"  本地模型：{', '.join(models) if models else '（无）'}")
        print(f"  已转写  ：{n_done} 份")
        print("-" * 64)
        for no, title in MENU:
            print(f"  {no}. {title}")
        print("-" * 64)
        print("   0. 退出")
        print("=" * 64)

        choice = ask("\n  选择（回车退出）：").strip()
        if not choice or choice == "0":
            break
        if choice == "1":
            clear()
            panel_transcribe(cp)
        elif choice == "2":
            clear()
            panel_batch(cp)
        elif choice == "3":
            panel_list(cp)
        elif choice == "4":
            clear()
            bili_login()
            ask("\n  按回车返回…")
        elif choice == "5":
            panel_status(cp)
        elif choice == "6":
            panel_collections(cp)
    clear()
    print("  已退出 video2text。")
    return 0


# --------------------------------------------------------------------------- #
# 命令行
# --------------------------------------------------------------------------- #
def main() -> int:
    cp = load_conf()

    # 无参数 → 交互面板（从总面板进来就是这条路）
    argv = sys.argv[1:]
    if not argv:
        rc = relaunch_if_needed(cp)
        return rc if rc is not None else interactive(cp)

    ap = argparse.ArgumentParser(
        description="视频 → 带时间戳纯文本（不带参数运行则是交互面板）")
    ap.add_argument("url", nargs="?")
    ap.add_argument("-o", "--outdir", default=None, help="输出根目录")
    ap.add_argument("--mode", choices=("subtitles", "auto", "whisper"), default=None,
                    help="subtitles仅字幕(默认)；auto无字幕时转写；whisper强制转写")
    ap.add_argument("--only-failed", action="store_true", help="仅补做已记录failed/pending项，不处理新增集")
    ap.add_argument("--collections", action="store_true", help="列出已记录合集")
    ap.add_argument("--sync-titles", default=None, metavar="ID", help="从已校验产物同步指定合集的标题文件夹，不联网、不转写")
    ap.add_argument("--export-collection", default=None, metavar="ID", help="导出指定合集ZIP")
    ap.add_argument("--export-to", default=None, metavar="PATH", help="ZIP新文件路径，不覆盖已有文件")
    ap.add_argument("--lock-status", action="store_true", help="只读诊断运行锁，不删除锁")
    ap.add_argument("--model", default=None, help="whisper 模型名，默认取配置 medium")
    ap.add_argument("--model-dir", default=None, help="本地模型目录")
    ap.add_argument("--device", default=None)
    ap.add_argument("--compute-type", default=None)
    ap.add_argument("--cookies", default=None, help="Netscape cookie 文件")
    ap.add_argument("--no-cookies", action="store_true", help="匿名探测")
    ap.add_argument("--lang", default=None, help="指定字幕语言码，如 ai-zh")
    ap.add_argument("--force-whisper", action="store_true", help="忽略字幕，强制转写；已有成功集仍跳过，重做需 --refresh")
    ap.add_argument("--single", action="store_true", help="只处理当前视频；无 p 的BV选择第1P，不展开所属合集")
    ap.add_argument("--refresh", "--force", action="store_true", help="强制重做本次所选全部集，包括已成功产物")
    ap.add_argument("--all-parts", action="store_true", help="显式 p 也展开全部分P及同页 ugc_season")
    ap.add_argument("--keep-audio", dest="keep_audio", action="store_true", default=None)
    ap.add_argument("--drop-audio", dest="keep_audio", action="store_false")
    ap.add_argument("--no-vad", dest="vad", action="store_false", default=None)
    ap.add_argument("--whisper-language", default=None)
    ap.add_argument("--list", action="store_true", help="列出已转写")
    ap.add_argument("--status", action="store_true", help="显示环境与模型状态")
    ap.add_argument("--login", action="store_true", help="扫码登录 B站")
    args = ap.parse_args()

    if args.export_to and not args.export_collection:
        ap.error("--export-to 必须与 --export-collection 同用")
    if args.collections or args.export_collection or args.lock_status or args.sync_titles:
        from collection_support import list_collections, export_collection, inspect_lock
        root = Path(args.outdir) if args.outdir else data_root(cp) / "transcripts"
        try:
            if args.lock_status:
                print(json.dumps(inspect_lock(root), ensure_ascii=False, indent=2))
            if args.collections:
                for item in list_collections(root):
                    print(f"{item['id']} | {item['title']} | {item['success']}/{item['total']}")
            if args.sync_titles:
                from title_layout import materialize_collection
                layout = materialize_collection(root, args.sync_titles)
                print(json.dumps(layout, ensure_ascii=False, indent=2))
            if args.export_collection:
                if not args.export_to:
                    ap.error("--export-collection 必须指定 --export-to")
                exported = export_collection(root, args.export_collection, Path(args.export_to))
                print(json.dumps(exported, ensure_ascii=False, indent=2))
                return 0 if exported['complete'] else 1
            return 0
        except (OSError, ValueError, KeyError) as exc:
            print(f"合集操作失败：{type(exc).__name__}；未覆盖已有产物")
            return 1
    if args.force_whisper and args.mode == "subtitles":
        ap.error("--force-whisper 与 --mode subtitles 冲突")

    if args.status:
        rc = relaunch_if_needed(cp)
        if rc is not None:
            return rc
        panel_status(cp)
        return 0
    if args.list:
        rc = relaunch_if_needed(cp)
        if rc is not None:
            return rc
        panel_list(cp)
        return 0

    rc = relaunch_if_needed(cp)
    if rc is not None:
        return rc

    if args.login:
        return bili_login()

    if not args.url:
        ap.print_help()
        return 1

    # 命令行指定值覆盖配置
    if args.device:
        cp.set("whisper", "device", args.device)
    if args.compute_type:
        cp.set("whisper", "compute_type", args.compute_type)
    if args.vad is not None:
        cp.set("whisper", "vad", "true" if args.vad else "false")
    if args.whisper_language is not None:
        cp.set("whisper", "language", args.whisper_language)

    res = process(
        args.url, cp=cp, nocookie=args.no_cookies,
        refresh=args.refresh, all_parts=args.all_parts, single=args.single,
        mode=args.mode, only_failed=args.only_failed,
        force_whisper=args.force_whisper, lang=args.lang,
        model=args.model,
        outdir=Path(args.outdir) if args.outdir else None,
        keep_audio=args.keep_audio,
        cookies_file=Path(args.cookies) if args.cookies else None,
        model_dir=Path(args.model_dir) if args.model_dir else None,
    )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
