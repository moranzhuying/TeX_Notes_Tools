"""普通独立前台Edge、有界独立/嵌入/显式备用PDF验收；不写真实笔记，不启动TeXstudio。"""
import base64
import builtins
import ctypes
from ctypes import wintypes
import struct
import zlib
import importlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import hashlib
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from playwright.sync_api import sync_playwright
from test_clean_ui_acceptance import RejectOld, hashes, OLD

WS = Path(__file__).resolve().parents[3]
PRODUCT = WS / 'Tools/progress'
OUT = WS / 'outputs/pdf_special_diagnosis_20261013'


def fixture_pdf():
    streams = [f'{color} rg 40 590 520 140 re f\n0 0 0 rg BT /F1 28 Tf 50 750 Td (FOREGROUND PAGE {name}) Tj ET'.encode()
               for color, name in [('0.9 0.1 0.1', 'ONE'), ('0.1 0.1 0.9', 'TWO')]]
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
               *[f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 5 0 R >> >> /Contents {n} 0 R >>'.encode() for n in (6, 7)],
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    objects += [b'<< /Length ' + str(len(s)).encode() + b' >>\nstream\n' + s + b'\nendstream' for s in streams]
    raw = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(raw)); raw += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(raw)
    raw += b'xref\n0 8\n0000000000 65535 f \n' + b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])
    return raw + f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def owned_window_png(pid, path):
    """仅截取自有Edge可见窗口客户区，不采集用户桌面。"""
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    for name in ('GetDC',):
        getattr(user, name).restype = ctypes.c_void_p
    for name in ('CreateCompatibleDC', 'CreateCompatibleBitmap', 'SelectObject'):
        getattr(gdi, name).restype = ctypes.c_void_p
    handles = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd): handles.append(hwnd)
        return True
    user.EnumWindows(callback(visit), 0)
    if not handles: return {'error': '自有Edge窗口未找到，未截用户窗口'}
    hwnd = handles[0]; rect = wintypes.RECT(); user.GetClientRect(hwnd, ctypes.byref(rect))
    width, height = rect.right, rect.bottom
    dc = user.GetDC(hwnd); mem = gdi.CreateCompatibleDC(ctypes.c_void_p(dc))
    bitmap = gdi.CreateCompatibleBitmap(ctypes.c_void_p(dc), width, height)
    old = gdi.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(bitmap))
    try:
        assert gdi.BitBlt(ctypes.c_void_p(mem), 0, 0, width, height, ctypes.c_void_p(dc), 0, 0, 0x00CC0020)
        header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        info = ctypes.create_string_buffer(header + bytes(12)); data = ctypes.create_string_buffer(width * height * 4)
        assert gdi.GetDIBits(ctypes.c_void_p(mem), ctypes.c_void_p(bitmap), 0, height, data, info, 0)
        raw = data.raw; rows = bytearray()
        for y in range(height):
            rows.append(0)
            for x in range(width):
                i = (y * width + x) * 4; rows.extend((raw[i + 2], raw[i + 1], raw[i]))
        def chunk(kind, value):
            return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
        path.write_bytes(png)
        return {'path': str(path), 'pid': pid, 'width': width, 'height': height}
    finally:
        gdi.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(old))
        gdi.DeleteObject(ctypes.c_void_p(bitmap)); gdi.DeleteDC(ctypes.c_void_p(mem)); user.ReleaseDC(hwnd, ctypes.c_void_p(dc))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'routes': {}, 'errors': [], 'legacy_access': [], 'http': [], 'target_events': [], 'product_changes': []}
    before = hashes()
    result['protected_snapshot'] = before
    result['fixture_sha256'] = hashlib.sha256(fixture_pdf()).hexdigest()
    product_before = {p.name: p.read_bytes() for p in PRODUCT.glob('workbench*') if p.is_file()}
    saved_path = sys.path[:]
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith('workbench') or k in OLD}
    finder = RejectOld()
    server = thread = browser = process = None
    original_builtin, original_io = builtins.open, io.open

    def guard(original):
        def opening(file, mode='r', *args, **kwargs):
            if isinstance(file, (str, bytes, Path)):
                name = Path(file).name.lower()
                if name in {'progress.conf', 'progress_marks.json', 'progress_settings.json'} or name.startswith(('progress_marks.', 'progress_settings.')):
                    result['legacy_access'].append(str(file))
                    raise AssertionError('禁止旧状态访问：' + str(file))
            return original(file, mode, *args, **kwargs)
        return opening

    try:
        with tempfile.TemporaryDirectory(prefix='temp2pages-', ignore_cleanup_errors=True) as temp:
            base = Path(temp); runtime = base / 'cleannewmodules'; runtime.mkdir()
            for source in PRODUCT.glob('workbench*.py'):
                if source.stem != 'workbench_legacy': shutil.copyfile(source, runtime / source.name)
            shutil.copyfile(PRODUCT / 'workbench_editor.html', runtime / 'workbench_editor.html')
            root = base / 'workspace'; book = root / 'LaTeX_Notes/ProbeBook'
            materials = book / 'Materials/C1/S1/N1'; materials.mkdir(parents=True)
            files = {'main.tex': '\\title{前台隔离两页}\n\\chapter{测试章}\n\\section{测试节}\n\\input{current}\n',
                     'current.tex': '\\subsection{前台单位}\nneedle\n',
                     'Probe_Content.md': '| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/S1/N1 | current.tex | Materials/C1/S1/N1 |\n',
                     'Source.md': '# 前台隔离来源\n',
                     'Materials/C1/S1/review.md': '| 目编号 | TeX | 标题 | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 | 疑点 | 结论 |\n|---|---|---|---|---|---|---|---|---|---|\n| C1/S1/N1 | current.tex | 前台单位 | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | 未检查 |\n',
                     'Materials/C1/S1/N1/record.md': '# C1/S1/N1\n- TeX：current.tex\n',
                     'Materials/C1/S1/N1/body.md': '隔离正文\n', 'Materials/C1/S1/N1/proof.md': '隔离证明\n'}
            for name, text in files.items(): (book / name).write_text(text, encoding='utf-8', newline='\n')
            pdfbytes = fixture_pdf(); (book / 'main.pdf').write_bytes(pdfbytes)
            (OUT / 'fixture.pdf').write_bytes(pdfbytes)
            result['fixture_root'] = str(root)
            for name in saved_modules: sys.modules.pop(name, None)
            sys.path[:] = [str(runtime)] + [p for p in saved_path if Path(p or '.').resolve() != PRODUCT]
            sys.meta_path.insert(0, finder)
            with patch('builtins.open', guard(original_builtin)), patch('io.open', guard(original_io)):
                for source in runtime.glob('workbench*.py'): importlib.import_module(source.stem)
                srv = importlib.import_module('workbench_server')
                result['module_sources'] = {k: v.__file__ for k, v in sys.modules.items() if k.startswith('workbench') and hasattr(v, '__file__')}
                assert all(Path(p).resolve().is_relative_to(runtime.resolve()) for p in result['module_sources'].values())
                server = srv.Server(root)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                result['origin'] = server.origin
                with urlopen(server.origin + '/pdf?book=ProbeBook') as response:
                    result['http_pdf_bytes_match'] = response.status == 200 and response.read() == pdfbytes
                    result['pdf_headers'] = dict(response.headers)
                with urlopen(Request(server.origin + '/pdf?book=ProbeBook', headers={'Range': 'bytes=0-31'})) as response:
                    result['range_valid'] = response.status == 206 and response.read() == pdfbytes[:32] and response.headers['Content-Range'] == f'bytes 0-31/{len(pdfbytes)}'
                try:
                    urlopen(Request(server.origin + '/pdf?book=ProbeBook', headers={'Range': 'bytes=999999-'}))
                except HTTPError as error:
                    result['range_invalid'] = error.code == 416 and error.headers['Content-Range'] == f'bytes */{len(pdfbytes)}'
                    error.close()
                with sync_playwright() as pw:
                    edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
                    assert edge.is_file(), '未找到本机已安装Edge'
                    with socket.socket() as sock:
                        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
                    process = subprocess.Popen([str(edge), '--user-data-dir=' + str(base / 'edge-profile'),
                                                '--remote-debugging-port=' + str(port), '--no-first-run',
                                                '--no-default-browser-check', '--window-size=1300,1000', 'about:blank'])
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1): break
                        except OSError:
                            if time.monotonic() >= deadline: raise
                            time.sleep(0.1)
                    browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                    result['launch'] = '普通已安装Edge，独立临时profile，非Playwright launch默认flags'
                    try:
                        result['browser_version'] = browser.version
                        page = browser.contexts[0].new_page()
                        page.set_viewport_size({'width': 1300, 'height': 1000})
                        page.on('pageerror', lambda e: result['errors'].append(str(e)))
                        page.on('response', lambda r: result['http'].append({'url': r.url, 'status': r.status, 'method': r.request.method}))
                        page.goto(server.origin); page.bring_to_front()
                        page.wait_for_function("() => document.querySelector('#message').textContent.includes('轻量导航已读取')")
                        page.evaluate("() => {window.pdfEvents=[];const create=URL.createObjectURL.bind(URL), revoke=URL.revokeObjectURL.bind(URL);URL.createObjectURL=b=>{const u=create(b);pdfEvents.push({event:'create',url:u,time:performance.now()});return u;};URL.revokeObjectURL=u=>{pdfEvents.push({event:'revoke',url:u,time:performance.now()});revoke(u);};document.querySelector('#pdfViewer').addEventListener('load',()=>pdfEvents.push({event:'iframe-load',src:document.querySelector('#pdfViewer').src,time:performance.now()}));}")
                        cdp = browser.new_browser_cdp_session(); messages = []
                        cdp.on('Target.receivedMessageFromTarget', lambda e: messages.append(e))
                        cdp.send('Target.setDiscoverTargets', {'discover': True})
                        for event in ('targetCreated', 'targetDestroyed', 'targetInfoChanged'):
                            cdp.on('Target.' + event, lambda e, kind=event: result['target_events'].append({'event': kind, 'data': e}))
                        counter = 0
                        viewer_sessions = {}

                        def viewer_state():
                            nonlocal counter
                            states = []
                            for info in cdp.send('Target.getTargets')['targetInfos']:
                                if info['type'] != 'webview': continue
                                session = None
                                try:
                                    session = viewer_sessions.get(info['targetId'])
                                    if session is None:
                                        session = cdp.send('Target.attachToTarget', {'targetId': info['targetId'], 'flatten': False})['sessionId']
                                        viewer_sessions[info['targetId']] = session
                                    counter += 1; start = len(messages)
                                    expression = 'JSON.stringify({page:document.querySelector("#pageselector")?.value,total:document.querySelector("#pagelength")?.textContent,url:location.href})'
                                    cdp.send('Target.sendMessageToTarget', {'sessionId': session, 'message': json.dumps({'id': counter, 'method': 'Runtime.evaluate', 'params': {'expression': expression, 'returnByValue': True}})})
                                    page.wait_for_timeout(150)
                                    for event in messages[start:]:
                                        message = json.loads(event['message'])
                                        if message.get('id') == counter and 'result' in message:
                                            states.append({'targetId': info['targetId'], 'target_url': info['url'], **json.loads(message['result']['result'].get('value', '{}'))})
                                except Exception as error: states.append({'targetId': info['targetId'], 'error': str(error)})
                            return states

                        image_page = browser.contexts[0].new_page()
                        page.bring_to_front()

                        def pixels(raw):
                            return image_page.evaluate("""async data => {const im=new Image();im.src='data:image/png;base64,'+data;await im.decode();const c=document.createElement('canvas');c.width=im.width;c.height=im.height;const ctx=c.getContext('2d');ctx.drawImage(im,0,0);const d=ctx.getImageData(0,0,c.width,c.height).data;const out={red:{count:0,minY:c.height,maxY:0},blue:{count:0,minY:c.height,maxY:0}};for(let y=80;y<880;y++)for(let x=50;x<1050;x++){const i=(y*c.width+x)*4;const k=d[i]>170&&d[i+1]<80&&d[i+2]<80?'red':d[i+2]>170&&d[i]<80&&d[i+1]<80?'blue':null;if(k){out[k].count++;out[k].minY=Math.min(out[k].minY,y);out[k].maxY=Math.max(out[k].maxY,y);}}return out;}""", base64.b64encode(raw).decode())

                        def capture(route, number):
                            samples = []; path = OUT / f'{route}-page{number}.png'
                            for sample in range(2):
                                page.wait_for_timeout(1500)
                                raw = page.screenshot(path=str(path)); color = pixels(raw); states = viewer_state()
                                expected, other = ('red', 'blue') if number == 1 else ('blue', 'red')
                                ready = (color[expected]['count'] > 10000 and 80 <= color[expected]['minY'] < 350 and color[other]['count'] == 0
                                         and any(s.get('page') == str(number) and s.get('total', '').strip() == '/ 2' for s in states))
                                samples.append({'pixels': color, 'viewer': states, 'ready': ready})
                                if ready: break
                            native = owned_window_png(process.pid, OUT / f'{route}-page{number}-native.png')
                            if native.get('path'):
                                native['pixels'] = pixels(Path(native['path']).read_bytes())
                                expected, other = ('red', 'blue') if number == 1 else ('blue', 'red')
                                native['marker_ready'] = native['pixels'][expected]['count'] > 10000 and native['pixels'][other]['count'] == 0
                            return {'ready': ready, 'screenshot': str(path), 'native': native, 'samples': samples, 'url': page.url}

                        workbench = page
                        for route in ('standalone-http', 'standalone-blob'):
                            current = result['routes'][route] = {}
                            for number in (1, 2):
                                page = browser.contexts[0].new_page()
                                if route == 'standalone-http':
                                    page.goto(server.origin + '/pdf?book=ProbeBook#page=' + str(number), wait_until='commit')
                                else:
                                    blob = workbench.evaluate("async () => {const r=await fetch('/pdf?book=ProbeBook');return URL.createObjectURL(await r.blob());}")
                                    page.goto(blob + '#page=' + str(number), wait_until='commit')
                                page.bring_to_front()
                                current['page' + str(number)] = capture(route, number)
                                page.close()
                                if route == 'standalone-blob': workbench.evaluate('u => URL.revokeObjectURL(u)', blob)
                            current['status'] = 'PASS' if all(current['page' + str(n)]['ready'] for n in (1, 2)) else 'UNVERIFIED'
                        page = workbench; page.bring_to_front()
                        page.evaluate("() => showPdf('ProbeBook',1)")
                        page.wait_for_function("() => !document.querySelector('#pdfViewer').hidden && document.querySelector('#pdfViewer').src.startsWith('blob:')")
                        page.locator('#pdfViewer').evaluate("el => {el.style.position='fixed';el.style.left='30px';el.style.top='20px';el.style.width='1040px';el.style.height='880px';el.style.zIndex='99999';}")
                        current = result['routes']['currentblob'] = {}
                        current['page1'] = capture('currentblob', 1)
                        if current['page1']['ready']:
                            page.locator('#pdfPage').fill('2'); page.locator('#jumpPdf').evaluate('el=>el.click()')
                            current['page2'] = capture('currentblob', 2)
                        current['status'] = 'PASS' if current.get('page2', {}).get('ready') else 'UNVERIFIED'
                        direct = result['routes']['direct'] = {}
                        page.evaluate("() => {releasePdf();openSearch();searchTab(true);const el=document.querySelector('#pdfViewer');el.src='/pdf?book=ProbeBook#page=1';el.hidden=false;}")
                        direct['page1'] = capture('direct', 1)
                        page.locator('#pdfViewer').evaluate("el => el.src='/pdf?book=ProbeBook#page=2'")
                        direct['page2'] = capture('direct', 2)
                        direct['status'] = 'PASS' if direct['page1']['ready'] and direct['page2']['ready'] else 'UNVERIFIED'
                        workbench.evaluate("() => showPdf('ProbeBook',1)")
                        workbench.wait_for_function("() => !document.querySelector('#openPdfTab').disabled")
                        fallback = result['routes']['fallback-click'] = {}
                        for number in (1, 2):
                            workbench.locator('#pdfPage').fill(str(number))
                            with workbench.expect_popup() as opened:
                                workbench.locator('#openPdfTab').click()
                            page = opened.value; page.bring_to_front()
                            fallback['page' + str(number)] = capture('fallback-click', number)
                            page.close(); page = workbench; page.bring_to_front()
                        fallback['status'] = 'PASS' if all(fallback['page' + str(n)]['ready'] for n in (1, 2)) else 'UNVERIFIED'
                        result['pdf_events'] = page.evaluate('pdfEvents')
                        result['final_targets'] = cdp.send('Target.getTargets')['targetInfos']
                    finally:
                        try: browser.new_browser_cdp_session().send('Browser.close')
                        except Exception: pass
                        browser.close(); browser = None
                        process.wait(timeout=10); result['owned_browser_closed'] = True
    except Exception as error:
        import traceback
        result['failure'] = repr(error)
        result['traceback'] = traceback.format_exc()
    finally:
        if server:
            server.shutdown(); server.server_close(); thread.join(10)
        result['owned_server_stopped'] = thread is None or not thread.is_alive()
        for name in list(sys.modules):
            if name.startswith('workbench') or name in OLD: sys.modules.pop(name, None)
        sys.modules.update(saved_modules); sys.path[:] = saved_path
        if finder in sys.meta_path: sys.meta_path.remove(finder)
        result['protected_hash_unchanged'] = before == hashes()
        result['product_changes'] = [name for name, raw in product_before.items() if (PRODUCT / name).read_bytes() != raw]
        result['overall'] = 'FAIL' if result.get('failure') or not result['protected_hash_unchanged'] else ('PASS' if result['routes'].get('currentblob', {}).get('status') == 'PASS' else 'PARTIAL/UNVERIFIED')
        result['exit'] = 1 if result['overall'] == 'FAIL' else 0
        (OUT / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
        print(json.dumps({'overall': result['overall'], 'exit': result['exit'], 'routes': {k: v.get('status', 'UNVERIFIED') for k, v in result['routes'].items()}, 'failure': result.get('failure')}, ensure_ascii=False))
    return result['exit']


if __name__ == '__main__':
    sys.exit(main())
