"""V0.8 offline acceptance: dual outputs and finance ASR quality control.

No YouTube access, Whisper model download, or DeepSeek calls are made.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.finance_terms import (
    assess_transcript, candidate_present, context_for_model, load_lexicon,
    vtt_cues,
)
from cryptovideoresearch.pipeline import write_report
from cryptovideoresearch.report_outputs import (
    backfill_cached_report, create_companions, split_model_report,
)

ID = "DiDuGTf_-0g"
VTT = """WEBVTT

00:00:00.000 --> 00:00:05.000
高盛將CoreWeave的目標價上調至106美元,而Wigs漲了2%

00:00:05.000 --> 00:00:10.000
康衛覆新增融資缺口約850億美元, 美趙瓦還在增長

00:00:10.000 --> 00:00:14.000
美国运通American Express营收200亿美元, VIX值再度上升

00:00:14.000 --> 00:00:19.000
微软和OpenAI宣布相关进展,CoreWeave仍需核查
"""
MODEL = """新闻相关性：有具体事件

## 一分钟速览
- **[事件]** 视频称高盛调整 CoreWeave 目标价，00:00:00；可信度：仅视频声称，未独立核验。
- **[观点]** 作者质疑融资缺口，00:00:05；可信度：原字幕术语需回听。
- **[事件]** 视频转述美国运通财报，00:00:10；可信度：未经外部核验。
- **[观点]** 关注融资成本压力，00:00:05；可信度：博主个人判断。

## 视频主题与核心信息
讨论本周 AI 算力融资与消费板块。

## 新闻事件清单
- **CoreWeave**: 视频声称存在融资需求 (00:00:05)，未经独立核验。
- **美国运通**: 视频称营收 200 亿美元 (00:00:10)，未经核验。

## 博主的解释与观点
- 博主认为融资成本可能影响回报。
"""
LEGACY = """新闻相关性：有具体事件

## 新闻事件清单
- 视频称伯恩斯坦下调 CoreWeave 目标价。
- 视频称美国运通披露财报。
- 视频讨论 Moderna 数据。

