# -*- coding: utf-8 -*-
"""GK881 DG hand-off pages.

GK881 does not always open the DG lobby directly. It first redirects to

    https://m.gk881.vip/Account/LoginToSupplier?SupplierType=DG
    https://m.gk881.vip/Lobby/Navigation

The ``m.`` mobile subdomain must not matter: DG is recognised by the
``ddnewpc`` document marker, not by host name. Those hand-off pages also have
no Casino menu, so the flow must wait for the DG document instead of clicking a
menu that does not exist (which used to raise TimeoutException).
"""

import time
import unittest

from aibcr.adapters import gk881 as GK

LOGIN_TO_SUPPLIER = "https://m.gk881.vip/Account/LoginToSupplier?SupplierType=DG"
DDNEWPC = ("https://new-dd-cn.example.com/ddnewpc/index.html"
           "?token=T&tableId=60101&lang=vi")


class FakeSwitch:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.handle = handle

    def default_content(self):
        self.driver.frame = None

    def frame(self, element):
        self.driver.frame = element


class HandOffDriver:
    """One tab on a GK881 DG hand-off page; the DG iframe mounts after a delay."""

    def __init__(self, url=LOGIN_TO_SUPPLIER, delay=0.0):
        self.url = url
        self.handle = "tab1"
        self.window_handles = ["tab1"]
        self.frame = None
        self.switch_to = FakeSwitch(self)
        self.delay = delay
        self.started = time.monotonic()
        self.queries = []

    @property
    def current_window_handle(self):
        return self.handle

    @property
    def current_url(self):
        return self.url

    def _mounted(self):
        return (time.monotonic() - self.started) >= self.delay

    def find_elements(self, by, selector):
        self.queries.append(selector)
        if selector == "iframe, frame":
            return ["dg-frame"] if self._mounted() else []
        return []

    def execute_script(self, script, *args):
        if "const frames=[...document.querySelectorAll('iframe,frame')]" in script:
            if self.frame is None:
                return {"url": self.url, "title": "",
                        "frames": 1 if self._mounted() else 0, "labels": []}
            return {"url": DDNEWPC, "title": "", "frames": 0, "labels": []}
        if "tableInfo || n._tableInfo" in script:
            if self.frame is None:
                return {"ready": False, "tables": []}
            return {"ready": True, "tables": [
                {"table_id": "60101", "name": "RB01", "online": 300}]}
        if "typeof Laya" in script and "tableInfo" not in script:
            if self.frame is None:
                return {"ready": False, "lobby": False, "in_table": False,
                        "label": "", "url_table": ""}
            return {"ready": True, "lobby": True, "in_table": False,
                    "label": "", "url_table": "60101"}
        return None


class HandOffUrlTest(unittest.TestCase):
    def test_mobile_login_to_supplier_is_recognised(self):
        self.assertTrue(GK._is_dg_entry_url(LOGIN_TO_SUPPLIER))

    def test_desktop_host_is_recognised_too(self):
        self.assertTrue(GK._is_dg_entry_url(
            "https://www.gk881.vip/Account/LoginToSupplier?SupplierType=DG"))

    def test_lobby_navigation_is_recognised(self):
        self.assertTrue(GK._is_dg_entry_url("https://m.gk881.vip/Lobby/Navigation"))

    def test_home_page_is_not_a_hand_off_page(self):
        for url in ("https://m.gk881.vip/", "https://m.gk881.vip/Lobby/Live",
                    "https://febet.kiwi/live-casino/baccarat"):
            self.assertFalse(GK._is_dg_entry_url(url), url)

    def test_query_is_matched_case_insensitively(self):
        self.assertTrue(GK._is_dg_entry_url(
            "https://m.gk881.vip/Account/LoginToSupplier?suppliertype=DG"))


class HandOffFlowTest(unittest.TestCase):
    def test_lobby_already_mounted_is_reused(self):
        result = GK.open_dg(HandOffDriver(delay=0.0), wait=10)
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_open"])
        self.assertEqual(result["tables"][0]["table_id"], "60101")

    def test_slow_lobby_waits_instead_of_clicking_the_casino_menu(self):
        driver = HandOffDriver(delay=2.0)
        result = GK.open_dg(driver, wait=15)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["already_open"])
        # It must not fall through to the provider-card navigation.
        self.assertFalse(any("entrance" in query for query in driver.queries),
                         "flow clicked the Casino menu on a hand-off page")

    def test_missing_lobby_reports_a_clear_error(self):
        result = GK.open_dg(HandOffDriver(delay=9999), wait=2)
        self.assertFalse(result["ok"])
        self.assertIn("chuyển tiếp DG", result["error"])

    def test_mobile_host_works_the_same_as_desktop(self):
        for url in (LOGIN_TO_SUPPLIER,
                    "https://www.gk881.vip/Account/LoginToSupplier?SupplierType=DG"):
            result = GK.open_dg(HandOffDriver(url=url, delay=0.0), wait=10)
            self.assertTrue(result["ok"], "%s -> %s" % (url, result.get("error")))


if __name__ == "__main__":
    unittest.main()
