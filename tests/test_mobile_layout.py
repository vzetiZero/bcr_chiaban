# -*- coding: utf-8 -*-
"""Phone-layout automation: the same sites render different DOM on mobile.

Verified against the live sites with an Android fingerprint:

E3951 mobile (`/m/index.html`)
  - navigation is `.game-menu-item`; `.nav-name` does not exist
  - provider cards are `.vendor-game-item`; the provider token sits in the image
    name as ``gcs__live-DG_<timestamp>.png`` (not ``DG-DEFAULT.png``)
  - login is a header `.login-btn` leading to a dedicated ``/m/login`` page whose
    form uses ``input[name=username]`` / ``input[name=password]``
  - promos are `.popup_container_v2` and `.bottom-modal` sheets

GK881 mobile (`m.gk881.vip`)
  - no ``ng-click`` attributes at all; categories are ``.category-item``
  - the landing page can be a "LINK TRUY CẬP" mirror hub

VNWTop mobile keeps the same labels but moves them into a tab bar.
"""

import inspect
import re
import unittest

from aibcr.adapters import e3951 as E
from aibcr.adapters import gk881 as GK
from aibcr.adapters import vnwtop as V


class E3951MobileSelectorTest(unittest.TestCase):
    def test_nav_matches_both_desktop_and_mobile(self):
        self.assertIn(".nav-name", E._CLICK_NAV_JS)
        self.assertIn(".game-menu-item", E._CLICK_NAV_JS)

    def test_nav_reports_the_layout_it_used(self):
        self.assertIn("layout: selector", E._CLICK_NAV_JS)

    def test_mobile_cards_are_recognised(self):
        self.assertIn(".vendor-game-item", E._LIVE_STATE_JS)
        self.assertIn(".vendor-box", E._LIVE_STATE_JS)

    def test_mobile_provider_token_is_parsed(self):
        # `gcs__live-DG_1792424580512.png` -> DG, not GCS.
        self.assertIn(r"([A-Za-z0-9]+)_\d+\.(?:png|webp|avif)", E._LIVE_STATE_JS)
        parsed = re.search(r"([A-Za-z0-9]+)_\d+\.(?:png|webp|avif)",
                           "gcs__live-DG_1792424580512.png")
        self.assertEqual(parsed.group(1).upper(), "DG")

    def test_mobile_dg_card_matcher(self):
        self.assertIn(r"-DG_\d+\.", E._SELECT_DG_JS)

    def test_launch_falls_back_to_the_card_on_mobile(self):
        self.assertIn(".vendor-game-item", E._CLICK_LAUNCH_JS)
        self.assertIn("vendor-card", E._CLICK_LAUNCH_JS)

    def test_login_supports_the_mobile_page(self):
        self.assertIn("input[name=username]", E._LOGIN_STATE_JS)
        self.assertIn("input[name=password]", E._LOGIN_STATE_JS)
        self.assertIn("form.form-content", E._LOGIN_STATE_JS)

    def test_login_opens_the_mobile_page_first(self):
        self.assertIn("opened-login-page", E._LOGIN_JS)
        self.assertIn(".login-btn", E._LOGIN_JS)

    def test_login_state_flags_mobile_layout(self):
        self.assertIn("mobile:", E._LOGIN_STATE_JS)

    def test_mobile_promo_close_controls(self):
        self.assertIn(".popup_container_v2 [class*=close]", E._PROMO_CLOSE_SELECTORS)
        self.assertIn(".bottom-modal [class*=close]", E._PROMO_CLOSE_SELECTORS)

    def test_open_dg_handles_the_two_step_mobile_login(self):
        source = inspect.getsource(E.open_dg)
        # open_dg must react to the login page being opened, then wait for the
        # form and submit it (the marker itself lives in _LOGIN_JS).
        self.assertIn('opened.get("opened")', source)
        self.assertIn("giao diện điện thoại", source)
        self.assertIn('state.get("mobile")', source)


class GK881MobileTest(unittest.TestCase):
    def test_mobile_layout_is_detected(self):
        self.assertIn(".category-item", GK._MOBILE_STATE_JS)
        source = inspect.getsource(GK._is_mobile_layout)
        self.assertIn("category-item", source)
        # The hub signal must be the page *heading*, not any line of text: a
        # footer mention turned ``hub`` on and misclassified a normal page.
        self.assertIn("h1, h2, h3", source)

    def test_mobile_category_click(self):
        self.assertIn(".category-item", GK._MOBILE_CATEGORY_JS)

    def test_mobile_popup_buttons(self):
        for label in ("tôi biết rồi", "đóng"):
            self.assertIn(label, GK._MOBILE_CLOSE_JS)

    def test_mirror_hub_warns_but_keeps_looking(self):
        """A hub heading must not abort the run on its own.

        Measured: the same URL and profile read "link truy cập" from the footer
        before the category strip was drawn; aborting there threw away a run that
        would have reached the lobby. The flow now warns and keeps trying.
        """
        source = inspect.getsource(GK.open_dg)
        self.assertIn("tổng hợp link", source)
        self.assertIn("vẫn thử tiếp", source)

    def test_desktop_flow_is_untouched(self):
        # The old Angular selectors must still be present.
        source = inspect.getsource(GK.open_dg)
        self.assertIn('li[ng-click*="entrance.click"]', source)


