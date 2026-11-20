# -*- coding: utf-8 -*-
"""Kiểm thử helper của tools/dump_ws_frames.py (không cần Chrome).

Khoá lại ba việc quan trọng trước khi dump dữ liệu thật:

    - token/session trong URL và payload luôn bị che
    - khung JSON được nhận đúng, khung text/binary vẫn ghi được
    - chữ ký message gom nhóm đúng để đọc summary nhanh
"""

import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dump_ws_frames",
                                              ROOT / "tools" / "dump_ws_frames.py")
DUMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DUMP)


class RedactionTests(unittest.TestCase):
    def test_url_token_is_masked_but_path_is_kept(self):
        url = ("wss://w-plms88uqmz.petalive.live/ws?token=abc123&table=6af8"
               "&access_token=xyz&sig=deadbeef")
        redacted = DUMP.redact_url(url)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("xyz", redacted)
        self.assertNotIn("deadbeef", redacted)
        self.assertIn("table=6af8", redacted)
        self.assertIn("/ws", redacted)

    def test_payload_token_is_masked_recursively(self):
        payload = {"type": "auth", "token": "abc", "data": {"jwt": "xyz", "hand": "B"}}
        redacted = DUMP.redact_payload(payload)
        self.assertEqual(redacted["token"], "***")
        self.assertEqual(redacted["data"]["jwt"], "***")
        self.assertEqual(redacted["data"]["hand"], "B")

    def test_userinfo_is_stripped(self):
        self.assertNotIn("user:pass", DUMP.redact_url("wss://user:pass@host/ws"))


class FrameWriterTests(unittest.TestCase):
    def build(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        writer = DUMP.Writer(folder / "f.jsonl", folder / "f.hits.jsonl")
        return writer, folder

    def test_json_and_text_frames_are_recorded(self):
        writer, folder = self.build()
        writer.frame("t1", "recv", "wss://h/ws", 1,
                     json.dumps({"type": "result", "winner": "B", "token": "k"}), 60000)
        writer.frame("t1", "recv", "wss://h/ws", 1, "not-json", 60000)
        writer.frame("t1", "sent", "wss://h/ws", 2, "bin", 60000)
        writer.close()
        rows = [json.loads(line) for line in
                (folder / "f.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["json"]["winner"], "B")
        self.assertEqual(rows[0]["json"]["token"], "***")
        self.assertEqual(rows[1]["data"], "not-json")
        self.assertIn("b64", rows[2])
        self.assertEqual((writer.recv, writer.sent), (2, 1))

    def test_interesting_frames_are_copied_to_hits(self):
        writer, folder = self.build()
        writer.frame("t1", "recv", "wss://h/ws", 1,
                     json.dumps({"type": "cards", "player": ["S1"], "banker": ["H10"]}), 60000)
        writer.close()
        hits = (folder / "f.hits.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(hits), 1)
        self.assertIn("cards", hits[0])


class HelperTests(unittest.TestCase):
    def test_signature_groups_by_type_and_keys(self):
        sig = DUMP.signature({"type": "history", "total": 1, "tableId": "t"})
        self.assertTrue(sig.startswith("history|"))
        self.assertIn("tableId", sig)
        self.assertEqual(DUMP.signature("plain text"), "text")

    def test_truncate_marks_the_cut(self):
        text, truncated = DUMP.truncate_text("x" * 100, 10)
        self.assertTrue(truncated)
        self.assertIn("truncated", text)

    def test_keyword_detection(self):
        self.assertIn("card", DUMP.has_interesting_keyword('{"cards": []}'))
        self.assertEqual(DUMP.has_interesting_keyword('{"hello": 1}'), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
