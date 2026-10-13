"""八书无旧数据真实HTTP验收；只在独立临时目录写入，冷启动使用当前解释器。"""
import builtins
import hashlib
import http.client
import importlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlencode

PRODUCT = Path(__file__).resolve().parents[1]
WORKSPACE = PRODUCT.parents[1]
BOOKS = ('General_Topology', 'Algebra', 'Integral_Theory', 'Topological_Vector_Space',
         'Functions_of_a_Real_Variable', 'Spectral_Theory', 'Algebraic_Topology',
         'Differential_and_Analytic_Manifolds')
UNITS = ('C1/S1/N1', 'C1/S1/N2')
OLD = {'progress', 'progress_ui', 'workbench_legacy'}
EVENTS = []


def legacy(path):
    name = Path(path).name.lower()
    return name in {'progress.py', 'progress_ui.html', 'progress.conf', 'workbench_legacy.py'} or name.startswith(('progress_marks.', 'progress_settings.')) or 'legacy' in Path(path).parts or 'legacy-archive' in Path(path).parts


class RejectOld(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in OLD:
            raise AssertionError('禁止旧模块导入：' + fullname)


def snapshot(root, opener=io.open):
    result = {}
    for path in root.rglob('*'):
        if path.is_file():
            with opener(path, 'rb') as stream:
                result[path.relative_to(root).as_posix()] = hashlib.sha256(stream.read()).hexdigest()
    return result


class CleanSave(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clean-save-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.modules = self.base / 'runtime'
        self.modules.mkdir()
        for source in PRODUCT.glob('workbench*.py'):
            if source.stem != 'workbench_legacy':
                shutil.copyfile(source, self.modules / source.name)
        shutil.copyfile(PRODUCT / 'workbench_editor.html', self.modules / 'workbench_editor.html')
        self.root = self.base / 'workspace'
        self.shelf = self.root / 'LaTeX_Notes'
        self.ids = {}
        for name in BOOKS:
            self.fixture(self.shelf / name, name)
            self.ids[name] = str(uuid.uuid4())
        self.config = self.modules / 'workbench_local.json'
        self.sessions = []
        self.addCleanup(self.stop)
        self.old_path = list(sys.path)
        self.old_modules = {k: v for k, v in sys.modules.items() if k.startswith('workbench') or k in OLD}
        for k in self.old_modules:
            del sys.modules[k]
        sys.path[:] = [str(self.modules)] + [p for p in sys.path if Path(p or '.').resolve() != PRODUCT]
        self.finder = RejectOld()
        sys.meta_path.insert(0, self.finder)
        self.addCleanup(self.restore)
        self.old_reads, self.writes = [], []
        self.readonly = False
        self.original_io = io.open
        def guard(original):
            def opening(file, mode='r', *args, **kwargs):
                if isinstance(file, (str, bytes, os.PathLike)):
                    p = Path(os.fsdecode(file)).resolve()
                    if legacy(p):
                        self.old_reads.append(str(p))
                        raise AssertionError('禁止旧文件读写：' + str(p))
                    if any(c in mode for c in 'wax+'):
                        self.writes.append(str(p))
                        if self.readonly or not p.is_relative_to(self.base):
                            raise AssertionError('非许可临时写入：' + str(p))
                return original(file, mode, *args, **kwargs)
            return opening
        original_os = os.open
        def os_guard(file, flags, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                p = Path(os.fsdecode(file)).resolve()
                if legacy(p):
                    self.old_reads.append(str(p))
                    raise AssertionError('禁止低层旧文件访问：' + str(p))
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    self.writes.append(str(p))
                    if self.readonly or not p.is_relative_to(self.base):
                        raise AssertionError('非许可低层写入：' + str(p))
            return original_os(file, flags, *args, **kwargs)
        self.patches = [patch('builtins.open', guard(builtins.open)), patch('io.open', guard(io.open)), patch('os.open', os_guard)]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.wb = importlib.import_module('workbench_launcher')
        for module in self.modules.glob('workbench*.py'):
            loaded = importlib.import_module(module.stem)
            self.assertTrue(Path(loaded.__file__).resolve().is_relative_to(self.modules))
        EVENTS.append({'test': self.id(), 'clean_runtime': str(self.modules),
                       'module_files': {name: module.__file__ for name, module in sys.modules.items() if name.startswith('workbench')},
                       'fixture_lf': True, 'fixture_books': len(BOOKS), 'fixture_units': len(BOOKS)*len(UNITS)})
        self.assertFalse(OLD & sys.modules.keys())
        self.assertFalse(any(legacy(p) for p in self.modules.iterdir()))
        self.data = self.wb.defaults() | {'root': str(self.root), 'port': self.port()}

    def fixture(self, book, name):
        files = {'main.tex': '\\title{隔离测试书}\n\\chapter{测试章}\n\\section{测试节}\n\\input{Content/u1}\n\\input{Content/u2}\n',
                 'Source.md': '# 合成测试来源\n不含真实教材内容。\n',
                 'Probe_Content.md': '| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n',
                 'Materials/C1/S1/review.md': '| 目编号 | TeX | 标题 | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 | 疑点 | 结论 |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n'}
        for i, uid in enumerate(UNITS, 1):
            files['Probe_Content.md'] += f'| {uid} | Content/u{i}.tex | Materials/{uid} |\n'
            files['Materials/C1/S1/review.md'] += f'| {uid} | Content/u{i}.tex | 合成单位{i} | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | 未检查 |\n'
            files[f'Content/u{i}.tex'] = f'\\subsection{{合成单位{i}}}\n合成正文 needle-{name}-{i}\n'
            files[f'Materials/{uid}/record.md'] = f'# {uid}\n- TeX：Content/u{i}.tex\n'
            for kind in ('body', 'proof'):
                files[f'Materials/{uid}/{kind}.md'] = '合成资料，不代表审核。\n'
        for relative, text in files.items():
            p = book / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode('utf-8'))
            self.assertNotIn(b'\r', p.read_bytes(), '夹具必须无CR')

    def restore(self):
        for name in list(sys.modules):
            if name.startswith('workbench') or name in OLD:
                sys.modules.pop(name, None)
        sys.modules.update(self.old_modules)
        sys.path[:] = self.old_path
        sys.meta_path.remove(self.finder)

    @staticmethod
    def port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def start(self, data):
        session = self.wb.Session()
        session.start(data | {'port': self.port()}, self.config, no_browser=True)
        self.sessions.append(session)
        return session.server

    def stop(self):
        for session in self.sessions:
            session.stop()
        self.sessions.clear()

    def request(self, server, route, payload=None, status=200):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
        try:
            conn.request('GET' if payload is None else 'POST', route,
                         None if payload is None else json.dumps(payload),
                         {'Origin': server.origin, 'X-Workbench-CSRF': server.token, 'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read()
            result = json.loads(raw) if 'json' in response.getheader('Content-Type', '') else raw.decode('utf-8')
            EVENTS.append({'test': self.id(), 'route': route, 'status': response.status})
            self.assertEqual(response.status, status, (route, result))
            return result
        finally:
            conn.close()

    def read(self, server, route, **args):
        return self.request(server, route + '?' + urlencode(args))

    def authorize(self):
        # 永久ID是独立合成身份；先登记身份，runtime仍不存在，由HTTP /init创建。
        for name, ident in self.ids.items():
            target = self.shelf / name / 'Materials/workbench/book.json'
            target.parent.mkdir()
            target.write_bytes((json.dumps({'schema_version': 1, 'book_id': ident}) + '\n').encode())
            self.assertFalse(target.with_name('runtime.json').exists())
        granted = self.wb.grant_books(self.data, self.ids, self.config)
        self.wb.save_config(granted, self.config)
        return self.wb.load_config(self.config)

    def save(self, server, book, route, read_route, patch_data, **extra):
        old = self.read(server, read_route, book=book, **extra)
        payload = {'book': book, 'expected': old['sha256'], 'patch': patch_data} | extra
        if route == '/patch-runtime':
            payload['revision'] = old['data']['revision']
        self.request(server, route, payload)
        saved = self.read(server, read_route, book=book, **extra)
        before = snapshot(self.base, self.original_io)
        self.request(server, route, payload, status=409)
        self.assertEqual(before, snapshot(self.base, self.original_io), '409不得产生新备份或修改文件')
        self.assertEqual(saved, self.read(server, read_route, book=book, **extra))
        return saved

    def test_default_readonly_poison_zero_write(self):
        poison = self.root / 'Tools/progress'
        poison.mkdir(parents=True)
        for name in ('progress_marks.json', 'progress_settings.json', 'progress.conf'):
            with self.original_io(poison / name, 'wb') as stream:
                stream.write(b'{"done":"injected-old-raw","math":"done"}')
        before = snapshot(self.base, self.original_io)
        self.writes.clear()
        self.readonly = True
        server = self.start(self.data)
        for route in ('/session', '/navigation', '/data', '/changes?since=%7B%7D&force=1'):
            self.assertNotIn('injected-old-raw', json.dumps(self.request(server, route)))
        for name in BOOKS:
            for uid in UNITS:
                review = self.read(server, '/review', book=name, unit=uid)
                self.assertEqual(review['row']['数学审核'], '未检查')
            self.request(server, '/init', {'book': name, 'confirm': True}, status=403)
        self.assertEqual(before, snapshot(self.base, self.original_io))
        self.assertEqual(self.old_reads, [])
        self.assertEqual(self.writes, [])

    def test_eight_books_all_fields_restart_conflicts_source(self):
        granted = self.authorize()
        server = self.start(granted)
        session_id = self.request(server, '/session')['session_id']
        self.assertEqual(set(self.request(server, '/session')['write_books']), set(BOOKS))
        persisted = {}
        for name in BOOKS:
            self.request(server, '/init', {'book': name, 'confirm': True})
            self.assertTrue((self.shelf / name / 'Materials/workbench/runtime.json').is_file())
            self.request(server, '/create-summaries', {'book': name, 'confirm': True})
            for field, value in [('plan', list(UNITS)), ('current_body', UNITS[0]),
                                 ('current_proof', UNITS[1]), ('current_summary', 'C1/S1'),
                                 ('version_basis', {UNITS[0]: hashlib.sha256((self.shelf / name / 'Content/u1.tex').read_bytes()).hexdigest()})]:
                runtime = self.save(server, name, '/patch-runtime', '/runtime', {field: value})
                self.assertEqual(runtime['data'][field], value)
            for uid in UNITS:
                review = self.save(server, name, '/patch-review', '/review',
                                   {'body': '进行中', 'source': '进行中', 'math': '进行中', 'proof': '待补',
                                    'issues': '合成验收待补', 'conclusion': '仅验证保存，不代表数学通过'}, unit=uid)
                for column, state in {'正文整理': '进行中', '来源对照': '进行中', '数学审核': '进行中', '证明回填': '待补',
                                      '疑点': '合成验收待补', '结论': '仅验证保存，不代表数学通过'}.items():
                    self.assertEqual(review['row'][column], state)
                for stage in ('body', 'source', 'math', 'proof'):
                    self.assertEqual(review['basis_status'][stage], 'current')
                persisted[(name, '/review', uid)] = review
            summary = self.save(server, name, '/patch-summary', '/summary',
                                {'summary': '待补', 'reason': '仅隔离验收，待补'}, scope='C1/S1')
            self.assertEqual(summary['state'], '待补')
            self.assertEqual(summary['basis_status'], 'current')
            persisted[(name, '/runtime', '')] = runtime
            persisted[(name, '/summary', 'C1/S1')] = summary
        # 两个unit共用review文件；末次保存后重新获取完整文件SHA及各行。
        for (name, route, identifier) in list(persisted):
            extra = {'unit': identifier} if route == '/review' else {'scope': identifier} if route == '/summary' else {}
            persisted[(name, route, identifier)] = self.read(server, route, book=name, **extra)
        self.stop()
        before = snapshot(self.base, self.original_io)
        server = self.start(granted)
        self.assertNotEqual(session_id, self.request(server, '/session')['session_id'])
        for (name, route, identifier), expected in persisted.items():
            extra = {'unit': identifier} if route == '/review' else {'scope': identifier} if route == '/summary' else {}
            self.assertEqual(expected, self.read(server, route, book=name, **extra))
        self.assertEqual(before, snapshot(self.base, self.original_io))
        changes = self.request(server, '/changes?since=%7B%7D&force=1')
        since = {book['name']: book['version'] for book in changes['books']}
        scans = server.changes.scans
        target = self.shelf / BOOKS[0] / 'Content/u1.tex'
        old_stat = target.stat()
        target.write_bytes(target.read_bytes() + b'\n% external temp append\n')
        self.assertNotEqual((old_stat.st_size, old_stat.st_mtime_ns), (target.stat().st_size, target.stat().st_mtime_ns))
        url = '/changes?' + urlencode({'since': json.dumps(since)})
        cached = self.request(server, url)
        self.assertTrue(cached['cached'])
        self.assertEqual(server.changes.scans, scans)
        forced = self.request(server, url + '&force=1')
        changed = next(book for book in forced['books'] if book['name'] == BOOKS[0])
        self.assertIn('Content/u1.tex', changed['modified'])
        self.assertTrue(changed['changed'])
        review = self.read(server, '/review', book=BOOKS[0], unit=UNITS[0])
        for stage in ('body', 'source', 'math', 'proof'):
            self.assertEqual(review['basis_status'][stage], 'stale')
        self.assertEqual(review['row'], persisted[(BOOKS[0], '/review', UNITS[0])]['row'])
        self.assertEqual(self.read(server, '/summary', book=BOOKS[0], scope='C1/S1')['basis_status'], 'stale')
        self.assertEqual(self.old_reads, [])
        EVENTS.append({'eight_book_order': list(BOOKS), 'permanent_ids': self.ids, 'all_fields_reopened': True})

    def test_identity_foreign_root_revoke_and_root_reset(self):
        granted = self.authorize()
        server = self.start(granted)
        self.request(server, '/init', {'book': BOOKS[0], 'confirm': True})
        target = self.shelf / BOOKS[1] / 'Materials/workbench/book.json'
        old = target.read_bytes()
        target.write_bytes((json.dumps({'schema_version': 1, 'book_id': str(uuid.uuid4())}) + '\n').encode())
        before = snapshot(self.base, self.original_io)
        self.request(server, '/patch-runtime', {'book': BOOKS[0], 'expected': '0'*64, 'revision': 0, 'patch': {'plan': []}}, status=403)
        self.assertFalse(self.request(server, '/session')['allow_write'])
        self.assertEqual(before, snapshot(self.base, self.original_io))
        target.write_bytes(old)
        foreign = self.base / 'foreign'
        for name in BOOKS:
            self.fixture(foreign / name, name)
        changed = self.wb.change_root(granted, str(foreign), self.config)
        for key, expected in {'allow_write': False, 'allow_open': False, 'write_books': [], 'write_book_ids': {}, 'write_root': '', 'write_book_id': ''}.items():
            self.assertEqual(changed[key], expected)
        server.root = foreign
        server.shelf = foreign
        server.write_validator = lambda: self.wb.write_permission(granted | {'root': str(foreign)}, self.config)
        before = snapshot(self.base, self.original_io)
        self.request(server, '/init', {'book': BOOKS[0], 'confirm': True}, status=403)
        self.assertEqual(before, snapshot(self.base, self.original_io))


def real_snapshot():
    targets = [WORKSPACE / 'LaTeX_Notes']
    targets += [PRODUCT / name for name in ('workbench_local.json', 'progress_marks.json', 'progress_settings.json', 'progress.conf', 'progress_marks.json.bak', 'progress_settings.json.bak')]
    result = {}
    for target in targets:
        if target.is_dir():
            result.update({str(target / rel): digest for rel, digest in snapshot(target).items()})
        elif target.is_file():
            result[str(target)] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result


if __name__ == '__main__':
    if '--worker' in sys.argv:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CleanSave)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        evidence = Path(sys.argv[sys.argv.index('--worker') + 1])
        evidence.write_text(json.dumps({'tests_run': result.testsRun, 'failures': len(result.failures),
                            'errors': len(result.errors), 'events': EVENTS,
                            'success': result.wasSuccessful()}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        raise SystemExit(0 if result.wasSuccessful() else 1)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=WORKSPACE / 'outputs/no_legacy_acceptance_20261013/save')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    before = real_snapshot()
    proc = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), '--worker', str(args.output / 'worker.json')], capture_output=True, text=True, encoding='utf-8')
    after = real_snapshot()
    (args.output / 'log.txt').write_text(proc.stdout + proc.stderr, encoding='utf-8', newline='\n')
    result = json.loads((args.output / 'worker.json').read_text(encoding='utf-8')) if (args.output / 'worker.json').is_file() else {}
    statuses = {}
    for event in result.get('events', []):
        if 'status' in event:
            key = str(event['status'])
            statuses[key] = statuses.get(key, 0) + 1
    result.update(http_status_counts=statuses, real_files_hashed=len(before),
                  exit_code=proc.returncode, interpreter=sys.executable, real_readonly_hashes_before=before,
                  real_readonly_hashes_after=after, real_files_unchanged=before == after,
                  cold_subprocess=True, fixture_units_per_book=2,
                  scope='仅后端保存验收；浏览器草稿目标删除由独立UI验收负责')
    (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(proc.stdout + proc.stderr)
    print('results:', args.output / 'results.json', 'exit:', proc.returncode, '真实文件不变:', before == after)
    raise SystemExit(proc.returncode if before == after else 2)
