"""书根PDF只读流、文本层定位及显式授权编辑器调用。"""
import os
import base64
import hashlib
from pathlib import Path
import re
import shutil
import subprocess

from workbench_store import Conflict, HASH, StoreError
from workbench_features import terms
from workbench_daily import registered_tex


def pdf_path(store):
    path = store.path('main.pdf')
    if path != store.book / 'main.pdf':
        raise StoreError('PDF仅允许登记书根main.pdf，不接受链接重定向')
    if not path.is_file():
        return None
    return path


def info(store):
    path = pdf_path(store)
    return {'available': bool(path), 'readonly': True,
            'mtime': path.stat().st_mtime if path else None,
            'notice': 'PDF是独立编译快照，可能与现行源码不同步；定位仅用文本层，不是OCR。' if path else '本书无main.pdf，仅提供源码；不会自动编译。'}


CONTENT_CAP = 64 * 1024 * 1024
CHUNK_SIZE = 65536


def content(store, offset, stamp):
    if not isinstance(offset, str) or not re.fullmatch(r'0|[1-9][0-9]{0,8}', offset):
        raise StoreError('offset须为规范非负整数')
    if not isinstance(stamp, str) or (stamp and not re.fullmatch(r'[a-f0-9]{64}', stamp)):
        raise StoreError('stamp须为空或完整SHA256')
    path = pdf_path(store)
    if path is None:
        raise StoreError('本书无main.pdf')
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        size = stat.st_size
        if size <= 0 or size > CONTENT_CAP:
            raise StoreError('PDF为空或超过64MiB内嵌上限；请自行用本地阅读器查看，不自动下载')
        version = hashlib.sha256(f'{stat.st_mtime_ns}:{size}'.encode()).hexdigest()
        start = int(offset)
        if start >= size or start % CHUNK_SIZE or (start and not stamp):
            raise StoreError('offset越界、未按64KiB对齐或缺少stamp')
        if stamp and stamp != version:
            raise StoreError('PDF已变化，请重新查看')
        stream.seek(start)
        chunk = stream.read(min(CHUNK_SIZE, size - start))
        after = path.stat()
        if len(chunk) != min(CHUNK_SIZE, size - start) or (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, size):
            raise StoreError('PDF读取期间变化，请重新查看')
    return {'offset': start, 'next': start + len(chunk), 'total': size,
            'stamp': version, 'chunk_size': CHUNK_SIZE, 'cap': CONTENT_CAP,
            'data': base64.b64encode(chunk).decode('ascii'), 'readonly': True}


def byte_range(value, size):
    if value is None:
        return (0, size - 1, 200)
    if len(value) > 80:
        raise StoreError('Range不可满足')
    match = re.fullmatch(r'bytes=([0-9]*)-([0-9]*)', value)
    if not match or not any(match.groups()) or size == 0:
        raise StoreError('Range不可满足')
    left, right = match.groups()
    if not left:
        count = int(right)
        if count == 0:
            raise StoreError('Range不可满足')
        return max(0, size - count), size - 1, 206
    start = int(left)
    end = min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise StoreError('Range不可满足')
    return start, end, 206


def serve(handler, store):
    path = pdf_path(store)
    if path is None:
        return handler.reply(404, {'error': '本书无main.pdf，仅提供源码'})
    with path.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        try:
            ranges = handler.headers.get_all('Range') or []
            if len(ranges) > 1:
                raise StoreError('多个Range不支持')
            start, end, status = byte_range(ranges[0] if ranges else None, size)
        except StoreError:
            handler.send_response(416)
            handler.send_header('Content-Range', 'bytes */' + str(size))
            handler.send_header('Content-Length', '0')
            handler.send_header('Accept-Ranges', 'bytes')
            handler.send_header('X-Content-Type-Options', 'nosniff')
            handler.send_header('Cache-Control', 'no-store')
            handler.send_header('Connection', 'close')
            handler.end_headers()
            handler.close_connection = True
            return
        count = max(0, end - start + 1)
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/pdf')
        handler.send_header('Content-Length', str(count))
        handler.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'self'")
        handler.send_header('Connection', 'close')
        handler.end_headers()
        stream.seek(start)
        while count:
            chunk = stream.read(min(count, 65536))
            if not chunk:
                break
            handler.wfile.write(chunk)
            count -= len(chunk)
        handler.close_connection = True


