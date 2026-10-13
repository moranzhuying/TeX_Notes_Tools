"""多书许可与 legacy 退役隔离测试，不写真实笔记。"""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench_launcher as wb
import workbench_legacy as legacy
import workbench_store as st
from test_gt_daily import GTTests


class MultiTests(GTTests):
    def test_isolated_source_change_basis_only(self):
        original = self.store.read_review(self.uid)
        self.store.patch_review(self.uid, {'body': '进行中'}, original['sha256'])
        self.assertEqual(self.store.read_review(self.uid)['basis_status']['body'], 'current')
        unit = self.store._unit(self.uid)
        source = self.store.path(unit['tex'])
        source.write_bytes(source.read_bytes() + b'\n% isolated change smoke\n')
        review = self.store.read_review(self.uid)
        self.assertEqual(review['basis_status']['body'], 'stale')
        self.assertEqual(review['row']['正文整理'], '进行中')

    def test_multi_permissions(self):
        identities = {'General_Topology': self.identity}
        names = ['Algebra', 'Integral_Theory', 'Topological_Vector_Space', 'Functions_of_a_Real_Variable',
                 'Spectral_Theory', 'Algebraic_Topology', 'Differential_and_Analytic_Manifolds']
        for name in names:
            shutil.copytree(self.source, self.root / name)
            identities[name] = st.BookStore(self.root, name).init()['book_id']
        granted = wb.grant_books(self.data, identities, self.config)
        self.assertEqual(set(wb.write_permission(granted, self.config)[1]), set(identities))
        self.start(granted)
        status, navigation = self.request('/navigation')
        self.assertEqual(status, 200)
        self.assertTrue(all(b['writable'] for b in navigation['books']))
        self.assertFalse(wb.write_permission(self.data, self.config)[0])
        alias = dict(identities)
        alias['Algebra'] = self.identity
        with self.assertRaises(ValueError):
            wb.grant_books(self.data, alias, self.config)
        external = self.base / 'external_multi'
        shutil.copytree(self.root, external)
        changed = wb.change_root(granted, str(external), self.config)
        self.assertEqual(changed['write_book_ids'], {})
        self.assertFalse(changed['allow_write'])
        with self.assertRaises(ValueError):
            wb.write_permission(granted | {'root': str(external)}, self.config)
        identity = self.root / 'Algebra/Materials/workbench/book.json'
        identity.write_bytes(st.encode({'schema_version': 1, 'book_id': self.identity}))
        self.assertFalse(any(b['writable'] for b in self.request('/navigation')[1]['books']))
        self.assertFalse(self.request('/session')[1]['allow_write'])
        self.assertEqual(self.request('/patch-runtime', {'book': 'General_Topology', 'expected': '0'*64,
                               'revision': 0, 'patch': {'plan': []}})[0], 403)


class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'shelf'
        for name in ('One', 'Two'):
            book = self.root / name
            (book / 'Content').mkdir(parents=True)
            (book / 'Materials').mkdir()
            (book / 'Content/shared.tex').write_text('same', encoding='utf-8')
            (book / 'B_Content.md').write_text('entry', encoding='utf-8')
            st.BookStore(self.root, name).init()
        (self.root / 'One/Content/unique.tex').write_text('one', encoding='utf-8')
        self.source = self.base / 'marks.json'
        self.raw = st.encode({'entries': {'Content/shared.tex': {'marks': {'proof': 'done'}, 'note': '私密备注'},
                            'Content/unique.tex': {'marks': {'proof': 'done'}}}, 'nodes': {}})
        self.source.write_bytes(self.raw)

    def snapshot(self):
        return {p.relative_to(self.base).as_posix(): p.read_bytes()
                for p in self.base.rglob('*') if p.is_file()}

    def test_ambiguity_no_read_no_promotion_repeated_rejection(self):
        private = self.base / 'private'
        before = self.snapshot()
        for _ in range(2):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('不得读取旧标记')):
                with self.assertRaises(legacy.RetiredError):
                    legacy.plan(self.root, self.raw)
                with self.assertRaises(legacy.RetiredError):
                    legacy.migrate(self.root, self.source, private)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse(list(self.root.rglob('review.md')))
        self.assertFalse(private.exists())
        for name in ('One', 'Two'):
            self.assertFalse((self.root / name / 'Materials/workbench/legacy').exists())

    def test_interrupted_and_concurrent_publish_rejected_preserves_archive(self):
        target = self.base / 'private/original.json'
        target.parent.mkdir()
        target.write_bytes(self.raw)
        (target.parent / '.interrupted.tmp').write_bytes(b'partial')
        before = self.snapshot()

        def reject(_):
            with self.assertRaises(legacy.RetiredError):
                legacy.publish(target, self.raw)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(reject, range(2)))
        with self.assertRaises(legacy.RetiredError):
            legacy.publish(target, b'changed')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(target.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
