"""Offline tests for the interactive B flow and single-channel mode."""
from __future__ import annotations

import io
import json
import os
import pty
import select
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.channels import (
    Channel, channel_slug, find_channels_by_name, normalize_channel,
)
from cryptovideoresearch.cli import build_parser
from cryptovideoresearch.interactive import (
    choose, load_settings, remember_channel, save_settings,
)
from cryptovideoresearch.youtube_news import Video, analyze_selected, main as news_main


class InteractiveTests(unittest.TestCase):
    def test_default_is_news_on_blank_input(self):
        with patch("cryptovideoresearch.interactive.sys.stdin", io.StringIO("")), \
             patch("builtins.input", return_value=""):
            self.assertEqual(choose("B 工作流", ["市场新闻", "YouTuber", "退出"]), 0)

    def test_menu_accepts_digit_choice(self):
        with patch("cryptovideoresearch.interactive.sys.stdin", io.StringIO("")), \
             patch("builtins.input", return_value="2"):
            self.assertEqual(choose("B 工作流", ["市场新闻", "YouTuber", "退出"]), 1)

    def test_arrow_down_then_enter_on_linux_pty(self):
        """Drive an actual pseudo-terminal, not a mock of the menu logic."""
        master, slave = pty.openpty()
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8", buffering=1) as terminal_in, \
                 os.fdopen(os.dup(slave), "w", encoding="utf-8", buffering=1) as terminal_out:
                chosen = []
                def worker():
                    with patch("cryptovideoresearch.interactive.sys.stdin", terminal_in), \
                         patch("cryptovideoresearch.interactive.sys.stdout", terminal_out):
                        chosen.append(choose("B", ["新闻", "YouTuber", "退出"]))
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                # Wait for the menu to enter cbreak mode and render before
                # sending keys; otherwise the PTY's canonical mode may buffer.
                self.assertTrue(select.select([master], [], [], 2)[0])
                os.read(master, 8192)
                os.write(master, b"\x1b[B")
                self.assertTrue(select.select([master], [], [], 2)[0])
                os.read(master, 8192)  # updated highlighted menu after arrow
                os.write(master, b"\r")
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive(), "Arrow selection did not finish")
                self.assertEqual(chosen, [1])
        finally:
            os.close(master)
            os.close(slave)

    def test_settings_and_channels_are_persistent_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "b_menu.json"
            cfg = load_settings(path)
            self.assertEqual(cfg["count"], 2)
            cfg["count"] = 4
            save_settings(cfg, path)
            self.assertEqual(load_settings(path)["count"], 4)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch("cryptovideoresearch.interactive.settings_path", return_value=path):
                remember_channel(Channel("Creator", normalize_channel("@creator123")), cfg)
                remember_channel(Channel("Creator", normalize_channel("@creator123")), cfg)
            new = load_settings(path)
            self.assertEqual(len(new["channels"]), 1)
            self.assertEqual(new["last_channel"], normalize_channel("@creator123"))

    def test_channel_urls_are_scoped_and_safe(self):
        url = normalize_channel("@crypto_creator")
        self.assertEqual(url, "https://www.youtube.com/@crypto_creator/videos")
        self.assertEqual(normalize_channel(url), url)
        channel_id = "UC" + "a" * 22
        self.assertEqual(
            normalize_channel("https://www.youtube.com/channel/" + channel_id),
            "https://www.youtube.com/channel/" + channel_id + "/videos",
        )
        for invalid in (
            "https://evil.test/@creator",
            "https://www.youtube.com/watch?v=ZWrgUWKOq_0",
            "https://www.youtube.com/@creator?next=evil",
            "http://youtube.com/@creator",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_channel(invalid)
        self.assertNotIn("/", channel_slug(url))
        self.assertNotEqual(channel_slug("@甲乙丙"), channel_slug("@丁戊己"))

    def test_creator_name_resolved_from_actual_channel_id(self):
        ident = "UC" + "A" * 22
        search = {"entries": [
            {"id": "ZWrgUWKOq_0", "channel": "Finance Creator",
             "channel_id": ident},
            {"id": "abc123DEF_0", "channel": "Finance Creator",
             "channel_id": ident},
        ]}
        with patch("cryptovideoresearch.youtube_news.find_videos", return_value=search):
            channels = find_channels_by_name("Finance Creator")
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].name, "Finance Creator")
        self.assertIn(ident, channels[0].url)

    def test_selected_channel_reports_only_channel_uploads(self):
        listing = {"entries": [
            {"id": "ZWrgUWKOq_0", "title": "本频道技术观点", "channel": "Selected Creator",
             "duration": 320},
            {"id": "abc123DEF_0", "title": "本频道市场新闻", "channel": "Selected Creator",
             "duration": 400},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            with patch("cryptovideoresearch.channels.list_channel_uploads", return_value=listing) as fetch:
                code = news_main([
                    "--channel", "@creator123", "--output", directory,
                    "--verify-top", "0", "--analyze-top", "0",
                    "--max-results", "10",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(
                fetch.call_args.args[0], normalize_channel("@creator123"),
            )
            data = json.loads((Path(directory) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual([v["id"] for v in data["videos"]],
                             ["ZWrgUWKOq_0", "abc123DEF_0"])

    def test_creator_prefers_captioned_uploads_to_uncaptioned_top_items(self):
        from cryptovideoresearch.pipeline import PipelineError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def video(vid, status):
                return Video(
                    id=vid, title="视频标题", channel="Creator",
                    url=f"https://www.youtube.com/watch?v={vid}", topic="YouTuber 频道",
                    published_at_utc=None, duration_seconds=300, views=None,
                    relevance_score=0, time_status="unknown", caption_status=status,
                )
            videos = [
                video("ZWrgUWKOq_0", "none"),
                video("abc123DEF_0", "unknown"),
                video("abcdefghijk", "available"),
            ]
            transcript = root / "temp.vtt"
            transcript.write_text("WEBVTT\\nplaceholder", encoding="utf-8")
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       return_value=(transcript, "uploaded")) as extract, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript",
                       return_value="新闻相关性：无具体事件\\n纯技术解读") as model, \
                 patch("cryptovideoresearch.youtube_news.write_report",
                       return_value=root / "report.md"):
                result = analyze_selected(
                    videos, root, 1, "none", False, "", [], accept_no_news=True,
                )
            self.assertEqual(result[0]["video_id"], "abcdefghijk")
            self.assertEqual(result[0]["status"], "analyzed-no-news")
            extract.assert_called_once()
            model.assert_called_once()

    def test_creator_probes_subtitles_even_if_metadata_reports_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v = Video(
                id="ZWrgUWKOq_0", title="财经分析", channel="Creator",
                url="https://www.youtube.com/watch?v=ZWrgUWKOq_0",
                topic="YouTuber 频道", published_at_utc=None, duration_seconds=900,
                views=None, relevance_score=0, time_status="unknown", caption_status="none",
            )
            transcript = root / "valid.vtt"
            transcript.write_text("WEBVTT\\nplaceholder", encoding="utf-8")
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       return_value=(transcript, "uploaded")) as extractor, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript",
                       return_value="博主观点") as model, \
                 patch("cryptovideoresearch.youtube_news.write_report",
                       return_value=root / "analysis.md"):
                result = analyze_selected(
                    [v], root, 1, "none", False, "", [], accept_no_news=True,
                )
            self.assertEqual(result[0]["status"], "analyzed")
            extractor.assert_called_once()
            model.assert_called_once()

    def test_bot_challenge_during_metadata_aborts_before_captions_or_ai(self):
        from cryptovideoresearch.pipeline import YouTubeAccessError
        listing = {"entries": [
            {"id": "ZWrgUWKOq_0", "title": "美股晨报", "channel": "Chosen",
             "duration": 300},
            {"id": "abc123DEF_0", "title": "市场讨论", "channel": "Chosen",
             "duration": 400},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            with patch("cryptovideoresearch.channels.list_channel_uploads",
                       return_value=listing), \
                 patch("cryptovideoresearch.youtube_news.fetch_video_metadata",
                       side_effect=YouTubeAccessError("Sign in to confirm you're not a bot")) as metadata, \
                 patch("cryptovideoresearch.youtube_news.extract_captions") as extract, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript") as model:
                code = news_main([
                    "--channel", "@creator123", "--output", directory,
                    "--verify-top", "10", "--analyze-top", "1",
                ])
            self.assertEqual(code, 1)
            metadata.assert_called_once()
            extract.assert_not_called()
            model.assert_not_called()
            report = json.loads((Path(directory) / "latest.json").read_text(encoding="utf-8"))
            self.assertTrue(any("YouTube authentication challenge:" in err
                                for err in report["errors"]))
            self.assertEqual(report["analyses"], [])

    def test_bot_challenge_during_captions_stops_other_video_attempts(self):
        from cryptovideoresearch.pipeline import YouTubeAccessError
        from cryptovideoresearch.youtube_news import Video
        items = [
            Video(
                id=vid, title="财经节目", channel="Creator",
                url=f"https://www.youtube.com/watch?v={vid}", topic="YouTuber 频道",
                published_at_utc=None, duration_seconds=300, views=None,
                relevance_score=0, time_status="unknown",
            )
            for vid in ("ZWrgUWKOq_0", "abc123DEF_0")
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       side_effect=YouTubeAccessError("Sign in to confirm you're not a bot")) as extract:
                errs = []
                result = analyze_selected(
                    items, Path(directory), 2, "none", False, "", errs,
                    accept_no_news=True,
                )
            self.assertEqual([r["status"] for r in result], ["access-blocked"])
            extract.assert_called_once()
            self.assertEqual(len(errs), 1)
            self.assertIn("authentication challenge", errs[0])

    def test_backward_compatibility_run_accepts_channel_flag(self):
        args = build_parser().parse_args(["run", "--channel", "@creator123", "--count", "1"])
        self.assertEqual(args.channel, "@creator123")
        self.assertEqual(args.count, 1)


if __name__ == "__main__":
    unittest.main()
