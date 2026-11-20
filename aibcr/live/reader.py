# -*- coding: utf-8 -*-
"""Gắn CDP vào tab bàn Petalive và phát sự kiện ván đấu.

Không mở/đóng Chrome: dùng đúng cổng gỡ lỗi đã có (mặc định 9222), bật ``Network.enable``
rồi đọc khung WebSocket của tab. Mỗi khung được ``decode`` thành sự kiện:

    on_round(round_dict)   kết quả ván: lá bài hai bên, cửa thắng
    on_state(state_dict)   đổi trạng thái: BETTING / WAITING_SHOW_RESULT / SHOW_RESULT
    on_raw(frame)          mọi khung đã tách (để log/ghi file)
"""

import json
import threading
import time
from urllib.request import urlopen

from aibcr.live import decode

DEFAULT_PORT = 9222
TAB_PATTERN = "live-games|/bcr/|petalive"
RECONNECT_SECONDS = 3.0
# Tab sảnh Petalive cũng chứa "live-games" nên phải loại nó khi tìm tab BÀN; nếu không
# LiveReader sẽ bám vào sảnh và không thấy khung kết quả nào.
PETALIVE_LOBBY_RE = r"/live-games/lobby/"
PETALIVE_TABLE_RE = r"/live-games/bcr/[A-Za-z0-9_-]+"


def list_pages(port=DEFAULT_PORT):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        return [page for page in json.load(response)
                if isinstance(page, dict) and page.get("type") == "page"]


def find_table_page(port=DEFAULT_PORT, pattern=TAB_PATTERN):
    """Chọn tab BÀN, bỏ qua tab sảnh Petalive dù cùng khớp pattern chung."""
    import re
    found = re.compile(pattern, re.I)
    lobby = re.compile(PETALIVE_LOBBY_RE, re.I)
    table = re.compile(PETALIVE_TABLE_RE, re.I)
    matches = []
    for page in list_pages(port):
        url = str(page.get("url") or "")
        if url and found.search(url) and not lobby.search(url):
            matches.append(page)
    if not matches:
        return None
    # Ưu tiên URL bàn Petalive rõ ràng (/live-games/bcr/<id>) hơn tab bất kỳ.
    for page in matches:
        if table.search(str(page.get("url") or "")):
            return page
    return matches[0]


class LiveReader(threading.Thread):
    """Thread đọc một tab; tự gắn lại khi tab bị tải lại (WS đứt)."""

    def __init__(self, on_round=None, on_state=None, on_raw=None, on_status=None,
                 port=DEFAULT_PORT, pattern=TAB_PATTERN, stop=None):
        super().__init__(daemon=True, name="bcr-live")
        self.on_round = on_round
        self.on_state = on_state
        self.on_raw = on_raw
        self.on_status = on_status
        self.port = port
        self.pattern = pattern
        self.stop = stop or threading.Event()
        self.connected = False
        self.table = ""
        self.last_error = ""
        self.last_round = None
        self.last_state = None
        self.frames = 0

    # ------------------------------------------------------------------ sự kiện
    def _status(self, text, level="info"):
        if self.on_status is not None:
            self.on_status(text, level)

    def handle_text(self, text):
        """Xử lý một khung; trả ``Frame`` đã tách (hoặc None). Tách riêng để test."""
        frame = decode.split_frame(text)
        if frame is None:
            return None
        self.frames += 1
        if self.on_raw is not None:
            self.on_raw(frame)
        if frame.event == decode.EVENT_RESULT:
            data = decode.decode_round(frame)
            if data:
                self.last_round = data
                self.table = data.get("table") or self.table
                if self.on_round is not None:
                    self.on_round(data)
        elif frame.event in (decode.EVENT_STATE, decode.EVENT_INFO):
            state = decode.decode_state(frame)
            if state:
                self.last_state = state
                self.table = state.get("table") or self.table
                if self.on_state is not None:
                    self.on_state(state)
        return frame

    # -------------------------------------------------------------------- vòng
    def run(self):
        while not self.stop.is_set():
            page = None
            try:
                page = find_table_page(self.port, self.pattern)
            except Exception as exc:
                self.last_error = "Chrome CDP %d không phản hồi (%s)." % (
                    self.port, type(exc).__name__)
                self._status(self.last_error, "error")
            if page is None:
                if self.last_error == "":
                    self._status("Chưa thấy tab bàn Petalive; chờ tab mở…", "warn")
                self.connected = False
                time.sleep(RECONNECT_SECONDS)
                continue
            try:
                self._stream(page)
            except Exception as exc:
                self.last_error = "Mất kết nối tab bàn (%s)." % type(exc).__name__
                self._status(self.last_error, "error")
            if self.stop.is_set():
                break
            self.connected = False
            time.sleep(RECONNECT_SECONDS)

    def _stream(self, page):
        import websocket

        endpoint = page.get("webSocketDebuggerUrl") or ""
        try:
            ws = websocket.create_connection(
                endpoint, suppress_origin=True, timeout=10,
                http_no_proxy=["127.0.0.1", "localhost", "::1"], redirect_limit=0)
        except Exception as exc:
            self.last_error = "Không gắn được tab bàn (%s)." % type(exc).__name__
            self._status(self.last_error, "error")
            return
        ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        self.connected = True
        self.last_error = ""
        self._status("Đã gắn tab bàn · đang đọc kết quả live.", "win")
        try:
            while not self.stop.is_set():
                ws.settimeout(0.5)
                try:
                    message = json.loads(ws.recv())
                except Exception as exc:
                    if type(exc).__name__ in ("WebSocketTimeoutException", "TimeoutError"):
                        continue
                    break
                if message.get("method") != "Network.webSocketFrameReceived":
                    continue
                payload = (message.get("params") or {}).get("response") or {}
                if payload.get("opcode") != 1:
                    continue
                self.handle_text(payload.get("payloadData") or "")
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def close(self):
        self.stop.set()
