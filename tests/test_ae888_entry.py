# -*- coding: utf-8 -*-
"""Tests for the 888AE66 site-entry adapter.

Facts these tests lock in were measured live on 24/11/2026 with signed-in
profiles on ``https://www.888ae66.com``:

* The compact OmniLogin mobile home (400 × 783 CSS px, DPR 1.875) renders
  ``SÒNG BÀI`` as ``.home-quick-item.navigation-PRODUCT`` at x≈192; it does not
  use ``.nav-item.live``. Tapping it routes the SPA to ``/gamelobby/live``.
* Dream Gaming is the card whose ``img`` has ``alt="banner-dg"``. Its wrapping
  ``<li>`` carries an unrelated locale class (``vi-VN``), so the image alt is
  the only stable handle.
* Tapping that card opens Dream Gaming in a **separate tab**
  (``ddnewpc/index.html?...&token=…``), so a profile ends with two tabs.
* Closing the site tab leaves one tab that still holds the whole Laya stage
  (7979 nodes) and its session token — that is the one-tab rule the user asked
  for.
* Dream Gaming may block the lobby with a slider captcha ("Xác minh an toàn" /
  "Kéo thanh trượt sang phải") drawn as Laya nodes, invisible to the DOM. The
  tool must never solve it: it announces it and waits for the human.
"""

import unittest
from urllib.parse import urlsplit

from aibcr.adapters import ae888 as A
from aibcr.adapters import febet as DG


class FakeDriver:
    """Minimal WebDriver stand-in: window handles, switching and script replies."""

    def __init__(self, urls, script=None):
        self.urls = dict(urls)
        self.handles = list(urls)
        self.current = self.handles[0]
        self.script = script or (lambda text, args: None)
        self.navigated = []
        self.closed = []
        self.switch_to = self

    # ---- window plumbing -------------------------------------------------
    @property
    def window_handles(self):
        return list(self.handles)

    @property
    def current_window_handle(self):
        return self.current

    @property
    def current_url(self):
        return self.urls[self.current]

    def window(self, handle):
        if handle not in self.urls:
            raise RuntimeError("no such window")
        self.current = handle

    def default_content(self):
        return None

    def close(self):
        self.closed.append(self.current)
        self.handles.remove(self.current)
        self.urls.pop(self.current, None)
        self.current = self.handles[0]

    # ---- page scripting --------------------------------------------------
    def execute_script(self, text, *args):
        return self.script(text, args)

    def get(self, url):
        self.navigated.append(url)
        self.urls[self.current] = url


DG_URL = ("https://new-dd-cn.ahsy114.com/ddnewpc/index.html"
          "?backUrl=x&language=vi&showapp=off&token=SECRETTOKEN&type=4")
SITE_URL = "https://www.888ae66.com/gamelobby/live"


