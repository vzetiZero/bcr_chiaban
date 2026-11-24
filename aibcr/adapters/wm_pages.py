# -*- coding: utf-8 -*-
"""Nhận diện tab WM (M88) đang mở qua CDP.

Chỉ là tiện ích *nhìn* trang: URL của WM không có dấu hiệu nhận biết nào (mirror đổi
liên tục), nên phải hỏi chính tab qua ``WM_DETECT_JS``. Không đọc lá bài, không dự
đoán gì — phần đó không còn trong dự án.

Trả ``(page, detect)``; không thấy thì ``(None, {})``.
"""

import json
import time
from urllib.request import urlopen

from aibcr.adapters import wm as WM

DEFAULT_PORT = 9222


def list_pages(port=DEFAULT_PORT):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        return [page for page in json.load(response)
                if isinstance(page, dict) and page.get("type") == "page"]


def find_wm_page(port=DEFAULT_PORT):
    """Tìm tab WM (sảnh hoặc bàn).

    Giữ tab sảnh làm phương án dự phòng nhưng vẫn soi hết các tab còn lại: Chrome có
    thể có tab sảnh đứng trước tab bàn, trả sảnh ngay thì ``find_wm_table`` báo không
    có bàn nào đang mở.
    """
    import websocket

    lobby_page = None
    lobby_detect = None
    for page in list_pages(port):
        endpoint = page.get("webSocketDebuggerUrl") or ""
        url = str(page.get("url") or "")
        if not endpoint or not url.startswith("https://"):
            continue
        try:
            ws = websocket.create_connection(
                endpoint, suppress_origin=True, timeout=4, redirect_limit=0,
                http_no_proxy=["127.0.0.1", "localhost", "::1"])
        except Exception:
            continue
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
            ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
                "expression": WM.WM_DETECT_JS, "returnByValue": True, "silent": True}}))
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                message = json.loads(ws.recv())
                if message.get("id") != 2:
                    continue
                value = (message.get("result") or {}).get("result", {}).get("value")
                if isinstance(value, dict) and value.get("is_wm"):
                    if value.get("kind") == "table":
                        return page, value
                    if lobby_page is None:
                        lobby_page, lobby_detect = page, value
                break
        except Exception:
            continue
        finally:
            try:
                ws.close()
            except Exception:
                pass
    return (lobby_page, lobby_detect) if lobby_page is not None else (None, {})


def find_wm_table(port=DEFAULT_PORT):
    """Tìm tab đang hiện màn hình bàn WM.

    Không nhận diện bằng URL mà bằng cấu trúc iframe ``iframe_101`` đang hiển thị.
    """
    page, detect = find_wm_page(port)
    if page is not None and detect.get("kind") == "table":
        return page, detect
    return None, {}
