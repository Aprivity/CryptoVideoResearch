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
    classify_report, find_videos, main, merge_videos, old_title_date,
    parse_results, verify_video_dates,
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

    def test_metadata_verification_removes_stale_video(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        selected = parse_results(raw, topic="BTC 与加密市场", query="news",
                                 hours=72, now=now)
        with patch("cryptovideoresearch.youtube_news.fetch_video_metadata",
                   return_value={"id": "ZWrgUWKOq_0", "upload_date": "20200101"}):
            validated = verify_video_dates(selected, count=1, cookies="none",
                                           hours=72, now=now, errors=[])
        self.assertNotIn("ZWrgUWKOq_0", {v.id for v in validated})

    def test_metadata_verification_preserves_recent_date(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        selected = parse_results(raw, topic="BTC 与加密市场", query="news",
                                 hours=72, now=now)
        with patch("cryptovideoresearch.youtube_news.fetch_video_metadata",
                   return_value={"id": "ZWrgUWKOq_0", "upload_date": "20261024"}):
            validated = verify_video_dates(selected, count=1, cookies="none",
                                           hours=72, now=now, errors=[])
        target = next(v for v in validated if v.id == "ZWrgUWKOq_0")
        self.assertEqual(target.published_at_utc, "2026-10-24")
        self.assertEqual(target.time_status, "date-only")

    def test_identical_titles_deduplicate_across_channel_ids(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        source = {"entries": [
            {"id": "ZWrgUWKOq_0", "title": "Bitcoin news analysis", "channel": "channel A"},
            {"id": "abc123DEF_0", "title": "Bitcoin News Analysis!!!", "channel": "channel B"},
        ]}
        items = parse_results(source, topic="BTC 与加密市场", query="news",
                              hours=72, now=now)
        self.assertEqual(len(merge_videos(items, 20)), 1)

    def test_event_news_ranks_above_generic_price_prediction(self):
        now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
        raw = {"entries": [
            {"id": "ZWrgUWKOq_0", "title": "Bitcoin Ethereum Price Prediction 2026 Next Move"},
            {"id": "abc123DEF_0", "title": "Bitcoin CPI inflation Fed policy news explained"},
        ]}
        found = parse_results(raw, topic="BTC 与加密市场", query="news", hours=168, now=now)
        # A pure price forecast can be filtered out entirely; it should never
        # outrank the specific macro-news candidate.
        ordered = merge_videos(found, 10)
        self.assertEqual(ordered[0].id, "abc123DEF_0")
        if len(ordered) == 2:
            self.assertGreater(ordered[0].relevance_score, ordered[1].relevance_score)

    def test_model_news_marker_and_legacy_fallback(self):
        self.assertEqual(
            classify_report("新闻相关性：无具体事件\\n## 视频主题与核心信息\\n技术分析"),
            "no-news",
        )
        self.assertEqual(
            classify_report("新闻相关性：有具体事件\\n## 新闻事件清单\\n视频提到了 CPI"),
            "reported-events",
        )
        self.assertEqual(
            classify_report("## 视频主题与核心信息\\n没有可靠的新闻事件内容。"),
            "no-news",
        )
        self.assertEqual(classify_report("## 核心观点\\n某些观点"), "unclassified")

    def test_old_dates_in_titles_are_filtered_without_inventing_upload_date(self):
        now = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
        cases = [
            ("【精華】CPI 20230731 美聯儲", "2023-07-31"),
            ("台積電 20230606 AI news", "2023-06-06"),
            ("科技回顧 20220810", "2022-08-10"),
            ("市場觀察 2026.7.25", "2026-07-25"),
            ("銀行危機｜20230314", "2023-03-14"),
            ("10月25日 加密新聞", None),
            ("2026.10.24 今日 CPI", None),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(old_title_date(title, now=now, hours=168), expected)

        data = {"entries": [
            {"id": "ZWrgUWKOq_0", "title": "美联储新闻 20230731", "duration": 500},
            {"id": "abc123DEF_0", "title": "CPI 通胀 最新财经解读", "duration": 500},
            {"id": "abcdefghijk", "title": "20230731 CPI 历史比较", "duration": 500,
             "upload_date": "20261024"},
        ]}
        found = parse_results(data, topic="美联储与宏观", query="news",
                              now=now, hours=168)
        self.assertEqual({v.id for v in found}, {"abc123DEF_0", "abcdefghijk"})
        recent = next(v for v in found if v.id == "abcdefghijk")
        self.assertEqual(recent.published_at_utc, "2026-10-24")

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
