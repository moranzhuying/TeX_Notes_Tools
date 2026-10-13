"""启动配置隔离回归：python -m unittest discover -s progress/tests -p test_workbench_launcher.py。"""
import contextlib
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import urlopen

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS / 'progress'))
sys.path.insert(0, str(TOOLS))
import workbench_launcher as wb
import launcher


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='workbench startup ')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'shelf with spaces'
        self.book = self.make_book(self.root, 'Probe')
        self.config = self.base / 'local.json'
        self.data = wb.defaults() | {'root': 'shelf with spaces'}
        wb.save_config(self.data, self.config)

    def make_book(self, root, name):
        book = root / name
        (book / 'Materials/C1/N1').mkdir(parents=True)
        (book / 'unit.tex').write_text('正文\n', encoding='utf-8')
        (book / 'Probe_Content.md').write_text('| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/N1 | unit.tex | Materials/C1/N1 |\n', encoding='utf-8')
        return book

    def drive(self, answers):
        with patch.object(sys, 'stdin', io.StringIO(answers)), patch.object(wb.webbrowser, 'open', side_effect=AssertionError('不得打开浏览器')), contextlib.redirect_stdout(io.StringIO()) as output:
            status = wb.panel(self.config, True)
        return status, output.getvalue()

    def free_port(self):
        with socket.socket() as pick:
            pick.bind(('127.0.0.1', 0))
            return pick.getsockname()[1]

    def test_config_and_root_permissions(self):
        self.assertEqual(wb.load_config(self.config), self.data)
        self.assertEqual(wb.root_path(self.data['root'], self.config), self.root.resolve())
        self.assertEqual(self.data['port'], 7656)
        self.assertFalse(wb.defaults()['allow_write'])
        self.assertEqual(wb.defaults()['write_books'], [])
        self.assertEqual(wb.defaults()['write_root'], '')
        old = self.data | {'allow_open': True, 'allow_write': True, 'write_books': ['Probe']}
        other = self.base / 'second shelf'
        self.make_book(other, 'Other')
        changed = wb.change_root(old, str(other), self.config)
        self.assertFalse(changed['allow_open'])
        self.assertFalse(changed['allow_write'])
        self.assertEqual(changed['write_books'], [])
        self.assertEqual(wb.change_root(old, str(self.root), self.config)['write_books'], ['Probe'])

    def test_bad_paths_and_registration(self):
        for bad in ('', str(self.book / 'unit.tex'), str(self.base / 'missing'), str(self.base)):
            with self.subTest(root=bad), self.assertRaises((ValueError, OSError)):
                wb.root_path(bad, self.config)
        for bad in ('relative.exe', str(self.base / 'missing.exe'), str(self.book / 'unit.tex')):
            with self.subTest(texstudio=bad), self.assertRaises(ValueError):
                wb.checked(self.data | {'texstudio': bad})
        second = self.book / 'Second_Content.md'
        second.write_bytes((self.book / 'Probe_Content.md').read_bytes())
        with self.assertRaisesRegex(ValueError, '登记入口不唯一'):
            wb.root_path(str(self.root), self.config)
        second.unlink()
        (self.book / 'unit.tex').unlink()
        with self.assertRaisesRegex(ValueError, '绑定无效'):
            wb.root_path(str(self.root), self.config)

    def test_registration_symlink_escape(self):
        outside = self.base / 'outside.md'
        outside.write_bytes((self.book / 'Probe_Content.md').read_bytes())
        entry = self.book / 'Probe_Content.md'
        original = entry.read_bytes()
        entry.unlink()
        try:
            entry.symlink_to(outside)
        except OSError:
            entry.write_bytes(original)
            self.skipTest('系统未授予符号链接创建权限')
        with self.assertRaisesRegex(ValueError, '越过书界'):
            wb.root_path(str(self.root), self.config)

    def test_corrupt_and_atomic_failure(self):
        self.config.write_text('{坏配置', encoding='utf-8')
        original = self.config.read_bytes()
        status, output = self.drive('')
        self.assertEqual(status, 2)
        self.assertIn('原文件保留', output)
        self.assertEqual(self.config.read_bytes(), original)
        wb.save_config(self.data, self.config)
        with patch.object(wb.os, 'replace', side_effect=OSError('模拟替换失败')), self.assertRaises(OSError):
            wb.save_config(self.data | {'port': 12345}, self.config)
        self.assertEqual(wb.load_config(self.config), self.data)
        self.assertEqual(list(self.base.glob('local.json.*.tmp')), [])

    def test_occupied_port_not_reused(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            session = wb.Session()
            with self.assertRaises(OSError):
                session.start(self.data | {'port': occupied.getsockname()[1]}, self.config, True)
            self.assertIsNone(session.server)

    def test_incomplete_legacy_permission_readonly_and_cleanup(self):
        session = wb.Session()
        self.addCleanup(session.stop)
        port = self.free_port()
        data = self.data | {'port': port, 'allow_open': True, 'allow_write': True, 'write_books': ['Probe']}
        with patch.object(wb.webbrowser, 'open', side_effect=AssertionError('不得打开浏览器')):
            origin = session.start(data, self.config, True)
        self.assertFalse(session.server.allow_write)
        self.assertEqual(session.server.write_books, set())
        self.assertTrue(session.server.allow_open)
        with urlopen(origin + '/navigation', timeout=3) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(ValueError):
            session.start(data, self.config, True)
        session.stop()
        with socket.socket() as released:
            released.bind(('127.0.0.1', port))

    def test_stdin_configuration(self):
        status, output = self.drive('2\nabc\n1\n\n3\n4\n\n0\n')
        self.assertEqual(status, 0)
        self.assertIn('操作失败', output)
        self.assertTrue(wb.load_config(self.config)['allow_open'])

    def test_stop_cancel_and_confirm(self):
        port = self.free_port()
        wb.save_config(self.data | {'port': port}, self.config)
        status, output = self.drive('5\n2\n6\nn\n0\nn\n6\ny\n0\n')
        self.assertEqual(status, 0)
        self.assertIn('修改配置前请先选择6', output)
        self.assertEqual(output.count('已取消停止'), 2)
        self.assertIn('尚未保存的输入', output)
        self.assertIn('实际写入：禁用', output)
        with socket.socket() as released:
            released.bind(('127.0.0.1', port))
        status, output = self.drive('5\n0\ny\n')
        self.assertEqual(status, 0)
        with socket.socket() as released:
            released.bind(('127.0.0.1', port))

    def test_eof_cleanup(self):
        port = self.free_port()
        wb.save_config(self.data | {'port': port}, self.config)
        status, output = self.drive('5\n')
        self.assertEqual(status, 0)
        self.assertIn('输入结束或中断', output)
        with socket.socket() as released:
            released.bind(('127.0.0.1', port))

    def test_main_menu_compatibility(self):
        four = next(x for x in launcher.MENU if x[0] == '4')
        fifteen = next(x for x in launcher.MENU if x[0] == '15')
        self.assertEqual(four[2:4], ('progress/workbench_launcher.py', '面板'))
        self.assertEqual(fifteen[2:4], ('progress/progress.py', '后台'))
        numbers = [int(x[0]) for x in launcher.MENU]
        expected = list(range(1, 14)) + ([14] if any(x[2] == 'spec_sync/spec_sync.py' for x in launcher.MENU) else []) + [15]
        self.assertEqual(numbers, expected)
        self.assertEqual(launcher.SUBMIT_NO, '12')
        with patch.object(launcher.subprocess, 'run') as run, patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertTrue(launcher.run(four))
            run.assert_called_once()
            popen.assert_not_called()
        for path in (TOOLS / 'launcher.py', TOOLS / 'progress/workbench_launcher.py', TOOLS / 'README.md', TOOLS / '.gitignore'):
            self.assertNotIn(b'\r', path.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