class SiteShapeTest(unittest.TestCase):
    def test_targets_the_measured_mobile_host(self):
        self.assertEqual(A.SITE_HOST, "888ae66.com")
        self.assertEqual(A._MOBILE_HOME, "/m")

    def test_live_route_matches_the_measured_navigation(self):
        js = A._LIVE_ROUTE_JS
        self.assertIn(".nav-item.live", js)
        self.assertIn(".home-quick-item", js)
        self.assertIn("[class*=navigation]", js)
        # Nhãn thật trên site là "SÒNG BÀI"; regex chấp nhận cả dấu và không dấu.
        self.assertIn("[oò]ng", js)

    def test_dream_gaming_card_is_found_by_the_measured_handles(self):
        js = A._LIVE_ROUTE_JS
        # Đo lại trên profile thật: thẻ DG là ``div.game-item.DG.customized`` và
        # ảnh bên trong có ``alt`` RỖNG — quy tắc cũ ``img[alt=banner-dg]`` không
        # khớp gì cả, nên luồng đứng ở sảnh và quét mãi.
        self.assertIn("live-dg", js)
        self.assertIn("game-item", js)
        self.assertIn("banner-dg", js)  # giữ cho bản site khác
        self.assertNotIn("vi-VN", js.split("return {")[0])

    def test_the_measured_markup_has_no_banner_dg_alt(self):
        # Hợp đồng với dữ liệu đo được: nếu ai đó "sửa" lại về alt=banner-dg thì
        # test này phải đỏ, vì trên site thật ảnh đó không có alt.
        js = A._LIVE_ROUTE_JS
        self.assertIn(r"/^banner-dg$/i.test(alt)", js)
        self.assertIn("|| /live-dg/i.test(src)", js)

    def test_popups_are_closed_by_their_own_close_button(self):
        js = A._LIVE_ROUTE_JS
        # Đo trên /gamelobby/live: popup là ``.nrc-modal`` và nút đóng là
        # ``div.iconClose``; không có bước này thì mọi cú bấm vào thẻ DG đều
        # rơi vào lớp phủ và luồng treo.
        self.assertIn(".nrc-", js)
        self.assertIn("iconClose", js)
        self.assertIn("closers", js)
        # Trang còn một ``div.close-button`` nằm ngoài màn hình ở (0,0) và các
        # chấm icon 12px; bấm bừa vào đó sẽ rời trang. Chỉ nhận nút thật sự
        # hit-test trúng tại toạ độ của nó.
        self.assertIn("elementFromPoint", js)
        self.assertIn("rect.width < 16", js)
        # Chỉ bấm nút đóng thật, không bấm nền mờ (bấm nền sẽ điều hướng đi).
        self.assertNotIn("target === currentTarget", js)

    def test_the_route_script_actually_returns_a_value(self):
        # Selenium chỉ trả giá trị khi script có ``return`` ở mức ngoài cùng.
        # Bọc trong IIFE không return khiến mọi lần đọc ra None và luồng báo
        # "chưa thấy thẻ DreamGaming" dù thẻ có trên trang.
        body = A._LIVE_ROUTE_JS.strip()
        self.assertFalse(body.startswith("(function"), body[:30])
        self.assertIn("\nreturn {", body)

    def test_the_card_is_scrolled_into_view_before_it_is_tapped(self):
        # ``/gamelobby/live`` cao ~4000px: thẻ DG đo được ở ``y≈2406`` trong khi
        # viewport chỉ 1103px. Bấm theo toạ độ viewport mà không cuộn thì cú bấm
        # rơi ra ngoài trang và luồng treo ở "chưa thấy thẻ DreamGaming".
        js = A._LIVE_ROUTE_JS
        self.assertIn("scrollIntoView", js)
        self.assertIn("block: 'center'", js)
        self.assertIn("bring(dgNode)", js)

    def test_login_gate_reads_the_header_button_only(self):
        js = A._LIVE_ROUTE_JS
        self.assertIn("button.header-btn.login", js)
        # Không đọc/ghi ô mật khẩu: người dùng tự đăng nhập.
        self.assertNotIn("password", js.lower())
        self.assertNotIn("value =", js)


class SafeLocationTest(unittest.TestCase):
    def test_never_exposes_the_session_token(self):
        class TokenDriver:
            current_url = DG_URL

        location = A._safe_location(TokenDriver())
        self.assertNotIn("token", location)
        self.assertNotIn("SECRETTOKEN", location)
        self.assertIn("ddnewpc", location)

    def test_falls_back_to_unknown_on_a_broken_url(self):
        class Broken:
            @property
            def current_url(self):
                raise RuntimeError("gone")

        self.assertEqual(A._safe_location(Broken()), "unknown")

    def test_reports_host_and_path_only(self):
        parsed = urlsplit(DG_URL)
        self.assertEqual(parsed.hostname, "new-dd-cn.ahsy114.com")
        self.assertNotIn(parsed.query, A._safe_location(type(
            "D", (), {"current_url": DG_URL})()))


