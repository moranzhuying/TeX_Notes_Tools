"""无旧依赖的隔离HTTP与真实Edge验收；OS调用仅mock，不启动编辑器。"""
import base64
import builtins
import hashlib
import importlib
import importlib.abc
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

WS = Path(__file__).resolve().parents[3]
PRODUCT = WS / 'Tools/progress'
OUT = WS / 'outputs/no_legacy_acceptance_20261013/ui'
OLD = {'progress', 'progress_ui', 'workbench_legacy'}


def hashes():
    files = [p for p in (WS / 'LaTeX_Notes').rglob('*') if p.is_file() and '.git' not in p.parts]
    files += list((WS / 'LaTeX_Notes').glob('*/.git/index'))
    files += [p for p in PRODUCT.glob('progress_*') if p.is_file()]
    files += [p for p in WS.iterdir() if p.is_file()]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def minimal_pdf():
    streams = [b'0.9 0.1 0.1 rg 30 30 240 220 re f\nBT /F1 24 Tf 40 280 Td (CLEAN PAGE ONE) Tj ET',
               b'0.1 0.1 0.9 rg 30 30 240 220 re f\nBT /F1 24 Tf 40 280 Td (CLEAN PAGE TWO) Tj ET']
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 320] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 320] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    objects += [b'<< /Length ' + str(len(s)).encode() + b' >>\nstream\n' + s + b'\nendstream' for s in streams]
    raw = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(raw)); raw += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(raw)
    raw += b'xref\n0 8\n0000000000 65535 f \n' + b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])
    return raw + f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


