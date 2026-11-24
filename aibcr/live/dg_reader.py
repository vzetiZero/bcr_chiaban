# -*- coding: utf-8 -*-
"""Đọc bàn DG (Laya) đang mở qua CDP: kết quả ván + pha cược.

DG đẩy dữ liệu bằng WebSocket **nhị phân protobuf** (xem ``dg_frames``), khác hẳn
Petalive (JSON text) và WM (protocol 21/24/25). Vì vậy phải có bộ đọc riêng: nếu
dùng ``LiveReader`` (Petalive) hay ``WMReader`` thì bàn DG không bao giờ khớp tab và
đường tự đánh coi như tắt.

Hai loại khung được dùng:

    1002  thông tin bàn/ván: tableId, gameNo, stateId, countDown, lá bài
    1003  kết quả ván: tableId + lá bài dạng nhãn ("3C227")

Đo trên bàn 60101 cho thấy khung ``1003`` bị gửi **nhiều lần trong cùng một ván**
(2 lá mỗi bên, rồi 3 lá mỗi bên khi bên đó bốc thêm). Vì vậy chỉ phát ván khi khung
``1002`` báo pha đã ngã (``stateId`` 5/8) và đã có lá của cả hai bên — đó là lúc số
lá cuối cùng, nên điểm/thắng thua không bị chốt non.

Khung 1003 **không** kèm mã ván, nên mã ván được lấy từ khung 1002 gần nhất của
đúng ``tableId`` đó. Không có mã ván thì không phát ván, để không gán kết quả sang
tay khác.

Sảnh DG gửi cả khung của các bàn khác đang xem trước; bộ đọc chỉ nhận bàn đang mở
(``tableId`` trên URL của tab) để không trộn kết quả hai bàn.

Thread này chỉ đọc tab, không bấm, không đổi trang, không gửi lệnh cược.
"""

import json
import re
import threading
import time
from urllib.request import urlopen

from aibcr.live import dg_frames as DGF

DEFAULT_PORT = 9222
RECONNECT_SECONDS = 3.0
# Mã bàn DG nằm trong URL của tab (?tableId=60101); giá trị chỉ dùng để lọc khung.
TABLE_RE = r"tableId=(\d+)"
# Pha đã ngã: 5 = đang hiện kết quả, 8 = kết thúc ván. Dưới đây là pha cược/chia bài.
SETTLED_STATES = (5, 8)


def list_pages(port=DEFAULT_PORT):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        return [page for page in json.load(response)
                if isinstance(page, dict) and page.get("type") == "page"]