def executable(explicit, kind):
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() not in {'.exe', ''}:
            raise StoreError('可执行配置须为现有绝对exe路径')
        return str(path.resolve())
    found = shutil.which(kind)
    candidates = ([found] if found else []) + ([
        'C:/texlive/2025/bin/windows/pdftotext.exe', 'C:/texlive/2024/bin/windows/pdftotext.exe'
    ] if kind == 'pdftotext' else ['C:/Program Files/texstudio/texstudio.exe', 'C:/Program Files (x86)/texstudio/texstudio.exe'])
    return next((str(Path(p).resolve()) for p in candidates if Path(p).is_file()), None)


def locate(store, query):
    words = [re.sub(r'\s+', '', w) for w in terms(query)]
    path = pdf_path(store)
    result = info(store) | {'pages': [], 'runs': [], 'first': 0, 'matched': False}
    if path is not None and path.stat().st_size > 256 * 1024 * 1024:
        return result | {'notice': 'PDF超过256MiB定位上限，仅流式浏览/源码；不自动抽取。'}
    if path is None:
        return result
    exe = executable(None, 'pdftotext')
    if not exe:
        return result | {'notice': '未找到pdftotext；仅提供PDF浏览和源码，不是OCR。'}
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    try:
        proc = subprocess.run([exe, '-enc', 'UTF-8', '-layout', str(path), '-'], capture_output=True, timeout=30, shell=False)
        if proc.returncode != 0 or len(proc.stdout) > 32 * 1024 * 1024:
            return result | {'notice': 'PDF文本提取失败或超限；仅提供浏览/源码，不是OCR。'}
        if stamp != (path.stat().st_mtime_ns, path.stat().st_size):
            return result | {'notice': 'PDF在定位期间变化，请重试；未采用旧页码。'}
        pages = proc.stdout.decode('utf-8', errors='replace').split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        hits = [i + 1 for i, page in enumerate(pages) if all(w in re.sub(r'\s+', '', page).lower() for w in words)]
        runs = []
        for page in hits:
            if runs and runs[-1][1] + 1 == page:
                runs[-1][1] = page
            else:
                runs.append([page, page])
        best = max(runs, key=lambda r: (r[1] - r[0], -r[0])) if runs else [0, 0]
        return result | {'pages': hits[:100], 'pages_total': len(hits), 'runs': runs[:40], 'first': best[0], 'total': len(pages), 'matched': bool(hits)}
    except (OSError, subprocess.SubprocessError):
        return result | {'notice': 'pdftotext失败或超时；仅提供PDF浏览/源码，不是OCR。'}


def open_tex(server, store, uid, confirm, line=None, selected_path=None, expected=None):
    with server.open_lock:
        return _open_tex(server, store, uid, confirm, line, selected_path, expected)


def _open_tex(server, store, uid, confirm, line, selected_path, expected):
    if confirm is not True:
        raise StoreError('必须confirm:true明确确认打开')
    if not server.allow_open:
        raise StoreError('OS打开未授权')
    unit, path = registered_tex(store, uid)
    if line is not None:
        if not isinstance(expected, str) or not HASH.fullmatch(expected):
            raise StoreError('搜索定位须提供完整expected SHA256，请重新搜索')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise Conflict('搜索命中源码已变化，请重新搜索；未调用TeXstudio')
        if type(line) is not int or not 1 <= line <= len(raw.decode('utf-8-sig').splitlines()):
            raise StoreError('搜索命中行号越界')
        if selected_path != unit['tex_path']:
            raise StoreError('搜索目标与登记路径不符')
    exe = executable(server.texstudio, 'texstudio')
    if not exe:
        return {'opened': False, 'notice': '未找到TeXstudio；请显式配置--texstudio，未调用OS。'}
    try:
        # TeXstudio随附background.html记录--line xx[:cc]；参数分离，不使用shell。
        subprocess.Popen([exe, *(['--line', str(line)] if line is not None else []), str(path)], shell=False)
    except OSError as exc:
        raise StoreError('TeXstudio启动失败；请核对--texstudio路径及本机执行权限，未确认打开成功') from exc
    return {'opened': True, 'line_requested': line, 'line_located': False,
            'notice': '已提交TeXstudio打开请求' + ('及--line ' + str(line) + '行定位参数（随附文档已核验；不保证编辑器已完成定位）' if line is not None else '（当前审核单位，仅打开文件）') + '；不自动编译或保存。'}
