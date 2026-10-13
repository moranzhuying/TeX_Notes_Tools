"""退役旧迁移：毒化 IO、旧 CLI 参数及新状态独立性验证。"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench_legacy as legacy
import workbench_store as st


class Poison:
    def __fspath__(self):
        raise AssertionError('不得转换调用方路径')

    def __str__(self):
        raise AssertionError('不得读取调用方对象')

    def read_bytes(self):
        raise AssertionError('不得读取旧JSON')


class LegacyRetiredTests(unittest.TestCase):
    def test_all_import_entries_reject_before_io_or_parsing(self):
        poison = Poison()
        calls = [(legacy.plan, (poison, poison)),
                 (legacy.migrate, (poison, poison, poison)),
                 (legacy.publish, (poison, poison))]
        for name in ('apply', 'archive', 'confirm'):
            self.assertFalse(hasattr(legacy, name), '不新增旧 API 不存在的入口')
        with ExitStack() as stack:
            for target in ('builtins.open', 'io.open', 'json.loads',
                           'pathlib.Path.resolve', 'pathlib.Path.read_bytes',
                           'pathlib.Path.write_bytes', 'pathlib.Path.mkdir',
                           'os.link', 'workbench_store.BookStore'):
                stack.enter_context(patch(target, side_effect=AssertionError('不得访问旧数据')))
            for function, args in calls:
                with self.subTest(entry=function.__name__):
                    with self.assertRaises(legacy.RetiredError) as caught:
                        function(*args)
                    self.assertIsInstance(caught.exception, st.StoreError)
                    self.assertIn('已停用', str(caught.exception))

    def test_cli_old_flags_commands_rejected_without_traceback(self):
        script = str(Path(legacy.__file__))
        commands = [[], ['--root', 'missing', '--source', 'missing.json', '--private', 'missing'],
                    ['--root', 'missing', '--source', 'missing.json', '--private', 'missing', '--apply'],
                    ['plan'], ['migrate'], ['confirm'], ['archive'], ['--confirm'], ['--apply']]
        for args in commands:
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-B', script, *args],
                                        capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertIn('已停用', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_main_rejects_without_reading_paths_and_help_explains_retirement(self):
        out, err = io.StringIO(), io.StringIO()
        with patch('builtins.open', side_effect=AssertionError('不得读取旧JSON')):
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(legacy.main(['--source', 'old.json', '--apply']), 2)
                self.assertEqual(legacy.main(['--help']), 0)
        self.assertIn('已有 legacy 归档仅保留', out.getvalue())
        self.assertIn('已停用', err.getvalue())

    def test_existing_archive_and_new_runtime_remain_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            book = base / 'shelf/One'
            (book / 'Content').mkdir(parents=True)
            (book / 'Materials/C01/S01/N01').mkdir(parents=True)
            (book / 'Content/unit.tex').write_text('正文', encoding='utf-8')
            (book / 'Materials/C01/S01/N01/record.md').write_text('# C01-S01-N01\nTeX: `Content/unit.tex`\n', encoding='utf-8')
            (book / 'B_Content.md').write_text(
                '| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n'
                '| C01-S01-N01 | Content/unit.tex | Materials/C01/S01/N01 |\n', encoding='utf-8')
            store = st.BookStore(base / 'shelf', 'One')
            store.init()
            original = book / 'Materials/workbench/legacy/existing/original.json'
            original.parent.mkdir(parents=True)
            original.write_bytes(b'{"marks":{"proof":"done"}}')
            runtime = store.read_runtime()
            store.patch_runtime({'plan': []}, runtime['sha256'], runtime['data']['revision'])
            before = {p.relative_to(base).as_posix(): p.read_bytes()
                      for p in base.rglob('*') if p.is_file()}
            with self.assertRaises(legacy.RetiredError):
                legacy.migrate(base / 'shelf', original, base / 'private')
            self.assertEqual(before, {p.relative_to(base).as_posix(): p.read_bytes()
                                     for p in base.rglob('*') if p.is_file()})
            self.assertEqual(store.read_runtime()['data']['revision'], runtime['data']['revision'] + 1)
            self.assertFalse(list(book.rglob('review.md')))
            self.assertFalse((base / 'private').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
