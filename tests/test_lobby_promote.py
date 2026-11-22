# -*- coding: utf-8 -*-
"""DG lobby promotion: iframe URL -> top-level tab URL.

GK881 mobile (and E3951) render Dream Gaming inside a site iframe. Reading the
frame's real URL and loading it as the page removes the site DOM and lets the
shared table sync rewrite ``direct1.html`` so every profile joins one table.

The URL carries a session token, so the helpers may only report its host.
"""

import unittest

from aibcr.adapters import e3951 as E
from aibcr.adapters import febet as F
from aibcr.adapters import gk881 as GK

SITE_TOP = "https://m.gk881.vip/Account/LoginToSupplier?SupplierType=DG"
DDNEWPC = ("https://new-dd-cn.example.com/ddnewpc/index.html"
           "?token=SECRET&tableId=60101&lang=vi")


class Switch:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.handle = handle

    def default_content(self):
        self.driver.frame = None

    def frame(self, element):
        self.driver.frame = element


class PromoteDriver:
    """Site tab with one DG iframe; CDP navigation replaces the tab URL."""

    def __init__(self, top=SITE_TOP, frame_url=DDNEWPC):
        self.handle = "site"
        self.window_handles = ["site"]
        self.frame = None
        self.top_url = top
        self.frame_url = frame_url
        self.iframe_src = "https://new-dd-cn.example.com/ddnewpc/direct1.html?token=SECRET"
        self.cdp = []
        self.gets = []
        self.switch_to = Switch(self)

    @property
    def current_url(self):
        return self.top_url

    @property
    def current_window_handle(self):
        return self.handle

    def find_elements(self, by, selector):
        if selector != "iframe, frame":
            return []
        if self.frame is not None:
            return []
        return ["dg-frame"] if self.frame_url else []

    def execute_cdp_cmd(self, method, params):
        self.cdp.append((method, params))
        if method == "Page.navigate":
            self.top_url = params["url"]
            self.frame_url = None
            self.frame = None
        return {}

    def get(self, url):
        self.gets.append(url)
        self.top_url = url
        self.frame_url = None

    def execute_script(self, script, *args):
        if "const frames=[...document.querySelectorAll('iframe,frame')]" in script:
            if self.frame is None:
                return {"url": self.top_url, "title": "",
                        "frames": 1 if self.frame_url else 0, "labels": []}
            return {"url": self.frame_url, "title": "", "frames": 0, "labels": []}
        if "stageKids" in script:
            mounted = self.frame is not None
            return {"laya": mounted, "stageKids": 1 if mounted else 0,
                    "width": 100, "height": 100}
        if "tableInfo || n._tableInfo" in script:
            return {"ready": True, "tables": [
                {"table_id": "60101", "name": "RB01", "online": 12}]}
        if "typeof Laya" in script and "tableInfo" not in script:
            return {"ready": True, "lobby": True, "in_table": False,
                    "label": "", "url_table": "60101"}
        if "const f = document.querySelectorAll('iframe,frame')[0];" in script:
            if "f.src =" in script:
                self.iframe_src = script
                return {"ok": True}
            return self.iframe_src
        return None


class GameFrameTest(unittest.TestCase):
    def test_prefers_the_ddnewpc_document(self):
        found = F.game_frame(PromoteDriver(), wait=1.0)
        self.assertIsNotNone(found)
        self.assertEqual(found["handle"], "site")
        self.assertIn("ddnewpc", found["url"])

    def test_returns_none_without_a_game_frame(self):
        self.assertIsNone(F.game_frame(PromoteDriver(frame_url=None), wait=0.5))


class NavigateTopTest(unittest.TestCase):
    def test_uses_cdp_and_never_rebinds_the_session(self):
        driver = PromoteDriver()
        self.assertTrue(F.navigate_top(driver, DDNEWPC))
        self.assertEqual(driver.gets, [])
        self.assertEqual(driver.cdp[0][0], "Page.navigate")

    def test_falls_back_to_get_without_cdp(self):
        class Legacy:
            def __init__(self):
                self.navigated = []

            def get(self, url):
                self.navigated.append(url)

        driver = Legacy()
        self.assertTrue(F.navigate_top(driver, DDNEWPC))
        self.assertEqual(driver.navigated, [DDNEWPC])


