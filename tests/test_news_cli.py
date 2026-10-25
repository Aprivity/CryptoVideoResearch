"""CLI wiring tests for the one-command install branch. No network or API calls."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cryptovideoresearch.cli import build_parser


class NewsCliTests(unittest.TestCase):
    def test_news_command_is_available_without_key(self):
        args = build_parser().parse_args(["news", "--hours", "24"])
        self.assertEqual(args.action, "news")
        self.assertEqual(args.hours, 24)

    def test_news_command_uses_offline_fixture_and_de_duplicates(self):
        fixture = Path(__file__).parent / "fixtures" / "news_sample.xml"
        with tempfile.TemporaryDirectory() as folder:
            args = build_parser().parse_args([
                "news", "--fixture", str(fixture),
                "--output", folder, "--hours", "100000",
            ])
            self.assertEqual(args.handler(args), 0)
            first = json.loads((Path(folder) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(first["counts"]["new"], 2)
            self.assertEqual(args.handler(args), 0)
            second = json.loads((Path(folder) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(second["counts"]["new"], 0)
            self.assertEqual(len(second["items"]), 2)


if __name__ == "__main__":
    unittest.main()