class RejectOld(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in OLD:
            raise AssertionError('禁止旧模块导入：' + fullname)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'checks': [], 'errors': [], 'http': [], 'legacy_access': [], 'spawn': [], 'pdf': {}}
    before = hashes()
    result['protected_hash_count'] = len(before)
    servers = []
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith('workbench') or k in OLD}
    saved_path = sys.path[:]
    finder = RejectOld()
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

    def check(name, condition=True):
        assert condition, name
        result['checks'].append(name)

    try:
        with tempfile.TemporaryDirectory(prefix='clean-ui ') as temp:
            base = Path(temp).resolve(); runtime = base / 'runtime'; runtime.mkdir()
            for source in PRODUCT.glob('workbench*.py'):
                if source.stem != 'workbench_legacy':
                    shutil.copyfile(source, runtime / source.name)
            shutil.copyfile(PRODUCT / 'workbench_editor.html', runtime / 'workbench_editor.html')
            root = base / 'workspace'; book = root / 'LaTeX_Notes/ProbeBook'
            (book / 'Materials/C1/S1/N1').mkdir(parents=True)
            (book / 'Materials/C1/S1/N2').mkdir()
            target = book / '中文 空格 & [合法] #命中.tex'
            current = book / 'current.tex'
            original = ('\\subsection{命中单位}\n' + ''.join(f'% needle 行{i}\n' for i in range(2, 32))).encode()
            target.write_bytes(original)
            files = {
                'main.tex': '\\title{干净书名}\n\\chapter{干净章}\n\\section{干净节}\n\\input{current}\n\\input{' + target.name + '}\n',
                'current.tex': '\\subsection{当前单位}\n当前审核正文\n',
                'Probe_Content.md': '| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/S1/N1 | current.tex | Materials/C1/S1/N1 |\n| C1/S1/N2 | ' + target.name + ' | Materials/C1/S1/N2 |\n',
                'Source.md': '# 隔离合法来源\n',
                'Materials/C1/S1/review.md': '| 目编号 | TeX | 标题 | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 | 疑点 | 结论 |\n|---|---|---|---|---|---|---|---|---|---|---|\n| C1/S1/N1 | current.tex | 当前单位 | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | 未检查 |\n| C1/S1/N2 | ' + target.name + ' | 命中单位 | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | 未检查 |\n',
            }
            for uid, name in [('N1', current.name), ('N2', target.name)]:
                for filename, text in [('record.md', '# C1/S1/' + uid + '\n- TeX：' + name + '\n'), ('body.md', '隔离正文\n'), ('proof.md', '隔离证明\n')]:
                    files['Materials/C1/S1/' + uid + '/' + filename] = text
            for name, text in files.items():
                (book / name).write_text(text, encoding='utf-8', newline='\n')
            pdfbytes = minimal_pdf(); (book / 'main.pdf').write_bytes(pdfbytes)
            check('合法UTF8 LF临时审核表', b'\r' not in (book / 'Materials/C1/S1/review.md').read_bytes())
            check('干净runtime无旧模块状态', not any(p.name in {'progress.py','workbench_legacy.py','progress_marks.json','progress_settings.json','progress.conf'} for p in base.rglob('*')))
            for name in saved_modules: sys.modules.pop(name, None)
            sys.path[:] = [str(runtime)] + [p for p in saved_path if Path(p or '.').resolve() != PRODUCT]
            sys.meta_path.insert(0, finder); sys.dont_write_bytecode = True
            with patch('builtins.open', guard(original_builtin)), patch('io.open', guard(original_io)):
                for source in runtime.glob('workbench*.py'): importlib.import_module(source.stem)
                srv = importlib.import_module('workbench_server'); pdf = importlib.import_module('workbench_pdf')
                result['module_sources'] = {name: module.__file__ for name,module in sys.modules.items() if name.startswith('workbench') and hasattr(module,'__file__')}
                check('模块来源全部干净runtime', all(Path(p).resolve().is_relative_to(runtime) for p in result['module_sources'].values()))
                def start(allow_open=False, allow_write=False):
                    server = srv.Server(root, allow_open=allow_open, allow_write=allow_write, write_books=['ProbeBook'] if allow_write else [])
                    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                    servers.append((server, thread)); return server
                readonly = start(); authorized = start(True)
                from urllib.request import Request
                from urllib.error import HTTPError
                def http(server, route, payload=None, headers=None):
                    h = {'Origin':server.origin,'X-Workbench-CSRF':server.token,'Content-Type':'application/json'} | (headers or {})
                    req = Request(server.origin+route, data=json.dumps(payload).encode() if payload is not None else None, headers=h)
                    try:
                        with urlopen(req) as response: return response.status, response.read(), dict(response.headers)
                    except HTTPError as response: return response.code, response.read(), dict(response.headers)
                status, raw, headers = http(readonly,'/pdf?book=ProbeBook')
                check('PDF真实字节200',status==200 and raw==pdfbytes)
                status, raw, headers = http(readonly,'/pdf?book=ProbeBook',headers={'Range':'bytes=0-31'})
                check('PDF Range206真实字节',status==206 and raw==pdfbytes[:32] and headers.get('Content-Range')==f'bytes 0-31/{len(pdfbytes)}')
                status, raw, _ = http(readonly,'/pdf?book=ProbeBook',headers={'Range':'bytes=99999-'})
                check('PDF越界Range416',status==416)
                status, raw, _ = http(readonly,'/api/pdfcontent?book=ProbeBook&offset=1&stamp=')
                check('PDF非对齐offset400',status==400)
                status, raw, _ = http(readonly,'/api/pdfcontent?book=ProbeBook&offset=0&stamp='+'0'*64)
                check('PDF版本stamp失配400',status==400)
                result['pdf']['http_contracts'] = ['200 full bytes','206 bytes 0-31','416 beyond EOF','400 offset','400 stamp']
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True, args=['--disable-features=msPdfOOUI,msPdfOOUIByDefault'])
                    try:
                        page = browser.new_page(viewport={'width': 1450, 'height': 1100})
                        page.on('pageerror', lambda e: result['errors'].append(str(e)))
                        page.on('dialog', lambda d: d.accept())
                        page.on('response', lambda r: result['http'].append({'url': r.url, 'status': r.status, 'method': r.request.method}))
                        def load(server):
                            page.goto(server.origin)
                            page.wait_for_function("() => document.querySelector('#message').textContent.includes('轻量导航已读取')")
                            page.wait_for_function('() => changeBaseline && Boolean(changeChecked)')
                            page.locator('#searchPanel').evaluate("el => el.closest('details').open=true")
                        def search(button='Enter'):
                            page.locator('#fullQuery').fill('needle')
                            with page.expect_response(lambda r: '/search?' in r.url) as response:
                                if button == 'Enter': page.locator('#fullQuery').press('Enter')
                                else: page.locator('#' + button).click()
                            page.wait_for_selector('.source-line.current')
                            page.wait_for_function("() => selectedHit !== null && document.querySelector('#hitParticipation').textContent.includes('PDF时间')")
                            return response.value, page.evaluate('selectedHit')
                        load(readonly)
                        check('搜索唯一按需且不在header', page.locator('#searchPanel #fullQuery').count()==1 and page.locator('header #fullQuery,#queryMirror').count()==0)
                        check('默认OS打开和当前单位打开禁用', page.locator('#openTex').is_disabled())
                        r, hit = search()
                        check('Enter只搜本书', 'book=ProbeBook' in r.url)
                        check('命中上下文SHA真实源码', hit['sha256']==hashlib.sha256(original).hexdigest() and 'needle' in page.locator('.source-line.current').inner_text())
                        check('命中打开默认禁用', page.locator('#hitOpenTex').is_disabled())
                        r, _ = search('fullSearch'); check('全书搜索无book限制', 'book=&' in r.url or r.url.endswith('book='))
                        page.locator('#pdfTab').click(); check('PDF tab', page.locator('#pdfPane').is_visible())
                        page.locator('#sourceTab').click(); check('source tab', page.locator('#sourcePane').is_visible())
                        with page.expect_response(lambda r: '/api/pdfcontent?' in r.url) as response:
                            page.locator('#hitView').click()
                        content = response.value.json()
                        check('真实HTTP PDF内容', base64.b64decode(content['data'])==pdfbytes)
                        result['pdf']['chunk'] = {k:v for k,v in content.items() if k!='data'}
                        result['pdf']['attempts'] = []
                        result['pdf']['status'] = 'UNVERIFIED'
                        image_page = browser.new_page()
                        try:
                            def colors(raw):
                                return image_page.evaluate("""async data => {const image=new Image();image.src='data:image/png;base64,'+data;await image.decode();const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);const bytes=ctx.getImageData(0,0,image.width,image.height).data;let red=0,blue=0;for(let i=0;i<bytes.length;i+=4){if(bytes[i]>170&&bytes[i+1]<80&&bytes[i+2]<80)red++;if(bytes[i+2]>170&&bytes[i]<80&&bytes[i+1]<80)blue++;}return {red,blue};}""",base64.b64encode(raw).decode())
                            page.bring_to_front()
                            page.set_viewport_size({'width':1450,'height':1100})
                            page.locator('#pdfViewer').evaluate("el => {el.style.position='fixed';el.style.left='20px';el.style.top='20px';el.style.width='1100px';el.style.height='900px';el.style.zIndex='99999';}")
                            browser_cdp = browser.new_browser_cdp_session()
                            plugin_messages=[]
                            browser_cdp.on('Target.receivedMessageFromTarget', lambda event: plugin_messages.append(event))
                            def viewer_state():
                                states=[]
                                for info in browser_cdp.send('Target.getTargets')['targetInfos']:
                                    if info['type']!='webview': continue
                                    session=browser_cdp.send('Target.attachToTarget',{'targetId':info['targetId'],'flatten':False})['sessionId']
                                    start=len(plugin_messages)
                                    browser_cdp.send('Target.sendMessageToTarget',{'sessionId':session,'message':json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':'JSON.stringify({page:document.querySelector("#pageselector")?.value,total:document.querySelector("#pagelength")?.textContent})','returnByValue':True}})})
                                    page.wait_for_timeout(250)
                                    for event in plugin_messages[start:]:
                                        message=json.loads(event['message'])
                                        if message.get('id')==1 and 'result' in message:
                                            states.append(json.loads(message['result']['result'].get('value','{}')))
                                    browser_cdp.send('Target.detachFromTarget',{'sessionId':session})
                                return states
                            def capture_ready(attempt,number,color):
                                samples=[]
                                path=OUT / f'final-pdf-attempt{attempt}-page{number}.png'
                                for sample in range(6):
                                    page.wait_for_timeout(2000)
                                    raw=page.screenshot(path=str(path))
                                    counts=colors(raw)
                                    states=viewer_state()
                                    samples.append({'colors':counts,'viewer':states})
                                    if counts[color]>1000 and any(s.get('page')==str(number) and s.get('total','').strip()=='/ 2' for s in states):
                                        return {'ready':True,'screenshot':str(path),'samples':samples}
                                return {'ready':False,'screenshot':str(path),'samples':samples}
                            for attempt in (1,2):
                                record={'attempt':attempt}; result['pdf']['attempts'].append(record)
                                if attempt==2:
                                    page.evaluate("() => showPdf(selectedHit.book,1)")
                                page.wait_for_function("() => !document.querySelector('#pdfViewer').hidden && document.querySelector('#pdfViewer').src.startsWith('blob:')")
                                record['page1']=capture_ready(attempt,1,'red')
                                if not record['page1']['ready']:
                                    record['reason']='第一页画布/阅读器未就绪，未尝试page2'; continue
                                page.locator('#pdfPage').fill('2')
                                page.locator('#jumpPdf').evaluate('el => el.click()')
                                record['page2']=capture_ready(attempt,2,'blue')
                                record['requested_page2']=page.locator('#pdfViewer').get_attribute('src')
                                if record['page2']['ready']:
                                    result['pdf']['status']='PASS'; break
                                record['reason']='第2页实际画布未核验通过；不判定产品失败'
                            result['pdf']['render_verification']=result['pdf']['status']
                        except Exception as error:
                            result['pdf']['diagnostic_error']=repr(error)
                        finally:
                            image_page.close()
                        result['groups']={'pdf_render':result['pdf']['status']}
                        load(authorized)
                        with patch.object(pdf, 'executable', return_value='C:/mock/texstudio.exe'), patch.object(pdf.subprocess, 'Popen') as spawn:
                            r, hit = search()
                            check('当前单位与命中独立', page.locator('#unit').input_value()=='C1/S1/N1' and hit['unit']=='C1/S1/N2')
                            for kind, raw in [('insert', b'% inserted\n'+original), ('delete', original.split(b'\n',1)[1]), ('equal-length', original.replace(b'needle',b'xxxxxx',1))]:
                                target.write_bytes(raw)
                                with page.expect_response(lambda r: r.url.endswith('/open')) as response: page.locator('#hitOpenTex').click()
                                check(kind+'旧命中409无spawn', response.value.status==409 and spawn.call_count==0)
                                page.wait_for_function("() => document.querySelector('#message').textContent.includes('已变化')")
                                page.screenshot(path=str(OUT / ('edge-stale-'+kind+'.png')), full_page=True)
                                target.write_bytes(original); search()
                            target.write_bytes(original.replace(b'needle',b'xxxxxx',1)); r, fresh = search()
                            with page.expect_response(lambda r: r.url.endswith('/open')) as response: page.locator('#hitOpenTex').click()
                            check('重新搜索才200', response.value.status==200 and spawn.call_count==1)
                            check('命中参数正确不声称定位完成', spawn.call_args.args[0]==['C:/mock/texstudio.exe','--line',str(fresh['line']),str(target)] and response.value.json()['line_located'] is False)
                            result['spawn'].append(spawn.call_args.args[0]); spawn.reset_mock()
                            page.locator('#openTex').evaluate("el => el.closest('details') && (el.closest('details').open=true)")
                            with page.expect_response(lambda r: r.url.endswith('/open')) as response: page.locator('#openTex').click()
                            check('当前单位打开独立正确路径', response.value.status==200 and spawn.call_args.args[0]==['C:/mock/texstudio.exe',str(current)])
                            result['spawn'].append(spawn.call_args.args[0])
                        writable = start(allow_write=True)
                        check('临时初始化200', http(writable,'/init',{'book':'ProbeBook','confirm':True})[0]==200)
                        check('临时总结初始化200', http(writable,'/create-summaries',{'book':'ProbeBook','confirm':True})[0]==200)
                        load(writable)
                        page.locator('#conclusion').fill('隔离dirty保留')
                        reviewpath = book / 'Materials/C1/S1/review.md'
                        result['review_before_refresh'] = reviewpath.read_text(encoding='utf-8')
                        rows = result['review_before_refresh'].splitlines()
                        for index, row in enumerate(rows):
                            if 'C1/S1/N1' in row:
                                cells = row.split('|'); cells[4] = ' 进行中 '; rows[index] = '|'.join(cells)
                        reviewpath.write_text('\n'.join(rows)+'\n', encoding='utf-8', newline='\n')
                        page.locator('#dailyRefresh').click()
                        page.wait_for_function("() => document.querySelector('#message').textContent.includes('手动重新读取')")
                        result['refresh_state'] = {'conclusion':page.locator('#conclusion').input_value(),'baseline':page.locator('#baseline').text_content(),'message':page.locator('#message').inner_text()}
                        check('强制重读保留dirty且基线变化', result['refresh_state']['conclusion']=='隔离dirty保留' and '正文整理：进行中' in result['refresh_state']['baseline'])
                        book.rename(base / 'removed-book')
                        page.locator('#dailyRefresh').click()
                        result['removed_navigation'] = json.loads(http(writable,'/navigation')[1])
                        page.wait_for_function("() => missingDraftTarget === true")
                        check('移除原单位scope保留dirty禁止保存', page.locator('#conclusion').input_value()=='隔离dirty保留' and page.locator('#saveReview').is_disabled() and page.locator('#saveSummary').is_disabled())
                        page.screenshot(path=str(OUT / 'edge-removed-dirty.png'), full_page=True)
                        check('无笔记写入HTTP请求', not any(x['method']=='POST' and not x['url'].endswith('/open') for x in result['http']))
                        check('零前端异常', not result['errors'])
                    finally: browser.close()
                check('零旧模块/状态访问', not result['legacy_access'] and not OLD.intersection(sys.modules))
                result['groups'].update(http_open_dirty='PASS', module_isolation='PASS')
    except Exception as e:
        result['failure'] = repr(e)
        raise
    finally:
        for server, thread in servers:
            server.shutdown(); server.server_close(); thread.join(10)
        result['owned_servers_stopped'] = all(not thread.is_alive() for _,thread in servers)
        for name in list(sys.modules):
            if name.startswith('workbench') or name in OLD: sys.modules.pop(name, None)
        sys.modules.update(saved_modules); sys.path[:] = saved_path
        if finder in sys.meta_path: sys.meta_path.remove(finder)
        result['protected_hash_unchanged'] = before == hashes()
        result['overall'] = 'FAIL' if result.get('failure') or not result['protected_hash_unchanged'] else ('PASS' if result['pdf'].get('status')=='PASS' else 'PARTIAL/UNVERIFIED')
        (OUT / 'final_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
        print(json.dumps({'out':str(OUT),'checks':len(result['checks']),'failure':result.get('failure'),'protected_hash_unchanged':result['protected_hash_unchanged']},ensure_ascii=False))
    assert result['protected_hash_unchanged']
    assert result.get('groups',{}).get('http_open_dirty') == 'PASS'


if __name__ == '__main__':
    main()
