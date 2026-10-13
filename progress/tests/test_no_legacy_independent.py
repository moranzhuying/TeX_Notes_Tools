"""临时可移植新版回归：无旧模块、禁止旧状态读、默认零写，不触及真实书架。"""
import builtins
import hashlib
import http.client
import importlib
import importlib.abc
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
OLD_MODULES = {'progress', 'progress_ui', 'workbench_legacy'}
OLD_NAMES = {'progress_marks.json', 'progress_settings.json', 'progress.conf'}


class RejectOld(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in OLD_MODULES:
            raise AssertionError('禁止导入旧模块：' + fullname)


class Poison(types.ModuleType):
    def __getattr__(self, name):
        raise AssertionError('禁止访问旧progress：' + name)


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='新版无旧依赖 ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.modules = self.base / 'runtime'
        self.modules.mkdir()
        for source in PRODUCT.glob('workbench*.py'):
            if source.stem != 'workbench_legacy':
                shutil.copyfile(source, self.modules / source.name)
        shutil.copyfile(PRODUCT / 'workbench_editor.html', self.modules / 'workbench_editor.html')
        self.root = self.base / 'workspace'
        self.book = self.root / 'LaTeX_Notes/ProbeBook'
        material = self.book / 'Materials/C1/S1/N1'
        material.mkdir(parents=True)
        self.uid = 'C1/S1/N1'
        files = {
            'main.tex': '\\title{独立书名}\n\\chapter{独立章节}\n\\section{独立小节}\n\\input{unit}\n',
            'unit.tex': '\\subsection{独立单位}\n独立正文 needle\n% TODO: R1 独立问题\n',
            'Probe_Content.md': '| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n| C1/S1/N1 | unit.tex | Materials/C1/S1/N1 |\n',
            'Source.md': '# 隔离来源\n',
            'Materials/C1/S1/N1/record.md': '# C1/S1/N1\n- TeX：unit.tex\n',
            'Materials/C1/S1/N1/body.md': '隔离正文资料\n',
            'Materials/C1/S1/N1/proof.md': '隔离证明资料\n',
            'Materials/C1/S1/review.md': '| 目编号 | TeX | 标题 | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 | 疑点 | 结论 |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| C1/S1/N1 | unit.tex | 独立单位 | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 | 无 | 未检查 |\n',
        }
        for name, text in files.items():
            (self.book / name).write_text(text, encoding='utf-8', newline='\n')
        self.assertNotIn(b'\r', (self.book / 'Materials/C1/S1/review.md').read_bytes(), '审核夹具必须真实为LF')
        self.assertFalse((self.modules / 'progress.py').exists())
        self.addCleanup(self.restore_modules)
        self.old_modules = {k: v for k, v in sys.modules.items() if k.startswith('workbench') or k in OLD_MODULES}
        for name in self.old_modules:
            sys.modules.pop(name, None)
        self.old_path = list(sys.path)
        sys.path[:] = [str(self.modules)] + [p for p in sys.path if Path(p or '.').resolve() != PRODUCT]
        self.old_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        self.finder = RejectOld()
        sys.meta_path.insert(0, self.finder)
        self.reads = []
        self.writes = []
        self.readonly = False
        original_builtin, original_io = builtins.open, io.open
        self.snapshot_open = original_io
        def guarded(original):
            def opening(file, mode='r', *args, **kwargs):
                if isinstance(file, (str, bytes, Path)):
                    path = Path(file)
                    if path.name.lower() in OLD_NAMES or path.name.lower().startswith(('progress_marks.', 'progress_settings.')):
                        self.reads.append(str(path))
                        raise AssertionError('禁止访问旧状态：' + str(path))
                    if any(c in mode for c in 'wax+'):
                        self.writes.append(str(path))
                        if self.readonly:
                            raise AssertionError('默认只读禁止写文件：' + str(path))
                return original(file, mode, *args, **kwargs)
            return opening
        self.patches = [patch('builtins.open', guarded(original_builtin)), patch('io.open', guarded(original_io))]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        self.servers = []
        self.addCleanup(self.close_servers)

    def restore_modules(self):
        for name in list(sys.modules):
            if name.startswith('workbench') or name in OLD_MODULES:
                sys.modules.pop(name, None)
        sys.modules.update(self.old_modules)
        sys.path[:] = self.old_path
        sys.meta_path.remove(self.finder)
        sys.dont_write_bytecode = self.old_bytecode

    def close_servers(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.servers.clear()

    def start(self, authorized=False):
        module = importlib.import_module('workbench_server')
        server = module.Server(self.root, allow_write=authorized, write_books=['ProbeBook'] if authorized else [])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return server

    def request(self, server, route, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=20)
        headers = {'Origin': server.origin, 'X-Workbench-CSRF': server.token, 'Content-Type': 'application/json'}
        try:
            connection.request('POST' if payload is not None else 'GET', route, json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if 'json' in response.getheader('Content-Type', '') else raw.decode('utf-8')
        finally:
            connection.close()

    def snapshot(self):
        result = {}
        for path in self.base.rglob('*'):
            if path.is_file():
                with self.snapshot_open(path, 'rb') as stream:
                    result[path.relative_to(self.base).as_posix()] = hashlib.sha256(stream.read()).hexdigest()
        return result

    def exercise_reads(self):
        before = self.snapshot()
        self.readonly = True
        for path in self.modules.glob('workbench*.py'):
            importlib.import_module(path.stem)
        server = self.start()
        routes = ['/', '/session', '/navigation', '/data', '/source?book=ProbeBook&unit='+self.uid+'&line=1',
                  '/search?q=needle&book=ProbeBook&limit=20', '/aggregate?book=ProbeBook', '/pdfinfo?book=ProbeBook',
                  '/runtime?book=ProbeBook', '/review?book=ProbeBook&unit='+self.uid, '/summary?book=ProbeBook&scope=C1',
                  '/changes?since=%7B%7D', '/participation?book=ProbeBook&unit='+self.uid]
        results = {}
        for route in routes:
            status, results[route] = self.request(server, route)
            self.assertEqual(status, 200, (route, results[route]))
        self.assertEqual(self.request(server, '/init', {'book': 'ProbeBook', 'confirm': True})[0], 403)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.writes, [])
        self.assertEqual(self.reads, [])
        review = results['/review?book=ProbeBook&unit='+self.uid]
        self.assertEqual(review['row']['数学审核'], '未检查')
        self.assertEqual(review['row']['正文整理'], '未检查')
        navigation = results['/navigation']['books'][0]
        self.assertIn('独立书名', json.dumps(navigation, ensure_ascii=False))
        self.assertIn('独立单位', json.dumps(navigation, ensure_ascii=False))
        self.assertIn('独立章节', json.dumps(navigation, ensure_ascii=False))
        self.assertIn('独立小节', json.dumps(navigation, ensure_ascii=False))
        self.assertIn('needle', json.dumps(results['/source?book=ProbeBook&unit='+self.uid+'&line=1'], ensure_ascii=False))
        self.assertIn('needle', json.dumps(results['/search?q=needle&book=ProbeBook&limit=20'], ensure_ascii=False))
        self.assertEqual(results['/runtime?book=ProbeBook'], {'initialized': False})
        self.assertEqual(results['/summary?book=ProbeBook&scope=C1'], {'initialized': False})
        self.assertNotIn('injected', json.dumps(results, ensure_ascii=False))
        return results

    def test_cold_import_absent_legacy_and_default_zero_write(self):
        self.exercise_reads()
        self.assertFalse(OLD_MODULES & sys.modules.keys())

    def test_progress_poison_sentinel_all_read_routes(self):
        sys.modules['progress'] = Poison('progress')
        self.exercise_reads()

    def test_poison_old_state_corpus_ignored(self):
        directory = self.root / 'Tools/progress'
        directory.mkdir(parents=True)
        corpus = [
            '{"entries":{"unit.tex":{"marks":{"math":"done"},"note":"injected"}},"nodes":{}}',
            'injected 非法JSON垃圾',
            '{"entries":"injected","nodes":["injected"]}',
        ]
        for raw in corpus:
            with self.subTest(poison=raw):
                for name in OLD_NAMES:
                    with self.snapshot_open(directory / name, 'w', encoding='utf-8') as stream:
                        stream.write(raw)
                self.exercise_reads()
                self.close_servers()

    def test_authorized_temp_save_conflict_and_reopen(self):
        server = self.start(authorized=True)
        self.assertEqual(self.request(server, '/init', {'book': 'ProbeBook', 'confirm': True})[0], 200)
        self.assertEqual(self.request(server, '/create-summaries', {'book': 'ProbeBook', 'confirm': True})[0], 200)
        operations = [('/runtime?book=ProbeBook', '/patch-runtime', {'patch': {'plan': [self.uid]}}),
                      ('/review?book=ProbeBook&unit='+self.uid, '/patch-review', {'unit': self.uid, 'patch': {'body': '进行中'}}),
                      ('/summary?book=ProbeBook&scope=C1', '/patch-summary', {'scope': 'C1', 'patch': {'summary': '进行中', 'reason': '隔离验证'}})]
        expected = []
        for route, save, extra in operations:
            status, old = self.request(server, route)
            self.assertEqual(status, 200)
            payload = {'book': 'ProbeBook', 'expected': old['sha256']} | extra
            if save == '/patch-runtime':
                payload['revision'] = old['data']['revision']
            self.assertEqual(self.request(server, save, payload)[0], 200)
            self.assertEqual(self.request(server, save, payload)[0], 409)
            expected.append((route, self.request(server, route)[1]))
        self.close_servers()
        self.assertTrue(self.writes, '显式授权隔离保存必须确实落盘')
        self.assertTrue(all(Path(name).resolve().is_relative_to(self.base) for name in self.writes), '保存不得逃出隔离目录')
        before = self.snapshot()
        self.writes.clear()
        self.readonly = True
        reopened = self.start()
        for route, persisted in expected:
            self.assertEqual(self.request(reopened, route), (200, persisted))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.reads, [])
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    if '--isolated-worker' in sys.argv:
        sys.argv.remove('--isolated-worker')
        unittest.main(verbosity=2)
    else:
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--isolated-worker'])
        raise SystemExit(process.returncode)