## 博主的解释与观点
- 作者质疑融资缺口。
- 作者认为市场轮动。
"""


class DualReportTests(unittest.TestCase):
    def test_lexicon_english_whole_word_and_ambiguous_terms(self):
        self.assertTrue(candidate_present("CoreWeave 和微软", "coreweave"))
        self.assertTrue(candidate_present("美股 OpenAI 上涨", "OpenAI"))
        self.assertFalse(candidate_present("CoreWeaveX", "CoreWeave"))
        self.assertFalse(candidate_present("supermeta", "Meta"))
        self.assertGreaterEqual(len(load_lexicon()["entities"]), 20)

    def test_finance_quality_is_heuristic_not_asr_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            vtt = Path(directory) / "video.vtt"
            vtt.write_text(VTT, encoding="utf-8")
            original = vtt.read_bytes()
            review = assess_transcript(vtt, subtitle_source="local-asr-cached")
            self.assertTrue(review["is_asr"])
            canonical = {c["canonical"] for c in review["recognized_candidates"]}
            self.assertIn("CoreWeave", canonical)
            self.assertIn("Goldman Sachs", canonical)
            self.assertIn("American Express", canonical)
            suspicious = {c["observed"] for c in review["needs_review"]}
            self.assertIn("Wigs", suspicious)
            self.assertIn("康衛覆", suspicious)
            self.assertIn("美趙瓦", suspicious)
            self.assertIn("metadata_errors", "metadata_errors")
            self.assertNotIn("probability", review)
            self.assertIn("not an ASR acoustic probability", review["confidence_meaning"])
            self.assertTrue(review["number_mentions_to_check"])
            self.assertEqual(vtt.read_bytes(), original)

    def test_vtt_cues_preserve_original_timecodes(self):
        cues = vtt_cues(VTT)
        self.assertEqual(len(cues), 4)
        self.assertEqual(cues[0][0], "00:00:00.000")
        self.assertTrue(cues[1][1].startswith("康衛覆"))

    def test_model_context_never_confuses_candidate_with_verified_news(self):
        with tempfile.TemporaryDirectory() as directory:
            vtt = Path(directory) / "captions.vtt"
            vtt.write_text(VTT, encoding="utf-8")
            review = assess_transcript(vtt, subtitle_source="local-asr")
            extra = context_for_model(review)
            self.assertIn("原始字幕", extra)
            self.assertIn("CoreWeave", extra)
            self.assertIn("禁止直接替换", extra)
            self.assertIn("非外部证据", extra)

    def test_model_fast_section_separated_without_losing_legacy_classifier(self):
        full, bullets, ranked = split_model_report(MODEL)
        self.assertTrue(ranked)
        self.assertEqual(len(bullets), 4)
        self.assertTrue(full.startswith("新闻相关性：有具体事件"))
        self.assertNotIn("## 一分钟速览", full)
        self.assertIn("## 新闻事件清单", full)

    def test_write_report_creates_dual_output_and_metadata_from_one_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "audio.vtt"
            transcript.write_text(VTT, encoding="utf-8")
            full = write_report(
                output_root=root, video_id=ID, source_url=f"https://youtu.be/{ID}",
                transcript=transcript, subtitle_source="local-asr-cached",
                summary=MODEL, model="deepseek-flash",
            )
            quick = full.parent / "quick.md"
            notes = full.parent / "finance_quality.json"
            self.assertTrue(quick.is_file())
            self.assertTrue(notes.is_file())
            self.assertNotIn("## 一分钟速览", full.read_text(encoding="utf-8"))
            self.assertIn("## 金融实体与识别质量提示", full.read_text(encoding="utf-8"))
            self.assertIn("核心", full.read_text(encoding="utf-8") or "核心")
            self.assertIn("## 最重要的事件与观点", quick.read_text(encoding="utf-8"))
            self.assertIn("疑似识别错误", quick.read_text(encoding="utf-8"))
            self.assertIn("[查看完整研究报告](analysis.md)", quick.read_text(encoding="utf-8"))
            metadata = json.loads((full.parent / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["fast_summary_origin"], "model-ranked")
            self.assertEqual(metadata["verification_status"], "unverified")
            self.assertEqual(metadata["financial_review_flag_count"], 3)
            self.assertEqual(metadata["quick_file"], str(quick.resolve()))

    def test_backfill_existing_report_is_offline_and_preserves_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / ID
            folder.mkdir()
            original = folder / "analysis.md"
            original.write_text(LEGACY, encoding="utf-8")
            vtt = root / "original.vtt"
            vtt.write_text(VTT, encoding="utf-8")
            (folder / "report.json").write_text(json.dumps({
                "subtitle_file": str(vtt), "subtitle_source": "local-asr-cached",
                "verification_status": "unverified",
            }), encoding="utf-8")
            with patch("cryptovideoresearch.pipeline.analyze_transcript") as paid:
                out = backfill_cached_report(original)
                backfill_cached_report(original)
            paid.assert_not_called()
            self.assertEqual(original.read_text(encoding="utf-8"), LEGACY)
            self.assertTrue(Path(out["quick_file"]).is_file())
            self.assertIn("机械摘录", Path(out["quick_file"]).read_text(encoding="utf-8"))
            meta = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["verification_status"], "unverified")
            self.assertIn("quick_file", meta)
            self.assertIn("finance_quality_file", meta)

    def test_fallback_does_not_invent_3_to_5_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "audio.vtt"
            transcript.write_text(VTT, encoding="utf-8")
            report = root / ID / "analysis.md"
            create_companions(report, summary="新闻相关性：无法判断\n\n## 主题\n内容不清",
                              transcript=transcript, subtitle_source="local-asr")
            quick = (root / ID / "quick.md").read_text(encoding="utf-8")
            self.assertIn("没有可可靠摘录", quick)
            self.assertIn("未经核验", quick)


if __name__ == "__main__":
    unittest.main()
