"""全部使用临时目录，不访问真实数据或网络。"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import collection_support as cs


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = "BVabc-cid-1", "BVabc-cid-2"
        self.state = {"version": 1, "collections": {"c": {"title": "课程", "episode_ids": [self.a, self.b],
                                                              "selected_ids": [self.a, self.b]}}, "episodes": {}}
        for key in (self.a, self.b):
            path = self.root / "episodes" / key / "transcript.txt"
            path.parent.mkdir(parents=True)
            data = ("内容 " + key).encode()
            path.write_bytes(data)
            self.state["episodes"][key] = {"title": "同名", "status": "success", "part": 1,
                                           "path": path.relative_to(self.root).as_posix(),
                                           "sha256": hashlib.sha256(data).hexdigest()}
        self.save()

    def save(self):
        (self.root / cs._MANIFEST).write_text(json.dumps(self.state), encoding="utf-8")

    def export(self):
        self.save()
        return cs.export_collection(self.root, "c", self.root)

    def test_complete_and_numbered_same_titles(self):
        result = self.export()
        self.assertTrue(result["complete"])
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertEqual(archive.namelist(), ["0001 同名.txt", "0002 同名.txt", "index.txt"])
            self.assertIn("BVabc p=1", archive.read("index.txt").decode())

    def test_selected_order_not_history(self):
        self.state["collections"]["c"]["selected_ids"] = [self.b, self.a]
        result = self.export()
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn(self.b, archive.read("0001 同名.txt").decode())

    def test_selected_subset(self):
        self.state["collections"]["c"]["selected_ids"] = [self.b]
        self.assertEqual(self.export()["exported"], 1)

    def test_empty_selection_does_not_use_history(self):
        self.state["collections"]["c"]["selected_ids"] = []
        result = self.export()
        self.assertFalse(result["complete"])
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("failed.txt", archive.namelist())

    def test_legacy_selection_fallback(self):
        del self.state["collections"]["c"]["selected_ids"]
        self.assertEqual(self.export()["exported"], 2)

    def test_missing_artifact(self):
        (self.root / self.state["episodes"][self.a]["path"]).unlink()
        result = self.export()
        self.assertEqual(result["failed_ids"], [self.a])
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("缺失", archive.read("failed.txt").decode())
            self.assertIn("不完整", archive.read("index.txt").decode())

    def test_modified_hash(self):
        (self.root / self.state["episodes"][self.a]["path"]).write_text("破坏", encoding="utf-8")
        self.assertEqual(self.export()["failed"], 1)

    def test_hash_missing(self):
        del self.state["episodes"][self.a]["sha256"]
        self.assertEqual(self.export()["failed"], 1)

    def test_empty_artifact(self):
        (self.root / self.state["episodes"][self.a]["path"]).write_bytes(b"")
        self.assertEqual(self.export()["failed"], 1)

    def test_failed_pending_list_and_secret_omission(self):
        for key, status in ((self.a, "failed"), (self.b, "pending")):
            self.state["episodes"][key].update(status=status, error="token=secret", url="https://invalid/?key=secret")
        self.assertEqual(cs.failed_episode_ids(self.state, "c"), [self.a, self.b])
        result = self.export()
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertNotIn("secret", archive.read("failed.txt").decode() + archive.read("index.txt").decode())

    def test_unknown_episode(self):
        self.state["collections"]["c"]["selected_ids"] = ["missing"]
        self.assertEqual(self.export()["failed_ids"], ["missing"])

    def test_traversal_rejected(self):
        for path in ("../secret.txt", "C:/secret.txt", "episodes/../../secret.txt", "episodes\\secret.txt"):
            with self.subTest(path=path):
                self.state["episodes"][self.a]["path"] = path
                self.assertEqual(self.export()["failed"], 1)

    def test_zip_names_safe(self):
        self.state["collections"]["c"]["title"] = "CON"
        self.state["episodes"][self.a]["title"] = "../../x:bad?\nname"
        result = self.export()
        self.assertEqual(Path(result["path"]).name, "_CON.zip")
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertTrue(all("/" not in name and "\\" not in name and ":" not in name for name in archive.namelist()))

    def test_symlink_escape(self):
        target = self.root / self.state["episodes"][self.a]["path"]
        target.unlink()
        try:
            target.symlink_to(self.root.parent)
        except OSError:
            self.skipTest("当前用户不允许创建符号链接")
        self.assertEqual(self.export()["failed"], 1)

    def test_rename_updates_export_only(self):
        self.state["collections"]["c"]["title"] = "新课程名"
        result = self.export()
        self.assertEqual(Path(result["path"]).stem, "新课程名")
        self.assertTrue((self.root / self.state["episodes"][self.a]["path"]).exists())

    def test_explicit_existing_file_never_overwritten(self):
        path = self.root / "keep.zip"
        path.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            cs.export_collection(self.root, "c", path)
        self.assertEqual(path.read_bytes(), b"keep")

    def test_directory_export_collision(self):
        first, second = self.export(), self.export()
        self.assertNotEqual(first["path"], second["path"])
        self.assertTrue(Path(first["path"]).is_file())

    def test_readonly_index(self):
        manifest = self.root / cs._MANIFEST
        before = manifest.read_bytes()
        items = cs.list_collections(self.root)
        self.assertEqual(items[0]["success"], 2)
        self.assertNotIn("data", items[0]["episodes"][0])
        self.assertEqual(items[0]["episodes"][0]["path"], f"episodes/{self.a}/transcript.txt")
        self.assertEqual(manifest.read_bytes(), before)

    def test_missing_manifest(self):
        (self.root / cs._MANIFEST).unlink()
        self.assertEqual(cs.list_collections(self.root), [])

    def test_broken_manifest(self):
        (self.root / cs._MANIFEST).write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            cs.list_collections(self.root)

    def test_invalid_selection(self):
        self.state["collections"]["c"]["selected_ids"] = [self.a, self.a]
        self.save()
        with self.assertRaises(ValueError):
            cs.list_collections(self.root)

    def test_unknown_part_legacy_metadata(self):
        del self.state["episodes"][self.a]["part"]
        result = self.export()
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertIn("BVabc p=未知 cid=1", archive.read("index.txt").decode())

    def test_no_lock(self):
        self.assertEqual(cs.inspect_lock(self.root)["status"], "absent")

    def test_live_lock_is_not_changed(self):
        lock = self.root / cs._LOCK
        lock.write_text(str(os.getpid()), encoding="ascii")
        self.assertTrue(cs.inspect_lock(self.root)["alive"])
        self.assertTrue(lock.exists())

    def test_unknown_lock_is_not_removed(self):
        lock = self.root / cs._LOCK
        for text in ("bad", "0", "-1", "999999999999999999", "{}"):
            lock.write_text(text, encoding="ascii")
            result = cs.inspect_lock(self.root)
            self.assertEqual(result["status"], "unknown")
            self.assertFalse(result["can_remove"])
            self.assertEqual(lock.read_text(), text)

    def test_audio_locks_visible_without_main_lock(self):
        paths = []
        for name, text in (("first", "123\n"), ("second", "bad")):
            path = self.root / "episodes" / self.a / ".audio-cache" / name / ".lock"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="ascii")
            paths.append(path)
        with mock.patch.object(cs, "_pid_alive", return_value=False):
            result = cs.inspect_lock(self.root)
        self.assertEqual(result["status"], "absent")
        self.assertEqual([item["status"] for item in result["audio_locks"]], ["dead", "unknown"])
        self.assertEqual(result["audio_locks"][0]["pid"], 123)
        self.assertTrue(all(not item["can_remove"] for item in result["audio_locks"]))
        self.assertTrue(all(path.exists() for path in paths))

    def test_audio_lock_fixed_depth_only(self):
        path = self.root / "episodes" / self.a / ".audio-cache" / "hash" / "deeper" / ".lock"
        path.parent.mkdir(parents=True)
        path.write_text("123", encoding="ascii")
        self.assertEqual(cs.inspect_lock(self.root)["audio_locks"], [])

    def test_audio_lock_reparse_directory_not_followed(self):
        from types import SimpleNamespace
        cache = self.root / "episodes" / self.a / ".audio-cache"
        lock = cache / "hash" / ".lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("123", encoding="ascii")
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == cache:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with mock.patch.object(Path, "lstat", lstat):
            self.assertEqual(cs.inspect_lock(self.root)["audio_locks"], [])
        self.assertTrue(lock.exists())

    def test_audio_lock_symbolic_directory_not_followed(self):
        from types import SimpleNamespace
        cache = self.root / "episodes" / self.a / ".audio-cache"
        lock = cache / "hash" / ".lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("123", encoding="ascii")
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == cache:
                return SimpleNamespace(st_mode=0o120777, st_file_attributes=0)
            return info

        with mock.patch.object(Path, "lstat", lstat):
            self.assertEqual(cs.inspect_lock(self.root)["audio_locks"], [])

    def test_dead_and_permission_unknown_lock(self):
        lock = self.root / cs._LOCK
        lock.write_text("123", encoding="ascii")
        for alive, status in ((False, "dead"), (None, "unknown")):
            with mock.patch.object(cs, "_pid_alive", return_value=alive):
                result = cs.inspect_lock(self.root)
            self.assertEqual(result["status"], status)
            self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
