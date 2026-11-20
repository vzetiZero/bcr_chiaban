# -*- coding: utf-8 -*-
"""Đặt cược WM bằng WebSocket (protocol 22) — nhanh, không phụ thuộc toạ độ chuột.

Bàn WM nói chuyện với server bằng khung **nhị phân** chứa JSON, mỗi khung có ``protocol``:

    21  thông tin bàn + ván (gameNo, gameNoRound, betMilliSecond, tableStatus)
    22  lệnh cược: {"betSerialNumber", "gameNo", "gameNoRound",
                    "betArr": [{"betArea": 2, "addBetMoney": 10}], "commission", "remark"}
    24  lá bài đang chia        25  kết quả ván        26  lịch sử bàn

``betArea``: 1 = Banker, 2 = Player, 3 = Hoà. Đã đối chiếu với lệnh thật: gửi
``betArea 2, addBetMoney 10`` thì server trả ``{"protocol": 22, "bOk": true}``, số dư giảm
đúng 10 (10.000đ) và chip hiện trên ô Player.

Muốn gửi lệnh thì phải giữ được instance ``WebSocket`` của trang, mà socket chỉ tạo một
lần lúc tải trang. Vì vậy module này chạy một thread giữ kết nối CDP: cài hook
``WebSocket``, tải lại tab một lần nếu cần (hook chỉ ăn từ document mới), rồi giữ nguyên
kết nối đó để gửi lệnh và đọc phản hồi. Sàn giữ nhiều socket (bàn cũ chưa đóng), nên
socket được chọn theo ``groupID`` khớp bàn đang mở (``#container`` của iframe bàn).

Không có socket thì ``WMBet`` tự quay về đường bấm chuột — tính năng đặt cược không bao
giờ phụ thuộc duy nhất vào WebSocket.
"""

import json
import threading
import time

from aibcr.adapters import browser as BR

# Ô cược -> betArea trên WebSocket.
BET_AREA = {"B": 1, "P": 2, "T": 3}
PROTOCOL_BET = 22
# Ghi chú cố định của client WM khi xác nhận cược (chép từ khung thật).
BET_REMARK = "1,0"
# Tên biến toàn cục của hook; đổi tên khi đổi cấu trúc để không đụng hook cũ còn sót.
HOOK_NAME = "__wmHook3"

HOOK_JS = r"""(() => {
    const isTop = (window === window.top);
    const label = isTop ? 'top' : 'iframe';
    if (window.__wmHook3) return 'already';
    const decoder = new TextDecoder('utf-8');
    const hook = {sockets: [], urls: [], protocols: {}, recent21: [], last22: null,
                  sent: [], errors: [], scope: {}, top: isTop};
    window.__wmHook3 = hook;
    // Chạy trong CẢ khung gốc lẫn iframe (Page.addScriptToEvaluateOnNewDocument áp cho
    // mọi frame). Socket đặt cược của WM nằm trong iframe bàn, nên phải hook riêng nó —
    // hook khung gốc không thấy socket đó.
    const make = (win, store, tag) => {
        if (!win) return;
        const Native = win.WebSocket;
        if (!Native) return;
        const indexOf = (ws) => store.sockets.indexOf(ws);
        function Wrapped(url, protocols) {
            const ws = protocols === undefined ? new Native(url) : new Native(url, protocols);
            try {
                store.scope[store.sockets.length] = tag;
                store.sockets.push(ws);
                store.urls.push(String(url));
                const send = ws.send.bind(ws);
                ws.send = function (data) {
                    try {
                        let text = data;
                        if (data instanceof ArrayBuffer) text = decoder.decode(new Uint8Array(data));
                        store.sent.push(String(text).slice(0, 240));
                        if (store.sent.length > 60) store.sent.shift();
                    } catch (e) {}
                    return send(data);
                };
                ws.addEventListener('message', function (event) {
                    try {
                        let text = event.data;
                        if (text instanceof ArrayBuffer) text = decoder.decode(new Uint8Array(text));
                        if (typeof text !== 'string') return;
                        const msg = JSON.parse(text);
                        const proto = msg && msg.protocol;
                        if (typeof proto !== 'number') return;
                        const idx = indexOf(ws);
                        store.protocols[idx] = proto;
                        if (proto === 21) {
                            store.recent21.push({socket: idx, at: Date.now(), data: msg.data});
                            if (store.recent21.length > 60) store.recent21.shift();
                        } else if (proto === 22) {
                            store.last22 = {socket: idx, at: Date.now(), data: msg.data};
                        }
                    } catch (e) {
                        if (store.errors.length < 20) store.errors.push(String(e).slice(0, 80));
                    }
                });
            } catch (e) {}
            return ws;
        }
        Wrapped.prototype = Native.prototype;
        ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach((k) => { Wrapped[k] = Native[k]; });
        win.WebSocket = Wrapped;
    };
    window.__wmMakeHook = make;
    make(window, hook, label);
    return 'installed:' + label;
})()"""