class PromoteLobbyTest(unittest.TestCase):
    def test_promotes_the_iframe_to_the_tab_url(self):
        driver = PromoteDriver()
        result = F.promote_lobby_to_tab(driver, site_hosts=("gk881.vip",),
                                        wait=2.0, settle=5.0, prefer_handle="site")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["promoted"])
        self.assertIn("ddnewpc", driver.current_url)
        # Only the host is exposed, never the token.
        self.assertEqual(result["host"], "new-dd-cn.example.com")
        self.assertNotIn("SECRET", repr(result))

    def test_noop_when_the_lobby_is_already_a_tab(self):
        driver = PromoteDriver(top=DDNEWPC, frame_url=None)
        result = F.promote_lobby_to_tab(driver, wait=1.0, settle=1.0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["promoted"])
        self.assertEqual(driver.cdp, [])

    def test_reports_failure_without_a_frame(self):
        driver = PromoteDriver(frame_url=None)
        result = F.promote_lobby_to_tab(driver, wait=0.5, settle=1.0)
        self.assertFalse(result["ok"])
        self.assertFalse(result["promoted"])

    def test_sync_after_promotion_rewrites_the_loader(self):
        driver = PromoteDriver(top=DDNEWPC, frame_url=None)
        driver.execute_script = self._wrap(driver)
        result = F.sync_table(driver, "60102", wait=1.0, settle=1.0)
        self.assertIn("tableId=60102", driver.nav_script)
        self.assertIn("direct1.html", driver.nav_script)
        self.assertIn("ok", result)

    @staticmethod
    def _wrap(driver):
        original = PromoteDriver.execute_script
        driver.nav_script = ""

        def script(source, *args):
            if "location.href =" in source:
                driver.nav_script = source
                return None
            return original(driver, source, *args)

        return script


class E3951PromoteCdpTest(unittest.TestCase):
    def test_promote_goes_through_cdp_on_a_managed_profile(self):
        driver = PromoteDriver(top="https://www.e3951.com/live")
        original = E.DG._dg_context
        E.DG._dg_context = lambda _d, wait=0: {
            "mode": "iframe", "path": (0,), "location": DDNEWPC}
        try:
            self.assertTrue(E.promote_lobby_to_tab(driver))
        finally:
            E.DG._dg_context = original
        self.assertEqual(driver.gets, [])
        self.assertEqual(driver.cdp[0][1]["url"], DDNEWPC)


class GK881MobilePromoteTest(unittest.TestCase):
    """The mobile entry flow must promote the lobby before returning tables."""

    class MobileDriver:
        def __init__(self):
            self.handle = "site"
            self.window_handles = ["site"]
            self.frame = None
            self.top_url = "https://m.gk881.vip/"
            self.switch_to = Switch(self)

        @property
        def current_url(self):
            return self.top_url

        @property
        def current_window_handle(self):
            return self.handle

        def find_elements(self, by, selector):
            return []

        def execute_cdp_cmd(self, method, params):
            return {}

        def execute_script(self, script, *args):
            if "const ua = navigator.userAgent" in script:
                return {"mobileUa": True, "touch": 5, "ng": 0,
                        "categories": 1, "hub": False}
            if "tôi biết rồi" in script:
                return {"closed": []}
            if "isHub" in script:
                return {"isHub": False, "categories": ["casino"],
                        "providers": [], "dgText": True}
            if "aliases" in script:
                return {"ok": True, "label": "casino"}
            if "isDgText" in script:
                return {"ok": True, "label": "dg trực tuyến"}
            return None

    def test_mobile_flow_promotes_and_refreshes_tables(self):
        driver = self.MobileDriver()
        calls = {"lobby": 0, "promote": 0}

        def fake_lobby(_driver, wait=0):
            calls["lobby"] += 1
            if calls["lobby"] == 1:
                return {"ok": False, "error": "chưa mở"}
            return {"ok": True, "tables": [
                {"table_id": "60101", "name": "RB01", "online": 12}]}

        def fake_promote(_driver, site_hosts=(), wait=0, settle=0,
                         prefer_handle=None):
            calls["promote"] += 1
            calls["prefer"] = prefer_handle
            calls["sites"] = site_hosts
            return {"ok": True, "promoted": True, "mode": "tab",
                    "host": "new-dd-cn.example.com"}

        original_lobby = GK.DG.lobby_tables
        original_promote = GK.DG.promote_lobby_to_tab
        GK.DG.lobby_tables = fake_lobby
        GK.DG.promote_lobby_to_tab = fake_promote
        try:
            result = GK.open_dg(driver, wait=20)
        finally:
            GK.DG.lobby_tables = original_lobby
            GK.DG.promote_lobby_to_tab = original_promote

        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["promoted"])
        self.assertEqual(result["layout"], "mobile")
        self.assertEqual(calls["promote"], 1)
        self.assertEqual(calls["prefer"], "site")
        self.assertEqual(calls["sites"], ("gk881.vip",))
        self.assertGreaterEqual(calls["lobby"], 3)


if __name__ == "__main__":
    unittest.main()
