"""只用临时书架的日常工作台独立回归，不启动编辑器。"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROGRESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRESS))
import workbench_daily as daily
from workbench_store import BookStore, StoreError


class DailyIndependentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='daily independent ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'shelf'
        self.book = self.make_book('Book')
        self.store = BookStore(self.root, self.book)

    def make_book(self, name):
        book = self.root / name
        (book / 'Materials/C1/N1').mkdir(parents=True)
        (book / 'unit.tex').write_text('正文\n', encoding='utf-8')
        (book / 'Probe_Content.md').write_text('| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/N1 | unit.tex | Materials/C1/N1 |\n', encoding='utf-8')
        (book / 'main.tex').write_text('\\input{unit}\n', encoding='utf-8')
        return book

    def discover(self, root):
        return sorted(p for p in root.iterdir() if p.is_dir())

    def changes(self, ttl=0):
        return daily.Changes(self.root, self.discover, ttl=ttl)

    def participation(self, source):
        (self.book / 'main.tex').write_text(source, encoding='utf-8')
        return daily.participation(self.store, 'C1/N1')

    def test_content_registration_pdf_and_book_changes(self):
        changes = self.changes()
        initial = changes.read()['books'][0]
        versions = json.dumps({'Book': initial['version']})
        entry = self.book / 'Probe_Content.md'
        entry.write_text(entry.read_text(encoding='utf-8') + '\n登记注释\n', encoding='utf-8')
        (self.book / 'main.pdf').write_bytes(b'isolated fixture')
        self.make_book('New')
        result = changes.read(versions)
        old = next(b for b in result['books'] if b['name'] == 'Book')
        self.assertIn('Probe_Content.md', old['modified'])
        self.assertIn('main.pdf', old['added'])
        self.assertEqual({b['name'] for b in result['books']}, {'Book', 'New'})
        versions = json.dumps({b['name']: b['version'] for b in result['books']})
        os.utime(self.book / 'main.pdf', ns=(1800000000000000000, 1800000000000000000))
        result = changes.read(versions)
        self.assertIn('main.pdf', next(b for b in result['books'] if b['name'] == 'Book')['modified'])
        shutil.rmtree(self.root / 'New')
        self.assertEqual(changes.read(versions)['removed_books'], ['New'])

    def test_history_repeated_version_after_sixteen(self):
        changes = self.changes()
        unit = self.book / 'unit.tex'
        distinct = set()
        for index in range(20):
            os.utime(unit, ns=(1700000000000000000 + index * 1000000, 1700000000000000000 + index * 1000000))
            distinct.add(changes.read()['books'][0]['version'])
        self.assertEqual(len(distinct), 20, 'fixture必须产生真实不同元数据版本')
        version = changes.read()['books'][0]['version']
        for _ in range(20):
            result = changes.read(json.dumps({'Book': version}))
            self.assertFalse(result['books'][0]['changed'])
        self.assertLessEqual(len(changes.history['Book']), 16)

    def test_permission_error_does_not_report_deleted_files(self):
        changes = self.changes()
        initial = changes.read()['books'][0]
        real_walk = os.walk
        invoked = []
        def denied(top, *args, **kwargs):
            for folder, dirs, files in real_walk(top, *args, **kwargs):
                if Path(folder).resolve() == self.book.resolve():
                    dirs[:] = []
                    yield folder, dirs, []
                    handler = kwargs.get('onerror')
                    if handler:
                        invoked.append(True)
                        handler(PermissionError('隔离模拟拒绝遍历'))
                    return
        with patch.object(daily.os, 'walk', side_effect=denied), self.assertRaises((StoreError, OSError)):
            changes.read(json.dumps({'Book': initial['version']}))
        self.assertEqual(invoked, [True], 'fixture必须实际调用onerror')
        self.assertEqual(changes.books['Book']['version'], initial['version'], '扫描失败必须保留旧快照，不得假报删除')

    def test_symlink_escape_not_statted(self):
        outside = self.base / 'outside'
        outside.mkdir()
        external = outside / 'external.tex'
        external.write_text('外部哨兵', encoding='utf-8')
        link = self.book / 'escape'
        try:
            link.symlink_to(outside, target_is_directory=True)
            (self.book / 'escaped.tex').symlink_to(external)
        except OSError:
            self.skipTest('系统未授予符号链接创建权限')
        real_stat = Path.stat
        def guarded(path, *args, **kwargs):
            if (path == external or path == self.book / 'escaped.tex') and kwargs.get('follow_symlinks', True):
                self.fail('扫描不得stat外部文件或外部链接文件')
            return real_stat(path, *args, **kwargs)
        try:
            with patch.object(Path, 'stat', guarded):
                result = self.changes().read()
        except StoreError:
            return
        self.assertEqual(result['books'][0]['file_count'], 3)

    def test_discovered_book_symlink_escape_not_statted(self):
        outside = self.base / 'external book'
        outside.mkdir()
        external = outside / 'unit.tex'
        external.write_text('外部哨兵', encoding='utf-8')
        link = self.root / 'EscapedBook'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('系统未授予符号链接创建权限')
        real_stat = Path.stat
        def guarded(path, *args, **kwargs):
            if path == external or path == link / 'unit.tex':
                self.fail('discover返回越界书时不得stat其外部文件')
            return real_stat(path, *args, **kwargs)
        try:
            with patch.object(Path, 'stat', guarded):
                result = self.changes().read()
        except (OSError, ValueError):
            return
        self.assertNotIn('EscapedBook', {b['name'] for b in result['books']})

    @unittest.skipUnless(os.name == 'nt', '目录junction仅Windows适用')
    def test_junction_escape_not_statted(self):
        outside = self.base / 'junction outside'
        outside.mkdir()
        external = outside / 'external.tex'
        external.write_text('外部哨兵', encoding='utf-8')
        junction = self.book / 'junction escape'
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
        if result.returncode:
            self.skipTest('当前系统不能创建临时junction')
        self.addCleanup(lambda: os.rmdir(junction) if junction.exists() else None)
        real_stat = Path.stat
        def guarded(path, *args, **kwargs):
            if path == external or path == junction / 'external.tex':
                self.fail('不得stat目录junction外部文件')
            return real_stat(path, *args, **kwargs)
        try:
            with patch.object(Path, 'stat', guarded):
                result = self.changes().read()
        except StoreError:
            return
        self.assertEqual(result['books'][0]['file_count'], 3)

    def test_ttl_concurrent_singleflight(self):
        changes = self.changes(ttl=3600)
        barrier = threading.Barrier(12)
        def read(_):
            barrier.wait(timeout=5)
            return changes.read()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(read, range(12)))
        self.assertEqual(changes.scans, 1)
        self.assertEqual(len({r['books'][0]['version'] for r in results}), 1)

    def test_force_performs_scan_before_ttl(self):
        changes = self.changes(ttl=3600)
        original = changes.read()['books'][0]['version']
        (self.book / 'unit.tex').write_text('改变临时正文长度\n', encoding='utf-8')
        self.assertEqual(changes.read()['books'][0]['version'], original)
        result = changes.read(force=True)
        self.assertNotEqual(result['books'][0]['version'], original)
        self.assertEqual(changes.scans, 2)

    def test_force_rejects_non_boolean(self):
        changes = self.changes(ttl=3600)
        changes.read()
        for invalid in (0, 1, '1', None, [], {}):
            with self.subTest(force=invalid), self.assertRaises(StoreError):
                changes.read(force=invalid)
        self.assertEqual(changes.scans, 1)

    def test_walk_failure_preserves_committed_snapshot(self):
        changes = self.changes(ttl=3600)
        original = changes.read()['books'][0]['version']
        books = json.loads(json.dumps(changes.books))
        scans, deadline = changes.scans, changes.deadline
        def failed_walk(*args, **kwargs):
            handler = kwargs.get('onerror')
            if handler:
                handler(PermissionError('隔离模拟扫描失败'))
            raise PermissionError('隔离模拟扫描失败')
            yield
        with patch.object(daily.os, 'walk', side_effect=failed_walk), self.assertRaises((StoreError, OSError)):
            changes.read(force=True)
        self.assertEqual(changes.books, books)
        self.assertEqual(changes.scans, scans)
        self.assertEqual(changes.deadline, deadline)
        self.assertEqual(changes.read()['books'][0]['version'], original)

    def test_active_commented_nested_and_includeonly(self):
        self.assertEqual(self.participation('\\input{unit}')['status'], 'seen')
        self.assertEqual(self.participation('% \\input{unit}\n')['status'], 'unseen')
        (self.book / 'middle.tex').write_text('\\input{unit}', encoding='utf-8')
        result = self.participation('\\input{middle}')
        self.assertEqual(result['status'], 'seen')
        self.assertEqual(result['chain'], ['main.tex', 'middle.tex', 'unit.tex'])
        self.assertEqual(self.participation('\\includeonly{other}\n\\include{unit}')['status'], 'unseen')
        self.assertEqual(self.participation('\\includeonly{unit}\n\\include{unit}')['status'], 'seen')

    def test_macro_condition_missing_and_cycle_unknown(self):
        for source in ('\\def\\where{unit}\n\\input{\\where}', '\\iftrue\\input{unit}\\fi', '\\input{missing}', '\\input{main}'):
            with self.subTest(source=source):
                self.assertEqual(self.participation(source)['status'], 'unknown')

    def test_braced_math_path(self):
        target = self.book / 'R^{n}.tex'
        (self.book / 'unit.tex').rename(target)
        entry = self.book / 'Probe_Content.md'
        entry.write_text(entry.read_text(encoding='utf-8').replace('unit.tex', 'R^{n}.tex'), encoding='utf-8')
        self.assertEqual(self.participation('\\input{R^{n}}')['status'], 'seen')

    def test_parent_directory_fallback_is_not_seen(self):
        (self.book / 'chapters').mkdir()
        (self.book / 'unit.tex').rename(self.book / 'chapters/unit.tex')
        entry = self.book / 'Probe_Content.md'
        entry.write_text(entry.read_text(encoding='utf-8').replace('unit.tex', 'chapters/unit.tex'), encoding='utf-8')
        (self.book / 'chapters/middle.tex').write_text('\\input{unit}', encoding='utf-8')
        result = self.participation('\\input{chapters/middle}')
        self.assertEqual(result['status'], 'unknown', '只有文件父目录候选时必须待核实TeX工作目录语义')

    def test_root_dot_input_is_seen(self):
        self.assertEqual(self.participation('\\input{./unit}')['status'], 'seen')

    def test_deep_braces_are_seen(self):
        (self.book / 'unit.tex').rename(self.book / 'R^{n^{m}}.tex')
        entry = self.book / 'Probe_Content.md'
        entry.write_text(entry.read_text(encoding='utf-8').replace('unit.tex', 'R^{n^{m}}.tex'), encoding='utf-8')
        self.assertEqual(self.participation('\\input{R^{n^{m}}}')['status'], 'seen')

    def test_unclosed_braces_are_unknown(self):
        self.assertEqual(self.participation('\\input{unit')['status'], 'unknown')

    def test_cached_checked_at_is_scan_time(self):
        changes = self.changes(ttl=3600)
        with patch.object(daily, 'now', return_value='first scan'):
            first = changes.read()
        with patch.object(daily, 'now', return_value='later response'):
            cached = changes.read()
        self.assertFalse(first['cached'])
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['checked_at'], first['checked_at'])
        self.assertEqual(cached['books'][0]['checked_at'], first['books'][0]['checked_at'])
        self.assertEqual(cached['response_at'], 'later response')
        self.assertEqual(changes.scans, 1)

    def test_added_books_empty_baseline_and_new_book(self):
        changes = self.changes()
        baseline = changes.read('{}')
        self.assertEqual(baseline['added_books'], [])
        versions = json.dumps({book['name']: book['version'] for book in baseline['books']})
        self.make_book('New')
        result = changes.read(versions)
        self.assertEqual(result['added_books'], ['New'])
        self.assertEqual(result['removed_books'], [])
        new = next(book for book in result['books'] if book['name'] == 'New')
        self.assertEqual(new['name'], 'New')
        self.assertEqual(len(new['version']), 64)
        self.assertEqual(new['file_count'], 3)
        self.assertFalse(new['comparison_available'])
        self.assertEqual(new['checked_at'], result['checked_at'])

    def test_two_books_failure_preserves_history(self):
        self.make_book('Second')
        changes = self.changes(ttl=3600)
        changes.read()
        old_books = copy.deepcopy(changes.books)
        old_history = copy.deepcopy(changes.history)
        (self.book / 'unit.tex').write_text('第一本已变化', encoding='utf-8')
        real_walk = os.walk
        def failing(top, *args, **kwargs):
            if Path(top).name == 'Second':
                kwargs['onerror'](PermissionError('第二本隔离扫描失败'))
            yield from real_walk(top, *args, **kwargs)
        with patch.object(daily.os, 'walk', side_effect=failing), self.assertRaises(StoreError):
            changes.read(force=True)
        self.assertEqual(changes.books, old_books)
        self.assertEqual(changes.history, old_history)
        self.assertEqual(changes.scans, 1)

    def test_pdf_staleness(self):
        pdf = self.book / 'main.pdf'
        pdf.write_bytes(b'fixture only')
        os.utime(pdf, ns=(1000000000, 1000000000))
        self.assertTrue(daily.participation(self.store, 'C1/N1')['pdf_may_be_stale'])
        for path in self.book.glob('*.tex'):
            os.utime(path, ns=(2000000000, 2000000000))
        os.utime(pdf, ns=(3000000000, 3000000000))
        self.assertFalse(daily.participation(self.store, 'C1/N1')['pdf_may_be_stale'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
