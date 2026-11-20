# -*- coding: utf-8 -*-
"""Giải mã dữ liệu WM (M88): mã cửa thắng, id lá bài, lịch sử và ván vừa ngã.

Các mẫu dưới đây chép từ khung WebSocket thật của bàn 101_531/101_508; điểm số
trong ``dtCard`` đã được đối chiếu trực tiếp với ``playerScore``/``bankerScore``.
"""

import base64
import json
import unittest

from aibcr.adapters import wm


HISTORY_FRAME = {
    "protocol": 26,
    "data": {
        "gameID": 101,
        "groupID": 531,
        "groupType": 84,
        "historyArr": [49, 209, 34, 193, 33, 322, 338, 76],
        "historyData": {
            "resultObjArr": [
                {"gameNo": 114798135, "gameNoRound": 1, "result": 49,
                 "resultContent": "b:52,2,50;p:33,13,61"},
                {"gameNo": 114798135, "gameNoRound": 2, "result": 209,
                 "resultContent": "b:25,43,;p:27,7,"},
                {"gameNo": 114798135, "gameNoRound": 3, "result": 34,
                 "resultContent": "b:73,24,6;p:11,21,6"},
                {"gameNo": 114798135, "gameNoRound": 4, "result": 193,
                 "resultContent": "b:28,21,;p:32,27,"},
                {"gameNo": 114798135, "gameNoRound": 5, "result": 33,
                 "resultContent": "b:45,31,;p:1,63,28"},
                {"gameNo": 114798135, "gameNoRound": 6, "result": 322,
                 "resultContent": "b:11,64,;p:43,26,"},
                {"gameNo": 114798135, "gameNoRound": 7, "result": 338,
                 "resultContent": "b:45,46,;p:69,69,"},
                {"gameNo": 114798135, "gameNoRound": 8, "result": 76,
                 "resultContent": "b:23,23,;p:5,21,"},
            ],
        },
    },
}

ROUND_FRAME = {
    "protocol": 25,
    "data": {
        "gameID": 101,
        "groupID": 508,
        "result": 34,
        "playerScore": 3,
        "bankerScore": 2,
        "dtCard": {
            "1": {"cardID": 53, "inputType": 4},
            "2": {"cardID": 72, "inputType": 4},
            "3": {"cardID": 62, "inputType": 4},
            "4": {"cardID": 11, "inputType": 4},
            "5": {"cardID": 61, "inputType": 4},
            "6": {"cardID": 62, "inputType": 4},
        },
    },
}

ROUND_WITH_SENTINEL = {
    "protocol": 25,
    "data": {
        "gameID": 101,
        "groupID": 508,
        "result": 193,
        "playerScore": 3,
        "bankerScore": 8,
        "dtCard": {
            "1": {"cardID": 23}, "2": {"cardID": 43}, "3": {"cardID": 13},
            "4": {"cardID": 65}, "5": {"cardID": 15}, "6": {"cardID": 15},
        },
    },
}


class CardMappingTests(unittest.TestCase):
    def test_rank_uses_20_slot_suits(self):
        self.assertEqual([wm.card_rank(card) for card in (1, 13, 21, 33, 41, 53, 61, 73)],
                         [1, 13, 1, 13, 1, 13, 1, 13])

    def test_values_follow_baccarat_rules(self):
        self.assertEqual(wm.card_value(1), 1)     # A
        self.assertEqual(wm.card_value(9), 9)
        self.assertEqual(wm.card_value(10), 0)    # 10
        self.assertEqual(wm.card_value(11), 0)    # J
        self.assertEqual(wm.card_value(13), 0)    # K
        self.assertEqual(wm.card_value(21), 1)    # A chất khác

    def test_sentinel_ids_are_not_cards(self):
        for card in (14, 15, 20, 34, 54, 60):
            self.assertFalse(wm.valid_card(card), card)

    def test_canonical_ids_are_1_to_52(self):
        seen = {wm.canonical_card(card) for card in
                list(range(1, 14)) + list(range(21, 34)) + list(range(41, 54)) +
                list(range(61, 74))}
        self.assertEqual(len(seen), 52)
        self.assertTrue(all(1 <= card <= 52 for card in seen))
        # Giữ nguyên rank/chất: id 1 (A♠) -> 1, id 73 (K♣) -> 52.
        self.assertEqual(wm.canonical_card(1), 1)
        self.assertEqual(wm.canonical_card(73), 52)


class ResultCodeTests(unittest.TestCase):
    def test_low_bits_are_the_winner(self):
        cases = {33: "B", 34: "P", 36: "T", 49: "B", 50: "P", 52: "T",
                 65: "B", 66: "P", 68: "T", 193: "B", 322: "P", 338: "P",
                 74: "P", 76: "T", 81: "B", 92: "T", 209: "B", 4097: "B"}
        for code, winner in cases.items():
            self.assertEqual(wm.winner_from_code(code), winner, code)

    def test_side_flags(self):
        flags = wm.code_flags(209)     # B + Player đôi + không rút lá 3 + natural
        self.assertTrue(flags["player_pair"])
        self.assertFalse(flags["banker_pair"])
        self.assertTrue(flags["no_third_card"])
        self.assertTrue(flags["banker_natural"])
        self.assertTrue(wm.code_flags(338)["player_pair"])
        self.assertTrue(wm.code_flags(33)["third_card"])


