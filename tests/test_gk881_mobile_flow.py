# -*- coding: utf-8 -*-
"""GK881 mobile: the announcement dialogs and the Laya lobby cards.

REAL failures found by driving a live ``m.gk881.vip`` profile through CDP:

* The home page stacks Angular-CDK dialogs ("GK88 - THƯỞNG NGHÌN TỶ …" and
  "TIN TỨC MỚI NHẤT"). Their close control is
  ``<span class="close absolute …">X</span>`` — not a ``button`` — so the old
  selector list never matched and the dialog stayed on top of the page.
* While the backdrop is up a tap on the "DG Trực Tuyến" card lands on the
  backdrop instead, and the site bounces to ``/Maintenance`` or
  ``/Account/Login``. The flow then waited 45-75 s and reported
  "Chưa thấy frame game DG đang tải.".
* The mobile lobby (``ddnewwap``) keeps ``tableId``/``gameType``/``onlineNum``
  directly on the card node and draws its labels in child ``Text`` nodes
  ("Baccarat RB01"). It has no ``tableInfo`` wrapper and no ``enterMC``; it uses
  ``tableMC``. The old scan therefore saw an empty lobby even though
  "Baccarat RB01 … RB05" was on screen.
* The category strip must be preferred: a ``<li>ĐẠI LÝ</li>`` appears earlier in
  the DOM and matched the old "casino/…/đại lý" alias list first, navigating to
  the agent page (which demands a login) instead of opening Casino.
"""

import inspect
import threading
import time
import unittest

from aibcr.adapters import gk881 as GK


class MobileSiteDriver:
    """Minimal driver for the mobile flow: dialogs close only when tapped."""

    def __init__(self, dialogs=2, categories=None, card_after=1, login_after=None):
        self.handle = "site"
        self.window_handles = ["site"]
        self.current_url = "https://m.gk881.vip/"
        self.frame = None
        self.switch_to = FakeSwitch(self)
        self.dialogs = dialogs
        self.categories = categories if categories is not None else [
            "hot nhất", "casino", "nổ hũ", "bắn cá", "thể thao"]
        self.card_after = card_after
        self.login_after = login_after
        self.card_taps = 0
        self.close_calls = 0
        self.close_before_tap = []
        self.closed_labels = []

    def find_elements(self, by, selector):
        return []

    @property
    def current_window_handle(self):
        return self.handle

    def execute_script(self, script, *args):
        if "const ua = navigator.userAgent" in script:
            return {"mobileUa": True, "touch": 5, "ng": 0,
                    "categories": len(self.categories), "hub": False}
        if "cdk-overlay-backdrop" in script and "tôi biết rồi" in script:
            return self._close_layers()
        if "isHub" in script:
            return {"isHub": False, "categories": self.categories,
                    "providers": [], "dgText": True}
        # ``_login_page_state`` (wait-for-operator) asks for the same route/password
        # facts but with its own field names; ``_is_login_wall`` keeps the old one.
        if "onLoginRoute" in script:
            return self._login_page_state()
        if "getComputedStyle(node)" in script and "maintenance" in script:
            return self._wall_state()
        if "via: 'category-item'" in script:
            return {"ok": True, "label": "casino", "via": "category-item"}
        if "isDgLabel" in script:
            self.close_before_tap.append(self.close_calls)
            self.card_taps += 1
            if self.login_after is not None and self.card_taps >= self.login_after:
                self.current_url = ("https://m.gk881.vip/Account/Login"
                                    "?loginToGame=%2FAccount%2FLoginToSupplier")
                return {"ok": True, "label": "dg trực tuyến"}
            if self.card_taps <= self.card_after:
                return {"ok": False, "count": 3,
                        "labels": ["dg casino", "dg trực tuyến"]}
            self.current_url = ("https://m.gk881.vip/Account/LoginToSupplier"
                                "?SupplierType=DG")
            return {"ok": True, "label": "dg trực tuyến"}
        return None

    def _on_login(self):
        return "/Account/Login?" in self.current_url

    def _wall_state(self):
        path = self.current_url.split("?")[0]
        path = path[path.find("/", 8):] if path.startswith("http") else path
        low = path.lower()
        return {"path": low, "password": self._on_login(),
                "maintenance": "/maintenance" in low,
                "handoff": "logintosupplier" in low}

    def _login_page_state(self):
        path = self.current_url.split("?")[0]
        path = path[path.find("/", 8):] if path.startswith("http") else path
        low = path.lower()
        return {"path": low, "password": self._on_login(),
                "onLoginRoute": "/account/login" in low or "/maintenance" in low,
                "handoff": "logintosupplier" in low,
                "hasUserBox": self._on_login()}

    def _close_layers(self):
        self.close_calls += 1
        if self.dialogs <= 0:
            return {"closed": [], "backdrops": 0, "panes": 0}
        # One dialog closes per pass, exactly like the two stacked CDK panes.
        self.dialogs -= 1
        self.closed_labels.append("x")
        return {"closed": ["x"], "backdrops": self.dialogs, "panes": self.dialogs}


