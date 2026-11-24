"""Lưu/khôi phục phiên đăng nhập site (cookie + localStorage)."""

import json
import os
import shutil
import tempfile
import unittest

from aibcr.adapters import session_store as SS


class FakeCookieDriver:
    def __init__(self, cookies=None, local=None, fail_add=False, url="about:blank"):
        self.cookies = list(cookies or [])
        self.local = dict(local or {})
        self.fail_add = fail_add
        self.added = []
        self.visited = []
        self.current_url = url

    def get_cookies(self):
        return self.cookies

    def add_cookie(self, item):
        if self.fail_add:
            raise RuntimeError("nope")
        self.added.append(item)

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def execute_script(self, script, *args):
        if "localStorage.setItem" in script:
            return len((args[0] if args else {}) or {})
        if "localStorage.key" in script:
            return dict(self.local)
        return None


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bcr-session-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_save_then_restore_round_trip(self):
        source = FakeCookieDriver(cookies=[
            {"name": "sess", "value": "abc123", "domain": ".gk881.vip",
             "path": "/", "expiry": 1830055400, "secure": True,
             "httpOnly": True, "sameSite": "Lax", "size": 12},
        ], local={"token": "xyz"})
        saved = SS.save(source, self.dir, "gk881")
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["cookies"], 1)
        self.assertEqual(saved["local"], 1)

        target = FakeCookieDriver()
        restored = SS.restore(target, self.dir, "gk881", url="https://m.gk881.vip/")
        self.assertTrue(restored["ok"])
        self.assertEqual(restored["cookies"], 1)
        # Only the fields needed to rebuild the session are kept.
        cookie = target.added[0]
        self.assertEqual(cookie["name"], "sess")
        self.assertEqual(cookie["expiry"], 1830055400)
        self.assertNotIn("size", cookie)

    def test_saved_file_never_appears_in_describe(self):
        """The UI view must not leak the cookie value."""
        driver = FakeCookieDriver(cookies=[
            {"name": "sess", "value": "SECRET-TOKEN", "domain": ".gk881.vip"}],
            local={"k": "SECRET-LOCAL"})
        SS.save(driver, self.dir, "gk881")
        info = SS.describe(self.dir, "gk881")
        self.assertTrue(info["found"])
        self.assertEqual(info["cookies"], 1)
        text = json.dumps(info, ensure_ascii=False)
        self.assertNotIn("SECRET", text)
        self.assertIn("gk881.vip", text)

    def test_domain_filter_keeps_the_site_only(self):
        driver = FakeCookieDriver(cookies=[
            {"name": "a", "value": "1", "domain": ".gk881.vip"},
            {"name": "b", "value": "2", "domain": ".other.example"},
        ])
        saved = SS.save(driver, self.dir, "gk881", domains=["gk881"])
        self.assertEqual(saved["cookies"], 1)

    def test_restore_without_a_file_is_not_an_error(self):
        result = SS.restore(FakeCookieDriver(), self.dir, "missing")
        self.assertFalse(result["ok"])
        self.assertFalse(result["found"])

    def test_restore_navigates_when_the_tab_is_on_another_origin(self):
        """``about:blank`` rejects every cookie, so restore must load the site.

        Measured: a freshly launched profile sits on ``about:blank`` and
        ``add_cookie`` throws ``InvalidCookieDomainException`` for all cookies,
        which silently turned "restore session" into a no-op.
        """
        source = FakeCookieDriver(cookies=[
            {"name": "sess", "value": "v", "domain": ".gk881.vip"}])
        SS.save(source, self.dir, "gk881")
        target = FakeCookieDriver(url="about:blank")
        result = SS.restore(target, self.dir, "gk881", url="https://m.gk881.vip/")
        self.assertEqual(target.visited, ["https://m.gk881.vip/"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["cookies"], 1)

    def test_restore_keeps_an_open_dg_lobby(self):
        """Restoring must not navigate away from the DG table screen."""
        source = FakeCookieDriver(cookies=[
            {"name": "sess", "value": "v", "domain": ".gk881.vip"}])
        SS.save(source, self.dir, "gk881")
        live = "https://new-dd-cn.example.com/ddnewwap/index.html?token=x"
        target = FakeCookieDriver(url=live)
        result = SS.restore(target, self.dir, "gk881", url="https://m.gk881.vip/")
        self.assertEqual(target.visited, [], "không được điều hướng khỏi sảnh DG")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cookies"], 1)

    def test_restore_survives_cookie_rejection(self):
        source = FakeCookieDriver(cookies=[
            {"name": "sess", "value": "v", "domain": ".gk881.vip"}])
        SS.save(source, self.dir, "gk881")
        result = SS.restore(FakeCookieDriver(fail_add=True), self.dir, "gk881")
        self.assertFalse(result["ok"])
        self.assertTrue(result["found"])

    def test_corrupt_file_is_ignored(self):
        path = SS.session_path(self.dir, "gk881")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(SS.load(self.dir, "gk881"))
        self.assertEqual(SS.describe(self.dir, "gk881"), {"found": False})

    def test_file_lives_inside_the_profile_folder(self):
        """The profile folder is gitignored, so the session file is too."""
        path = SS.session_path(self.dir, "gk881")
        self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(self.dir)))

    def test_clear_removes_the_file(self):
        SS.save(FakeCookieDriver(cookies=[
            {"name": "a", "value": "b", "domain": ".gk881.vip"}]), self.dir, "gk881")
        self.assertTrue(SS.describe(self.dir, "gk881")["found"])
        self.assertTrue(SS.clear(self.dir, "gk881")["ok"])
        self.assertFalse(SS.describe(self.dir, "gk881")["found"])


if __name__ == "__main__":
    unittest.main()
