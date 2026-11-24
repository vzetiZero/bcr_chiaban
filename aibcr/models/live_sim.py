# -*- coding: utf-8 -*-
"""Tầng Model: vòng đời một phiên bám bàn + các hàm thuần dùng chung.

Không còn phương pháp 3-3/3-2, thang cược, dự đoán hay quyết toán. Lệnh cược do UI
cấu hình cho từng ván (cửa + số chip cố định); model này chỉ giữ phần chung: giữ
bàn đang bám, cập nhật cầu, quản vòng đời lệnh cược và đối chiếu chip thật.
Không import tkinter, không import adapter — chạy độc lập và test bằng dữ liệu thuần.
"""

import time

from aibcr.config import *  # noqa: F401,F403  (PLACE_*, LIVE_STALE)
from aibcr.models import chips
from aibcr.models import engine as E
from aibcr.models import money as M


def row_problem(row, now=None, check_fresh=True):
    """Lỗi đọc dữ liệu thật sự (mất kết nối, dữ liệu cũ, xung đột)."""
    now = time.time() if now is None else now
    if not row:
        return "Chưa có dữ liệu bàn. Mở Chrome, đăng nhập và chọn một bàn."
    if check_fresh and now - row["ts"] > LIVE_STALE:
        return "Dữ liệu quá %d giây chưa cập nhật. Đã dừng để tránh tính sai." % LIVE_STALE
    if row.get("conflict"):
        return "Có nhiều cầu khác nhau cùng tên bàn. Cần đối chiếu lại."
    if row.get("read_error"):
        return row["read_error"]
    return ""


def table_is_clear(live):
    """True nếu cả 3 cửa B/P/T đang trống — suy luận "đã sang ván mới"."""
    if not isinstance(live, dict) or not live.get("ok"):
        return False
    spots = live.get("spots") or {}
    for side in ("B", "P", "T"):
        entry = spots.get(side) or {}
        if float(entry.get("amount") or entry.get("amount_vnd") or 0) > 0:
            return False
    return True


def parse_road(text):
    """Đọc cầu dạng chữ: B=Banker, P=Player, T=Hoà. Ký tự khác bị bỏ qua."""
    mapping = {"B": E.BANKER, "P": E.PLAYER, "T": E.TIE}
    return [mapping[ch] for ch in str(text or "").upper() if ch in mapping]


def strong_side(results):
    """Bên ra nhiều tay hơn; hoà điểm thì lấy Banker (quy ước cửa đỏ)."""
    dec = E.decisions_only(results)
    banker, player = dec.count(E.BANKER), dec.count(E.PLAYER)
    if banker == player:
        return E.BANKER, {"banker": banker, "player": player, "tie_break": True,
                          "tie_side": E.BANKER}
    if banker > player:
        return E.BANKER, {"banker": banker, "player": player, "tie_break": False}
    return E.PLAYER, {"banker": banker, "player": player, "tie_break": False}


def table_stats(results):
    """Số liệu một bàn: bên mạnh, B/P, lệch, vệt cuối."""
    side, detail = strong_side(results)
    dec = E.decisions_only(results)
    banker, player = dec.count(E.BANKER), dec.count(E.PLAYER)
    runs = E.run_lengths(results)
    return {
        "hands": len(results),
        "strong": side,
        "weak": E.PLAYER if side == E.BANKER else E.BANKER,
        "strong_detail": detail,
        "streak": runs[-1] if runs else None,
        "banker": banker,
        "player": player,
        "lead": abs(banker - player),
        "tie_break": bool(detail.get("tie_break")),
    }


