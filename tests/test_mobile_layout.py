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
        self.assertIn("link truy cập", source)

    def test_mobile_category_click(self):
        self.assertIn(".category-item", GK._MOBILE_CATEGORY_JS)

    def test_mobile_popup_buttons(self):
        for label in ("tôi biết rồi", "đóng"):
            self.assertIn(label, GK._MOBILE_CLOSE_JS)

    def test_mirror_hub_is_reported_not_clicked(self):
        source = inspect.getsource(GK.open_dg)
        self.assertIn("trang tổng hợp link", source)

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
