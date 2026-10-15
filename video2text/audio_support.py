"""身份绑定的原始音频缓存；不导入模型、不执行转码。"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse


def _source(url: str) -> dict:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("音频源必须是无用户信息的 HTTP 链接")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    match = re.fullmatch(r"/video/(BV[0-9A-Za-z]+)/*", parsed.path)
    if parsed.hostname.lower() in ("bilibili.com", "www.bilibili.com", "m.bilibili.com") and match:
        parts = [v for k, v in query if k == "p"]
        if parts and (len(parts) != 1 or not re.fullmatch(r"[0-9]+", parts[0])
                      or int(parts[0]) < 1):
            raise ValueError("音频分P必须是一个正整数")
        part = int(parts[0]) if parts else 1
        bvid = match.group(1)
        return {"url": f"https://www.bilibili.com/video/{bvid}?p={part}",
                "bvid": bvid, "part": part}
    query = [(k, v) for k, v in query
             if not k.startswith("utm_") and k not in ("spm_id_from", "vd_source")]
    return {"url": urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                                           parsed.path, urllib.parse.urlencode(sorted(query)), ""))}


def _guard(root: Path, path: Path) -> Path:
    if not path.is_relative_to(root):
        raise ValueError("音频缓存路径越界")
    for node in (path, *path.parents):
        if node.is_symlink() or (hasattr(node, "is_junction") and node.is_junction()):
            raise ValueError("音频缓存路径包含符号链接或联接")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("音频缓存路径解析后越界")
    return path


def _tree_guard(root: Path, path: Path) -> None:
    _guard(root, path)
    if path.is_dir():
        for child in path.iterdir():
            _guard(root, child)
            if child.is_dir():
                _tree_guard(root, child)


def _read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("音频缓存元数据损坏，拒绝覆盖；请检查缓存目录") from error
    if not isinstance(result, dict):
        raise ValueError("音频缓存元数据必须是对象")
    return result


def _write_json(root: Path, path: Path, value: dict) -> None:
    tmp = _guard(root, path.with_name(path.name + ".tmp"))
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, _guard(root, path))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified(root: Path, ready: Path, source: dict) -> Path:
    _tree_guard(root, ready)
    metadata = _read_json(ready / "cache.json")
    name = metadata.get("file")
    if (metadata.get("version") != 1 or metadata.get("source") != source
            or not isinstance(name, str) or not re.fullmatch(r"audio\.[a-zA-Z0-9]+", name)):
        raise ValueError("音频缓存身份或文件名不匹配，拒绝覆盖")
    audio = _guard(root, ready / name)
    size = metadata.get("size")
    if (type(size) is not int or size <= 0 or not audio.is_file()
            or audio.stat().st_size != size or _digest(audio) != metadata.get("sha256")):
        raise ValueError("音频缓存大小或 SHA256 校验失败，拒绝覆盖")
    return audio


def drop_cached_audio(audio: Path) -> None:
    """仅删除经身份和摘要验证的缓存音频；保留元数据、检查点及未知残片。"""
    audio = Path(os.path.abspath(audio))
    ready = audio.parent
    entry = ready.parent
    cache = entry.parent
    root = cache.parent
    if (ready.name != "ready" or cache.name != ".audio-cache"
            or not re.fullmatch(r"[0-9a-f]{64}", entry.name)):
        raise ValueError("仅允许删除专用缓存 ready 目录内的已验证音频")
    _tree_guard(root, ready)
    metadata = _read_json(ready / "cache.json")
    source = metadata.get("source")
    if (not isinstance(source, dict)
            or hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest() != entry.name):
        raise ValueError("音频缓存源身份与目录不匹配，拒绝删除")
    lock = _guard(root, entry / ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError("音频缓存正在使用，拒绝删除") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(str(os.getpid()) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        verified = _verified(root, ready, source)
        if verified != audio:
            raise ValueError("指定文件不是缓存元数据中的音频，拒绝删除")
        # 先持久化删除意图；中断后仍有音频则继续校验，无音频才隔离重取。
        _write_json(root, ready / "dropped.json",
                    {"version": 1, "source": source, "file": audio.name})
        _guard(root, audio).unlink()
    finally:
        _guard(root, lock).unlink()


def download_audio_cached(url: str, outdir: Path, *, nocookie: bool,
                          browser: str, cookies: str | None) -> Path:
    """复用经源身份、大小和摘要校验的音频，否则在固定暂存目录续传。

    损坏或身份不明的专用缓存会明确拒绝；普通旧 audio.* 始终保留。
    ready 目录原子提交音频和元数据；进程被强杀后的锁需人工检查处理。
    """
    source = _source(url)
    root = Path(os.path.abspath(outdir))
    _guard(root, root)
    root.mkdir(parents=True, exist_ok=True)
    cache = _guard(root, root / ".audio-cache")
    cache.mkdir(exist_ok=True)
    key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    entry = _guard(root, cache / key)
    entry.mkdir(exist_ok=True)
    lock = _guard(root, entry / ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError("音频缓存正被使用或留有中断锁；请先核对正在运行的任务") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(str(os.getpid()) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        ready = _guard(root, entry / "ready")
        if ready.exists():
            try:
                _tree_guard(root, ready)
                dropped = ready / "dropped.json"
                if dropped.exists():
                    marker = _read_json(dropped)
                    name = marker.get("file")
                    if (marker.get("source") != source or marker.get("version") != 1
                            or not isinstance(name, str)
                            or not re.fullmatch(r"audio\.[a-zA-Z0-9]+", name)):
                        raise ValueError("音频删除标记身份不匹配")
                    if not (ready / name).exists():
                        retired = Path(tempfile.mkdtemp(prefix="retired-", dir=entry))
                        # 使用刚创建的独占空目录，保留所有未知残留和检查点。
                        os.rename(ready, retired / "ready")
                    else:
                        return _verified(root, ready, source)
                else:
                    return _verified(root, ready, source)
            except ValueError as error:
                raise ValueError(
                    f"{error}；缓存目录：{entry}。现有文件未覆盖；"
                    "核对后可将此源目录整体移动到 .audio-cache 外备份，再重试下载。"
                ) from error
        staging = _guard(root, entry / "staging")
        binding = staging / "source.json"
        if staging.exists():
            try:
                _tree_guard(root, staging)
                if _read_json(binding) != {"version": 1, "source": source}:
                    raise ValueError("音频暂存身份不匹配，拒绝续传")
            except ValueError as error:
                raise ValueError(
                    f"{error}；缓存目录：{entry}。现有文件未覆盖；"
                    "核对后可将此源目录整体移动到 .audio-cache 外备份，再重试下载。"
                ) from error
        else:
            staging.mkdir()
            _write_json(root, binding, {"version": 1, "source": source})
        opts = {"noplaylist": True, "format": "ba", "continuedl": True,
                "nopart": False, "outtmpl": str(staging / "audio.%(ext)s"),
                "socket_timeout": 30, "retries": 3, "overwrites": False,
                "postprocessors": [], "quiet": True, "no_warnings": True,
                "noprogress": True}
        if not nocookie:
            if cookies:
                opts["cookiefile"] = cookies
            else:
                opts["cookiesfrombrowser"] = (browser,)
        import yt_dlp

        # 下载器会在抛错前输出带签名的请求地址；成功与失败均不回显原始日志。
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source["url"], download=True)
        _tree_guard(root, staging)
        if not isinstance(info, dict) or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError("单集音频返回合集或空元数据，拒绝提升缓存")
        ext = info.get("ext")
        if not isinstance(ext, str) or not re.fullmatch(r"[a-zA-Z0-9]+", ext):
            raise ValueError("下载结果缺少安全的音频扩展名")
        audio = _guard(root, staging / ("audio." + ext))
        if not audio.is_file() or audio.stat().st_size <= 0:
            raise ValueError("下载结果未包含指定格式的非空音频")
        metadata = {"version": 1, "source": source, "file": audio.name,
                    "size": audio.stat().st_size, "sha256": _digest(audio)}
        _write_json(root, staging / "cache.json", metadata)
        # 目录提交使读者不会看见只有音频、没有 sidecar 的半成品。
        os.replace(staging, ready)
        return _verified(root, ready, source)
    finally:
        _guard(root, lock).unlink()
