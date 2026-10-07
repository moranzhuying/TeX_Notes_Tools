#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video2text.py — 视频转文字（带时间戳纯文本）

把没有字幕的讲座视频（B站 / YouTube）转成带时间戳的纯文本，供大模型整理成
LaTeX 笔记。策略是**两段式**：

  1. 先探测该视频有没有字幕（B站 的 AI 字幕语言码是 `ai-zh`）
  2. **有字幕** → 直接下字幕转文本（秒级完成）
     **无字幕** → 下音频流 → faster-whisper (CPU/int8) 转写（慢，实时率约 0.5x）

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
TRANSCRIPTS = DATA / "transcripts"

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
        import yt_dlp  # noqa: F401
        import faster_whisper  # noqa: F401
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
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


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
        captured = buf.getvalue().strip()
        if captured:
            for ln in captured.splitlines()[-12:]:
                print(f"    | {ln}")
        raise

    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    return {
        "info": info,
        "subtitles": info.get("subtitles") or {},
        "auto": info.get("automatic_captions") or {},
    }


def pick_subtitle_lang(subtitles: dict, auto: dict, prefer: str | None):
    """按优先级挑一个语言 → (lang, items)"""
    if prefer:
        for table in (subtitles, auto):
            if prefer in table:
                return prefer, table[prefer]
        return None
    for lang in LANG_PRIORITY:
        for table in (subtitles, auto):
            if lang in table:
                return lang, table[lang]
    for table in (subtitles, auto):
        if table:
            lang = next(iter(table))
            return lang, table[lang]
    return None


# --------------------------------------------------------------------------- #
# 字幕解析
# --------------------------------------------------------------------------- #
def cookie_header(cookiefile: str | None) -> str | None:
    if not cookiefile:
        return None
    p = Path(cookiefile)
    if not p.exists():
        return None
    pairs = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and "bilibili" in parts[0]:
                pairs.append(f"{parts[5]}={parts[6]}")
    return "; ".join(pairs) if pairs else None


def fetch_url(url: str, cookies: str | None = None) -> bytes:
    if url.startswith("//"):
        url = "https:" + url
    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    if cookies:
        headers["Cookie"] = cookies
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


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
        m = re.search(r"(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)", block)
        if not m:
            continue
        tag = re.sub(r"<[^>]+>", "", " ".join(block.splitlines()[1:])).strip()
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
    return [], f"字幕下载/解析失败：{last_err}"


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
    import yt_dlp

    print()
    print("-" * 64)
    print("  下载音频流（yt-dlp -f ba，不转码 → 不需要 ffmpeg）")
    print("-" * 64)
    opts = {
        "format": "ba",                  # bestaudio；不加 -x，所以不需要 ffmpeg
        "outtmpl": str(outdir / "audio.%(ext)s"),
        "quiet": False,
        "noprogress": False,
        "socket_timeout": 30,
        "retries": 3,
    }
    if cookies:
        opts["cookiefile"] = cookies
    elif not nocookie:
        opts["cookiesfrombrowser"] = (browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    cand = [c for c in sorted(outdir.glob("audio.*"))
            if c.suffix.lower() not in (".part", ".ytdl")]
    if not cand:
        raise RuntimeError("音频下载失败：未找到音频文件")
    audio = max(cand, key=lambda p: p.stat().st_size)
    print(f"  >> 音频文件：{audio.name}  {human(audio.stat().st_size)}")
    return audio


def transcribe(audio: Path, *, model_name: str, model_dir: Path | None,
               device: str, compute_type: str, vad: bool,
               prompt: str, language: str | None):
    if model_dir and model_dir.is_dir():
        source, origin = str(model_dir), "本地目录（离线，免联网）"
    else:
        source = model_name
        origin = f"HuggingFace（走 {os.environ.get('HF_ENDPOINT')}）"

    print()
    print("-" * 64)
    print(f"  faster-whisper 转写（{device}/{compute_type}）")
    print("-" * 64)
    print(f"  模型来源：{origin}")
    print(f"  模型    ：{source}")
    print(f"  术语提示：{prompt}")
    if not (model_dir and model_dir.is_dir()):
        print("  ⚠ 未命中本地模型目录，将联网下载；若卡住请检查")
        print("    HF_ENDPOINT 与 HF_HUB_DISABLE_XET（后者才是强制走镜像的开关）")

    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(source, device=device, compute_type=compute_type)
    print(f"  >> 模型就绪，用时 {time.time() - t0:.1f}s")

    seg_iter, info = model.transcribe(
        str(audio),
        language=language,
        initial_prompt=prompt,
        vad_filter=vad,
        vad_parameters=dict(min_silence_duration_ms=500) if vad else None,
        condition_on_previous_text=False,   # 长讲座：避免陷入重复幻觉
        beam_size=5,
    )
    print(f"  >> 检测语言：{info.language} (p={info.language_probability:.2f})，"
          f"音频时长 {fmt_ts(info.duration)}")

    segs, t1, last = [], time.time(), time.time()
    for seg in seg_iter:
        segs.append((seg.start, seg.end, seg.text.strip()))
        if time.time() - last > 20:
            pct = (seg.end / info.duration * 100) if info.duration else 0
            print(f"     ... 转写中 {fmt_ts(seg.end)} / {fmt_ts(info.duration)}  "
                  f"({pct:.1f}%)", flush=True)
            last = time.time()
    print(f"  >> 转写完成：{len(segs)} 条，用时 {time.time() - t1:.1f}s")
    return segs


# --------------------------------------------------------------------------- #
# 单个视频转换（面板与命令行共用）
# --------------------------------------------------------------------------- #
def convert(url: str, *, cp: configparser.ConfigParser, nocookie: bool,
            force_whisper: bool, lang: str | None, model: str | None,
            outdir: Path | None, keep_audio: bool | None,
            cookies_file: Path | None = None,
            model_dir: Path | None = None,
            verbose: bool = True) -> dict:
    """转写一个视频。返回 {'ok', 'title', 'mode', 'path', 'segments', 'seconds', 'error'}"""
    t0 = time.time()
    res = {"ok": False, "title": "", "mode": "", "path": None,
           "segments": 0, "seconds": 0.0, "error": None}

    browser = cp.get("download", "browser", fallback="edge")
    print(f"  探测中：{url}")
    cf = cookies_file if cookies_file is not None else COOKIE_FILE
    cookies = None
    if not nocookie and cf.is_file():
        cookies = str(cf)

    try:
        probe = probe_subtitles(url, nocookie=nocookie, browser=browser,
                               cookies=cookies, quiet=True)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"探测失败：{type(e).__name__}: {str(e)[:150]}"
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
    target = base / title
    target.mkdir(parents=True, exist_ok=True)

    picked = None if force_whisper else pick_subtitle_lang(
        probe["subtitles"], probe["auto"], lang)

    # ---------- 分支 A：字幕（秒级） ----------
    if picked:
        sub_lang, items = picked
        print(f"  → 走字幕路线（语言码 {sub_lang}）")
        segs, note = parse_subtitle_items(items, cookie_header(cookies))
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
        print("    ⚠ 字幕解析失败，回退 whisper。")

    if not picked:
        print("  → 无可用字幕，走 whisper 转写")
        if duration:
            print(f"    预估耗时约 {duration * 0.5 / 60:.0f} 分钟（实测实时率约 0.5x）")

    # ---------- 分支 B：whisper ----------
    try:
        audio = download_audio(url, target, nocookie=nocookie,
                               browser=browser, cookies=cookies)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"音频下载失败：{type(e).__name__}: {str(e)[:150]}"
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
        )
    except Exception as e:  # noqa: BLE001
        res["error"] = f"转写失败：{type(e).__name__}: {str(e)[:150]}"
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
            audio.unlink()
            print(f"    已删除音频（keep_audio = false）")
        except OSError:
            pass
    return res