class TabTidyTest(unittest.TestCase):
    def test_keeps_the_dg_tab_and_closes_the_site_tab(self):
        driver = FakeDriver({"site": SITE_URL, "dg": DG_URL})
        result = A.close_site_tabs(driver)
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], 1)
        self.assertEqual(result["tabs"], 1)
        self.assertEqual(driver.closed, ["site"])
        # Phiên WebDriver phải trỏ lại tab sảnh DG sau khi đóng.
        self.assertEqual(driver.current, "dg")

    def test_reports_an_error_when_no_dg_tab_exists(self):
        driver = FakeDriver({"site": SITE_URL})
        result = A.close_site_tabs(driver)
        self.assertFalse(result["ok"])
        self.assertEqual(result["closed"], 0)
        self.assertEqual(driver.closed, [])

    def test_keep_only_dg_drops_the_launchgame_leftover(self):
        # Sau khi sảnh đã vẽ (Laya có bàn), tab ``/launchgame`` còn sót lại chỉ là
        # rác của lần redirect — người dùng yêu cầu đúng **một** tab.
        driver = FakeDriver({"dg": DG_URL,
                             "boot": "https://www.888ae66.com/launchgame?code=abc",
                             "site": SITE_URL})
        result = A.close_site_tabs(driver, keep_only_dg=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tabs"], 1)
        self.assertEqual(sorted(driver.closed), ["boot", "site"])
        self.assertEqual(driver.current, "dg")

    def test_keep_only_dg_never_closes_the_preferred_dg_tab(self):
        # Có hai tab DG (bấm thẻ hai lần): giữ tab đang đọc được sảnh.
        other = DG_URL.replace("ddnewpc", "ddnewpc") + "&again=1"
        driver = FakeDriver({"dg": DG_URL, "dg2": other, "site": SITE_URL})
        result = A.close_site_tabs(driver, keep_only_dg=True, prefer="dg")
        self.assertTrue(result["ok"])
        self.assertEqual(driver.handles, ["dg"])
        self.assertEqual(driver.current, "dg")

    def test_dg_tab_is_never_closed(self):
        driver = FakeDriver({"dg": DG_URL, "promo": "https://www.888ae66.com/promo"})
        A.close_site_tabs(driver)
        self.assertNotIn("dg", driver.closed)
        self.assertEqual(driver.handles, ["dg"])

    def test_launchgame_tab_is_kept_until_it_becomes_the_lobby(self):
        # Đo trên 888AE66: bấm thẻ DG mở ``/launchgame`` trước, rồi tab đó mới
        # thành ``ddnewpc/index.html``. Đóng nó như "tab site" là giết sảnh.
        self.assertTrue(A._is_dg_candidate("https://www.888ae66.com/launchgame?x=1"))
        self.assertTrue(A._is_dg_candidate(DG_URL))
        self.assertFalse(A._is_dg_candidate(SITE_URL))
        driver = FakeDriver({"dg": DG_URL,
                             "boot": "https://www.888ae66.com/launchgame?code=abc",
                             "site": SITE_URL})
        result = A.close_site_tabs(driver)
        self.assertEqual(driver.closed, ["site"])
        self.assertEqual(result["closed"], 1)
        self.assertFalse(result["ok"])  # vẫn còn 2 tab: sảnh + launchgame
        self.assertEqual(result["tabs"], 2)


class SiteTabPickTest(unittest.TestCase):
    """Tab DG chứa ``backUrl=…888ae66.com…`` nên không được nhận là tab site."""

    def test_the_dg_tab_is_never_chosen_as_the_site_tab(self):
        driver = FakeDriver({"sg": DG_URL, "site": SITE_URL})
        handle = A._site_source_handle(driver)
        self.assertEqual(handle, "site")

    def test_a_launchgame_tab_is_not_driven_as_the_site_either(self):
        driver = FakeDriver({"boot": "https://www.888ae66.com/launchgame?c=1",
                             "site": SITE_URL})
        self.assertEqual(A._site_source_handle(driver), "site")

    def test_falls_back_to_a_non_dg_tab(self):
        driver = FakeDriver({"dg": DG_URL})
        # Chỉ còn tab DG (sảnh đã mở, tab site đã đóng): không có tab nào để
        # chạy script điều hướng của site, nên trả None thay vì trả tab DG và
        # chạy menu của site trên chính sảnh game.
        self.assertIsNone(A._site_source_handle(driver))


class OpenDgTest(unittest.TestCase):
    def test_rejects_a_missing_driver(self):
        result = A.open_dg(None, wait=5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["site_id"], "888ae66")

    def test_reuses_an_open_lobby_without_touching_the_table(self):
        driver = FakeDriver({"site": SITE_URL, "dg": DG_URL})
        original_context = DG._dg_context
        original_tables = DG.lobby_tables
        DG._dg_context = lambda drv, wait=0: {"mode": "tab", "location": DG_URL}
        DG.lobby_tables = lambda drv, wait=0, log=None: {
            "ok": True, "in_table": True, "table_id": "60101",
            "tables": [{"table_id": "60101", "name": "RB01", "online": 0}]}
        try:
            result = A.open_dg(driver, wait=10)
        finally:
            DG._dg_context = original_context
            DG.lobby_tables = original_tables
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_open"])
        self.assertTrue(result["in_table"])
        self.assertEqual(result["tabs"], 1)
        # Không rời bàn, không nạp lại trang.
        self.assertEqual(driver.navigated, [])

    def test_a_captcha_stops_the_flow_instead_of_reporting_success(self):
        driver = FakeDriver({"site": SITE_URL, "dg": DG_URL})
        original_context = DG._dg_context
        original_wait = DG.wait_for_captcha
        DG._dg_context = lambda drv, wait=0: {"mode": "tab", "location": DG_URL}
        DG.wait_for_captcha = lambda drv, report=None, timeout=0, poll=0: {
            "ok": False, "waited": 1.0, "error": "Sảnh DG vẫn đang chờ captcha"}
        try:
            result = A.open_dg(driver, wait=10)
        finally:
            DG._dg_context = original_context
            DG.wait_for_captcha = original_wait
        self.assertFalse(result["ok"])
        self.assertTrue(result["captcha"])
        self.assertIn("captcha", result["error"])
        # Tab sảnh DG không bị đóng khi chưa vượt captcha.
        self.assertEqual(driver.closed, [])

    def test_an_unreadable_live_lobby_never_opens_a_second_dg_tab(self):
        # Sảnh đã mở nhưng lưới bàn chưa đọc được (Laya đang vẽ): mở lại game từ
        # site sẽ đẻ ra tab DG thứ hai trên cùng một phiên.
        driver = FakeDriver({"site": SITE_URL, "dg": DG_URL})
        original_context = DG._dg_context
        original_tables = DG.lobby_tables
        original_wait = DG.wait_for_captcha
        DG._dg_context = lambda drv, wait=0: {"mode": "tab", "location": DG_URL}
        DG.wait_for_captcha = lambda drv, report=None, timeout=0, poll=0: {
            "ok": True, "waited": 0.0}
        DG.lobby_tables = lambda drv, wait=0, log=None: {
            "ok": False, "error": "Laya đã tải nhưng chưa tìm thấy node bàn thật"}
        try:
            result = A.open_dg(driver, wait=10)
        finally:
            DG._dg_context = original_context
            DG.lobby_tables = original_tables
            DG.wait_for_captcha = original_wait
        self.assertFalse(result["ok"])
        self.assertIn("chưa tìm thấy node bàn thật", result["error"])
        # Không bấm gì trên site, không đóng tab nào.
        self.assertEqual(driver.closed, [])
        self.assertEqual(driver.handles, ["site", "dg"])


class PopupTest(unittest.TestCase):
    """Popup khuyến mãi phải được đóng trước khi bấm thẻ DG."""

    def test_close_popups_taps_the_close_control_once(self):
        clicks = []
        driver = FakeDriver({"site": "https://www.888ae66.com/gamelobby/live"})
        states = [
            {"overlays": ["nrc-modal fade-in"], "closers": [
                {"x": 788, "y": 174, "sel": "DIV.iconClose", "alt": ""}]},
            {"overlays": [], "closers": []},
        ]
        driver.script = lambda text, args: states.pop(0) if states else {
            "overlays": [], "closers": []}
        original = DG._cdp_click
        DG._cdp_click = lambda drv, x, y: clicks.append((x, y)) or True
        seen = []
        try:
            result = A.close_popups(driver, lambda text, level="info": seen.append(text))
        finally:
            DG._cdp_click = original
        self.assertEqual(result["closed"], 1)
        self.assertEqual(result["left"], 0)
        self.assertEqual(clicks, [(788, 174)])
        self.assertTrue(any("iconClose" in text for text in seen))

    def test_close_popups_does_nothing_when_the_page_is_clean(self):
        clicks = []
        driver = FakeDriver({"site": SITE_URL})
        driver.script = lambda text, args: {"overlays": [], "closers": []}
        original = DG._cdp_click
        DG._cdp_click = lambda drv, x, y: clicks.append((x, y)) or True
        try:
            result = A.close_popups(driver)
        finally:
            DG._cdp_click = original
        self.assertEqual(result["closed"], 0)
        self.assertEqual(clicks, [])

    def test_a_popup_that_cannot_be_closed_is_reported_not_clicked_through(self):
        # Popup mở lại liên tục (carousel): báo đúng bước "đóng popup" thay vì
        # để luồng quét "chưa vào sảnh DG" mãi.
        driver = FakeDriver({"site": "https://www.888ae66.com/gamelobby/live"})
        state = {"overlays": ["nrc-modal fade-in"],
                 "closers": [{"x": 788, "y": 174, "sel": "DIV.iconClose"}]}
        driver.script = lambda text, args: state
        original_click = DG._cdp_click
        original_context = DG._dg_context
        DG._cdp_click = lambda drv, x, y: True
        DG._dg_context = lambda drv, wait=0: None
        try:
            result = A.open_dg(driver, wait=3)
        finally:
            DG._cdp_click = original_click
            DG._dg_context = original_context
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "đóng popup")
        self.assertIn("popup", result["error"])