class HistoryTests(unittest.TestCase):
    def test_result_content_splits_banker_and_player(self):
        cards = wm.decode_result_content("b:52,2,50;p:33,13,61")
        self.assertEqual(cards["banker"], [52, 2, 50])
        self.assertEqual(cards["player"], [33, 13, 61])

    def test_history_rounds_match_result_codes(self):
        rounds = wm.decode_history(HISTORY_FRAME["data"])
        self.assertEqual(len(rounds), 8)
        self.assertEqual(wm.letters(rounds), "BBPBBPPT")
        self.assertEqual(rounds[0]["banker_score"], 2)   # b:52,2,50 -> 0+2+0
        self.assertEqual(rounds[0]["player_score"], 1)   # p:33,13,61 -> 0+0+1
        self.assertEqual(rounds[0]["winner"], "B")
        self.assertTrue(rounds[1]["player_pair"])        # p:27,7 cùng rank 7

    def test_history_without_cards_still_reports_letters(self):
        data = {"gameID": 101, "groupID": 1, "historyArr": [33, 34, 36],
                "historyData": {"resultObjArr": []}}
        self.assertEqual(wm.letters(wm.decode_history(data)), "BPT")


class RoundTests(unittest.TestCase):
    def test_dtcard_slots_map_to_sides(self):
        round_data = wm.decode_round(ROUND_FRAME["data"])
        self.assertEqual(round_data["player_cards"], [53, 62, 61])
        self.assertEqual(round_data["banker_cards"], [72, 11, 62])
        self.assertEqual(round_data["winner"], "P")
        self.assertEqual(round_data["player_score"], 3)
        self.assertEqual(round_data["banker_score"], 2)

    def test_sentinel_cards_are_dropped(self):
        round_data = wm.decode_round(ROUND_WITH_SENTINEL["data"])
        self.assertEqual(round_data["player_cards"], [23, 13])
        self.assertEqual(round_data["banker_cards"], [43, 65])
        self.assertEqual(round_data["banker_score"], 8)


class FrameTests(unittest.TestCase):
    def test_decode_binary_frame(self):
        payload = base64.b64encode(json.dumps(HISTORY_FRAME).encode("utf-8")).decode("ascii")
        decoded = wm.decode_frame(payload, 2)
        self.assertEqual(decoded["protocol"], 26)
        self.assertEqual(decoded["data"]["groupID"], 531)

    def test_decode_text_frame_and_reject_garbage(self):
        self.assertEqual(wm.decode_frame(json.dumps(ROUND_FRAME), 1)["protocol"], 25)
        self.assertIsNone(wm.decode_frame("not json", 1))
        self.assertIsNone(wm.decode_frame(base64.b64encode(b"[]").decode(), 2))

    def test_table_key_round_trip(self):
        self.assertEqual(wm.table_key(101, 531), "101_531")
        self.assertEqual(wm.parse_table_key("101_531"), (101, 531))
        self.assertIsNone(wm.parse_table_key("531"))

    def test_section_id_is_parsed(self):
        parsed = wm.parse_section_id("groupBac_101_1355_86")
        self.assertEqual((parsed["game"], parsed["group"], parsed["type"]), (101, 1355, 86))
        self.assertIsNone(wm.parse_section_id("groupBac_bad"))


class LobbyAbsorbTests(unittest.TestCase):
    def test_absorb_wm_collects_history_and_table(self):
        from aibcr.adapters import lobby_stream as LS

        stream = LS.LobbyStream()
        payload = base64.b64encode(json.dumps(HISTORY_FRAME).encode("utf-8")).decode("ascii")
        stream._absorb({"opcode": 2, "payloadData": payload})
        self.assertEqual(stream.wm_histories["101_531"]["rounds"][0]["winner"], "B")
        table = {"protocol": 21, "data": {"gameID": 101, "groupID": 531, "gameNo": 1,
                                          "gameNoRound": 9, "betMilliSecond": 19000,
                                          "tableDtExtend": {"tableName": "百家樂"}}}
        stream._absorb({"opcode": 2, "payloadData":
                        base64.b64encode(json.dumps(table).encode()).decode()})
        self.assertEqual(stream.wm_tables["101_531"]["round"], 9)
        self.assertEqual(stream.wm_tables["101_531"]["bet_milliseconds"], 19000)

    def test_absorb_ignores_non_wm_frames(self):
        from aibcr.adapters import lobby_stream as LS

        stream = LS.LobbyStream()
        stream._absorb({"opcode": 1, "payloadData": '{"type": "lobby.histories"}'})
        self.assertEqual(stream.wm_histories, {})
        self.assertEqual(stream.histories, {})


class WMPageDetectionTests(unittest.TestCase):
    def test_table_tab_is_found_after_lobby_tab(self):
        from unittest.mock import patch
        from aibcr.live import wm_reader

        class FakeSocket:
            def __init__(self, kind):
                self.kind = kind

            def send(self, _message):
                pass

            def recv(self):
                return json.dumps({"id": 2, "result": {"result": {
                    "value": {"is_wm": True, "kind": self.kind}}}})

            def close(self):
                pass

        pages = [
            {"url": "https://wm.example/lobby", "webSocketDebuggerUrl": "ws://lobby"},
            {"url": "https://wm.example/table", "webSocketDebuggerUrl": "ws://table"},
        ]
        sockets = {"ws://lobby": FakeSocket("lobby"),
                   "ws://table": FakeSocket("table")}
        with patch.object(wm_reader, "list_pages", return_value=pages), \
                patch("websocket.create_connection", side_effect=lambda endpoint, **_kw: sockets[endpoint]):
            page, detect = wm_reader.find_wm_page(9222)

        self.assertEqual(page["url"], "https://wm.example/table")
        self.assertEqual(detect["kind"], "table")


if __name__ == "__main__":
    unittest.main()
