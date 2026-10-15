"""合集 manifest 的只读索引、完整性校验与安全导出。"""

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile


_MANIFEST = ".video2text-manifest.json"
_LOCK = ".video2text.lock"
_ID = re.compile(r"(?:BV[0-9A-Za-z]+-cid-[1-9][0-9]*|url-[0-9a-f]{32})\Z")


def _selection(collection):
    ids = collection.get("selected_ids", collection.get("episode_ids", []))
    if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
        raise ValueError("合集选择列表损坏")
    if len(ids) != len(set(ids)):
        raise ValueError("合集选择列表含重复 ID")
    return list(ids)


def _load(root):
    path = Path(root) / _MANIFEST
    if path.is_symlink():
        raise ValueError("manifest 不得是符号链接")
    if not path.exists():
        return {"version": 1, "collections": {}, "episodes": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("manifest 无法读取或已损坏") from exc
    if (not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("collections"), dict)
            or not isinstance(state.get("episodes"), dict)):
        raise ValueError("manifest 版本或结构不受支持")
    for collection in state["collections"].values():
        if not isinstance(collection, dict):
            raise ValueError("合集元信息损坏")
        _selection(collection)
    return state


def failed_episode_ids(state, collection_id):
    """返回当前选择中 failed、pending 或缺失条目的 ID，不检查磁盘。"""
    collection = state["collections"][collection_id]
    episodes = state.get("episodes", {})
    return [key for key in _selection(collection)
            if not isinstance(episodes.get(key), dict)
            or episodes[key].get("status") != "success"]


def _safe_name(value):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", str(value or "未命名"))
    text = text.strip(" .")[:100].rstrip(" .") or "未命名"
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", text, re.I):
        text = "_" + text
    return text


def _line(value):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "未命名"))[:300]


def _source(key, entry):
    match = re.fullmatch(r"(BV[0-9A-Za-z]+)-cid-([1-9][0-9]*)", key)
    bvid = entry.get("bvid")
    if not isinstance(bvid, str) or not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        bvid = match.group(1) if match else None
    part = entry.get("part", entry.get("p"))
    part_text = str(part) if type(part) is int and part > 0 else "未知"
    if bvid:
        return f"{bvid} p={part_text}" + (f" cid={match.group(2)}" if match else "")
    return "源平台 ID 未记录（不导出原始 URL）"


def _payload(root, key, entry):
    if not _ID.fullmatch(key):
        return None, "集 ID 非法"
    expected = f"episodes/{key}/transcript.txt"
    if entry.get("path") != expected:
        return None, "产物路径不匹配或越界"
    root = Path(root).resolve()
    target = root / expected
    try:
        if not target.resolve().is_relative_to(root):
            return None, "产物符号链接越界"
        data = target.read_bytes()
    except OSError:
        return None, "产物缺失或不可读"
    digest = entry.get("sha256")
    if not data:
        return None, "产物为空"
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return None, "缺少有效 SHA256，需重新转换"
    if hashlib.sha256(data).hexdigest() != digest.lower():
        return None, "SHA256 校验失败"
    return data, None


def _items(root, state, collection):
    result = []
    for number, key in enumerate(_selection(collection), 1):
        entry = state["episodes"].get(key)
        entry = entry if isinstance(entry, dict) else {}
        status = entry.get("status", "missing")
        data, reason = None, None
        if status == "success":
            data, reason = _payload(root, key, entry)
        else:
            reason = {"failed": "转换失败，需重试", "pending": "尚未完成转换"}.get(status, "条目缺失或状态无效")
        safe_path = f"episodes/{key}/transcript.txt" if _ID.fullmatch(key) else None
        result.append({"id": key, "number": number, "title": _line(entry.get("title") or key),
                       "path": safe_path,
                       "status": status if status in ("success", "failed", "pending") else "missing",
                       "verified": data is not None, "reason": reason,
                       "source": _source(key, entry), "data": data})
    return result


