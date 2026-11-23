# -*- coding: utf-8 -*-
"""Android device fingerprint: generation, stability and CDP application.

Every Chrome profile must present an Android phone identity (user-agent, screen,
touch, WebGL, canvas noise) that differs between profiles but stays stable for a
given profile across restarts. A new profile draws a new identity automatically.
"""

import json
import unittest

from aibcr.adapters import device_profile as DP
from aibcr.models import fingerprint as FP


class GeneratorTest(unittest.TestCase):
    def test_same_seed_is_stable(self):
        self.assertEqual(FP.generate(seed=11), FP.generate(seed=11))

    def test_different_seeds_vary(self):
        first = FP.generate(seed=11)
        second = FP.generate(seed=99)
        self.assertNotEqual((first["device"], first["canvas_seed"]),
                            (second["device"], second["canvas_seed"]))

    def test_user_agent_is_android_mobile(self):
        fingerprint = FP.generate(seed=5)
        agent = fingerprint["user_agent"]
        self.assertIn("Android", agent)
        self.assertIn("Mobile Safari", agent)
        self.assertIn("Mozilla/5.0 (Linux; Android", agent)

    def test_user_agent_uses_the_real_chrome_major(self):
        fingerprint = FP.generate(seed=5, chrome_major="157")
        self.assertIn("Chrome/157.0.0.0", fingerprint["user_agent"])

    def test_identity_has_every_field_the_injection_needs(self):
        fingerprint = FP.generate(seed=5)
        for key in ("user_agent", "platform", "languages", "screen", "cores",
                    "memory", "webgl_vendor", "webgl_renderer", "canvas_seed",
                    "max_touch_points", "android", "device", "mobile_layout"):
            self.assertIn(key, fingerprint)
        self.assertTrue(fingerprint["mobile_layout"])
        self.assertEqual(fingerprint["max_touch_points"], 5)

    def test_new_profiles_draw_different_devices(self):
        seen = {(item["device"], item["canvas_seed"]) for item in
                (FP.generate() for _ in range(6))}
        self.assertGreaterEqual(len(seen), 4)

    def test_regenerate_avoids_the_previous_device(self):
        current = FP.generate(seed=3)
        fresh = FP.regenerate(current)
        self.assertNotEqual(fresh["device"], current["device"])

    def test_describe_is_short_and_safe(self):
        label = FP.describe(FP.generate(seed=7))
        self.assertIn("Android", label)
        self.assertNotIn("token", label.lower())
        self.assertEqual(FP.describe(None), "Chưa có dấu vết")


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.fingerprint = FP.generate(seed=1234)
        self.script = DP.build_script(self.fingerprint)

    def test_script_is_empty_without_a_fingerprint(self):
        self.assertEqual(DP.build_script(None), "")
        self.assertEqual(DP.build_script({}), "")

    def test_script_hides_webdriver(self):
        self.assertIn("webdriver", self.script)
        self.assertIn("undefined", self.script)

    def test_script_overrides_navigator_fields(self):
        for field in ("platform", "hardwareConcurrency", "deviceMemory",
                      "maxTouchPoints", "languages"):
            self.assertIn(field, self.script)

    def test_script_patches_canvas_and_webgl(self):
        self.assertIn("getImageData", self.script)
        self.assertIn("toDataURL", self.script)
        self.assertIn("37445", self.script)  # UNMASKED_VENDOR_WEBGL
        self.assertIn("37446", self.script)  # UNMASKED_RENDERER_WEBGL

    def test_noise_skips_transparent_pixels(self):
        # Transparent pixels are dropped by the PNG encoder, so noise there would
        # not change the exported hash.
        self.assertIn("data[i + 3] === 0", self.script)

    def test_script_embeds_the_profile_seed(self):
        payload = json.loads(self.script.split("var FP = ", 1)[1].split(";", 1)[0])
        self.assertEqual(payload["canvasSeed"], self.fingerprint["canvas_seed"])
        self.assertEqual(payload["webglVendor"], self.fingerprint["webgl_vendor"])

    def test_guard_prevents_double_application(self):
        self.assertIn("__aibcrDeviceApplied", self.script)


class FakeDriver:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def execute_cdp_cmd(self, method, params):
        if method in self.fail:
            raise RuntimeError("boom")
        self.calls.append((method, params))
        return {}