# Cài hook vào iframe bàn hiện tại (iframe có thể đã tồn tại trước khi cài hook).
INSTALL_TABLE_JS = r"""(() => {
    const frame = document.getElementById('iframe_101');
    if (!frame || !frame.contentWindow) return 'no_frame';
    try {
        const child = frame.contentWindow;
        const factory = window.__wmMakeHook;
        if (typeof factory !== 'function') return 'no_factory';
        if (!child.__wmHook3) {
            child.__wmHook3 = {sockets: [], urls: [], protocols: {}, recent21: [],
                               last22: null, sent: [], errors: [], scope: {}, top: false};
        }
        factory(child, child.__wmHook3, 'iframe');
        return 'ok';
    } catch (e) { return 'err:' + String(e).slice(0, 60); }
})()"""

# Nạp lại iframe bàn để nó tạo socket MỚI (socket cũ tạo trước khi cài hook nên không
# bắt được). Chỉ nạp lại iframe — không đụng khung ngoài, bàn vẫn y nguyên.
RELOAD_TABLE_JS = r"""(() => {
    const frame = document.getElementById('iframe_101');
    if (!frame || !frame.contentWindow) return 'no_frame';
    try {
        frame.contentWindow.location.reload();
        return 'reload';
    } catch (e) {
        try { frame.src = frame.getAttribute('src') || frame.src; return 'reload_src'; }
        catch (err) { return 'err:' + String(err).slice(0, 60); }
    }
})()"""

READ_JS = r"""(() => {
    const frame = document.getElementById('iframe_101');
    const doc = (frame && frame.contentDocument) || document;
    const box = doc.getElementById('container');
    const m = box ? /(?:^|\s)group(\d+)/.exec((box.className || '').toString()) : null;
    const openGroup = m ? parseInt(m[1], 10) : null;
    // Hook chạy riêng trong mỗi frame: gộp socket của khung gốc (sảnh) và iframe (bàn).
    const stores = [];
    const push = (hook, label) => {
        if (hook && hook.sockets) stores.push({hook: hook, label: label});
    };
    push(window.__wmHook3, 'top');
    try {
        const child = frame && frame.contentWindow;
        if (child && child.__wmHook3 && child.__wmHook3 !== window.__wmHook3) {
            push(child.__wmHook3, 'iframe');
        }
    } catch (e) {}
    if (!stores.length) return {installed: false, open_group: openGroup};
    const merged = {urls: [], states: [], scopes: {}, protocols: {}, recent21: [],
                    last22: null, sent: [], errors: [], offsets: {}};
    for (const entry of stores) {
        const hook = entry.hook;
        const base = merged.states.length;
        merged.offsets[entry.label] = base;
        for (let i = 0; i < hook.sockets.length; i++) {
            merged.states.push(hook.sockets[i].readyState);
            merged.scopes[base + i] = entry.label;
            merged.urls.push(hook.urls[i] || '');
        }
        for (const key of Object.keys(hook.protocols || {})) {
            merged.protocols[base + parseInt(key, 10)] = hook.protocols[key];
        }
        for (const item of (hook.recent21 || [])) {
            merged.recent21.push({socket: base + item.socket, at: item.at, data: item.data});
        }
        if (hook.last22) {
            const at = hook.last22.at || 0;
            if (!merged.last22 || at > (merged.last22.at || 0)) {
                merged.last22 = {socket: base + hook.last22.socket, at: at,
                                 data: hook.last22.data, scope: entry.label,
                                 offset: base};
            }
        }
        for (const line of (hook.sent || []).slice(-6)) merged.sent.push(line);
    }
    return {installed: true, urls: merged.urls, states: merged.states,
            scopes: merged.scopes, protocols: merged.protocols,
            recent21: merged.recent21, last22: merged.last22,
            open_group: openGroup, sent: merged.sent.slice(-6),
            errors: merged.errors, offsets: merged.offsets};
})()"""