class FakeSwitch:
    def __init__(self, driver):
        self.driver = driver

    def window(self, handle):
        self.driver.handle = handle

    def default_content(self):
        self.driver.frame = None

    def frame(self, element):
        self.driver.frame = element


class MobileScriptTest(unittest.TestCase):
    """The scripts must cover the real markup that was found on the live site."""

    def test_close_script_targets_the_cdk_dialogs(self):
        js = GK._MOBILE_CLOSE_JS
        self.assertIn(".cdk-overlay-pane", js)
        self.assertIn(".cdk-overlay-backdrop", js)

    def test_close_script_reads_the_span_close_control(self):
        js = GK._MOBILE_CLOSE_JS
        # The live "X" control is <span class="close absolute top-[15px] …">.
        self.assertIn("'button, span, i, a, [class*=close], [class*=Close]'", js)
        self.assertIn("node.click()", js)

    def test_close_script_reports_leftover_layers(self):
        js = GK._MOBILE_CLOSE_JS
        self.assertIn("backdrops:", js)
        self.assertIn("panes:", js)

    def test_category_script_prefers_the_game_strip(self):
        js = GK._MOBILE_CATEGORY_JS
        self.assertIn("'.category-item'", js)
        self.assertIn("via: 'category-item'", js)
        # Agent/account rows must never be treated as a game category.
        for label in ("đại lý", "dai ly", "nạp tiền", "cskh"):
            self.assertIn(label, js)

    def test_category_script_lists_labels_for_diagnostics(self):
        self.assertIn("labels:", GK._MOBILE_CATEGORY_JS)

    def test_dg_card_script_ignores_the_table_marquee(self):
        js = GK._MOBILE_DG_CARD_JS
        # "DG CASINO <bàn> <số người>" is a running-table marquee, not a card.
        self.assertIn("text.length > 40", js)
        self.assertIn("isProviderCard", js)

    def test_dg_card_script_reports_visible_labels(self):
        self.assertIn("labels:", GK._MOBILE_DG_CARD_JS)


class LobbyScriptTest(unittest.TestCase):
    def test_mobile_cards_expose_the_id_on_the_node(self):
        js = GK.DG._DG_LOBBY_JS
        self.assertIn("'tableId'", js)
        self.assertIn("'onlineNum'", js)
        self.assertIn("'gameType'", js)

    def test_mobile_cards_are_named_from_child_text(self):
        js = GK.DG._DG_LOBBY_JS
        self.assertIn("collect", js)
        self.assertIn(r"\b(RB|SB|S)\s*\d+\b", js)

    def test_mobile_lobby_is_recognised_without_enter_mc(self):
        js = GK.DG._DG_STATE_JS
        self.assertIn("tableMC", js)
        self.assertIn("enterMC", js)
        self.assertIn("table_cards", js)

    def test_mobile_table_screen_is_recognised(self):
        """The phone table screen has no ``banker`` node, only a bet view."""
        js = GK.DG._DG_STATE_JS
        self.assertIn("betBtn", js)
        self.assertIn("betHandler", js)
        # A lobby that still reports cards must not win over a real bet view.
        self.assertIn("&& !inTable", js)


