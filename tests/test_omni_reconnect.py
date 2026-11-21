# -*- coding: utf-8 -*-
"""Regression tests: a managed profile must expose a navigable tab, and the
OmniLogin connection must be remembered across app launches."""

import inspect
import io
import os
import unittest
import json

from aibcr.adapters import browser as BR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NavigablePageTest(unittest.TestCase):
    """OmniLogin's Chrome starts on chrome://newtab/, which used to be filtered
    out, so the engine reported "no Chrome tab to open the site"."""

    def _session(self, targets):
        session = BR.BrowserSession()
        session._cdp_json = lambda resource: targets
        return session

    def test_newtab_placeholder_is_navigable(self):
        session = self._session([
            {"type": "page", "id": "N", "url": "chrome://newtab/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9232/devtools/page/N"},
        ])
        self.assertEqual([p["id"] for p in session._cdp_pages()], ["N"])

    def test_about_blank_is_navigable(self):
        session = self._session([
            {"type": "page", "id": "B", "url": "about:blank",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/B"},
        ])
        self.assertEqual([p["id"] for p in session._cdp_pages()], ["B"])

    def test_browser_ui_targets_are_ignored(self):
        session = self._session([
            {"type": "browser_ui", "id": "U", "url": "chrome://omnibox-popup.top-chrome/"},
            {"type": "page", "id": "P", "url": "https://site.example/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/P"},
        ])
        self.assertEqual([p["id"] for p in session._cdp_pages()], ["P"])

    def test_extension_and_devtools_surfaces_are_ignored(self):
        session = self._session([
            {"type": "page", "id": "E", "url": "chrome-extension://abc/x.html",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/E"},
            {"type": "page", "id": "D", "url": "devtools://devtools/bundled/x.html",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/D"},
        ])
        self.assertEqual(session._cdp_pages(), [])

    def test_page_without_debugger_url_is_rejected(self):
        session = self._session([{"type": "page", "id": "X", "url": "https://site.example/"}])
        self.assertEqual(session._cdp_pages(), [])

    def test_real_omnilogin_target_shape_is_accepted(self):
        # Shape observed from OmniLogin profile 2 (Chrome 157).
        session = self._session([
            {"type": "page", "id": "BF98FA9DF287", "url": "chrome://newtab/",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9232/devtools/page/BF98FA9DF287"},
            {"type": "browser_ui", "id": "519937AC201F",
             "url": "chrome://omnibox-popup.top-chrome/"},
        ])
        pages = session._cdp_pages()
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["id"], "BF98FA9DF287")


class RememberedConnectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(ROOT, "ui", "main.js"), encoding="utf-8") as handle:
            cls.main_js = handle.read()
        with io.open(os.path.join(ROOT, "ui", "renderer", "app.js"), encoding="utf-8") as handle:
            cls.app_js = handle.read()
        with io.open(os.path.join(ROOT, "ui", "preload.js"), encoding="utf-8") as handle:
            cls.preload = handle.read()

    def test_connection_store_is_persisted(self):
        self.assertIn("profile-connections.json", self.main_js)
        self.assertIn("async function rememberOmniConnection", self.main_js)
        self.assertIn("async function loadOmniConnections", self.main_js)

    def test_successful_open_records_the_connection(self):
        self.assertIn("await rememberOmniConnection(profileIndex, omni", self.main_js)
        # The group path remembers each profile too.
        self.assertGreaterEqual(self.main_js.count("rememberOmniConnection("), 2)

    def test_explicit_close_forgets_the_connection(self):
        self.assertIn("await forgetOmniConnection(profileIndex)", self.main_js)
        self.assertIn("ipcMain.handle('profiles:forgetConnection'", self.main_js)

    def test_renderer_restores_on_boot(self):
        self.assertIn("await restoreRememberedConnections()", self.app_js)
        self.assertIn("async function restoreRememberedConnections", self.app_js)

    def test_restore_reloads_the_manager_profile_list(self):
        block = self.app_js[self.app_js.index("async function restoreRememberedConnections"):]
        block = block[:block.index("const restored = [];")]
        # Without fresh options the selects cannot show the saved ids.
        self.assertIn("api.listOmniProfiles", block)

    def test_restore_adopts_the_remembered_selection(self):
        block = self.app_js[self.app_js.index("async function restoreRememberedConnections"):]
        self.assertIn("selectedProfileIndices = [...new Set(restored)]", block)

    def test_ipc_exposes_connection_endpoints(self):
        self.assertIn("profiles:connections", self.main_js)
        self.assertIn("loadProfileConnections", self.preload)
        self.assertIn("forgetProfileConnection", self.preload)

    def test_connections_file_keeps_no_secrets(self):
        block = self.main_js[
            self.main_js.index("async function rememberOmniConnection"):]
        block = block[:block.index("async function forgetOmniConnection")]
        # Only routing identifiers are stored; never credentials or tokens.
        for forbidden in ("password", "token", "cookie", "secret"):
            self.assertNotIn(forbidden, block.lower())


if __name__ == "__main__":
    unittest.main()
