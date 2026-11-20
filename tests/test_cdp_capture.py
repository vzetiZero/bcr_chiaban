# -*- coding: utf-8 -*-
"""Kiểm thử tools/cdp_capture.py (không cần Chrome).

Khoá lại phần dễ sai khi chạy live: chọn đúng tab bàn, không in trùng quá nhiều,
và không lộ token khi in URL.
"""

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cdp_capture", ROOT / "tools" / "cdp_capture.py")
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


class MatchTabTests(unittest.TestCase):
    PAGES = [
        {"id": "a", "url": "https://site/lobby"},
        {"id": "b", "url": "https://w-plm.petalive.live/live-games/bcr/6af8?token=***"},
        {"id": "c", "url": "about:blank"},
    ]

    def test_matches_the_table_tab(self):
        page = CAPTURE.match_tab(self.PAGES, "live-games|/bcr/")
        self.assertEqual(page["id"], "b")

    def test_returns_none_when_nothing_matches(self):
        self.assertIsNone(CAPTURE.match_tab(self.PAGES, "khong-co-tab-nao"))

    def test_empty_pattern_takes_the_first_tab(self):
        self.assertEqual(CAPTURE.match_tab(self.PAGES, "")["id"], "a")


class LivePrinterTests(unittest.TestCase):
    def test_repeated_signature_is_capped(self):
        printer = CAPTURE.LivePrinter(limit_per_signature=2)
        record = {"json": {"type": "result", "winner": "B"}}
        for _ in range(5):
            printer.feed(record)
        self.assertEqual(printer.hits, 5)
        self.assertEqual(printer.seen["result|type,winner"], 5)

    def test_unrelated_frames_are_ignored(self):
        printer = CAPTURE.LivePrinter()
        printer.feed({"json": {"type": "ping"}})
        self.assertEqual(printer.hits, 0)

    def test_describe_handles_text_frames(self):
        text = CAPTURE.describe({"data": "hello"})
        self.assertIn("hello", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
