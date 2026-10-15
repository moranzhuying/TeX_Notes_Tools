"""分块转写、身份绑定检查点及独立进度心跳。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid


_SAMPLE_RATE = 16000


class _Heartbeat:
    def __init__(self, interval):
        self.interval = interval
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.stage = "准备"
        self.position = 0.0
        self.total = None
        # 测速基准：只统计转写阶段，排除加载与解码耗时。
        self.rate_started = None
        self.rate_base = 0.0
        self.thread = threading.Thread(target=self._run, name="transcription-heartbeat", daemon=True)

    def _eta(self):
        if self.rate_started is None or not self.total:
            return None
        span = time.monotonic() - self.rate_started
        advanced = self.position - self.rate_base
        if span < 60 or advanced < 120:
            return None
        remaining = self.total - self.position
        return max(remaining, 0.0) / (advanced / span)

    def _run(self):
        while not self.stop.wait(self.interval):
            elapsed = time.monotonic() - self.started
            total = f" / {self.total:.1f} 秒" if self.total is not None else ""
            percent = f"（{min(self.position / self.total, 1) * 100:.0f}%）" if self.total else ""
            eta = self._eta()
            tail = "ETA 待测速" if eta is None else f"ETA 约 {eta / 60:.0f} 分钟"
            # ETA 由本次已实测速率推算；样本不足时明确显示为待测速。
            print(f"转写心跳：{self.stage}{percent}；耗时 {elapsed:.1f} 秒；"
                  f"已处理音频 {self.position:.1f}{total}；{tail}", file=sys.stderr, flush=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_path(root, directory, checkpoint):
    for path in (root, directory, checkpoint):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("检查点路径含符号链接或联接，拒绝访问")
    resolved_root = root.resolve()
    if (directory.resolve().parent != resolved_root
            or checkpoint.resolve().parent != directory.resolve()):
        raise ValueError("检查点路径越出绑定目录，拒绝访问")


def _active_path(root, active):
    for path in (root, active):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("活动检查点路径含链接，拒绝访问")
    if active.resolve().parent != root.resolve():
        raise ValueError("活动检查点路径越界，拒绝访问")


def _read_active(root, active, binding_id):
    _active_path(root, active)
    if not active.exists():
        return None
    try:
        value = json.loads(active.read_text(encoding="utf-8"))
        if (not isinstance(value, dict)
                or set(value) != {"binding_id", "generation", "checksum"}
                or value["binding_id"] != binding_id
                or value["checksum"] != _payload_checksum(value)):
            raise ValueError("活动检查点身份或完整性不匹配")
        generation = value["generation"]
        prefix = f"{binding_id}-run-"
        if (not isinstance(generation, str) or not generation.startswith(prefix)
                or len(generation) != len(prefix) + 32
                or any(char not in "0123456789abcdef" for char in generation[len(prefix):])):
            raise ValueError("活动检查点代际名称非法")
        directory = root / generation
        checkpoint = directory / "checkpoint.json"
        _checkpoint_path(root, directory, checkpoint)
        if not checkpoint.is_file():
            raise ValueError("活动检查点目标缺失")
        return generation
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("活动检查点损坏，拒绝覆盖") from exc


def _payload_checksum(value):
    payload = {key: item for key, item in value.items() if key != "checksum"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write(path, value):
    value["checksum"] = _payload_checksum(value)
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_checkpoint(value, binding, chunk_seconds):
    if (not isinstance(value, dict) or set(value) != {"version", "binding", "duration", "chunks", "checksum"}
            or value["version"] != 1 or value["binding"] != binding
            or not _number(value["duration"]) or value["duration"] < 0
            or not isinstance(value["chunks"], list)):
        raise ValueError("检查点损坏或身份不匹配，拒绝覆盖")
    try:
        checksum = _payload_checksum(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("检查点内容非法，拒绝覆盖") from exc
    if value["checksum"] != checksum:
        raise ValueError("检查点完整性校验失败，拒绝覆盖")
    duration = value["duration"]
    count = math.ceil(duration / chunk_seconds)
    if len(value["chunks"]) > count:
        raise ValueError("检查点分块数量非法，拒绝覆盖")
    for index, chunk in enumerate(value["chunks"]):
        if not isinstance(chunk, list):
            raise ValueError("检查点分块格式非法，拒绝覆盖")
        previous = index * chunk_seconds
        end = min((index + 1) * chunk_seconds, duration)
        for segment in chunk:
            if (not isinstance(segment, list) or len(segment) != 3
                    or not _number(segment[0]) or not _number(segment[1])
                    or not isinstance(segment[2], str)
                    or not (previous <= segment[0] < segment[1] <= end)):
                raise ValueError("检查点片段非法，拒绝覆盖")
            previous = segment[0]
    return count


def transcribe_resumable(audio: Path, *, model_name, model_dir, device, compute_type,
                         vad, prompt, language, checkpoint_dir=None, heartbeat_seconds=20,
                         chunk_seconds=300, overlap_seconds=0, refresh=False) -> list[tuple[float, float, str]]:
    """默认无重叠分块；显式重叠为实验模式，时间漂移可能导致边界文字遗漏。"""
    for name, value in (("heartbeat_seconds", heartbeat_seconds), ("chunk_seconds", chunk_seconds)):
        if not _number(value) or value <= 0:
            raise ValueError(f"{name} 必须为正有限数")
    if not _number(overlap_seconds) or not 0 <= overlap_seconds < chunk_seconds:
        raise ValueError("overlap_seconds 必须非负且小于分块长度")
    # 分块边界必须落在样本上，避免浮点截断遗漏样本。
    chunk_samples = round(chunk_seconds * _SAMPLE_RATE)
    overlap_samples = round(overlap_seconds * _SAMPLE_RATE)
    if chunk_samples < 1:
        raise ValueError("分块长度不足一个样本")
    chunk_seconds = chunk_samples / _SAMPLE_RATE
    audio = Path(audio)
    local = Path(model_dir) if model_dir is not None else None
    source = str(local.resolve()) if local is not None and local.is_dir() else str(model_name)
    with _Heartbeat(heartbeat_seconds) as progress:
        progress.stage = "校验音频与检查点"
        binding = {
            "audio_sha256": _digest_file(audio), "model_source": source,
            "model_name": model_name, "device": device, "compute_type": compute_type,
            "vad": vad, "prompt": prompt, "language": language,
            "beam_size": 5, "condition_on_previous_text": False,
            "vad_parameters": {"min_silence_duration_ms": 500} if vad else None,
            "sample_rate": _SAMPLE_RATE, "chunk_seconds": chunk_seconds,
            "overlap_samples": overlap_samples,
        }
        encoded = json.dumps(binding, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        root = Path(checkpoint_dir) if checkpoint_dir is not None else audio.parent / ".transcription-checkpoints"
        binding_id = hashlib.sha256(encoded).hexdigest()
        active = root / f"{binding_id}-active.json"
        active_generation = _read_active(root, active, binding_id)
        generation = (f"{binding_id}-run-{uuid.uuid4().hex}" if refresh
                      else active_generation or binding_id)
        directory = root / generation
        checkpoint = directory / "checkpoint.json"
        _checkpoint_path(root, directory, checkpoint)
        state = None
        if checkpoint.exists():
            try:
                state = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("检查点无法读取，拒绝覆盖") from exc
            count = _validate_checkpoint(state, binding, chunk_seconds)
            progress.total = state["duration"]
            progress.position = min(len(state["chunks"]) * chunk_seconds, state["duration"])

        progress.stage = "加载解码依赖"
        from faster_whisper.audio import decode_audio

        progress.stage = "解码音频"
        waveform = decode_audio(str(audio), sampling_rate=_SAMPLE_RATE)
        duration = len(waveform) / _SAMPLE_RATE
        if state is not None and state["duration"] != duration:
            raise ValueError("解码时长与检查点不一致，拒绝覆盖")
        if state is not None and len(state["chunks"]) == count:
            return [tuple(segment) for chunk in state["chunks"] for segment in chunk]
        progress.stage = "加载模型"
        from faster_whisper import WhisperModel
        model = WhisperModel(source, device=device, compute_type=compute_type)
        if overlap_samples:
            print("分块边界提示：重叠片段按中点归属；模型在相邻块的时间戳可能漂移，"
                  "边界文字可能重复或遗漏，不保证逐词无损。", file=sys.stderr, flush=True)
        if state is None:
            state = {"version": 1, "binding": binding, "duration": duration, "chunks": []}
            directory.mkdir(parents=True, exist_ok=True)
            _checkpoint_path(root, directory, checkpoint)
            _atomic_write(checkpoint, state)
            if refresh:
                _active_path(root, active)
                _atomic_write(active, {"binding_id": binding_id, "generation": generation})
        progress.total = duration
        count = math.ceil(len(waveform) / chunk_samples)
        progress.rate_started = time.monotonic()
        progress.rate_base = progress.position
        for index in range(len(state["chunks"]), count):
            core_start = index * chunk_samples
            core_end = min((index + 1) * chunk_samples, len(waveform))
            window_start = max(0, core_start - overlap_samples)
            window_end = min(len(waveform), core_end + overlap_samples)
            progress.stage = f"转写第 {index + 1}/{count} 块（等待片段）"
            segments, _ = model.transcribe(
                waveform[window_start:window_end], vad_filter=vad,
                initial_prompt=prompt, language=language,
                vad_parameters=binding["vad_parameters"],
                condition_on_previous_text=False, beam_size=5,
            )
            completed = []
            start_seconds, end_seconds = core_start / _SAMPLE_RATE, core_end / _SAMPLE_RATE
            for segment in segments:
                start = float(segment.start) + window_start / _SAMPLE_RATE
                end = float(segment.end) + window_start / _SAMPLE_RATE
                if not math.isfinite(start) or not math.isfinite(end) or end < start:
                    raise ValueError("转写器返回非法时间戳")
                midpoint = (start + end) / 2
                if start_seconds <= midpoint < end_seconds:
                    start, end = max(start, start_seconds), min(end, end_seconds)
                    if end > start:
                        completed.append([start, end, str(segment.text).strip()])
            completed.sort(key=lambda segment: (segment[0], segment[1]))
            # 只提交完整消费成功的块；生成器中断不会把半块误标为完成。
            state["chunks"].append(completed)
            _checkpoint_path(root, directory, checkpoint)
            _atomic_write(checkpoint, state)
            progress.position = end_seconds
        return [tuple(segment) for chunk in state["chunks"] for segment in chunk]
