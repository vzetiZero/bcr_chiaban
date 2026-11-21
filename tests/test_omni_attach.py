# -*- coding: utf-8 -*-
"""Regression tests for the OmniLogin attach path.

The user reported that Chrome opened by OmniLogin closed immediately instead of
running the Selenium workflow. Three separate defects caused that:

1. ``_cdp_pages`` rejected ``about:blank`` targets, so a freshly attached
   profile had no drivable tab and window resizing failed.
2. ``site_open`` used ``driver.get`` for external profiles. That blocks until
   ``PAGE_LOAD_TIMEOUT`` and raises on slow sites.
3. Whenever navigation "failed", the UI called ``stopOmniProfile`` which asks
   OmniLogin to kill the browser process the user just watched open.
"""

import inspect
import io
import os
import re
import unittest

from aibcr.adapters import browser as BR
from aibcr.controllers import baccarat as BC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CdpPageFilterTest(unittest.TestCase):
    def test_blank_tabs_are_kept(self):
        """A fresh managed profile sits on about:blank or chrome://newtab/ and
        must stay drivable, otherwise no tab can be navigated."""
        session = BR.BrowserSession()
        session._cdp_json = lambda resource: [
            {"type": "page", "id": "A", "url": "about:blank",
             "webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/page/A" % BR.CDP_PORT},
            {"type": "page", "id": "B", "url": "chrome://newtab/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/page/B" % BR.CDP_PORT},
        ]
        pages = session._cdp_pages()
        self.assertEqual([page["id"] for page in pages], ["A", "B"])

    def test_browser_internal_surfaces_are_skipped(self):
        session = BR.BrowserSession()
        session._cdp_json = lambda resource: [
            {"type": "page", "id": "X", "url": "chrome-extension://abc/page.html",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/X"},
            {"type": "page", "id": "Y", "url": "devtools://devtools/bundled/x.html",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/Y"},
            {"type": "page", "id": "Z", "url": "https://site.example/lobby",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/Z"},
        ]
        pages = session._cdp_pages()
        self.assertEqual([page["id"] for page in pages], ["Z"])

    def test_non_page_targets_are_skipped(self):
        session = BR.BrowserSession()
        session._cdp_json = lambda resource: [
            {"type": "service_worker", "id": "SW", "url": "https://site.example/sw.js"},
            {"type": "page", "id": "P", "url": "about:blank",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/P"},
        ]
        self.assertEqual([page["id"] for page in session._cdp_pages()], ["P"])


class SiteOpenNavigationTest(unittest.TestCase):
    def test_external_profiles_navigate_over_cdp_not_driver_get(self):
        source = inspect.getsource(BC.BaccaratController.site_open)
        external_block = source[source.index("external_browser"):]
        external_block = external_block[:external_block.index("if self.browser.connected")]
        self.assertIn("self.browser.navigate(url)", external_block)
        # driver.get blocks for PAGE_LOAD_TIMEOUT and raises on slow pages.
        self.assertNotIn("driver.get(", external_block)

    def test_navigation_uses_page_navigate_cdp_command(self):
        source = inspect.getsource(BR.BrowserSession.navigate)
        self.assertIn("Page.navigate", source)

    def test_navigate_reports_failure_without_closing_the_browser(self):
        source = inspect.getsource(BR.BrowserSession.navigate)
        self.assertNotIn("quit()", source)
        self.assertNotIn("terminate", source)


class ProfileStopIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(ROOT, "ui", "main.js"), encoding="utf-8") as handle:
            cls.main_js = handle.read()

    def test_single_open_keeps_the_profile_on_navigation_failure(self):
        start = self.main_js.index("const navigated = await engine.call('site.open'")
        block = self.main_js[start:]
        # The failure branch ends where the success branch registers the profile.
        block = block[:block.index("if (omni) {")]
        self.assertIn("keepProfile: true", block)
        self.assertNotIn("stopOmniProfile", block)

    def test_group_open_does_not_stop_managed_profiles_on_nav_failure(self):
        marker = "const reply = await engine.call('site.open'"
        block = self.main_js[self.main_js.index(marker):]
        block = block[:block.index("return { ...reply")]
        self.assertNotIn("stopOmniProfile", block)
        self.assertIn("activeProfileIndices.add(profileIndex)", block)

    def test_detach_does_not_kill_chrome(self):
        source = inspect.getsource(BR.BrowserSession.stop)
        external_block = source[source.index("external_browser"):]
        external_block = external_block[:external_block.index("driver, self.driver = self.driver, None")]
        self.assertNotIn("driver.quit()", external_block)
        self.assertIn("service.stop()", external_block)

    def test_only_explicit_close_asks_the_manager_to_stop(self):
        # stopOmniProfile must remain reachable from the explicit close paths.
        self.assertIn("async function stopOmniProfile", self.main_js)
        close_block = self.main_js[
            self.main_js.index("ipcMain.handle('profile:close'"):]
        close_block = close_block[:close_block.index("ipcMain.handle", 30)]
        self.assertIn("stopOmniProfile", close_block)


if __name__ == "__main__":
    unittest.main()
