"""临时书架验证新版依赖闭包不接触旧面板入口或状态。"""
import builtins
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROGRESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRESS))


class NoOldPanelTests(unittest.TestCase):
    def test_daily_dependency_closure_and_titles_without_old_panel(self):
        original_import = builtins.__import__
        original_read = Path.read_text
        original_bytes = Path.read_bytes
        original_open = Path.open
        forbidden = {'progress.conf', 'progress_settings.json', 'progress_marks.json', 'progress.py'}

        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] == 'progress':
                raise AssertionError('新版不得导入旧progress')
            return original_import(name, *args, **kwargs)

        def guard(path):
            if path.name in forbidden:
                raise AssertionError('新版不得读取旧面板：' + str(path))

        def guarded_read(path, *args, **kwargs):
            guard(path)
            return original_read(path, *args, **kwargs)

        def guarded_bytes(path, *args, **kwargs):
            guard(path)
            return original_bytes(path, *args, **kwargs)

        def guarded_open(path, *args, **kwargs):
            guard(path)
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix='no old panel ') as temporary:
            root = Path(temporary)
            book = root / 'LaTeX_Notes/Book'
            material = book / 'Materials/C1/N1'
            material.mkdir(parents=True)
            (book / 'main.tex').write_text('\\title{\\texorpdfstring{$\\R^{n}$}{Rn}}\n\\chapter{第一章}\n\\input{unit}\n', encoding='utf-8')
            (book / 'unit.tex').write_text('\\subsection{嵌套{标题}}\n正文\n', encoding='utf-8')
            (book / 'Probe_Content.md').write_text('| 目编号 | TeX | 资料目录 |\n|---|---|---|\n| C1/N1 | unit.tex | Materials/C1/N1 |\n', encoding='utf-8')
            for name in ('body.md', 'proof.md', 'record.md'):
                (material / name).write_text('', encoding='utf-8')
            old = root / 'Tools/progress'
            old.mkdir(parents=True)
            for name in forbidden - {'progress.py'}:
                (old / name).write_text('损坏的旧状态', encoding='utf-8')
            with patch('builtins.__import__', guarded_import), patch.object(Path, 'read_text', guarded_read), patch.object(Path, 'read_bytes', guarded_bytes), patch.object(Path, 'open', guarded_open):
                for name in ('workbench_tex', 'workbench_readonly', 'workbench_store', 'workbench_features', 'workbench_daily', 'workbench_pdf', 'workbench_server', 'workbench_launcher'):
                    importlib.import_module(name)
                ro = importlib.import_module('workbench_readonly')
                data = ro.scan(root)
                units = data['books'][0]['units']
                title, scopes = ro.navigation_titles(book, units, lambda relative: ro.safe(book, relative))
                self.assertEqual(title, 'R^n')
                self.assertEqual(units[0]['title'], '嵌套标题')
                self.assertEqual(scopes['C1']['title'], '第一章')
                self.assertFalse(data['legacy']['active'])
                self.assertEqual(data['legacy']['raw'], {})
                self.assertEqual(data['legacy']['candidates'], [])
                self.assertNotIn('legacy_candidates', units[0])
                self.assertEqual(set(units[0]['statuses'].values()), {'未登记'})

    def test_nested_input_and_dotted_paths_keep_original_rules(self):
        import workbench_tex as tex
        self.assertEqual(tex.parse_inputs(r'\\input{./Content/R^{n}/index} \\input{./K.u/item}'), ['./Content/R^{n}/index', './K.u/item'])
        self.assertEqual(tex.resolve_target(Path('Book'), './K.u/item').as_posix(), 'Book/K.u/item.tex')
        self.assertEqual(tex.take_group('{a{b}c}', 0), ('a{b}c', 7))
        self.assertTrue(tex.file_metrics(Path('unused'), text=r'\\begin{theorem}内容\\end{lemma}')['unpaired'])


if __name__ == '__main__':
    unittest.main()
