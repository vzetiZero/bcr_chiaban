# -*- coding: utf-8 -*-
"""Hai site khác nhau nhưng phải vào CÙNG một bàn DG — đo bằng Chrome thật.

Bối cảnh: người dùng chạy profile 1 = GK881 và profile 2 = E3951 (hai Chrome,
hai cổng CDP 9222/9223). Yêu cầu là cả hai phải ở chung một bàn, chung một ván.

Số đo ngày 24/11/2026, cùng lúc trên hai cổng:

* Sảnh của hai site là hai host khác nhau và hai **bản build khác nhau**:
  GK881 → ``new-dd-cloudfront.ywjxi.com/ddnewwap``, E3951 →
  ``new-dd-cn.dingdangmail.com/ddnewwap``.
* Cả hai đều liệt kê đúng 5 bàn giống nhau, cùng thứ tự:
  ``60101 RB01, 60102 RB02, 60103 RB03, 60104 RB04, 60105 RB05`` (người dùng cũng
  nhận thấy "chung giao diện và thứ tự các bàn").
* Vào bàn 60101 ở cả hai: ``round_id`` trùng nhau qua nhiều ván
  (``202611240022R1035``, ``R1036``, ``R1049``, ``R1051``…).
* ``max_k`` **khác nhau**: GK881 báo 10–1000, E3951 báo 10–1M, dù cùng bàn. Vì
  vậy mức cược chung phải lấy mức nhỏ nhất mà mọi sảnh cùng đặt được, không được
  lấy theo profile dẫn đầu.

Những điều này khoá lại hành vi dễ tái phát:

* Chọn bàn phải là **giao** của mọi sảnh (``ui/table_sync.js``), không phải danh
  sách của profile dẫn đầu.
* Mã bàn phải đọc từ **view cược** (``view.tableId``); vào bàn bằng cách bấm thẻ
  trên bản điện thoại thì URL không có ``tableId``.
* ``Page.navigate`` phải gửi trên websocket của **tab**, không phải của browser.
"""

import json
import unittest

from aibcr.adapters import febet as F


class TableIdentityTest(unittest.TestCase):
    """Mã bàn phải đọc được cả khi URL không mang ``tableId``."""

    def test_bet_state_reads_the_table_from_the_bet_view(self):
        js = F._DG_BET_STATE_JS
        # Đo trên tab 60101 của bản điện thoại: ``location`` không có tableId,
        # nhưng ``view.tableId`` / ``gameInfo.tableId`` = 60101.
        self.assertIn("view.tableId", js)
        self.assertIn("tableId", js)
        self.assertIn("gameInfo", js)
        self.assertIn("table_id:tableId", js)

    def test_bet_state_keeps_the_human_table_name(self):
        js = F._DG_BET_STATE_JS
        self.assertIn("tableName", js)
        self.assertIn("table_name:tableName", js)

    def test_round_state_also_reads_the_view_table(self):
        js = F._DG_STATE_JS
        self.assertIn("viewTable", js)
        self.assertIn("table_id: viewTable || urlTable", js)
        # URL vẫn được giữ riêng để ``sync_table`` so được loader.
        self.assertIn("url_table: urlTable", js)

    def test_loader_url_is_accepted_as_current_table(self):
        import inspect
        for function in (F.sync_table, F.lobby_tables, F.current_table):
            source = inspect.getsource(function)
            self.assertIn('state.get("table_id")', source,
                          "%s phải nhận mã bàn từ view" % function.__name__)


class SharedTableContractTest(unittest.TestCase):
    """Điều kiện để hai sảnh khác nhau thật sự ở chung một bàn."""

    def test_sync_table_verifies_the_landed_table_matches(self):
        import inspect
        source = inspect.getsource(F.sync_table)
        # Đang ở bàn khác thì không được coi là "đã vào bàn".
        self.assertIn("landed_id", source)
        self.assertIn("landed_id == table_id", source)

    def test_every_mode_requires_the_same_table_id(self):
        import inspect
        source = inspect.getsource(F.sync_table)
        # Trước đây chỉ chế độ iframe so ``url_table``; bấm thẻ trên bản điện
        # thoại không đổi URL nên phải so mã bàn đọc từ view ở mọi chế độ.
        self.assertNotIn('needs_url_match = ctx["mode"] != "top"', source)


class PromoteDocumentTest(unittest.TestCase):
    """Tab site phải được thay bằng chính URL sảnh, không giữ ``/m/home``."""

    def test_promote_uses_the_real_frame_document(self):
        import inspect
        source = inspect.getsource(F.promote_frame_to_tab)
        self.assertIn("navigate_top", source)
        self.assertIn("_wait_promoted", source)

    def test_promote_wait_accepts_the_dg_document_or_a_live_laya_stage(self):
        import inspect
        source = inspect.getsource(F._wait_promoted)
        self.assertIn('"ddnew" in current.lower()', source)
        self.assertIn("_has_top_laya", source)

    def test_promote_never_returns_the_tokenised_url(self):
        import inspect
        source = inspect.getsource(F.promote_frame_to_tab)
        for leaked in ("return {\"ok\": True, \"promoted\": True, \"url\"",
                       "result[\"url\"]"):
            self.assertNotIn(leaked, source)
        source = inspect.getsource(F._wait_promoted)
        self.assertNotIn('"url":', source)


class FrameOwnershipTest(unittest.TestCase):
    """Không được kéo nhầm sảnh DG của profile khác trong cùng Chrome."""

    def test_iframe_hosts_guard_is_used_before_promoting(self):
        import inspect
        source = inspect.getsource(F._promote_cdp_frame)
        self.assertIn("_IFRAME_HOSTS_JS", source)
        self.assertIn("not in hosts", source)

    def test_iframe_hosts_js_reads_resolved_hosts(self):
        js = F._IFRAME_HOSTS_JS
        self.assertIn("iframe,frame", js)
        self.assertIn("hostname", js)


class PhoneBuildTest(unittest.TestCase):
    """Bản điện thoại dùng ``index.html``; đổi bàn bằng ``?tableId=``."""

    def test_phone_loader_keeps_index_html(self):
        url = F._loader_url(
            "https://new-dd-cn.dingdangmail.com/ddnewwap/index.html?token=T&language=vi",
            "", "60103")
        self.assertIn("/ddnewwap/index.html?", url)
        self.assertIn("tableId=60103", url)
        # Token phiên phải được giữ, nhưng không được in ra log.
        self.assertIn("token=T", url)

    def test_lobby_url_drops_only_the_table(self):
        url = F._lobby_url_from(
            "https://new-dd-x.example/ddnewwap/index.html?token=T&tableId=60101")
        self.assertIn("token=T", url)
        self.assertNotIn("tableId", url)
        self.assertIn("/ddnewwap/index.html", url)

    def test_phone_loader_is_not_the_desktop_one(self):
        url = F._loader_url(
            "https://new-dd-x.example/ddnewwap/index.html?token=T", "", "60102")
        self.assertNotIn("direct1.html", url)


if __name__ == "__main__":
    unittest.main()
