# -*- coding: utf-8 -*-
"""Kiểm thử engine JSON của Electron (aibcr/service/engine.py).

Không cần Chrome: bàn/Chrome được thay bằng đối tượng giả. Mục tiêu là khoá lại hợp
đồng giữa UI Electron và tiến trình Python của AI_BCR:

    - chỉ có một dịch vụ Baccarat, dispatch đúng method, method lạ báo lỗi
    - nút “VÀO BÀN HỢP LỆ” tìm + mở + xác nhận bàn nhưng KHÔNG đặt cược
    - vào bàn đầu tiên có mã, không lọc cầu; lệnh cược do UI/AI chốt từng tay
    - đóng Chrome bằng tay thì app thấy mất kết nối và còn đường mở lại
"""

import json
import pathlib
import threading
import tempfile
import time
import unittest

from aibcr.adapters import browser as BR
from aibcr.service import engine


class FakeEmitter:
    def __init__(self):
        self.events = []

    def event(self, name, data):
        self.events.append((name, data))

    def reply(self, request_id, result=None, error=None):
        self.events.append(("reply", {"id": request_id, "result": result, "error": error}))

    def send(self, payload):
        self.events.append(("send", payload))


def make_service(config=None, letters=None, now=None, source="evo-ws"):
    """Dịch vụ Baccarat với Chrome giả đang kết nối và một bàn đã đọc được."""
    folder = pathlib.Path(tempfile.mkdtemp())
    service = engine.BaccaratService(folder / "state.json", FakeEmitter())
    if config:
        result = service.config_set(config)
        assert result.get("ok"), result
    service.browser = type("FakeBrowser", (), {
        "connected": True, "note": "", "mode": "cdp", "cdp_attached": True,
        "stop": lambda self: None,
    })()
    if letters is not None:
        stamp = now if now is not None else time.time()
        service.tables = {"id:t1": {
            "key": "id:t1", "label": "Bàn 1", "letters": letters, "ts": stamp,
            "table_id": "t1", "game_type": "", "read_error": "", "source": source,
            "conflict": False, "stable": 3, "screen_stable": 3,
            "ws_confirmed_letters": letters,
        }}
    return service


