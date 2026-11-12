"""日常只读检测：元数据签名与保守静态输入链，不运行TeX。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from workbench_store import StoreError


def now():
    return datetime.now(timezone.utc).isoformat()


class Changes:
    def __init__(self, root, discover, ttl=3):
        self.root, self.discover, self.ttl = root, discover, ttl
        self.lock = threading.Lock()
        self.deadline = 0
        self.books = {}
        self.history = {}
        self.scans = 0
        self.checked_at = None

    def read(self, since='{}', force=False):
        if not isinstance(force, bool):
            raise StoreError('force须为布尔值')
        try:
            versions = json.loads(since)
        except (ValueError, TypeError) as exc:
            raise StoreError('since须为书名到版本的JSON对象') from exc
        if not isinstance(versions, dict) or len(versions) > 100 or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 64 for k, v in versions.items()):
            raise StoreError('since版本格式无效')
        with self.lock:
            cached = not force and time.monotonic() < self.deadline
            if not cached:
                fresh, histories = {}, {}
                checked_at = now()

                def failed(exc):
                    raise StoreError('变化扫描失败：' + str(exc)) from exc

                def safe(path, boundary):
                    resolved = path.resolve()
                    if not resolved.is_relative_to(boundary):
                        raise StoreError('变化扫描路径越界：' + str(path))
                    metadata = path.lstat()
                    return not (stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400)

                try:
                    root = Path(self.root).resolve()
                    shelf = root / 'LaTeX_Notes' if (root / 'LaTeX_Notes').is_dir() else root
                    if not safe(shelf, root):
                        raise StoreError('变化扫描书架入口为链接：' + str(shelf))
                    shelf = shelf.resolve()
                    for book in self.discover(self.root):
                        book = Path(book)
                        if not safe(book, shelf):
                            continue
                        book = book.resolve()
                        if book == shelf:
                            raise StoreError('变化扫描书目录不能是书架根')
                        entries = {}
                        for folder, dirs, files in os.walk(book, followlinks=False, onerror=failed):
                            folder = Path(folder)
                            if not safe(folder, book):
                                raise StoreError('变化扫描目录变为链接：' + str(folder))
                            kept = []
                            for name in dirs:
                                path = folder / name
                                allowed = safe(path, book)
                                if allowed and not name.startswith('.') and name.lower() not in {'backups', 'backup', '__pycache__', '_backup'}:
                                    kept.append(name)
                            dirs[:] = kept
                            for name in files:
                                path = folder / name
                                if not safe(path, book) or name.startswith(('.', '~')):
                                    continue
                                rel = path.relative_to(book).as_posix()
                                if not (path.suffix.lower() == '.tex' or path.suffix.lower() == '.md' and (rel.startswith('Materials/') or rel in {'Source.md', 'README.md'} or name.endswith('_Content.md')) or rel in {'main.pdf', 'Materials/workbench/runtime.json', 'Materials/workbench/book.json'}):
                                    continue
                                st = path.stat(follow_symlinks=False)
                                if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
                                    raise StoreError('变化扫描文件变为链接：' + str(path))
                                entries[rel] = (st.st_mtime_ns, st.st_size)
                        version = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
                        history = dict(self.history.get(book.name, {}))
                        history.pop(version, None)
                        history[version] = entries
                        while len(history) > 16:
                            del history[next(iter(history))]
                        histories[book.name] = history
                        fresh[book.name] = {'name': book.name, 'version': version, 'checked_at': checked_at, 'file_count': len(entries), 'latest_mtime': max((v[0] for v in entries.values()), default=0) / 1e9}
                except (OSError, RuntimeError) as exc:
                    failed(exc)
                self.books, self.history = fresh, histories
                self.checked_at = checked_at
                self.scans += 1
                self.deadline = time.monotonic() + self.ttl
            result = []
            for name, info in self.books.items():
                old = self.history[name].get(versions.get(name))
                current = self.history[name][info['version']]
                different = name in versions and versions[name] != info['version']
                result.append(info | {'changed': different, 'comparison_available': old is not None,
                    'added': sorted(current.keys() - old.keys()) if old is not None else [],
                    'deleted': sorted(old.keys() - current.keys()) if old is not None else [],
                    'modified': sorted(k for k in current.keys() & old.keys() if current[k] != old[k]) if old is not None else []})
            return {'books': result, 'removed_books': sorted(versions.keys() - self.books.keys()),
                    'added_books': sorted(self.books.keys() - versions.keys()) if versions else [],
                    'checked_at': self.checked_at, 'cached': cached, 'response_at': now(), 'ttl_seconds': self.ttl,
                    'method': 'stat元数据签名（路径、mtime_ns、大小）；不是内容hash或审核，保留最近16个版本用于差异比较'}


def uncomment(text):
    return '\n'.join(re.split(r'(?<!\\)%', line, maxsplit=1)[0] for line in text.splitlines())


TOKEN = re.compile(r'\\(includeonly|input|include|if[a-zA-Z@]*|else|fi)\b')


def tokens(text):
    offset = 0
    while match := TOKEN.search(text, offset):
        command = match[1]
        offset = match.end()
        if command not in {'input', 'include', 'includeonly'}:
            yield None, None, command, None
            continue
        start = offset
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text) or text[start] != '{':
            yield None, None, None, command
            continue
        depth, end = 1, start + 1
        while end < len(text) and depth:
            if text[end] == '\\':
                end += 2
                continue
            if text[end] == '{':
                depth += 1
            elif text[end] == '}':
                depth -= 1
            end += 1
        if depth:
            yield None, None, None, command
            offset = len(text)
        else:
            yield command, text[start + 1:end - 1], None, None
            offset = end


def registered_tex(store, uid):
    import workbench_readonly as ro
    if not isinstance(uid, str):
        raise StoreError('unit须为字符串')
    selected = []
    for entry in store.book.glob('*_Content.md'):
        rows = ro.bindings(store.path(entry.name))
        if rows:
            selected.append(rows)
    if len(selected) != 1:
        raise StoreError('登记入口不唯一')
    units, paths = {}, set()
    for display, tex, material, _ in selected[0]:
        local = ro.local_id(display)
        if not local or local in units or tex in paths or material != 'Materials/' + local:
            raise StoreError('登记编号或绑定冲突')
        path = store.path(tex)
        if path.suffix.lower() != '.tex' or not path.is_file() or not store.path(material).is_dir():
            raise StoreError('仅允许同书登记TeX文件')
        units[local] = ({'id': local, 'tex_path': tex}, path)
        paths.add(tex)
    if uid not in units:
        raise StoreError('单位未登记')
    return units[uid]


def participation(store, uid):
    unit, target = registered_tex(store, uid)
    wanted = target.relative_to(store.book).as_posix()
    seen, chains, reasons, visiting = set(), {}, [], set()
    includeonly = None

    def walk(rel, chain, uncertain=False):
        nonlocal includeonly
        if rel in visiting:
            reasons.append('输入链循环：' + rel)
            return
        if len(seen) > 2000 or len(chain) > 60:
            reasons.append('输入链超出静态解析上限')
            return
        try:
            path = store.path(rel)
            if path.suffix.lower() != '.tex' or not path.is_file():
                reasons.append('缺少输入目标：' + rel)
                return
            text = uncomment(path.read_bytes().decode('utf-8-sig'))
        except (StoreError, OSError, UnicodeError):
            reasons.append('目标不可静态读取：' + rel)
            return
        seen.add(rel)
        chains.setdefault(rel, (chain + [rel], uncertain))
        visiting.add(rel)
        depth = 0
        if re.search(r'\\(?:def|edef|gdef|newcommand|renewcommand|let|csname|catcode|endinput|begin\s*\{(?:comment|verbatim|filecontents))\b', text):
            uncertain = True
            reasons.append('含宏定义、特殊环境或控制语义：' + rel)
        for cmd, value, cond, bare in tokens(text):
            if cond:
                if cond.startswith('if'):
                    depth += 1
                elif cond == 'fi':
                    depth = max(0, depth - 1)
                reasons.append('条件分支待核实：' + rel)
                continue
            if bare:
                reasons.append('未解析的输入语法：' + rel)
                continue
            if cmd == 'includeonly':
                if depth or uncertain or '\\' in value:
                    reasons.append('includeonly待核实：' + rel)
                else:
                    includeonly = {v.strip().removesuffix('.tex') for v in value.split(',')}
                continue
            if '\\' in value or '#' in value or not value.strip():
                reasons.append('宏输入目标待核实：' + rel)
                continue
            name = value.strip()
            if cmd == 'include' and includeonly is not None and name.removesuffix('.tex') not in includeonly:
                continue
            if not name.endswith('.tex'):
                name += '.tex'
            # TeX通常相对编译工作目录；书根与当前文件目录都有候选时不猜测。
            candidates = list(dict.fromkeys([name, (path.parent.relative_to(store.book) / name).as_posix()]))
            valid = []
            root_valid = False
            for candidate in candidates:
                try:
                    p = store.path(candidate)
                    if p.is_file() and p.suffix.lower() == '.tex':
                        valid.append(p.relative_to(store.book).as_posix())
                        if candidate == name:
                            root_valid = True
                except StoreError:
                    reasons.append('输入目标越界：' + candidate)
            if len(set(valid)) != 1:
                reasons.append('缺失或歧义输入目标：' + name)
                continue
            fallback = not root_valid
            if fallback:
                reasons.append('仅父目录候选命中，编译工作目录待核实：' + name)
            walk(valid[0], chain + [rel], uncertain or depth > 0 or fallback)
        visiting.remove(rel)

    walk('main.tex', [])
    chain, uncertain = chains.get(wanted, ([], False))
    status = 'unknown' if uncertain or reasons else ('seen' if wanted in seen else 'unseen')
    source_mtime = max((store.path(p).stat().st_mtime for p in seen), default=target.stat().st_mtime)
    source_mtime = max(source_mtime, target.stat().st_mtime)
    pdf = store.path('main.pdf')
    pdf_time = pdf.stat().st_mtime if pdf.is_file() else None
    return {'book': store.book.name, 'unit': uid, 'path': unit['tex_path'], 'absolute_path': str(target),
            'status': status, 'static_chain_seen': wanted in seen, 'chain': chain, 'reasons': list(dict.fromkeys(reasons))[:30],
            'source_mtime': source_mtime, 'pdf_mtime': pdf_time, 'pdf_may_be_stale': pdf_time is None or source_mtime > pdf_time,
            'notice': {'seen': '已见静态输入链；不保证TeX所有执行分支激活', 'unseen': '当前静态输入链未见；不等于文件不可打开', 'unknown': '待核实：存在静态解析无法确认的语义'}[status] + '；不自动启用章节或编译。'}
