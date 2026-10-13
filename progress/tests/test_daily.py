"""日常调整隔离探针：不改真实书，不调用真实编辑器。"""
import concurrent.futures
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

WS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WS / 'Tools/progress'))
import workbench_daily as daily
import workbench_server as srv
import workbench_store as st
import workbench_readonly as ro
import workbench_features as features
import workbench_pdf as pdf

RUN = Path(tempfile.mkdtemp(prefix='workbench_daily_', dir=WS / 'outputs'))
results = []
def check(name, value):
    results.append({'test': name, 'passed': bool(value)})
    assert value, name

def real_hashes():
    paths = [p for b in ro.discover(WS) for p in b.rglob('*') if p.is_file() and '.git' not in p.parts and (p.suffix in {'.tex', '.md', '.json', '.pdf'} or p.name.startswith('progress_'))]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

before = real_hashes()
real = ro.scan(WS)
book = next(b for b in real['books'] if b['name'] == 'General_Topology')
u = next(u for u in book['units'] if u['id'].startswith('C05/S02'))
units = [v for v in book['units'] if v['review_path'] == u['review_path']]
root = RUN / 'shelf'
b = root / 'Book'
b.mkdir(parents=True)
files = {u['binding_provenance']['path'], u['review_path'], 'Source.md'}
for unit in units:
    files.add(unit['tex_path'])
    files.update(unit['materials_path'] + '/' + n for n in ('record.md', 'body.md', 'proof.md'))
for name in files:
    p = b / name
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WS / 'LaTeX_Notes' / book['name'] / name, p)
(b / u['binding_provenance']['path']).write_text('| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n' + ''.join('| '+x['display_id']+' | '+x['tex_path']+' | '+x['materials_path']+' |\n' for x in units), encoding='utf-8', newline='\n')
store = st.BookStore(root, 'Book')
store.init()
uid = u['id']
target = u['tex_path']
main = b / 'main.tex'
def put(text):
    main.write_text(text, encoding='utf-8', newline='\n')
def part(text):
    put(text)
    return daily.participation(store, uid)
check('主动输入已见', part('\\input{'+target+'}')['status'] == 'seen')
check('注释输入未见', part('%\\input{'+target+'}')['status'] == 'unseen')
(b / 'nest.tex').write_text('\\input{'+target+'}', encoding='utf-8')
check('递归输入已见', part('\\input{nest}')['chain'] == ['main.tex', 'nest.tex', target])
check('条件分支未知', part('\\iftrue\\input{'+target+'}\\fi')['status'] == 'unknown')
check('includeonly排除', part('\\includeonly{other}\\include{'+target.removesuffix('.tex')+'}')['status'] == 'unseen')
check('includeonly包含', part('\\includeonly{'+target.removesuffix('.tex')+'}\\include{'+target+'}')['status'] == 'seen')
check('宏目标未知', part('\\input{\\target}')['status'] == 'unknown')
check('缺目标未知', part('\\input{missing}')['status'] == 'unknown')
check('环未知', part('\\input{main}')['status'] == 'unknown')
check('越界未知', part('\\input{../outside}')['status'] == 'unknown')
put('\\input{'+target+'}')
(b / 'main.pdf').write_bytes(b'%PDF-fixture')
os.utime(b / 'main.pdf', (1, 1))
check('PDF过期检测', daily.participation(store, uid)['pdf_may_be_stale'])
changes = daily.Changes(root, ro.discover, ttl=300)
first = changes.read()
versions = {x['name']: x['version'] for x in first['books']}
with patch.object(Path, 'read_bytes', side_effect=AssertionError('变化检测不应读内容')):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: changes.read(json.dumps(versions)), range(16)))
check('TTL合并仅一次扫描且不读内容', changes.scans == 1)
new = b / 'new.tex'
new.write_text('new', encoding='utf-8')
changes.deadline = 0
added = changes.read(json.dumps(versions))['books'][0]
check('新增文件检测', 'new.tex' in added['added'])
new.write_text('modified long', encoding='utf-8')
changes.deadline = 0
modified = changes.read(json.dumps({'Book': added['version']}))['books'][0]
check('修改文件检测', 'new.tex' in modified['modified'])
new.unlink()
changes.deadline = 0
check('删除文件检测', 'new.tex' in changes.read(json.dumps({'Book': modified['version']}))['books'][0]['deleted'])
# A/B：原实现与新实现的搜索结果及审核读值不变。
old_path = RUN / 'old_features.py'
old_path.write_bytes((WS / 'Tools/progress/workbench_features.py').read_bytes())
spec = importlib.util.spec_from_file_location('old_features', old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
server = srv.Server(root, 0, True, ['Book'])
check('A/B搜索结果一致', old.search(server, 'TODO', 'Book') == features.search(server, 'TODO', 'Book'))
check('默认打开拒绝', not server.allow_open)
with patch.object(pdf.subprocess, 'Popen') as spawn:
    try:
        pdf.open_tex(server, store, uid, True)
        check('直接调用未授权拒绝', False)
    except st.StoreError:
        check('直接调用未授权拒绝', not spawn.called)
server.allow_open = True
with patch.object(pdf, 'executable', return_value='mock.exe'), patch.object(pdf.subprocess, 'Popen') as spawn:
    expected = hashlib.sha256(store.path(target).read_bytes()).hexdigest()
    pdf.open_tex(server, store, uid, True, 1, target, expected)
    check('搜索命中使用文档行参数', spawn.call_args.args[0] == ['mock.exe', '--line', '1', str(store.path(target))])
    for bad in ['../main.tex', 'main.tex', 'C:/outside.tex']:
        try:
            pdf.open_tex(server, store, uid, True, 1, bad, expected)
            check('错误目标拒绝'+bad, False)
        except st.StoreError:
            check('错误目标拒绝'+bad, True)
server.allow_open = False
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
def api(path, args=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    if args is None:
        conn.request('GET', path)
    else:
        conn.request('POST', path, json.dumps(args), {'Content-Type':'application/json', 'Origin':server.origin, 'X-Workbench-CSRF':server.token})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data)
try:
    check('API session身份', api('/session')[1]['service'] == 'latex-writing-workbench')
    check('API变化', api('/changes?since=%7B%7D')[0] == 200)
    check('API未授权打开403', api('/open', {'book':'Book','unit':uid,'confirm':True})[0] == 403)
    check('API越界书拒绝', api('/participation?book=..&unit=x')[0] == 400)
    ui = subprocess.run([os.environ.get('NODE_BINARY', shutil.which('node') or 'node'), str(Path(__file__).with_name('ui_daily.cjs')), server.origin, uid, str(RUN)], env=os.environ, capture_output=True, text=True)
    (RUN / 'ui.log').write_text(ui.stdout + ui.stderr, encoding='utf-8')
    check('jsdom日常交互', ui.returncode == 0)
finally:
    server.shutdown()
    thread.join(10)
    server.server_close()
check('真实八书hash保护', before == real_hashes())
(RUN / 'evidence.json').write_text(json.dumps({'results':results,'real_hash_count':len(before),'run':str(RUN)}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed':len(results),'run':str(RUN)}, ensure_ascii=False))
