"""将已有分P转写原文安全登记到 video2text 的稳定 CID 索引。"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import parse_qs, urlsplit


_BVID = re.compile(r"BV[0-9A-Za-z]+\Z")
_TIMESTAMP = re.compile(r"(?m)^\[\d{1,3}:\d{2}(?::\d{2})?(?:\.\d+)?\]\s*\S")
_MANIFEST = ".video2text-manifest.json"
_LOCK = ".video2text.lock"


def _plain(path, *, directory=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError("拒绝链接、重解析点或错误文件类型")
    return True


def _atomic_json(path, state):
    fd, temp = tempfile.mkstemp(prefix=".legacy-import-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _url_part(url, bvid):
    if not isinstance(url, str):
        raise ValueError("历史 URL 缺失")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in ("www.bilibili.com", "bilibili.com")
            or parts.username or parts.password or parts.port
            or parts.path not in (f"/video/{bvid}", f"/video/{bvid}/") or parts.fragment):
        raise ValueError("历史 URL 与公开视频身份不匹配")
    query = parse_qs(parts.query, strict_parsing=True)
    if set(query) != {"p"} or len(query["p"]) != 1 or not re.fullmatch(r"[1-9][0-9]*", query["p"][0]):
        raise ValueError("历史 URL 缺少唯一合法 p 参数")
    return int(query["p"][0])


def _source(path_value, parent):
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("历史原文路径非法")
    path = Path(path_value)
    if not path.is_absolute():
        path = parent / path
    path = Path(os.path.abspath(path))
    if not _plain(path):
        raise ValueError("历史原文缺失")
    if not _plain(parent, directory=True) or not path.resolve().is_relative_to(parent.resolve()):
        raise ValueError("历史原文必须位于 progress.json 目录内")
    current = path.parent
    parent = Path(os.path.abspath(parent))
    while current != parent:
        if not _plain(current, directory=True):
            raise ValueError("历史原文目录不得含链接或重解析点")
        current = current.parent
    data = path.read_bytes()
    if not data:
        raise ValueError("历史原文为空")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("历史原文不是 UTF-8") from exc
    lines = text.splitlines()[:8]
    if not any(line.startswith("# 标题：") and line.partition("：")[2].strip() for line in lines):
        raise ValueError("历史原文缺少标题")
    if not _TIMESTAMP.search(text):
        raise ValueError("历史原文缺少带正文的时间戳")
    return data


def _view(view_data):
    if not isinstance(view_data, dict) or not isinstance(view_data.get("bvid"), str) or not _BVID.fullmatch(view_data["bvid"]):
        raise ValueError("公开 view 缺少有效 BV")
    bvid = view_data["bvid"]
    pages = view_data.get("pages")
    if not isinstance(pages, list) or len(pages) != 52:
        raise ValueError("公开 view 必须精确包含 52 个分P")
    cids = set()
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or type(page.get("page")) is not int or page["page"] != number
                or type(page.get("cid")) is not int or page["cid"] <= 0
                or page["cid"] in cids or not isinstance(page.get("part"), str)
                or not page["part"].strip()):
            raise ValueError("公开 view 分P序号、CID 或标题非法")
        cids.add(page["cid"])
    return bvid, pages


def import_bili_parts(root: Path, progress_file: Path, view_data: dict, *, collection_title=None) -> dict:
    """完整校验旧进度及公开 view，保留旧原件，以非覆盖写入新产物。"""
    root, progress_file = Path(os.path.abspath(root)), Path(os.path.abspath(progress_file))
    if not _plain(root, directory=True) or not _plain(progress_file.parent, directory=True) or not _plain(progress_file):
        raise ValueError("输入目录、进度文件或输出根目录不存在或不安全")
    if (root.resolve().is_relative_to(progress_file.parent.resolve())
            or progress_file.parent.resolve().is_relative_to(root.resolve())):
        raise ValueError("内部目标与历史原文目录不得互相包含")
    bvid, pages = _view(view_data)
    if collection_title is None:
        collection_title = view_data.get("title")
    if not isinstance(collection_title, str) or not collection_title.strip():
        raise ValueError("合集标题为空")
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    records = _records(progress)
    if len(records) != len(pages):
        raise ValueError("历史记录数与公开视频分P数不一致")
    plans = []
    paths = set()
    for number, (part, record) in enumerate(records, 1):
        url, source_path = _record_fields(record)
        if type(part) is not int or part != number or _url_part(url, bvid) != number:
            raise ValueError("历史进度分P不连续或与 URL 不匹配")
        source = Path(source_path)
        canonical = source if source.is_absolute() else progress_file.parent / source
        folded = str(Path(os.path.abspath(canonical))).casefold()
        if folded in paths:
            raise ValueError("历史原文路径重复")
        paths.add(folded)
        data = _source(source_path, progress_file.parent)
        page = pages[number - 1]
        key = f"{bvid}-cid-{page['cid']}"
        plans.append((key, number, record["title"], data, hashlib.sha256(data).hexdigest()))
    lock = root / _LOCK
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("其他转写或导入正在运行，或存在未处理锁") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
        return _import_locked(root, bvid, collection_title.strip(), plans)
    finally:
        lock.unlink()


def _records(progress):
    if (not isinstance(progress, dict) or len(progress) != 52
            or set(progress) != {str(number) for number in range(1, 53)}):
        raise ValueError("历史进度必须精确含 1 至 52 的连续 P 序号")
    return [(number, progress[str(number)]) for number in range(1, 53)]


def _record_fields(record):
    if (not isinstance(record, dict) or record.get("ok") is not True
            or not isinstance(record.get("title"), str) or not record["title"].strip()
            or not isinstance(record.get("path"), str)):
        raise ValueError("历史分P并非已完成且含标题和原文路径")
    return record.get("url"), record["path"]


def _import_locked(root, bvid, title, plans):
    manifest = root / _MANIFEST
    if _plain(manifest):
        original = manifest.read_bytes()
        try:
            state = json.loads(original)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("现有 manifest 已损坏") from exc
    else:
        if manifest.is_symlink():
            raise ValueError("manifest 不得是链接")
        original = None
        state = {"version": 1, "collections": {}, "episodes": {}}
    if (not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1
            or not isinstance(state.get("collections"), dict) or not isinstance(state.get("episodes"), dict)):
        raise ValueError("现有 manifest 结构非法")
    directory = root / "episodes"
    if (directory.exists() or directory.is_symlink()) and not _plain(directory, directory=True):
        raise ValueError("内部 episodes 目录不安全")
    for key, _, _, data, digest in plans:
        folder = directory / key
        target = folder / "transcript.txt"
        if (folder.exists() or folder.is_symlink()) and not _plain(folder, directory=True):
            raise ValueError("现有分P目录不安全")
        if (target.exists() or target.is_symlink()) and (not _plain(target) or hashlib.sha256(target.read_bytes()).hexdigest() != digest):
            raise ValueError("现有转写文件内容与历史原文冲突")
        existing = state["episodes"].get(key)
        if existing is not None and (not isinstance(existing, dict) or existing.get("status") != "success"
                                     or existing.get("path") != f"episodes/{key}/transcript.txt"
                                     or existing.get("sha256") != digest or not target.exists()):
            raise ValueError("已有集索引与历史原文冲突")
    collection_id = "bili-video-" + bvid
    old = state["collections"].get(collection_id)
    keys = [item[0] for item in plans]
    if old is not None and (not isinstance(old, dict)
                            or old.get("selected_ids", old.get("episode_ids")) != keys
                            or old.get("episode_ids") != keys):
        raise ValueError("同 BV 已有合集选择不同，拒绝修改")
    if old is not None and all(key in state["episodes"] for key in keys):
        return {"collection_id": collection_id, "total": len(plans), "written": 0,
                "skipped": len(plans), "snapshot": None}
    written = skipped = 0
    for key, part, public_title, data, digest in plans:
        folder = directory / key
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "transcript.txt"
        if target.exists() or target.is_symlink():
            if not _plain(target) or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("写入期间转写文件发生冲突")
            skipped += 1
        else:
            try:
                with target.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            written += 1
        state["episodes"].setdefault(key, {"id": key, "bvid": bvid,
                                           "cid": int(key.rsplit("-cid-", 1)[1]), "part": part,
                                           "title": public_title, "path": f"episodes/{key}/transcript.txt",
                                           "status": "success", "sha256": digest, "size": len(data),
                                           "mode": "legacy-import"})
    if old is None:
        state["collections"][collection_id] = {"title": title, "episode_ids": keys, "selected_ids": keys}
    if original is not None:
        snapshot = root / (".video2text-manifest.pre-legacy-import-"
                           + hashlib.sha256(original).hexdigest() + ".json")
        if snapshot.exists() or snapshot.is_symlink():
            if not _plain(snapshot) or snapshot.read_bytes() != original:
                raise ValueError("已有快照内容不一致；请先人工检查")
        else:
            with snapshot.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
    _atomic_json(manifest, state)
    return {"collection_id": collection_id, "total": len(plans), "written": written,
            "skipped": skipped, "snapshot": str(snapshot) if original is not None else None}
