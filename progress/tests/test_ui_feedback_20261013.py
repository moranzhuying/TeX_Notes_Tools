"""四项界面只读验收：复用7656，不启动/重启服务，不写真实笔记。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

WS = Path(__file__).resolve().parents[3]
OUT = WS / 'outputs/workbench_ui_feedback_20261013'
BASE = os.environ.get('WORKBENCH_BASE', 'http://127.0.0.1:7656')


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def hashes():
    roots = [WS / 'LaTeX_Notes']
    files = [p for root in roots for p in root.rglob('*') if p.is_file() and '.git' not in p.parts]
    files += list((WS / 'LaTeX_Notes').glob('*/.git/index'))
    files += [p for p in (WS / 'Tools/progress').glob('progress_*') if p.is_file()]
    return {str(p.relative_to(WS)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    OUT.mkdir(exist_ok=True)
    before = hashes()
    session = get('/session')
    navigation = get('/navigation')
    (OUT / 'protection_before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    env = dict(os.environ)
    # jsdom使用Node默认模块发现，外部安装位置由NODE_PATH提供。
    js = subprocess.run([shutil.which('node') or 'node', str(Path(__file__).with_suffix('.cjs')), BASE, str(OUT)], env=env, capture_output=True, text=True, encoding='utf-8')
    (OUT / 'jsdom.log').write_text(js.stdout + js.stderr, encoding='utf-8')
    assert js.returncode == 0, js.stdout + js.stderr
    evidence = {'errors': [], 'viewports': [], 'session': session}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        try:
            for width in (1200, 390):
                page = browser.new_page(viewport={'width': width, 'height': 1000}, color_scheme='dark')
                page.on('pageerror', lambda e: evidence['errors'].append(str(e)))
                page.route('**/*', lambda route: route.abort() if route.request.method != 'GET' else route.continue_())
                page.goto(BASE)
                page.wait_for_function("() => document.querySelector('#message').textContent.includes('轻量导航已读取')", timeout=120000)
                page.locator('#theme').select_option('dark')
                page.locator('#book').select_option('General_Topology')
                page.wait_for_function("() => selectedBook === 'General_Topology' && document.querySelector('#participation').textContent.split('\\n').length === 3", timeout=120000)
                page.locator('#searchPanel').evaluate("el => el.closest('details').open = true")
                page.locator('#fullQuery').fill('拓扑')
                page.locator('#fullQuery').press('Enter')
                page.wait_for_selector('.source-line.current', timeout=120000)
                page.wait_for_function("() => document.querySelector('#hitParticipation').textContent.split('\\n').length === 3", timeout=120000)
                assert page.locator('#fullQuery').is_visible()
                assert page.locator('#queryMirror').count() == 0
                geometry = page.evaluate("""() => {
                    const box = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height};};
                    return {source:box('#sourceTab'),pdf:box('#pdfTab'),tool:box('#hitSource'),tabs:box('.search-tabs'),tools:box('.hit-tools'),overflow:document.documentElement.scrollWidth>innerWidth,lines:['participation','hitParticipation'].map(id=>({id,text:document.getElementById(id).textContent,whiteSpace:getComputedStyle(document.getElementById(id)).whiteSpace})),visibleSearchInputs:[...document.querySelectorAll('#fullQuery,#queryMirror')].filter(el=>el.getBoundingClientRect().height>0).length};
                }""")
                assert geometry['visibleSearchInputs'] == 1
                assert not geometry['overflow'], geometry
                assert abs(geometry['source']['left'] - geometry['tool']['left']) < 1
                assert abs(geometry['source']['top'] - geometry['pdf']['top']) < 1
                assert abs(geometry['source']['height'] - geometry['tool']['height']) < 1
                assert 64 <= geometry['source']['width'] <= 100
                assert 64 <= geometry['pdf']['width'] <= 100
                for line in geometry['lines']:
                    assert len(line['text'].split('\n')) == 3 and line['whiteSpace'] == 'pre-line'
                page.screenshot(path=str(OUT / f'edge-dark-{width}-full.png'), full_page=True)
                page.locator('.search-detail').screenshot(path=str(OUT / f'edge-dark-{width}-search.png'))
                page.locator('#reviewEditor').screenshot(path=str(OUT / f'edge-dark-{width}-unit.png'))
                page.locator('#pdfTab').click()
                assert page.locator('#pdfPane').is_visible()
                page.locator('#sourceTab').click()
                assert page.locator('#sourcePane').is_visible()
                evidence['viewports'].append({'width': width, **geometry})
                page.close()
        finally:
            browser.close()
    assert not evidence['errors'], evidence['errors']
    assert session == get('/session'), '服务会话/权限不应改变'
    after = get('/navigation')
    ids = lambda data: {b['name']: sorted((u['id'], u['tex_path'], u['materials_path']) for u in b['units']) for b in data['books']}
    assert ids(navigation) == ids(after)
    assert len(ids(after)) == 8 and sum(map(len, ids(after).values())) == 1818
    assert before == hashes(), '真实笔记/旧状态/index必须完全不变'
    evidence.update(real_hash_unchanged=True, hash_count=len(before), books=8, units=1818)
    (OUT / 'edge_evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(OUT), 'hash_count': len(before), 'books': 8, 'units': 1818, 'errors': evidence['errors']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
