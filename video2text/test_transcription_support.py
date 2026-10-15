"""只使用临时音频与伪转写器的离线测试。"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np

import transcription_support as support


def segment(start, end, text="文字"):
    return types.SimpleNamespace(start=start, end=end, text=text)


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.audio = self.root / "test.audio"
        self.audio.write_bytes(b"fake-audio")
        self.calls = []
        self.wave = np.zeros(650 * 16000, dtype=np.float32)
        self.action = lambda index: [segment(0, 1)]
        owner = self

        class Model:
            def __init__(self, *args, **kwargs):
                owner.loaded = getattr(owner, "loaded", 0) + 1

            def transcribe(self, waveform, **kwargs):
                owner.calls.append((len(waveform), kwargs))
                return iter(owner.action(len(owner.calls) - 1)), None

        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = Model
        audio_module = types.ModuleType("faster_whisper.audio")
        audio_module.decode_audio = lambda *args, **kwargs: self.wave
        self.modules = {"faster_whisper": fake, "faster_whisper.audio": audio_module}
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def run_transcription(self, **kwargs):
        options = dict(model_name="tiny", model_dir=None, device="cpu", compute_type="int8",
                       vad=True, prompt="数学", language="zh", checkpoint_dir=self.root / "checkpoints",
                       overlap_seconds=2)
        options.update(kwargs)
        return support.transcribe_resumable(self.audio, **options)

    def checkpoints(self):
        return list((self.root / "checkpoints").glob("*/checkpoint.json"))

    def test_resume_after_interruption_skips_completed_chunks(self):
        def interrupted(index):
            if index == 1:
                raise KeyboardInterrupt()
            return [segment(2, 3)]
        self.action = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.run_transcription()
        state = json.loads(self.checkpoints()[0].read_text(encoding="utf-8"))
        self.assertEqual(len(state["chunks"]), 1)
        self.calls.clear()
        self.action = lambda index: [segment(2, 3)]
        result = self.run_transcription()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([row[0] for row in result], [2, 300, 600])
        self.calls.clear()
        self.modules["faster_whisper"].WhisperModel = lambda *a, **k: self.fail("完整检查点不应加载模型")
        self.assertEqual(self.run_transcription(), result)
        self.assertFalse(self.calls)

    def test_refresh_uses_new_generation_and_keeps_old_checkpoint(self):
        self.run_transcription()
        old_checkpoint = self.checkpoints()[0]
        old_contents = old_checkpoint.read_bytes()
        self.calls.clear()
        self.run_transcription(refresh=True)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.checkpoints()), 2)
        self.assertEqual(old_checkpoint.read_bytes(), old_contents)
        fresh = next(path for path in self.checkpoints() if path != old_checkpoint)
        self.assertIn("-run-", fresh.parent.name)

    def test_interrupted_refresh_resumes_active_generation_without_force(self):
        self.run_transcription()
        old_checkpoint = self.checkpoints()[0]
        old_contents = old_checkpoint.read_bytes()
        self.calls.clear()

        def interrupted(index):
            if index == 1:
                raise KeyboardInterrupt()
            return [segment(2, 3)]

        self.action = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.run_transcription(refresh=True)
        self.calls.clear()
        self.action = lambda index: [segment(2, 3)]
        result = self.run_transcription()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([row[0] for row in result], [2, 300, 600])
        self.assertEqual(old_checkpoint.read_bytes(), old_contents)
        self.calls.clear()
        self.assertEqual(self.run_transcription(), result)
        self.assertFalse(self.calls)

    def test_broken_active_fails_closed_even_on_refresh(self):
        self.run_transcription(refresh=True)
        active = next((self.root / "checkpoints").glob("*-active.json"))
        checkpoints = {path: path.read_bytes() for path in self.checkpoints()}
        active.write_text("{broken", encoding="utf-8")
        for refresh in (False, True):
            with self.assertRaisesRegex(ValueError, "活动检查点"):
                self.run_transcription(refresh=refresh)
            self.assertEqual(active.read_text(encoding="utf-8"), "{broken")
            self.assertEqual({path: path.read_bytes() for path in self.checkpoints()}, checkpoints)

    def test_active_generation_rejects_unsafe_basename(self):
        self.run_transcription(refresh=True)
        active = next((self.root / "checkpoints").glob("*-active.json"))
        value = json.loads(active.read_text(encoding="utf-8"))
        value["generation"] = "../outside"
        value["checksum"] = support._payload_checksum(value)
        active.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "活动检查点"):
            self.run_transcription()

    def test_generator_failure_does_not_commit_partial_chunk(self):
        def failure():
            yield segment(2, 3)
            raise RuntimeError("模拟生成器失败")
        self.action = lambda index: failure()
        with self.assertRaises(RuntimeError):
            self.run_transcription()
        state = json.loads(self.checkpoints()[0].read_text(encoding="utf-8"))
        self.assertEqual(state["chunks"], [])

    def test_corrupt_checkpoint_is_not_overwritten(self):
        self.run_transcription()
        checkpoint = self.checkpoints()[0]
        checkpoint.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_transcription()
        self.assertEqual(checkpoint.read_text(encoding="utf-8"), "{broken")

    def test_semantically_invalid_checkpoint_is_not_overwritten(self):
        self.run_transcription()
        checkpoint = self.checkpoints()[0]
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["chunks"][0] = [[0, 9999, "坏时间戳"]]
        contents = json.dumps(state)
        checkpoint.write_text(contents, encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_transcription()
        self.assertEqual(checkpoint.read_text(encoding="utf-8"), contents)

    def test_forged_complete_checkpoint_still_checks_decoded_duration(self):
        self.run_transcription()
        checkpoint = self.checkpoints()[0]
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["duration"] = 0
        state["chunks"] = []
        state["checksum"] = support._payload_checksum(state)
        contents = json.dumps(state)
        checkpoint.write_text(contents, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "时长"):
            self.run_transcription()
        self.assertEqual(checkpoint.read_text(encoding="utf-8"), contents)

    def test_payload_checksum_detects_silent_valid_json_damage(self):
        self.run_transcription()
        checkpoint = self.checkpoints()[0]
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["duration"] = 0
        state["chunks"] = []
        contents = json.dumps(state)
        checkpoint.write_text(contents, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "完整性"):
            self.run_transcription()
        self.assertEqual(checkpoint.read_text(encoding="utf-8"), contents)

    def test_overlap_timestamp_drift_is_reported_not_claimed_lossless(self):
        self.wave = np.zeros(310 * 16000, dtype=np.float32)
        self.action = lambda index: [[segment(299, 301)], [segment(0.5, 2.5)]][index]
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = self.run_transcription()
        self.assertEqual(result, [])
        self.assertIn("不保证逐词无损", output.getvalue())

    def test_parameter_audio_and_model_source_changes_are_isolated(self):
        self.run_transcription()
        self.run_transcription(prompt="新提示")
        self.audio.write_bytes(b"different-audio")
        self.run_transcription()
        local = self.root / "local-model"
        local.mkdir()
        self.run_transcription(model_dir=local)
        self.assertEqual(len(self.checkpoints()), 4)

    def test_public_default_has_no_overlap(self):
        result = support.transcribe_resumable(
            self.audio, model_name="tiny", model_dir=None, device="cpu", compute_type="int8",
            vad=True, prompt="数学", language="zh", checkpoint_dir=self.root / "checkpoints",
        )
        self.assertEqual([call[0] // 16000 for call in self.calls], [300, 300, 50])
        self.assertEqual([row[0] for row in result], [0, 300, 600])

    def test_overlap_uses_midpoint_and_clips_to_core(self):
        self.wave = np.zeros(620 * 16000, dtype=np.float32)
        chunks = [
            [segment(298, 300, "左"), segment(299, 301, "边界")],
            [segment(0, 2, "左"), segment(1, 3, "边界"), segment(301, 303, "次边界")],
            [segment(1, 3, "次边界"), segment(20, 22, "末尾")],
        ]
        self.action = lambda index: chunks[index]
        self.assertEqual(self.run_transcription(), [
            (298, 300, "左"), (300, 301, "边界"),
            (600, 601, "次边界"), (618, 620, "末尾"),
        ])
        self.assertEqual([call[0] // 16000 for call in self.calls], [302, 304, 22])

    def test_heartbeat_covers_loading_decoding_and_generator_wait_and_stops(self):
        original_model = self.modules["faster_whisper"].WhisperModel

        def slow_model(*args, **kwargs):
            time.sleep(0.035)
            return original_model(*args, **kwargs)

        def slow_decode(*args, **kwargs):
            time.sleep(0.035)
            return np.zeros(16000, dtype=np.float32)

        def slow_segments():
            time.sleep(0.035)
            raise RuntimeError("中断等待")
            yield

        self.modules["faster_whisper"].WhisperModel = slow_model
        self.modules["faster_whisper.audio"].decode_audio = slow_decode
        self.action = lambda index: slow_segments()
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(RuntimeError):
                self.run_transcription(heartbeat_seconds=0.005)
        text = output.getvalue()
        for stage in ("加载模型", "解码音频", "等待片段", "耗时", "已处理音频", "ETA"):
            self.assertIn(stage, text)
        self.assertFalse(any(t.name == "transcription-heartbeat" for t in threading.enumerate()))

    def test_linked_checkpoint_paths_are_rejected_without_writes(self):
        self.run_transcription()
        checkpoint = self.checkpoints()[0]
        before = checkpoint.read_bytes()
        original = Path.is_symlink
        for forbidden in (checkpoint.parent.parent, checkpoint.parent, checkpoint):
            with self.subTest(path=forbidden):
                with patch.object(Path, "is_symlink", lambda path: path == forbidden or original(path)):
                    with self.assertRaises(ValueError):
                        self.run_transcription()
                self.assertEqual(checkpoint.read_bytes(), before)

    def test_resolved_checkpoint_escape_is_rejected(self):
        root = self.root / "checkpoints"
        directory = root / "binding"
        checkpoint = directory / "checkpoint.json"
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == directory:
                return self.root / "outside" / "binding"
            return original(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            with self.assertRaises(ValueError):
                support._checkpoint_path(root, directory, checkpoint)

    def test_invalid_chunk_parameters(self):
        for options in ({"chunk_seconds": 0}, {"heartbeat_seconds": 0},
                        {"overlap_seconds": 300}, {"chunk_seconds": float("nan")}):
            with self.assertRaises(ValueError):
                self.run_transcription(**options)


if __name__ == "__main__":
    unittest.main()