class DispatchTests(unittest.TestCase):
    def test_bet_ladder_config_is_clamped_and_persisted(self):
        service = make_service()
        reply = service.bet_ladder_config_set({
            "stakes": "5 30 60", "min_t": 20, "max_t": 50,
            "min_tk": 4, "total_bet": 1200, "hop_min": "3 4 2",
            "hop_max": 2, "side": "B",
        })
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["stake"], 20)
        self.assertEqual(service.config["min_tk"], 4)
        self.assertEqual(service.config["hop_rounds"], [3, 4, 2])
        self.assertEqual(service.config["hop_max"], 2)

    def test_verified_bet_result_advances_the_configured_ladder(self):
        service = make_service()
        service.bet_ladder_config_set({"stakes": "10 20 30", "min_t": 1,
                                       "max_t": 100, "side": "P"})
        self.assertEqual(service.bet_ladder_result({"outcome": "LOSS"})["stake"], 20)
        self.assertEqual(service.bet_ladder_result({"outcome": "PUSH"})["stake"], 20)
        self.assertEqual(service.bet_ladder_result({"outcome": "WIN"})["stake"], 10)
        self.assertFalse(service.bet_ladder_result({"outcome": "UNKNOWN"})["ok"])

    def test_ping_and_state_are_answered(self):
        service = make_service()
        result, error = engine.dispatch(service, "ping", {})
        self.assertIsNone(error)
        self.assertTrue(result["pong"])
        self.assertEqual(result["game"], "baccarat")
        snapshot, error = engine.dispatch(service, "state", {})
        self.assertIsNone(error)
        self.assertEqual(snapshot["game"], "baccarat")
        self.assertFalse(snapshot["tool_running"])

    def test_unknown_method_reports_an_error(self):
        service = make_service()
        result, error = engine.dispatch(service, "khong.co", {})
        self.assertIsNone(result)
        self.assertIn("không hỗ trợ", error)

    def test_only_baccarat_is_supported(self):
        emit = FakeEmitter()
        baccarat = engine.build_service("baccarat", emit,
                                       pathlib.Path(tempfile.mkdtemp()) / "b.json")
        self.assertIsInstance(baccarat, engine.BaccaratService)
        with self.assertRaises(SystemExit):
            engine.build_service("longlong", emit,
                                 pathlib.Path(tempfile.mkdtemp()) / "l.json")

    def test_dispatch_exposes_the_enter_valid_command(self):
        """UI chỉ gọi đúng một lệnh để vào bàn hợp lệ."""
        service = make_service()
        methods = []
        service.enter_valid_table = lambda: methods.append("enter") or {"ok": True}
        reply, error = engine.dispatch(service, "table.enterValid", {})
        self.assertIsNone(error)
        self.assertTrue(reply["ok"])
        self.assertEqual(methods, ["enter"])

    def test_dispatch_exposes_cancel_enter_valid(self):
        service = make_service()
        methods = []
        service.cancel_enter_valid = lambda: methods.append("cancel") or {"ok": True}
        reply, error = engine.dispatch(service, "table.cancelEnter", {})
        self.assertIsNone(error)
        self.assertTrue(reply["ok"])
        self.assertEqual(methods, ["cancel"])

    def test_dispatch_exposes_bet_and_key_commands_without_leaking_the_key(self):
        service = make_service()
        reply, error = engine.dispatch(service, "bet.config", {"side": "B", "stake": 180})
        self.assertIsNone(error)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(service.bet_config, {"side": "B", "stake": 180.0})

        reply, error = engine.dispatch(service, "ai.key.set", {"key": "dummy-ram-only"})
        self.assertIsNone(error)
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["has_key"])

        snapshot, error = engine.dispatch(service, "state", {})
        self.assertIsNone(error)
        self.assertNotIn("dummy-ram-only", json.dumps(snapshot, ensure_ascii=False))
        service._save_state()
        saved = service.state_path.read_text(encoding="utf-8")
        self.assertNotIn("dummy-ram-only", saved)

    def test_bet_place_refuses_before_a_table_is_chosen(self):
        service = make_service()
        reply, error = engine.dispatch(service, "bet.place", {})
        self.assertIsNone(error)
        self.assertFalse(reply["ok"])
        self.assertIn("VÀO BÀN", reply["error"])


