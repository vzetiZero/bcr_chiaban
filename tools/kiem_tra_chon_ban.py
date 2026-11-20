# -*- coding: utf-8 -*-
"""Kiểm tra THỰC TẾ ở mức chọn bàn (chạy với Chrome/sảnh thật của bạn).

Cách dùng (Chrome đang mở sảnh Baccarat với CDP 9222):

    python tools/kiem_tra_chon_ban.py              # chỉ đọc sảnh, in danh sách bàn
    python tools/kiem_tra_chon_ban.py --vao-ban    # đọc sảnh rồi bấm ô bàn ĐẦU TIÊN có
                                                   # mã bàn và chờ đọc được cầu (KHÔNG cược)

Không còn điều kiện lọc cầu: bàn nào có mã bàn thì vào bàn đó. --vao-ban dùng đúng
quy trình của nút “VÀO BÀN HỢP LỆ” nhưng dừng ở bước đọc được cầu: không arm kế
hoạch, không bấm chip.
"""

import argparse
import pathlib
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aibcr.adapters import browser as BR
from aibcr.models import engine as E
from aibcr.models.live_sim import table_stats

ENTRY_WAIT = 75


def cdp_open(port=BR.CDP_PORT, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


class _Emitter:
    def event(self, name, data):
        pass

    def reply(self, request_id, result=None, error=None):
        pass

    def send(self, payload):
        pass


def print_board(rows):
    width = max([len(str(row.get("label"))) for row in rows] + [8])
    print("%-*s %5s %-7s %s" % (width, "BÀN", "TAY", "MẠNH", "MÃ BÀN"))
    for row in rows:
        info = table_stats(list(row.get("letters") or ""))
        print("%-*s %5d %-7s %s" % (
            width, str(row.get("label"))[:width], info["hands"],
            E.SIDE_NAME.get(info["strong"], "—"), row.get("table_id") or "—"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vao-ban", action="store_true",
                    help="bấm ô bàn đầu tiên có mã rồi chờ đọc được cầu (không đặt cược)")
    ap.add_argument("--favorites", action="store_true", help="chỉ quét bàn Ưa thích")
    ap.add_argument("--timeout", type=float, default=ENTRY_WAIT,
                    help="giây chờ đọc được cầu sau khi mở bàn (mặc định 75)")
    args = ap.parse_args()

    if not cdp_open():
        print("Không thấy Chrome CDP ở cổng %d." % BR.CDP_PORT)
        print("Mở Chrome kèm --remote-debugging-port=%d, đăng nhập và vào sảnh Baccarat."
              % BR.CDP_PORT)
        return 2

    # Dùng đúng controller/service thật; chỉ tắt đặt chip để không đụng tiền.
    from aibcr.service import engine

    service = engine.BaccaratService(pathlib.Path(tempfile.mkdtemp()) / "probe.json", _Emitter())
    service.config_set({"auto_place": False})
    service.tool_running = False
    if not service.browser.connected:
        service.browser.attach()
    if not service.browser.connected:
        print("Chưa gắn được Chrome CDP:", getattr(service.browser, "note", "")
              or getattr(service.browser, "last_error", "") or "không rõ lý do")
        return 2

    ok, note = service.stream.find_lobby_tab()
    if not ok:
        print("Không nhận được tab sảnh:", note)
        return 2

    print("Đang quét sảnh (cuộn hết danh sách, có thể mất tới 75 giây)…")
    rows = service.stream.sweep(favorites_only=args.favorites)
    if not rows:
        print("Không đọc được bàn:", service.stream.last_error or "sảnh chưa có dữ liệu")
        return 2

    print("\nĐã đọc %d bàn\n" % len(rows))
    print_board(rows)

    passed = [row for row in rows if row.get("table_id")]
    if not passed:
        print("\nKhông có bàn nào có mã bàn để mở.")
        return 1
    if not args.vao-ban:
        print("\nBàn sẽ được mở: %s" % passed[0].get("label"))
        return 0

    table_id = passed[0].get("table_id")
    print("\nBấm ô bàn %s…" % passed[0].get("label"))
    ok, note = service.stream.open_table(table_id)
    print(note)
    if not ok:
        return 1

    print("Chờ đọc được cầu trong bàn, tối đa %ds…" % args.timeout)
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        reports = service.browser.scan()
        tables = [table for report in reports for table in report.get("tables", [])]
        row = next((table for table in tables if table.get("id") == table_id), None)
        if row:
            state = (row.get("source"), len(row.get("letters") or ""))
            if state != last:
                print("  đọc được %d tay · nguồn %s%s" % (
                    state[1], row.get("source"),
                    " · lỗi: " + row["read_error"] if row.get("read_error") else ""))
                last = state
            if row.get("letters"):
                print("\nĐẠT: đã vào bàn và đọc được cầu. Chưa đặt cược (đúng thiết kế).")
                return 0
        time.sleep(1.5)
    print("\nHết %ds mà chưa đọc được cầu trong bàn." % args.timeout)
    return 1


if __name__ == "__main__":
    sys.exit(main())
