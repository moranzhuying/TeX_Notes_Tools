"""标题视图仅在临时目录中测试。"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import title_layout as tl


class TitleLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.a, self.b = "BVabc-cid-1", "BVabc-cid-2"
        self.state = {"version": 1, "collections": {"course": {"title": "课程", "selected_ids": [self.a, self.b]}},
                      "episodes": {}}
        for key in (self.a, self.b):
            self.add_episode(key, "同名", ("文本 " + key).encode())
        self.save()

    def add_episode(self, key, title, data, status="success"):
        target = self.root / "episodes" / key / "transcript.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.state["episodes"][key] = {"title": title, "path": f"episodes/{key}/transcript.txt",
                                        "status": status, "sha256": hashlib.sha256(data).hexdigest()}

    def save(self):
        (self.root / ".video2text-manifest.json").write_text(json.dumps(self.state), encoding="utf-8")

    def run_layout(self, cid="course", **kwargs):
        self.save()
        return tl.materialize_collection(self.root, cid, **kwargs)

    def test_flat_duplicate_titles_stable_id_suffix(self):
        result = self.run_layout()
        target = Path(result["directory"])
        names = [item.name for item in target.iterdir()]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(item[3:].startswith("同名--") and item.endswith(".txt") for item in names))
        self.assertEqual({item[:3] for item in names}, {"01 ", "02 "})
        self.assertEqual({item.read_bytes() for item in target.iterdir()},
                         {("文本 " + key).encode() for key in (self.a, self.b)})
        self.assertTrue(all(item.is_file() for item in target.iterdir()))
        self.assertEqual(result["written"], 2)

    def test_repeat_does_not_rewrite_same_hash(self):
        first = self.run_layout()
        target = Path(first["directory"])
        with mock.patch.object(tl, "_atomic_bytes", wraps=tl._atomic_bytes) as write:
            second = self.run_layout()
            self.assertEqual(write.call_count, 1)  # 仅保存根目录索引
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual(len(list(target.iterdir())), 2)

    def test_casefold_and_windows_names_and_truncation(self):
        self.state["collections"]["course"]["title"] = "CON"
        self.state["episodes"][self.a]["title"] = "Bad:Name?/\\*"
        self.state["episodes"][self.b]["title"] = "A" * 200
        result = self.run_layout()
        folder = Path(result["directory"])
        self.assertEqual(folder.name, "_CON")
        self.assertEqual({item.name for item in folder.iterdir()}, {"01 Bad_Name____.txt", "02 " + "A" * 93 + ".txt"})
        self.state["episodes"][self.a]["title"] = "ABC"
        self.state["episodes"][self.b]["title"] = "abc"
        self.state["collections"]["course"]["title"] = "更新"
        folder = Path(self.run_layout()["directory"])
        self.assertEqual(len(list(folder.iterdir())), 2)
        self.assertTrue(all("--" in item.stem for item in folder.iterdir()))

    def test_collection_collision_uses_stable_suffix(self):
        self.state["collections"]["other"] = {"title": "课程", "selected_ids": [self.a]}
        first = Path(self.run_layout()["directory"])
        second = Path(self.run_layout("other")["directory"])
        self.assertNotEqual(first, second)
        self.assertTrue(first.name.startswith("课程--"))
        self.assertTrue(second.name.startswith("课程--"))
        self.assertTrue((first / next(first.iterdir()).name).exists())

    def test_single_video_folder_and_title_file(self):
        self.state["collections"]["course"]["selected_ids"] = [self.a]
        self.state["collections"]["course"]["title"] = "单集视频"
        self.state["episodes"][self.a]["title"] = "单集视频"
        folder = Path(self.run_layout()["directory"])
        self.assertEqual([item.name for item in folder.iterdir()], ["单集视频.txt"])

    def test_failed_entries_skipped_and_later_incremental(self):
        self.state["episodes"][self.b]["status"] = "failed"
        first = self.run_layout()
        self.assertEqual(first["failed_ids"], [self.b])
        self.assertEqual(len(list(Path(first["directory"]).iterdir())), 1)
        self.state["episodes"][self.b]["status"] = "success"
        second = self.run_layout()
        self.assertEqual((second["written"], second["skipped"]), (1, 1))

    def test_rename_and_reorder_leave_old_managed_files(self):
        previous = Path(self.run_layout()["directory"])
        self.state["collections"]["course"].update(title="新课", selected_ids=[self.b, self.a])
        self.state["episodes"][self.a]["title"] = "新标题"
        result = self.run_layout()
        latest = Path(result["directory"])
        self.assertNotEqual(previous, latest)
        self.assertEqual(len(result["stale"]), 2)
        self.assertTrue(all(path.startswith(previous.name + "/") for path in result["stale"]))
        self.assertEqual(len(list(previous.iterdir())), 2)
        self.assertEqual(len(list(latest.iterdir())), 2)
        index = json.loads((self.root / tl._INDEX).read_text(encoding="utf-8"))
        self.assertEqual(len(index["files"]), 4)

    def test_reordering_same_collection_reports_stale_files(self):
        folder = Path(self.run_layout()["directory"])
        self.state["collections"]["course"]["selected_ids"] = [self.b, self.a]
        result = self.run_layout()
        self.assertEqual(result["written"], 2)
        self.assertEqual(len(result["stale"]), 2)
        self.assertEqual(len(list(folder.iterdir())), 4)
        self.assertEqual({item.read_bytes() for item in folder.iterdir()},
                         {("文本 " + key).encode() for key in (self.a, self.b)})

    def test_existing_unmanaged_file_or_folder_rejected(self):
        (self.root / "课程").mkdir()
        with self.assertRaises(FileExistsError):
            self.run_layout()
        (self.root / "课程").rmdir()
        first = self.run_layout()
        index = self.root / tl._INDEX
        index.unlink()
        with self.assertRaises(FileExistsError):
            self.run_layout()
        self.assertTrue(Path(first["directory"]).exists())

    def test_unmanaged_target_and_modified_managed_target_rejected(self):
        folder = Path(self.run_layout()["directory"])
        (folder / "01 新来.txt").write_text("私有文件", encoding="utf-8")
        self.state["episodes"][self.a]["title"] = "新来"
        with self.assertRaises(FileExistsError):
            self.run_layout()
        self.assertEqual((folder / "01 新来.txt").read_text(encoding="utf-8"), "私有文件")
        self.state["episodes"][self.a]["title"] = "同名"
        one = next(folder.glob("01 同名*.txt"))
        one.write_text("用户修改", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_layout()

    def test_invalid_manifest_path_hash_and_empty_fail_closed(self):
        self.run_layout()
        index_before = (self.root / tl._INDEX).read_bytes()
        for invalid in ("../outside", "episodes/BVabc-cid-2/transcript.txt"):
            self.state["episodes"][self.a]["path"] = invalid
            with self.assertRaises(ValueError):
                self.run_layout()
        self.state["episodes"][self.a]["path"] = f"episodes/{self.a}/transcript.txt"
        self.state["episodes"][self.a]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.run_layout()
        self.state["episodes"][self.a]["sha256"] = hashlib.sha256(b"").hexdigest()
        (self.root / "episodes" / self.a / "transcript.txt").write_bytes(b"")
        with self.assertRaises(ValueError):
            self.run_layout()
        self.assertEqual((self.root / tl._INDEX).read_bytes(), index_before)

    def test_broken_manifest_and_index_rejected(self):
        manifest = self.root / ".video2text-manifest.json"
        manifest.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            tl.materialize_collection(self.root, "course")
        self.run_layout()
        (self.root / tl._INDEX).write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_layout()

    def test_source_symlink_rejected(self):
        target = self.root / "episodes" / self.a / "transcript.txt"
        target.unlink()
        try:
            target.symlink_to(self.root / "episodes" / self.b / "transcript.txt")
        except OSError:
            self.skipTest("当前用户不允许符号链接")
        with self.assertRaises(ValueError):
            self.run_layout()

    def test_lock_refuses_concurrent_invocation(self):
        (self.root / tl._LOCK).write_text("123", encoding="ascii")
        with self.assertRaises(RuntimeError):
            self.run_layout()
        self.assertEqual((self.root / tl._LOCK).read_text(encoding="ascii"), "123")

    def test_verified_header_title_preferred_to_manifest_title(self):
        self.state["collections"]["course"]["selected_ids"] = [self.a]
        self.add_episode(self.a, "studio_video_234.mp4", "# 来源：视频\n# 标题：完整真实标题\n正文".encode())
        folder = Path(self.run_layout()["directory"])
        self.assertEqual([item.name for item in folder.iterdir()], ["完整真实标题.txt"])

    def test_header_title_survives_utf8_boundary_cut_in_body(self):
        self.state["collections"]["course"]["selected_ids"] = [self.a]
        prefix = "# 来源：视频\n# 标题：完整中文标题\n".encode("utf-8")
        payload = prefix + b"x" * (8191 - len(prefix)) + "中正文".encode("utf-8")
        self.assertEqual(payload[8191], "中".encode("utf-8")[0])
        self.add_episode(self.a, "studio_video_999.mp4", payload)
        folder = Path(self.run_layout()["directory"])
        self.assertEqual([item.name for item in folder.iterdir()], ["完整中文标题.txt"])

    def test_main_lock_held_does_not_remove_caller_lock(self):
        lock = self.root / tl._LOCK
        lock.write_text("外层主锁", encoding="utf-8")
        result = self.run_layout(lock_held=True)
        self.assertEqual(result["written"], 2)
        self.assertEqual(lock.read_text(encoding="utf-8"), "外层主锁")

    def test_interrupted_replacement_recovers_with_index_previous_hash(self):
        first = Path(self.run_layout()["directory"])
        self.add_episode(self.a, "同名", "替换后的内容".encode())
        original = tl._atomic_bytes
        target = first / ("01 " + tl._unique_names({self.a: "同名", self.b: "同名"}, ".txt")[self.a])

        def interrupted(path, data):
            if path == target:
                raise OSError("模拟目标原子替换前中断")
            return original(path, data)

        with mock.patch.object(tl, "_atomic_bytes", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_layout()
        partial = json.loads((self.root / tl._INDEX).read_text(encoding="utf-8"))
        self.assertIn("previous_sha256", partial["files"][first.name + "/" + target.name])
        self.assertEqual(self.run_layout()["written"], 1)
        final = json.loads((self.root / tl._INDEX).read_text(encoding="utf-8"))
        self.assertNotIn("previous_sha256", final["files"][first.name + "/" + target.name])

    def test_new_file_crash_keeps_index_and_recovers(self):
        folder = self.root / "课程"
        original = tl._atomic_bytes

        def interrupted(path, data):
            if path.parent == folder and path.suffix == ".txt":
                raise OSError("模拟首次写文件前中断")
            return original(path, data)

        with mock.patch.object(tl, "_atomic_bytes", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_layout()
        self.assertFalse((self.root / tl._LOCK).exists())
        self.assertEqual(self.run_layout()["written"], 2)

    def test_index_traversal_and_symlink_folder_rejected(self):
        self.run_layout()
        index = self.root / tl._INDEX
        state = json.loads(index.read_text(encoding="utf-8"))
        state["directories"]["course"] = ".."
        index.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_layout()

    def test_updated_source_and_no_overwrite_option(self):
        first = self.run_layout()
        content = "更新的正文".encode()
        self.add_episode(self.a, "同名", content)
        with self.assertRaises(FileExistsError):
            self.run_layout(overwrite_managed=False)
        second = self.run_layout()
        self.assertEqual(second["written"], 1)
        folder = Path(first["directory"])
        self.assertIn(content, {item.read_bytes() for item in folder.iterdir()})


if __name__ == "__main__":
    unittest.main()
