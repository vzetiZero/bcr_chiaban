# -*- coding: utf-8 -*-
"""Tầng Model: vòng đời một phiên đọc bàn + các hàm thuần dùng chung.

Không còn phương pháp 3-3/3-2, thang cược hay khối mạnh/yếu. Lệnh cược do UI
cấu hình cho từng tay (cửa + số chip cố định) hoặc lấy từ nhận định AI; model này
chỉ giữ phần chung: theo dõi cầu, đối chiếu chip thật, ghi lãi/lỗ và chốt lời.
Không import tkinter, không import adapter — chạy độc lập và test bằng dữ liệu thuần.
"""

import re
import time

from aibcr.config import *  # noqa: F401,F403  (BET_GATE_*, PLACE_*, LIVE_STALE)
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


def signed(value):
    return ("+" if value > 0 else "") + M.fmt_money(value)


def group_money_input(raw, caret):
    """Nhóm ô nhập tiền theo dấu phẩy hàng nghìn và giữ vị trí con trỏ."""
    raw = str(raw)
    separators = [char for char in raw if char in ",."]
    decimal = ""
    if "," in raw and "." in raw:
        decimal = "." if raw.rfind(".") > raw.rfind(",") else ","
    elif separators:
        sep = separators[0]
        pieces = raw.split(sep)
        if len(pieces) == 2 and (1 <= len(pieces[1]) <= 2):
            decimal = sep
        elif len(pieces) > 2 and len(pieces[-1]) <= 2 and all(len(p) == 3 for p in pieces[1:-1]):
            decimal = sep
    if decimal:
        whole, fraction = raw.rsplit(decimal, 1)
        whole_digits = re.sub(r"\D", "", whole)
        fraction = re.sub(r"\D", "", fraction)
        grouped_whole = M.fmt_input_money(int(whole_digits)) if whole_digits else "0"
        grouped = grouped_whole + "." + fraction
    else:
        whole_digits = re.sub(r"\D", "", raw)
        fraction = ""
        grouped = M.fmt_input_money(int(whole_digits)) if whole_digits else ""
    if grouped == raw:
        return raw, caret
    kept = len(re.sub(r"\D", "", raw[:caret]))
    if decimal and raw.rfind(decimal) < caret and kept >= len(whole_digits):
        return grouped, min(len(grouped), len(M.fmt_input_money(int(whole_digits)) if whole_digits else "0")
                            + 1 + max(0, kept - len(whole_digits)))
    if kept >= len(whole_digits) + len(fraction):
        return grouped, len(grouped)
    seen = 0
    for index, char in enumerate(grouped):
        if char.isdigit():
            seen += 1
            if seen == kept + 1:
                return grouped, index
    return grouped, len(grouped)


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
    """Theo dõi một bàn; lệnh cược được chốt từ UI/AI chứ không tự sinh."""

    def __init__(self, book=None, unit=100.0):
        self.money = book or M.MoneyBook(capital=3000.0, unit=unit, take_profit_pct=25.0)
        self.results = []
        self.log = []
        self.table_key = None
        self.table_name = "Chưa chọn bàn"
        self.letters = ""
        self.running = False
        self.entry_waiting = False
        self.pending = None
        self.note = "Chọn bàn để theo dõi."
        self.place_skips = 0
        self.cycle_done = False
        self.take_profit_done = False

    def bind(self, row):
        self.pause()
        self.table_key, self.table_name = row["key"], row["label"]
        self.letters = row["letters"]
        self.results = list(self.letters)
        self.place_skips = 0
        self.cycle_done = False
        self.take_profit_done = False
        self.entry_waiting = False
        self.note = "Đã chọn bàn."

    def start(self, row):
        """Bắt đầu theo dõi bàn đã chọn.

        Không chờ "hết tay hiện tại" nữa: WM chỉ gửi kết quả khi ván kết thúc, nên trạng
        thái chờ đó có thể treo rất lâu và UI đứng im. Tay đang chạy không có lệnh nên
        không bị tính tiền; lệnh đầu tiên được arm ngay cho tay kế và gate đặt chip
        (`_wait_for_next_hand`) vẫn chờ bàn dọn chip trước khi bấm.
        """
        if row["key"] != self.table_key:
            self.note = "Hãy chọn bàn trước."
            return False
        if row["letters"] != self.letters:
            self.bind(row)
        if self.money.blocked:
            self.note = self.money.blocked[1]
            return False
        self.running = True
        self.entry_waiting = False
        self.pending = None
        self.note = "Đang theo dõi · sẽ tự đặt cược tay kế tiếp."
        return True

    def pause(self, reason="Đã tạm dừng. Không ghi thêm kết quả vào vốn."):
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
        self.cycle_done = False

    def set_order(self, side, stake, reason="", baseline=None):
        """Chốt lệnh cược cho tay kế tiếp (do UI bấm nút “Tự đặt cược”)."""
        if side not in (E.BANKER, E.PLAYER, E.TIE) or float(stake or 0) <= 0:
            return None
        self.pending = {
            "side": side, "stake": float(stake), "reason": str(reason or ""),
            "baseline": self.letters if baseline is None else baseline,
            "armed_at": time.time(), "placed": None,
        }
        self.note = "Đã chốt %s · %s đv · chờ ván mới để bấm chip." % (
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

    def _skip_unplaced_hand(self, letters, order):
        """Tay có chữ mới nhưng không đặt được chip: chỉ cập nhật cầu, không đụng vốn."""
        reason = order.get("place_note") or "không xác nhận được lượt đặt chip."
        self.letters = letters
        self.results = list(letters)
        self.place_skips += 1
        self.log.append(dict(time=time.time(), armed_at=order.get("armed_at"),
                             table=self.table_name, table_key=self.table_key,
                             hand=len(letters), result=letters[-1], bet=order["side"], stake=0,
                             delta=0.0, outcome="not_placed", balance_after=self.money.balance,
                             source="chip-not-placed"))
        if self.place_skips >= PLACE_SKIP_LIMIT:
            self.pause("Đã bỏ %d tay liên tiếp vì không đặt được chip thật (%s). Dừng để kiểm tra "
                       "khay chip và ô cược." % (self.place_skips, reason))
            return False
        self.note = ("Tay %d không được tính vì chưa đặt được chip (%s). Cấu hình lại lệnh cho tay kế."
                     % (len(letters), reason))
        self.pending = None
        return False

    def process(self, row, now=None):
        if not self.running:
            return False
        if not row or row["key"] != self.table_key:
            self.pause("Không còn đọc được bàn đang theo dõi. Hãy chọn lại bàn.")
            return False
        letters = row["letters"]
        problem = row_problem(row, now, check_fresh=False)
        if row.get("conflict") or row.get("read_error"):
            self.pause(problem)
            return False
        current_time = time.time() if now is None else now
        if current_time - row["ts"] > LIVE_STALE:
            if letters == self.letters:
                return False
            self.pause(row_problem(row, now))
            return False
        if row.get("stable", 0) < 2:
            return False
        if problem:
            self.pause(problem)
            return False
        if letters == self.letters:
            return False
        if not letters.startswith(self.letters):
            # Cầu không nối tiếp cầu cũ: bàn được vẽ lại/xem lịch sử khác nguồn, hoặc vừa
            # đổi shoe. Đồng bộ lại thay vì dừng phiên — dừng ở đây là lý do UI "đứng im"
            # dù bàn vẫn có kết quả mới.
            lost = self.pending
            self.letters = letters
            self.results = list(letters)
            self.entry_waiting = False
            if lost:
                self.pending = None
                self.place_skips += 1
                self.note = "Cầu đổi nguồn · đã đồng bộ lại %d tay, bỏ tay đang chờ chip." % len(letters)
            else:
                self.note = "Đã đồng bộ lại cầu (%d tay)." % len(letters)
            return True
        if len(letters) > len(self.letters) + 1:
            # Nguồn dữ liệu nhảy nhiều tay (lần đầu đọc được lịch sử dài hơn): nhận cầu mới
            # nhưng không tự tính lãi/lỗ cho các tay không đặt được.
            jumped = len(letters) - len(self.letters)
            self.letters = letters
            self.results = list(letters)
            self.entry_waiting = False
            if self.pending:
                self.pending = None
                self.place_skips += 1
                self.note = ("Nhảy %d tay cùng lúc · bỏ lệnh đang chờ, cầu đã cập nhật."
                             % jumped)
            else:
                self.note = "Đã cập nhật cầu (+%d tay)." % jumped
            return True

        if self.entry_waiting:
            self.letters = letters
            self.results = list(letters)
            self.entry_waiting = False
            self.note = "Đã nhận kết quả tay hiện tại · sẵn sàng nhận lệnh cược tay kế."
            return True

        order = self.pending
        if not order or order.get("baseline") != self.letters:
            # Không có lệnh: vẫn cập nhật cầu để UI hiển thị, nhưng không tính vốn.
            self.letters = letters
            self.results = list(letters)
            self.note = "Đã cập nhật cầu · chưa có lệnh cược cho tay này."
            return True

        if order.get("placed") == "pending":
            if current_time - (order.get("placing_at") or current_time) > PLACE_CONFIRM_TIMEOUT:
                order["placed"] = "failed"
                order["place_note"] = ("không có xác nhận đặt chip sau %d giây (lượt bấm có thể "
                                       "đã chết giữa chừng)." % int(PLACE_CONFIRM_TIMEOUT))
            else:
                order.setdefault("result_seen_at", current_time)
                self.note = "Chờ xác nhận đã đặt chip thật xong rồi mới tính tay này."
                return False
        if order.get("placed") == "failed":
            return self._skip_unplaced_hand(letters, order)
        if order.get("placed") != "ok":
            order["place_note"] = "không có xác nhận web đã đặt chip cho tay này."
            return self._skip_unplaced_hand(letters, order)
        if (order.get("result_seen_at")
                and (order.get("confirmed_at") or 0) > order["result_seen_at"]):
            order["place_note"] = ("chip chỉ được xác nhận sau khi kết quả tay này đã về "
                                   "(bấm sang cửa sổ tay sau) nên tay này không được tính.")
            return self._skip_unplaced_hand(letters, order)

        self.place_skips = 0
        result = letters[-1]
        settled = self.money.settle(order["side"], result, order["stake"], E.PAYOUT)
        self.letters = letters
        self.results = list(letters)
        self.pending = None
        self.log.append(dict(time=time.time(), armed_at=order.get("armed_at"),
                             table=self.table_name, table_key=self.table_key,
                             hand=len(letters), result=result, bet=order["side"],
                             stake=order["stake"], delta=settled["delta"],
                             outcome=settled["outcome"], balance_after=self.money.balance,
                             source="live-driver"))
        if self.money.blocked:
            self.pause(self.money.blocked[1])
            if self.money.blocked[0] == "TAKE_PROFIT":
                self.take_profit_done = True
                self.cycle_done = True
                self.note = ("Đã đạt mục tiêu lãi %.0f%% vốn (%s) · rời bàn." % (
                    self.money.take_profit_pct, M.fmt_money(self.money.profit)))
        else:
            self.note = "Đã ghi tay %d (%s) · chờ lệnh tiếp theo." % (len(letters), result)
        return True