def compare_chips(order_side, order_stake, live, unit=None):
    """So chip thật trên bàn với lệnh cược đã chốt.

    Trả dict(status, side, expected, actual, extra, suggested_chips, note):
      match / no_bet / wrong_side / wrong_amount / extra_bets / ungroupable / unknown
    """
    expected = float(order_stake or 0)
    if not isinstance(live, dict) or not live.get("ok"):
        split = chips.decompose(expected, unit or chips.DEFAULT_CHIP_UNIT)
        return {"status": "unknown", "side": order_side, "expected": expected, "actual": 0.0,
                "extra": {}, "suggested_chips": split["chips"],
                "note": "Chưa đọc được chip trên bàn."}

    chip_unit = int(live.get("unit") or unit or chips.DEFAULT_CHIP_UNIT)
    spots = live.get("spots") or {}
    amounts = {side: float((spots.get(side) or {}).get("amount_vnd") or 0)
               for side in (E.BANKER, E.PLAYER, E.TIE)}
    total = sum(amounts.values())
    actual = amounts.get(order_side, 0.0)
    extra = {side: value for side, value in amounts.items() if side != order_side and value > 0}
    split = chips.decompose(expected, chip_unit, live.get("denominations") or None)

    if not split["exact"]:
        return {"status": "ungroupable", "side": order_side, "expected": expected,
                "actual": actual, "extra": extra, "suggested_chips": split["chips"],
                "note": "%s không ghép được bằng mệnh giá chip đang có (thiếu %s)." % (
                    M.fmt_money(expected), M.fmt_money(split["remainder_vnd"]))}
    if total <= 0:
        return {"status": "no_bet", "side": order_side, "expected": expected, "actual": 0.0,
                "extra": {}, "suggested_chips": split["chips"],
                "note": "Chưa đặt chip nào trên bàn."}
    if actual <= 0 and extra:
        placed = next(iter(extra))
        return {"status": "wrong_side", "side": order_side, "expected": expected, "actual": 0.0,
                "extra": extra, "suggested_chips": split["chips"],
                "note": "Đang đặt %s ở %s — lệnh là %s." % (
                    M.fmt_money(sum(extra.values())), E.SIDE_NAME[placed], E.SIDE_NAME[order_side])}
    if abs(actual - expected) >= 1:
        return {"status": "wrong_amount", "side": order_side, "expected": expected, "actual": actual,
                "extra": extra, "suggested_chips": split["chips"],
                "note": "Đặt %s nhưng lệnh là %s ở %s." % (
                    M.fmt_money(actual), M.fmt_money(expected), E.SIDE_NAME[order_side])}
    if extra:
        return {"status": "extra_bets", "side": order_side, "expected": expected, "actual": actual,
                "extra": extra, "suggested_chips": split["chips"],
                "note": "Đúng %s %s nhưng còn đặt thêm %s ở cửa khác." % (
                    E.SIDE_NAME[order_side], M.fmt_money(actual),
                    M.fmt_money(sum(extra.values())))}
    return {"status": "match", "side": order_side, "expected": expected, "actual": actual,
            "extra": {}, "suggested_chips": split["chips"],
            "note": "Chip khớp lệnh: %s %s." % (E.SIDE_NAME[order_side], M.fmt_money(actual))}


