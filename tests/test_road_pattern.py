# -*- coding: utf-8 -*-
"""Big Road + xác suất theo dạng cầu + chọn cửa có xác suất cao nhất."""

import pathlib
import tempfile
import time
import unittest

from aibcr.controllers.baccarat import BaccaratController
from aibcr.live import cards, predict, road
from aibcr.live.session import LiveSession


class BigRoadTests(unittest.TestCase):
    def test_columns_and_dragon_tail(self):
        result = road.big_road("BBBBBBBP")
        # 6 ô đầu đầy cột 1; ô B thứ 7 đi sang phải cùng hàng (đuôi rồng) rồi P mở cột mới.
        self.assertEqual(len(result["columns"]), 3)
        self.assertEqual([cell["row"] for cell in result["columns"][0]], [0, 1, 2, 3, 4, 5])
        self.assertEqual([(cell["side"], cell["row"]) for cell in result["columns"][1]],
                         [("B", 5)])
        self.assertEqual(result["columns"][2][0]["side"], "P")

    def test_new_side_opens_new_column(self):
        result = road.big_road("BPBP")
        self.assertEqual(len(result["columns"]), 4)
        self.assertEqual([col[0]["side"] for col in result["columns"]],
                         ["B", "P", "B", "P"])

    def test_empty_and_junk_are_ignored(self):
        self.assertEqual(road.big_road("")["cells"], 0)
        self.assertEqual(road.big_road("BxP?T")["cells"], 2)
        self.assertEqual(road.last_streak("")["length"], 0)
        self.assertEqual(road.last_streak("BPPPT"), {"side": "P", "length": 3})

    def test_tie_is_a_marker_not_a_new_cell(self):
        """Big Road thật: hoà không mở cột mới mà là vạch trên ô của vệt đang chạy."""
        result = road.big_road("BTTB")
        self.assertEqual(len(result["columns"]), 1)
        self.assertEqual(result["cells"], 2)
        self.assertEqual(result["columns"][0][0]["ties"], 2)
        self.assertEqual([cell["row"] for cell in result["columns"][0]], [0, 1])
        leading = road.big_road("TTB")
        self.assertEqual(leading["cells"], 1)
        self.assertEqual(leading["leading_ties"], 2)
        self.assertEqual(leading["columns"][0][0]["ties"], 2)


class PatternTests(unittest.TestCase):
    def test_counts_and_streak(self):
        stats = predict.pattern_stats("BBPPPB")
        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["counts"], {"P": 3, "B": 3, "T": 0})
        self.assertEqual(stats["streak"], {"side": "B", "length": 1})
        self.assertAlmostEqual(sum(stats["shares"].values()), 1.0)

    def test_ties_do_not_break_the_visible_streak(self):
        """Big Road bỏ qua hoà: 3 tay B rồi hoà vẫn là chuỗi B 3 tay, không phải T."""
        stats = predict.pattern_stats("BBBT")
        self.assertEqual(stats["counts"]["T"], 1)
        self.assertEqual(stats["streak"], {"side": "B", "length": 3})

    def test_requires_enough_samples(self):
        stats = predict.pattern_stats("PB")
        self.assertIsNone(stats["probabilities"])

    def test_pattern_probabilities_when_history_repeats(self):
        # 10 chuỗi "PP" rồi đổi sang B: đủ mẫu cho bucket P dài 2.
        history = "PPB" * 10 + "PP"
        stats = predict.pattern_stats(history)
        self.assertEqual(stats["bucket"]["samples"], 10)
        self.assertIsNotNone(stats["probabilities"])
        self.assertAlmostEqual(stats["probabilities"]["B"], 1.0)

    def test_predict_exposes_top_side_and_normalised_probabilities(self):
        shoe = cards.Shoe(8)
        result = predict.predict(shoe, "PPBPBPPB", trials=800, seed=3)
        self.assertTrue(result["ok"])
        total = sum(result["probabilities"].values())
        self.assertAlmostEqual(total, 1.0, places=6)
        key = {"P": "p_player", "B": "p_banker", "T": "p_tie"}
        self.assertIn(result["top_side"], ("P", "B", "T"))
        self.assertAlmostEqual(result["top_probability"],
                               result["probabilities"][key[result["top_side"]]])
        self.assertIn("Cầu", predict.pattern_note(result["patterns"],
                                                  result["top_side"]))


