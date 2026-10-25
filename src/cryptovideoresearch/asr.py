"""Optional local speech-to-text fallback for YouTube videos without subtitles.

Nothing is downloaded or imported from faster-whisper until the user explicitly
enables --asr-fallback. ASR is local inference; the model weights are fetched
once into the user's cache. Reports and transcripts stay separate per video.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .pipeline import (
    PipelineError, checked_run, find_ytdlp, valid_vtt, youtube_video_id,
)

ASR_MODELS = ("tiny", "base", "small", "medium")
ASR_DEVICES = ("cpu", "cuda")
AUDIO_EXTS = ("m4a", "webm", "opus", "mp3", "aac", "ogg")
MAX_AUDIO_MIB = 250


def model_cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base.expanduser() / "cryptovideoresearch" / "whisper-models"


def cached_asr(video_dir: Path, *, model: str) -> Path | None:
    if model not in ASR_MODELS:
        raise ValueError("Unsupported ASR model")
    target = video_dir / f"local-asr-{model}.vtt"
    return target if valid_vtt(target) else None


def download_audio(url: str, video_dir: Path, *, cookies: str = "none") -> Path:
    """Download one audio-only stream. Never download a video stream."""
    video_id = youtube_video_id(url)
    if cookies not in ("none", "chrome", "firefox", "chromium", "brave"):
        raise PipelineError("Unsupported browser cookies")
    video_dir.mkdir(parents=True, exist_ok=True)
    for extension in AUDIO_EXTS:
        existing = video_dir / f"{video_id}.source.{extension}"
        if existing.is_file() and existing.stat().st_size >= 1024:
            return existing
    binary = find_ytdlp()
    if not binary:
        raise PipelineError("yt-dlp not installed; run cryptovideo doctor")
    output = str(video_dir / f"{video_id}.source.%(ext)s")
    command = [
        binary, "--no-playlist", "--js-runtimes", "node",
        "--no-warnings", "--no-overwrites", "--max-filesize",
        f"{MAX_AUDIO_MIB}M", "-f",
        "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "-o", output, url,
    ]
    if cookies != "none":
        command[1:1] = ["--cookies-from-browser", cookies]
    checked_run(command, timeout=900)
    for extension in AUDIO_EXTS:
        audio = video_dir / f"{video_id}.source.{extension}"
        if audio.is_file() and audio.stat().st_size >= 1024:
            return audio
    raise PipelineError("yt-dlp did not produce a usable audio-only file")


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def transcribe_audio(audio: Path, target: Path, *, model: str = "small",
                     device: str = "cpu") -> Path:
    """Decode using PyAV, transcribe locally with faster-whisper, save VTT atomically."""
    if model not in ASR_MODELS or device not in ASR_DEVICES:
        raise ValueError("Unsupported ASR model/device")
    if not audio.is_file():
        raise PipelineError(f"Audio file missing: {audio}")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise PipelineError(
            "Local ASR is optional and not installed. Run: cryptovideo asr-setup"
        ) from exc
    root = model_cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    try:
        whisper = WhisperModel(
            model, device=device,
            compute_type="int8" if device == "cpu" else "float16",
            download_root=str(root),
        )
        segments, _ = whisper.transcribe(
            str(audio), beam_size=5, vad_filter=True,
            condition_on_previous_text=False,
        )
        lines = ["WEBVTT", ""]
        # Inference is lazy: consume all segments before writing the VTT.
        for segment in segments:
            start, end = float(segment.start), float(segment.end)
            text = re.sub(r"\s+", " ", str(segment.text)).strip()
            if not text or end <= start or start < 0:
                continue
            lines.extend([
                f"{format_timestamp(start)} --> {format_timestamp(end)}",
                text, "",
            ])
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise PipelineError(f"Local ASR failed: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".vtt.tmp")
    try:
        tmp.write_text("\n".join(lines), encoding="utf-8")
        if not valid_vtt(tmp):
            raise PipelineError("Local ASR produced no usable speech; refusing to send empty text to DeepSeek")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def transcribe_video(url: str, output_root: Path, *, cookies: str = "none",
                     model: str = "small", device: str = "cpu",
                     keep_audio: bool = False, refresh: bool = False) -> tuple[Path, str]:
    """Reuse valid transcriptions, else download audio and perform local inference.

    An access challenge from yt-dlp propagates unchanged; ASR cannot bypass it.
    Partial transcript files are never returned. A user may retain the source
    audio with keep_audio; otherwise clean it only after success.
    """
    if model not in ASR_MODELS or device not in ASR_DEVICES:
        raise ValueError("Unsupported ASR model/device")
    video_id = youtube_video_id(url)
    directory = output_root / video_id
    if not refresh:
        cached = cached_asr(directory, model=model)
        if cached is not None:
            return cached, "local-asr-cached"
    print(f"[ASR] {video_id}: no usable YouTube captions; acquiring audio", flush=True)
    audio = download_audio(url, directory, cookies=cookies)
    target = directory / f"local-asr-{model}.vtt"
    try:
        transcript = transcribe_audio(audio, target, model=model, device=device)
    except BaseException:
        # Audio is retained after interrupted/failed transcriptions to allow
        # local retry without another YouTube download.
        raise
    if not keep_audio:
        audio.unlink(missing_ok=True)
    print(f"[ASR] {video_id}: saved timestamped transcript {transcript}", flush=True)
    return transcript, "local-asr"


def available() -> bool:
    from importlib.util import find_spec
    return find_spec("faster_whisper") is not None
