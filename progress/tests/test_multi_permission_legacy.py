"""多书许可隔离测试，不写真实笔记。"""
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench_launcher as wb
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
