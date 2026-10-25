"""User-facing commands for the research-only video workflow."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from .config import DEFAULT_MODEL, key_path, load_key, save_key
from .pipeline import (
    PipelineError, analyze_transcript, default_prompt_path,
    extract_captions, find_ytdlp, valid_vtt, write_report, youtube_video_id,
)

YOUTUBE_LOGIN_URL = "https://www.youtube.com/"


def cmd_setup(args: argparse.Namespace) -> int:
    if not args.skip_key:
        if key_path().is_file() and not args.replace_key:
            print(f"API key already configured at {key_path()}; not overwriting.")
        elif os.environ.get("DEEPSEEK_API_KEY") and not args.replace_key:
            print("DEEPSEEK_API_KEY already present in this process; not saving it.")
        elif not sys.stdin.isatty():
            raise PipelineError("Run setup in an interactive terminal, or export DEEPSEEK_API_KEY")
        else:
            value = getpass.getpass("DeepSeek API Key (hidden input): ")
            try:
                path = save_key(value)
            finally:
                value = ""
            print(f"API key saved to {path} (mode 0600).")
    print("To diagnose dependencies: cryptovideo doctor")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0
    def show(name: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        status = "OK" if ok else "MISSING"
        print(f"[{status}] {name}{': ' + detail if detail else ''}")
        if not ok:
            problems += 1

    node = shutil.which("node")
    major = 0
    version = "not installed"
    if node:
        try:
            version = subprocess.check_output([node, "--version"], text=True, timeout=5).strip()
            major = int(version.lstrip("v").split(".")[0])
        except (ValueError, OSError, subprocess.SubprocessError):
            version = "unable to determine version"
    show("Node.js >= 24", major >= 24, version)
    show("npm", shutil.which("npm") is not None)
    show("Summarize", shutil.which("summarize") is not None)
    show("yt-dlp", find_ytdlp() is not None, find_ytdlp() or "")
    show("prompt file", default_prompt_path().is_file())
    print(f"[INFO] FFmpeg: {'found' if shutil.which('ffmpeg') else 'optional, not installed'}")
    from .asr import available as asr_available
    print(f"[INFO] Optional local ASR: {'installed' if asr_available() else 'disabled (run cryptovideo asr-setup)'}")
    print(f"[INFO] Tesseract: {'found' if shutil.which('tesseract') else 'optional, not installed'}")
    print(f"[INFO] proxy: {'configured' if any(os.environ.get(k) for k in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy')) else 'not configured'}")
    try:
        load_key()
        print("[OK] DeepSeek key: configured (value hidden)")
    except RuntimeError:
        print("[INFO] DeepSeek key: missing (run cryptovideo setup)")
    print("The doctor runs no API calls, browser logins, or paid requests.")
    return 1 if problems else 0


def cmd_asr_setup(args: argparse.Namespace) -> int:
    """Install the opt-in ASR dependency, without downloading model weights."""
    from .asr import available
    from importlib.util import find_spec
    if available() and find_spec("socksio") is not None:
        print("[OK] faster-whisper and HTTPX SOCKS proxy support are already installed.")
        return 0
    root = Path(__file__).resolve().parents[2]
    print("[ASR] Installing or upgrading optional faster-whisper and SOCKS proxy support via pip.")
    print("[ASR] Model weights will only download upon your first ASR transcription.")
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", f"{root}[asr]"],
        check=False,
    )
    if completed.returncode:
        print("[FAIL] Optional ASR installation failed; normal caption-only mode is unaffected.",
              file=sys.stderr)
        return completed.returncode
    print("[OK] Local ASR installed. Select ASR fallback in the interactive settings.")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    print("Opening YouTube; sign in or complete verification yourself.")
    if not webbrowser.open(YOUTUBE_LOGIN_URL):
        print(f"Open manually: {YOUTUBE_LOGIN_URL}")
    return 0


def require_asr_runtime() -> None:
    """Fail early before requesting video audio when the optional extra is absent."""
    from .asr import available
    if not available():
        raise PipelineError("Local ASR runtime is not installed. Run: cryptovideo asr-setup")


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Free-of-DeepSeek subtitle extraction with optional local ASR fallback."""
    from .pipeline import NoCaptionsError
    root = Path(args.output_dir).expanduser().resolve()
    try:
        transcript, source = extract_captions(
            args.url, root, cookies=args.cookies, refresh=False,
        )
    except NoCaptionsError:
        require_asr_runtime()
        from .asr import transcribe_video
        transcript, source = transcribe_video(
            args.url, root, cookies=args.cookies,
            model=args.asr_model, device=args.asr_device,
            keep_audio=args.keep_audio, refresh=False,
        )
    print(f"[OK] Transcript source: {source}")
    print(f"[OK] Transcript file: {transcript}")
    print("[INFO] No DeepSeek calls were made.")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    load_key()  # Fail fast before requesting the video.
    video_id = youtube_video_id(args.url)
    root = Path(args.output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    from .pipeline import NoCaptionsError
    try:
        transcript, source = extract_captions(
            args.url, root, cookies=args.cookies, refresh=False
        )
    except NoCaptionsError:
        if not args.asr_fallback:
            raise
        require_asr_runtime()
        from .asr import transcribe_video
        transcript, source = transcribe_video(
            args.url, root, cookies=args.cookies, model=args.asr_model,
            device=args.asr_device, keep_audio=args.keep_audio,
        )
    print(f"Transcript: {transcript} ({source})", file=sys.stderr)
    summary = analyze_transcript(
        transcript, model=args.model,
        prompt=Path(args.prompt).expanduser() if args.prompt else None,
    )
    report = write_report(
        output_root=root, video_id=video_id, source_url=args.url,
        transcript=transcript, subtitle_source=source,
        summary=summary, model=args.model,
    )
    print(f"Saved: {report}")
    print(f"Metadata: {report.parent / 'report.json'}")
    return 0


def cmd_analyze_file(args: argparse.Namespace) -> int:
    load_key()
    transcript = Path(args.transcript).expanduser().resolve()
    if not transcript.is_file():
        raise PipelineError(f"File not found: {transcript}")
    if transcript.suffix.lower() == ".vtt" and not valid_vtt(transcript):
        raise PipelineError("Invalid or empty VTT file")
    video_id = args.video_id
    if not video_id:
        raise PipelineError("--video-id is required for analyze-file")
    from .pipeline import VIDEO_ID_RE
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise PipelineError("--video-id must be an 11-character YouTube video ID")
    root = Path(args.output_dir).expanduser().resolve()
    summary = analyze_transcript(
        transcript, model=args.model,
        prompt=Path(args.prompt).expanduser() if args.prompt else None,
    )
    report = write_report(
        output_root=root, video_id=video_id, source_url=None,
        transcript=transcript, subtitle_source="local-file",
        summary=summary, model=args.model,
    )
    print(f"Saved: {report}")
    return 0


def cmd_news(args: argparse.Namespace) -> int:
    """Run one news scan using the repository's configured RSS feeds."""
    from .news_monitor import main as run_news

    root = Path(__file__).resolve().parents[2]
    config = Path(args.config).expanduser() if args.config else root / "news_sources.json"
    output = Path(args.output).expanduser() if args.output else root / "outputs/news"
    argv = [
        "--config", str(config), "--output", str(output),
        "--hours", str(args.hours), "--limit", str(args.limit),
    ]
    if args.fixture:
        argv.extend(["--fixture", args.fixture])
    return run_news(argv)


def cmd_youtube_news(args: argparse.Namespace) -> int:
    """Discover YouTube market-news explainers; optional paid video analysis."""
    if args.asr_fallback and args.analyze_top > 0:
        require_asr_runtime()
    from .youtube_news import main as run_youtube_news

    root = Path(__file__).resolve().parents[2]
    config = Path(args.config).expanduser() if args.config else root / "youtube_news_queries.json"
    if args.channel:
        from .channels import normalize_channel, channel_slug
        url = normalize_channel(args.channel)
        output = Path(args.output).expanduser() if args.output else root / "outputs" / "youtubers" / channel_slug(url)
    else:
        url = None
        output = Path(args.output).expanduser() if args.output else root / "outputs/youtube-news"
    argv = [
        "--config", str(config), "--output", str(output),
        "--hours", str(args.hours), "--per-query", str(args.per_query),
        "--max-results", str(args.max_results), "--min-seconds", str(args.min_seconds),
        "--analyze-top", str(args.analyze_top), "--cookies", args.cookies,
        "--verify-top", str(args.verify_top),
    ]
    if url:
        argv.extend(["--channel", url])
    if args.fixture:
        argv.extend(["--fixture", args.fixture])
    if args.refresh:
        argv.append("--refresh")
    if args.allow_unknown_age:
        argv.append("--allow-unknown-age")
    if args.model:
        argv.extend(["--model", args.model])
    if args.asr_fallback:
        argv.extend(["--asr-fallback", "--asr-model", args.asr_model,
                     "--asr-device", args.asr_device])
    if args.keep_audio:
        argv.append("--keep-audio")
    return run_youtube_news(argv)


def cmd_run(args: argparse.Namespace) -> int:
    """One-command discovery plus separate reports for a bounded number of videos."""
    # A single invocation deliberately limits paid model analysis to 1..5
    # successful/cached reports. Never repeat paid work when a report exists.
    if args.count > 0:
        load_key()  # Fail before YouTube requests if no DeepSeek key.
        if args.asr_fallback:
            require_asr_runtime()
    from .youtube_news import main as run_youtube_news

    root = Path(__file__).resolve().parents[2]
    config = Path(args.config).expanduser() if args.config else root / "youtube_news_queries.json"
    if args.channel:
        from .channels import normalize_channel, channel_slug
        url = normalize_channel(args.channel)
        output = Path(args.output).expanduser() if args.output else root / "outputs" / "youtubers" / channel_slug(url)
    else:
        url = None
        output = Path(args.output).expanduser() if args.output else root / "outputs/youtube-news"
    argv = [
        "--config", str(config), "--output", str(output),
        "--hours", str(args.hours),
        "--per-query", str(args.per_query),
        "--max-results", str(args.max_results),
        "--verify-top", str(args.verify_top),
        "--analyze-top", str(args.count),
        "--cookies", args.cookies,
    ]
    if url:
        argv.extend(["--channel", url])
    if args.count and not args.strict_dates:
        # First ask YouTube for actual upload dates; when the platform omits
        # them, the report still labels such videos "unknown".
        print("[NOTICE] Videos without a verified upload date can be analyzed; "
              "their age and news claims remain unverified.")
        argv.append("--allow-unknown-age")
    if args.refresh:
        argv.append("--refresh")
    if args.model:
        argv.extend(["--model", args.model])
    if args.asr_fallback:
        argv.extend(["--asr-fallback", "--asr-model", args.asr_model,
                     "--asr-device", args.asr_device])
    if args.keep_audio:
        argv.append("--keep-audio")
    if args.fixture:
        argv.extend(["--fixture", args.fixture])
    started_at = time.time()
    code = run_youtube_news(argv)
    metadata = output / "latest.json"
    # Even a no-news run writes a real individual report. Don't hide its path.
    # Avoid accidentally showing stale output if discovery failed before rendering.
    if metadata.is_file() and metadata.stat().st_mtime >= started_at - 2:
        print(f"\nVideo candidate index: {output / 'latest.md'}")
        details = json.loads(metadata.read_text(encoding="utf-8"))
        present = [
            record for record in details.get("analyses", [])
            if record.get("status") in (
                "cached", "analyzed", "cached-no-news", "analyzed-no-news"
            )
        ]
        for item in present:
            print(f"Video report ({item['status']}, {item.get('classification', 'unclassified')}): "
                  f"{item['analysis_file']}")
        if args.count and not present:
            print("[NOTICE] No report produced. Read latest.md for missing dates, "
                  "unavailable subtitles or YouTube access errors.")
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cryptovideo",
        description="Research-only YouTube caption extraction and DeepSeek summaries",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    menu = sub.add_parser("menu", help="Interactive B menu: arrows, digits or Enter for news")
    menu.set_defaults(handler=lambda args: __import__(
        "cryptovideoresearch.interactive", fromlist=["main"]
    ).main())
    setup = sub.add_parser("setup", help="Securely configure a DeepSeek API key")
    setup.add_argument("--replace-key", action="store_true", help="Replace local key")
    setup.add_argument("--skip-key", action="store_true", help="Skip key input")
    setup.set_defaults(handler=cmd_setup)
    doctor = sub.add_parser("doctor", help="Check local dependencies (offline)")
    doctor.set_defaults(handler=cmd_doctor)
    setup_asr = sub.add_parser("asr-setup", help="Install optional local ASR runtime (no model download)")
    setup_asr.set_defaults(handler=cmd_asr_setup)
    login = sub.add_parser("login", help="Open YouTube for manual sign-in/verification")
    login.set_defaults(handler=cmd_login)
    news = sub.add_parser("news", help="Fetch RSS news once, de-duplicate and write a source-linked report")
    news.add_argument("--config", help="Override news_sources.json")
    news.add_argument("--output", help="Override news report directory")
    news.add_argument("--hours", type=int, default=72, help="Lookback window in hours")
    news.add_argument("--limit", type=int, default=100, help="Maximum report items")
    news.add_argument("--fixture", help="Offline RSS XML fixture for repeatable testing")
    news.set_defaults(handler=cmd_news)
    ytnews = sub.add_parser("youtube-news", help="Search YouTube for market-news videos (no paid APIs by default)")
    ytnews.add_argument("--config", help="Override youtube_news_queries.json")
    ytnews.add_argument("--channel", help="Only collect videos from this @handle or official YouTube channel URL")
    ytnews.add_argument("--output", help="Output directory for video candidates and optional analyses")
    ytnews.add_argument("--hours", type=int, default=168, help="Exclude known-old uploads; unknown times remain labeled")
    ytnews.add_argument("--per-query", type=int, default=8, help="YouTube search result count per query")
    ytnews.add_argument("--max-results", type=int, default=15, help="Maximum video candidates")
    ytnews.add_argument("--min-seconds", type=int, default=90, help="Skip very short videos when duration is known")
    ytnews.add_argument("--verify-top", type=int, default=5, help="Verify upload dates on top N candidates; 0 disables (faster)")
    ytnews.add_argument("--allow-unknown-age", action="store_true", help="Explicitly allow paid analysis of undated videos")
    ytnews.add_argument("--analyze-top", type=int, default=0, help="Analyze top N videos with Summarize + DeepSeek (paid)")
    ytnews.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
    ytnews.add_argument("--model", help="Model name if analyzing")
    ytnews.add_argument("--fixture", help="Offline YouTube search JSON fixture")
    ytnews.add_argument("--refresh", action="store_true", help="Re-analyze existing summaries")
    ytnews.add_argument("--asr-fallback", action="store_true", help="Use optional local Whisper when subtitles are missing")
    ytnews.add_argument("--asr-model", choices=("tiny", "base", "small", "medium"), default="small")
    ytnews.add_argument("--asr-device", choices=("cpu", "cuda"), default="cpu")
    ytnews.add_argument("--keep-audio", action="store_true", help="Retain source audio after successful ASR")
    ytnews.set_defaults(handler=cmd_youtube_news)
    transcribe = sub.add_parser("transcribe", help="Get video captions or local ASR transcript (no DeepSeek call)")
    transcribe.add_argument("url", help="Single YouTube video URL")
    transcribe.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
    transcribe.add_argument("--asr-model", choices=("tiny", "base", "small", "medium"), default="small")
    transcribe.add_argument("--asr-device", choices=("cpu", "cuda"), default="cpu")
    transcribe.add_argument("--keep-audio", action="store_true")
    transcribe.add_argument("--output-dir", default="./outputs/asr-validation")
    transcribe.set_defaults(handler=cmd_transcribe)
    run = sub.add_parser("run", help="One command: search YouTube and generate separate AI video reports")
    run.add_argument("--count", type=int, choices=range(1, 6), default=2,
                     metavar="{1..5}", help="Number of successful/cached reports to produce (default 2)")
    run.add_argument("--hours", type=int, default=168, help="Recency window (default 7 days)")
    run.add_argument("--verify-top", type=int, default=10, help="Check upload dates for top N search results")
    run.add_argument("--per-query", type=int, default=8)
    run.add_argument("--max-results", type=int, default=20)
    run.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
    run.add_argument("--strict-dates", action="store_true",
                     help="Only analyze videos confirmed to be in the requested time window")
    run.add_argument("--refresh", action="store_true", help="Re-run DeepSeek for existing reports")
    run.add_argument("--asr-fallback", action="store_true", help="Fallback to local Whisper for videos without subtitles")
    run.add_argument("--asr-model", choices=("tiny", "base", "small", "medium"), default="small")
    run.add_argument("--asr-device", choices=("cpu", "cuda"), default="cpu")
    run.add_argument("--keep-audio", action="store_true", help="Keep source audio after successful ASR")
    run.add_argument("--model", help="Override model used for video analysis")
    run.add_argument("--config", help="Custom YouTube search configuration")
    run.add_argument("--channel", help="YouTuber @handle or official channel URL; report separately")
    run.add_argument("--output", help="Custom report directory")
    run.add_argument("--fixture", help="Offline search fixture (for developer testing)")
    run.set_defaults(handler=cmd_run)
    for command in ("analyze", "analyze-file"):
        p = sub.add_parser(command, help="Analyze a YouTube URL or an existing transcript")
        if command == "analyze":
            p.add_argument("url", help="YouTube watch/short/live URL")
            p.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
            p.add_argument("--refresh", action="store_true", help="Attempt to fetch captions again")
            p.add_argument("--asr-fallback", action="store_true", help="Optional local Whisper if no captions")
            p.add_argument("--asr-model", choices=("tiny", "base", "small", "medium"), default="small")
            p.add_argument("--asr-device", choices=("cpu", "cuda"), default="cpu")
            p.add_argument("--keep-audio", action="store_true")
            p.set_defaults(handler=cmd_analyze)
        else:
            p.add_argument("transcript", help="Local VTT or plain UTF-8 text file")
            p.add_argument("--video-id", required=True, help="11-character YouTube video ID")
            p.set_defaults(handler=cmd_analyze_file)
        p.add_argument("--model", default=DEFAULT_MODEL, help="DeepSeek model name (default: deepseek-flash)")
        p.add_argument("--output-dir", default="./outputs", help="Directory for reports and captions")
        p.add_argument("--prompt", help="Alternative prompt Markdown file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .interactive import main as interactive_main
            return interactive_main()
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (PipelineError, RuntimeError, OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
