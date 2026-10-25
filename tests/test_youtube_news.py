"""Offline tests for YouTube-first news discovery. No remote APIs, subscriptions or trades."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.cli import build_parser
from cryptovideoresearch.youtube_news import (
    find_videos, main, merge_videos, parse_results,
)

FIXTURE = Path(__file__).parent / "fixtures/youtube_search.json"


class YouTubeNewsTests(unittest.TestCase):
    def test_parse_metadata_and_missing_publish_dates(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        found = parse_results(source, topic="BTC 与加密市场", query="BTC 新闻",
                              hours=72, now=now)
        self.assertEqual({v.id for v in found}, {"ZWrgUWKOq_0", "abc123DEF_0"})
        undecided = next(v for v in found if v.id == "ZWrgUWKOq_0")
        self.assertIsNone(undecided.published_at_utc)
        self.assertEqual(undecided.time_status, "unknown")
        self.assertTrue(undecided.url.startswith("https://www.youtube.com/watch?v="))

    def test_merging_id_preserves_one_video_and_all_queries(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        a = parse_results(raw, topic="BTC 与加密市场", query="BTC", hours=72, now=now)
        b = parse_results(raw, topic="BTC 与加密市场", query="crypto", hours=72, now=now)
        merged = merge_videos(a + b, 20)
        self.assertEqual(len(merged), 2)
        self.assertEqual(sorted(merged[0].matched_queries), ["BTC", "crypto"])

    def test_search_uses_current_ytdlp_prefix(self):
        fake = subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        with patch("cryptovideoresearch.youtube_news.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("cryptovideoresearch.youtube_news.checked_run", return_value=fake) as runner:
            data = find_videos("BTC news", 6, cookies="none")
            self.assertEqual(len(data["entries"]), 4)
            command = runner.call_args.args[0]
            self.assertIn("ytsearch6:BTC news", command)
            self.assertFalse(any("ytsearchdate" in word for word in command))

    def test_cli_offline_repeat_run_does_not_add_duplicates_or_need_key(self):
        with tempfile.TemporaryDirectory() as folder:
            args = build_parser().parse_args([
                "youtube-news", "--fixture", str(FIXTURE),
                "--output", folder, "--hours", "720", "--min-seconds", "90",
            ])
            self.assertEqual(args.handler(args), 0)
            first = json.loads((Path(folder) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(first["videos"]), 2)
            self.assertEqual(first["discovery_new"], 2)
            self.assertEqual(args.handler(args), 0)
            second = json.loads((Path(folder) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(second["discovery_new"], 0)
            self.assertEqual(second["source"], "youtube-search")
            self.assertEqual(second["analyses"], [])

    def test_corrupted_fixture_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "data"
            output.mkdir()
            (output / "latest.md").write_text("prior", encoding="utf-8")
            fixture = Path(folder) / "bad.json"
            fixture.write_text("{not json}", encoding="utf-8")
            self.assertEqual(main(["--output", str(output), "--fixture", str(fixture)]), 2)
            self.assertEqual((output / "latest.md").read_text(), "prior")


if __name__ == "__main__":
    unittest.main()
