# -*- coding: utf-8 -*-
"""Đặt cược theo cấu hình: chốt lệnh, chống đặt trùng, đối chiếu chip.

Phạm vi chỉ là vòng đặt cược: không đọc kết quả, không đổi mức theo thắng/thua.
"""

import pathlib
import tempfile
import time
import unittest

from aibcr.controllers.baccarat import BaccaratController


class Emitter:
    def event(self, name, data):
        pass


class BetTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_controller(self):
        controller = BaccaratController(
            str(pathlib.Path(self.tmp.name) / "state.json"), Emitter())
        self.addCleanup(controller.shutdown)
        return controller

    def ready(self, controller, letters="BBP"):
        row = {"key": "id:test", "label": "Bàn test", "letters": letters,
               "ts": time.time(), "table_id": "test", "stable": 3,
               "conflict": False, "read_error": ""}
        controller.tables = {row["key"]: row}
        controller.sim.bind(row)
        controller.sim.start(row)
        controller.sim.entry_waiting = False
        controller.tool_running = True
        return row

    def test_auto_tick_places_the_configured_side(self):
        controller = self.make_controller()
        controller.dispatch("bet.config", {"side": "P", "stake": 10})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))

        controller._auto_bet_tick()

        self.assertTrue(controller.sim.pending, controller.auto_bet_note)
        self.assertEqual(placed[0]["side"], "P")
        self.assertEqual(placed[0]["stake"], 10.0)

    def test_auto_tick_does_not_rearm_the_same_road(self):
        controller = self.make_controller()
        controller.dispatch("bet.config", {"side": "B", "stake": 20})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))

        controller._auto_bet_tick()
        controller.sim.pending = None       # chip đã đặt xong cho ván này
        controller._auto_bet_tick()

        self.assertEqual(len(placed), 1, "cùng một cầu thì không chốt lệnh lần hai")
        self.assertEqual(controller.auto_bet_hand, 4)

    def test_new_road_allows_the_next_bet(self):
        controller = self.make_controller()
        controller.dispatch("bet.config", {"side": "B", "stake": 20})
        row = self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        controller._auto_bet_tick()

        row["letters"] = "BBPB"
        row["stable"] = 3
        controller._process_sim(row)
        controller.sim.pending = None
        controller._auto_bet_tick()

        self.assertEqual(len(placed), 2)
        self.assertEqual(controller.auto_bet_hand, 5)

    def test_ladder_stake_is_fixed_no_matter_what_happens(self):
        controller = self.make_controller()
        reply = controller.dispatch(
            "bet.ladder.configure",
            {"stakes": "10 20 30", "min_t": 1, "max_t": 100, "side": "B"})[0]
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["stake"], 10)
        self.assertEqual(controller.bet_ladder.step, 0, "không tiến bước theo kết quả")

    def test_chip_check_compares_the_last_placed_order(self):
        controller = self.make_controller()
        controller.dispatch("bet.config", {"side": "B", "stake": 60})
        self.ready(controller)
        controller._place_armed_bet = lambda order: None
        controller.dispatch("bet.place", {})
        self.assertEqual(controller.last_order["side"], "B")

        controller.sim.pending = None
        controller.chip_live = {"ok": True, "unit": 1,
                               "spots": {"B": {"amount": 60.0, "amount_vnd": 60.0}}}
        self.assertEqual(controller.chip_check()["status"], "match")

        controller.last_order = None
        controller._resolve_order = lambda params=None: {
            "side": "P", "stake": 60.0, "reason": ""}
        self.assertEqual(controller.chip_check()["status"], "wrong_side")

    def test_stale_scan_does_not_shorten_the_tracked_road(self):
        controller = self.make_controller()
        self.ready(controller, letters="BBPB")
        controller._ingest([{"table_id": "test", "label": "Bàn test",
                            "letters": "BBP", "source": "cdp"}])
        self.assertEqual(controller.tables["id:test"]["letters"], "BBPB")

    def test_snapshot_has_no_money_or_result_blocks(self):
        controller = self.make_controller()
        self.ready(controller)
        snapshot = controller.snapshot()
        for key in ("money", "history", "live", "log_tail", "wallet_text"):
            self.assertNotIn(key, snapshot)
        self.assertEqual(snapshot["table"]["hand"], 3)

    def test_removed_methods_are_gone(self):
        controller = self.make_controller()
        for method in ("live.start", "live.stop", "ai.check", "ai.key.set",
                       "bet.ladder.result", "session.recover", "export"):
            result, error = controller.dispatch(method, {})
            self.assertIsNone(result)
            self.assertIn("không hỗ trợ", error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
