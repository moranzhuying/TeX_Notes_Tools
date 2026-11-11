"""真实八书只读浏览器验收；仅启动和停止本脚本拥有的随机端口服务。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright
WS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WS / 'Tools/progress'))
import workbench_server as srv
import workbench_readonly as ro

out = Path(tempfile.mkdtemp(prefix='workbench_daily_browser_', dir=WS / 'outputs'))
def hashes():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for b in ro.discover(WS) for p in b.rglob('*') if p.is_file() and '.git' not in p.parts and p.suffix in {'.tex','.md','.json','.pdf'}}
before = hashes()
server = srv.Server(WS / 'LaTeX_Notes', 0)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
result = {'errors':[], 'checks':[]}
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width':1500,'height':1000})
            page.on('pageerror', lambda e: result['errors'].append(str(e)))
            page.goto(server.origin)
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('轻量导航已读取')", timeout=60000)
            page.wait_for_function("() => changeBaseline === true && Boolean(changeChecked) && document.querySelector('#freshness').textContent.includes('元数据扫描时间')", timeout=60000)
            assert page.locator('#book option').count() == 8
            assert page.locator('#dailyRefresh').is_visible()
            assert page.locator('#openTex').is_disabled()
            result['checks'].append('真实八书导航/顶部显眼重读/默认拒绝打开')
            assert page.locator('header #fullQuery').count() == 0
            assert page.locator('#searchPanel #fullQuery').count() == 1
            assert page.locator('#queryMirror').count() == 0
            page.locator('#searchPanel').evaluate("el => el.closest('details').open = true")
            assert page.locator('#fullQuery').is_visible()
            page.locator('#fullQuery').fill('群')
            page.locator('#bookSearch').click()
            page.wait_for_selector('.source-line.current', timeout=60000)
            page.wait_for_function("() => document.querySelector('#hitParticipation').textContent.includes('PDF时间')", timeout=60000)
            assert page.locator('#hitOpenTex').is_disabled()
            result['checks'].append('真实搜索命中源码/保守输入链/PDF时间/命中打开默认拒绝')
            page.screenshot(path=str(out / 'daily.png'), full_page=True)
            page.locator('#dailyRefresh').click()
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('手动重新读取')", timeout=60000)
            result['checks'].append('真实只读手动重读')
            assert not result['errors']
        finally:
            browser.close()
finally:
    server.shutdown()
    t.join(10)
    server.server_close()
result['real_hash_unchanged'] = before == hashes()
assert result['real_hash_unchanged']
result['hash_count'] = len(before)
(out / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'out':str(out),**result},ensure_ascii=False))
