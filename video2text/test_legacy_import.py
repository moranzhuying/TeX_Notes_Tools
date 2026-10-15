"""所有旧进度导入测试仅操作随机临时目录。"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import legacy_import as legacy


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "transcripts"
        self.root.mkdir()
        self.old = self.base / "旧输出"
        self.old.mkdir()
        self.progress_file = self.old / "progress.json"
        self.bvid = "BVexample123"
        self.view = {"bvid": self.bvid, "title": "合集标题", "pages": [
            {"page": n, "cid": 900000 + n, "part": f"公开第{n}集"} for n in range(1, 53)]}
        self.progress = {}
        for n in range(1, 53):
            directory = self.old / f"P{n:02d}"
            directory.mkdir()
            path = directory / "transcript.txt"
            path.write_text(f"# 来源：视频\n# 标题：公开第{n}集\n\n[00:00:01] 文字{n}\n", encoding="utf-8")
            self.progress[str(n)] = {"ok": True, "title": f"历史第{n}集", "path": str(path),
                                     "url": f"https://www.bilibili.com/video/{self.bvid}/?p={n}"}
        self.save()

    def save(self):
        self.progress_file.write_text(json.dumps(self.progress, ensure_ascii=False), encoding="utf-8")

    def run_import(self):
        return legacy.import_bili_parts(self.root, self.progress_file, self.view)

    def state(self):
        return json.loads((self.root / legacy._MANIFEST).read_text(encoding="utf-8"))

    def test_import_52_and_repeat_without_rewrite(self):
        first = self.run_import()
        self.assertEqual((first["total"], first["written"], first["skipped"]), (52, 52, 0))
        self.assertEqual((self.run_import()["written"], self.run_import()["skipped"]), (0, 52))
        state = self.state()
        self.assertEqual(len(state["episodes"]), 52)
        self.assertEqual(state["collections"][first["collection_id"]]["selected_ids"], [
            f"{self.bvid}-cid-{900000 + n}" for n in range(1, 53)])
        for n in range(1, 53):
            entry = state["episodes"][f"{self.bvid}-cid-{900000 + n}"]
            content = Path(self.progress[str(n)]["path"]).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual((self.root / entry["path"]).read_bytes(), content)
            self.assertNotIn(str(self.old), json.dumps(entry))

    def test_preserve_other_collections_and_snapshot(self):
        original = {"version": 1, "collections": {"other": {"title": "原合集", "episode_ids": [], "selected_ids": []}},
                    "episodes": {}}
        manifest = self.root / legacy._MANIFEST
        manifest.write_text(json.dumps(original), encoding="utf-8")
        original_bytes = manifest.read_bytes()
        result = self.run_import()
        self.assertEqual(self.state()["collections"]["other"], original["collections"]["other"])
        self.assertEqual(Path(result["snapshot"]).read_bytes(), original_bytes)
        self.assertEqual(self.run_import()["skipped"], 52)

    def test_preexisting_matching_unindexed_file_and_interrupted_copy(self):
        key = f"{self.bvid}-cid-900001"
        target = self.root / "episodes" / key / "transcript.txt"
        target.parent.mkdir(parents=True)
        target.write_bytes(Path(self.progress["1"]["path"]).read_bytes())
        original = legacy._atomic_json
        with mock.patch.object(legacy, "_atomic_json", side_effect=OSError("模拟写 manifest 前中断")):
            with self.assertRaises(OSError):
                self.run_import()
        self.assertFalse((self.root / legacy._LOCK).exists())
        self.assertEqual(target.read_bytes(), Path(self.progress["1"]["path"]).read_bytes())
        with mock.patch.object(legacy, "_atomic_json", wraps=original):
            result = self.run_import()
        self.assertEqual((result["written"], result["skipped"]), (0, 52))

    def test_invalid_progress_records_fail_before_writing(self):
        variants = []
        missing = dict(self.progress)
        missing.pop("52")
        variants.append(missing)
        duplicate_path = dict(self.progress)
        duplicate_path["2"] = {**duplicate_path["2"], "path": duplicate_path["1"]["path"]}
        variants.append(duplicate_path)
        bad_url = dict(self.progress)
        bad_url["2"] = {**bad_url["2"], "url": bad_url["1"]["url"]}
        variants.append(bad_url)
        incomplete = dict(self.progress)
        incomplete["2"] = {**incomplete["2"], "ok": False}
        variants.append(incomplete)
        for records in variants:
            with self.subTest(records=list(records)[-2:]):
                self.progress_file.write_text(json.dumps(records), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.run_import()
                self.assertFalse((self.root / legacy._MANIFEST).exists())
        self.save()

    def test_reject_source_outside_and_symlink(self):
        original = self.progress["1"]["path"]
        outside = self.base / "elsewhere.txt"
        outside.write_bytes(Path(original).read_bytes())
        self.progress["1"]["path"] = str(outside)
        self.save()
        with self.assertRaises(ValueError):
            self.run_import()
        self.progress["1"]["path"] = original
        link = self.old / "P01" / "linked.txt"
        try:
            link.symlink_to(original)
        except OSError:
            self.skipTest("无符号链接权限")
        self.progress["1"]["path"] = str(link)
        self.save()
        with self.assertRaises(ValueError):
            self.run_import()

    def test_reject_bad_source_and_public_page(self):
        first = Path(self.progress["1"]["path"])
        original = first.read_bytes()
        for body in (b"", "# 标题：有标题\n无时间戳".encode("utf-8"), b"[00:01] content"):
            first.write_bytes(body)
            with self.assertRaises(ValueError):
                self.run_import()
        first.write_bytes(original)
        self.view["pages"][1]["cid"] = 900001
        with self.assertRaises(ValueError):
            self.run_import()
        self.view["pages"][1]["cid"] = 900002
        self.view["pages"][1]["page"] = 3
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertFalse((self.root / legacy._MANIFEST).exists())

    def test_collision_never_overwrites_existing_file_or_manifest(self):
        self.run_import()
        manifest = (self.root / legacy._MANIFEST)
        original = manifest.read_bytes()
        target = self.root / "episodes" / f"{self.bvid}-cid-900001" / "transcript.txt"
        target.write_text("用户另行修改", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(target.read_text(encoding="utf-8"), "用户另行修改")
        target.write_bytes(Path(self.progress["1"]["path"]).read_bytes())
        state = self.state()
        state["episodes"][f"{self.bvid}-cid-900001"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(state), encoding="utf-8")
        damaged = manifest.read_bytes()
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(manifest.read_bytes(), damaged)

    def test_existing_lock_refused_and_preserved(self):
        lock = self.root / legacy._LOCK
        lock.write_text("101", encoding="ascii")
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.assertEqual(lock.read_text(encoding="ascii"), "101")


if __name__ == "__main__":
    unittest.main()