SEND_JS = r"""(() => {
    const frame = document.getElementById('iframe_101');
    const want = %d;
    const stores = [];
    if (window.__wmHook3) stores.push({hook: window.__wmHook3, label: 'top'});
    try {
        const child = frame && frame.contentWindow;
        if (child && child.__wmHook3 && child.__wmHook3 !== window.__wmHook3) {
            stores.push({hook: child.__wmHook3, label: 'iframe'});
        }
    } catch (e) {}
    let offset = 0;
    for (const entry of stores) {
        const count = entry.hook.sockets.length;
        if (want < offset + count) {
            const socket = entry.hook.sockets[want - offset];
            if (!socket) return {ok: false, error: 'no_socket'};
            if (socket.readyState !== 1) return {ok: false, error: 'socket_not_open'};
            try {
                const bytes = new TextEncoder().encode(%s);
                socket.send(bytes.buffer);
                return {ok: true, bytes: bytes.length, scope: entry.label};
            } catch (e) {
                return {ok: false, error: String(e).slice(0, 120)};
            }
        }
        offset += count;
    }
    return {ok: false, error: 'no_socket'};
})()"""


def bet_frame(side, amount, game_no, round_no, serial=1):
    """Khung protocol 22 đặt ``amount`` (đơn vị sảnh) vào cửa ``side``."""
    return {"protocol": PROTOCOL_BET,
            "data": {"betSerialNumber": int(serial), "gameNo": game_no,
                     "gameNoRound": round_no,
                     "betArr": [{"betArea": BET_AREA[side], "addBetMoney": int(amount)}],
                     "commission": 0, "remark": BET_REMARK}}


def current_table(state):
    """Socket + khung 21 của ĐÚNG bàn đang mở: ``(index, data, seen_at_ms)`` hoặc ``None``.

    Hai điều kiện:
      * ``groupID`` khớp bàn đang mở (sàn đẩy 21 cho nhiều bàn trên cùng socket);
      * socket phải thuộc **iframe bàn** khi có — socket khung gốc (sảnh) nhận được dữ
        liệu bàn nhưng server từ chối lệnh cược gửi từ đó (``bOk: false``).
    """
    frames = (state or {}).get("recent21") or []
    states = (state or {}).get("states") or []
    scopes = (state or {}).get("scopes") or {}
    group = (state or {}).get("open_group")

    def open_socket(index):
        return 0 <= index < len(states) and states[index] == 1

    def pick(only_iframe):
        best = None
        for entry in frames:
            try:
                index = int((entry or {}).get("socket"))
            except (TypeError, ValueError):
                continue
            if not open_socket(index):
                continue
            if only_iframe and scopes.get(str(index), scopes.get(index)) != "iframe":
                continue
            data = (entry or {}).get("data") or {}
            if group is not None and data.get("groupID") != group:
                continue
            at = float((entry or {}).get("at") or 0)
            if best is None or at > best[2]:
                best = (index, data, at)
        return best

    return pick(True) or (None if group is not None else pick(False))


