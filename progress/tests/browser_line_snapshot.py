"""真实Edge页面到隔离HTTP的搜索旧命中拒绝验收。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright

WS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WS / 'Tools/progress'))
import workbench_server as srv
import workbench_pdf as pdf

out = Path(tempfile.mkdtemp(prefix='line_browser_', dir=WS / 'outputs/workbench_line_verify_20261013'))
root = out / 'shelf'
book = root / 'Book'
(book / 'Materials/C1/N1').mkdir(parents=True)
target = book / '中文 空格 & [合法] #定位.tex'
original = ''.join(f'% marker 行{i}\n' for i in range(1, 41)).encode('utf-8')
target.write_bytes(original)
(book / 'Probe_Content.md').write_text('| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/N1 | '+target.name+' | Materials/C1/N1 |\n', encoding='utf-8', newline='\n')
(book / 'main.tex').write_text('\\input{'+target.name+'}\n', encoding='utf-8', newline='\n')
(book / 'Materials/review.md').write_text('| 目编号 | 标题 | TeX | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 | 疑点 | 结论 |\n|---|---|---|---|---|---|---|---|---|---|\n| C1/N1 | 临时单位 | '+target.name+' | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | |\n', encoding='utf-8', newline='\n')
server = srv.Server(root, allow_open=True)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
result = {'checks': [], 'errors': [], 'responses': []}
try:
    with patch.object(pdf, 'executable', return_value='mock.exe'), patch.object(pdf.subprocess, 'Popen') as spawn, sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width':1400,'height':1000})
            page.on('pageerror', lambda e: result['errors'].append(str(e)))
            page.on('dialog', lambda d: d.accept())
            page.goto(server.origin)
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('轻量导航已读取') || document.querySelector('#message').textContent.includes('启动读取失败')")
            assert '启动读取失败' not in page.locator('#message').inner_text(), page.locator('#message').inner_text()
            page.locator('#searchPanel').evaluate("el => el.closest('details').open=true")
            for kind, raw in [('新增', b'% new\n'+original), ('删除', original.split(b'\n',1)[1]), ('等长替换', original.replace(b'marker',b'xxxxxx',1))]:
                target.write_bytes(original)
                page.locator('#fullQuery').fill('marker')
                page.locator('#bookSearch').click()
                page.wait_for_selector('.source-line.current')
                page.wait_for_function("() => selectedHit !== null && !document.querySelector('#hitOpenTex').disabled")
                hit = page.evaluate('selectedHit')
                assert hit['sha256'] == hashlib.sha256(original).hexdigest()
                target.write_bytes(raw)
                with page.expect_response(lambda r: r.url.endswith('/open')) as response:
                    page.locator('#hitOpenTex').click()
                r = response.value
                payload = r.request.post_data_json
                body = r.json()
                assert r.status == 409, body
                assert payload['expected'] == hit['sha256']
                assert '已变化' in body['error']
                page.wait_for_function("() => document.querySelector('#message').textContent.includes('已变化')")
                spawn.assert_not_called()
                result['checks'].append(kind+'：真实浏览器POST到HTTP409且零spawn')
                result['responses'].append({'kind':kind,'status':r.status,'request':payload,'response':body})
                page.screenshot(path=str(out / (kind+'.png')), full_page=True)
            target.write_bytes(original)
            page.locator('#bookSearch').click()
            page.wait_for_selector('.source-line.current')
            with page.expect_response(lambda r: r.url.endswith('/open')) as response:
                page.locator('#hitOpenTex').click()
            assert response.value.status == 200
            assert spawn.call_count == 1
            assert spawn.call_args.args[0][-3:] == ['--line','1',str(target)]
            result['checks'].append('新搜索正常打开200及完整特殊路径参数')
            assert not result['errors']
        finally:
            browser.close()
finally:
    server.shutdown()
    t.join(10)
    server.server_close()
(out / 'evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
print(json.dumps({'out':str(out),**result},ensure_ascii=False))