class LiveSnapshotTests(unittest.TestCase):
    def test_snapshot_has_hand_history_and_road(self):
        session = LiveSession(trials=400)
        session.on_round({"issue_id": "a", "table": "WM 101_505", "winner": "B",
                          "player_cards": [1, 2], "banker_cards": [3, 4],
                          "round": 27})
        view = session.snapshot()
        self.assertEqual(view["history"], "B")
        self.assertEqual(view["hand"], 27)
        self.assertEqual(view["road"]["cells"], 1)
        self.assertEqual(view["road"]["columns"][0][0]["side"], "B")
        self.assertIn("pattern_note", view["prediction"])

    def test_state_updates_the_real_hand_number_and_notifies(self):
        """gameNoRound (protocol 21) là số tay thật: UI phải nhận ngay, không chờ ván mới."""
        session = LiveSession(trials=200)
        notified = []
        session.on_prediction = notified.append
        session.on_state({"table": "WM 101_505", "state": "BETTING", "round": 27,
                          "time_remains": 12.0})
        self.assertEqual(session.snapshot()["hand"], 27)
        self.assertEqual(session.snapshot()["state"], "BETTING")
        self.assertTrue(notified)
        # Tick betMilliSecond không làm bắn lại sự kiện (tránh spam UI mỗi giây).
        count = len(notified)
        session.on_state({"table": "WM 101_505", "state": "BETTING", "round": 27,
                          "time_remains": 11.0})
        self.assertEqual(len(notified), count)
        session.on_state({"table": "WM 101_505", "state": "SHOW_RESULT", "round": 27})
        self.assertEqual(len(notified), count + 1)


    def test_seed_rows_only_predict_once_at_the_end(self):
        """Nạp 30 ván cũ không được chạy Monte Carlo 30 lần (làm đứng UI)."""
        session = LiveSession(trials=100)
        notified = []
        session.on_prediction = notified.append
        for index in range(3):
            session.on_round({
                "issue_id": "seed:%d" % index, "table": "WM 101_505", "winner": "B",
                "player_cards": [1, 2], "banker_cards": [3, 4], "round": 24 + index,
                "seed": True, "seed_last": index == 2})
        self.assertEqual(session.snapshot()["history"], "BBB")
        self.assertEqual(session.snapshot()["hand"], 26)
        self.assertEqual(len(notified), 1)
        self.assertIsNotNone(session.snapshot()["prediction"])

    def _seed_batch(self, session, first=1, last=30, game_no=12215520, winners="B"):
        for index in range(first, last + 1):
            session.on_round({
                "issue_id": "seed:%d" % index, "table": "WM 101_505",
                "winner": winners[(index - first) % len(winners)],
                "player_cards": [1, 2], "banker_cards": [3, 4],
                "round": index, "game_no": game_no,
                "seed": True, "seed_last": index == last})

    def test_history_replay_after_live_round_is_merged_not_duplicated(self):
        """Protocol 26 về sau protocol 25 không được cộng trùng ván 30."""
        session = LiveSession(trials=100)
        session.on_round({
            "issue_id": "live:30", "table": "WM 101_505", "winner": "P",
            "player_cards": [1, 2], "banker_cards": [3, 4],
            "round": 30, "game_no": 12215520})
        self._seed_batch(session, winners="PB")
        view = session.snapshot()
        self.assertEqual(len(view["history"]), 30)
        self.assertEqual(view["hand"], 30)
        self.assertEqual(view["history"][-1], "P")
        self.assertGreaterEqual(view["duplicates"], 1)

    def test_repeated_history_replay_is_idempotent(self):
        session = LiveSession(trials=100)
        self._seed_batch(session, winners="PB")
        once = session.snapshot()["history"]
        self._seed_batch(session, winners="PB")
        self.assertEqual(session.snapshot()["history"], once)
        self.assertEqual(len(once), 30)

    def test_new_shoe_clears_old_road(self):
        session = LiveSession(trials=100)
        self._seed_batch(session, first=1, last=3, game_no=111, winners="B")
        self.assertEqual(session.snapshot()["history"], "BBB")
        session.on_round({
            "issue_id": "new-shoe", "table": "WM 101_505", "winner": "P",
            "player_cards": [5, 6], "banker_cards": [7, 8],
            "round": 1, "game_no": 222})
        view = session.snapshot()
        self.assertEqual(view["history"], "P")
        self.assertEqual(view["hand"], 1)

    def test_seed_loads_full_shoe_but_advances_only_recent_hands(self):
        """Lịch sử dài phải khớp số tay bàn; shoe chỉ trừ 40 tay cuối."""
        session = LiveSession(trials=100)
        for index in range(1, 61):
            session.on_round({
                "issue_id": "seed:%d" % index, "table": "WM 101_505",
                "winner": "B" if index % 2 else "P",
                "player_cards": [1 + (index * 4) % 52, 1 + (index * 4 + 1) % 52],
                "banker_cards": [1 + (index * 4 + 2) % 52, 1 + (index * 4 + 3) % 52],
                "round": index, "game_no": 777,
                "seed": True, "seed_last": index == 60})
        view = session.snapshot()
        self.assertEqual(len(view["history"]), 60)
        self.assertEqual(view["hand"], 60)
        self.assertEqual(view["result_hand"], 60)
        self.assertEqual(session.shoe.dealt, 40 * 4)