class LayoutMatchTest(unittest.TestCase):
    """Khung DG của 888AE66 là OOPIF, không phải tab mới."""

    def test_the_lobby_is_promoted_from_the_cdp_frame(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "aibcr" / "adapters" / "ae888.py").read_text(encoding="utf-8")
        # Đo trên Chrome thật: tab site tự chuyển sang /launchgame rồi sảnh chạy
        # trong iframe khác tiến trình ``ddnewwap``. Không có bước này thì không
        # bao giờ có "tab ddnew" để chờ, và luồng báo lỗi dù sảnh đã mở.
        self.assertIn("find_game_frame", source)
        self.assertIn("promote_frame_to_tab", source)
        self.assertIn("ddnewwap", source)


class CaptchaPolicyTest(unittest.TestCase):
    """Người dùng tự kéo thanh trượt; tool chỉ báo động và chờ."""

    def test_blocking_wording_is_recognised(self):
        for text in ("Xác minh an toàn", "Kéo thanh trượt sang phải",
                     "xac minh an toan", "keo thanh truot",
                     # Bản Laya mới vẽ captcha bằng tiếng Anh (đo 25/11/2026).
                     "SafetyVerify", "Drag the slider"):
            self.assertTrue(DG._CAPTCHA_BLOCK_RE.search(text), text)

    def test_success_wording_is_not_treated_as_a_block(self):
        self.assertFalse(DG._CAPTCHA_BLOCK_RE.search("Xác minh thành công"))
        self.assertTrue(DG._CAPTCHA_PASS_RE.search("Xác minh thành công"))
        self.assertFalse(DG._CAPTCHA_BLOCK_RE.search("Verified successfully"))
        self.assertTrue(DG._CAPTCHA_PASS_RE.search("Verified successfully"))

    def test_captcha_probe_reads_the_laya_tree_not_only_the_dom(self):
        # Đo trên 888AE66: lúc thanh trượt hiện, DOM rỗng -> chỉ soi DOM sẽ sai.
        js = DG._DG_CAPTCHA_JS
        self.assertIn("Laya.stage", js)
        self.assertIn("numChildren", js)
        self.assertIn("domText", js)

    def test_the_probe_never_attempts_to_solve(self):
        for name in ("_DG_CAPTCHA_JS",):
            js = getattr(DG, name)
            for forbidden in ("dispatchMouseEvent", "Input.", "drag", "pointerdown"):
                self.assertNotIn(forbidden, js)

    def test_waiting_ends_as_soon_as_the_slider_is_gone(self):
        states = [{"blocked": True, "text": "Kéo thanh trượt sang phải"},
                  {"blocked": True, "text": "Kéo thanh trượt sang phải"},
                  {"blocked": False, "text": ""}]
        original = DG.captcha_state
        DG.captcha_state = lambda driver: states.pop(0) if states else {"blocked": False}
        seen = []
        try:
            result = DG.wait_for_captcha(None, lambda text, level="info": seen.append(level),
                                         timeout=5, poll=0)
        finally:
            DG.captcha_state = original
        self.assertTrue(result["ok"])
        # Chỉ một lần báo động (mức ``action``) dù captcha còn nhiều vòng poll;
        # dòng sau là thông báo tiến trình "đã vượt captcha", không hú còi.
        self.assertEqual(seen[0], "action")
        self.assertEqual(seen.count("action"), 1)

    def test_the_alarm_list_rings_for_the_slider(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "ui" / "renderer" / "alarm.js").read_text(encoding="utf-8")
        self.assertIn("'xác minh an toàn'", source)
        self.assertIn("'kéo thanh trượt'", source)
        # Captcha của bản Laya mới là tiếng Anh; thiếu hai mẫu này thì còi im.
        self.assertIn("'drag the slider'", source)
        self.assertIn("'safetyverify'", source)
        # Mức "action" phải đi qua được cửa chỉ-nhận-error.
        self.assertIn("actionLevel", source)

    def test_the_runner_uses_the_same_captcha_wording(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "ui" / "main.js").read_text(encoding="utf-8")
        self.assertIn("const CAPTCHA_NOTE_RE", source)
        self.assertIn("drag the slider", source)
        self.assertNotIn("/xác minh an toàn|kéo thanh trượt/i.test", source)


