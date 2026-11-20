# -*- coding: utf-8 -*-
"""Test đồng bộ bàn DG qua tableId và lọc iframe widget của FEBET."""

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


class FakeDriver:
    """Frame 0 = widget, frame 1 = DG (location thật khác thuộc tính src)."""

    def __init__(self, url, dg_location, src_attr="about:blank"):
        self.window_handles = ["w1"]
        self.current_url = url
        self.switch_to = FakeSwitch(self)
        self.frame = None
        self.frames = ["widget", "dg"]
        self.dg_location = dg_location
        self.src_attr = src_attr
        self.scripts = []

    def find_elements(self, by, selector):
        return list(self.frames)

    def execute_script(self, js, *args):
        self.scripts.append(js)
        if "return location.href" in js:
            return self.dg_location if self.frame == "dg" else "https://secure.livechatinc.com/x"
        if "f.src =" in js:
            self.src_attr = js
            return {"ok": True}
        return None


LOBBY = "https://febet.kiwi/live-casino/baccarat"
DG_LOC = ("https://new-dd-cloudfront.example.com/ddnewpc/index.html"
          "?token=SECRET&language=vi&tableId=10101&backUrl=https%3A%2F%2Ffebet.kiwi")


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


class CurrentTableTest(unittest.TestCase):
    def test_reads_table_id_from_frame_location(self):
        result = F.current_table(FakeDriver(LOBBY, DG_LOC))
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "10101")
        self.assertNotIn("SECRET", str(result))

    def test_no_driver(self):
        self.assertFalse(F.current_table(None)["ok"])

    def test_no_dg_frame(self):
        driver = FakeDriver(LOBBY, "https://febet.kiwi/other")
        self.assertFalse(F.current_table(driver, wait=0)["ok"])

    def test_loader_without_table_id_waits_then_fails(self):
        driver = FakeDriver(LOBBY, "https://x.example.com/ddnewpc/direct1.html?token=SECRET")
        result = F.current_table(driver, wait=0)
        self.assertFalse(result["ok"])

    def test_not_lobby(self):
        self.assertFalse(F.current_table(FakeDriver("https://febet.kiwi/login", DG_LOC), wait=0)["ok"])


class SyncTableTest(unittest.TestCase):
    def test_rejects_invalid_ids(self):
        driver = FakeDriver(LOBBY, DG_LOC)
        for bad in ("", "abc", "10101;alert(1)", "1" * 13, "10 101", "-1"):
            result = F.sync_table(driver, bad)
            self.assertFalse(result["ok"], bad)
        self.assertEqual(driver.scripts, [])

    def test_sets_table_id_keeps_token_inside_page(self):
        driver = FakeDriver(LOBBY, DG_LOC)
        result = F.sync_table(driver, "10102")
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_id"], "10102")
        self.assertIn("tableId=10102", driver.src_attr)
        self.assertIn("token=SECRET", driver.src_attr)  # token giữ lại trong trang
        self.assertNotIn("SECRET", str(result))         # nhưng không lộ ra kết quả
        self.assertIn("[1]", driver.src_attr)           # đúng iframe DG
        # Selenium execute_script cần "return", nếu không kết quả luôn là None.
        self.assertTrue(driver.src_attr.startswith("return "))

    def test_no_dg_frame_reports_error(self):
        driver = FakeDriver(LOBBY, "https://febet.kiwi/other")
        self.assertFalse(F.sync_table(driver, "10101", wait=0)["ok"])


if __name__ == "__main__":
    unittest.main()