"""独立冷启动验收；仅向指定证据目录及系统临时目录写入。"""
import argparse
import builtins
import hashlib
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
import urllib.error
import urllib.parse
import urllib.request

MODULES = ('workbench_tex', 'workbench_readonly', 'workbench_store', 'workbench_features',
           'workbench_pdf', 'workbench_daily', 'workbench_server', 'workbench_launcher')
OLD_NAMES = {'progress.py', 'progress_ui.html', 'progress_marks.json', 'progress_marks.json.bak',
             'progress_settings.json', 'progress_settings.json.bak', 'progress.conf',
             'progress.conf.example', 'workbench_legacy.py', '._data', '_data', 'legacy'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def snapshot(workspace, source):
    roots = [workspace / 'LaTeX_Notes', source,
             workspace / 'outputs/legacy_retirement_20261013',
             workspace / 'outputs/old_panel_retirement_20261013']
    result = {}
    for root in roots:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or ('__pycache__' in path.parts or 'tests' in path.relative_to(root).parts):
                continue
            result[str(path.relative_to(workspace)).replace('\\', '/')] = digest(path)
    return result


def guard(copy_root, writable):
    attempts = []
    class BlockOld(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in {'progress', 'workbench_legacy'}:
                attempts.append({'kind': 'import', 'name': fullname})
                raise AssertionError('禁止旧模块：' + fullname)
    sys.meta_path.insert(0, BlockOld())
    for name in tuple(sys.modules):
        if name.split('.')[0] in {'progress', 'workbench_legacy'}:
            del sys.modules[name]
    def old_path(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        return bool(set(Path(os.fsdecode(value)).parts) & OLD_NAMES)
    def audit(event, args):
        if event == 'open':
            value = args[0]
            if old_path(value):
                attempts.append({'kind': 'open', 'path': str(value)})
                raise AssertionError('禁止旧文件：' + str(value))
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and isinstance(value, (str, bytes, os.PathLike)):
                p = Path(os.fsdecode(value)).absolute()
                if not any(p.is_relative_to(root) for root in writable):
                    raise AssertionError('拒绝真实写入：' + str(p))
    sys.addaudithook(audit)
    for attr in ('stat', 'lstat', 'scandir', 'listdir'):
        original = getattr(os, attr)
        def spy(value, *args, _original=original, **kwargs):
            if old_path(value):
                attempts.append({'kind': _original.__name__, 'path': str(value)})
                raise AssertionError('禁止旧文件探测：' + str(value))
            return _original(value, *args, **kwargs)
        setattr(os, attr, spy)
    sys.path.insert(0, str(copy_root))
    return attempts


def fixture(root, names):
    for index, name in enumerate(names, 1):
        book = root / name
        materials = book / 'Materials/C91/S92/N93'
        materials.mkdir(parents=True)
        (book / 'main.tex').write_text('\\title{Clean fixture %d}\n\\chapter{Cold chapter}\n\\section{Cold section}\n\\input{unit}\n' % index, encoding='utf-8', newline='\n')
        (book / 'unit.tex').write_text('\\subsection{Independent title}\nSynthetic fixture body.\n', encoding='utf-8', newline='\n')
        (book / 'FX_Content.md').write_text('| 目编号 | TeX | 资料目录 |\n| --- | --- | --- |\n| FX-C91-S92-N93 | unit.tex | Materials/C91/S92/N93 |\n', encoding='utf-8', newline='\n')
        (materials / 'record.md').write_text('# FX-C91-S92-N93\n- TeX：unit.tex\n', encoding='utf-8', newline='\n')
        for field in ('body', 'proof'):
            (materials / (field + '.md')).write_text('Synthetic fixture only.\n', encoding='utf-8', newline='\n')
        (materials / 'review.md').write_text('| 目编号 | TeX | 标题 | 正文整理 | 来源对照 | 数学审核 | 证明回填 | 总结导引 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| FX-C91-S92-N93 | unit.tex | Independent title | 未检查 | 未检查 | 未检查 | 未检查 | 未检查 |\n', encoding='utf-8', newline='\n')


def worker(args):
    copy_root = Path(args.copy).resolve()
    sys.dont_write_bytecode = True
    report_path = Path(args.report).resolve()
    attempts = guard(copy_root, [copy_root, report_path.parent])
    guard_checks = []
    for label, operation in (
        ('旧模块导入', lambda: __import__('progress')),
        ('旧文件读取', lambda: (copy_root / 'progress_marks.json').read_text()),
        ('旧文件存在探测', lambda: (copy_root / 'progress_settings.json').exists()),
    ):
        try:
            operation()
        except AssertionError:
            guard_checks.append(label)
        else:
            raise AssertionError('guard自测失效：' + label)
    assert len(guard_checks) == 3
    attempts.clear()
    import workbench_launcher as launcher
    from workbench_store import BookStore
    import workbench_readonly as ro
    for name, module in tuple(sys.modules.items()):
        if name.startswith('workbench'):
            assert Path(module.__file__).resolve().parent == copy_root
    assert not any(Path(p).resolve() == Path(args.workspace).resolve() for p in sys.path)
    report = {'mode': args.worker, 'old_access_attempts': attempts,
              'guard_negative_controls': guard_checks,
              'isolated': bool(sys.flags.isolated), 'cwd': str(Path.cwd()),
              'sys_path': list(sys.path)}
    if args.worker == 'real':
        root = Path(args.workspace) / 'LaTeX_Notes'
        books = []
        for book in ro.discover(root):
            navigation = BookStore(root, book.name, request_read=True).navigation()
            ids = sorted(u['id'] for u in navigation['units'])
            books.append({'name': book.name, 'count': len(ids), 'ids': ids,
                          'ids_sha256': hashlib.sha256(json.dumps(ids).encode()).hexdigest()})
        report['books'] = books
        report['count'] = sum(b['count'] for b in books)
        assert len(books) == 8 and report['count'] == 1818, report
        assert not attempts, attempts
    else:
        names = json.loads(Path(args.names).read_text(encoding='utf-8'))
        root = copy_root / 'fixture'
        fixture(root, names)
        config = copy_root / 'workbench_local.json'
        default = launcher.load_config(config)
        assert default == launcher.defaults()
        assert launcher.write_permission(default, config) == (False, ())
        assert not config.exists()
        panel_stream = io.StringIO()
        original_input, original_stdout = builtins.input, sys.stdout
        try:
            builtins.input = lambda prompt='': '0'
            sys.stdout = panel_stream
            assert launcher.panel(config, no_browser=True) == 0
        finally:
            builtins.input, sys.stdout = original_input, original_stdout
        assert '实际写入：禁用' in panel_stream.getvalue()
        assert not config.exists()
        session = launcher.Session()
        routes = []
        class ColdBoot(unittest.TestCase):
            def test_session_http_and_title(self):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                data = launcher.checked(default | {'root': str(root), 'port': port})
                launcher.root_path(data['root'], config)
                origin = session.start(data, config, no_browser=True)
                def request(route, payload=None):
                    headers = {}
                    if payload is not None:
                        headers = {'Content-Type': 'application/json', 'Origin': origin,
                                   'X-Workbench-CSRF': session.server.token}
                    req = urllib.request.Request(origin + route, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
                    try:
                        with urllib.request.urlopen(req, timeout=30) as response:
                            status, raw = response.status, response.read()
                    except urllib.error.HTTPError as exc:
                        status, raw = exc.code, exc.read()
                    self.assertFalse(attempts)
                    self.assertNotIn(b'OLD_POISON', raw)
                    routes.append({'route': route, 'status': status, 'bytes': len(raw),
                                   'sha256': hashlib.sha256(raw).hexdigest(), 'old_access_count': len(attempts)})
                    return status, raw
                try:
                    status, raw = request('/')
                    self.assertEqual(status, 200)
                    self.assertIn(b'__CSRF__', Path(copy_root / 'workbench_editor.html').read_bytes())
                    self.assertNotIn(b'__CSRF__', raw)
                    status, raw = request('/session')
                    state = json.loads(raw)
                    self.assertEqual(status, 200)
                    self.assertFalse(state['allow_write'])
                    self.assertFalse(state['allow_open'])
                    self.assertEqual(state['write_books'], [])
                    for route in ('/navigation', '/data'):
                        status, raw = request(route)
                        catalog = json.loads(raw)
                        self.assertEqual(status, 200)
                        self.assertEqual({b['name'] for b in catalog['books']}, set(names))
                        self.assertEqual(sum(len(b['units']) for b in catalog['books']), 8)
                        self.assertTrue(catalog['readonly'])
                        self.assertEqual(catalog.get('conflicts', []), [])
                        legacy = catalog.get('legacy', {})
                        self.assertEqual(legacy.get('raw', {}), {})
                        self.assertEqual(legacy.get('candidates', []), [])
                        self.assertFalse(legacy.get('active', False))
                        self.assertFalse(legacy.get('migration_performed', False))
                        self.assertTrue(all(not b['conflicts'] for b in catalog['books']))
                        self.assertTrue(all(not b['writable'] and not b['initialized'] for b in catalog['books']))
                        if route == '/navigation':
                            self.assertTrue(all(b['title'].startswith('Clean fixture') for b in catalog['books']))
                            self.assertTrue(all(b['units'][0]['title'] == 'Independent title' for b in catalog['books']))
                    book = urllib.parse.quote(names[0])
                    for route in (f'/review?book={book}&unit=C91/S92/N93', f'/runtime?book={book}',
                                  f'/summary?book={book}&scope=C91', f'/backups?book={book}'):
                        status, raw = request(route)
                        self.assertEqual(status, 200, route + ': ' + raw.decode('utf-8'))
                        self.assertFalse(json.loads(raw)['initialized'])
                    status, raw = request('/init', {'book': names[0], 'confirm': True})
                    self.assertEqual(status, 403)
                    self.assertFalse(any(root.rglob('book.json')))
                    self.assertFalse(any(root.rglob('runtime.json')))
                    self.assertFalse(any(root.rglob('summaries.md')))
                    self.assertFalse(config.exists())
                finally:
                    session.stop()
                self.assertIsNone(session.server)
                self.assertFalse(attempts)
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ColdBoot))
        report.update(tests_run=result.testsRun, success=result.wasSuccessful(), unittest_log=stream.getvalue(), routes=routes,
                      fixture_books=8, fixture_units=8, panel_defaults=default,
                      panel_log=panel_stream.getvalue(),
                      imported_modules=sorted(m for m in sys.modules if m.startswith('workbench')),
                      copied_files=sorted(p.name for p in copy_root.iterdir() if p.is_file()))
        assert result.wasSuccessful(), stream.getvalue()
    assert not attempts
    module_paths = {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
                    if name.startswith('workbench')}
    assert set(module_paths) == set(MODULES), module_paths
    assert all(Path(path).parent == copy_root for path in module_paths.values()), module_paths
    report['module_paths'] = module_paths
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    print(json.dumps({'success': True, 'mode': args.worker, 'report': str(report_path)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument('--output')
    parser.add_argument('--worker', choices=('real', 'cold'))
    parser.add_argument('--copy')
    parser.add_argument('--report')
    parser.add_argument('--names')
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    workspace = Path(args.workspace).resolve()
    source = workspace / 'Tools/progress'
    output = Path(args.output).resolve() if args.output else workspace / 'outputs/no_legacy_acceptance_20261013/boot'
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot(workspace, source)
    logs = []
    success = False
    try:
        with tempfile.TemporaryDirectory(prefix='no_legacy_boot_') as temporary:
            copy_root = Path(temporary)
            for module in MODULES:
                shutil.copyfile(source / (module + '.py'), copy_root / (module + '.py'))
            for page in ('workbench_editor.html', 'workbench_readonly.html'):
                shutil.copyfile(source / page, copy_root / page)
            runner = copy_root / 'runner.py'
            shutil.copyfile(Path(__file__), runner)
            def run(mode, extra=()):
                command = [sys.executable, '-I', '-B', str(runner), '--worker', mode,
                           '--workspace', str(workspace), '--copy', str(copy_root),
                           '--report', str(output / (mode + '.json')), *extra]
                completed = subprocess.run(command, cwd=copy_root, capture_output=True, text=True, encoding='utf-8', timeout=180)
                logs.append({'command': command, 'cwd': str(copy_root), 'exit_code': completed.returncode,
                             'stdout': completed.stdout, 'stderr': completed.stderr})
                assert completed.returncode == 0, completed.stdout + completed.stderr
            run('real')
            real = json.loads((output / 'real.json').read_text(encoding='utf-8'))
            names = copy_root / 'names.json'
            names.write_text(json.dumps([b['name'] for b in real['books']]), encoding='utf-8', newline='\n')
            run('cold', ('--names', str(names)))
            success = True
    finally:
        after = snapshot(workspace, source)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        protection = {'success': success and not changed, 'protected_files': len(before), 'changed': changed,
                      'before': before, 'after': after}
        (output / 'protection.json').write_text(json.dumps(protection, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
        (output / 'subprocess.json').write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
        (output / 'run.log').write_text('\n'.join(x['stdout'] + x['stderr'] for x in logs), encoding='utf-8', newline='\n')
        assert not changed, changed
    print(json.dumps({'success': success, 'protected_files': len(before), 'changed': changed, 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