class VNWTopMobileTest(unittest.TestCase):
    def test_side_lookup_falls_back_for_mobile(self):
        self.assertIn(".side-text", V._CLICK_SIDE_JS)
        self.assertIn("[class*=tab]", V._CLICK_SIDE_JS)

    def test_banner_lookup_accepts_any_alt_image(self):
        self.assertIn("img[alt]", V._CLICK_DG_JS)

    def test_mobile_overlay_selectors(self):
        source = inspect.getsource(V.dismiss_overlays)
        self.assertIn("bottom-modal", source)


class PhoneFrameTest(unittest.TestCase):
    def test_window_matches_the_device_aspect(self):
        from aibcr.adapters import device_profile as DP
        from aibcr.models import fingerprint as FP
        frame = DP.mobile_window(FP.generate(seed=4242))
        self.assertIn("width", frame)
        self.assertIn("height", frame)
        self.assertIn("viewport", frame)
        # Portrait phone: taller than wide, and readable.
        self.assertGreater(frame["height"], frame["width"])
        self.assertGreaterEqual(frame["width"], 360)

    def test_viewport_is_retargeted_without_mutating_the_original(self):
        from aibcr.adapters import device_profile as DP
        from aibcr.models import fingerprint as FP
        original = FP.generate(seed=7)
        copy = DP.with_viewport(original, {"width": 430, "height": 955})
        self.assertEqual(copy["viewport"], {"width": 430, "height": 955})
        self.assertNotIn("viewport", original)

    def test_metrics_use_the_retargeted_viewport(self):
        from aibcr.adapters import device_profile as DP
        from aibcr.models import fingerprint as FP

        class Driver:
            def __init__(self):
                self.calls = []

            def execute_cdp_cmd(self, method, params):
                self.calls.append((method, params))

        driver = Driver()
        fingerprint = DP.with_viewport(FP.generate(seed=9), {"width": 430, "height": 955})
        DP.apply_to_driver(driver, fingerprint)
        metrics = next(p for m, p in driver.calls
                       if m == "Emulation.setDeviceMetricsOverride")
        self.assertEqual(metrics["width"], 430)
        self.assertEqual(metrics["height"], 955)

    def test_page_area_overrides_the_retargeted_viewport(self):
        """Once the window is known, its real area wins over the phone viewport.

        Otherwise Chrome shrinks the phone surface into the frame and leaves a
        blank strip (the reported "UI smaller than the window").
        """
        from aibcr.adapters import device_profile as DP
        from aibcr.models import fingerprint as FP

        class Driver:
            def __init__(self):
                self.calls = []

            def execute_cdp_cmd(self, method, params):
                self.calls.append((method, params))

        driver = Driver()
        fingerprint = DP.with_viewport(FP.generate(seed=9), {"width": 430, "height": 955})
        DP.apply_to_driver(driver, fingerprint,
                           page_area={"width": 888, "height": 1108, "dpr": 0.6})
        metrics = next(p for m, p in driver.calls
                       if m == "Emulation.setDeviceMetricsOverride")
        self.assertEqual((metrics["width"], metrics["height"]), (888, 1108))

    def test_device_scale_is_capped(self):
        from aibcr.adapters import device_profile as DP
        from aibcr.models import fingerprint as FP

        class Driver:
            def __init__(self):
                self.calls = []

            def execute_cdp_cmd(self, method, params):
                self.calls.append((method, params))

        driver = Driver()
        fingerprint = FP.generate(seed=1)
        DP.apply_to_driver(driver, fingerprint)
        metrics = next(p for m, p in driver.calls
                       if m == "Emulation.setDeviceMetricsOverride")
        self.assertLessEqual(metrics["deviceScaleFactor"], 3.0)


if __name__ == "__main__":
    unittest.main()

