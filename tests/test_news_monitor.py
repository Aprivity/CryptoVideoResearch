"""Offline tests, including two-run CLI de-duplication and malformed source handling."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cryptovideoresearch.news_monitor import (
    _utc, canonical_url, feed_url, main, parse_feed, recent_articles, save_articles,
)

TEST_XML = b'''<rss version="2.0"><channel>
<item><title>BTC update</title><link>https://example.org/news?id=1&amp;utm_source=feed</link>
<pubDate>Sat, 24 Oct 2026 20:00:00 GMT</pubDate><description>BTC rally &amp; context</description></item>
<item><title>Undated claim</title><link>https://example.org/undated</link></item>
</channel></rss>'''
SOURCE = {"name": "Test", "topic": "BTC", "type": "rss", "url": "https://example.org/feed.xml"}


class NewsMonitorTests(unittest.TestCase):
    def test_feed_url(self):
        self.assertIn("q=Bitcoin", feed_url({"type": "google_news", "query": "Bitcoin"}))
        self.assertEqual(feed_url(SOURCE), "https://example.org/feed.xml")

    def test_canonical_url_and_protection(self):
        self.assertEqual(canonical_url("https://Example.org/news?utm_source=x&a=1"), "https://example.org/news?a=1")
        for value in ("http://example.org", "file:///etc/passwd", "https://localhost/x"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                canonical_url(value)

    def test_rss_parse_no_invented_dates(self):
        items = parse_feed(TEST_XML, SOURCE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "BTC update")
        self.assertEqual(items[0].url, "https://example.org/news?id=1")
        self.assertEqual(_utc("invalid"), None)

    def test_de_dup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news.db"
            articles = parse_feed(TEST_XML, SOURCE)
            self.assertEqual(save_articles(path, articles), 1)
            self.assertEqual(save_articles(path, articles), 0)
            self.assertEqual(len(recent_articles(path, "2026-01-01T00:00:00+00:00")), 1)

    def test_one_shot_fixture_second_run_no_new(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "news"
            fixture = Path(directory) / "sample.xml"
            fixture.write_bytes(TEST_XML)
            args = ["--fixture", str(fixture), "--output", str(out), "--hours", "100000"]
            self.assertEqual(main(args), 0)
            first = json.loads((out / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(first["counts"]["new"], 1)
            self.assertEqual(main(args), 0)
            second = json.loads((out / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(second["counts"]["new"], 0)
            self.assertEqual(len(second["items"]), 1)
            self.assertIn("unverified", second["verification_status"])

    def test_all_invalid_feed_fails_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "news"
            out.mkdir()
            (out / "latest.md").write_text("prior", encoding="utf-8")
            fixture = Path(directory) / "bad.xml"
            fixture.write_text("not xml", encoding="utf-8")
            self.assertEqual(main(["--fixture", str(fixture), "--output", str(out)]), 1)
            self.assertEqual((out / "latest.md").read_text(encoding="utf-8"), "prior")


if __name__ == "__main__":
    unittest.main()
