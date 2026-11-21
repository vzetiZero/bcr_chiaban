# -*- coding: utf-8 -*-
"""Regression tests: attach to a manager's Chrome whose build differs from the
installed Chrome.

OmniLogin ships its own Chrome (observed 157.0.8103.38) while the machine has
Chrome 158. Selenium Manager resolved a 158 chromedriver, so attaching raised:

    SessionNotCreatedException: This version of ChromeDriver only supports
    Chrome version 158 / Current browser version is 157.0.8103.38

The adapter must read the real major version from CDP and pass it as the
``browserVersion`` capability so the matching driver is selected.
"""

import inspect
import re
import unittest

from aibcr.adapters import browser as BR


class CdpBrowserVersionTest(unittest.TestCase):
    def _session_with(self, payload, error=None):
        session = BR.BrowserSession()

        class FakeResponse:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_args):
                return False

            def read(self_inner):
                import json
                return json.dumps(payload).encode()

        def fake_urlopen(url, timeout=None):
            if error:
                raise error
            return FakeResponse()

        original = BR.urlopen
        BR.urlopen = fake_urlopen
        self.addCleanup(setattr, BR, "urlopen", original)
        return session

    def test_major_version_is_parsed_from_browser_string(self):
        session = self._session_with({"Browser": "Chrome/157.0.8103.38"})
        self.assertEqual(session._cdp_browser_version(9232), "157")

    def test_newer_build_still_yields_its_major(self):
        session = self._session_with({"Browser": "Chrome/158.0.8127.36"})
        self.assertEqual(session._cdp_browser_version(9232), "158")

    def test_missing_browser_key_returns_empty(self):
        session = self._session_with({})
        self.assertEqual(session._cdp_browser_version(9232), "")

    def test_unreachable_endpoint_returns_empty(self):
        session = self._session_with({}, error=OSError("refused"))
        self.assertEqual(session._cdp_browser_version(9232), "")

    def test_non_numeric_version_returns_empty(self):
        session = self._session_with({"Browser": "HeadlessChrome/beta"})
        self.assertEqual(session._cdp_browser_version(9232), "")


class AttachVersionHintTest(unittest.TestCase):
    def test_attach_passes_the_detected_version(self):
        source = inspect.getsource(BR.BrowserSession.attach_external)
        self.assertIn("_cdp_browser_version(port)", source)
        self.assertIn("opts.browser_version = major", source)

    def test_hint_is_optional(self):
        source = inspect.getsource(BR.BrowserSession.attach_external)
        # A failure to read the version must not block attaching.
        self.assertIn("if major:", source)

    def test_attach_still_never_quits_the_managed_browser(self):
        source = inspect.getsource(BR.BrowserSession.attach_external)
        self.assertNotIn("driver.quit()", source)

    def test_attach_documents_the_version_mismatch(self):
        doc = (BR.BrowserSession.attach_external.__doc__ or "").lower()
        self.assertIn("omnilogin", doc)
        self.assertIn("sessionnotcreatedexception", doc)


if __name__ == "__main__":
    unittest.main()
