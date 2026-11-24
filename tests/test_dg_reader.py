# -*- coding: utf-8 -*-
"""Tests cho ``DGReader`` — bộ đọc bàn DG (Laya) của sảnh DG.

Khung dựng theo đúng bố cục protobuf đo được trên bàn 60101, nên test khoá cả hành
vi "chỉ phát khi ván đã ngã" và "chỉ nhận bàn đang mở".
"""

import unittest

from aibcr.live import dg_frames as DGF
from aibcr.live.dg_reader import DGReader

from tests.test_dg_frames import bet_state_frame, result_frame


class Recorder:
    def __init__(self):
        self.rounds = []
        self.states = []

    def on_round(self, data):
        self.rounds.append(data)

    def on_state(self, state):
        self.states.append(state)


def make_reader():
    rec = Recorder()
    reader = DGReader(on_round=rec.on_round, on_state=rec.on_state)
    return reader, rec


class EmitOnSettledTest(unittest.TestCase):
    def test_result_mid_round_is_not_emitted(self):
        # Khung 1003 đến giữa ván (mới 2 lá) không được coi là kết quả.
        reader, rec = make_reader()
        reader.handle_frame(bet_state_frame(countdown=20, state_id=1,
                                           game_no="202611240011R1050"))
        payload = reader.handle_frame(result_frame())
        self.assertIsNone(payload)
        self.assertEqual(rec.rounds, [])

    def test_settled_bet_state_emits_one_round(self):
        reader, rec = make_reader()
        reader.handle_frame(bet_state_frame(countdown=20, state_id=1,
                                           game_no="202611240011R1050"))
        payload = reader.handle_frame(bet_state_frame(
            countdown=0, state_id=5, game_no="202611240011R1050",
            cards='{"banker":["AS228","6H230",""],"player":["3C227","7C229",""]}'))
        self.assertIsNotNone(payload)
        self.assertEqual(len(rec.rounds), 1)
        self.assertEqual(payload["game_no"], "202611240011R1050")
        self.assertEqual(payload["round"], 1050)
        self.assertEqual(payload["winner"], "B")
        self.assertEqual(payload["player_score"], 0)
        self.assertEqual(payload["banker_score"], 7)
        self.assertEqual(payload["table"], "60101")

    def test_same_round_is_never_emitted_twice(self):
        reader, rec = make_reader()
        frame = bet_state_frame(countdown=0, state_id=5,
                                game_no="202611240011R1051",
                                cards='{"banker":"AS228","player":"10H19"}')
        self.assertIsNotNone(reader.handle_frame(frame))
        self.assertIsNone(reader.handle_frame(frame))
        self.assertEqual(len(rec.rounds), 1)

    def test_state_events_report_betting_then_result(self):
        reader, rec = make_reader()
        reader.handle_frame(bet_state_frame(countdown=25, state_id=1,
                                            game_no="202611240011R1052"))
        self.assertTrue(rec.states)
        self.assertEqual(rec.states[-1]["state"], "BETTING")
        self.assertEqual(rec.states[-1]["round"], 1052)
        reader.handle_frame(bet_state_frame(countdown=0, state_id=5,
                                            game_no="202611240011R1052",
                                            cards='{"banker":"AS228","player":"5H1"}'))
        self.assertEqual(rec.states[-1]["state"], "SHOW_RESULT")

    def test_result_frame_without_known_game_is_not_emitted(self):
        # Không có khung 1002 nào mang mã ván -> không được đoán tay.
        reader, rec = make_reader()
        payload = reader.handle_frame(result_frame())
        self.assertIsNone(payload)
        self.assertEqual(rec.rounds, [])


class OpenTableFilterTest(unittest.TestCase):
    def test_frames_of_other_tables_are_ignored(self):
        reader, rec = make_reader()
        reader.open_table_id = "60101"
        # Bàn 60102 (bàn xem trước trong sảnh) không được nhận.
        other = bet_state_frame(countdown=0, state_id=5, table_id=60102,
                                game_no="202611240012R2037",
                                cards='{"banker":"AS228","player":"5H1"}')
        self.assertIsNone(reader.handle_frame(other))
        self.assertEqual(rec.rounds, [])
        # Bàn đang mở thì nhận.
        mine = bet_state_frame(countdown=0, state_id=5, table_id=60101,
                               game_no="202611240011R1053",
                               cards='{"banker":"AS228","player":"5H1"}')
        self.assertIsNotNone(reader.handle_frame(mine))
        self.assertEqual(len(rec.rounds), 1)

    def test_no_filter_until_open_table_known(self):
        reader, rec = make_reader()
        frame = bet_state_frame(countdown=0, state_id=5, table_id=60104,
                                game_no="202611240012R4002",
                                cards='{"banker":"AS228","player":"5H1"}')
        self.assertIsNotNone(reader.handle_frame(frame))


class RoundNumberTest(unittest.TestCase):
    def test_round_number_from_game_no(self):
        self.assertEqual(DGReader._round_no("202611240011R1050"), 1050)
        self.assertIsNone(DGReader._round_no(""))
        self.assertIsNone(DGReader._round_no("khong-co-ma"))
        self.assertIsNone(DGReader._round_no("202611240011Rxx"))

    def test_table_id_from_url(self):
        from aibcr.live.dg_reader import table_id_from_url
        self.assertEqual(table_id_from_url(
            "https://x/ddnewwap/index.html?token=abc&tableId=60101"), "60101")
        self.assertEqual(table_id_from_url("https://x/ddnewwap/index.html"), "")


class GarbageInputTest(unittest.TestCase):
    def test_broken_frames_do_not_raise(self):
        reader, rec = make_reader()
        for raw in (b"", b"\xff", None, "text", b"\x08\x01"):
            reader.handle_frame(raw)
        self.assertEqual(rec.rounds, [])


if __name__ == "__main__":
    unittest.main()
