# -*- coding: utf-8 -*-
"""Đưa nhiều profile (nhiều cổng CDP) về sảnh DG rồi vào CÙNG một bàn.

Chỉ dùng CDP thuần: không Selenium, nên Chrome của người dùng không bị tắt.

Với mỗi cổng:
  1. Tìm target DG. Nếu sảnh còn nằm trong iframe của trang site thì đưa chính
     URL đó lên tab (``Page.navigate``) — đúng bước app làm để bỏ popup site.
  2. Bỏ ``tableId`` để về sảnh và chờ Laya vẽ lại lưới bàn.
  3. Thêm ``tableId`` của bàn chung và chờ ``in_table`` đúng bàn đó.

    python tools/sync_profiles.py --table 60101 --ports 9222 9223
"""

import json
import sys
import time
import urllib.parse as up

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402

KEEP = ("table_id", "table_name", "round_id", "state_id", "countdown", "bet_open",
        "min_k", "max_k", "balance_k", "balance_known")


def page_rows(port):
    return [row for row in targets(port)
            if row.get("type") == "page" and "devtools://" not in (row.get("url") or "")]


def dg_row(port):
    rows = [row for row in targets(port)
            if "ddnew" in (row.get("url") or "").lower() and row.get("webSocketDebuggerUrl")]
    return rows[0] if rows else None


def navigate(port, url):
    """``Page.navigate`` trên websocket của tab (gửi qua browser socket bị bỏ qua)."""
    import websocket
    rows = page_rows(port)
    row = next((item for item in rows if "ddnew" in (item.get("url") or "").lower()), None)
    if row is None:
        if not rows:
            return {"error": "no-page"}
        row = rows[0]
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=40)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                return reply.get("result") or ({"error": reply.get("error")})
    finally:
        ws.close()


def read(port, which="bet"):
    """Đọc state/lobby/bet từ target DG hiện tại của cổng."""
    row = dg_row(port)
    if not row:
        return {}
    target = Target(row)
    try:
        code = {"state": DG._DG_STATE_JS, "lobby": DG._DG_LOBBY_JS,
                "bet": DG._DG_BET_STATE_JS}[which]
        return target.eval(wrap(code)) or {}
    finally:
        target.close()


def wait_until(port, which, want, timeout=60.0, interval=1.5):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = read(port, which)
        if want(last):
            return last
        time.sleep(interval)
    return last


def to_lobby(port, label):
    """Đưa sảnh về tab chính (nếu còn trong iframe) rồi bỏ ``tableId``."""
    row = dg_row(port)
    if not row:
        return {"ok": False, "error": "chưa thấy sảnh DG — hãy mở DG trên site này trước"}
    url = row["url"]
    if row.get("type") != "page":
        site = page_rows(port)
        print("  %s: sảnh đang trong iframe của %s → đưa lên tab"
              % (label, (site[0]["url"] or "").split("?")[0] if site else "?"), flush=True)
        navigate(port, url)
        time.sleep(4)
        row = dg_row(port)
        if not row or row.get("type") != "page":
            return {"ok": False, "error": "không đưa được sảnh lên tab"}
        url = row["url"]

    lobby_url = DG._lobby_url_from(url)
    if url != lobby_url:
        navigate(port, lobby_url)
    lobby = wait_until(port, "lobby",
                       lambda value: bool((value or {}).get("tables")), timeout=45)
    tables = [item.get("table_id") for item in (lobby.get("tables") or [])]
    print("  %s: sảnh %s — %d bàn %s"
          % (label, (dg_row(port) or {}).get("url", "").split("?")[0],
             len(tables), tables), flush=True)
    return {"ok": bool(tables), "tables": tables,
            "url": (dg_row(port) or {}).get("url", "")}


def enter(port, label, table_id):
    row = dg_row(port)
    if not row:
        return {"ok": False, "error": "mất sảnh DG"}
    url = DG._loader_url(row["url"], "", table_id)
    parsed = up.urlsplit(url)
    print("  %s: mở %s?tableId=%s"
          % (label, parsed.path, (up.parse_qs(parsed.query).get("tableId") or [""])[0]),
          flush=True)
    navigate(port, url)
    state = wait_until(port, "state",
                       lambda value: bool(value.get("in_table"))
                       and str(value.get("table_id")) == str(table_id), timeout=60)
    return {"ok": bool(state.get("in_table")), "state": state}


def main(argv):
    table = "60101"
    ports = [9222, 9223]
    if "--table" in argv:
        table = str(argv[argv.index("--table") + 1])
    if "--ports" in argv:
        ports = []
        index = argv.index("--ports") + 1
        while index < len(argv) and not argv[index].startswith("--"):
            ports.append(int(argv[index]))
            index += 1
    labels = {port: "P%d" % (offset + 1) for offset, port in enumerate(ports)}
    print("bàn chung:", table, "| cổng:", ports, flush=True)

    print("\n== 1: về sảnh ==", flush=True)
    lobby_reports = {}
    for port in ports:
        lobby_reports[port] = to_lobby(port, labels[port])
        if not lobby_reports[port].get("ok"):
            print("  %s LỖI: %s" % (labels[port], lobby_reports[port].get("error")), flush=True)
    missing = [labels[port] for port, report in lobby_reports.items() if not report.get("ok")]
    if missing:
        print("\nDừng: %s chưa về được sảnh DG." % ", ".join(missing), flush=True)
        return 1

    # Bàn phải có ở MỌI sảnh, nếu không nhóm sẽ tách bàn dù đã "thành công".
    absent = [labels[port] for port, report in lobby_reports.items()
              if table not in (report.get("tables") or [])]
    if absent:
        print("\nDừng: bàn %s không có trên %s." % (table, ", ".join(absent)), flush=True)
        return 1

    print("\n== 2: vào bàn %s ==" % table, flush=True)
    entered = {}
    for port in ports:
        entered[port] = enter(port, labels[port], table)

    print("\n== 3: kiểm chứng ==", flush=True)
    rounds = {}
    for port in ports:
        bet = read(port, "bet")
        rounds[port] = str(bet.get("round_id") or "")
        print("  %s %s | bàn %s %s | ván %s | mở=%s | %s-%s"
              % (labels[port], (dg_row(port) or {}).get("url", "").split("/")[2],
                 bet.get("table_id"), bet.get("table_name"), bet.get("round_id"),
                 bet.get("bet_open"), bet.get("min_k"), bet.get("max_k")), flush=True)
    same_table = len({str(read(port, "bet").get("table_id")) for port in ports}) == 1
    same_round = len(set(rounds.values())) == 1 and all(rounds.values())
    print("\n  cùng bàn: %s | cùng mã ván: %s" % (same_table, same_round), flush=True)
    return 0 if same_table else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