class WmReaderHandTests(unittest.TestCase):
    def test_result_and_state_carry_the_round_number(self):
        from aibcr.adapters import wm
        from aibcr.live.wm_reader import WMReader

        rounds, states = [], []
        reader = WMReader(on_round=rounds.append, on_state=states.append, port=1)
        reader.open_key = wm.table_key(101, 508)
        reader.handle({"protocol": 21, "data": {
            "gameID": 101, "groupID": 508, "gameNo": 114798135, "gameNoRound": 27,
            "betMilliSecond": 19000, "tableDtExtend": {"tableName": "Bàn 1"}}})
        reader.handle({"protocol": 25, "data": {
            "gameID": 101, "groupID": 508, "result": 34,
            "playerScore": 3, "bankerScore": 2,
            "dtCard": {"1": {"cardID": 53}, "2": {"cardID": 72}, "3": {"cardID": 62},
                       "4": {"cardID": 11}, "5": {"cardID": 61}, "6": {"cardID": 62}}}})
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["winner"], "P")
        self.assertEqual(rounds[0]["round"], 27, "protocol 25 phải kế thừa số tay từ 21")
        self.assertEqual(states[-1]["round"], 27)
        self.assertEqual(states[-1]["state"], "SHOW_RESULT")

    def test_result_round_follows_history_not_replayed_betting_round(self):
        """Protocol 25 không có số tay: lấy mốc lịch sử + 1, không lấy vòng 21 phát lại."""
        from aibcr.adapters import wm
        from aibcr.live.wm_reader import WMReader

        rounds, states = [], []
        reader = WMReader(on_round=rounds.append, on_state=states.append, port=1)
        reader.open_key = wm.table_key(101, 508)
        reader.handle({"protocol": 26, "data": {
            "gameID": 101, "groupID": 508,
            "historyData": {"resultObjArr": [
                {"gameNo": 555, "gameNoRound": index, "result": 1,
                 "resultContent": "b:3,4,;p:1,2,"} for index in range(1, 27)]}}})
        # WM phát lại vòng cược 28 trước khi khung kết quả tay 27 tới.
        reader.handle({"protocol": 21, "data": {
            "gameID": 101, "groupID": 508, "gameNo": 555, "gameNoRound": 28,
            "betMilliSecond": 15000}})
        reader.handle({"protocol": 25, "data": {
            "gameID": 101, "groupID": 508, "result": 34,
            "playerScore": 3, "bankerScore": 2,
            "dtCard": {"1": {"cardID": 53}, "2": {"cardID": 72},
                       "3": {"cardID": 62}, "4": {"cardID": 11}}}})
        self.assertEqual(rounds[-1]["round"], 27)
        self.assertEqual(states[-1]["round"], 27)
        self.assertEqual(states[-1]["state"], "SHOW_RESULT")

    def test_replayed_finished_round_does_not_move_hand_back(self):
        from aibcr.adapters import wm
        from aibcr.live.wm_reader import WMReader

        states = []
        reader = WMReader(on_round=lambda data: None, on_state=states.append, port=1)
        reader.open_key = wm.table_key(101, 508)
        reader._last_result_round = 27
        reader._last_result_game = "555"
        reader.handle({"protocol": 21, "data": {
            "gameID": 101, "groupID": 508, "gameNo": 555, "gameNoRound": 28,
            "betMilliSecond": 15000}})
        self.assertEqual(states[-1]["round"], 28)
        reader.handle({"protocol": 21, "data": {
            "gameID": 101, "groupID": 508, "gameNo": 555, "gameNoRound": 27,
            "betMilliSecond": 9000}})
        self.assertEqual(states[-1]["round"], 28, "không được lùi về tay đã có kết quả")


    def test_switch_table_resets_round_markers(self):
        """Đổi bàn: số tay bàn cũ không được chặn oan vòng đầu của bàn mới."""
        from aibcr.adapters import wm
        from aibcr.live.wm_reader import WMReader

        states = []
        reader = WMReader(on_round=lambda data: None, on_state=states.append, port=1)
        reader.open_key = wm.table_key(101, 508)
        reader._last_result_round = 52
        reader._last_result_game = "111"
        reader._round_by_cards = {"1,2,3,4": 52}
        reader.last_state = {"round": 52}
        reader._bind_open_table(wm.table_key(101, 1356))
        self.assertEqual(reader.open_key, wm.table_key(101, 1356))
        self.assertIsNone(reader._last_result_round)
        self.assertIsNone(reader._last_result_game)
        self.assertEqual(reader._round_by_cards, {})
        self.assertIsNone(reader.last_state)
        reader.handle({"protocol": 21, "data": {
            "gameID": 101, "groupID": 1356, "gameNo": 999, "gameNoRound": 15,
            "betMilliSecond": 10000}})
        self.assertEqual(states[-1]["round"], 15)


class ExplicitSideBetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_controller(self):
        class Emitter:
            def event(self, name, data):
                pass

        controller = BaccaratController(
            str(pathlib.Path(self.tmp.name) / "state.json"), Emitter())
        self.addCleanup(controller.shutdown)
        return controller

    def view(self):
        return {
            "running": True, "table": "WM test", "hand": 12, "rounds": 6,
            "table_name": "WM test", "history": "BBPBBP",
            "prediction": {"ok": True, "playable": False, "best_side": None,
                           "top_side": "B", "top_probability": 0.46,
                           "probabilities": {"p_player": 0.44, "p_banker": 0.46,
                                             "p_tie": 0.10}},
            "analysis": {"verdict": "BỎ TAY", "focus_side": "T"},
        }

    def ready(self, controller):
        row = {"key": "id:test", "label": "WM test", "letters": "BBP",
               "ts": time.time(), "table_id": "test", "stable": 3}
        controller.tables = {row["key"]: row}
        controller.sim.bind(row)
        controller.sim.start(row)
        controller.sim.entry_waiting = False
        controller.tool_running = True
        return row

    def test_explicit_side_is_not_replaced_by_prediction(self):
        controller = self.make_controller()

        class FakeLive:
            def snapshot(self):
                return self_outer.view()

        self_outer = self
        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "B", "stake": 60})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        result, error = controller.dispatch("bet.place", {})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertEqual(placed[0]["side"], "B")
        self.assertEqual(placed[0]["stake"], 60.0)
        self.assertIn("người dùng", placed[0]["reason"])

    def test_explicit_side_does_not_use_prediction_fallback(self):
        controller = self.make_controller()

        class FakeLive:
            def snapshot(self):
                view = self_outer.view()
                view["prediction"].pop("top_side")
                view["prediction"].pop("top_probability")
                view["prediction"]["probabilities"] = {"p_player": 0.39,
                                                       "p_banker": 0.51,
                                                       "p_tie": 0.10}
                return view

        self_outer = self
        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "P", "stake": 10})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        result, error = controller.dispatch("bet.place", {})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertEqual(placed[0]["side"], "P")

    def test_auto_bet_tick_uses_explicit_side_without_prediction(self):
        """Cửa do người dùng chọn có thể đặt dù chưa có dữ liệu dự đoán."""
        controller = self.make_controller()
        self_outer = self
        state = {"view": self.view()}
        state["view"]["prediction"] = None

        class FakeLive:
            def snapshot(self):
                return state["view"]

        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "P", "stake": 10})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))

        controller._auto_bet_tick()
        self.assertTrue(controller.sim.pending, controller.auto_bet_note)
        self.assertEqual(placed[0]["side"], "P")

    def test_chip_check_between_rounds_compares_last_placed_order(self):
        """Ván vừa ngã, chip ván đó còn trên bàn: không được báo SAI CỬA theo lệnh tay kế."""
        controller = self.make_controller()
        self_outer = self

        class FakeLive:
            def snapshot(self):
                return self_outer.view()

        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "B", "stake": 60})
        self.ready(controller)
        controller._place_armed_bet = lambda order: None
        controller.dispatch("bet.place", {})
        self.assertEqual(controller.last_order["side"], "B")

        # Kết quả về: pending bị xoá; chip Banker của ván vừa đặt vẫn hiện trên bàn.
        controller.sim.pending = None
        controller.chip_live = {"ok": True, "unit": 1,
                                "spots": {"B": {"amount": 60.0, "amount_vnd": 60.0}}}
        self.assertEqual(controller.chip_check()["status"], "match")

        # Chưa có lệnh nào: vẫn so theo lệnh sắp chốt như trước.
        controller.last_order = None
        controller._resolve_order = lambda params=None: {
            "side": "P", "stake": 60.0, "reason": ""}
        self.assertEqual(controller.chip_check()["status"], "wrong_side")

    def test_next_hand_no_uses_live_hand_not_road_length(self):
        """Cầu bị cắt (chỉ giữ 40 tay gần nhất) nhưng số tay thật vẫn phải đúng."""
        controller = self.make_controller()
        self_outer = self
        state = {"view": self_outer.view()}
        state["view"].update({"history": "B" * 40, "hand": 128,
                              "result_hand": 127, "state": "SHOW_RESULT"})

        class FakeLive:
            def snapshot(self):
                return state["view"]

        controller.live_session = FakeLive()
        self.assertEqual(controller._next_hand_no(41), 128)
        state["view"].update({"state": "BETTING", "hand": 128})
        self.assertEqual(controller._next_hand_no(41), 128)

    def test_stale_scan_does_not_roll_back_live_road(self):
        """Lượt quét bắt đầu trước khi ván mới về không được xoá tay vừa nhận."""
        controller = self.make_controller()
        self.ready(controller)
        controller.live_road = "BBPB"
        controller._ingest([{"table_id": "test", "label": "WM test",
                             "letters": "BBP", "source": "wm-ws-26"}])
        self.assertEqual(controller.tables["id:test"]["letters"], "BBPB")

    def test_auto_tick_waits_when_live_reader_is_still_on_another_table(self):
        """Vừa mở bàn mới: bộ đọc còn ở bàn cũ → chưa đặt, chờ nạp cầu bàn mới."""
        controller = self.make_controller()
        state = {"view": self.view()}
        state["view"].update({"table": "WM 101_508", "hand": 52,
                              "result_hand": 51, "state": "BETTING"})

        class FakeLive:
            def snapshot(self):
                return state["view"]

        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "B", "stake": 10})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))

        controller._auto_bet_tick()
        self.assertEqual(placed, [])
        self.assertIsNone(controller.sim.pending)
        self.assertIsNone(controller.auto_bet_letters)
        self.assertIn("chờ dữ liệu bàn mới", controller.auto_bet_note)

        # Bộ đọc bám đúng bàn: tick sau đặt ngay theo xác suất của bàn này.
        state["view"] = self.view()
        controller._auto_bet_tick()
        self.assertTrue(controller.sim.pending, controller.auto_bet_note)
        self.assertEqual(placed[0]["side"], "B")


    def test_watchdog_relaunches_dead_live_reader(self):
        """Bộ đọc live chết (CDP/mạng) phải được gắn lại thay vì bỏ mặc."""
        controller = self.make_controller()

        class Dead:
            last_error = "boom"

            def is_alive(self):
                return False

        class NewReader:
            def __init__(self):
                self.started = False

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started

        controller.live_session = object()
        controller.live_reader = Dead()
        made = []
        controller._make_live_reader = lambda session: made.append(NewReader()) or made[-1]
        controller._watch_live_reader()
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].started)
        self.assertIs(controller.live_reader, made[0])

        # Còn sống thì không tạo thêm (không gắn trùng hai bộ đọc).
        controller._watch_live_reader()
        self.assertEqual(len(made), 1)


    def test_follow_open_table_when_reader_on_another_table(self):
        """Chrome ở bàn khác bàn theo dõi: chuyển theo bàn thật, không treo chờ mãi."""
        controller = self.make_controller()
        self.ready(controller)
        state = {"view": self.view()}
        state["view"].update({"table": "WM 101_1352", "history": "BBPB",
                              "hand": 4, "result_hand": 4, "state": "SHOW_RESULT"})

        class FakeLive:
            def snapshot(self):
                return state["view"]

        controller.live_session = FakeLive()
        controller.browser.wm_open_key = "101_1352"
        controller.dispatch("bet.config", {"side": "B", "stake": 10})
        controller._follow_open_table()
        self.assertEqual(controller.sim.table_key, "id:101_1352")
        self.assertEqual(controller.sim.letters, "BBPB")
        self.assertTrue(controller.sim.running)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        controller._auto_bet_tick()
        self.assertTrue(controller.sim.pending, controller.auto_bet_note)
        self.assertEqual(placed[0]["side"], "B")

    def test_lobby_recovery_detaches_stale_table(self):
        """Chrome về sảnh/đăng nhập quá lâu: rời bàn cũ để tool tự vào lại, không treo."""
        controller = self.make_controller()
        self.ready(controller)
        controller.browser.cdp_attached = True
        controller.browser._alive_checked_at = time.monotonic()
        controller.browser._alive_ok = True
        controller.browser.wm_open_key = ""
        controller.auto_bet_note = "Đang chờ dữ liệu bàn mới từ WebSocket · chưa đặt tay nào."
        controller._recover_from_lobby()
        self.assertTrue(controller.sim.running)  # chưa quá ngưỡng
        self.assertIsNotNone(controller.lobby_since)
        controller.lobby_since = time.monotonic() - 30
        controller._recover_from_lobby()
        self.assertIsNone(controller.sim.table_key)
        self.assertFalse(controller.sim.running)
        self.assertIsNone(controller.lobby_since)
        self.assertIn("tìm bàn lại", controller.auto_bet_note)

    def test_lobby_recovery_keeps_table_while_chrome_in_table(self):
        controller = self.make_controller()
        self.ready(controller)
        controller.browser.cdp_attached = True
        controller.browser._alive_checked_at = time.monotonic()
        controller.browser._alive_ok = True
        controller.browser.wm_open_key = "test"
        controller.lobby_since = time.monotonic() - 30
        controller._recover_from_lobby()
        self.assertTrue(controller.sim.running)
        self.assertIsNone(controller.lobby_since)

    def test_paused_sim_in_lobby_detaches_and_reenters(self):
        """Sim pause + vẫn bám bàn + Chrome về sảnh: phải rời bàn để tool vào lại."""
        controller = self.make_controller()
        self.ready(controller)
        controller.sim.pause("Dữ liệu quá 45 giây chưa cập nhật.")
        controller.browser.cdp_attached = True
        controller.browser._alive_checked_at = time.monotonic()
        controller.browser._alive_ok = True
        controller.browser.wm_open_key = ""
        controller.lobby_since = time.monotonic() - 30
        controller._recover_from_lobby()
        self.assertIsNone(controller.sim.table_key)
        self.assertFalse(controller.sim.running)

    def test_paused_sim_resumes_when_chrome_back_in_same_table(self):
        controller = self.make_controller()
        row = self.ready(controller)
        controller.sim.pause("Dữ liệu quá 45 giây chưa cập nhật.")
        controller.browser.cdp_attached = True
        controller.browser._alive_checked_at = time.monotonic()
        controller.browser._alive_ok = True
        controller.browser.wm_open_key = "test"
        controller._recover_from_lobby()
        self.assertTrue(controller.sim.running)
        self.assertEqual(controller.sim.table_key, row["key"])

    def test_root_left_site_is_session_loss_and_clears_wait_note(self):
        """Tab bị đẩy sang trang đăng nhập: dừng đặt + xoá ghi chú 'chờ WS' gây hiểu lầm."""
        controller = self.make_controller()
        self.ready(controller)
        controller.browser.last_diag = {"reason": "root_left_site"}
        self.assertTrue(controller._auth_blame())
        controller.auto_bet_note = "Đang chờ dữ liệu bàn mới từ WebSocket · chưa đặt tay nào."
        controller._try_recover_session = lambda: None
        controller._session_lost("Tab bị đẩy sang trang đăng nhập.")
        self.assertTrue(controller.session_lost)
        self.assertFalse(controller.sim.running)
        self.assertIsNone(controller.auto_bet_letters)
        self.assertIn("Mất phiên đăng nhập", controller.auto_bet_note)


    def test_auto_tick_does_not_arm_a_backwards_hand(self):
        """Lịch sử/phát lại về muộn báo tay cũ hơn tay đã chốt: không đặt trùng."""
        controller = self.make_controller()
        state = {"view": self.view()}
        state["view"].update({"state": "BETTING", "hand": 13, "result_hand": 12})

        class FakeLive:
            def snapshot(self):
                return state["view"]

        controller.live_session = FakeLive()
        controller.dispatch("bet.config", {"side": "B", "stake": 10})
        self.ready(controller)
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        controller._auto_bet_tick()
        self.assertEqual(len(placed), 1)
        self.assertEqual(controller.auto_bet_hand, 13)

        # Cầu đổi (ván mới về) nhưng số tay live lùi về 12: phải chặn, không arm lại.
        controller.sim.pending = None
        controller.sim.letters = "BBPBBPB"
        state["view"].update({"state": "SHOW_RESULT", "hand": 12, "result_hand": 11})
        controller._auto_bet_tick()
        self.assertEqual(len(placed), 1)
        self.assertIn("đã được xử lý", controller.auto_bet_note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