def find_dg_page(port=DEFAULT_PORT):
    """Tìm tab DG (``ddnewpc``/``ddnewwap`` hoặc trang chứa sảnh Laya).

    Trả ``page`` hoặc ``None``. Không dùng URL làm điều kiện duy nhất vì GK881 mở sảnh
    Laya ngay trong trang ``/Account/LoginToSupplier``.
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


class DGReader(threading.Thread):
    """Thread đọc một tab bàn DG; tự gắn lại khi tab đổi hoặc WS đứt."""

    def __init__(self, on_round=None, on_state=None, on_status=None,
                 port=DEFAULT_PORT, stop=None):
        super().__init__(daemon=True, name="bcr-dg-live")
        self.on_round = on_round
        self.on_state = on_state
        self.on_status = on_status
        self.port = port
        self.stop = stop or threading.Event()
        self.connected = False
        self.table = ""
        self.table_id = ""
        self.last_error = ""
        self.last_round = None
        self.last_state = None
        self.frames = 0
        # Bàn đang mở (lấy từ URL của tab). Rỗng thì nhận mọi bàn thấy được.
        self.open_table_id = ""
        # Mã ván gần nhất theo bàn, để ghép khung kết quả (1003) vào đúng tay.
        self._game_by_table = {}
        # Lá của khung 1003 gần nhất theo bàn (đã có lá nhưng chưa tới pha ngã).
        self._pending = {}
        # Chống phát lại cùng một ván (DG gửi lặp khi mở lại tab).
        self._emitted = set()

    # ------------------------------------------------------------------ sự kiện
    def _status(self, text, level="info"):
        if self.on_status is not None:
            try:
                self.on_status(text, level)
            except Exception:
                pass

    def handle_frame(self, raw):
        """Xử lý một khung nhị phân; trả payload ván mới (hoặc ``None``).

        Tách riêng khỏi vòng socket để test không cần Chrome. ``1003`` chỉ được coi
        là kết quả khi bàn đã sang pha ngã **và** đủ lá hai bên; khung 1003 phát lại
        giữa ván (mới 2 lá) không được phát ra ngoài.
        """
        frame = DGF.decode_frame(raw)
        if not frame:
            return None
        self.frames += 1
        table_id = str(frame.get("table_id") or "")
        if table_id and self.open_table_id and table_id != self.open_table_id:
            # Khung của bàn khác trong sảnh xem trước: bỏ, không trộn kết quả.
            return None
        if table_id:
            self.table_id = table_id
        game_no = str(frame.get("game_no") or "")
        if game_no and table_id:
            self._game_by_table[table_id] = game_no
            if len(self._game_by_table) > 32:
                self._game_by_table = dict(list(self._game_by_table.items())[-16:])

        if frame["kind"] == DGF.MSG_BET_STATE:
            state_id = frame.get("state_id")
            settled = int(state_id) in SETTLED_STATES if state_id is not None else False
            state = {
                "table": self._table_label(table_id),
                "table_id": table_id,
                "game_no": game_no,
                "state": "SHOW_RESULT" if settled else (
                    "BETTING" if state_id == 1 else "DEALING"),
                "state_id": state_id,
                "countdown": frame.get("countdown"),
                "round": self._round_no(game_no) or None,
            }
            if not self.table and state["table"]:
                self.table = state["table"]
            self.last_state = state
            if self.on_state is not None:
                try:
                    self.on_state(dict(state))
                except Exception:
                    pass
            if not settled:
                return None
            # Khung 1002 ở pha ngã mang bộ lá cuối cùng: chốt ván ở đây.
            player = frame.get("player_cards") or []
            banker = frame.get("banker_cards") or []
            if player and banker:
                return self._emit(game_no, table_id, player, banker)
            return None

        # Khung 1003 giữa ván: ghi nhớ lá nhưng chưa phát (sẽ phát khi pha ngã).
        if not game_no:
            game_no = self._game_by_table.get(table_id, "")
        player = frame.get("player_cards") or []
        banker = frame.get("banker_cards") or []
        if game_no and player and banker:
            self._pending[table_id or game_no] = (game_no, player, banker)
        return None

    def _emit(self, game_no, table_id, player, banker):
        """Phát một ván đã ngã ra ``on_round`` (chống phát trùng)."""
        if not game_no or not player or not banker:
            return None
        signature = (game_no, tuple(player), tuple(banker))
        if signature in self._emitted:
            return None
        self._emitted.add(signature)
        if len(self._emitted) > 400:
            self._emitted = set(list(self._emitted)[-200:])
        verdict = DGF.hand_verdict(player, banker)
        label = self._table_label(table_id)
        if label:
            self.table = label
        payload = {
            "issue_id": "%s:%s" % (label or table_id or "DG", game_no),
            "table": label or self.table or "DG",
            "table_id": table_id,
            "room_id": label or table_id,
            "player_cards": list(player),
            "banker_cards": list(banker),
            "bets": [],
            "winner": verdict["winner"],
            "player_score": verdict["player_score"],
            "banker_score": verdict["banker_score"],
            "round": self._round_no(game_no),
            "game_no": game_no,
        }
        self.last_round = payload
        self.last_state = {
            "table": payload["table"],
            "table_id": table_id,
            "game_no": game_no,
            "state": "SHOW_RESULT",
            "round": payload["round"],
            "countdown": 0,
        }
        if self.on_round is not None:
            try:
                self.on_round(payload)
            except Exception:
                pass
        if self.on_state is not None:
            try:
                self.on_state(dict(self.last_state))
            except Exception:
                pass
        return payload

    # ------------------------------------------------------------------ tiện ích
    @staticmethod
    def _round_no(game_no):
        """``202611240011R1024`` -> ``1024`` (số tay trong shoe hiện tại)."""
        text = str(game_no or "")
        if "R" not in text:
            return None
        tail = text.rsplit("R", 1)[-1]
        return int(tail) if tail.isdigit() else None

    @staticmethod
    def _table_label(table_id):
        """Nhãn bàn dùng để so với ``sim.table_key``; rỗng thì để bộ đọc tự đặt."""
        return str(table_id or "")

    # -------------------------------------------------------------------- vòng
    def run(self):
        while not self.stop.is_set():
            try:
                page = find_dg_page(self.port)
            except Exception as exc:
                page = None
                self.last_error = "Chrome CDP %d không phản hồi (%s)." % (
                    self.port, type(exc).__name__)
                self._status(self.last_error, "error")
            if page is None:
                if self.last_error == "":
                    self._status("Chưa thấy tab bàn DG; hãy mở bàn rồi thử lại.", "warn")
                self.connected = False
                time.sleep(RECONNECT_SECONDS)
                continue
            try:
                self._stream(page)
            except Exception as exc:
                self.last_error = "Mất kết nối bàn DG (%s)." % type(exc).__name__
                self._status(self.last_error, "error")
            if self.stop.is_set():
                break
            self.connected = False
            time.sleep(RECONNECT_SECONDS)

    def _stream(self, page):
        import base64

        import websocket

        endpoint = page.get("webSocketDebuggerUrl") or ""
        # Bàn đang mở nằm trên URL của tab (không log token).
        self.open_table_id = table_id_from_url(page.get("url") or "") or self.open_table_id
        try:
            ws = websocket.create_connection(
                endpoint, suppress_origin=True, timeout=10, redirect_limit=0,
                http_no_proxy=["127.0.0.1", "localhost", "::1"])
        except Exception as exc:
            self.last_error = "Không gắn được tab bàn DG (%s)." % type(exc).__name__
            self._status(self.last_error, "error")
            return
        try:
            ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
            self.connected = True
            self.last_error = ""
            self._status("Đã gắn tab bàn DG · đang đọc kết quả live.", "win")
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
                if payload.get("opcode") != 2:
                    continue
                try:
                    raw = base64.b64decode(payload.get("payloadData") or "")
                except Exception:
                    continue
                self.handle_frame(raw)
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def close(self):
        self.stop.set()