class ConfigTests(unittest.TestCase):
    def test_site_open_updates_selected_url_on_an_existing_profile(self):
        service = make_service()
        visited = []
        service.browser.navigate = lambda url: (visited.append(url) or (True, "opened"))
        url = "https://example.com/account"
        result, error = service.dispatch("site.open", {"url": url})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertEqual(visited, [url])
        self.assertEqual(service.config["start_url"], url)

    def test_site_open_rejects_non_https_url(self):
        service = make_service()
        result, error = service.dispatch("site.open", {"url": "file:///secret"})
        self.assertIsNone(error)
        self.assertFalse(result["ok"])

    def test_legacy_auto_side_disables_auto_place(self):
        service = make_service()
        migrated = service._normalize_config({**service.config, "bet_side": "AUTO",
                                              "auto_place": True})
        self.assertEqual(migrated["bet_side"], "P")
        self.assertFalse(migrated["auto_place"])

    def test_config_set_persists_the_per_hand_bet_order(self):
        service = make_service()
        reply = service.config_set({"bet_side": "P", "bet_stake": 250.5})
        self.assertTrue(reply["ok"], reply)
        saved = json.loads(service.state_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved["bet_side"], "P")
        self.assertEqual(saved["bet_stake"], 250.5)
        self.assertEqual(service.bet_config, {"side": "P", "stake": 250.5})

    def test_removed_method_config_is_never_saved(self):
        service = make_service()
        reply = service.config_set({
            "profile": "3-3", "ladder": [100, 300], "ladder_mode": "multiply",
            "ladder_base": 100, "block_mode": "repeat", "live_exit_streak": 9,
            "auto_cycle": True,
        })
        self.assertTrue(reply["ok"], reply)
        saved = json.loads(service.state_path.read_text(encoding="utf-8"))["settings"]
        for key in ("profile", "ladder", "ladder_mode", "ladder_base", "block_mode",
                    "live_exit_streak", "auto_cycle", "min_hands", "max_streak",
                    "min_lead"):
            self.assertNotIn(key, saved)
            self.assertNotIn(key, service.config)

    def test_removed_filter_keys_are_ignored(self):
        service = make_service()
        reply = service.config_set({"min_hands": 20, "max_streak": 2, "min_lead": 5,
                                    "max_lead": 3, "tie_side": "P"})
        self.assertTrue(reply["ok"], reply)
        for key in ("min_hands", "max_hands", "max_streak", "min_lead", "max_lead",
                    "tie_side"):
            self.assertNotIn(key, service.config)

    def test_invalid_start_url_falls_back_to_the_default(self):
        service = make_service()
        reply = service.config_set({"start_url": "khong-phai-link"})
        self.assertTrue(reply.get("ok"), reply)
        self.assertTrue(service.config["start_url"].startswith("http"))

    def test_window_is_clamped_and_persisted(self):
        service = make_service()
        reply = service.apply_window({"width": 99999, "height": 10, "percent": 500,
                                      "fullscreen": True})
        self.assertTrue(reply["ok"])
        window = service.config["chrome_window"]
        self.assertTrue(window["fullscreen"])
        self.assertEqual(window["width"], BR.SIZE_MAX[0])
        self.assertEqual(window["height"], BR.SIZE_MIN[1])
        self.assertEqual(window["percent"], BR.SCALE_MAX)
        saved = json.loads(service.state_path.read_text(encoding="utf-8"))["settings"]
        self.assertEqual(saved["chrome_window"], window)


class ToolLifecycleTests(unittest.TestCase):
    def test_tool_starts_even_without_chrome_by_hunting_a_table(self):
        """Bật tool là tự vào bàn hợp lệ: thiếu Chrome thì luồng vào bàn tự gắn/mở."""
        service = make_service()
        service.browser = type("FakeBrowser", (), {
            "connected": False, "note": "", "mode": "cdp", "cdp_attached": False,
            "attach": lambda self: False, "stop": lambda self: None,
        })()
        service.enter_valid_table = lambda: {"ok": True, "note": "hunting"}
        result = service.tool_start()
        self.assertTrue(result["ok"], result)
        self.assertTrue(service.tool_running)


