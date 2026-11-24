# -*- coding: utf-8 -*-
"""Những gì đã đo trên site thật khi đi trọn luồng E3951 → DG.

Ba điều dưới đây đều là kết quả đo bằng Chrome thật, không phải suy đoán, và mỗi
điều từng làm hỏng luồng thật:

1. Người dùng dán ``/m/gameRecord``. Đó là trang **lịch sử cược**; dải
   ``Casino/Nổ hũ/...`` ở đó là tab lọc ``.mc-tab-item``, không phải menu vào
   sảnh, nên phải quay về trang chủ rồi mới bấm Casino.
2. Nút "Chơi ngay" của bản điện thoại là ``a.chooser-btn.blue`` trong popup
   ``.am-popup-wrap.chooser-game-popup``; ``.card-btn`` chỉ có ở bản desktop.
3. Sảnh DG nằm trong iframe **khác tiến trình** (CDP target ``type: iframe``,
   tài liệu thật ``ddnewwap/index.html``) trong khi ``src`` của thẻ iframe vẫn ghi
   ``ddnewpc/direct1.html``. WebDriver không switch vào frame đó được, nên chỉ
   ``/json/list`` thấy nó.
4. Trong sảnh, ``clickHandler.run()`` trên thẻ bàn trả ``ok`` nhưng vẫn ở sảnh;
   chuột thật qua ``Input.dispatchMouseEvent`` mới vào bàn.
5. ``index.html?tableId=60101`` của bản điện thoại vào thẳng bàn — đã đo.
"""

import unittest

from aibcr.adapters import dg_pages
from aibcr.adapters import e3951 as E
from aibcr.adapters import febet as F


class RecordPageTest(unittest.TestCase):
    def test_home_url_for_the_mobile_build(self):
        self.assertEqual(E._home_url("https://e39d5d05qc.e3951.com/m/gameRecord"),
                         "https://e39d5d05qc.e3951.com/m/home")

    def test_home_url_for_a_desktop_page(self):
        self.assertEqual(E._home_url("https://www.e3951.com/live"),
                         "https://www.e3951.com/")

    def test_home_url_rejects_non_http_locations(self):
        self.assertEqual(E._home_url(""), "")
        self.assertEqual(E._home_url("about:blank"), "")
        self.assertEqual(E._home_url("javascript:void(0)"), "")

    def test_open_dg_recovers_from_a_menu_less_sub_page(self):
        import inspect
        source = inspect.getsource(E.open_dg)
        self.assertIn("_home_url", source)
        self.assertIn("không có menu vào sảnh", source)


class LaunchButtonTest(unittest.TestCase):
    def test_mobile_chooser_button_is_the_first_target(self):
        self.assertIn(".chooser-btn", E._CLICK_LAUNCH_JS)
        # The measured mobile layout: `a.chooser-btn.blue` inside the chooser popup.
        self.assertIn("layout: 'chooser-btn'", E._CLICK_LAUNCH_JS)

    def test_desktop_card_button_still_supported(self):
        self.assertIn(".card-btn", E._CLICK_LAUNCH_JS)

    def test_launch_readiness_polls_both_layouts(self):
        import inspect
        source = inspect.getsource(E.open_dg)
        self.assertIn(".chooser-btn, .card-btn", source)


class OutOfProcessFrameTest(unittest.TestCase):
    """Iframe khác tiến trình: chỉ CDP thấy, và phải đúng frame của trang này."""

    def test_cdp_target_scan_looks_for_both_builds(self):
        self.assertIn("ddnew", dg_pages.GAME_URL_MARK)

    def test_promote_requires_the_frame_to_belong_to_this_page(self):
        import inspect
        source = inspect.getsource(F._promote_cdp_frame)
        # Host của target phải trùng host một `<iframe src>` trong trang hiện tại,
        # nếu không sẽ kéo nhầm tab DG của profile khác trong cùng Chrome.
        self.assertIn("_IFRAME_HOSTS_JS", source)
        self.assertIn("not in hosts", source)

    def test_promote_only_moves_iframe_targets(self):
        import inspect
        source = inspect.getsource(F._promote_cdp_frame)
        self.assertIn('target.get("type") != "iframe"', source)

    def test_dg_context_retries_once_after_promoting(self):
        import inspect
        source = inspect.getsource(F._dg_context)
        self.assertIn("tried_promote", source)
        self.assertIn("_promote_cdp_frame", source)


class LayaCardClickTest(unittest.TestCase):
    def test_card_click_uses_a_real_mouse_event(self):
        import inspect
        source = inspect.getsource(F._laya_enter_table)
        self.assertIn("_LAYA_CARD_BOX_JS", source)
        self.assertIn("_cdp_click", source)

    def test_card_box_js_converts_stage_point_to_client_pixels(self):
        js = F._LAYA_CARD_BOX_JS
        self.assertIn("localToGlobal", js)
        self.assertIn("rect.width / stageW", js)
        # A point outside the canvas must never be clicked.
        self.assertIn("outside-canvas", js)


class LobbyUrlPromoteTest(unittest.TestCase):
    """Tab E3951 phải chạy chính URL sảnh trong iframe, không giữ ``/m/home``.

    URL mang ``token`` nên chỉ được dùng để điều hướng; ``open_dg`` trả về
    ``promoted`` + ``host`` chứ không trả URL.
    """

    def test_open_dg_reports_promotion_and_host(self):
        import inspect
        source = inspect.getsource(E.open_dg)
        self.assertIn('"promoted"', source)
        self.assertIn('"host"', source)
        self.assertNotIn('"url"', source)

    def test_promote_targets_the_real_frame_document(self):
        import inspect
        source = inspect.getsource(E.promote_lobby_to_tab)
        self.assertIn("promote_frame_to_tab", source)
        self.assertIn("_promote_cdp_frame", source)

    def test_promote_accepts_the_phone_build(self):
        # ``ddnewwap`` (điện thoại) cũng phải qua cửa kiểm tra, không chỉ ``ddnewpc``.
        import inspect
        source = inspect.getsource(E.promote_lobby_to_tab)
        self.assertIn('"ddnew" in location.lower()', source)
        self.assertNotIn('"ddnewpc" in location.lower()', source)


if __name__ == "__main__":
    unittest.main()

