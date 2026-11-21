# -*- coding: utf-8 -*-
"""Tests for the E3951 site-entry adapter (popup/login/Casino/DG/promote)."""

import unittest

from aibcr.adapters import e3951 as E


class FakeDriver:
    """Minimal Selenium stand-in for the E3951 flow."""

    def __init__(self, current="https://www.e3951.com/seamless?gameType=LIVE"):
        self.current_url = current
        self.window_handles = ["tab-1"]
        self.current_window_handle = "tab-1"
        self.scripts = []
        self.navigated = []

    def switch_to_default(self):
        pass

    @property
    def switch_to(self):
        return self

    def default_content(self):
        pass

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        return self._respond(script, args)

    def _respond(self, script, args):
        if script == E._LOGIN_STATE_JS:
            return {"modalVisible": False, "formPresent": False,
                    "submitVisible": False, "hasUsername": False, "hasPassword": False}
        if script == E._DISMISS_PROMO_JS:
            return {"closed": []}
        if script == E._CLICK_NAV_JS:
            return {"ok": True}
        if script == E._LIVE_STATE_JS:
            return {"path": "/live", "boxCount": 12,
                    "vendorNames": ["SE", "DG"], "launch": ["CHƠI NGAY"]}
        if script == E._SELECT_DG_JS:
            return {"ok": True}
        if script == E._CLICK_LAUNCH_JS:
            return {"ok": True, "label": "Chơi ngay"}
        if script == E._NAVIGATE_IN_PLACE_JS:
            return True
        return None

    def get(self, url):
        self.navigated.append(url)
        self.current_url = url


class FailingDriver(FakeDriver):
    """Fails at the requested stage so error paths can be asserted."""

    def __init__(self, fail_at, **kwargs):
        super().__init__(**kwargs)
        self.fail_at = fail_at

    def _respond(self, script, args):
        if self.fail_at == "nav" and script == E._CLICK_NAV_JS:
            return {"ok": False, "labels": ["trang chủ"]}
        if self.fail_at == "cards" and script == E._LIVE_STATE_JS:
            return {"path": "/live", "boxCount": 0}
        if self.fail_at == "vendor" and script == E._SELECT_DG_JS:
            return {"ok": False, "count": 12}
        if self.fail_at == "launch" and script == E._CLICK_LAUNCH_JS:
            return {"ok": False}
        return super()._respond(script, args)


class E3951PopupTest(unittest.TestCase):
    def test_promo_close_never_targets_the_login_modal(self):
        self.assertIn(".loginPopupModal", E._DISMISS_PROMO_JS)
        self.assertIn("form.login-form", E._DISMISS_PROMO_JS)
        # `.close-popup` is the ticket/reward popup close control, so chained
        # reward popups are dismissed too.
        self.assertIn(".close-popup", E._PROMO_CLOSE_SELECTORS)

    def test_login_only_reports_booleans_never_credentials(self):
        self.assertIn("hasUsername", E._LOGIN_STATE_JS)
        self.assertIn("value.length > 0", E._LOGIN_STATE_JS)
        # The state script must not return the raw field values.
        self.assertNotIn("username:", E._LOGIN_STATE_JS)
        self.assertNotIn("password:", E._LOGIN_STATE_JS)

    def test_dismiss_promos_returns_clicked_selectors(self):
        driver = FakeDriver()
        self.assertEqual(E.dismiss_promos(driver), [])

    def test_login_state_reports_no_modal_for_logged_in_session(self):
        state = E.login_state(FakeDriver())
        self.assertFalse(state["modalVisible"])


class E3951PromoteTest(unittest.TestCase):
    def test_promote_navigates_top_level_to_the_dg_lobby(self):
        class IframeCtx(FakeDriver):
            pass

        driver = IframeCtx()
        original = E.DG._dg_context
        E.DG._dg_context = lambda _d, wait=0: {
            "mode": "iframe", "path": (0,),
            "location": "https://new-dd-cn.example.com/ddnewpc/index.html?token=T&tableId=60101"}
        try:
            self.assertTrue(E.promote_lobby_to_tab(driver))
        finally:
            E.DG._dg_context = original
        self.assertEqual(len(driver.navigated), 1)
        self.assertIn("ddnewpc", driver.navigated[0])

    def test_promote_is_a_noop_when_already_a_tab(self):
        driver = FakeDriver()
        original = E.DG._dg_context
        E.DG._dg_context = lambda _d, wait=0: {
            "mode": "tab",
            "location": "https://new-dd-cn.example.com/ddnewpc/index.html?token=T"}
        try:
            self.assertTrue(E.promote_lobby_to_tab(driver))
        finally:
            E.DG._dg_context = original
        self.assertEqual(driver.navigated, [])

    def test_promote_returns_false_without_a_dg_frame(self):
        driver = FakeDriver()
        original = E.DG._dg_context
        E.DG._dg_context = lambda _d, wait=0: None
        try:
            self.assertFalse(E.promote_lobby_to_tab(driver))
        finally:
            E.DG._dg_context = original
        self.assertEqual(driver.navigated, [])

    def test_promote_ignores_non_dg_locations(self):
        driver = FakeDriver()
        original = E.DG._dg_context
        E.DG._dg_context = lambda _d, wait=0: {
            "mode": "iframe", "path": (0,), "location": "https://www.e3951.com/live"}
        try:
            self.assertFalse(E.promote_lobby_to_tab(driver))
        finally:
            E.DG._dg_context = original
        self.assertEqual(driver.navigated, [])


if __name__ == "__main__":
    unittest.main()