class ApplyTest(unittest.TestCase):
    def test_applies_user_agent_metrics_touch_and_script(self):
        driver = FakeDriver()
        fingerprint = FP.generate(seed=42)
        applied = DP.apply_to_driver(driver, fingerprint, chrome_major="157")
        methods = [call[0] for call in driver.calls]
        self.assertIn("Network.setUserAgentOverride", methods)
        self.assertIn("Emulation.setDeviceMetricsOverride", methods)
        self.assertIn("Emulation.setTouchEmulationEnabled", methods)
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", methods)
        self.assertIn("ua", applied)
        self.assertIn("metrics", applied)
        self.assertIn("script", applied)

    def test_user_agent_metadata_matches_the_ua(self):
        driver = FakeDriver()
        fingerprint = FP.generate(seed=42)
        DP.apply_to_driver(driver, fingerprint, chrome_major="157")
        call = next(item for item in driver.calls
                    if item[0] == "Network.setUserAgentOverride")
        self.assertEqual(call[1]["userAgent"], fingerprint["user_agent"])
        self.assertEqual(call[1]["userAgentMetadata"]["platform"], "Android")
        self.assertTrue(call[1]["userAgentMetadata"]["mobile"])

    def test_metrics_are_mobile_portrait(self):
        driver = FakeDriver()
        fingerprint = FP.generate(seed=42)
        DP.apply_to_driver(driver, fingerprint)
        call = next(item for item in driver.calls
                    if item[0] == "Emulation.setDeviceMetricsOverride")
        self.assertTrue(call[1]["mobile"])
        self.assertEqual(call[1]["width"], fingerprint["screen"]["width"])
        self.assertEqual(call[1]["screenOrientation"]["type"], "portraitPrimary")

    def test_failure_never_raises(self):
        driver = FakeDriver(fail={"Network.setUserAgentOverride",
                                  "Emulation.setDeviceMetricsOverride",
                                  "Page.addScriptToEvaluateOnNewDocument"})
        applied = DP.apply_to_driver(driver, FP.generate(seed=1))
        self.assertIsInstance(applied, list)

    def test_missing_fingerprint_is_a_noop(self):
        driver = FakeDriver()
        self.assertEqual(DP.apply_to_driver(driver, None), [])
        self.assertEqual(driver.calls, [])


class FitViewportTest(unittest.TestCase):
    """The emulated viewport must equal the window's real page area.

    Chrome shrinks the emulated surface to fit the page area, so a phone-shaped
    viewport (412×915, ratio 0.45) inside a 900×1200 frame (page area ratio 0.80)
    rendered at only 47 % × 83 % — the "page smaller than the window" report.
    Matching the area renders 1:1 and fills the frame.
    """

    def test_viewport_equals_the_page_area(self):
        area = {"width": 888, "height": 1108, "dpr": 0.6}
        fitted = DP._fit_viewport_to_area({"width": 412, "height": 915},
                                          {"dpr": 3.0}, area)
        self.assertEqual((fitted["width"], fitted["height"]), (888, 1108))

    def test_scale_factor_follows_the_window_not_the_phone(self):
        area = {"width": 888, "height": 1108, "dpr": 0.6}
        fitted = DP._fit_viewport_to_area({"width": 412, "height": 915},
                                          {"dpr": 3.0}, area)
        # 0.6 makes 888 CSS × 0.6 = 533 device px = the real page surface.
        self.assertAlmostEqual(fitted["deviceScaleFactor"], 0.6, places=4)

    def test_aspect_ratio_matches_the_area(self):
        area = {"width": 520, "height": 900, "dpr": 1.25}
        fitted = DP._fit_viewport_to_area({"width": 412, "height": 915},
                                          {"dpr": 3.0}, area)
        self.assertAlmostEqual(fitted["width"] / fitted["height"],
                               520 / 900.0, places=4)

    def test_missing_area_falls_back_to_the_phone_viewport(self):
        self.assertIsNone(DP._fit_viewport_to_area(
            {"width": 412, "height": 915}, {"dpr": 3.0}, None))
        self.assertIsNone(DP._fit_viewport_to_area(
            {"width": 412, "height": 915}, {"dpr": 3.0}, {"width": 0, "height": 0}))

    def test_page_area_wins_over_the_phone_viewport(self):
        driver = FakeDriver()
        fingerprint = FP.generate(seed=42)
        DP.apply_to_driver(driver, fingerprint,
                           page_area={"width": 888, "height": 1108, "dpr": 0.6})
        metrics = next(p for m, p in driver.calls
                       if m == "Emulation.setDeviceMetricsOverride")
        self.assertEqual((metrics["width"], metrics["height"]), (888, 1108))
        self.assertTrue(metrics["mobile"])
        # screen must track the viewport: a real phone reports
        # innerWidth == screen.width, so claiming a 412 px screen inside an
        # 888 px viewport would itself be a fingerprinting tell.
        self.assertEqual(metrics["screenWidth"], 888)
        self.assertEqual(metrics["screenHeight"], 1108)

    def test_skip_metrics_sets_no_viewport(self):
        driver = FakeDriver()
        DP.apply_to_driver(driver, FP.generate(seed=42), skip_metrics=True)
        methods = [call[0] for call in driver.calls]
        self.assertNotIn("Emulation.setDeviceMetricsOverride", methods)
        self.assertNotIn("Emulation.setTouchEmulationEnabled", methods)
        # The user-agent must still go in before the first navigation.
        self.assertIn("Network.setUserAgentOverride", methods)
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", methods)


if __name__ == "__main__":
    unittest.main()
