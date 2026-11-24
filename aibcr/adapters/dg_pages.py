# -*- coding: utf-8 -*-
"""Nhận diện tab/frame sảnh DG (Laya) đang mở qua CDP.

Chỉ là tiến trình *nhận* trang: đọc ``/json/list`` rồi so URL. Không giải mã khung
WebSocket, không đọc lá bài, không đoán gà — phần đó đã bị bỏ khỏi dự án.

``/json/list`` là đường duy nhất thấy được **iframe khác tiến trình** (OOPIF):
đo trên ``e39d5d05qc.e3951.com/m/home``, game DG nằm trong một target
``type: iframe`` với tài liệu thật ``ddnewwap/index.html``, trong khi ``src`` của
thẻ ``<iframe>`` vẫn ghi ``ddnewpc/direct1.html``. WebDriver không switch vào
được frame đó, nên mọi vòng quét ``find_elements("iframe, frame")`` đều báo
"chưa mở game" dù sảnh đã chạy.

Trả ``page``/``target`` hoặc ``None``; ``table_id_from_url`` đọc ``?tableId=60101``.
"""

import json
import re
import time
from urllib.request import urlopen

DEFAULT_PORT = 9222
# Mã bàn DG nằm trong URL của tab (?tableId=60101).
TABLE_RE = r"tableId=(\d+)"
# Tài liệu DG: ``ddnewpc`` (máy tính) và ``ddnewwap`` (điện thoại) đều chứa ``ddnew``.
GAME_URL_MARK = "ddnew"


def list_targets(port=DEFAULT_PORT):
    """Mọi target CDP có URL (page, iframe/OOPIF, worker...)."""
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        rows = json.load(response)
    return [row for row in rows if isinstance(row, dict) and row.get("url")]


def list_pages(port=DEFAULT_PORT):
    return [target for target in list_targets(port) if target.get("type") == "page"]


def find_dg_page(port=DEFAULT_PORT):
    """Tìm tab DG (``ddnewpc``/``ddnewwap`` hoặc trang chứa sảnh Laya).

    Không dùng URL làm điều kiện duy nhất vì GK881 mở sảnh Laya ngay trong trang
    ``/Account/LoginToSupplier``, nên vẫn phải nhận theo dấu ``ddnew`` của Laya.
    """
    for target in list_targets(port):
        if GAME_URL_MARK in str(target.get("url") or "").lower():
            return target
    return None


def find_game_target(port=DEFAULT_PORT, wait=0.0, interval=0.4):
    """Target DG, kể cả iframe khác tiến trình. ``wait`` để chờ sảnh kịp tải."""
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        found = find_dg_page(port)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def table_id_from_url(url):
    """``...?tableId=60101`` -> ``"60101"``; không có thì ``""``."""
    found = re.search(TABLE_RE, str(url or ""))
    return found.group(1) if found else ""