class WMSocket(threading.Thread):
    """Thread giữ kết nối CDP + hook WebSocket của tab WM, gửi lệnh cược."""

    def __init__(self, session=None, on_status=None, reload_on_start=False):
        super().__init__(daemon=True, name="wm-socket")
        self.session = session or BR.BrowserSession()
        self.on_status = on_status
        self.reload_on_start = reload_on_start
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._command = None
        self._ws = None
        self._state = {}
        self._state_at = 0.0
        self._reloaded = False
        self._serial = {"key": None, "value": 0}
        self.last_error = ""
        self.ready_at = 0.0

    # ------------------------------------------------------------------ tiện ích
    def _status(self, text, level="info"):
        if self.on_status is None:
            return
        try:
            self.on_status(text, level)
        except Exception:
            pass

    def _command_locked(self, method, params=None, timeout=BR.SCRIPT_TIMEOUT):
        if self._command is None:
            raise RuntimeError("not_connected")
        return self._command(method, params, timeout)

    def evaluate(self, expression, timeout=BR.SCRIPT_TIMEOUT):
        with self.lock:
            result = self._command_locked("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "silent": True,
            }, timeout)
        return (result or {}).get("result", {}).get("value")

    def click_at(self, x, y, pause=0.0):
        """Bấm chuột thật tại toạ độ khung gốc bằng kết nối CDP dùng chung.

        Dùng chung kết nối với hook thay vì mở kết nối mới mỗi lần bấm: mở/đóng CDP liên
        tục làm tab chậm và dễ timeout.
        """
        with self.lock:
            self._command_locked("Input.dispatchMouseEvent",
                                 {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
            self._command_locked("Input.dispatchMouseEvent",
                                 {"type": "mousePressed", "x": x, "y": y, "button": "left",
                                  "buttons": 1, "clickCount": 1})
            self._command_locked("Input.dispatchMouseEvent",
                                 {"type": "mouseReleased", "x": x, "y": y, "button": "left",
                                  "buttons": 0, "clickCount": 1})
        if pause:
            time.sleep(pause)

    def state(self, fresh=False):
        """Ảnh chụp hook (đọc trực tiếp nếu ``fresh`` hoặc cache đã cũ)."""
        with self.lock:
            if fresh or time.time() - self._state_at > 1.0:
                try:
                    value = self._command_locked("Runtime.evaluate", {
                        "expression": READ_JS, "returnByValue": True, "silent": True,
                    }).get("result", {}).get("value")
                    if isinstance(value, dict):
                        self._state = value
                        self._state_at = time.time()
                except Exception as exc:
                    self.last_error = "Không đọc được hook WS (%s)." % type(exc).__name__
        return dict(self._state or {})

    def ready(self):
        state = self.state()
        return current_table(state) is not None

    # ------------------------------------------------------------------ kết nối
    def _connect(self):
        import websocket

        page = self.session._cdp_page()
        if page is None:
            raise RuntimeError("no_page")
        ws = websocket.create_connection(
            BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
            redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
        state = {"seq": 0}

        def command(method, params=None, timeout=BR.SCRIPT_TIMEOUT):
            state["seq"] += 1
            seq = state["seq"]
            ws.settimeout(timeout)
            ws.send(json.dumps({"id": seq, "method": method, "params": params or {}}))
            deadline = time.monotonic() + timeout
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(method)
                message = json.loads(ws.recv())
                if message.get("id") != seq:
                    continue
                if message.get("error"):
                    raise RuntimeError(str(message["error"])[:120])
                return message.get("result", {})

        self._ws = ws
        self._command = command
        command("Page.enable")
        command("Runtime.enable")
        command("Page.addScriptToEvaluateOnNewDocument",
                {"source": HOOK_JS, "runImmediately": True})
        return True

    def _close(self):
        self._command = None
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def wait_ready(self, timeout=20.0):
        """Chờ hook thấy socket của bàn đang mở."""
        deadline = time.monotonic() + max(1.0, float(timeout))
        while time.monotonic() < deadline:
            if self.ready():
                self.ready_at = time.time()
                return True
            time.sleep(0.5)
        return False

    def prepare(self, timeout=25.0):
        """Kết nối + cài hook. Chỉ nạp lại khung khi ``reload_on_start`` cho phép.

        Nạp lại khung bàn sẽ làm bàn nháy và có thể mất trạng thái cược, nên khi đang đứng
        trong bàn (``reload_on_start=False``) ta chỉ cài hook sẵn và để đường bấm chip
        xử lý — không đụng vào bàn đang theo dõi.
        """
        if not self._connect():
            return False
        if self.wait_ready(3.0):
            return True
        try:
            self.evaluate(INSTALL_TABLE_JS)
            if self.ready():
                return True
        except Exception:
            pass
        if not self.reload_on_start or self._reloaded:
            return self.wait_ready(min(5.0, timeout))
        self._reloaded = True
        try:
            # Ưu tiên nạp lại riêng khung bàn (khung ngoài và sảnh giữ nguyên).
            self.evaluate(RELOAD_TABLE_JS)
            self._status("Đang nạp lại khung bàn để bắt socket đặt cược…", "info")
            if self.wait_ready(timeout):
                return True
        except Exception:
            pass
        try:
            with self.lock:
                self._command_locked("Page.reload", {"ignoreCache": False}, timeout=15)
        except Exception:
            return False
        self._status("Đang tải lại tab WM để bắt socket đặt cược…", "info")
        return self.wait_ready(timeout)

    # ------------------------------------------------------------------ vòng nền
    def run(self):
        """Vòng nền: giữ hook sống và bắt socket khi bàn được mở lại.

        Không tải lại tab (sẽ mất bàn). Chỉ báo trạng thái một lần để log không spam khi
        socket chưa sẵn sàng và cược đang đi bằng đường bấm chip.
        """
        warned = False
        while not self.stop_event.is_set():
            try:
                if self._command is None:
                    self._connect()
                    try:
                        self.evaluate(INSTALL_TABLE_JS)
                    except Exception:
                        pass
                self.state(fresh=True)
                if not self.ready():
                    try:
                        self.evaluate(INSTALL_TABLE_JS)
                    except Exception:
                        pass
                if self.ready():
                    if warned:
                        self._status("Socket WM sẵn sàng · đặt cược gửi thẳng qua WebSocket.",
                                     "win")
                        warned = False
                elif not warned:
                    self._status("Cược bằng bấm chip (chưa bắt được socket WM).", "info")
                    warned = True
                self.stop_event.wait(0.5)
            except Exception as exc:
                self.last_error = "Mất kết nối socket WM (%s)." % type(exc).__name__
                self._close()
                self.stop_event.wait(5.0)

    def close(self):
        self.stop_event.set()
        self._close()

    # ------------------------------------------------------------------ đặt cược
    def _next_serial(self, game_no, round_no):
        key = "%s:%s" % (game_no, round_no)
        if self._serial["key"] != key:
            self._serial = {"key": key, "value": 0}
        self._serial["value"] += 1
        return self._serial["value"]

    def place(self, side, amount, wait_seconds=6.0):
        """Gửi lệnh cược qua WebSocket; trả ``{"ok", "frame", "reply", "error"}``."""
        side = str(side or "").upper()[:1]
        if side not in BET_AREA:
            return {"ok": False, "error": "Cửa cược không hợp lệ: %r" % (side,)}
        try:
            amount = int(round(float(amount)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Số tiền không hợp lệ."}
        if amount <= 0:
            return {"ok": False, "error": "Số tiền phải lớn hơn 0."}
        if self._command is None:
            return {"ok": False, "error": "not_connected"}

        state = self.state(fresh=True)
        current = current_table(state)
        if current is None:
            return {"ok": False, "error": "no_socket"}
        socket_index, data, seen_at = current
        game_no, round_no = data.get("gameNo"), data.get("gameNoRound")
        if game_no is None or round_no is None:
            return {"ok": False, "error": "Chưa biết ván hiện tại của bàn."}
        age = (time.time() * 1000.0) - float(seen_at or 0)
        if age > 15000:
            return {"ok": False, "error": "Dữ liệu bàn đã cũ (%.1fs) — chưa gửi."
                                          % (age / 1000.0)}
        # Không tự đoán pha cược bằng ``tableStatus``: server trả ``bOk: false`` khi cửa
        # cược đã đóng, đó mới là căn cứ.
        frame = bet_frame(side, amount, game_no, round_no,
                          serial=self._next_serial(game_no, round_no))
        payload = json.dumps(json.dumps(frame, ensure_ascii=False))
        sent_at = time.time() * 1000.0
        with self.lock:
            try:
                result = self._command_locked("Runtime.evaluate", {
                    "expression": SEND_JS % (int(socket_index), payload),
                    "returnByValue": True, "silent": True,
                }).get("result", {}).get("value") or {}
            except Exception as exc:
                return {"ok": False, "error": "send_failed", "frame": frame,
                        "detail": type(exc).__name__}
            if not result.get("ok"):
                return {"ok": False, "error": result.get("error") or "send_failed",
                        "frame": frame}
            deadline = time.monotonic() + max(1.0, float(wait_seconds))
            while time.monotonic() < deadline:
                try:
                    info = self._command_locked("Runtime.evaluate", {
                        "expression": READ_JS, "returnByValue": True, "silent": True,
                    }).get("result", {}).get("value") or {}
                except Exception:
                    break
                reply = info.get("last22") or {}
                if float(reply.get("at") or 0) >= sent_at:
                    body = reply.get("data") or {}
                    return {"ok": bool(body.get("bOk")), "frame": frame, "reply": body,
                            "error": "" if body.get("bOk") else "server_rejected"}
                time.sleep(0.15)
        return {"ok": False, "frame": frame, "error": "no_reply"}


# ------------------------------------------------------------------ dùng chung
def install_hook(session):
    """Cài hook WebSocket cho các document MỚI của tab (không tải lại trang).

    Dùng khi người dùng đang đứng trong bàn: tải lại tab sẽ đẩy Chrome về sảnh và mất
    bàn, nên chỉ cài hook sẵn — lần tải trang sau (hoặc lần vào bàn từ sảnh) socket sẽ
    được bắt và lệnh cược đi qua WebSocket.
    """
    import websocket

    page = session._cdp_page()
    if page is None:
        return False
    ws = None
    try:
        ws = websocket.create_connection(
            BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
            redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
        state = {"seq": 0}

        def command(method, params=None):
            state["seq"] += 1
            seq = state["seq"]
            ws.settimeout(BR.SCRIPT_TIMEOUT)
            ws.send(json.dumps({"id": seq, "method": method, "params": params or {}}))
            while True:
                message = json.loads(ws.recv())
                if message.get("id") == seq:
                    if message.get("error"):
                        raise RuntimeError(str(message["error"])[:120])
                    return message.get("result", {})

        command("Page.enable")
        command("Page.addScriptToEvaluateOnNewDocument",
                {"source": HOOK_JS, "runImmediately": True})
        return True
    except Exception:
        return False
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def get_socket(session, start=True, reload_on_start=False, on_status=None):
    """Lấy (và khởi động) một ``WMSocket`` dùng chung cho cả app."""
    socket = getattr(session, "wm_socket", None)
    if socket is not None and socket.is_alive():
        return socket
    socket = WMSocket(session, on_status=on_status, reload_on_start=reload_on_start)
    session.wm_socket = socket
    if start:
        socket.start()
    return socket
