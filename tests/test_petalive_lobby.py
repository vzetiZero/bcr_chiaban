# -*- coding: utf-8 -*-
"""Nhận diện và quét sảnh Petalive (/live-games/lobby/bcr) — không cần Chrome thật."""

import time
import unittest
from unittest.mock import patch

from aibcr.adapters import browser as BR
from aibcr.adapters import lobby_stream as LS

LOBBY = "https://w-plms88uqmz.petalive.live/live-games/lobby/bcr"
TABLE = "https://w-plms88uqmz.petalive.live/live-games/bcr/6af813456826dea5aea8e27b"
EVO = "https://tmrw17k36as.evo-games.com/frontend/evo/r3/#category=all_games&game=baccarat"


class PetaliveUrlTests(unittest.TestCase):
    def test_lobby_url_is_recognised(self):
        self.assertTrue(BR.is_lobby_url(LOBBY))
        self.assertTrue(BR.is_lobby_url(EVO))
        self.assertTrue(BR.is_lobby_url(LOBBY + "/"))

    def test_table_url_is_not_a_lobby(self):
        self.assertFalse(BR.is_lobby_url(TABLE))
        self.assertTrue(BR.is_petalive_table_url(TABLE))
        self.assertFalse(BR.is_petalive_table_url(LOBBY))
        self.assertFalse(BR.is_petalive_table_url(EVO))

    def test_table_url_rejects_bad_ids_and_userinfo(self):
        self.assertFalse(BR.is_petalive_table_url(
            "https://w-plms88uqmz.petalive.live/live-games/bcr/../entry"))
        self.assertFalse(BR.is_petalive_table_url(
            "https://user@w-plms88uqmz.petalive.live/live-games/bcr/abc123"))

    def test_cdp_page_prefers_petalive_table_over_portal(self):
        session = BR.BrowserSession()
        pages = [
            {"url": "https://www.neo179.com/gamelobby/live"},
            {"url": TABLE},
        ]
        with patch.object(BR.BrowserSession, "_cdp_pages", return_value=pages):
            self.assertEqual(session._cdp_page()["url"], TABLE)

    def test_back_to_lobby_url_drops_table_path(self):
        self.assertEqual(LS.lobby_list_url(TABLE), LOBBY)
        self.assertEqual(LS.lobby_list_url(EVO).split("#")[0], EVO.split("#")[0])


class LiveReaderTabTests(unittest.TestCase):
    def test_reader_skips_lobby_and_prefers_table_tab(self):
        from aibcr.live import reader as LR
        pages = [
            {"id": "lobby", "type": "page", "url": LOBBY},
            {"id": "other", "type": "page", "url": "https://example.com/live-games/x"},
            {"id": "table", "type": "page", "url": TABLE},
        ]
        with patch.object(LR, "list_pages", return_value=pages):
            self.assertEqual(LR.find_table_page()["id"], "table")

    def test_reader_returns_none_when_only_lobby_is_open(self):
        from aibcr.live import reader as LR
        with patch.object(LR, "list_pages", return_value=[
                {"id": "lobby", "type": "page", "url": LOBBY}]):
            self.assertIsNone(LR.find_table_page())


class FakeStream(LS.LobbyStream):
    """Chỉ thay phần nói chuyện với CDP; giữ nguyên logic gom ô bàn."""

    def __init__(self, tiles, scroll=None):
        super().__init__(human_mouse=False)
        self.tiles = tiles
        self.scroll = scroll or {"top": 0, "max": 1000, "client": 500}
        self.calls = []

    def _try_value(self, ws, expression, context_id):
        if "wui-live-games-layout__body-container" in expression:
            return {"x": 100, "y": 100, "width": 400, "height": 300}
        return None

    def _evaluate(self, ws, expression, context_id):
        self.calls.append(expression)
        return {"result": {"value": {"tiles": self.tiles, "scroll": self.scroll}}}

    def _wheel_scroll_to(self, ws, context_id, target_top, box, petalive=False):
        self.calls.append(("scroll", target_top, petalive))


class PetaliveSweepTests(unittest.TestCase):
    def test_reads_letters_from_room_tiles(self):
        tiles = [
            {"id": "roomA", "title": "Baccarat V1", "letters": "PBTPBB",
             "read_error": "", "game_type": "baccarat"},
            {"id": "roomB", "title": "Baccarat V2", "letters": "",
             "read_error": "Chưa đọc được cầu trong ô bàn.", "game_type": "baccarat"},
            {"id": "", "title": "ignored", "letters": "P"},
        ]
        stream = FakeStream(tiles)
        # Không patch time.monotonic bằng list cố định: module ``time`` là toàn cục nên
        # patch này rò rỉ sang test khác và làm chúng ném StopIteration.
        with patch("aibcr.adapters.lobby_stream.time.monotonic",
                   side_effect=lambda: 0.0 if len(stream.calls) < 2 else 100.0):
            rows = stream._sweep_petalive(object(), 1, {"scroll": {"top": 0}}, 10, False)
        self.assertEqual(len(rows), 2)
        by_id = {row["table_id"]: row for row in rows}
        self.assertEqual(by_id["roomA"]["letters"], "PBTPBB")
        self.assertEqual(by_id["roomA"]["source"], "petalive-board")
        self.assertEqual(by_id["roomA"]["label"], "Baccarat V1")
        self.assertTrue(by_id["roomA"]["road_match"])
        self.assertEqual(by_id["roomB"]["read_error"], "Chưa đọc được cầu trong ô bàn.")
        self.assertIn("2 bàn Petalive", stream.note)

    def test_scroll_uses_petalive_container(self):
        stream = FakeStream([{"id": "roomA", "title": "V1", "letters": "PPB",
                              "read_error": ""}])
        stream.scroll = {"top": 0, "max": 0, "client": 500}
        with patch("aibcr.adapters.lobby_stream.time.monotonic",
                   side_effect=lambda: 0.0 if len(stream.calls) < 2 else 100.0):
            stream._sweep_petalive(object(), 1, {"scroll": {"top": 0}}, 10, False)
        self.assertTrue(any(isinstance(call, tuple) and call[0] == "scroll" and call[2]
                            for call in stream.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