class ScriptSyntaxTest(unittest.TestCase):
    """Blob JS phải biên dịch được — sai một ngoặc là hỏng cả luồng live."""

    def test_every_ae888_script_compiles(self):
        import pathlib
        import shutil
        import subprocess
        import sys

        node = shutil.which("node")
        if not node:
            self.skipTest("không có node để kiểm cú pháp JS")
        root = pathlib.Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tools" / "check_js_syntax.py"), "ae888.py"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(root))
        self.assertEqual(result.returncode, 0,
                         (result.stdout or "") + (result.stderr or ""))
        self.assertIn("ok   ae888._LIVE_ROUTE_JS", result.stdout)


class RegistryTest(unittest.TestCase):
    def test_service_is_registered_for_the_site_id(self):
        from aibcr.service.sites import SITE_ENTRY_SERVICES

        self.assertIn("888ae66.openDG", SITE_ENTRY_SERVICES)

    def test_controller_is_wired_into_the_engine(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "aibcr" / "controllers" / "baccarat.py").read_text(
            encoding="utf-8-sig")
        self.assertIn("AE888EntryController", source)
        self.assertIn("self.ae888_entry", source)

    def test_ui_treats_the_site_as_automated(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "ui" / "main.js").read_text(encoding="utf-8")
        self.assertIn("'888ae66': '888ae66.openDG'", source)
        self.assertIn("AUTOMATED_SITE_IDS", source)

    def test_the_badge_uses_the_same_list_as_the_runner(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "ui" / "main.js").read_text(encoding="utf-8")
        declared = re.search(r"const AUTOMATED_SITE_IDS = Object\.freeze\(\[(.*?)\]\)",
                             source, re.S)
        self.assertIsNotNone(declared)
        self.assertIn("'888ae66'", declared.group(1))
        # `publicSites()` phải dựa vào danh sách đó: nếu hardcode lại, site mới
        # sẽ hiện "Thủ công" trong khi adapter của nó vẫn chạy.
        body = source[source.index("function publicSites()"):]
        body = body[:body.index("ipcMain.handle('app:info'")]
        self.assertIn("automation: AUTOMATED_SITE_IDS.includes(id)", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
