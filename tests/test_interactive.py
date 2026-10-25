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
from cryptovideoresearch.youtube_news import main as news_main


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
                os.write(master, b"\\x1b[B\\r")
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

    def test_backward_compatibility_run_accepts_channel_flag(self):
        args = build_parser().parse_args(["run", "--channel", "@creator123", "--count", "1"])
        self.assertEqual(args.channel, "@creator123")
        self.assertEqual(args.count, 1)


if __name__ == "__main__":
    unittest.main()
