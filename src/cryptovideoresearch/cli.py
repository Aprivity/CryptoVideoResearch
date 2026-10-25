"""User-facing commands for the research-only video workflow."""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
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
    print(f"[INFO] Tesseract: {'found' if shutil.which('tesseract') else 'optional, not installed'}")
    print(f"[INFO] proxy: {'configured' if any(os.environ.get(k) for k in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy')) else 'not configured'}")
    try:
        load_key()
        print("[OK] DeepSeek key: configured (value hidden)")
    except RuntimeError:
        print("[INFO] DeepSeek key: missing (run cryptovideo setup)")
    print("The doctor runs no API calls, browser logins, or paid requests.")
    return 1 if problems else 0


def cmd_login(args: argparse.Namespace) -> int:
    print("Opening YouTube; sign in or complete verification yourself.")
    if not webbrowser.open(YOUTUBE_LOGIN_URL):
        print(f"Open manually: {YOUTUBE_LOGIN_URL}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    load_key()  # Fail fast before requesting the video.
    video_id = youtube_video_id(args.url)
    root = Path(args.output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    transcript, source = extract_captions(
        args.url, root, cookies=args.cookies, refresh=args.refresh
    )
    print(f"Captions: {transcript} ({source})", file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cryptovideo",
        description="Research-only YouTube caption extraction and DeepSeek summaries",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("setup", help="Securely configure a DeepSeek API key")
    setup.add_argument("--replace-key", action="store_true", help="Replace local key")
    setup.add_argument("--skip-key", action="store_true", help="Skip key input")
    setup.set_defaults(handler=cmd_setup)
    doctor = sub.add_parser("doctor", help="Check local dependencies (offline)")
    doctor.set_defaults(handler=cmd_doctor)
    login = sub.add_parser("login", help="Open YouTube for manual sign-in/verification")
    login.set_defaults(handler=cmd_login)
    for command in ("analyze", "analyze-file"):
        p = sub.add_parser(command, help="Analyze a YouTube URL or an existing transcript")
        if command == "analyze":
            p.add_argument("url", help="YouTube watch/short/live URL")
            p.add_argument("--cookies", choices=("none", "chrome", "firefox", "chromium", "brave"), default="none")
            p.add_argument("--refresh", action="store_true", help="Attempt to fetch captions again")
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
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (PipelineError, RuntimeError, OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