class BaccaratEnterValidTests(unittest.TestCase):
    """Nút duy nhất “VÀO BÀN HỢP LỆ”: tìm + mở + xác nhận nhưng KHÔNG cược."""

    # 22 tay: B 13 · P 9 (lệch 4), không bệt quá 3 — chỉ là cầu mẫu cho pipeline.
    VALID = "".join(side * count for side, count in (
        ("B", 3), ("P", 2), ("B", 3), ("P", 2), ("B", 2),
        ("P", 3), ("B", 2), ("P", 2), ("B", 3)))

    def service(self, letters=None, config=None):
        return make_service(config=config, letters=letters or self.VALID, source="evo-bead")

    def test_live_reader_switches_to_wm_when_chrome_navigates_there(self):
        from unittest.mock import patch
        from aibcr.controllers import baccarat as BC

        service = self.service()

        class FakeReader:
            def __init__(self):
                self.started = False
                self.alive = True

            def is_alive(self):
                return self.alive

            def start(self):
                self.started = True

            def join(self, timeout=None):
                self.alive = False

        old_reader, new_reader = FakeReader(), FakeReader()
        old_stop = threading.Event()
        service.live_session = object()
        service.live_reader = old_reader
        service.live_stop_event = old_stop
        service.live_reader_probe_at = 0
        service._make_live_reader = lambda _session, wm_detected=None: new_reader
        with patch.object(BC, "find_wm_page", return_value=({"id": "wm"}, {"kind": "table"})):
            service._refresh_live_reader_kind()

        self.assertTrue(old_stop.is_set())
        self.assertIs(service.live_reader, new_reader)
        self.assertTrue(new_reader.started)

    def prime(self, service, letters=None):
        """Giả lập: đã bấm ô bàn và cầu trong bàn đã xác nhận cùng shoe."""
        letters = service.tables["id:t1"]["letters"] if letters is None else letters
        service.enter_valid = True
        service.valid_check_done = False
        service.auto_start_key = "id:t1"
        service.auto_start_letters = letters
        service.auto_start_deadline = time.time() + 60

    def test_enter_valid_binds_the_table_without_starting_a_session(self):
        service = self.service()
        self.prime(service)
        service._auto_start_verified_table()
        self.assertTrue(service.valid_check_done)
        self.assertFalse(service.enter_valid)
        self.assertEqual(service.sim.table_key, "id:t1")
        self.assertFalse(service.sim.running, "chưa bật tool thì chưa chạy phiên")
        self.assertIsNone(service.sim.pending, "chưa được chốt lệnh cược")
        self.assertFalse(service.place_busy, "không được đặt chip")
        self.assertIn("CHƯA đặt cược", service.valid_note)

    def test_enter_valid_accepts_any_road_inside_the_table(self):
        """Không còn điều kiện cùng shoe: cầu trong bàn khác sảnh vẫn vào bình thường."""
        service = self.service()
        self.prime(service, letters="PPPBBB")
        service._auto_start_verified_table()
        self.assertTrue(service.valid_check_done)
        self.assertIsNone(service.auto_start_key)
        self.assertEqual(service.sim.table_key, "id:t1")
        self.assertFalse(service.sim.running)

    def test_tool_start_tracks_the_verified_table(self):
        service = self.service()
        self.prime(service)
        service._auto_start_verified_table()
        reply = service.tool_start()
        self.assertTrue(reply["ok"])
        self.assertTrue(service.sim.running)
        # Theo dõi ngay; cửa sổ cược vẫn được bảo vệ bởi gate chờ bàn dọn chip
        # (`_wait_for_next_hand`) trước khi bấm chip thật.
        self.assertFalse(service.sim.entry_waiting)
        self.assertIsNone(service.sim.pending)

    def test_enter_valid_hunts_without_the_tool(self):
        service = self.service()
        service.enter_valid = True
        called = []
        service.open_table = lambda key: called.append(key) or {"ok": True}
        service.auto_open_table(allow_sweep=False)
        self.assertEqual(called, ["id:t1"], "phải mở bàn đạt chuẩn dù tool chưa chạy")

    def test_auto_hunt_alone_still_needs_the_tool(self):
        service = self.service()
        called = []
        service.open_table = lambda key: called.append(key) or {"ok": True}
        service.auto_open_table(allow_sweep=False)
        self.assertEqual(called, [], "không bật tool thì không tự mở bàn")

    def test_enter_valid_binds_a_wm_table_already_open(self):
        """Mở lại app khi tab vẫn ở trong bàn WM: theo bàn đó, không quét sảnh."""
        from aibcr.controllers import baccarat as BC

        service = self.service()
        reports = [{"page": {"title": "WM"}, "tables": [{
            "table_id": "101_1353", "label": "EIPRIL V", "letters": "BPPB",
            "game_type": "baccarat", "read_error": "", "source": "wm-ws-26",
            "ws_hands": 4, "road_match": True}]}]

        class FakeBrowser:
            connected = True
            mode = "cdp"
            cdp_attached = True
            wm_open_key = "101_1353"

            def scan(self):
                return reports

            def stop(self):
                pass

        lobbies = []

        class FakeStream:
            def find_lobby_tab(self):
                lobbies.append(True)
                return True, "sảnh"

        service.browser = FakeBrowser()
        service.stream = FakeStream()
        original = BC.find_wm_table
        BC.find_wm_table = lambda port=9222: ({"id": "p"}, {"kind": "table"})
        self.addCleanup(setattr, BC, "find_wm_table", original)

        service.tool_running = True
        reply = service.enter_valid_table()
        self.assertTrue(reply["ok"], reply)
        deadline = time.time() + 3
        while time.time() < deadline and not service.auto_start_key:
            service._drain()
            time.sleep(0.02)
        self.assertEqual(service.auto_start_key, "id:101_1353")
        self.assertEqual(lobbies, [], "đang trong bàn thì không được quét sảnh")

        service._auto_start_verified_table()
        self.assertEqual(service.sim.table_key, "id:101_1353")
        self.assertTrue(service.sim.running)

    def test_cancel_enter_valid_stops_the_hunt(self):
        service = self.service()
        service.enter_valid = True
        service.cycle_waiting = True
        reply = service.cancel_enter_valid()
        self.assertTrue(reply["ok"])
        self.assertFalse(service.enter_valid)
        self.assertFalse(service.cycle_waiting)
        self.assertIn("huỷ", service.valid_note.casefold())

    def test_enter_valid_times_out(self):
        service = self.service()
        service.enter_valid = True
        service.enter_deadline = time.time() - 1
        service._watch_enter_valid(time.time())
        self.assertFalse(service.enter_valid)
        self.assertFalse(service.cycle_waiting)
        self.assertIn("Chưa vào được bàn", service.valid_note)

    def test_snapshot_exposes_enter_valid_state(self):
        service = self.service()
        service.enter_valid = True
        service.enter_deadline = time.time() + 30
        block = service.snapshot()["enter_valid"]
        self.assertTrue(block["active"])
        self.assertFalse(block["checked"])
        self.assertGreater(block["remain"], 0)

    def test_tool_start_without_chrome_enters_valid_flow(self):
        service = self.service()
        service.browser = type("FakeBrowser", (), {
            "connected": False, "note": "", "mode": "cdp", "cdp_attached": False,
            "attach": lambda self: False, "stop": lambda self: None,
        })()
        reply = service.tool_start()
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(service.tool_running)
        self.assertTrue(service.enter_valid, "bật tool phải tự tìm bàn hợp lệ")
        service.cancel_enter_valid()


