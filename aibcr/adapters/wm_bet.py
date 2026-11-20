# -*- coding: utf-8 -*-
"""Chọn chip và đặt cược trên bàn WM (M88) — bản port từ dự án LONG-LONG cũ.

Bàn WM đặt cược theo hai bước: bấm mệnh giá trên khay rồi bấm ô cược để "treo" chip,
sau đó bấm nút xác nhận (``bet_btn``) mới thực sự gửi lệnh ``protocol 22`` đi. Nhờ vậy
giữa hai bước có cửa sổ an toàn để đọc lại số tiền đã treo và huỷ nếu sai.

Thang tiền: khay chip WM in ``10 / 20 / 50 / 100 / 500 / 1k`` theo đơn vị nghìn đồng
(VNDK), nên **1 đơn vị sảnh = 1.000đ**: chip ``10`` = 10.000đ, ``1k`` = 1.000.000đ.
Số gửi lên sàn đúng bằng số trên khay (``addBetMoney: 10`` cho chip 10), nên không cần
nhân quy đổi — chỉ cần chia tiền theo đúng mệnh giá đang có.

Quy trình ``place`` (giống ``LongLongTable.place`` của dự án cũ):
    1. đọc khay chip + ô cược, kiểm tra từng hộp có bấm được (đủ lớn, nằm trong khung);
    2. chờ hết hiệu ứng chia bài (lớp phủ kết quả che khay chip);
    3. chia số tiền thành mệnh giá **khít** (không đặt thiếu);
    4. mỗi chip: bấm chip → bấm ô → đọc lại số tiền đã treo, lệch là huỷ toàn bộ;
    5. đủ tiền mới bấm xác nhận, rồi đọc lại lần cuối.
"""

import json
import time

from aibcr.adapters import browser as BR
from aibcr.models import chips as CHIPS

# Mã ô cược trên WebSocket (protocol 22: ``betArea``) — đã đối chiếu với lệnh thật.
BET_AREA = {"B": 1, "P": 2, "T": 3}
SPOT_ID = {"B": "Banker", "P": "Player", "T": "Tie"}
SIDE_NAME = {"B": "Banker", "P": "Player", "T": "Hoà"}
# Một đơn vị sảnh = 1.000đ (khay WM in theo VNDK).
DONG_PER_UNIT = 1000.0

READ_JS = r"""(() => {
    const frame = document.getElementById('iframe_101');
    if (!frame) return {reason: 'no_table_frame'};
    const fs = getComputedStyle(frame);
    const fr = frame.getBoundingClientRect();
    if (fs.display === 'none' || fs.visibility === 'hidden' || fr.width < 10)
        return {reason: 'table_hidden'};
    let doc = null;
    try { doc = frame.contentDocument; } catch (e) { return {reason: 'cross_origin'}; }
    if (!doc) return {reason: 'no_document'};
    const box = (el) => {
        const r = el.getBoundingClientRect();
        return {cx: fr.x + r.x + r.width / 2, cy: fr.y + r.y + r.height / 2,
                w: r.width, h: r.height};
    };
    const local = (el) => {
        const r = el.getBoundingClientRect();
        const hit = doc.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return {w: r.width, h: r.height,
                hit: hit ? (hit.id || '') + '|' + (hit.className || '').toString().slice(0, 40) : ''};
    };
    const chips = [];
    for (const item of doc.querySelectorAll('#chip_box .chip_item')) {
        const cls = (item.className || '').toString();
        const m = /chip_b_([0-9a-z]+)/.exec(cls);
        if (!m) continue;
        const info = local(item);
        if (info.w < 4) continue;
        chips.push(Object.assign({key: m[1], on: item.classList.contains('on')},
                                 box(item), info));
    }
    const spots = {};
    for (const side of ['B', 'P', 'T']) {
        const id = side === 'B' ? 'Banker' : (side === 'P' ? 'Player' : 'Tie');
        const el = doc.getElementById(id);
        if (!el) continue;
        const holder = doc.getElementById('playbetbox' + id);
        const money = holder ? holder.querySelector('.mybet_money') : null;
        const value = money ? parseFloat((money.textContent || '').replace(/[^0-9.]/g, '')) : 0;
        spots[side] = Object.assign({my_bet: Number.isFinite(value) ? value : 0,
                                     chips: holder ? holder.children.length : 0},
                                    box(el), local(el));
    }
    const btn = (id) => { const e = doc.getElementById(id);
        if (!e) return null;
        const info = local(e);
        if (info.w < 4) return null;
        return Object.assign({cls: (e.className || '').toString()}, box(e)); };
    const wallet = document.getElementById('menu_ver2_balance');
    const countdown = doc.getElementById('countdown');
    return {
        chips, spots,
        betBtn: btn('bet_btn'), cancelBtn: btn('cancel_btn'),
        tray: (() => { const e = doc.getElementById('chip_box');
            if (!e) return null;
            const r = e.getBoundingClientRect();
            return {w: r.width, h: r.height}; })(),
        open_result: !!doc.querySelector('#opencard-wrapper.wrapper.on'),
        countdown: countdown ? (countdown.className || '').toString() : '',
        wallet: wallet ? (wallet.textContent || '').replace(/\s+/g, ' ').trim() : '',
        href: location.href.slice(0, 120)
    };
})()"""


