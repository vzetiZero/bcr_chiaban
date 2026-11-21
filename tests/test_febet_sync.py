# -*- coding: utf-8 -*-
"""Test đồng bộ bàn DG qua tableId và lọc iframe widget của FEBET."""

import json
import re
import unittest

from aibcr.adapters import febet as F


class FakeSwitch:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        pass

    def default_content(self):
        self.driver.frame = None

    def frame(self, element):
        self.driver.frame = element


LOBBY = "https://febet.kiwi/live-casino/baccarat"
DG_LOC = ("https://new-dd-cloudfront.example.com/ddnewpc/index.html"
          "?token=SECRET&language=vi&tableId=60101&backUrl=https%3A%2F%2Ffebet.kiwi")
DG_HALL_LOC = DG_LOC.replace("tableId=60101", "tableId=10101")
DG_SRC = ("https://new-dd-cloudfront.example.com/ddnewpc/direct1.html"
          "?token=SECRET&language=vi&tableId=60101")


class FakeDriver:
    """Frame 0 = widget, frame 1 = DG; src giữ URL loader, location là trang thật."""

    redirect = True  # mô phỏng direct1.html redirect sang index.html

    def __init__(self, url, dg_location, src_value=DG_SRC):
        self.window_handles = ["w1"]
        self.current_url = url
        self.switch_to = FakeSwitch(self)
        self.frame = None
        self.frames = ["widget", "dg"]
        self.dg_location = dg_location
        self.src_value = src_value
        self.src_attr = ""
        self.scripts = []

    def find_elements(self, by, selector):
        return list(self.frames)

    def execute_script(self, js, *args):
        self.scripts.append(js)
        if "return location.href" in js:
            return self.dg_location if self.frame == "dg" else "https://secure.livechatinc.com/x"
        if "typeof Laya" in js and "tableInfo || n._tableInfo" in js:
            return {"ready": True, "tables": [
                {"table_id": "60101", "name": "RB01", "online": 10}]}
        if "typeof Laya" in js:
            table = re.search(r"tableId=(\d+)", self.dg_location)
            is_hall = bool(table and table.group(1) == "10101")
            return {"ready": True, "lobby": "direct1" in self.dg_location or is_hall,
                    "in_table": "index.html" in self.dg_location and not is_hall,
                    "label": "RB01", "url_table": table.group(1) if table else ""}
        if "getAttribute('src')" in js:
            return self.src_value
        if js.startswith("location.href ="):
            url = json.loads(js.split("=", 1)[1].strip().rstrip(";"))
            self.current_url = url
            if self.redirect:
                self.dg_location = url.replace("direct1.html", "index.html")
            return None
        if "f.src =" in js:
            self.src_attr = js
            if self.redirect:
                url = json.loads(re.search(r'f\.src = (".*?");', js).group(1))
                self.dg_location = url.replace("direct1.html", "index.html")
            return {"ok": True}
        return None


class WidgetOriginTest(unittest.TestCase):
    def test_widgets_excluded(self):
        for origin in ("https://secure.livechatinc.com", "https://www.google.com",
                       "https://www.gstatic.com", "https://tawk.to"):
            self.assertTrue(F._is_widget_origin(origin), origin)

    def test_game_origin_kept(self):
        self.assertFalse(F._is_widget_origin("https://new-dd-cloudfront.ywjxi.com"))
        self.assertFalse(F._is_widget_origin("https://new-dd-cn.dingdangmail.com"))

    def test_empty_origin_is_widget(self):
        self.assertTrue(F._is_widget_origin(""))


class ChipSequenceTest(unittest.TestCase):
    def test_finds_exact_minimum_chip_count(self):
        self.assertEqual(F.exact_chip_sequence(125, [100, 50, 25, 10]), [100, 25])

    def test_rejects_unrepresentable_or_unsafe_amounts(self):
        self.assertEqual(F.exact_chip_sequence(17, [10, 5]), [])
        self.assertEqual(F.exact_chip_sequence(10001, [500, 100, 10, 1]), [])

    def test_rejects_empty_or_invalid_denominations(self):
        self.assertEqual(F.exact_chip_sequence(20, []), [])
        self.assertEqual(F.exact_chip_sequence(20, [0, -10, "bad"]), [])


class CurrentTableTest(unittest.TestCase):
    def test_only_confirmed_60xxx_ids_are_real_tables(self):
        self.assertTrue(F._is_real_table_id("60101"))
        self.assertTrue(F._is_real_table_id("60102"))
        for hall_id in ("10101", "10102", "601", "6010", "70101"):
            self.assertFalse(F._is_real_table_id(hall_id), hall_id)

    def test_reads_table_id_from_frame_location(self):
        result = F.current_table(FakeDriver(LOBBY, DG_LOC))
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "60101")
        self.assertNotIn("SECRET", str(result))

    def test_hall_id_is_never_reported_as_an_open_table(self):
        url = DG_LOC.replace("tableId=60101", "tableId=10101")
        result = F.current_table(FakeDriver(LOBBY, url))
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "10101")
        self.assertFalse(result["in_table"])
        self.assertTrue(result["lobby"])

    def test_no_driver(self):
        self.assertFalse(F.current_table(None)["ok"])

    def test_no_dg_frame(self):
        driver = FakeDriver(LOBBY, "https://febet.kiwi/other")
        self.assertFalse(F.current_table(driver, wait=0)["ok"])

    def test_loader_without_table_id_waits_then_fails(self):
        driver = FakeDriver(LOBBY, "https://x.example.com/ddnewpc/direct1.html?token=SECRET")
        result = F.current_table(driver, wait=0)
        self.assertFalse(result["ok"])

    def test_same_dg_frame_works_from_another_site_host(self):
        driver = FakeDriver("https://m.gk881.vip/", DG_LOC)
        result = F.current_table(driver, wait=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "60101")


