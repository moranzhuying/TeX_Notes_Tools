"""退役入口独立验收；仅使用临时夹具，不读取真实旧状态。"""
import builtins
import contextlib
import importlib
import io
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_no_legacy_independent as portable


class RetirementEntrypoints(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='retirement_independent_')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'shelf'
        self.root.mkdir()
        self.raw = json.dumps({'entries': {'../../escape.tex': {'marks': {'math': 'done', 'proof': 'done'}, 'note': '私密旧备注不可读取 <script>malicious</script>', 'path': 'C:/private/secret'}}, 'nodes': {'unit.tex': 'done'}}).encode()
        self.source = self.base / 'progress_marks.json'
        self.source.write_bytes(self.raw)
        self.archive = self.root / 'legacy'
        self.archive.mkdir()
        (self.archive / 'marks_before.json').write_bytes(self.raw)
        self.module = importlib.import_module('workbench_legacy')

    def snapshot(self):
        return {p.relative_to(self.base).as_posix(): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}

    @contextlib.contextmanager
    def no_access(self):
        events = []
        def denied(*args, **kwargs):
            events.append(repr(args))
            raise AssertionError('退役入口不得读写或创建目录')
        with contextlib.ExitStack() as stack:
            for target in ('builtins.open', 'io.open', 'pathlib.Path.open', 'pathlib.Path.mkdir', 'pathlib.Path.read_bytes', 'pathlib.Path.read_text', 'pathlib.Path.write_bytes', 'pathlib.Path.write_text', 'os.open', 'os.mkdir', 'os.makedirs', 'os.replace', 'os.rename', 'os.unlink'):
                stack.enter_context(patch(target, side_effect=denied))
            yield events
        self.assertEqual(events, [])

    def test_cli_valid_missing_and_malformed_parameters_reject_without_io(self):
        before = self.snapshot()
        cases = [[], ['plan'], ['apply'], ['plan', '--root', str(self.root), '--source', str(self.source)], ['apply', '--root', str(self.root), '--source', str(self.source), '--private', str(self.base/'private'), '--confirm'], ['plan', '--marks', str(self.source)], ['apply', '--plan', str(self.archive/'marks_before.json')], ['malicious', '../../escape']]
        for args in cases:
            with self.subTest(args=args), self.no_access(), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(self.module.main(args), 2)
                self.assertIn('retired', stderr.getvalue())
                self.assertNotIn('私密旧备注', stdout.getvalue()+stderr.getvalue())
                self.assertNotIn('Traceback', stderr.getvalue())
                self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.base/'private').exists())
        self.check_actual_cli_process_valid_and_missing_parameters()

    def test_import_entrypoints_reject_no_plan_archive_or_promotion(self):
        before = self.snapshot()
        calls = [('plan', (self.root, self.raw)), ('migrate', (self.root, self.source, self.base/'private')), ('publish', (self.archive/'marks_before.json', self.raw))]
        for name, args in calls:
            with self.subTest(entry=name), self.no_access():
                with self.assertRaises(self.module.RetiredError) as error:
                    getattr(self.module, name)(*args)
                self.assertIn('retired', str(error.exception))
        for name in ('apply', 'archive', 'confirm'):
            self.assertFalse(hasattr(self.module, name), '不得新增不存在的旧API')
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.root.rglob('review.md')))

    def check_actual_cli_process_valid_and_missing_parameters(self):
        before = self.snapshot()
        script = Path(self.module.__file__)
        for args in (['plan'], ['apply'], ['plan', '--root', str(self.root), '--marks', str(self.source)], ['apply', '--root', str(self.root), '--marks', str(self.source), '--private', str(self.base/'private')]):
            with self.subTest(args=args):
                process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(script), *args], capture_output=True, text=True)
                self.assertEqual(process.returncode, 2)
                self.assertIn('retired', process.stderr)
                self.assertNotIn('Traceback', process.stderr)
                self.assertEqual(process.stdout, '')
        self.assertEqual(before, self.snapshot())

    def test_help_is_tombstone_not_a_migration_plan(self):
        with self.no_access(), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(self.module.main(['--help']), 0)
        self.assertIn('retired', stdout.getvalue())
        self.assertNotIn('--source', stdout.getvalue())