def chip_value(key):
    """Đổi mã mệnh giá của khay ('10', '1k') sang số đơn vị sảnh."""
    text = str(key or "").strip().lower()
    if text.endswith("k"):
        try:
            return int(round(float(text[:-1]) * 1000))
        except ValueError:
            return 0
    try:
        return int(round(float(text)))
    except ValueError:
        return 0


def parse_denominations(chips):
    """Danh sách mệnh giá (đơn vị sảnh) từ khay đọc được."""
    values = []
    for chip in chips or []:
        value = chip_value((chip or {}).get("key"))
        if value > 0 and value not in values:
            values.append(value)
    return sorted(values)


def box_clickable(box, min_size=4):
    """Hộp có bấm được không: đủ lớn và toạ độ hợp lệ."""
    if not isinstance(box, dict):
        return False
    return (box.get("w") or 0) >= min_size and (box.get("h") or 0) >= min_size


def hovered(box):
    """Chuột đang nằm trên chính phần tử này (không bị lớp phủ che)."""
    if not isinstance(box, dict):
        return False
    hit = str(box.get("hit") or "")
    return "chip_item" in hit or "playbetbox" in hit or "table_item" in hit


class WMBet:
    """Đọc khay chip/ô cược và đặt chip thật trên bàn WM (chỉ một kết nối CDP mỗi lệnh)."""

    def __init__(self, session=None):
        self.session = session or BR.BrowserSession()
        self.last_error = ""
        self.last_state = {}

    # ------------------------------------------------------------------ kết nối
    def _command_factory(self, ws):
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
                if message.get("id") == seq:
                    if message.get("error"):
                        raise RuntimeError(str(message["error"])[:120])
                    return message.get("result", {})

        return command

    def read(self):
        """Đọc trạng thái bàn (khay chip, ô cược, số tiền đang treo, nút bấm).

        Ưu tiên kết nối CDP dùng chung của ``WMSocket``: ``wait_phase`` gọi hàm này vài
        lần mỗi giây, mở/đóng kết nối mới liên tục sẽ làm tab chậm và timeout.
        """
        value = None
        socket = getattr(self.session, "wm_socket", None)
        if socket is not None and getattr(socket, "_command", None) is not None:
            try:
                value = socket.evaluate(READ_JS)
            except Exception:
                value = None
        if value is None:
            value = self._read_once()
            if value is None:
                return {"ok": False, "error": self.last_error}
        if not isinstance(value, dict) or value.get("reason"):
            self.last_error = "Bàn WM chưa sẵn sàng (%s)." % (
                (value or {}).get("reason", "no_value"))
            return {"ok": False, "error": self.last_error}
        value["ok"] = True
        value["denominations"] = parse_denominations(value.get("chips"))
        value["my_bet"] = sum((spot or {}).get("my_bet") or 0
                              for spot in (value.get("spots") or {}).values())
        self.last_state = value
        self.last_error = ""
        return value

    def _read_once(self):
        """Đọc trạng thái qua một kết nối CDP riêng (dự phòng khi chưa có WMSocket)."""
        import websocket

        page = self.session._cdp_page()
        if page is None:
            self.last_error = "Không có tab WM trong Chrome."
            return None
        ws = None
        try:
            ws = websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            command = self._command_factory(ws)
            command("Runtime.enable")
            return command("Runtime.evaluate", {
                "expression": READ_JS, "returnByValue": True, "silent": True,
            }).get("result", {}).get("value")
        except Exception as exc:
            self.last_error = "Không đọc được bàn WM (%s)." % type(exc).__name__
            return None
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------ bấm chuột
    def _click(self, command, box, pause=0.14):
        """Bấm chuột thật tại tâm hộp (toạ độ đã quy về khung gốc)."""
        x, y = float(box["cx"]), float(box["cy"])
        command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y,
                                             "buttons": 0})
        command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                             "button": "left", "buttons": 1,
                                             "clickCount": 1})
        command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                             "button": "left", "buttons": 0,
                                             "clickCount": 1})
        time.sleep(pause)

    def _park_mouse(self, command):
        """Đưa con trỏ ra khỏi bàn cược để lớp hover không che khay chip."""
        try:
            command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 2, "y": 2,
                                                 "button": "none", "buttons": 0})
        except Exception:
            pass

    # ------------------------------------------------------------------ pha cược
    def wait_phase(self, deadline_seconds=40.0, poll=0.25):
        """Chờ bàn mở cửa cược: khay chip bấm được (không bị lớp kết quả che).

        Đây là điều kiện thật của WM — chính client cũng chỉ bấm được khi lớp phủ kết quả
        đã tan. Dùng chung cho cả WebSocket: gửi lệnh sớm sẽ bị server trả ``bOk: false``.
        Không dựa vào class ``#opencard-wrapper`` vì nó có thể "on" suốt ván.
        """
        deadline = time.monotonic() + max(1.0, float(deadline_seconds))
        while time.monotonic() < deadline:
            state = self.read()
            if state.get("ok"):
                chips = [chip for chip in state.get("chips") or [] if box_clickable(chip)]
                if chips and any(hovered(chip) for chip in chips):
                    return state
            time.sleep(poll)
        return {}

    # ------------------------------------------------------------------ đặt cược
    def place(self, side, units, confirm=True, max_chips=20, wait_seconds=40.0,
              settle_seconds=1.2):
        """Đặt ``units`` (đơn vị sảnh, 1 đv = 1.000đ) vào cửa ``side`` (B/P/T).

        Trả dict ``{"ok", "placed", "total", "denominations", "error"}``. Không bao giờ
        đặt thiếu tiền: không chia khít được thì dừng trước khi bấm.
        """
        side = str(side or "").upper()[:1]
        if side not in BET_AREA:
            return {"ok": False, "error": "Cửa cược không hợp lệ: %r" % (side,)}
        try:
            target = int(round(float(units)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Số tiền không hợp lệ: %r" % (units,)}
        if target <= 0:
            return {"ok": False, "error": "Số tiền phải lớn hơn 0."}

        # Chờ đúng cửa sổ cược trước khi làm bất cứ điều gì (áp dụng cho cả WS và chuột).
        phase = self.wait_phase(wait_seconds)
        if not phase:
            return {"ok": False, "error": "Bàn chưa mở cược trong %d giây." % int(wait_seconds)}

        # Đường nhanh: gửi lệnh cược thẳng qua WebSocket (protocol 22). Không phụ thuộc
        # khay chip/toạ độ nên không bị lớp phủ chia bài che. Chỉ dùng khi bàn đang sạch
        # chip để không cộng dồn nhầm vào lệnh cũ.
        if confirm:
            fast = self._place_ws(side, target)
            if fast is not None:
                return fast

        import websocket

        page = self.session._cdp_page()
        if page is None:
            return {"ok": False, "error": "Không có tab WM trong Chrome."}
        ws = None
        placed = []
        try:
            ws = websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            command = self._command_factory(ws)
            command("Runtime.enable")

            def read():
                value = command("Runtime.evaluate", {
                    "expression": READ_JS, "returnByValue": True, "silent": True,
                }).get("result", {}).get("value")
                return value if isinstance(value, dict) and not value.get("reason") else {}

            self._park_mouse(command)
            # Bàn đã mở cược (wait_phase ở trên); đọc lại một lần cho toạ độ mới nhất.
            state = read()
            deadline = time.monotonic() + max(1.0, float(wait_seconds))
            while time.monotonic() < deadline:
                chips = [chip for chip in state.get("chips") or []
                         if box_clickable(chip)]
                if chips and any(hovered(chip) for chip in chips) and state.get("spots"):
                    break
                time.sleep(0.3)
                state = read()
            if not state:
                return {"ok": False, "error": "Chưa đọc được bàn WM."}
            spot = (state.get("spots") or {}).get(side)
            if not box_clickable(spot):
                return {"ok": False, "error": "Không thấy ô cược %s." % SIDE_NAME[side]}
            denominations = parse_denominations(state.get("chips"))
            plan = CHIPS.decompose(target, unit=1, denominations=denominations)
            if not plan.get("exact") or not plan.get("chips"):
                return {"ok": False, "denominations": denominations,
                        "error": "Không chia được %d đv theo mệnh giá %s (thiếu %s đv)."
                                 % (target, denominations, plan.get("remainder_vnd"))}
            if len(plan["chips"]) > max_chips:
                return {"ok": False, "denominations": denominations,
                        "error": "Cần %d chip (> %d) — dừng cho an toàn."
                                 % (len(plan["chips"]), max_chips)}

            before = float(spot.get("my_bet") or 0)
            running = before
            by_value = {chip_value(chip.get("key")): chip
                        for chip in state.get("chips") or []}
            for value in plan["chips"]:
                chip = by_value.get(value)
                if not box_clickable(chip):
                    self._undo(command, state, len(placed))
                    return {"ok": False, "placed": placed, "denominations": denominations,
                            "error": "Không bấm được chip %s." % value}
                self._click(command, chip, pause=0.10)
                self._click(command, spot, pause=0.16)
                placed.append(value)
                # Xác minh ngay sau từng chip: cửa sổ cược có thể đóng giữa chừng.
                gained = self._wait_my_bet(command, read, side, running + value,
                                           timeout=settle_seconds)
                if gained is None:
                    probe = read()
                    self._undo(command, probe or state, len(placed))
                    return {"ok": False, "placed": placed, "denominations": denominations,
                            "error": "Ván đã đóng — chip không vào bàn (đã huỷ)."}
                running = gained
                spot = (read().get("spots") or {}).get(side) or spot

            total = running
            if abs(total - (before + target)) > 0.01:
                probe = read()
                self._undo(command, probe or state, len(placed))
                return {"ok": False, "placed": placed, "denominations": denominations,
                        "delta": total - before,
                        "error": "Đặt lệch: cần %d, bàn ghi %g — đã huỷ."
                                 % (target, total - before)}
            if not confirm:
                self._park_mouse(command)
                return {"ok": True, "placed": placed, "total": total,
                        "denominations": denominations, "confirmed": False,
                        "note": "Chip đã treo trên bàn (chưa bấm xác nhận)."}
            # Bấm xác nhận: chỉ lúc này sàn mới gửi protocol 22.
            probe = read()
            button = (probe or {}).get("betBtn")
            if not box_clickable(button):
                self._undo(command, probe or state, len(placed))
                return {"ok": False, "placed": placed, "denominations": denominations,
                        "error": "Không thấy nút xác nhận (đã huỷ chip)."}
            self._click(command, button, pause=0.2)
            time.sleep(0.8)
            self._park_mouse(command)
            after = read()
            remaining = sum((s or {}).get("my_bet") or 0
                            for s in (after.get("spots") or {}).values())
            return {"ok": True, "placed": placed, "total": total,
                    "denominations": denominations, "confirmed": True,
                    "bet_area": BET_AREA[side], "my_bet_after": remaining,
                    "note": "Đã đặt %d đv vào %s." % (target, SIDE_NAME[side])}
        except Exception as exc:
            self.last_error = "Lỗi khi đặt chip (%s)." % type(exc).__name__
            return {"ok": False, "placed": placed, "error": self.last_error}
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _place_ws(self, side, target):
        """Thử đặt qua WebSocket; ``None`` nghĩa là không dùng được, hãy bấm chuột."""
        from aibcr.adapters.wm_ws import get_socket

        socket = get_socket(self.session, start=False)
        if socket is None or not socket.ready():
            return None
        current = self.read_bets()
        if not current.get("ok"):
            return None
        if current.get("total"):
            # Đang có chip treo: gửi thêm qua WS sẽ cộng dồn — để đường bấm chuột xử lý.
            return None
        result = socket.place(side, target)
        if not result.get("ok"):
            # Server từ chối/lỗi gửi: KHÔNG bỏ tay — rơi về bấm chuột (đường đã kiểm chứng
            # với chính client của sàn, có đọc lại số tiền sau từng chip).
            return None
        # Xác minh bằng số chip thật đang treo trên bàn.
        deadline = time.monotonic() + 2.5
        placed = 0.0
        while time.monotonic() < deadline:
            after = self.read_bets()
            placed = float(((after.get("spots") or {}).get(side) or {}).get("amount") or 0)
            if abs(placed - target) < 0.01:
                break
            time.sleep(0.2)
        if abs(placed - target) >= 0.01:
            # Lệch: huỷ ngay bằng nút huỷ của bàn để không giữ lệnh sai.
            undo = self.cancel()
            return {"ok": False, "placed": [], "denominations": current.get("denominations") or [],
                    "via": "ws", "error": "WS đặt lệch: cần %d, bàn ghi %g%s."
                             % (target, placed,
                                " (đã huỷ)" if undo.get("ok") else " (chưa huỷ được!)")}
        return {"ok": True, "placed": [target], "total": placed, "via": "ws",
                "denominations": current.get("denominations") or [],
                "confirmed": True, "bet_area": BET_AREA[side],
                "note": "Đã đặt %d đv vào %s qua WebSocket." % (target, SIDE_NAME[side])}

    def _wait_my_bet(self, command, read, side, target, timeout=1.2):
        """Chờ số tiền treo trên cửa đạt ``target``; trả tổng mới hoặc None nếu không lên."""
        deadline = time.monotonic() + max(0.2, float(timeout))
        while True:
            state = read()
            spot = (state.get("spots") or {}).get(side) or {}
            total = float(spot.get("my_bet") or 0)
            if total + 0.01 >= float(target):
                return total
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.12)

    def _undo(self, command, state, times):
        """Bấm nút huỷ để trả chip về (mỗi cú bấm huỷ toàn bộ chip đang treo)."""
        button = (state or {}).get("cancelBtn")
        if not box_clickable(button):
            return False
        try:
            self._click(command, button, pause=0.2)
            self._park_mouse(command)
            return True
        except Exception:
            return False

    def cancel(self):
        """Huỷ toàn bộ chip đang treo trên bàn (nếu có)."""
        state = self.read()
        if not state.get("ok"):
            return {"ok": False, "error": state.get("error") or "Chưa đọc được bàn."}
        if not state.get("my_bet"):
            return {"ok": True, "note": "Không có chip nào đang treo."}
        import websocket

        page = self.session._cdp_page()
        ws = None
        try:
            ws = websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            command = self._command_factory(ws)
            command("Runtime.enable")
            done = self._undo(command, state, 1)
            time.sleep(0.5)
            after = self.read()
            return {"ok": True, "cancelled": done,
                    "my_bet_after": after.get("my_bet") if after.get("ok") else None}
        except Exception as exc:
            return {"ok": False, "error": "Lỗi khi huỷ chip (%s)." % type(exc).__name__}
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------ tiện ích
    def read_bets(self):
        """Chip của CHÍNH MÌNH đang treo trên bàn, cùng định dạng ``table_bets.read``.

        Trả ``spots``/``total``/``total_units``/``denominations``/``unit`` để
        ``live_sim.compare_chips`` và ``table_is_clear`` dùng lại được mà không phải
        biết đang đọc bàn EVO hay WM.
        """
        state = self.read()
        if not state.get("ok"):
            return {"ok": False, "error": state.get("error") or "Chưa đọc được bàn.",
                    "spots": {}, "unit": 1, "denominations": [], "ts": time.time()}
        spots = {}
        for side, spot in (state.get("spots") or {}).items():
            units = float((spot or {}).get("my_bet") or 0)
            spots[side] = {"amount": units, "amount_vnd": units,
                           "chips": int((spot or {}).get("chips") or 0)}
        total = sum(item["amount"] for item in spots.values())
        return {"ok": True, "error": "", "source": "wm",
                "spots": spots, "total": total, "total_units": total,
                "denominations": state.get("denominations") or [],
                "unit": 1, "wallet": state.get("wallet") or "",
                "countdown": state.get("countdown") or "",
                "open_result": bool(state.get("open_result")),
                "ts": time.time(),
                "note": "Chip của bạn đang treo trên bàn WM (1 đv = 1.000đ)."}


def to_site_amount(units):
    """Đổi đơn vị sảnh (1 đv = 1.000đ) sang số tiền gửi sàn — WM giữ nguyên số."""
    try:
        return int(round(float(units or 0)))
    except (TypeError, ValueError):
        return 0


def to_units(amount_vnd):
    """Đổi tiền thật (đồng) về đơn vị sảnh của WM."""
    try:
        return float(amount_vnd or 0) / DONG_PER_UNIT
    except (TypeError, ValueError):
        return 0.0
