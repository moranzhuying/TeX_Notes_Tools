"""合集 CLI 与面板入口的离线集成测试。"""

import configparser
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import collection_support
import video2text


class CollectionUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cp = configparser.ConfigParser()
        for target, value in (("load_conf", self.cp), ("data_root", self.root)):
            patcher = mock.patch.object(video2text, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.relaunch = mock.patch.object(video2text, "relaunch_if_needed", side_effect=AssertionError("合集入口不得启动模型环境"))
        self.relaunch.start()
        self.addCleanup(self.relaunch.stop)
        self.items = [{"id": "course", "title": "测试课程", "success": 1, "total": 2,
                       "episodes": [{"id": "one", "number": 1, "title": "第一集", "status": "success",
                                     "path": "episodes/one/transcript.txt"}]}]

    def cli(self, *args):
        output = io.StringIO()
        with mock.patch.object(video2text.sys, "argv", ["video2text.py", *args]), contextlib.redirect_stdout(output):
            result = video2text.main()
        return result, output.getvalue()

    def panel(self, answers):
        output = io.StringIO()
        with mock.patch.object(video2text, "ask", side_effect=answers), contextlib.redirect_stdout(output):
            video2text.panel_collections(self.cp)
        return output.getvalue()

    def test_collections_cli_without_model(self):
        with mock.patch.object(collection_support, "list_collections", return_value=self.items) as listing:
            code, output = self.cli("--collections")
        self.assertEqual(code, 0)
        self.assertIn("course | 测试课程 | 1/2", output)
        listing.assert_called_once_with(self.root / "transcripts")

    def test_cli_outdir_exact_root(self):
        with mock.patch.object(collection_support, "list_collections", return_value=[]) as listing:
            self.assertEqual(self.cli("--collections", "--outdir", str(self.root))[0], 0)
        listing.assert_called_once_with(self.root)

    def test_lock_cli_is_readonly(self):
        with mock.patch.object(collection_support, "inspect_lock", return_value={"exists": True, "status": "unknown"}) as inspect:
            code, output = self.cli("--lock-status")
        self.assertEqual(code, 0)
        self.assertIn("unknown", output)
        inspect.assert_called_once_with(self.root / "transcripts")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_export_success_and_partial_exit_codes(self):
        target = self.root / "new.zip"
        for complete in (True, False):
            with self.subTest(complete=complete), mock.patch.object(collection_support, "export_collection", return_value={"path": str(target), "complete": complete}) as export:
                code, output = self.cli("--export-collection", "course", "--export-to", str(target))
                self.assertEqual(code, 0 if complete else 1)
                self.assertIn("complete", output)
                export.assert_called_once_with(self.root / "transcripts", "course", target)
        self.assertFalse(target.exists())

    def test_export_requires_destination(self):
        with mock.patch.object(collection_support, "export_collection") as export, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.cli("--export-collection", "course")
        self.assertEqual(error.exception.code, 2)
        export.assert_not_called()

    def test_destination_requires_collection(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.cli("--export-to", str(self.root / "new.zip"))
        self.assertEqual(error.exception.code, 2)

    def test_export_existing_file_error_safe_message(self):
        with mock.patch.object(collection_support, "export_collection", side_effect=FileExistsError("secret-token")):
            code, output = self.cli("--export-collection", "course", "--export-to", str(self.root / "old.zip"))
        self.assertEqual(code, 1)
        self.assertIn("FileExistsError", output)
        self.assertNotIn("secret-token", output)

    def test_listing_corrupt_manifest_safe_message(self):
        with mock.patch.object(collection_support, "list_collections", side_effect=ValueError("secret-token")):
            code, output = self.cli("--collections")
        self.assertEqual(code, 1)
        self.assertNotIn("secret-token", output)

    def test_cli_combines_readonly_operations(self):
        with mock.patch.object(collection_support, "list_collections", return_value=self.items) as listing, mock.patch.object(collection_support, "inspect_lock", return_value={"status": "absent"}) as inspect:
            code, output = self.cli("--collections", "--lock-status")
        self.assertEqual(code, 0)
        self.assertIn("absent", output)
        self.assertIn("测试课程", output)
        listing.assert_called_once()
        inspect.assert_called_once()

    def test_panel_blank_returns_without_export(self):
        with mock.patch.object(collection_support, "list_collections", return_value=self.items), mock.patch.object(collection_support, "export_collection") as export:
            output = self.panel(["", ""])
        self.assertIn("测试课程", output)
        export.assert_not_called()

    def test_panel_lock_diagnosis(self):
        with mock.patch.object(collection_support, "list_collections", return_value=[]), mock.patch.object(collection_support, "inspect_lock", return_value={"status": "unknown"}) as inspect:
            output = self.panel(["l", ""])
        self.assertIn("unknown", output)
        inspect.assert_called_once_with(self.root / "transcripts")

    def test_panel_selection_and_cancel(self):
        with mock.patch.object(collection_support, "list_collections", return_value=self.items), mock.patch.object(collection_support, "export_collection") as export:
            output = self.panel(["1", "", "", ""])
        self.assertIn("01 第一集 [success]", output)
        export.assert_not_called()

    def test_panel_export_partial(self):
        target = self.root / "partial.zip"
        with mock.patch.object(collection_support, "list_collections", return_value=self.items), mock.patch.object(collection_support, "export_collection", return_value={"path": str(target), "complete": False}) as export:
            output = self.panel(["1", "", str(target), ""])
        self.assertIn("完整：False", output)
        export.assert_called_once_with(self.root / "transcripts", "course", target)
        self.assertFalse(target.exists())

    def test_panel_export_error_no_secret(self):
        with mock.patch.object(collection_support, "list_collections", return_value=self.items), mock.patch.object(collection_support, "export_collection", side_effect=ValueError("secret-token")):
            output = self.panel(["1", "", str(self.root / "x.zip"), ""])
        self.assertIn("ValueError", output)
        self.assertNotIn("secret-token", output)

    def test_panel_invalid_selection_no_export(self):
        for selection in ("0", "99", "-1", "bad"):
            with self.subTest(selection=selection), mock.patch.object(collection_support, "list_collections", return_value=self.items), mock.patch.object(collection_support, "export_collection") as export:
                self.panel([selection, ""])
                export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
