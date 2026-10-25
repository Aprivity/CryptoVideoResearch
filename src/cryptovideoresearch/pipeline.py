"""Subprocess-based YouTube captions -> Summarize -> DeepSeek pipeline."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import DEFAULT_MODEL, make_model_env

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# YouTube uses many regional and auto-translated language tags.
# "--sub-langs" supports regex, unlike the old fixed five-language allowlist.
LANGUAGE_ORDER = (
    "zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh-HK", "zh-SG", "zh",
    "en-orig", "en-US", "en-GB", "en",
)
SUB_LANGS = "zh.*,en.*"


class PipelineError(RuntimeError):
    """Expected user-facing extraction or analysis failure."""


class NoCaptionsError(PipelineError):
    """No valid YouTube VTT tracks could be obtained; ASR is now appropriate."""


class YouTubeAccessError(PipelineError):
    """YouTube requests verification; caption availability is still unknown."""


def youtube_auth_challenge(details: str) -> bool:
    """Detect the explicit YouTube bot challenge without guessing caption status."""
    lower = details.casefold().replace("’", "'")
    return "sign in to confirm" in lower and "not a bot" in lower


def youtube_video_id(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise PipelineError("Provide a valid https:// YouTube video URL")
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        segments = [segment for segment in parts.path.split("/") if segment]
        if parts.path == "/watch":
            video_id = parse_qs(parts.query).get("v", [""])[0]
        elif len(segments) == 2 and segments[0] in ("shorts", "live", "embed"):
            video_id = segments[1]
        else:
            video_id = ""
    elif host in ("youtu.be", "www.youtu.be"):
        video_id = parts.path.strip("/")
    else:
        raise PipelineError("Only youtube.com and youtu.be video URLs are supported")
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise PipelineError("Invalid YouTube video ID")
    return video_id


def find_ytdlp() -> str | None:
    # Prefer pipx version over old distribution packages.
    candidate = Path.home() / ".local" / "bin" / "yt-dlp"
    if candidate.is_file() and candidate.stat().st_mode & 0o111:
        return str(candidate)
    return shutil.which("yt-dlp")


def checked_run(
    command: list[str], *, timeout: int, input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, input=input_text, text=True, encoding="utf-8",
            capture_output=True, timeout=timeout, env=env, check=False,
        )
    except FileNotFoundError as exc:
        raise PipelineError(f"Required command not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"Command timed out after {timeout}s: {command[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "No diagnostic output").strip()[-1400:]
        if Path(command[0]).name == "yt-dlp" and youtube_auth_challenge(detail):
            raise YouTubeAccessError(
                "YouTube requires sign-in/bot verification, so subtitle availability "
                "cannot be checked. Sign in to YouTube in a supported browser and "
                "select that browser in B Settings (e.g. Cookies: chrome); "
                "if it still fails, do not repeatedly retry anonymous requests. "
                f"yt-dlp: {detail[-500:]}"
            )
        raise PipelineError(f"{command[0]} exited {result.returncode}: {detail}")
    return result


def valid_vtt(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 200:
            return False
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return False
    if not content.lstrip().startswith("WEBVTT") or "-->" not in content:
        return False
    dialogue = [
        line.strip() for line in content.splitlines()
        if line.strip() and "-->" not in line and not line.startswith(
            ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")
        )
    ]
    return sum(len(line) for line in dialogue) >= 80


def prefer_caption(video_dir: Path) -> Path | None:
    # yt-dlp emits files like VIDEO_ID.zh-Hans.vtt. Do not read unrelated files.
    # An ASR transcript is not a genuine YouTube caption track. Only the
    # dedicated optional fallback may reuse it.
    files = [p for p in video_dir.glob("*.vtt")
             if not p.name.startswith("local-asr-") and valid_vtt(p)]
    if not files:
        return None
    def priority(path: Path) -> int:
        return next(
            (i for i, lang in enumerate(LANGUAGE_ORDER) if path.name.endswith(f".{lang}.vtt")),
            len(LANGUAGE_ORDER),
        )
    return min(files, key=lambda p: (priority(p), p.name))


def extract_captions(
    url: str, output_root: Path, *, cookies: str = "none", refresh: bool = False
) -> tuple[Path, str]:
    video_id = youtube_video_id(url)
    target = output_root / video_id
    target.mkdir(parents=True, exist_ok=True)
    if not refresh:
        existing = prefer_caption(target)
        if existing is not None:
            return existing, "cached"
    executable = find_ytdlp()
    if executable is None:
        raise PipelineError("yt-dlp missing; run scripts/install.sh")
    if cookies not in ("none", "chrome", "firefox", "chromium", "brave"):
        raise PipelineError("Invalid cookies browser")
    errors = []
    for mode, switch in (("uploaded", "--write-subs"), ("automatic", "--write-auto-subs")):
        command = [
            executable, "--no-playlist", "--skip-download",
            "--js-runtimes", "node", switch,
            "--sub-langs", SUB_LANGS, "--sub-format", "vtt",
            "-o", str(target / "%(id)s.%(ext)s"), url,
        ]
        if cookies != "none":
            command[1:1] = ["--cookies-from-browser", cookies]
        try:
            checked_run(command, timeout=180)
        except YouTubeAccessError:
            # The login challenge is not evidence of missing subtitles.
            # Trying the alternative --write-auto-subs mode only repeats it.
            raise
        except PipelineError as exc:
            errors.append(str(exc))
            continue
        found = prefer_caption(target)
        if found is not None:
            return found, mode
    note = "; ".join(errors)[-1600:] if errors else (
        "yt-dlp exited successfully but returned no valid zh*/en* VTT subtitles; "
        "the uploader may not provide captions, YouTube may not offer auto-captions, "
        "or subtitles may be restricted"
    )
    raise NoCaptionsError(
        "No valid complete subtitle file was obtained; the YouTube description "
        "will NOT be sent to the model. Check video captions, proxy, cookies. " + note
    )


def default_prompt_path() -> Path:
    # Editable install from the GitHub source tree; allow an explicit override in callers.
    return Path(__file__).resolve().parents[2] / "prompts" / "crypto_research_zh.md"


def analyze_transcript(
    transcript: Path, *, model: str = DEFAULT_MODEL, prompt: Path | None = None
) -> str:
    if not transcript.is_file():
        raise PipelineError(f"Transcript file not found: {transcript}")
    content = transcript.read_text(encoding="utf-8-sig")
    if transcript.suffix.lower() == ".vtt":
        if not valid_vtt(transcript):
            raise PipelineError("VTT is empty, incomplete, or missing caption timestamps")
    elif len(content.strip()) < 80:
        raise PipelineError("Transcript too short; refusing to summarize a description")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise PipelineError("Invalid model name")
    prompt_path = prompt or default_prompt_path()
    if not prompt_path.is_file():
        raise PipelineError(f"Prompt file not found: {prompt_path}")
    binary = shutil.which("summarize")
    if binary is None:
        raise PipelineError("Summarize CLI missing; run scripts/install.sh")
    command = [
        binary, "-", "--model", "openai/" + model,
        "--prompt-file", str(prompt_path), "--language", "zh",
        "--length", "long", "--force-summary", "--plain", "--timeout", "5m",
    ]
    result = checked_run(command, input_text=content, timeout=420, env=make_model_env())
    output = result.stdout.strip()
    if len(output) < 30:
        raise PipelineError("AI returned empty or unusually short output")
    return output + "\n"


def write_report(
    *, output_root: Path, video_id: str, source_url: str | None,
    transcript: Path, subtitle_source: str, summary: str, model: str
) -> Path:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise PipelineError("Invalid report video ID")
    folder = output_root / video_id
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / "analysis.md"
    tmp_path = folder / "analysis.md.tmp"
    tmp_path.write_text(summary, encoding="utf-8")
    tmp_path.replace(report_path)
    payload = {
        "schema_version": "0.1.0",
        "video_id": video_id,
        "source_url": source_url,
        "subtitle_file": str(transcript.resolve()),
        "subtitle_source": subtitle_source,
        "model": "openai/" + model,
        "analysis_file": str(report_path.resolve()),
        "verification_status": "unverified",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Research extraction only; not investment advice.",
    }
    json_tmp = folder / "report.json.tmp"
    json_tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json_tmp.replace(folder / "report.json")
    return report_path