class BaccaratEngineTests(unittest.TestCase):
    def test_scan_maps_browser_reports_to_rows(self):
        service = make_service()
        service.browser = type("FakeBrowser", (), {
            "connected": True,
            "scan": lambda self: [{"tables": [{"id": "t1", "title": "Bàn 1",
                                               "letters": "BBBPPP"}]}],
        })()
        snapshot = service.scan()
        self.assertEqual(snapshot["tables"][0]["id"], "t1")
        self.assertEqual(snapshot["tables"][0]["letters"], "BBBPPP")


class BaccaratNoFilterTests(unittest.TestCase):
    """Không còn điều kiện vào bàn: mọi cầu đều được nhận và vào bàn đầu tiên có mã."""

    @staticmethod
    def road(*runs):
        """Ghép cầu từ các vệt (ký tự, số tay) để dễ kiểm soát số B/P và bệt."""
        return "".join(side * count for side, count in runs)

    # B 13 · P 9, không bệt quá 3 tay, không có hai vệt 3 liền nhau.
    LEAD4 = road(("B", 3), ("P", 2), ("B", 3), ("P", 2), ("B", 2), ("P", 3),
                 ("B", 2), ("P", 2), ("B", 3))
    # B 20 · P 10 (lệch 10) — trước đây bị loại vì vượt mức tối đa.
    LEAD10 = road(("B", 3), ("P", 2), ("B", 2), ("P", 1), ("B", 3), ("P", 2),
                  ("B", 2), ("P", 1), ("B", 3), ("P", 2), ("B", 2), ("P", 1),
                  ("B", 3), ("P", 1), ("B", 2))
    # Bệt 6 tay liền — trước đây bị loại vì vượt bệt tối đa.
    STREAK = "BBBBBB" + "PPBBPPBBPPBBPPBB" + "PPBB"
    # Hoà điểm B 8 · P 8.
    TIE = road(("B", 2), ("P", 3), ("B", 2), ("P", 2), ("B", 2), ("P", 2),
               ("B", 2), ("P", 1))

    def service(self, letters):
        return make_service(letters=letters)

    def test_any_road_is_accepted(self):
        for letters in (self.LEAD4, self.LEAD10, self.STREAK):
            row = self.service(letters).table_rows()[0]
            self.assertTrue(row["eligible"], row["verdict"])
            self.assertEqual(row["verdict"], "Sẵn sàng vào bàn")

    def test_tie_prefers_red_banker(self):
        row = self.service(self.TIE).table_rows()[0]
        self.assertEqual((row["banker"], row["player"], row["lead"]), (8, 8, 0))
        self.assertTrue(row["tie_break"])
        self.assertEqual(row["strong"], "B")
        self.assertTrue(row["eligible"])

    def test_auto_open_takes_the_first_table_with_an_id(self):
        service = make_service()
        service.tool_running = True
        stamp = time.time()
        service.tables = {
            "id:first": {"key": "id:first", "label": "Bàn bệt", "letters": self.STREAK,
                         "ts": stamp, "table_id": "first", "game_type": "",
                         "read_error": "", "source": "evo-bead", "conflict": False,
                         "stable": 1, "screen_stable": 1, "ws_confirmed_letters": ""},
            "id:second": {"key": "id:second", "label": "Bàn đẹp", "letters": self.LEAD4,
                          "ts": stamp, "table_id": "second", "game_type": "",
                          "read_error": "", "source": "evo-bead", "conflict": False,
                          "stable": 3, "screen_stable": 3, "ws_confirmed_letters": self.LEAD4},
        }
        opened = []
        service.open_table = lambda key: opened.append(key) or {"ok": True}
        service.auto_open_table()
        self.assertEqual(opened, ["id:first"])

    def test_new_session_keeps_the_bet_order(self):
        service = self.service(self.LEAD4)
        self.assertTrue(service.session_new({"capital": 2500, "bet_side": "T",
                                             "bet_stake": 75})["ok"])
        self.assertEqual(service.bet_config, {"side": "T", "stake": 75.0})
        self.assertEqual(service.sim.money.unit, 75.0)


