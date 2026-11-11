"""离线回归：python -m unittest discover -s Tools/video2text -p 'test_*.py'。"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("v2t", Path(__file__).with_name("video2text.py"))
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
BV = "BV1111111111"
OTHER = "BV2222222222"
URL = f"https://www.bilibili.com/video/{BV}"


def view(bvid=BV, cids=(11, 22)):
    return {"bvid": bvid, "title": "课程", "pages": [
        {"cid": cid, "page": i, "part": "同名"} for i, cid in enumerate(cids, 1)]}


class Regression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cp = v.load_conf()
        self.options = dict(cp=self.cp, outdir=self.root, nocookie=True,
                            force_whisper=False, lang=None, model=None, keep_audio=True)
        self.calls = []
        self.bad = set()
        self.metadata = view()
        self.patches = [patch.object(v, "bili_view", side_effect=self.get_view),
                        patch.object(v, "convert", side_effect=self.convert)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def get_view(self, bvid):
        return self.metadata if bvid == BV else view(bvid, (33, 44))

    def convert(self, url, **kwargs):
        target = kwargs["target_dir"] / "transcript.txt"
        self.calls.append((url, target))
        if target.parent.name in self.bad:
            return {"ok": False, "error": "模拟失败"}
        v.write_text(target, "[00:00:01] 离线产物\n")
        return {"ok": True, "path": target}

    def run_process(self, url=URL, **kwargs):
        return v.process(url, **self.options, **kwargs)

    def state(self):
        return json.loads((self.root / ".video2text-manifest.json").read_text(encoding="utf-8"))

    def test_increment_reorder_title_removed_refresh(self):
        self.assertEqual(self.run_process()["completed"], 2)
        original = [p for _, p in self.calls]
        self.metadata = view(cids=(22, 11))
        self.metadata["title"] = "改名"
        self.assertEqual(self.run_process()["skipped"], 2)
        self.assertEqual(len(self.calls), 2)
        self.metadata = view(cids=(11,))
        self.assertEqual(self.run_process()["skipped"], 1)
        self.assertTrue(all(p.is_file() for p in original))
        self.assertEqual(self.run_process(refresh=True)["completed"], 1)

    def test_failure_missing_empty_and_pending(self):
        self.bad.add(f"{BV}-cid-22")
        first = self.run_process()
        self.assertEqual((first["completed"], first["failed"], first["exit_code"]), (1, 1, 1))
        self.assertEqual(self.state()["episodes"][f"{BV}-cid-22"]["status"], "failed")
        self.bad.clear()
        self.assertEqual(self.run_process()["completed"], 1)
        self.calls[0][1].unlink()
        self.assertEqual(self.run_process()["completed"], 1)
        v.write_text(self.calls[-1][1], "")
        self.assertEqual(self.run_process()["completed"], 1)
        state = self.state()
        state["episodes"][f"{BV}-cid-11"]["status"] = "pending"
        v.atomic_json(self.root / ".video2text-manifest.json", state)
        self.assertEqual(self.run_process()["completed"], 1)

    def test_explicit_part_and_all_parts(self):
        self.assertEqual(self.run_process(URL + "?p=2")["completed"], 1)
        self.assertTrue(self.calls[0][0].endswith("?p=2"))
        res = self.run_process(URL + "?p=2", all_parts=True)
        self.assertEqual((res["completed"], res["skipped"]), (1, 1))
        self.assertFalse(self.run_process(URL + "?p=99")["ok"])

    def test_season_cross_bv_and_stable_seed(self):
        season = {"id": 77, "title": "合集", "sections": [
            {"episodes": [{"bvid": BV}, {"bvid": OTHER}, {"bvid": BV}]}]}
        self.metadata["ugc_season"] = season
        self.assertEqual(self.run_process()["completed"], 4)
        self.assertIn("bili-season-77", self.state()["collections"])
        with patch.object(v, "bili_view", side_effect=lambda b: dict(view(b, (11, 22) if b == BV else (33, 44)), ugc_season=season)):
            self.assertEqual(self.run_process(URL.replace(BV, OTHER))["skipped"], 4)

    def test_corrupt_refused_even_refresh(self):
        manifest = self.root / ".video2text-manifest.json"
        for text in ("{broken", "{}", "[]", "", '{"version":2}'):
            v.write_text(manifest, text)
            before = manifest.read_bytes()
            self.assertFalse(self.run_process(refresh=True)["ok"])
            self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(self.calls)

    def test_paths_and_manifest_binding(self):
        for path in ("../outside", "/absolute", "C:/bad", "a\\b", "a/./b", "a//b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                v.relative_output(self.root, path)
        self.run_process()
        state = self.state()
        state["episodes"][f"{BV}-cid-11"]["path"] = "episodes/other/transcript.txt"
        v.atomic_json(self.root / ".video2text-manifest.json", state)
        before = (self.root / ".video2text-manifest.json").read_bytes()
        self.assertFalse(self.run_process()["ok"])
        self.assertEqual((self.root / ".video2text-manifest.json").read_bytes(), before)

    def test_lock_and_atomic_failure(self):
        lock = self.root / ".video2text.lock"
        v.write_text(lock, "existing\n")
        self.assertFalse(self.run_process()["ok"])
        self.assertEqual(lock.read_text(), "existing\n")
        lock.unlink()
        self.run_process()
        manifest = self.root / ".video2text-manifest.json"
        before = manifest.read_bytes()
        with patch.object(v.os, "replace", side_effect=OSError("模拟中断")):
            with self.assertRaises(OSError):
                v.atomic_json(manifest, {"bad": 1})
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".manifest-*.tmp")))

    def test_single_convert_subtitle_and_whisper(self):
        # 停止 convert mock，实际调用既有单集接口。
        self.patches[1].stop()
        probe = {"info": {"id": "single-22", "title": "同名", "duration": 10},
                 "subtitles": {}, "auto": {}}
        with patch.object(v, "probe_subtitles", return_value=probe), \
                patch.object(v, "download_audio", return_value=self.root / "audio.m4a") as audio, \
                patch.object(v, "transcribe", return_value=[(0, 1, "内容")]):
            res = v.convert(URL + "?p=2", mode="auto", **self.options)
            self.assertTrue(res["ok"])
            self.assertIn("whisper", res["mode"])
            self.assertGreater(res["path"].stat().st_size, 0)
            audio.assert_called_once()
            probe["subtitles"] = {"zh": [{"ext": "json", "data": '{"body":[{"from":0,"to":1,"content":"字幕"}]}'}]}
            audio.reset_mock()
            res = v.convert(URL + "?p=2", **self.options)
            self.assertTrue(res["ok"])
            audio.assert_not_called()

    def test_ydl_single_and_audio_isolation(self):
        self.assertTrue(v.ydl_opts(True, "edge", None, True)["noplaylist"])
        instances = []

        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts
                instances.append(self)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download=False):
                if download:
                    path = Path(self.opts["outtmpl"].replace("%(ext)s", "m4a"))
                    v.write_text(path, "new-audio")
                return {"id": "22", "title": "单集", "ext": "m4a"}

        fake = types.SimpleNamespace(YoutubeDL=FakeYDL)
        v.write_text(self.root / "audio.webm", "old" * 100)
        with patch.dict(sys.modules, {"yt_dlp": fake}):
            self.assertEqual(v.probe_subtitles(URL + "?p=2", nocookie=True, browser="edge", cookies=None)["info"]["id"], "22")
            audio = v.download_audio(URL + "?p=2", self.root, nocookie=True, browser="edge", cookies=None)
        self.assertEqual(audio.read_text(), "new-audio")
        self.assertTrue(all(i.opts["noplaylist"] for i in instances))

    def test_metadata_failure_no_partial_collection(self):
        self.metadata["ugc_season"] = {"id": 77, "sections": [{"episodes": [{}]}]}
        self.assertFalse(self.run_process()["ok"])
        self.assertFalse(self.calls)
        self.assertFalse((self.root / ".video2text-manifest.json").exists())

    def test_symlink_escape_when_supported(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "episodes"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("本机未授予创建符号链接权限")
            self.assertFalse(self.run_process()["ok"])
            self.assertFalse(list(Path(outside).iterdir()))

    def test_panel_and_cli_use_process(self):
        aggregate = {"ok": True, "completed": 1, "skipped": 0, "failed": 0, "error": None}
        with patch.object(v, "ask", side_effect=[URL, ""]), patch.object(v, "process", return_value=aggregate) as call:
            v.panel_transcribe(self.cp)
            call.assert_called_once()
        with patch.object(v, "ask", side_effect=[URL, "", ""]), patch.object(v, "process", return_value=aggregate) as call:
            v.panel_batch(self.cp)
            call.assert_called_once()
        with patch.object(sys, "argv", ["video2text.py", URL, "--refresh", "--all-parts"]), \
                patch.object(v, "relaunch_if_needed", return_value=None), \
                patch.object(v, "process", return_value={"ok": False}) as call:
            self.assertEqual(v.main(), 1)
            self.assertTrue(call.call_args.kwargs["refresh"])
            self.assertTrue(call.call_args.kwargs["all_parts"])


    def test_added_same_title_and_modified_nonempty(self):
        self.assertEqual(self.run_process()["completed"], 2)
        self.assertEqual(len({p for _, p in self.calls}), 2)
        self.metadata = view(cids=(22, 11, 55))
        self.assertEqual((self.run_process()["completed"], len(self.calls)), (1, 3))
        v.write_text(self.calls[0][1], "被改坏的非空产物")
        res = self.run_process()
        self.assertEqual((res["completed"], res["skipped"]), (1, 2))
        self.assertTrue(all(e.get("sha256") for e in self.state()["episodes"].values()))

    def test_keyboard_interrupt_preserves_success(self):
        actual = self.convert
        def interrupted(url, **kwargs):
            if url.endswith("p=2"):
                raise KeyboardInterrupt()
            return actual(url, **kwargs)
        with patch.object(v, "convert", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.run_process()
        self.assertEqual(self.state()["episodes"][f"{BV}-cid-11"]["status"], "success")
        self.assertFalse((self.root / ".video2text.lock").exists())
        res = self.run_process()
        self.assertEqual((res["completed"], res["skipped"]), (1, 1))

    def test_single_and_force_cli(self):
        self.assertEqual(self.run_process(single=True)["completed"], 1)
        self.assertTrue(self.calls[0][0].endswith("p=1"))
        self.assertFalse(self.run_process(single=True, all_parts=True)["ok"])
        with patch.object(sys, "argv", ["video2text.py", URL, "--single", "--force"]), \
                patch.object(v, "relaunch_if_needed", return_value=None), \
                patch.object(v, "process", return_value={"ok": True}) as call:
            self.assertEqual(v.main(), 0)
            self.assertTrue(call.call_args.kwargs["single"])
            self.assertTrue(call.call_args.kwargs["refresh"])

    def test_flat_different_bv_and_duplicates(self):
        collection_url = "https://space.bilibili.com/1/lists/77"
        info = {"_type": "playlist", "id": "1_77", "extractor_key": "BilibiliCollectionList",
                "entries": [{"url": URL}, {"url": URL.replace(BV, OTHER)}, {"url": URL}]}
        with patch.object(v, "flat_playlist", return_value=info):
            self.assertEqual(self.run_process(collection_url)["completed"], 4)
            info["entries"].reverse()
            self.assertEqual(self.run_process(collection_url)["skipped"], 4)

    def test_flat_generic_stable_id_and_options(self):
        info = {"_type": "playlist", "id": "course", "extractor_key": "Example",
                "entries": [{"id": str(i), "ie_key": "Example", "title": "同名",
                             "url": f"https://example.test/watch?v={i}"} for i in range(70)]}
        with patch.object(v, "flat_playlist", return_value=info):
            self.assertEqual(self.run_process("https://example.test/list")["completed"], 70)
            info["entries"].reverse()
            self.assertEqual(self.run_process("https://example.test/list")["skipped"], 70)
        instances = []
        class FakeYDL:
            def __init__(self, opts):
                instances.append(opts)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download=False):
                if download:
                    raise AssertionError("flat不得下载")
                return info
        with patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYDL)}):
            self.assertIs(v.flat_playlist("https://example.test/list", nocookie=True), info)
        self.assertEqual(instances[0]["extract_flat"], "in_playlist")
        self.assertFalse(instances[0]["noplaylist"])
        self.assertFalse(instances[0]["listsubtitles"])
        self.assertTrue(instances[0]["skip_download"])


    def test_season_partial_count_refused_before_dedup(self):
        season = {"id": 77, "episode_count": 3, "sections": [
            {"episodes": [{"bvid": BV}, {"bvid": OTHER}]}]}
        self.metadata["ugc_season"] = season
        self.assertFalse(self.run_process()["ok"])
        self.assertFalse(self.calls)
        season["sections"][0]["episodes"].append({"bvid": BV})
        self.assertEqual(self.run_process()["completed"], 4)

    def test_view_failure_preserves_manifest(self):
        self.run_process()
        manifest = self.root / ".video2text-manifest.json"
        before = manifest.read_bytes()
        with patch.object(v, "bili_view", side_effect=RuntimeError("匿名接口受限")):
            self.assertFalse(self.run_process()["ok"])
        self.assertEqual(manifest.read_bytes(), before)

    def test_panel_list_and_preview_show_header_title(self):
        target = self.root / "transcripts" / "episodes" / f"{BV}-cid-11" / "transcript.txt"
        v.write_text(target, "# 转写来源：字幕\n# 标题：人类可读课程标题\n\n[00:00:01] 内容\n")
        output = io.StringIO()
        with patch.object(v, "data_root", return_value=self.root), \
                patch.object(v, "ask", side_effect=["1", "", ""]), \
                patch.object(v, "clear"), contextlib.redirect_stdout(output):
            v.panel_list(self.cp)
        self.assertGreaterEqual(output.getvalue().count("人类可读课程标题"), 3)


if __name__ == "__main__":
    unittest.main()
