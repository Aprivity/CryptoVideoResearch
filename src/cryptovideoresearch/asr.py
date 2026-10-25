"""Optional local speech-to-text fallback for YouTube videos without subtitles.

Nothing is downloaded or imported from faster-whisper until the user explicitly
enables --asr-fallback. ASR is local inference; the model weights are fetched
once into the user's cache. Reports and transcripts stay separate per video.
"""
from __future__ import annotations

import os
import re
import importlib
from unittest.mock import patch
from contextlib import contextmanager
from pathlib import Path

from .pipeline import (
    PipelineError, checked_run, find_ytdlp, valid_vtt, youtube_video_id,
)

ASR_MODELS = ("tiny", "base", "small", "medium")
ASR_DEVICES = ("cpu", "cuda")


def installed_pyav_major() -> int | None:
    """Read installed PyAV version without importing its native audio codecs."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return int(version("av").split(".", 1)[0])
    except (PackageNotFoundError, ValueError):
        return None


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



PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def normalized_proxy_environment(source: dict[str, str]) -> dict[str, str]:
    """Return a copy with legacy SOCKS URLs mapped to explicit SOCKS5 URLs."""
    output = dict(source)
    for key in PROXY_ENV_KEYS:
        value = output.get(key)
        if value is not None and value.lower().startswith("socks://"):
            output[key] = "socks5://" + value[len("socks://"):]
    return output


@contextmanager
def compatible_model_download_proxies():
    """Normalize legacy socks:// to socks5:// only while loading Whisper.

    yt-dlp accepts socks://, whereas HTTPX (used by Hugging Face Hub)
    requires a specific SOCKS version. Preserve each original env variable,
    including ALL_PROXY, and restore it even when the download fails.
    The user controls the proxy; do not change host, port, or credentials.
    """
    original = {key: os.environ[key] for key in PROXY_ENV_KEYS
                if key in os.environ and os.environ[key].lower().startswith("socks://")}
    try:
        os.environ.update(normalized_proxy_environment({key: original[key] for key in original}))
        if original:
            print("[ASR] Normalized legacy SOCKS proxy scheme for model download "
                  "(temporary; original environment will be restored)", flush=True)
        yield
    finally:
        for key, value in original.items():
            os.environ[key] = value


@contextmanager
def compatible_pyav_audio_decoder():
    """Temporarily adapt older faster-whisper's av.open call for PyAV >=19.

    Released faster-whisper 1.2.1 passes metadata_errors='ignore', removed
    by PyAV 19. Upstream faster-whisper already fixes this by omitting that
    kwarg with new versions of PyAV. Apply the same compatibility behavior
    only while transcribing, then restore the original function.
    This is process-scoped and does not alter installed site-packages.
    """
    if (installed_pyav_major() or 0) < 19:
        yield
        return
    try:
        fw_audio = importlib.import_module("faster_whisper.audio")
    except ImportError:
        # Older tests stub WhisperModel without the full optional library.
        yield
        return
    pyav = fw_audio.av
    original_open = pyav.open

    def compatible_open(*args, **kwargs):
        if "metadata_errors" in kwargs:
            kwargs = dict(kwargs)
            kwargs.pop("metadata_errors")
        return original_open(*args, **kwargs)

    with patch.object(pyav, "open", compatible_open):
        print("[ASR] PyAV 19+ compatibility for faster-whisper audio decoding enabled",
              flush=True)
        yield


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
        with compatible_model_download_proxies():
            whisper = WhisperModel(
                model, device=device,
                compute_type="int8" if device == "cpu" else "float16",
                download_root=str(root),
            )
        lines = ["WEBVTT", ""]
        # Whisper inference is lazy: the compatibility patch must stay active
        # until every generator segment has been decoded and consumed.
        with compatible_pyav_audio_decoder():
            segments, _ = whisper.transcribe(
                str(audio), beam_size=5, vad_filter=True,
                condition_on_previous_text=False,
            )
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
        message = str(exc)
        if ("Using SOCKS proxy" in message and "socksio" in message) or (
            "socksio" in message and "not installed" in message
        ):
            raise PipelineError(
                "Local ASR model download needs HTTPX SOCKS support. "
                "Run: ./.venv/bin/python -m pip install 'httpx[socks]' "
                "or rerun cryptovideo asr-setup after updating the project."
            ) from exc
        if isinstance(exc, TypeError) and "metadata_errors" in message and "open()" in message:
            raise PipelineError(
                "faster-whisper/PyAV audio decoder unexpectedly rejected metadata_errors. "
                "Update CryptoVideoResearch to use the PyAV 19+ compatibility adapter; "
                "audio is preserved for retry."
            ) from exc
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