class LiveSimulation:
    """Bám một bàn: giữ cầu đã đọc và vòng đời lệnh cược của ván kế.

    Không tính thắng/thua, không giữ sổ tiền, không đổi mức cược theo kết quả: chỉ
    cần biết "ván này đã xếp chip chưa" để nhường lượt cho ván sau.
    """

    def __init__(self, unit=100.0):
        self.unit = float(unit or 100.0)
        self.results = []
        self.table_key = None
        self.table_name = "Chưa chọn bàn"
        self.letters = ""
        self.running = False
        self.entry_waiting = False
        self.pending = None
        self.note = "Chọn bàn để theo dõi."
        self.place_skips = 0

    def bind(self, row):
        self.pause()
        self.table_key, self.table_name = row["key"], row["label"]
        self.letters = row["letters"]
        self.results = list(self.letters)
        self.place_skips = 0
        self.entry_waiting = False
        self.note = "Đã chọn bàn."

    def start(self, row):
        """Bắt đầu bám bàn đã chọn; lệnh đầu tiên được arm ngay cho ván kế."""
        if row["key"] != self.table_key:
            self.note = "Hãy chọn bàn trước."
            return False
        if row["letters"] != self.letters:
            self.bind(row)
        self.running = True
        self.entry_waiting = False
        self.pending = None
        self.note = "Đang theo dõi · sẽ xếp chip cho ván kế tiếp."
        return True

    def pause(self, reason="Đã tạm dừng."):
        self.running = False
        self.entry_waiting = False
        self.pending = None
        self.note = reason

    def detach(self, reason="Đã rời bàn."):
        """Rời bàn: dừng theo dõi và bỏ liên kết bàn (dùng khi tool dừng về sảnh)."""
        self.pause(reason)
        self.table_key = None
        self.table_name = "Chưa chọn bàn"
        self.letters = ""
        self.results = []
        self.place_skips = 0

    def set_order(self, side, stake, reason="", baseline=None):
        """Chốt lệnh cược cho ván kế tiếp (do UI bấm nút “Tự đặt cược”)."""
        if side not in (E.BANKER, E.PLAYER, E.TIE) or float(stake or 0) <= 0:
            return None
        self.pending = {
            "side": side, "stake": float(stake), "reason": str(reason or ""),
            "baseline": self.letters if baseline is None else baseline,
            "armed_at": time.time(), "placed": None,
        }
        self.note = "Đã chốt %s · %s đv · chờ ván mới để xếp chip." % (
            E.SIDE_NAME[side], M.fmt_money(stake))
        return self.pending

    def mark_placing(self, order=None):
        order = self.pending if order is None else order
        if order is not None:
            order["placed"] = "pending"
            order["placing_at"] = time.time()

    def mark_placed(self, ok, note="", order=None):
        target = self.pending if order is None else order
        if target is None or target is not self.pending or target.get("placed") != "pending":
            return False
        target["placed"] = "ok" if ok else "failed"
        target["place_note"] = note
        target["confirmed_at"] = target.get("placed_at") or time.time()
        return True

    def process(self, row, now=None):
        """Nhận cầu mới của bàn đang bám; trả True khi cầu thật sự đổi."""
        if not self.running:
            return False
        if not row or row["key"] != self.table_key:
            self.pause("Không còn đọc được bàn đang theo dõi. Hãy chọn lại bàn.")
            return False
        letters = row["letters"]
        if row.get("conflict") or row.get("read_error"):
            self.pause(row_problem(row, now, check_fresh=False))
            return False
        current_time = time.time() if now is None else now
        if current_time - row["ts"] > LIVE_STALE:
            if letters == self.letters:
                return False
            self.pause(row_problem(row, now))
            return False
        if row.get("stable", 0) < 2:
            return False
        if letters == self.letters:
            return False
        if not letters.startswith(self.letters):
            # Cầu không nối tiếp cầu cũ (bàn vẽ lại/đổi shoe): đồng bộ lại thay vì dừng.
            self.letters = letters
            self.results = list(letters)
            self.entry_waiting = False
            self.pending = None
            self.note = "Đã đồng bộ lại cầu (%d ván)." % len(letters)
            return True

        jumped = len(letters) - len(self.letters)
        order = self.pending
        self.letters = letters
        self.results = list(letters)
        self.entry_waiting = False
        if order and len(letters) > len(str(order.get("baseline") or "")):
            self.pending = None
            if order.get("placed") == "ok":
                self.place_skips = 0
                self.note = "Ván %d đã xong · chờ lệnh cho ván kế." % len(letters)
            else:
                self.place_skips += 1
                reason = order.get("place_note") or "chưa xác nhận được lượt xếp chip."
                self.note = ("Ván %d chưa xếp được chip (%s) · chờ lệnh cho ván kế."
                             % (len(letters), reason))
            return True
        if order and order.get("placed") == "pending":
            self.note = "Đang chờ xác nhận đã xếp chip cho ván này."
            return True
        self.note = "Đã cập nhật cầu (+%d ván)." % jumped
        return True



