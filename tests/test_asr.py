"""V0.7 local ASR tests: mocked audio and Whisper; no model downloads or network."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.asr import (
    cached_asr, download_audio, format_timestamp, normalized_proxy_environment,
    transcribe_audio, transcribe_video,
)
from cryptovideoresearch.cli import asr_pip_environment, build_parser
from cryptovideoresearch.pipeline import (
    NoCaptionsError, PipelineError, YouTubeAccessError, prefer_caption,
    valid_vtt,
)
from cryptovideoresearch.youtube_news import Video, analyze_selected


VIDEO_ID = "DiDuGTf_-0g"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
GOOD_TEXT = (
    "这段音频讨论美国经济数据和市场风险，并解释几个关键观点。"
    "视频内容来自播主的个人评论，不代表任何已经获得核实的新闻事件。"
    "请对照官方数据与发布时间，独立检查所有数字。"
)


def fake_video(video_id: str = VIDEO_ID) -> Video:
    return Video(
        id=video_id, title="财经新闻解读", channel="Creator",
        url=f"https://www.youtube.com/watch?v={video_id}",
        topic="YouTuber 频道", published_at_utc=None,
        duration_seconds=1800, views=None, relevance_score=0,
        time_status="unknown",
    )


class ASRTests(unittest.TestCase):
    def test_vtt_timestamp_and_atomic_transcript(self):
        self.assertEqual(format_timestamp(3661.25), "01:01:01.250")
        self.assertEqual(format_timestamp(-1), "00:00:00.000")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.m4a"
            audio.write_bytes(b"A" * 2048)
            class FakeWhisper:
                def __init__(self, *args, **kwargs):
                    self.asserted_kwargs = kwargs
                def transcribe(self, path, **kwargs):
                    self.path = path
                    self.options = kwargs
                    return iter([
                        types.SimpleNamespace(start=0, end=8.5, text=GOOD_TEXT),
                        types.SimpleNamespace(start=8.5, end=9.0, text="  第二段话  "),
                    ]), types.SimpleNamespace(language="zh")
            with patch.dict(sys.modules, {"faster_whisper":
                                         types.SimpleNamespace(WhisperModel=FakeWhisper)}), \
                 patch("cryptovideoresearch.asr.model_cache_dir", return_value=root / "model-cache"):
                dest = transcribe_audio(audio, root / "local-asr-small.vtt")
            self.assertEqual(dest.name, "local-asr-small.vtt")
            self.assertTrue(valid_vtt(dest))
            self.assertIn("00:00:08.500", dest.read_text(encoding="utf-8"))
            self.assertFalse((root / "local-asr-small.vtt.tmp").exists())
            self.assertIsNone(prefer_caption(root))  # ASR must not masquerade as native subtitle

    def test_proxy_normalization_does_not_mutate_source(self):
        source = {"ALL_PROXY": "socks://127.0.0.1:7890",
                  "https_proxy": "https://example.test:443", "NO_PROXY": "localhost"}
        fixed = normalized_proxy_environment(source)
        self.assertEqual(source["ALL_PROXY"], "socks://127.0.0.1:7890")
        self.assertEqual(fixed["ALL_PROXY"], "socks5://127.0.0.1:7890")
        self.assertEqual(fixed["https_proxy"], source["https_proxy"])
        self.assertEqual(fixed["NO_PROXY"], "localhost")

    def test_pip_bootstrap_uses_local_http_on_socks_only_environment(self):
        source = {
            "HTTP_PROXY": "socks://127.0.0.1:7890",
            "HTTPS_PROXY": "socks://127.0.0.1:7890",
            "ALL_PROXY": "socks://127.0.0.1:7890",
            "NO_PROXY": "localhost",
        }
        env, reason = asr_pip_environment(source, pip_socks_available=False)
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["ALL_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["http_proxy"], "http://127.0.0.1:7890")
        self.assertEqual(env["NO_PROXY"], "localhost")
        self.assertEqual(source["HTTP_PROXY"], "socks://127.0.0.1:7890")
        self.assertIn("temporary local HTTP", reason)

    def test_pip_bootstrap_respects_explicit_http_proxy_and_rejects_socks(self):
        source = {"ALL_PROXY": "socks://127.0.0.1:7890"}
        env, mode = asr_pip_environment(
            source, pip_proxy="http://127.0.0.1:7891", pip_socks_available=False,
        )
        self.assertEqual(env["ALL_PROXY"], "http://127.0.0.1:7891")
        self.assertEqual(mode, "explicit HTTP(S) proxy")
        for invalid in (
            "socks5://127.0.0.1:7890", "http://user:pass@127.0.0.1:7890",
            "https://127.0.0.1:7890/?next=1",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(PipelineError):
                asr_pip_environment(source, pip_proxy=invalid)

    def test_pip_bootstrap_rejects_nonlocal_sockshost_without_http_listener(self):
        with self.assertRaises(PipelineError):
            asr_pip_environment({"HTTPS_PROXY": "socks5://proxy.example.test:1080"},
                                pip_socks_available=False)

    def test_asr_setup_repairs_existing_pyav_19_instead_of_returning_early(self):
        from cryptovideoresearch.cli import cmd_asr_setup
        from argparse import Namespace
        with patch("cryptovideoresearch.asr.available", return_value=True), \
             patch("cryptovideoresearch.asr.installed_pyav_major", return_value=19), \
             patch("cryptovideoresearch.cli.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, "", "")) as runner:
            self.assertEqual(
                cmd_asr_setup(Namespace(pip_proxy="http://127.0.0.1:7890")), 0,
            )
        packages = runner.call_args.args[0]
        self.assertIn("av>=11,<19", packages)
        self.assertIn("faster-whisper>=1.1,<2", packages)

    def test_incompatible_pyav_is_detected_before_video_download(self):
        from cryptovideoresearch.cli import require_asr_runtime
        with patch("cryptovideoresearch.asr.available", return_value=True), \
             patch("cryptovideoresearch.asr.installed_pyav_major", return_value=19):
            with self.assertRaisesRegex(PipelineError, "asr-setup"):
                require_asr_runtime()

    def test_legacy_decoder_kwarg_error_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.m4a"
            audio.write_bytes(b"A" * 2048)
            class OldDecoderWhisper:
                def __init__(self, *args, **kwargs):
                    pass
                def transcribe(self, *args, **kwargs):
                    raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
            with patch.dict(sys.modules, {
                "faster_whisper": types.SimpleNamespace(WhisperModel=OldDecoderWhisper)
            }):
                with self.assertRaisesRegex(PipelineError, "av>=11,<19"):
                    transcribe_audio(audio, root / "local-asr-base.vtt", model="base")
            self.assertTrue(audio.exists())

    def test_asr_setup_direct_install_avoids_isolated_project_build(self):
        from cryptovideoresearch.cli import cmd_asr_setup
        from argparse import Namespace
        env = {"HTTPS_PROXY": "socks://127.0.0.1:7890"}
        with patch.dict(os.environ, env), \
             patch("cryptovideoresearch.asr.available", return_value=False), \
             patch("cryptovideoresearch.cli.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, "", "")) as pip:
            self.assertEqual(cmd_asr_setup(Namespace(pip_proxy="http://127.0.0.1:7890")), 0)
        args, kwargs = pip.call_args
        self.assertIn("faster-whisper>=1.1,<2", args[0])
        self.assertIn("httpx[socks]>=0.27,<1", args[0])
        self.assertIn("av>=11,<19", args[0])
        self.assertNotIn("-e", args[0])
        self.assertEqual(kwargs["env"]["HTTPS_PROXY"], "http://127.0.0.1:7890")

    def test_legacy_socks_proxy_normalized_only_during_whisper_model_load(self):
        from cryptovideoresearch.asr import PROXY_ENV_KEYS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.m4a"
            audio.write_bytes(b"A" * 2048)
            recorded = {}
            class FakeWhisper:
                def __init__(self, *args, **kwargs):
                    recorded.update({key: os.environ.get(key) for key in PROXY_ENV_KEYS})
                def transcribe(self, path, **kwargs):
                    return iter([types.SimpleNamespace(
                        start=0, end=12.0, text=GOOD_TEXT,
                    )]), types.SimpleNamespace(language="zh")
            originals = {
                "HTTP_PROXY": "socks://127.0.0.1:7890",
                "https_proxy": "SoCkS://localhost:7890",
                "ALL_PROXY": "socks://user:pass@127.0.0.1:7891",
                "NO_PROXY": "localhost,127.0.0.1",
            }
            with patch.dict(os.environ, originals), \
                 patch.dict(sys.modules, {"faster_whisper":
                                         types.SimpleNamespace(WhisperModel=FakeWhisper)}), \
                 patch("cryptovideoresearch.asr.model_cache_dir",
                       return_value=root / "whisper-models"):
                dest = transcribe_audio(audio, root / "local-asr-small.vtt")
                for key in originals:
                    self.assertEqual(os.environ[key], originals[key])
            self.assertTrue(valid_vtt(dest))
            self.assertEqual(recorded["HTTP_PROXY"], "socks5://127.0.0.1:7890")
            self.assertEqual(recorded["https_proxy"], "socks5://localhost:7890")
            self.assertEqual(recorded["ALL_PROXY"], "socks5://user:pass@127.0.0.1:7891")

    def test_proxy_environment_restored_after_whisper_download_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.m4a"
            audio.write_bytes(b"A" * 2048)
            class FakeWhisper:
                def __init__(self, *args, **kwargs):
                    self.check = os.environ["HTTPS_PROXY"]
                    self.asserted = self.check
                    raise ValueError("network failure")
            with patch.dict(os.environ, {"HTTPS_PROXY": "socks://127.0.0.1:7890"}), \
                 patch.dict(sys.modules, {"faster_whisper":
                                         types.SimpleNamespace(WhisperModel=FakeWhisper)}):
                with self.assertRaises(PipelineError):
                    transcribe_audio(audio, root / "local-asr-small.vtt")
                self.assertEqual(os.environ["HTTPS_PROXY"], "socks://127.0.0.1:7890")

    def test_download_uses_only_audio_and_browser_cookies(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_run(command, **_kwargs):
                self.assertIn("bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio", command)
                self.assertIn("--max-filesize", command)
                self.assertIn("--cookies-from-browser", command)
                self.assertIn("chrome", command)
                self.assertNotIn("--extract-audio", command)
                (Path(folder) / (VIDEO_ID + ".source.m4a")).write_bytes(b"A" * 2048)
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("cryptovideoresearch.asr.find_ytdlp",
                       return_value="/fake/yt-dlp"), \
                 patch("cryptovideoresearch.asr.checked_run", side_effect=fake_run) as runner:
                result = download_audio(URL, Path(folder), cookies="chrome")
            self.assertEqual(result.suffix, ".m4a")
            self.assertEqual(runner.call_count, 1)

    def test_asr_caches_transcript_without_new_model_or_audio_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / VIDEO_ID
            root.mkdir()
            transcript = root / "local-asr-small.vtt"
            transcript.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:15.000\n" + GOOD_TEXT + "\n",
                encoding="utf-8",
            )
            with patch("cryptovideoresearch.asr.download_audio") as downloader, \
                 patch("cryptovideoresearch.asr.transcribe_audio") as engine:
                returned, source = transcribe_video(URL, Path(folder))
            self.assertEqual(returned, transcript)
            self.assertEqual(source, "local-asr-cached")
            downloader.assert_not_called()
            engine.assert_not_called()

    def test_no_audio_cleanup_when_transcription_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / VIDEO_ID
            root.mkdir()
            audio = root / (VIDEO_ID + ".source.webm")
            audio.write_bytes(b"A" * 2048)
            with patch("cryptovideoresearch.asr.download_audio", return_value=audio), \
                 patch("cryptovideoresearch.asr.transcribe_audio",
                       side_effect=PipelineError("empty transcript")):
                with self.assertRaises(PipelineError):
                    transcribe_video(URL, Path(folder))
            self.assertTrue(audio.exists())

    def test_audio_removed_after_success_by_default_and_keep_option(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / VIDEO_ID
            root.mkdir()
            audio = root / (VIDEO_ID + ".source.m4a")
            audio.write_bytes(b"A" * 2048)
            transcript = root / "local-asr-small.vtt"
            transcript.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:15.000\n" + GOOD_TEXT + "\n",
                encoding="utf-8",
            )
            with patch("cryptovideoresearch.asr.download_audio", return_value=audio), \
                 patch("cryptovideoresearch.asr.transcribe_audio", return_value=transcript):
                transcribe_video(URL, Path(folder), refresh=True)
            self.assertFalse(audio.exists())
            audio.write_bytes(b"A" * 2048)
            with patch("cryptovideoresearch.asr.download_audio", return_value=audio), \
                 patch("cryptovideoresearch.asr.transcribe_audio", return_value=transcript):
                transcribe_video(URL, Path(folder), keep_audio=True, refresh=True)
            self.assertTrue(audio.exists())

    def test_missing_captions_uses_local_asr_then_one_paid_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / "cached.vtt"
            transcript.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:15.000\n" + GOOD_TEXT + "\n",
                encoding="utf-8",
            )
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       side_effect=NoCaptionsError("none")) as native, \
                 patch("cryptovideoresearch.asr.transcribe_video",
                       return_value=(transcript, "local-asr")) as local, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript",
                       return_value="新闻相关性：有具体事件\n事件转述") as deepseek, \
                 patch("cryptovideoresearch.youtube_news.write_report",
                       return_value=root / "report.md") as report:
                items = analyze_selected(
                    [fake_video()], root, 1, "chrome", False, "", [],
                    accept_no_news=True, asr_fallback=True,
                )
            self.assertEqual(items[0]["status"], "analyzed")
            self.assertEqual(items[0]["transcript_source"], "local-asr")
            native.assert_called_once()
            local.assert_called_once()
            deepseek.assert_called_once()
            self.assertEqual(report.call_args.kwargs["subtitle_source"], "local-asr")

    def test_youtube_access_error_never_triggers_asr(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       side_effect=YouTubeAccessError("verification")) as native, \
                 patch("cryptovideoresearch.asr.transcribe_video") as local, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript") as deepseek:
                results = analyze_selected(
                    [fake_video()], Path(folder), 1, "chrome", False, "", [],
                    accept_no_news=True, asr_fallback=True,
                )
            self.assertEqual(results[0]["status"], "access-blocked")
            native.assert_called_once()
            local.assert_not_called()
            deepseek.assert_not_called()

    def test_standalone_transcribe_never_calls_deepseek(self):
        with tempfile.TemporaryDirectory() as folder:
            parser = build_parser()
            args = parser.parse_args([
                "transcribe", URL, "--cookies", "chrome",
                "--asr-model", "base", "--output-dir", folder,
            ])
            transcript = Path(folder) / "local-asr-base.vtt"
            transcript.write_text(
                "WEBVTT\\n\\n00:00:00.000 --> 00:00:15.000\\n" + GOOD_TEXT,
                encoding="utf-8",
            )
            with patch("cryptovideoresearch.cli.extract_captions",
                       side_effect=NoCaptionsError("no subtitles")) as native, \
                 patch("cryptovideoresearch.asr.available", return_value=True), \
                 patch("cryptovideoresearch.asr.transcribe_video",
                       return_value=(transcript, "local-asr")) as transcriber, \
                 patch("cryptovideoresearch.cli.analyze_transcript") as deepseek:
                self.assertEqual(args.handler(args), 0)
            native.assert_called_once()
            transcriber.assert_called_once()
            deepseek.assert_not_called()

    def test_asr_is_opt_in_on_all_command_lines(self):
        parser = build_parser()
        standard = parser.parse_args(["run", "--count", "1"])
        self.assertFalse(standard.asr_fallback)
        self.assertEqual(standard.asr_model, "small")
        enabled = parser.parse_args([
            "run", "--count", "1", "--asr-fallback",
            "--asr-model", "base", "--asr-device", "cpu",
        ])
        self.assertTrue(enabled.asr_fallback)
        self.assertEqual(enabled.asr_model, "base")
        y = parser.parse_args(["youtube-news", "--asr-fallback"])
        self.assertTrue(y.asr_fallback)


if __name__ == "__main__":
    unittest.main()
