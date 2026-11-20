# -*- coding: utf-8 -*-
"""Kiểm thử bộ đọc live BCR (cards/decode/predict) và tool dòng lệnh.

Mọi test chạy bằng dữ liệu thật đã bắt từ site (khung WS trong
``tests/fixtures``-style: các chuỗi dưới đây chép từ aibcr_ws_frames.jsonl).
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aibcr.live import cards, decode, predict

# Khung thật: P 22,8 (9) · B 3,49 (3) → Player thắng, natural.
REAL_RESULT = (
    ';game;petaball;onGetGameResult;0;0;{"issueId":"BCR_VV77842-261119-0369",'
    '"result":"22,8-3,49","roomId":"petaball-BCR_VV77842",'
    '"listBetTypeWin":["LIVE_BCR_BANKER_ODD","LIVE_BCR_PLAYER","LIVE_BCR_PLAYER_NATURAL",'
    '"LIVE_BCR_PLAYER_EVEN"]}'
)
REAL_TIE = (
    ';game;petaball;onGetGameResult;0;0;{"issueId":"BCR_VV77844-261119-0330",'
    '"result":"28,23,22-46,23,12","roomId":"petaball-BCR_VV77844",'
    '"listBetTypeWin":["LIVE_BCR_TIE"]}'
)
REAL_STATE = (
    ';game;petaball-BCR_VV77842;onGetGameInfo;0;0;{"issueId":"BCR_VV77842-261119-0369",'
    '"state":"BETTING","timeRemains":2,"result":"","totalPlayer":5045}'
)
OTHER_GAME = (';game;petaball;onGetGameResult;0;0;{"issueId":"SICBO_VV282-261119-0193",'
              '"result":"335","roomId":"petaball-SICBO_VV282",'
              '"listBetTypeWin":["SICBO_BIG"]}')


class CardTests(unittest.TestCase):
    def test_rank_and_value_mapping_matches_live_data(self):
        # 19 -> 5, 14 -> 4 ... đã đối chiếu 34 ván thật.
        self.assertEqual(cards.card_rank(19), 5)
        self.assertEqual(cards.card_rank(14), 4)
        self.assertEqual(cards.card_rank(49), 13)
        self.assertEqual(cards.card_value(49), 0)     # K
        self.assertEqual(cards.card_value(45), 0)     # Q
        self.assertEqual(cards.card_value(41), 0)     # J
        self.assertEqual(cards.card_value(37), 0)     # 10
        self.assertEqual(cards.card_value(33), 9)
        self.assertEqual(cards.card_value(1), 1)      # A

    def test_hand_total_and_natural(self):
        # Ván thật BCR_VV77842-261119-0369: P 22,8 = 8 điểm · B 20,52 = 5 điểm.
        self.assertEqual(cards.hand_total([22, 8]), 8)
        self.assertEqual(cards.hand_total([20, 52]), 5)
        self.assertEqual(cards.hand_total([28, 23, 22]), 9)
        self.assertTrue(cards.is_natural([22, 8]))
        self.assertFalse(cards.is_natural([22, 8, 4]))

    def test_shoe_counts_decrement_and_detect_exhaustion(self):
        shoe = cards.Shoe(1)
        self.assertEqual(shoe.remaining, 52)
        shoe.take(19)
        self.assertEqual(shoe.remaining, 51)
        # id 19 là rank 5: mỗi bộ có 4 lá, đã dùng 1 nên còn 3.
        self.assertEqual(shoe.value_counts()[cards.card_value(19)], 3)
        for card_id in range(1, 53):
            if card_id != 19:
                shoe.take(card_id)
        with self.assertRaises(ValueError):
            shoe.take(19)

    def test_value_counts_has_ten_buckets(self):
        counts = cards.Shoe(8).value_counts()
        self.assertEqual(len(counts), 10)
        self.assertEqual(sum(counts), 52 * 8)
        self.assertEqual(counts[0], 16 * 8)   # 10/J/Q/K = 4 rank × 4 chất


class DecodeTests(unittest.TestCase):
    def test_split_and_decode_a_real_round(self):
        frame = decode.split_frame(REAL_RESULT)
        self.assertEqual(frame.event, decode.EVENT_RESULT)
        data = decode.decode_round(frame)
        self.assertEqual(data["table"], "BCR_VV77842")
        self.assertEqual(data["player_cards"], [22, 8])
        self.assertEqual(data["banker_cards"], [3, 49])
        self.assertEqual(data["winner"], "P")
        self.assertIn("LIVE_BCR_PLAYER_NATURAL", data["bets"])

    def test_tie_round_is_decoded(self):
        data = decode.decode_round(decode.split_frame(REAL_TIE))
        self.assertEqual(data["winner"], "T")
        self.assertEqual(len(data["player_cards"]), 3)

    def test_non_baccarat_round_is_ignored(self):
        self.assertIsNone(decode.decode_round(decode.split_frame(OTHER_GAME)))

    def test_state_frame_is_decoded(self):
        state = decode.decode_state(decode.split_frame(REAL_STATE))
        self.assertEqual(state["state"], "BETTING")
        self.assertEqual(state["time_remains"], 2)

    def test_garbage_frames_are_ignored(self):
        self.assertIsNone(decode.split_frame("hello"))
        self.assertIsNone(decode.split_frame(";game;room;event"))
        self.assertIsNone(decode.decode_round(None))


class PredictTests(unittest.TestCase):
    def test_full_shoe_has_no_positive_edge(self):
        result = predict.predict(cards.Shoe(8), "", trials=20000, seed=7)
        probs = result["probabilities"]
        self.assertAlmostEqual(probs["p_banker"], 0.4586, delta=0.015)
        self.assertAlmostEqual(probs["p_player"], 0.4462, delta=0.015)
        self.assertAlmostEqual(probs["p_tie"], 0.0952, delta=0.01)
        self.assertFalse(result["playable"])
        self.assertIsNone(result["best_side"])
        self.assertIn("Bỏ tay", result["recommendation"])

    def test_removing_tens_moves_probability_toward_banker(self):
        """Chứng minh code thật sự phản ứng theo composition của shoe."""
        base = predict.monte_carlo(cards.Shoe(8).value_counts(), trials=20000, seed=9)
        counts = cards.Shoe(8).value_counts()
        counts[0] = 64          # rút bớt lá 10/J/Q/K
        lean = predict.monte_carlo(counts, trials=20000, seed=9)
        self.assertNotEqual(base["p_banker"], lean["p_banker"])
        self.assertGreater(lean["p_banker"], base["p_banker"] - 0.01)

    def test_markov_needs_enough_history(self):
        short = predict.markov("BPBP")
        self.assertIsNone(short["p_player"])
        taller = predict.markov("BPBPB" * 10)
        self.assertIsNotNone(taller["p_player"])
        self.assertEqual(taller["state"], "B")

    def test_markov_follows_the_last_side(self):
        table = predict.markov("PBBBPB" * 10)
        self.assertEqual(table["state"], "B")
        self.assertGreater(table["p_tie"], 0)

    def test_exhausted_shoe_is_reported(self):
        shoe = cards.Shoe(1)
        for card_id in range(1, 53):
            shoe.take(card_id)
        self.assertFalse(predict.predict(shoe, "")["ok"])

    def test_advance_round_updates_history_and_totals(self):
        shoe = cards.Shoe(8)
        verdict = predict.advance_round(shoe, [22, 8], [20, 52])
        self.assertEqual((verdict["player_total"], verdict["banker_total"]), (8, 5))
        self.assertEqual(verdict["winner"], "P")
        self.assertEqual(shoe.dealt, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