class TopLevelLobbyTest(unittest.TestCase):
    """GK881 mobile renders the DG lobby in the page body of
    /Account/LoginToSupplier?SupplierType=DG (no ``ddnewpc`` iframe), so the
    frame-only walkers used to report "Laya chưa tải xong" for a lobby that was
    plainly visible on screen."""

    class Switch:
        def __init__(self, driver):
            self.driver = driver

        def window(self, handle):
            self.driver.handle = handle

        def default_content(self):
            self.driver.frame = None

        def frame(self, element):
            self.driver.frame = element

    def _driver(self, mounted=True, stage_kids=1):
        from aibcr.adapters import febet as F

        class Driver:
            def __init__(self):
                self.handle = "tab1"
                self.window_handles = ["tab1"]
                self.frame = None
                self.switch_to = TopLevelLobbyTest.Switch(self)
                self.current_url = (
                    "https://m.gk881.vip/Account/LoginToSupplier?SupplierType=DG")
                self.mounted = mounted
                self.stage_kids = stage_kids if mounted else 0

            @property
            def current_window_handle(self):
                return self.handle

            def find_elements(self, by, selector):
                return []

            def execute_script(self, script, *args):
                if "stageKids" in script and "typeof Laya === 'undefined'" in script:
                    return {"laya": self.mounted, "stageKids": self.stage_kids}
                if "const frames=[...document.querySelectorAll('iframe,frame')]" in script:
                    return {"url": self.current_url, "title": "", "frames": 0, "labels": []}
                if "tableInfo || n._tableInfo" in script:
                    if not self.mounted:
                        return {"ready": False, "tables": []}
                    return {"ready": True, "tables": [
                        {"table_id": "60101", "name": "RB01", "online": 303}]}
                if "typeof Laya" in script and "tableInfo" not in script:
                    if not self.mounted:
                        return {"ready": False, "lobby": False, "in_table": False,
                                "label": "", "url_table": ""}
                    return {"ready": True, "lobby": True, "in_table": False,
                            "label": "", "url_table": "60101"}
                return None

        return Driver()

    def test_has_top_laya_requires_a_drawn_stage(self):
        from aibcr.adapters import febet as F
        self.assertTrue(F._has_top_laya(self._driver()))
        self.assertFalse(F._has_top_laya(self._driver(mounted=False)))
        self.assertFalse(F._has_top_laya(self._driver(stage_kids=0)))

    def test_dg_window_finds_the_page_hosting_the_lobby(self):
        from aibcr.adapters import febet as F
        self.assertEqual(F._dg_window(self._driver()), "tab1")

    def test_dg_frame_reports_the_top_document(self):
        from aibcr.adapters import febet as F
        path, location = F._dg_frame(self._driver(), wait=1.0)
        self.assertEqual(path, ())
        self.assertIn("LoginToSupplier", location)

    def test_dg_context_labels_the_top_mode(self):
        from aibcr.adapters import febet as F
        context = F._dg_context(self._driver(), wait=1.0)
        self.assertEqual(context["mode"], "top")

    def test_lobby_tables_reads_the_page_body(self):
        from aibcr.adapters import febet as F
        result = F.lobby_tables(self._driver(), wait=2.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tables"][0]["table_id"], "60101")

    def test_unmounted_lobby_still_reports_a_clear_error(self):
        from aibcr.adapters import febet as F
        result = F.lobby_tables(self._driver(mounted=False), wait=1.0)
        self.assertFalse(result["ok"])
        self.assertIn("Laya", result["error"])

    def test_ddnewpc_frame_still_wins_over_the_top_fallback(self):
        from aibcr.adapters import febet as F

        class IframeDriver(self._driver().__class__):
            def find_elements(self, by, selector):
                return ["dg-frame"] if self.frame is None else []

            def execute_script(self, script, *args):
                if "const frames=[...document.querySelectorAll('iframe,frame')]" in script:
                    if self.frame is None:
                        return {"url": self.current_url, "title": "", "frames": 1, "labels": []}
                    return {"url": "https://x/ddnewpc/index.html?tableId=60101",
                            "title": "", "frames": 0, "labels": []}
                return super().execute_script(script, *args)

        driver = IframeDriver()
        driver.current_url = "https://febet.kiwi/live-casino/baccarat"
        path, location = F._dg_frame(driver, wait=1.0)
        self.assertEqual(path, (0,))
        self.assertIn("ddnewpc", location)

    def test_sync_table_taps_the_laya_card_in_top_mode(self):
        from aibcr.adapters import febet as F
        driver = self._driver()
        calls = []
        original = driver.execute_script

        def script(source, *args):
            if "const wanted = String(arguments[0] || '')" in source:
                calls.append(args)
                return {"ok": True, "label": "RB01"}
            return original(source, *args)

        driver.execute_script = script
        result = F.sync_table(driver, "60101", wait=2.0, settle=1.0)
        self.assertTrue(calls, "the Laya card was not tapped")
        self.assertEqual(calls[0][0], "60101")
        # settle window may not confirm; either way the tap happened.
        self.assertIn("ok", result)
