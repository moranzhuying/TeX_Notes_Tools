"""将已校验的内部转写产物物化为按标题组织的只读副本。"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


_MANIFEST = ".video2text-manifest.json"
_INDEX = ".title-layout.json"
_LOCK = ".video2text.lock"
_ID = re.compile(r"(?:BV[0-9A-Za-z]+-cid-[1-9][0-9]*|url-[0-9a-f]{32})\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)


def _plain(path, directory=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"拒绝符号链接或重解析点：{path}")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise ValueError(f"文件类型不符合预期：{path}")
    return True


def _read_json(path):
    if not _plain(path):
        raise ValueError(f"缺少文件：{path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"文件已损坏：{path.name}") from exc


def _name(title, fallback):
    if not isinstance(title, str) or not title.strip():
        title = fallback
    text = _INVALID.sub("_", title).strip(" .")[:100].rstrip(" .") or "未命名"
    return "_" + text if _RESERVED.fullmatch(text) else text


def _suffix(identifier):
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12]


def _unique_names(titles, extensions=""):
    stems = {key: _name(title, key) for key, title in titles.items()}
    groups = {}
    for key, stem in stems.items():
        groups.setdefault((stem + extensions).casefold(), []).append(key)
    result = {}
    for key, stem in stems.items():
        if len(groups[(stem + extensions).casefold()]) > 1:
            stem = stem[:86].rstrip(" .") + "--" + _suffix(key)
        result[key] = stem + extensions
    return result


def _atomic_bytes(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".title-layout-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_index(root):
    path = root / _INDEX
    if not path.exists() and not path.is_symlink():
        return {"version": 1, "directories": {}, "history": {}, "files": {}}
    state = _read_json(path)
    if (not isinstance(state, dict) or type(state.get("version")) is not int
            or state["version"] != 1 or not isinstance(state.get("directories"), dict)
            or not isinstance(state.get("files"), dict)):
        raise ValueError("标题视图索引结构损坏")
    history = state.setdefault("history", {})
    if not isinstance(history, dict):
        raise ValueError("标题视图历史索引损坏")
    for cid, names in history.items():
        if (not isinstance(cid, str) or not isinstance(names, list)
                or any(not isinstance(name, str) or name in ("", ".", "..")
                       or name != _name(name, name) for name in names)):
            raise ValueError("标题视图历史目录索引损坏")
    for cid, name in state["directories"].items():
        if (not isinstance(cid, str) or not isinstance(name, str)
                or name in ("", ".", "..") or name != _name(name, name)):
            raise ValueError("标题视图目录索引损坏")
    for relative, entry in state["files"].items():
        if (not isinstance(relative, str) or len(relative.split("/")) != 2
                or relative.split("/")[0] in ("", ".", "..")
                or relative.split("/")[0] != _name(relative.split("/")[0], "目录")
                or not relative.endswith(".txt") or not relative.split("/")[1][:-4]
                or relative.split("/")[1][:-4] != _name(relative.split("/")[1][:-4], "文件")
                or not isinstance(entry, dict)
                or not isinstance(entry.get("episode_id"), str)
                or not isinstance(entry.get("sha256"), str)
                or not _HASH.fullmatch(entry["sha256"])
                or (entry.get("previous_sha256") is not None
                    and (not isinstance(entry["previous_sha256"], str)
                         or not _HASH.fullmatch(entry["previous_sha256"])))):
            raise ValueError("标题视图文件索引损坏")
    return state


def _verified_items(root, state, selected):
    verified, failed = {}, []
    for key in selected:
        entry = state["episodes"].get(key)
        if not _ID.fullmatch(key) or not isinstance(entry, dict):
            raise ValueError("合集含未知或非法集 ID")
        status = entry.get("status")
        if status in ("failed", "pending"):
            failed.append(key)
            continue
        if status != "success" or entry.get("path") != f"episodes/{key}/transcript.txt":
            raise ValueError("集状态或产物路径损坏")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ValueError("集 SHA256 非法")
        episodes = root / "episodes"
        _plain(episodes, directory=True)
        _plain(episodes / key, directory=True)
        target = episodes / key / "transcript.txt"
        if not _plain(target):
            raise ValueError("集转写产物缺失")
        data = target.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("集转写产物为空或 SHA256 不匹配")
        header = data[:8192].decode("utf-8-sig", errors="replace")
        title = next((line[len("# 标题："):].strip() for line in header.splitlines()[:8]
                      if line.startswith("# 标题：") and line[len("# 标题："):].strip()), None)
        verified[key] = (title or entry.get("title"), data, digest)
    return verified, failed


def _check_destination(root, directory, plans, index, collection_id):
    existing = {}
    for item in root.iterdir():
        folded = item.name.casefold()
        if folded in existing:
            raise FileExistsError(f"根目录存在大小写碰撞：{item}")
        existing[folded] = item
    old = index["directories"].get(collection_id)
    found = existing.get(directory.casefold())
    if found is not None:
        if found.name != directory or old != directory:
            raise FileExistsError(f"未登记或大小写冲突的标题目录：{found}")
        _plain(found, directory=True)
    elif old == directory:
        # 已登记但用户删除了目录：可以重新生成，不删除旧索引。
        pass
    if found is None:
        return
    children = {}
    for item in found.iterdir():
        folded = item.name.casefold()
        if folded in children:
            raise FileExistsError(f"已有大小写碰撞的文件：{item}")
        children[folded] = item
    for filename, key, _, _ in plans:
        prior = children.get(filename.casefold())
        if prior is None:
            continue
        relative = directory + "/" + filename
        managed = index["files"].get(relative)
        if (prior.name != filename or not isinstance(managed, dict)
                or managed["episode_id"] != key):
            raise FileExistsError(f"未登记或大小写冲突的转写文件：{prior}")
        _plain(prior)
        actual = hashlib.sha256(prior.read_bytes()).hexdigest()
        if actual != managed["sha256"] and actual != managed.get("previous_sha256"):
            raise ValueError(f"已登记转写文件被外部修改：{prior}")


def materialize_collection(root, collection_id, *, overwrite_managed=True, lock_held=False):
    """写入标题视图；状态失败的集跳过，损坏的成功集使操作整体失败。"""
    root = Path(root)
    if not _plain(root, directory=True):
        raise ValueError("输出根目录不存在")
    lock = root / _LOCK
    acquired = False
    try:
        if not lock_held:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise RuntimeError("转写或标题视图正在进行，或存在未处理锁") from exc
            acquired = True
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(str(os.getpid()))
        state = _read_json(root / _MANIFEST)
        if (not isinstance(state, dict) or type(state.get("version")) is not int
                or state["version"] != 1 or not isinstance(state.get("collections"), dict)
                or not isinstance(state.get("episodes"), dict)):
            raise ValueError("manifest 结构损坏")
        collections = state["collections"]
        if collection_id not in collections or not isinstance(collections[collection_id], dict):
            raise ValueError("合集不存在或结构损坏")
        for collection in collections.values():
            if not isinstance(collection, dict) or not isinstance(collection.get("selected_ids"), list):
                raise ValueError("合集选择列表损坏")
            selected = collection["selected_ids"]
            if any(not isinstance(key, str) for key in selected) or len(set(selected)) != len(selected):
                raise ValueError("合集选择列表含非法或重复 ID")
        index = _load_index(root)
        for name in index["directories"].values():
            target = root / name
            if target.exists() or target.is_symlink():
                _plain(target, directory=True)
        for relative, record in index["files"].items():
            folder, filename = relative.split("/")
            parent = root / folder
            if parent.exists() or parent.is_symlink():
                _plain(parent, directory=True)
                target = parent / filename
                if target.exists() or target.is_symlink():
                    _plain(target)
                    actual = hashlib.sha256(target.read_bytes()).hexdigest()
                    if actual not in (record["sha256"], record.get("previous_sha256")):
                        raise ValueError(f"已登记转写文件被外部修改：{target}")
        directories = _unique_names({key: collection.get("title") for key, collection in collections.items()})
        if len({name.casefold() for name in directories.values()}) != len(directories):
            raise ValueError("合集目录名称碰撞")
        directory = directories[collection_id]
        selected = collections[collection_id]["selected_ids"]
        verified, failed = _verified_items(root, state, selected)
        filenames = _unique_names({key: (verified[key][0] if key in verified else state["episodes"][key].get("title"))
                                   for key in selected}, ".txt")
        width = max(2, len(str(len(selected))))
        plans = [((filenames[key] if len(selected) == 1 else
                   f"{number:0{width}d} {filenames[key][:-4][:95 - width].rstrip(' .')}.txt"),
                  key, verified[key][1], verified[key][2])
                 for number, key in enumerate(selected, 1) if key in verified]
        _check_destination(root, directory, plans, index, collection_id)
        target_dir = root / directory
        if not overwrite_managed:
            for filename, _, _, digest in plans:
                target = target_dir / filename
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise FileExistsError(f"不允许更新已登记文件：{target}")
        if not target_dir.exists():
            target_dir.mkdir()
        prior_directory = index["directories"].get(collection_id)
        if prior_directory and prior_directory != directory:
            index["history"].setdefault(collection_id, [])
            if prior_directory not in index["history"][collection_id]:
                index["history"][collection_id].append(prior_directory)
        index["directories"][collection_id] = directory
        written = skipped = 0
        for filename, key, data, digest in plans:
            target = target_dir / filename
            relative = directory + "/" + filename
            previous = index["files"].get(relative)
            actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
            if actual == digest:
                skipped += 1
            else:
                index["files"][relative] = {"episode_id": key, "sha256": digest}
                if actual is not None:
                    index["files"][relative]["previous_sha256"] = previous["sha256"]
                _atomic_bytes(root / _INDEX, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                _atomic_bytes(target, data)
                written += 1
            index["files"][relative] = {"episode_id": key, "sha256": digest}
        index["directories"][collection_id] = directory
        _atomic_bytes(root / _INDEX, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        current = {directory + "/" + filename for filename, _, _, _ in plans}
        owned = set(index["history"].get(collection_id, [])) | {directory}
        stale = sorted(relative for relative in index["files"]
                       if relative not in current and relative.split("/")[0] in owned)
        return {"directory": str(target_dir), "written": written, "skipped": skipped,
                "failed": len(failed), "failed_ids": failed, "stale": stale}
    finally:
        if acquired:
            lock.unlink()