class MobileTableTest(unittest.TestCase):
    """The phone loader is ``ddnewwap`` and the card id lives on the node."""

    def test_phone_loader_is_recognised_as_dg(self):
        source = inspect.getsource(GK.DG._loader_url)
        self.assertIn('"ddnew" in (src or "").lower()', source)

    def test_loader_keeps_the_phone_folder(self):
        url = GK.DG._loader_url(
            "https://m.gk881.vip/Account/LoginToSupplier?SupplierType=DG",
            "https://new-dd-cn.example.com/ddnewwap/index.html?token=T",
            "60102")
        self.assertIn("/ddnewwap/index.html", url)
        self.assertNotIn("direct1.html", url)
        self.assertIn("tableId=60102", url)

    def test_phone_loader_is_never_rewritten_to_direct1(self):
        """Measured live: ``ddnewwap/direct1.html`` is a 404 page with no Laya."""
        lobby = ("https://new-dd-cn.example.com/ddnewwap/index.html"
                 "?token=T&language=vi&tableId=&backUrl=x")
        url = GK.DG._loader_url(lobby, "", "60101")
        self.assertIn("/ddnewwap/index.html", url)
        self.assertNotIn("direct1.html", url)
        self.assertIn("tableId=60101", url)

    def test_desktop_loader_still_uses_direct1(self):
        url = GK.DG._loader_url(
            "https://new-dd-cn.example.com/ddnewpc/index.html?token=T", "", "60103")
        self.assertIn("/ddnewpc/direct1.html", url)
        self.assertIn("tableId=60103", url)

    def test_laya_enter_matches_the_table_id_attribute(self):
        js = GK.DG._LAYA_ENTER_JS
        self.assertIn("node.tableId", js)
        self.assertIn("idOf", js)
        # The phone card draws "Baccarat RB01"; the id is not in any text node.
        self.assertIn("textsOf", js)

    def test_dg_context_reads_the_phone_tab(self):
        source = inspect.getsource(GK.DG._dg_context)
        self.assertIn('"ddnew" in location.lower()', source)

    def test_dg_window_reads_the_phone_tab(self):
        source = inspect.getsource(GK.DG._dg_window)
        self.assertIn('"ddnew" in url', source)


class LoginWallTest(unittest.TestCase):
    def test_login_form_is_detected(self):
        driver = MobileSiteDriver()
        self.assertFalse(GK._is_login_wall(driver))
        driver.current_url = "https://m.gk881.vip/Account/Login?loginToGame=x"
        self.assertTrue(GK._is_login_wall(driver))

    def test_maintenance_page_is_detected(self):
        driver = MobileSiteDriver()
        driver.current_url = "https://m.gk881.vip/Maintenance?code=siteInfo"
        self.assertTrue(GK._is_login_wall(driver))

    def test_dg_hand_off_page_is_not_a_login_wall(self):
        """``/Account/LoginToSupplier`` shares the /account/login prefix."""
        driver = MobileSiteDriver()
        driver.current_url = ("https://m.gk881.vip/Account/LoginToSupplier"
                              "?SupplierType=DG")
        self.assertFalse(GK._is_login_wall(driver))