class MultiSiteDGEntryTest(unittest.TestCase):
    def test_non_febet_sites_reuse_an_already_open_dg_lobby(self):
        for site_id in ("e3951", "gk881", "vnwtop", "888ae66", "bum123"):
            with self.subTest(site_id=site_id):
                result = F.open_dg_for_site(FakeDriver("https://m.gk881.vip/", DG_LOC),
                                            site_id, wait=0)
                self.assertTrue(result["ok"])
                self.assertTrue(result["lobby_ready"])
                self.assertEqual(result["site_id"], site_id)

    def test_unknown_site_does_not_try_a_generic_click(self):
        result = F.open_dg_for_site(FakeDriver("https://m.gk881.vip/", DG_LOC),
                                    "unknown", wait=0)
        self.assertFalse(result["ok"])


class SyncTableTest(unittest.TestCase):
    def test_rejects_invalid_ids(self):
        driver = FakeDriver(LOBBY, DG_LOC)
        for bad in ("", "abc", "10101", "10102", "10101;alert(1)", "1" * 13, "10 101", "-1"):
            result = F.sync_table(driver, bad)
            self.assertFalse(result["ok"], bad)
        self.assertEqual(driver.scripts, [])

    def test_sets_table_id_keeps_token_inside_page(self):
        driver = FakeDriver(LOBBY, DG_LOC)
        result = F.sync_table(driver, "60102", settle=5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "60102")
        self.assertIn("tableId=60102", driver.src_attr)
        self.assertIn("token=SECRET", driver.src_attr)  # token giữ lại trong trang
        self.assertNotIn("SECRET", str(result))         # nhưng không lộ ra kết quả
        self.assertIn("[1]", driver.src_attr)           # đúng iframe DG
        # Selenium execute_script cần "return", nếu không kết quả luôn là None.
        self.assertTrue(driver.src_attr.startswith("return "))
        # Phải đi qua loader direct1.html; gán thẳng index.html làm game thoát iframe.
        self.assertIn("direct1.html", driver.src_attr)
        self.assertIn("index.html", driver.dg_location)
        self.assertIn("tableId=60102", driver.dg_location)

    def test_empty_src_falls_back_to_loader_from_location(self):
        driver = FakeDriver(LOBBY, DG_LOC, src_value="")
        result = F.sync_table(driver, "60102", settle=5)
        self.assertTrue(result["ok"])
        self.assertIn("direct1.html", driver.src_attr)

    def test_reports_error_when_game_never_lands(self):
        class NoRedirect(FakeDriver):
            redirect = False

        driver = NoRedirect(LOBBY, DG_LOC)
        result = F.sync_table(driver, "60102", settle=0)
        self.assertFalse(result["ok"])

    def test_no_dg_frame_reports_error(self):
        driver = FakeDriver(LOBBY, "https://febet.kiwi/other")
        self.assertFalse(F.sync_table(driver, "60101", wait=0)["ok"])

    def test_same_table_skips_reload(self):
        driver = FakeDriver(LOBBY, DG_LOC)
        result = F.sync_table(driver, "60101")
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("already"))
        self.assertTrue(result.get("in_table"))
        self.assertNotIn("f.src =", "".join(driver.scripts))

    def test_same_url_id_still_reloads_when_laya_says_lobby(self):
        hall_url = DG_LOC.replace("tableId=60101", "tableId=60102")
        driver = FakeDriver(LOBBY, hall_url)
        driver.dg_location = hall_url.replace("index.html", "direct1.html")
        result = F.sync_table(driver, "60102", settle=5)
        self.assertTrue(result["ok"])
        self.assertTrue(result["in_table"])
        self.assertIn("f.src =", "".join(driver.scripts))

    def test_tab_mode_navigates_loader(self):
        driver = FakeDriver(DG_LOC, DG_LOC)
        result = F.sync_table(driver, "60102", settle=5)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("in_table"))
        self.assertTrue(any(js.startswith("location.href =") for js in driver.scripts))
        self.assertIn("direct1.html", driver.current_url)

    def test_lobby_tables_reads_laya_cards(self):
        driver = FakeDriver(LOBBY, DG_HALL_LOC)
        result = F.lobby_tables(driver)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tables"][0]["table_id"], "60101")
        self.assertEqual(result["tables"][0]["name"], "RB01")

    def test_lobby_scan_waits_for_laya_cards_and_filters_hall_id(self):
        class DelayedTables(FakeDriver):
            reads = 0

            def execute_script(self, js, *args):
                if "tableInfo || n._tableInfo" in js:
                    self.reads += 1
                    if self.reads < 3:
                        return {"ready": False, "tables": []}
                    return {"ready": True, "tables": [
                        {"table_id": "10101", "name": "Lobby"},
                        {"table_id": "10102", "name": "False RB02"},
                        {"table_id": "60101", "name": "RB01", "online": 10},
                        {"table_id": "60101", "name": "RB01", "online": 10}]}
                return super().execute_script(js, *args)

        result = F.lobby_tables(DelayedTables(LOBBY, DG_HALL_LOC), wait=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tables"], [
            {"table_id": "60101", "name": "RB01", "online": 10}])


if __name__ == "__main__":
    unittest.main()
