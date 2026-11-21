# -*- coding: utf-8 -*-
"""Tests for the VNWTop site-entry adapter (Casino trực tiếp -> DreamGaming)."""

import unittest

from aibcr.adapters import vnwtop as V


class FakeDriver:
    def __init__(self):
        self.window_handles = ["site-tab"]
        self.current_url = "https://vnwtop.com/"
        self.scripts = []
        self.navigated = []
        self.closed = []

    @property
    def switch_to(self):
        return self

    def window(self, handle):
        self.handle = handle

    def default_content(self):
        pass

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        if script == V._DISMISS_JS:
            return {"closed": []}
        if script == V._CLICK_SIDE_JS:
            return {"ok": True}
        if script == V._LIVE_STATE_JS:
            return {"path": "/", "bannerCount": 5,
                    "names": ["SA Gaming", "DreamGaming"], "active": ["Casino trực tiếp"],
                    "modalVisible": False}
        if script == V._CLICK_DG_JS:
            return {"ok": True, "alt": "DreamGaming"}
        if script == V._NAVIGATE_IN_PLACE_JS:
            return True
        return None

    @property
    def current_window_handle(self):
        return self.window_handles[0]

    def get(self, url):
        self.navigated.append(url)
        self.current_url = url

    def close(self):
        self.closed.append(self.current_url)


class VNWTopSourceTest(unittest.TestCase):
    def test_targets_the_live_casino_label(self):
        self.assertEqual(V._CASINO_LABEL, "casino trực tiếp")
        self.assertIn(".side-text", V._CLICK_SIDE_JS)

    def test_matches_the_dreamgaming_banner(self):
        self.assertEqual(V._DG_NAME, "dreamgaming")
        self.assertIn("platform-banner-full", V._CLICK_DG_JS)
        # Provider names are compared with spaces stripped, so "Dream Gaming"
        # and "DreamGaming" both resolve.
        self.assertIn("replace(/\\s+/g, '')", V._CLICK_DG_JS)

    def test_dismiss_touches_only_overlay_close_controls(self):
        import inspect
        source = inspect.getsource(V.dismiss_overlays)
        self.assertIn(".van-icon-cross", source)
        # Login inputs are never read or clicked by the dismiss script.
        self.assertNotIn("input", V._DISMISS_JS)
        self.assertNotIn("password", V._DISMISS_JS)

    def test_in_place_navigation_preserves_a_single_window(self):
        self.assertIn("location.assign", V._NAVIGATE_IN_PLACE_JS)


class VNWTopPromoteTest(unittest.TestCase):
    def test_promote_reads_lobby_from_popup_and_closes_it(self):
        driver = FakeDriver()
        driver.window_handles = ["site-tab", "dg-tab"]
        current = {"handle": "site-tab"}

        def switch_window(handle):
            current["handle"] = handle

        driver.window = switch_window

        class TrackingDriver(FakeDriver):
            @property
            def current_url(self):
                return ("https://new-dd-cn.example.com/ddnewpc/index.html?token=T"
                        if current["handle"] == "dg-tab" else "https://vnwtop.com/")

            @current_url.setter
            def current_url(self, value):
                pass

        tracking = TrackingDriver()
        tracking.window_handles = ["site-tab", "dg-tab"]
        tracking.window = switch_window
        closed = []
        tracking.close = lambda: closed.append(current["handle"])

        self.assertTrue(V.promote_lobby_to_tab(tracking, "site-tab"))
        self.assertEqual(closed, ["dg-tab"])
        self.assertEqual(tracking.window_handles, ["site-tab", "dg-tab"])
        self.assertEqual(len(tracking.navigated), 1)
        self.assertIn("ddnewpc", tracking.navigated[0])

    def test_promote_is_false_without_a_dg_window(self):
        driver = FakeDriver()
        driver.window_handles = ["site-tab", "promo-tab"]

        class PromoDriver(FakeDriver):
            @property
            def current_url(self):
                return "https://vnwtop.com/promo"

            @current_url.setter
            def current_url(self, value):
                pass

        promo = PromoDriver()
        promo.window_handles = ["site-tab", "promo-tab"]
        promo.window = lambda handle: None
        closed = []
        promo.close = lambda: closed.append("x")
        self.assertFalse(V.promote_lobby_to_tab(promo, "site-tab"))
        self.assertEqual(closed, [])
        self.assertEqual(promo.navigated, [])


class VNWTopUnitsTest(unittest.TestCase):
    def test_safe_location_never_exposes_query_tokens(self):
        class TokenDriver:
            current_url = "https://new-dd-cn.example.com/ddnewpc/index.html?token=SECRET&tableId=60101"

        location = V._safe_location(TokenDriver())
        self.assertNotIn("token", location)
        self.assertNotIn("SECRET", location)
        self.assertIn("ddnewpc", location)

    def test_open_dg_rejects_missing_driver(self):
        result = V.open_dg(None, wait=5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["site_id"], "vnwtop")

    def test_open_dg_reports_missing_casino_entry(self):
        class NoNav(FakeDriver):
            def execute_script(self, script, *args):
                if script == V._CLICK_SIDE_JS:
                    return {"ok": False, "labels": ["Xổ số"]}
                return super().execute_script(script, *args)

        original = V.DG.lobby_tables
        V.DG.lobby_tables = lambda driver, wait=0: {"ok": False, "error": "chưa có"}
        try:
            result = V.open_dg(NoNav(), wait=5)
        finally:
            V.DG.lobby_tables = original
        self.assertFalse(result["ok"])
        self.assertIn("Casino", result["error"])


if __name__ == "__main__":
    unittest.main()
