"""完全离线的音频缓存回归测试。"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from audio_support import download_audio_cached, drop_cached_audio


class AudioCacheTests(unittest.TestCase):
    URL = "https://www.bilibili.com/video/BV1Abc?p=2"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.action = None
        owner = self

        class MockYDL:
            def __init__(self, opts):
                self.opts = opts
                owner.calls.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def extract_info(self, url, download):
                owner.assertTrue(download)
                owner.assertEqual(self.opts["format"], "ba")
                owner.assertTrue(self.opts["noplaylist"])
                owner.assertTrue(self.opts["continuedl"])
                owner.assertFalse(self.opts["nopart"])
                owner.assertEqual(self.opts["postprocessors"], [])
                path = Path(self.opts["outtmpl"].replace("%(ext)s", "m4a"))
                if owner.action:
                    return owner.action(path, url)
                path.write_bytes(b"audio contents")
                return {"id": "BV1Abc", "ext": "m4a"}

        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=MockYDL)}).start()

    def run_download(self, url=None, **kwargs):
        opts = {"nocookie": True, "browser": "edge", "cookies": None}
        opts.update(kwargs)
        return download_audio_cached(url or self.URL, self.root, **opts)

    def test_verified_reuse_and_lazy_import(self):
        first = self.run_download()
        self.assertEqual(first.read_bytes(), b"audio contents")
        with patch.dict(sys.modules, {"yt_dlp": None}):
            again = self.run_download("http://m.bilibili.com/video/BV1Abc/?p=02&utm_source=x")
        self.assertEqual(first, again)
        self.assertEqual(len(self.calls), 1)
        meta = json.loads((first.parent / "cache.json").read_text())
        self.assertEqual(meta["source"]["part"], 2)
        self.assertEqual(meta["size"], first.stat().st_size)
        self.assertEqual(len(meta["sha256"]), 64)

    def test_different_source_and_part_never_reuse(self):
        first = self.run_download()
        second = self.run_download(self.URL.replace("p=2", "p=3"))
        third = self.run_download(self.URL.replace("BV1Abc", "BV9Def"))
        self.assertEqual(len({first, second, third}), 3)
        self.assertTrue(first.exists())
        self.assertEqual(len(self.calls), 3)

    def test_unbound_legacy_audio_is_untouched(self):
        legacy = self.root / "audio.m4a"
        legacy.write_bytes(b"untrusted old contents")
        path = self.run_download()
        self.assertNotEqual(path, legacy)
        self.assertEqual(legacy.read_bytes(), b"untrusted old contents")

    def test_damaged_audio_rejected_without_download(self):
        path = self.run_download()
        path.write_bytes(b"audio contentz")
        with self.assertRaisesRegex(ValueError, "校验失败") as caught:
            self.run_download()
        self.assertIn(str(path.parent.parent), str(caught.exception))
        self.assertIn("现有文件未覆盖", str(caught.exception))
        self.assertIn("移动", str(caught.exception))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(path.read_bytes(), b"audio contentz")

    def test_corrupt_metadata_rejected(self):
        path = self.run_download()
        metadata = path.parent / "cache.json"
        metadata.write_text("not json")
        with self.assertRaisesRegex(ValueError, "元数据损坏"):
            self.run_download()
        self.assertTrue(path.exists())
        self.assertEqual(len(self.calls), 1)

    def test_wrong_source_rejected(self):
        path = self.run_download()
        metadata = path.parent / "cache.json"
        value = json.loads(metadata.read_text())
        value["source"]["part"] = 99
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "身份"):
            self.run_download()
        self.assertEqual(len(self.calls), 1)

    def test_interruption_keeps_part_and_resumes_same_path(self):
        def interrupt(path, url):
            path.with_suffix(".m4a.part").write_bytes(b"partial")
            raise KeyboardInterrupt
        self.action = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_download()
        old_template = self.calls[-1]["outtmpl"]
        partial = Path(old_template.replace("%(ext)s", "m4a.part"))
        self.assertEqual(partial.read_bytes(), b"partial")

        def resume(path, url):
            self.assertEqual(path.with_suffix(".m4a.part").read_bytes(), b"partial")
            path.write_bytes(b"partial completed")
            return {"ext": "m4a"}
        self.action = resume
        result = self.run_download()
        self.assertEqual(self.calls[-1]["outtmpl"], old_template)
        self.assertEqual(result.read_bytes(), b"partial completed")
        self.assertFalse((result.parent.parent / ".lock").exists())

    def test_other_extension_not_selected_by_size(self):
        def download(path, url):
            path.with_suffix(".webm").write_bytes(b"old" * 5000)
            path.write_bytes(b"new")
            return {"ext": "m4a"}
        self.action = download
        self.assertEqual(self.run_download().read_bytes(), b"new")

    def test_missing_selected_extension_rejected(self):
        def download(path, url):
            path.with_suffix(".webm").write_bytes(b"old" * 5000)
            return {"ext": "m4a"}
        self.action = download
        with self.assertRaisesRegex(ValueError, "指定格式"):
            self.run_download()
        self.assertFalse(list(self.root.rglob("ready")))

    def test_failure_does_not_remove_previous_source(self):
        path = self.run_download()
        def fail(path, url):
            path.with_suffix(".m4a.part").write_bytes(b"partial")
            raise RuntimeError("模拟下载失败")
        self.action = fail
        with self.assertRaises(RuntimeError):
            self.run_download(self.URL.replace("p=2", "p=3"))
        self.assertEqual(path.read_bytes(), b"audio contents")
        self.assertTrue(list(self.root.rglob("*.part")))

    def test_metadata_path_traversal_rejected(self):
        path = self.run_download()
        metadata = path.parent / "cache.json"
        value = json.loads(metadata.read_text())
        value["file"] = "../../audio.m4a"
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "文件名"):
            self.run_download()

    def test_unsafe_extension_and_playlist_rejected(self):
        for info in ({"ext": "../escape"}, {"ext": "m4a", "_type": "playlist"},
                     {"ext": "m4a", "_type": "multi_video"}, None):
            self.action = lambda path, url, info=info: info
            with self.assertRaises(ValueError):
                self.run_download()

    def test_symlink_cache_rejected(self):
        external = self.root / "external"
        external.mkdir()
        try:
            (self.root / ".audio-cache").symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("系统未授权创建符号链接")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            self.run_download()
        self.assertEqual(list(external.iterdir()), [])

    def test_symlink_staging_file_rejected_before_downloader(self):
        def fail(path, url):
            raise RuntimeError("暂停")
        self.action = fail
        with self.assertRaises(RuntimeError):
            self.run_download()
        staging = Path(self.calls[-1]["outtmpl"]).parent
        outside = self.root / "outside"
        outside.write_bytes(b"unchanged")
        try:
            (staging / "audio.m4a.part").symlink_to(outside)
        except OSError:
            self.skipTest("系统未授权创建符号链接")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            self.run_download()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(outside.read_bytes(), b"unchanged")

    def test_symbolic_link_guard_without_os_privilege(self):
        original = Path.is_symlink
        def simulated_link(path):
            return path.name == ".audio-cache" or original(path)
        with patch.object(Path, "is_symlink", simulated_link):
            with self.assertRaisesRegex(ValueError, "符号链接"):
                self.run_download()
        self.assertEqual(self.calls, [])

    def test_concurrent_lock_rejected(self):
        path = self.run_download()
        lock = path.parent.parent / ".lock"
        lock.write_text("another worker")
        with self.assertRaisesRegex(RuntimeError, "中断锁"):
            self.run_download()
        self.assertEqual(lock.read_text(), "another worker")
        self.assertEqual(path.read_bytes(), b"audio contents")

    def test_corrupt_staging_binding_rejected_before_download(self):
        def interrupt(path, url):
            raise KeyboardInterrupt
        self.action = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_download()
        staging = Path(self.calls[-1]["outtmpl"]).parent
        (staging / "source.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "暂存身份"):
            self.run_download()
        self.assertEqual(len(self.calls), 1)

    def test_atomic_commit_failure_preserves_staging(self):
        import audio_support
        real_replace = audio_support.os.replace
        def replace(source, destination):
            if Path(destination).name == "ready":
                raise OSError("模拟提交中断")
            return real_replace(source, destination)
        with patch.object(audio_support.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.run_download()
        staging = Path(self.calls[-1]["outtmpl"]).parent
        self.assertTrue((staging / "audio.m4a").is_file())
        self.assertTrue((staging / "cache.json").is_file())
        self.assertFalse((staging.parent / "ready").exists())
        self.assertEqual(self.run_download().read_bytes(), b"audio contents")

    def test_drop_removes_only_verified_audio_and_redownloads(self):
        audio = self.run_download()
        unknown = audio.parent / "checkpoint.jsonl"
        unknown.write_text("keep checkpoint")
        drop_cached_audio(audio)
        self.assertFalse(audio.exists())
        self.assertTrue((audio.parent / "cache.json").exists())
        self.assertEqual(unknown.read_text(), "keep checkpoint")
        again = self.run_download()
        self.assertEqual(again, audio)
        self.assertEqual(again.read_bytes(), b"audio contents")
        retired = list(audio.parent.parent.glob("retired-*/ready/checkpoint.jsonl"))
        self.assertEqual(len(retired), 1)
        self.assertEqual(retired[0].read_text(), "keep checkpoint")
        self.assertEqual(len(self.calls), 2)

    def test_drop_rejects_unknown_or_corrupt_audio(self):
        legacy = self.root / "audio.m4a"
        legacy.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            drop_cached_audio(legacy)
        audio = self.run_download()
        audio.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            drop_cached_audio(audio)
        self.assertEqual(audio.read_bytes(), b"bad")
        self.assertEqual(legacy.read_bytes(), b"keep")

    def test_interrupted_drop_with_existing_audio_remains_usable(self):
        audio = self.run_download()
        metadata = json.loads((audio.parent / "cache.json").read_text())
        marker = {"version": 1, "source": metadata["source"], "file": audio.name}
        (audio.parent / "dropped.json").write_text(json.dumps(marker))
        self.assertEqual(self.run_download(), audio)
        self.assertEqual(len(self.calls), 1)

    def test_downloader_raw_logs_never_escape(self):
        def fail(path, url):
            print("secret signed URL")
            print("secret Cookie header", file=sys.stderr)
            raise RuntimeError("private failure")
        self.action = fail
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                self.run_download()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")
        self.assertTrue(self.calls[-1]["quiet"])
        self.assertTrue(self.calls[-1]["no_warnings"])

    def test_download_lock_records_pid(self):
        def download(path, url):
            lock = path.parent.parent / ".lock"
            self.assertEqual(lock.read_text().strip(), str(os.getpid()))
            path.write_bytes(b"audio")
            return {"ext": "m4a"}
        self.action = download
        self.run_download()

    def test_cookie_policy(self):
        self.run_download(cookies="private.txt")
        self.assertNotIn("cookiefile", self.calls[-1])
        self.run_download(self.URL.replace("p=2", "p=3"), nocookie=False, cookies="private.txt")
        self.assertEqual(self.calls[-1]["cookiefile"], "private.txt")
        self.run_download(self.URL.replace("p=2", "p=4"), nocookie=False)
        self.assertEqual(self.calls[-1]["cookiesfrombrowser"], ("edge",))

    def test_invalid_url_and_part_rejected_before_io(self):
        for url in ("file:///tmp/audio", "https://user:pass@example.test/watch",
                    self.URL + "&p=3", self.URL.replace("p=2", "p=0")):
            with self.assertRaises(ValueError):
                self.run_download(url)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