class MobileFlowTest(unittest.TestCase):
    def setUp(self):
        self.original_lobby = GK.DG.lobby_tables
        self.original_promote = GK.DG.promote_lobby_to_tab
        self.original_wait = GK._LOGIN_WAIT
        self.original_grace = GK._LOGIN_GRACE
        GK.DG.promote_lobby_to_tab = lambda *a, **k: {"ok": False}

    def tearDown(self):
        GK.DG.lobby_tables = self.original_lobby
        GK.DG.promote_lobby_to_tab = self.original_promote
        GK._LOGIN_WAIT = self.original_wait
        GK._LOGIN_GRACE = self.original_grace

    def _lobby_after(self, taps, tables=None):
        driver_box = {}

        def fake_lobby(driver, wait=0):
            if driver.card_taps >= taps:
                return {"ok": True, "tables": tables or [
                    {"table_id": "60101", "name": "Baccarat RB01", "online": 309}]}
            return {"ok": False, "error": "Laya đã tải nhưng chưa tìm thấy bàn."}

        return fake_lobby

    def test_dialogs_are_cleared_before_every_card_tap(self):
        driver = MobileSiteDriver(dialogs=3, card_after=1)
        GK.DG.lobby_tables = self._lobby_after(1)
        result = GK.open_dg(driver, wait=20)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["layout"], "mobile")
        self.assertTrue(driver.close_before_tap)
        # The backdrop was gone before the successful card tap.
        self.assertGreaterEqual(driver.close_before_tap[-1], 3)

    def test_login_wall_waits_for_the_operator_then_continues(self):
        """A login form must be waited on, not turned into a hard failure."""
        driver = MobileSiteDriver(dialogs=0, card_after=0, login_after=1)
        GK._LOGIN_WAIT = 6.0
        GK._LOGIN_GRACE = 0.2
        GK.DG.lobby_tables = self._lobby_after(1)

        def sign_in_later():
            # The operator signs in after ~2 s; the run must then continue.
            time.sleep(2.0)
            driver.current_url = ("https://m.gk881.vip/Account/LoginToSupplier"
                                  "?SupplierType=DG")

        threading.Thread(target=sign_in_later, daemon=True).start()
        result = GK.open_dg(driver, wait=60)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["layout"], "mobile")
        self.assertEqual(result["tables"][0]["table_id"], "60101")

    def test_login_wait_gives_the_budget_back(self):
        """Time spent waiting for a human must not eat the site timeout."""
        driver = MobileSiteDriver(dialogs=0, card_after=0, login_after=1)
        GK._LOGIN_WAIT = 20.0
        GK._LOGIN_GRACE = 0.2
        GK.DG.lobby_tables = self._lobby_after(1)

        def sign_in_slowly():
            time.sleep(4.0)
            driver.current_url = ("https://m.gk881.vip/Account/LoginToSupplier"
                                  "?SupplierType=DG")

        threading.Thread(target=sign_in_slowly, daemon=True).start()
        # A budget far smaller than the wait: extending it is what lets the run
        # finish instead of dying on "no provider card" right after sign-in.
        result = GK.open_dg(driver, wait=4)
        self.assertTrue(result["ok"], result.get("error"))

    def test_login_timeout_names_the_cause(self):
        driver = MobileSiteDriver(dialogs=0, card_after=0, login_after=1)
        GK._LOGIN_WAIT = 2.0
        GK._LOGIN_GRACE = 0.2
        GK.DG.lobby_tables = self._lobby_after(99)
        result = GK.open_dg(driver, wait=30)
        self.assertFalse(result["ok"])
        self.assertIn("đăng nhập", result["error"])

    def test_transient_login_redirect_still_reaches_the_lobby(self):
        """``/Account/Login?loginToGame=…`` resolves by itself; keep waiting."""
        driver = MobileSiteDriver(dialogs=0, card_after=0, login_after=1)

        def fake_lobby(current, wait=0):
            if "/Account/Login?" in current.current_url:
                # The site continues on its own to the DG hand-off page.
                current.current_url = ("https://m.gk881.vip/Account/LoginToSupplier"
                                       "?SupplierType=DG")
                return {"ok": False, "error": "Laya chưa tải xong."}
            if "LoginToSupplier" not in current.current_url:
                return {"ok": False, "error": "Laya chưa tải xong."}
            return {"ok": True, "tables": [
                {"table_id": "60101", "name": "Baccarat RB01", "online": 12}]}

        GK.DG.lobby_tables = fake_lobby
        result = GK.open_dg(driver, wait=40)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["layout"], "mobile")
        self.assertEqual(result["tables"][0]["table_id"], "60101")

    def test_missing_provider_card_lists_what_is_visible(self):
        driver = MobileSiteDriver(dialogs=0, card_after=99)
        GK.DG.lobby_tables = self._lobby_after(99)
        result = GK.open_dg(driver, wait=3)
        self.assertFalse(result["ok"])
        self.assertIn("DreamGaming", result["error"])

    def test_unmounted_lobby_reports_the_scan_error(self):
        driver = MobileSiteDriver(dialogs=0, card_after=0)
        GK.DG.lobby_tables = self._lobby_after(99)
        result = GK.open_dg(driver, wait=5)
        self.assertFalse(result["ok"])
        self.assertIn("Laya", result["error"])


class ClosePopupTest(unittest.TestCase):
    def test_close_loops_until_the_backdrop_is_gone(self):
        driver = MobileSiteDriver(dialogs=4)
        closed = GK.close_mobile_popups(driver, rounds=8)
        self.assertEqual(driver.dialogs, 0)
        self.assertEqual(len(closed), 4)

    def test_close_stops_when_nothing_is_left(self):
        driver = MobileSiteDriver(dialogs=0)
        self.assertEqual(GK.close_mobile_popups(driver, rounds=5), [])
        self.assertEqual(driver.close_calls, 1)

    def test_open_dg_still_keeps_the_desktop_entry(self):
        source = inspect.getsource(GK.open_dg)
        self.assertIn('_MOBILE_CATEGORY_JS, "casino"', source)
        self.assertIn("login_gate", source)


if __name__ == "__main__":
    unittest.main()