def list_collections(root):
    """读取并验证当前选择的产物；不修改 manifest 或目录。"""
    state = _load(root)
    result = []
    for key, collection in state["collections"].items():
        items = _items(root, state, collection)
        good = sum(item["verified"] for item in items)
        result.append({"id": key, "title": _line(collection.get("title") or key),
                       "selected_ids": _selection(collection), "total": len(items),
                       "success": good, "failed": len(items) - good,
                       "complete": bool(items) and good == len(items),
                       "episodes": [{k: v for k, v in item.items() if k != "data"} for item in items]})
    return result


def export_collection(root, collection_id, destination: Path):
    """以当前选择顺序导出；显式 zip 路径不覆盖，目录下自动避让同名文件。"""
    state = _load(root)
    collection = state["collections"][collection_id]
    items = _items(root, state, collection)
    title = _line(collection.get("title") or collection_id)
    destination = Path(destination)
    directory = destination.is_dir()
    if not directory and destination.suffix.lower() != ".zip":
        raise ValueError("destination 必须是已有目录或 .zip 文件路径")
    count = 1
    while True:
        suffix = "" if count == 1 else f" ({count})"
        path = destination / (_safe_name(title) + suffix + ".zip") if directory else destination
        try:
            stream = path.open("xb")
            break
        except FileExistsError:
            if not directory:
                raise
            count += 1
    failed = [item for item in items if not item["verified"]]
    complete = bool(items) and not failed
    lines = [title, "导出状态：" + ("完整" if complete else "不完整"),
             f"本次选择 {len(items)} 集；已校验 {len(items) - len(failed)} 集；失败 {len(failed)} 集", ""]
    try:
        with stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                number = f"{item['number']:04d}"
                label = "已校验成功" if item["verified"] else "失败：" + item["reason"]
                lines.append(f"{number} | {item['title']} | {item['status']} | {label} | {item['source']}")
                if item["verified"]:
                    archive.writestr(f"{number} {_safe_name(item['title'])}.txt", item["data"])
            archive.writestr("index.txt", "\n".join(lines) + "\n")
            if failed or not items:
                failures = [f"{item['number']:04d} | {_line(item['id'])} | {item['title']} | {item['reason']}"
                            for item in failed]
                archive.writestr("failed.txt", "\n".join(failures or ["当前选择为空，未导出任何集"]) + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "ok": complete, "complete": complete,
            "exported": len(items) - len(failed), "failed": len(failed),
            "failed_ids": [item["id"] for item in failed]}


def _pid_alive(pid):
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError as exc:
        return False if exc.errno == errno.ESRCH else None


def _inspect_lock_path(path):
    result = {"exists": True, "pid": None, "alive": None, "status": "unknown",
              "can_remove": False}
    try:
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
                or not stat.S_ISREG(info.st_mode)):
            return result
        with path.open("r", encoding="ascii") as stream:
            text = stream.read(128).strip()
    except FileNotFoundError:
        result.update(exists=False, status="absent")
        return result
    except (OSError, UnicodeError):
        return result
    if not re.fullmatch(r"[1-9][0-9]{0,9}", text) or int(text) > 0xFFFFFFFF:
        return result
    result["pid"] = int(text)
    try:
        result["alive"] = _pid_alive(result["pid"])
    except (OSError, AttributeError, OverflowError):
        pass
    result["status"] = {True: "alive", False: "dead", None: "unknown"}[result["alive"]]
    return result


def _plain_directory(path):
    try:
        info = path.lstat()
        return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _child_directories(path):
    if not _plain_directory(path):
        return []
    try:
        return sorted((item for item in path.iterdir() if _plain_directory(item)), key=lambda item: item.name)
    except OSError:
        return []


def inspect_lock(root):
    """只读诊断主锁及固定层级音频锁；不跟随链接或自动删除任何锁。"""
    root = Path(root)
    result = _inspect_lock_path(root / _LOCK)
    result["audio_locks"] = []
    if not _plain_directory(root):
        return result
    for episode in _child_directories(root / "episodes"):
        for cache in _child_directories(episode / ".audio-cache"):
            path = cache / ".lock"
            item = _inspect_lock_path(path)
            if item["exists"]:
                item["path"] = path.relative_to(root).as_posix()
                result["audio_locks"].append(item)
    return result