# --------------------------------------------------------------------------- #
# 面板各项
# --------------------------------------------------------------------------- #
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
    res = convert(url, cp=cp, nocookie=False, force_whisper=False,
                  lang=None, model=None, outdir=None, keep_audio=None)
    print()
    print("-" * 64)
    if res["ok"]:
        print(f"  ✓ {res['title']}")
        print(f"    路线：{res['mode']}　条数：{res['segments']}　"
              f"耗时：{res['seconds']:.1f}s")
        print(f"    输出：{res['path']}")
    else:
        print(f"  ✗ 失败：{res['error']}")
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
            results.append((u, convert(u, cp=cp, nocookie=False,
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
            print(f"  ✓ {n:>2}. [{r['mode']}] {r['title']}　"
                  f"{r['segments']} 条　{r['seconds']:.1f}s")
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

        items = sorted(base.glob("*/transcript.txt"),
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
            print(f"  {i:>2}. {p.parent.name[:44]:<46}")
            print(f"      {n_lines:>5} 条　{human(size):>9}　{src:<7} {mtime}")
        print()
        print("     序号    看预览（前 15 条）")
        print("     d 序号  删掉某个（连同音频）")
        print("     回车    返回")
        ans = ask("\n  选择：").strip().lower()
        if not ans:
            return

        m = re.match(r"^d\s*(\d+)$", ans)
        if m:
            idx = int(m.group(1))
            if not (1 <= idx <= len(items)):
                continue
            tgt = items[idx - 1].parent
            if ask(f"  确认删除「{tgt.name}」？ [y/N] ").strip().lower() not in ("y", "yes"):
                continue
            import shutil
            shutil.rmtree(tgt, ignore_errors=True)
            print("  ✓ 已删除。")
            time.sleep(1)
            continue

        if ans.isdigit() and 1 <= int(ans) <= len(items):
            p = items[int(ans) - 1]
            clear()
            print("=" * 64)
            print(f"  {p.parent.name}")
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
    items = list(base.glob("*/transcript.txt")) if base.is_dir() else []
    print(f"    {len(items)} 份　{human(dir_size(base))}")

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
    ("3", "已转写（查看 / 预览 / 删除）"),
    ("4", "重新登录 B站（扫码）"),
    ("5", "环境与模型状态"),
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
        n_done = len(list(base.glob("*/transcript.txt"))) if base.is_dir() else 0
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
    ap.add_argument("--model", default=None, help="whisper 模型名，默认取配置 medium")
    ap.add_argument("--model-dir", default=None, help="本地模型目录")
    ap.add_argument("--device", default=None)
    ap.add_argument("--compute-type", default=None)
    ap.add_argument("--cookies", default=None, help="Netscape cookie 文件")
    ap.add_argument("--no-cookies", action="store_true", help="匿名探测")
    ap.add_argument("--lang", default=None, help="指定字幕语言码，如 ai-zh")
    ap.add_argument("--force-whisper", action="store_true", help="忽略字幕，强制转写")
    ap.add_argument("--keep-audio", dest="keep_audio", action="store_true", default=None)
    ap.add_argument("--drop-audio", dest="keep_audio", action="store_false")
    ap.add_argument("--no-vad", dest="vad", action="store_false", default=None)
    ap.add_argument("--whisper-language", default=None)
    ap.add_argument("--list", action="store_true", help="列出已转写")
    ap.add_argument("--status", action="store_true", help="显示环境与模型状态")
    ap.add_argument("--login", action="store_true", help="扫码登录 B站")
    args = ap.parse_args()

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

    res = convert(
        args.url, cp=cp, nocookie=args.no_cookies,
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
