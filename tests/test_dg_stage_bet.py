# -*- coding: utf-8 -*-
"""Hợp đồng DG đo trực tiếp trên bàn 60101 (Laya), ghi lại để không tái phát.

Ba điều đo được bằng Chrome thật, không phải suy đoán:

* Chuỗi "10-1000" trên màn hình bàn và ``baccaratLimit.bpMin/bpMax`` cùng là
  10/1000, khay chip là ``10, 50, 100, … 500000``; vậy 1 đơn vị DG = 1 "k".
* ``chip.event('click')`` và ``spot.event('click')`` **không** đổi
  ``playerInfo.selectChip`` / ``betMoneyTmp``; ``chipMan.selectChipHandler(chip)``
  và ``view.betHandler({buttonName:'Player'})`` thì có.
* ``playerInfo.balance == 0`` làm ``checkBet`` chặn mọi cú bấm chip, nên phải báo
  đúng "số dư 0" thay vì đổ lỗi cho mệnh giá chip.
"""

import re
import unittest

from aibcr.adapters import febet as F


class StageBetSourceTest(unittest.TestCase):
    """Đọc mã nguồn để chặn việc quay lại các API Laya đã đo là không tác dụng."""

    @classmethod
    def setUpClass(cls):
        cls.js = F._DG_STAGE_BET_JS

    def test_selects_chip_through_chip_manager_handler(self):
        self.assertIn("selectChipHandler", self.js)

    def test_places_chip_through_view_bet_handler(self):
        self.assertIn("betHandler({buttonName:name})", self.js)

    def test_never_taps_nodes_with_synthetic_laya_events(self):
        """Phát sự kiện chuột vào node là đường đã đo là không chạy."""
        self.assertNotIn("event('mousedown')", self.js)
        self.assertNotIn("spot.event(", self.js)
        self.assertNotIn("chip.event(", self.js)

    def test_verifies_each_chip_by_reading_the_bet_box_again(self):
        self.assertIn("readTmp(side) - before === denom * scale", self.js)

    def test_zero_balance_is_reported_not_silently_blamed_on_the_chip(self):
        self.assertIn("balanceUnread", self.js)
        self.assertIn('kiểm tra "Balance" trong bàn', self.js)

    def test_zero_balance_does_not_hard_block_staging(self):
        """Có build chỉ điền số dư sau ván đầu, nên không được chặn cứng."""
        self.assertNotIn("if (balK <= 0)", self.js)

    def test_confirms_through_the_view_confirm_handler(self):
        self.assertIn("confirmBet", self.js)

    def test_never_divides_the_table_unit_again(self):
        self.assertIn("const scale = 1;", self.js)
        # Chip thật của bàn 60101: 10…500000, đọc nguyên giá trị.
        self.assertNotIn("amountK * scale) return", self.js)


class BetStateSourceTest(unittest.TestCase):
    def test_reports_whether_balance_was_actually_read(self):
        js = F._DG_BET_STATE_JS
        self.assertIn("balance_k", js)
        self.assertIn("balance_known", js)

    def test_chip_denominations_are_not_divided(self):
        self.assertIn("Math.round(raw / scale)", F._DG_BET_STATE_JS)

    def test_documents_the_measured_floor(self):
        js = F._DG_BET_STATE_JS
        match = re.search(r"const scale = 1;(.*)", js, re.S)
        self.assertIsNotNone(match)
        self.assertIn("10-1000", js)


class ZeroBalanceGateTest(unittest.TestCase):
    """Bài học từ lần chạy thật: balance 0 làm mọi cú bấm chip vô hiệu."""

    def test_error_names_the_balance_not_the_chip(self):
        js = F._DG_STAGE_BET_JS
        gate = re.search(r"const balK = .*?if \(!balanceUnread && amountK > balK\)",
                         js, re.S)
        self.assertIsNotNone(gate, "phải còn cổng kiểm số dư")
        self.assertIn("balanceUnread", gate.group(0))
        # Chỉ chặn khi đọc được số dư thật và số dư đó nhỏ hơn mức cược.
        self.assertIn("amountK > balK", gate.group(0))


if __name__ == "__main__":
    unittest.main()
