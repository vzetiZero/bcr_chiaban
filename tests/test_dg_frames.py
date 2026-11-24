# -*- coding: utf-8 -*-
"""Tests cho bộ giải mã khung WebSocket DG (Laya, sảnh DG của GK881).

Dữ liệu mẫu là khung nhị phân thật đo được trên bàn 60101, nên test khoá đúng cấu
trúc protobuf mà DG đang gửi; nếu DG đổi cấu trúc thì phải sửa cả hai nơi.
"""

import base64
import unittest

from aibcr.live import cards as CARDS
from aibcr.live import dg_frames as DGF


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field, wire):
    return _varint((field << 3) | wire)


def _uint(field, value):
    return _tag(field, 0) + _varint(int(value))


def _bytes(field, payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return _tag(field, 2) + _varint(len(payload)) + payload


def bet_state_frame(table_id=60101, countdown=24, state_id=1,
                    game_no="202611240011R1024",
                    cards='{"banker":"44-28-0","player":"5-32-7"}'):
    """Dựng khung 1002 (mở cược) đúng bố cục đo được."""
    sub = b"".join([
        _uint(1, table_id),
        _uint(2, 11),
        _uint(3, countdown),
        _uint(4, state_id),
        _uint(5, 0),
        _bytes(7, cards),
        _bytes(11, game_no),
        _bytes(14, "1"),
        _uint(15, 0),
        _uint(16, 0),
    ])
    return b"".join([_uint(1, DGF.MSG_BET_STATE), _uint(4, 6), _bytes(17, sub)])


def result_frame(player=("3C227", "7C229", ""), banker=("AS228", "6H230", ""),
                 table_id=60101):
    """Dựng khung 1003 (kết quả) đúng bố cục đo được."""
    payload = '{"banker":%s,"player":%s}' % (
        _json_list(banker), _json_list(player))
    return b"".join([_uint(1, DGF.MSG_RESULT),
                     _bytes(5, "2611244141613"),
                     _uint(6, table_id),
                     _bytes(14, payload)])


def _json_list(values):
    import json
    return json.dumps(list(values))


class CardLabelTest(unittest.TestCase):
    def test_labels_map_to_rank_major_ids(self):
        # Thứ tự chất theo aibcr.live.cards: ♠=0, ♥=1, ♦=2, ♣=3.
        # id = (rank - 1) * 4 + chỉ_số_chất + 1
        self.assertEqual(DGF.label_to_card_id("AS228"), 1)      # Át Bích
        self.assertEqual(DGF.label_to_card_id("3C227"), 12)     # 3 Chuồn
        self.assertEqual(DGF.label_to_card_id("7C229"), 28)     # 7 Chuồn
        self.assertEqual(DGF.label_to_card_id("6H230"), 22)     # 6 Cơ
        self.assertEqual(DGF.label_to_card_id("10H19"), 38)     # 10 Cơ
        self.assertEqual(DGF.label_to_card_id("KD1"), 51)       # K Rô
        # Đối chiếu ngược với chính module lá bài để không lệch bảng.
        for label, card_id in (("AS228", 1), ("3C227", 12), ("10H19", 38)):
            self.assertEqual(CARDS.card_label(card_id), "%s%s" % (
                CARDS.RANK_NAMES[CARDS.card_rank(card_id) - 1],
                CARDS.SUIT_NAMES[(card_id - 1) % 4]))
            self.assertTrue(label.startswith(DGF.LABEL_TAIL_RE.sub("", label)))

    def test_label_rejects_garbage(self):
        for bad in ("", None, "  ", "ZZ9", "1X2", "C"):
            self.assertIsNone(DGF.label_to_card_id(bad), bad)
        # Nhãn không có đuôi số vẫn đọc được: "AS" = Át Bích.
        self.assertEqual(DGF.label_to_card_id("AS"), 1)

    def test_numeric_ids_are_suit_major(self):
        # Bằng chứng thật trên bàn 60101: khung cho player [35, 11], ảnh chụp bàn hiện
        # đúng 9♣ + J♠ và header ghi "9 VS 0". DG xếp id theo CHẤT (13 lá một chất,
        # thứ tự ♠ ♥ ♣ ♦), không phải rank-major như aibcr.live.cards.
        player, _banker = DGF.cards_from_json('{"player":"35-11-0","banker":"0-0-0"}')
        self.assertEqual([CARDS.card_label(card) for card in player],
                         ["9♣", "J♠"])
        self.assertEqual(CARDS.hand_total(player), 9)

        # Ảnh chụp thứ hai: player [20, 16] hiện 7♥ + 3♥ = 10 -> 0 điểm, header "P 0".
        player2, _ = DGF.cards_from_json('{"player":"20-16-0","banker":"0-0-0"}')
        self.assertEqual([CARDS.card_label(card) for card in player2],
                         ["7♥", "3♥"])
        self.assertEqual(CARDS.hand_total(player2), 0)

    def test_dash_ids_still_work(self):
        self.assertEqual([CARDS.card_label(c) for c in DGF.card_ids("44-28-0")],
                         ["5♦", "2♣"])
        self.assertEqual(DGF.card_ids("0-0-0"), [])
        self.assertEqual(DGF.card_ids("55-1"), [])  # 55 ngoài 1..52
        self.assertEqual(DGF.card_ids("1-2-3"), [
            DGF.card_id(1), DGF.card_id(2), DGF.card_id(3)])

    def test_every_dg_id_maps_to_a_unique_card(self):
        # 52 id DG phải phủ đúng 52 lá, không trùng và không rỗng.
        mapped = [DGF.card_id(number) for number in range(1, 53)]
        self.assertEqual(len(set(mapped)), 52)
        self.assertTrue(all(CARDS.valid_card(card) for card in mapped))
        self.assertIsNone(DGF.card_id(0))
        self.assertIsNone(DGF.card_id(53))
        self.assertIsNone(DGF.card_id("abc"))


class CardsFromJsonTest(unittest.TestCase):
    def test_reads_numeric_and_label_forms(self):
        player, banker = DGF.cards_from_json('{"banker":"44-28-0","player":"5-32-7"}')
        self.assertEqual(player, [DGF.card_id(5), DGF.card_id(32), DGF.card_id(7)])
        self.assertEqual(banker, [DGF.card_id(44), DGF.card_id(28)])

        player, banker = DGF.cards_from_json(
            '{"banker":["AS228","6H230",""],"player":["3C227","7C229",""]}')
        self.assertEqual(player, [12, 28])
        self.assertEqual(banker, [1, 22])

    def test_both_forms_agree_on_the_same_cards(self):
        # Cùng một lá: dạng số (id DG) và dạng nhãn (tên hạng + chất) phải ra cùng id.
        names = {0: "S", 1: "H", 2: "D", 3: "C"}
        for number in range(1, 53):
            converted = DGF.card_id(number)
            rank_name = CARDS.RANK_NAMES[CARDS.card_rank(converted) - 1]
            suit = names[(converted - 1) % 4]
            back = DGF.label_to_card_id("%s%s7" % (rank_name, suit))
            self.assertEqual(back, converted, "%d -> %s" % (number, rank_name))

    def test_bad_json_is_empty_not_raising(self):
        self.assertEqual(DGF.cards_from_json("not json"), ([], []))
        self.assertEqual(DGF.cards_from_json('{"player": 5}'), ([], []))


class HandVerdictTest(unittest.TestCase):
    def test_uses_the_shared_card_map(self):
        # 3+7 = 10 -> 0 điểm (baccarat); A+6 = 7 điểm -> Banker thắng.
        player = [DGF.label_to_card_id("3C227"), DGF.label_to_card_id("7C229")]
        banker = [DGF.label_to_card_id("AS228"), DGF.label_to_card_id("6H230")]
        self.assertEqual(CARDS.hand_total(player), 0)
        self.assertEqual(CARDS.hand_total(banker), 7)
        verdict = DGF.hand_verdict(player, banker)
        self.assertEqual(verdict["player_score"], 0)
        self.assertEqual(verdict["banker_score"], 7)
        self.assertEqual(verdict["winner"], "B")

    def test_tie_and_incomplete(self):
        player = [DGF.label_to_card_id("5H1")]
        banker = [DGF.label_to_card_id("5S2")]
        self.assertEqual(DGF.hand_verdict(player, banker)["winner"], "T")
        self.assertEqual(DGF.hand_verdict([], banker)["winner"], "")


class DecodeFrameTest(unittest.TestCase):
    def test_decodes_real_bet_state_frame(self):
        frame = DGF.decode_frame(bet_state_frame())
        self.assertIsNotNone(frame)
        self.assertEqual(frame["kind"], DGF.MSG_BET_STATE)
        self.assertEqual(frame["table_id"], "60101")
        self.assertEqual(frame["game_no"], "202611240011R1024")
        self.assertEqual(frame["state_id"], 1)
        self.assertEqual(frame["countdown"], 24)
        # Player "5-32-7" = 5♠ 6♣ 7♠ -> 18 -> 8 điểm; banker "44-28" = 5♦ 2♣ -> 7 điểm.
        self.assertEqual([CARDS.card_label(c) for c in frame["player_cards"]],
                         ["5♠", "6♣", "7♠"])
        self.assertEqual([CARDS.card_label(c) for c in frame["banker_cards"]],
                         ["5♦", "2♣"])
        self.assertEqual(frame["player_score"], 8)
        self.assertEqual(frame["banker_score"], 7)
        self.assertEqual(frame["winner"], "P")

    def test_decodes_real_result_frame(self):
        frame = DGF.decode_frame(result_frame())
        self.assertIsNotNone(frame)
        self.assertEqual(frame["kind"], DGF.MSG_RESULT)
        self.assertEqual(frame["table_id"], "60101")
        self.assertEqual(frame["player_cards"], [12, 28])
        self.assertEqual(frame["banker_cards"], [1, 22])
        self.assertEqual(frame["winner"], "B")

    def test_ignores_unrelated_or_broken_payloads(self):
        self.assertIsNone(DGF.decode_frame(b""))
        self.assertIsNone(DGF.decode_frame(b"\x08\x01"))  # kind 1: khung khác
        self.assertIsNone(DGF.decode_frame("khong phai bytes"))
        # Khung đúng loại nhưng không có dữ liệu bàn/ván.
        self.assertIsNone(DGF.decode_frame(_uint(1, DGF.MSG_RESULT)))

    def test_truncated_frame_does_not_raise(self):
        raw = bet_state_frame()
        for cut in (1, 5, len(raw) // 2, len(raw) - 1):
            DGF.decode_frame(raw[:cut])  # chỉ cần không ném lỗi

    def test_round_trips_through_base64_like_cdp(self):
        raw = bet_state_frame(state_id=5, countdown=0, game_no="202611240010R1052")
        decoded = DGF.decode_frame(base64.b64decode(base64.b64encode(raw)))
        self.assertEqual(decoded["state_id"], 5)
        self.assertEqual(decoded["game_no"], "202611240010R1052")


if __name__ == "__main__":
    unittest.main()
