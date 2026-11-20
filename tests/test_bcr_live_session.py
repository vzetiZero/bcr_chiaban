# -*- coding: utf-8 -*-
"""Kiểm thử vòng chạy live của tools/bcr_live.py (không cần Chrome).

Khoá hai lỗi thực tế đã gặp khi chạy với site thật:

    - cùng một ván bị phát lại (mở lại tab / reconnect) không được cộng lá 2 lần
    - dự đoán không được báo "cửa tốt nhất" khi cả 3 cửa đều EV âm
"""

import importlib.util
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aibcr.live import cards

SPEC = importlib.util.spec_from_file_location("bcr_live", ROOT / "tools" / "bcr_live.py")
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)

ROUND = {
    "issue_id": "BCR_VV77845-261119-0514",
    "table": "BCR_VV77845",
    "player_cards": [28, 32, 5],
    "banker_cards": [37, 41, 49],
    "winner": None,
    "bets": [],
}


class SessionTests(unittest.TestCase):
    def build(self, **kwargs):
        session = LIVE.Session(decks=8, trials=600, seed=20261119, table="", **kwargs)
        session.out = io.StringIO()
        return session

    def test_duplicate_issue_is_not_counted_twice(self):
        session = self.build()
        session.on_round(dict(ROUND))
        dealt = session.shoe.dealt
        session.on_round(dict(ROUND))
        self.assertEqual(session.shoe.dealt, dealt)
        self.assertEqual(session.duplicates, 1)
        self.assertEqual(len(session.rounds), 1)

    def test_new_issue_is_counted(self):
        session = self.build()
        session.on_round(dict(ROUND))
        second = dict(ROUND, issue_id="BCR_VV77845-261119-0515")
        session.on_round(second)
        self.assertEqual(len(session.rounds), 2)
        self.assertEqual(session.shoe.dealt, 12)

    def test_prediction_after_round_has_probabilities(self):
        session = self.build()
        session.on_round(dict(ROUND))
        prediction = session.prediction
        self.assertTrue(prediction["ok"])
        total = sum(prediction["probabilities"].values())
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertFalse(prediction["playable"])
        self.assertIsNone(prediction["best_side"])

    def test_shoe_snapshot_reflects_dealt_cards(self):
        session = self.build()
        session.on_round(dict(ROUND))
        self.assertEqual(session.shoe.remaining, 52 * 8 - 6)
        self.assertTrue(cards.Shoe(8).value_counts())


if __name__ == "__main__":
    unittest.main(verbosity=2)