class ChromeClosedRecoveryTests(unittest.TestCase):
    """Đóng Chrome bằng tay: app phải thấy mất kết nối và còn đường mở lại."""

    @staticmethod
    def fake_browser(connected=False, note=""):
        return type("FakeBrowser", (), {"connected": connected, "note": note,
                                        "mode": "cdp" if connected else "",
                                        "stop": lambda self: None})()

    def baccarat(self):
        now = time.time()
        service = make_service(letters="BBBP")
        service.tables["id:t1"]["ts"] = now
        service.tool_running = True
        return service

    def test_clears_tables_and_pauses_when_chrome_closes(self):
        service = self.baccarat()
        service.browser = self.fake_browser(connected=True)
        service._on_chrome_lost()
        self.assertEqual(service.tables, {})
        self.assertIn("Mở Chrome", service.sweep_note)
        self.assertTrue(service.offline_noted)

    def test_snapshot_reports_disconnected(self):
        service = self.baccarat()
        service.browser = self.fake_browser(connected=False, note="Chrome đã đóng")
        snapshot = service.snapshot()
        self.assertFalse(snapshot["chrome_connected"])
        self.assertEqual(snapshot["tables"], [])
        self.assertEqual(snapshot["chrome_note"], "Chrome đã đóng")

    def test_ready_flag_resets_after_reconnect(self):
        service = self.baccarat()
        service._on_chrome_lost()
        self.assertTrue(service.offline_noted)
        service._on_chrome_ready()
        self.assertFalse(service.offline_noted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
