"""One-click B workflow: CLI dispatch and bounded API calls, all offline."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.cli import build_parser
from cryptovideoresearch.pipeline import PipelineError
from cryptovideoresearch.youtube_news import Video, analyze_selected


def video(video_id: str) -> Video:
    return Video(
        id=video_id,
        title="Bitcoin market report",
        channel="Example channel",
        url=f"https://www.youtube.com/watch?v={video_id}",
        topic="BTC 与加密市场", published_at_utc=None,
        duration_seconds=300, views=None,
        relevance_score=8, time_status="unknown",
    )


class RunTests(unittest.TestCase):
    def test_one_command_dispatches_search_plus_two_analyses(self):
        with tempfile.TemporaryDirectory() as folder:
            args = build_parser().parse_args(["run", "--output", folder])
            self.assertEqual(args.count, 2)
            with patch("cryptovideoresearch.cli.load_key", return_value="test-key"), \
                 patch("cryptovideoresearch.youtube_news.main", return_value=0) as dispatched:
                self.assertEqual(args.handler(args), 0)
                argv = dispatched.call_args.args[0]
                self.assertIn("--analyze-top", argv)
                self.assertEqual(argv[argv.index("--analyze-top") + 1], "2")
                self.assertIn("--allow-unknown-age", argv)

    def test_strict_dates_requires_verified_videos(self):
        with tempfile.TemporaryDirectory() as folder:
            args = build_parser().parse_args([
                "run", "--strict-dates", "--count", "3", "--output", folder,
            ])
            with patch("cryptovideoresearch.cli.load_key", return_value="test-key"), \
                 patch("cryptovideoresearch.youtube_news.main", return_value=0) as dispatched:
                self.assertEqual(args.handler(args), 0)
                argv = dispatched.call_args.args[0]
                self.assertNotIn("--allow-unknown-age", argv)
                self.assertEqual(argv[argv.index("--analyze-top") + 1], "3")

    def test_missing_key_fails_before_network(self):
        args = build_parser().parse_args(["run"])
        with patch("cryptovideoresearch.cli.load_key", side_effect=RuntimeError("Missing key")), \
             patch("cryptovideoresearch.youtube_news.main") as dispatched:
            with self.assertRaises(RuntimeError):
                args.handler(args)
            dispatched.assert_not_called()

    def test_one_missing_transcript_tries_next_video_without_extra_model_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            vids = [video(i) for i in ("ZWrgUWKOq_0", "abc123DEF_0", "abcdefghijk")]
            transcript = root / "sample.vtt"
            transcript.write_text("WEBVTT\nplaceholder", encoding="utf-8")
            calls = []
            def extract(url, *_a, **_kw):
                calls.append(url)
                if url.endswith("ZWrgUWKOq_0"):
                    raise PipelineError("No subtitles")
                return transcript, "uploaded"
            def write_report(**kwargs):
                result = root / "videos" / kwargs["video_id"] / "analysis.md"
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text("fake report", encoding="utf-8")
                return result
            errs = []
            with patch("cryptovideoresearch.youtube_news.extract_captions", side_effect=extract), \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript", return_value="fake summary") as model, \
                 patch("cryptovideoresearch.youtube_news.write_report", side_effect=write_report):
                results = analyze_selected(vids, root, 2, "none", False, "", errs)
            self.assertEqual([x["status"] for x in results], ["failed", "analyzed", "analyzed"])
            self.assertEqual(model.call_count, 2)
            self.assertEqual(len(errs), 1)
            self.assertEqual(len(calls), 3)

    def test_no_caption_metadata_skips_unusable_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = video("ZWrgUWKOq_0"), video("abc123DEF_0")
            a.caption_status = "none"
            transcript = Path(folder) / "valid.vtt"
            transcript.write_text("WEBVTT\\nplaceholder", encoding="utf-8")
            with patch("cryptovideoresearch.youtube_news.extract_captions",
                       return_value=(transcript, "automatic")) as extractor, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript",
                       return_value="mock summary") as model, \
                 patch("cryptovideoresearch.youtube_news.write_report",
                       return_value=Path(folder) / "mock-analysis.md"):
                errors = []
                result = analyze_selected([a, b], Path(folder), 1, "none", False, "", errors)
            self.assertEqual(result[0]["status"], "no-captions")
            self.assertEqual(result[1]["status"], "analyzed")
            self.assertEqual(extractor.call_count, 1)
            self.assertEqual(model.call_count, 1)

    def test_scans_past_three_no_subtitle_videos_for_one_report(self):
        with tempfile.TemporaryDirectory() as folder:
            videos = [video(s) for s in ("ZWrgUWKOq_0", "abc123DEF_0", "abcdefghijk", "0123456789A")]
            transcript = Path(folder) / "valid.vtt"
            transcript.write_text("WEBVTT\\nplaceholder", encoding="utf-8")
            def extraction(url, *_a, **_kw):
                if not url.endswith("0123456789A"):
                    raise PipelineError("Captions not provided")
                return transcript, "automatic"
            with patch("cryptovideoresearch.youtube_news.extract_captions", side_effect=extraction) as extractor, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript", return_value="mock summary") as model, \
                 patch("cryptovideoresearch.youtube_news.write_report",
                       return_value=Path(folder) / "mock-analysis.md"):
                result = analyze_selected(videos, Path(folder), 1, "none", False, "", [])
            self.assertEqual([entry["status"] for entry in result],
                             ["failed", "failed", "failed", "analyzed"])
            self.assertEqual(extractor.call_count, 4)
            self.assertEqual(model.call_count, 1)

    def test_cached_report_skips_analyzing_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "videos" / "ZWrgUWKOq_0" / "analysis.md"
            target.parent.mkdir(parents=True)
            target.write_text("already complete", encoding="utf-8")
            with patch("cryptovideoresearch.youtube_news.extract_captions") as extract, \
                 patch("cryptovideoresearch.youtube_news.analyze_transcript") as model:
                results = analyze_selected([video("ZWrgUWKOq_0")], root, 1, "none", False, "", [])
            self.assertEqual(results[0]["status"], "cached")
            extract.assert_not_called()
            model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
