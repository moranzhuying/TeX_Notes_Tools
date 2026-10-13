"""隔离搜索快照与打开鲜度契约；不启动真实编辑器。"""
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench_features as features
import workbench_pdf as pdf
import workbench_server as server


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / '中文 空格 & [合法] #定位.tex'
        self.original = ''.join(f'% marker 第{i}行\n' for i in range(1, 41)).encode()
        self.path.write_bytes(self.original)
        self.unit = {'id': 'C01', 'tex_path': self.path.name, 'title': '临时单位'}
        test = self

        class Store:
            book = test.root

            def path(self, _):
                return test.path

            def navigation(self):
                return {'units': [test.unit]}

        self.store = Store()
        self.srv = server.Server(self.root, allow_open=True)
        self.srv.store = lambda *a, **k: self.store
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.register = patch.object(pdf, 'registered_tex', return_value=(self.unit, self.path))
        self.register.start()
        self.exe = patch.object(pdf, 'executable', return_value='C:/Program Files/texstudio/texstudio.exe')
        self.exe.start()
        self.spawn = patch.object(pdf.subprocess, 'Popen')
        self.mock_spawn = self.spawn.start()

    def tearDown(self):
        self.spawn.stop()
        self.exe.stop()
        self.register.stop()
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, body):
        conn = http.client.HTTPConnection('127.0.0.1', self.srv.server_port)
        conn.request('POST', '/open', json.dumps(body), {'Content-Type': 'application/json',
                     'Origin': self.srv.origin, 'X-Workbench-CSRF': self.srv.token})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def body(self, line=17):
        return {'book': 'Book', 'unit': 'C01', 'confirm': True, 'line': line,
                'path': self.path.name, 'expected': hashlib.sha256(self.original).hexdigest()}

    def test_search_source_snapshot(self):
        hit = features.search(self.srv, 'marker', 'Book')['results'][0]
        self.assertEqual(hit['sha256'], self.body()['expected'])
        self.assertEqual(features.source(self.store, 'C01', '17')['sha256'], hit['sha256'])

    def test_stale_insert_delete_equal_length(self):
        variants = [b'% inserted\n' + self.original, self.original.split(b'\n', 1)[1],
                    self.original.replace(b'marker', b'xxxxxx', 1)]
        for raw in variants:
            with self.subTest(kind=len(raw)):
                self.path.write_bytes(raw)
                status, data = self.request(self.body())
                self.assertEqual(status, 409, data)
                self.assertIn('已变化', data['error'])
                self.mock_spawn.assert_not_called()

    def test_bounds_and_special_path(self):
        for line in (1, 17, 40):
            status, data = self.request(self.body(line))
            self.assertEqual(status, 200, data)
            self.assertFalse(data['line_located'])
            self.assertEqual(self.mock_spawn.call_args.args[0][-3:], ['--line', str(line), str(self.path)])
        self.mock_spawn.reset_mock()
        for line in (0, 41, True, '17'):
            self.assertEqual(self.request(self.body(line))[0], 400)
        self.mock_spawn.assert_not_called()

    def test_expected_required_and_current_unit_compatible(self):
        body = self.body()
        del body['expected']
        self.assertEqual(self.request(body)[0], 400)
        self.assertEqual(self.request({'book': 'Book', 'unit': 'C01', 'confirm': True})[0], 200)

    def test_path_and_hash_validation(self):
        for field, value in [('path', 'wrong.tex'), ('expected', 'invalid')]:
            body = self.body()
            body[field] = value
            self.assertEqual(self.request(body)[0], 400)
        self.mock_spawn.assert_not_called()

    def test_lock_held_during_spawn(self):
        acquired = []
        def spawn(*args, **kwargs):
            def other():
                ok = self.srv.open_lock.acquire(blocking=False)
                acquired.append(ok)
                if ok:
                    self.srv.open_lock.release()
            t = threading.Thread(target=other)
            t.start()
            t.join()
        self.mock_spawn.side_effect = spawn
        self.assertEqual(self.request(self.body())[0], 200)
        self.assertEqual(acquired, [False])


if __name__ == '__main__':
    unittest.main(verbosity=2)
