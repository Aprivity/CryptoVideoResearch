"""Offline tests: never contact YouTube, DeepSeek, or a browser."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptovideoresearch.config import load_key, save_key, make_model_env
from cryptovideoresearch.pipeline import (
    PipelineError, analyze_transcript, extract_captions, valid_vtt,
    write_report, youtube_video_id,
)

TEST_VTT = (
    "WEBVTT\n\n"
    "00:00:00.733 --> 00:00:04.200\n"
    "比特币价格出现了明显波动，研究者认为短期可能震荡，但没有给出交易策略。\n\n"
    "00:00:04.500 --> 00:00:12.000\n"
    "研究者补充说明均线正在上移，视频没有展示交易入场、止盈、止损或资金管理规则。\n"
    "此样本只用于软件测试，不包含真实投资建议，也没有进行独立数据核验。\n"
)


class PipelineTests(unittest.TestCase):
    def test_youtube_id_allowlist(self):
        self.assertEqual(youtube_video_id("https://youtu.be/ZWrgUWKOq_0"), "ZWrgUWKOq_0")
        self.assertEqual(youtube_video_id("https://www.youtube.com/watch?v=ZWrgUWKOq_0&t=3"), "ZWrgUWKOq_0")
        self.assertEqual(youtube_video_id("https://www.youtube.com/shorts/ZWrgUWKOq_0"), "ZWrgUWKOq_0")
        for bad in ("http://youtube.com/watch?v=ZWrgUWKOq_0",
                    "https://evil.test/watch?v=ZWrgUWKOq_0",
                    "https://youtube.com/watch?v=../etc/passwd"):
            with self.subTest(bad=bad), self.assertRaises(PipelineError):
                youtube_video_id(bad)

    def test_vtt_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.vtt"
            path.write_text(TEST_VTT, encoding="utf-8")
            self.assertTrue(valid_vtt(path))
            path.write_text("Enjoy videos on YouTube!", encoding="utf-8")
            self.assertFalse(valid_vtt(path))

    def test_caption_fallback_and_cookies_are_argument_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            def fake_run(command, **kwargs):
                commands.append(command)
                if "--write-auto-subs" in command:
                    target = Path(directory) / "ZWrgUWKOq_0" / "ZWrgUWKOq_0.zh-Hans.vtt"
                    target.write_text(TEST_VTT, encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("cryptovideoresearch.pipeline.find_ytdlp", return_value="/fake/yt-dlp"), \
                 patch("cryptovideoresearch.pipeline.checked_run", side_effect=fake_run):
                path, source = extract_captions(
                    "https://youtu.be/ZWrgUWKOq_0", Path(directory), cookies="chrome")
            self.assertTrue(path.is_file())
            self.assertEqual(source, "automatic")
            self.assertEqual(len(commands), 2)
            self.assertIn("--cookies-from-browser", commands[0])
            self.assertIn("chrome", commands[0])

    def test_regional_chinese_caption_tags_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(command, **_kwargs):
                self.assertIn("zh.*,en.*", command)
                target = Path(directory) / "ZWrgUWKOq_0" / "ZWrgUWKOq_0.zh-TW.vtt"
                target.write_text(TEST_VTT, encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("cryptovideoresearch.pipeline.find_ytdlp", return_value="/fake/yt-dlp"), \
                 patch("cryptovideoresearch.pipeline.checked_run", side_effect=fake_run):
                path, source = extract_captions("https://youtu.be/ZWrgUWKOq_0", Path(directory))
            self.assertEqual(source, "uploaded")
            self.assertTrue(path.name.endswith(".zh-TW.vtt"))

    def test_analysis_uses_deepseek_and_no_claude(self):
        with tempfile.TemporaryDirectory() as directory:
            vtt = Path(directory) / "test.vtt"
            prompt = Path(directory) / "prompt.md"
            vtt.write_text(TEST_VTT, encoding="utf-8")
            prompt.write_text("Summarize the captions", encoding="utf-8")
            fake = subprocess.CompletedProcess(["summarize"], 0, "## 结论\n字幕提及市场震荡但没有策略参数，资料未经核实，尚需结合其他公开来源确认客观数据。\n", "")
            with patch("cryptovideoresearch.pipeline.shutil.which", return_value="/fake/summarize"), \
                 patch("cryptovideoresearch.pipeline.make_model_env", return_value={"OPENAI_API_KEY": "dummy"}), \
                 patch("cryptovideoresearch.pipeline.checked_run", return_value=fake) as runner:
                output = analyze_transcript(vtt, prompt=prompt)
            self.assertIn("未经核实", output)
            args, kwargs = runner.call_args
            self.assertIn("openai/deepseek-flash", args[0])
            self.assertEqual(kwargs["env"]["OPENAI_API_KEY"], "dummy")
            self.assertNotIn("--cli", args[0])

    def test_refuse_empty_model_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.vtt"
            prompt = Path(directory) / "prompt.md"
            path.write_text(TEST_VTT, encoding="utf-8")
            prompt.write_text("Prompt", encoding="utf-8")
            fake = subprocess.CompletedProcess([], 0, "", "")
            with patch("cryptovideoresearch.pipeline.shutil.which", return_value="/fake/summarize"), \
                 patch("cryptovideoresearch.pipeline.make_model_env", return_value={}), \
                 patch("cryptovideoresearch.pipeline.checked_run", return_value=fake):
                with self.assertRaises(PipelineError):
                    analyze_transcript(path, prompt=prompt)

    def test_report_metadata_is_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vtt = root / "captions.vtt"
            vtt.write_text(TEST_VTT, encoding="utf-8")
            path = write_report(
                output_root=root, video_id="ZWrgUWKOq_0",
                source_url="https://youtu.be/ZWrgUWKOq_0", transcript=vtt,
                subtitle_source="uploaded", summary="## Summary\nNot verified\n",
                model="deepseek-flash",
            )
            obj = json.loads((path.parent / "report.json").read_text())
            self.assertEqual(obj["verification_status"], "unverified")
            self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(obj))

    def test_local_secret_permissions_and_env(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": directory, "DEEPSEEK_API_KEY": ""}, clear=True):
            path = save_key("secret-test-key")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(load_key(), "secret-test-key")
            env = make_model_env()
            self.assertEqual(env["OPENAI_BASE_URL"], "https://api.deepseek.com/v1")
            self.assertEqual(env["OPENAI_API_KEY"], "secret-test-key")


if __name__ == "__main__":
    unittest.main()
