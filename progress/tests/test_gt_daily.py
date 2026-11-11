"""GT许可及HTTP保存隔离验收；真实笔记只读取。"""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

WS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WS / 'Tools/progress'))
import workbench_launcher as wb
import workbench_readonly as ro
import workbench_store as st


class GTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence_root = WS / 'outputs/workbench_gt_daily_20261013'
        evidence_root.mkdir(parents=True, exist_ok=True)
        cls.evidence = Path(tempfile.mkdtemp(prefix='gt_daily_', dir=evidence_root))
        book = next(b for b in ro.scan(WS)['books'] if b['name'] == 'General_Topology')
        unit = next(u for u in book['units'] if u['id'].startswith('C05/S02'))
        units = [u for u in book['units'] if u['review_path'] == unit['review_path']]
        cls.uid = unit['id']
        cls.source = cls.evidence / 'fixture'
        cls.source.mkdir()
        files = {unit['binding_provenance']['path'], unit['review_path'], 'Source.md'}
        for u in units:
            files.add(u['tex_path'])
            files.update(u['materials_path'] + '/' + n for n in ('record.md', 'body.md', 'proof.md'))
        for name in files:
            target = cls.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(WS / 'LaTeX_Notes/General_Topology' / name, target)
        (cls.source / unit['binding_provenance']['path']).write_text('| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n' + ''.join('| '+u['display_id']+' | '+u['tex_path']+' | '+u['materials_path']+' |\n' for u in units), encoding='utf-8')

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='case_', dir=self.evidence))
        self.root = self.base / 'shelf'
        shutil.copytree(self.source, self.root / 'General_Topology')
        self.store = st.BookStore(self.root, 'General_Topology')
        self.store.init()
        self.store.create_summaries()
        self.config = self.base / 'local.json'
        self.data = wb.defaults() | {'root': str(self.root), 'port': 0}
        self.data['port'] = 7656
        self.identity = self.store.identity()['book_id']
        self.granted = wb.grant_gt(self.data, self.identity, self.config)
        self.session = wb.Session()
        self.addCleanup(self.session.stop)

    def start(self, data):
        # 服务允许随机隔离端口，配置校验仍验证有效真实端口。
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.session.start(data | {'port': port}, self.config, True)

    def request(self, path, data=None):
        server = self.session.server
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=20)
        headers = {'Origin': server.origin, 'X-Workbench-CSRF': server.token, 'Content-Type': 'application/json'}
        conn.request('POST' if data is not None else 'GET', path, None if data is None else json.dumps(data), headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_default_readonly(self):
        self.start(self.data)
        self.assertFalse(self.session.server.allow_write)
        self.assertEqual(self.request('/init', {'book': 'General_Topology', 'confirm': True})[0], 403)

    def test_root_identity_and_same_name(self):
        self.assertEqual(wb.write_permission(self.granted, self.config), (True, ('General_Topology',)))
        external = self.base / 'external'
        shutil.copytree(self.root, external)
        with self.assertRaises(ValueError):
            wb.write_permission(self.granted | {'root': str(external)}, self.config)
        with self.assertRaises(ValueError):
            wb.grant_gt(self.data, '错误ID', self.config)
        changed = wb.change_root(self.granted, str(external), self.config)
        self.assertEqual(changed['write_books'], [])
        self.assertEqual(changed['write_root'], '')
        self.assertFalse(changed['allow_write'])
        with self.assertRaises(ValueError):
            wb.write_permission(self.granted | {'write_books': ['Algebra']}, self.config)

    def test_independent_open_and_panel_confirmation(self):
        import contextlib
        import io
        from unittest.mock import patch
        wb.save_config(self.data, self.config)
        with patch.object(sys, 'stdin', io.StringIO('7\n'+self.identity+'\nn\n0\n')), contextlib.redirect_stdout(io.StringIO()):
            wb.panel(self.config, True)
        self.assertFalse(wb.load_config(self.config)['allow_write'])
        with patch.object(sys, 'stdin', io.StringIO('7\n'+self.identity+'\nGT\n0\n')), contextlib.redirect_stdout(io.StringIO()):
            wb.panel(self.config, True)
        self.assertTrue(wb.load_config(self.config)['allow_write'])
        self.assertFalse(wb.load_config(self.config)['allow_open'])
        self.start(self.granted | {'allow_open': True})
        self.assertTrue(self.session.server.allow_open)
        self.assertTrue(self.session.server.allow_write)

    def test_gt_runtime_review_summary_conflicts(self):
        self.start(self.granted)
        status, runtime = self.request('/runtime?book=General_Topology')
        self.assertEqual(status, 200)
        payload = {'book': 'General_Topology', 'expected': runtime['sha256'], 'revision': runtime['data']['revision'], 'patch': {'plan': [self.uid]}}
        self.assertEqual(self.request('/patch-runtime', payload)[0], 200)
        self.assertEqual(self.request('/patch-runtime', payload)[0], 409)
        status, review = self.request('/review?book=General_Topology&unit='+self.uid)
        payload = {'book': 'General_Topology', 'unit': self.uid, 'expected': review['sha256'], 'patch': {'body': '进行中'}}
        self.assertEqual(self.request('/patch-review', payload)[0], 200)
        self.assertEqual(self.request('/patch-review', payload)[0], 409)
        status, summary = self.request('/summary?book=General_Topology&scope=C05')
        payload = {'book': 'General_Topology', 'scope': 'C05', 'expected': summary['sha256'], 'patch': {'summary': '进行中', 'reason': '隔离验收'}}
        self.assertEqual(self.request('/patch-summary', payload)[0], 200)
        self.assertEqual(self.request('/patch-summary', payload)[0], 409)
        identity = self.root / 'General_Topology/Materials/workbench/book.json'
        identity.write_text('{"book_id":"替换ID"}', encoding='utf-8')
        self.assertEqual(self.request('/patch-summary', payload)[0], 403)

    def test_seven_books_denied_without_initializing(self):
        names = ['Algebra', 'Integral_Theory', 'Topological_Vector_Space', 'Functions_of_a_Real_Variable', 'Spectral_Theory', 'Algebraic_Topology', 'Differential_and_Analytic_Manifolds']
        for name in names:
            shutil.copytree(self.source, self.root / name)
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for n in names for p in (self.root / n).rglob('*') if p.is_file()}
        self.start(self.granted)
        for name in names:
            with self.subTest(book=name):
                for path, extra in [('/init', {'confirm': True}), ('/patch-runtime', {'expected': '0'*64, 'revision': 0, 'patch': {'plan': []}}), ('/patch-review', {'unit': self.uid, 'expected': '0'*64, 'patch': {'body': '进行中'}}), ('/create-summaries', {'confirm': True}), ('/restore', {'backup_id': '隔离不存在', 'expected': '0'*64, 'confirm': True}), ('/patch-summary', {'scope': 'C05', 'expected': '0'*64, 'patch': {'summary': '进行中'}})]:
                    self.assertEqual(self.request(path, {'book': name} | extra)[0], 403)
                self.assertFalse((self.root / name / 'Materials/workbench').exists())
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for n in names for p in (self.root / n).rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main(verbosity=2)
