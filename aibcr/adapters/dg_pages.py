# -*- coding: utf-8 -*-
"""Nhận diện tab sảnh DG (Laya) đang mở qua CDP.

Chỉ là tiến trình *nhận* trang: đọc ``/json/list`` rồi so URL. Không giải mã khung
WebSocket, không đọc lá bài, không đoán gà — phần đó đã bị bỏ khỏi dự án.

Trả ``page`` hoặc ``None``; ``table_id_from_url`` đọc ``?tableId=60101``.
"""

import json
import re
from urllib.request import urlopen

DEFAULT_PORT = 9222
# Mã bàn DG nằm trong URL của tab (?tableId=60101).
TABLE_RE = r"tableId=(\d+)"


def list_pages(port=DEFAULT_PORT):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        return [page for page in json.load(response)
                if isinstance(page, dict) and page.get("type") == "page"]


def find_dg_page(port=DEFAULT_PORT):
    """Tìm tab DG (``ddnewpc``/``ddnewwap`` hoặc trang chứa sảnh Laya).

    Không dùng URL làm điều kiện duy nhất vì GK881 mở sảnh Laya ngay trong trang
    ``/Account/LoginToSupplier``, nên vẫn phải nhận theo dấu ``ddnew`` của Laya.
    """
    for page in list_pages(port):
        url = str(page.get("url") or "").lower()
        if "ddnew" in url:
            return page
    return None


def table_id_from_url(url):
    """``...?tableId=60101`` -> ``"60101"``; không có thì ``""``."""
    found = re.search(TABLE_RE, str(url or ""))
    return found.group(1) if found else ""