class NewWritesAfterRetirement(portable.PortableTests):
    # 已有独立冷启动四项另行完整运行，此类只运行新增六写入口保护。
    test_cold_import_absent_legacy_and_default_zero_write = None
    test_progress_poison_sentinel_all_read_routes = None
    test_poison_old_state_corpus_ignored = None
    test_authorized_temp_save_conflict_and_reopen = None

    def test_six_write_endpoints_save_restart_conflict_identity_and_no_legacy(self):
        directory = self.book / 'Materials/workbench/legacy'
        directory.mkdir(parents=True)
        with self.snapshot_open(directory/'marks_before.json', 'w', encoding='utf-8') as out:
            out.write('{"entries":{"unit.tex":{"marks":{"math":"done"},"note":"injected"}}}')
        original_builtin, original_io = builtins.open, io.open
        def guard(original):
            def opening(file, mode='r', *args, **kwargs):
                if isinstance(file, (str, bytes, Path)) and 'legacy' in Path(file).parts:
                    raise AssertionError('新版不得读取旧归档')
                return original(file, mode, *args, **kwargs)
            return opening
        with patch('builtins.open', guard(original_builtin)), patch('io.open', guard(original_io)):
            server = self.start(True)
            self.assertEqual(self.request(server, '/init', {'book':'ProbeBook','confirm':True})[0], 200)
            self.assertEqual(self.request(server, '/create-summaries', {'book':'ProbeBook','confirm':True})[0], 200)
            review_route='/review?book=ProbeBook&unit='+self.uid
            review=self.request(server,review_route)[1]
            self.assertEqual(review['row']['数学审核'],'未检查')
            operations=[('/runtime?book=ProbeBook','/patch-runtime',{'patch':{'plan':[self.uid]}}),(review_route,'/patch-review',{'unit':self.uid,'patch':{'body':'进行中'}}),('/summary?book=ProbeBook&scope=C1','/patch-summary',{'scope':'C1','patch':{'summary':'进行中','reason':'隔离退役验收'}})]
            persisted=[]
            for route,endpoint,extra in operations:
                old=self.request(server,route)[1]
                payload={'book':'ProbeBook','expected':old['sha256']}|extra
                if endpoint=='/patch-runtime': payload['revision']=old['data']['revision']
                status,saved=self.request(server,endpoint,payload)
                self.assertEqual(status,200)
                self.assertEqual(self.request(server,endpoint,payload)[0],409)
                if endpoint=='/patch-runtime':
                    restored={'book':'ProbeBook','backup_id':saved['backup_id'],'expected':saved['sha256'],'confirm':True}
                    self.assertEqual(self.request(server,'/restore',restored)[0],200)
                    self.assertEqual(self.request(server,'/restore',restored)[0],409)
                persisted.append((route,self.request(server,route)[1]))
            self.close_servers()
            reopened=self.start(True)
            for route,value in persisted: self.assertEqual(self.request(reopened,route),(200,value))
            self.assertEqual(self.request(reopened,review_route)[1]['row']['数学审核'],'未检查')
            launcher=importlib.import_module('workbench_launcher')
            store=importlib.import_module('workbench_store').BookStore(self.root/'LaTeX_Notes','ProbeBook')
            config=self.base/'permission.json'
            granted=launcher.grant_books(launcher.defaults()|{'root':str(self.root)}, {'ProbeBook':store.identity()['book_id']}, config)
            reopened.write_validator=lambda: launcher.write_permission(granted,config)
            self.assertTrue(reopened.effective_permission()[0])
            identity=self.book/'Materials/workbench/book.json'
            with self.snapshot_open(identity,'w',encoding='utf-8') as out: out.write('{"schema_version":1,"book_id":"changed"}')
            for endpoint,extra in [('/init',{'confirm':True}),('/create-summaries',{'confirm':True}),('/patch-runtime',{'expected':'0'*64,'revision':0,'patch':{'plan':[]}}),('/patch-review',{'unit':self.uid,'expected':'0'*64,'patch':{'body':'进行中'}}),('/patch-summary',{'scope':'C1','expected':'0'*64,'patch':{'summary':'进行中'}}),('/restore',{'backup_id':'missing','expected':'0'*64,'confirm':True})]:
                self.assertEqual(self.request(reopened,endpoint,{'book':'ProbeBook'}|extra)[0],403)
            self.close_servers()
        self.assertEqual(self.reads,[])
        self.assertTrue(all(Path(name).resolve().is_relative_to(self.base) for name in self.writes))


if __name__ == '__main__':
    unittest.main(verbosity=2)
