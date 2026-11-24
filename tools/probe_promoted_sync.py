# -*- coding: utf-8 -*-
"""Trên tab ĐÃ tách sang sảnh DG, đổi bàn bằng loader ``?tableId=`` và đọc mã ván.

Đây là đường ``sync_table`` dùng khi ``mode == "tab"``: ``_loader_url`` giữ nguyên
``index.html`` của bản điện thoại, giữ token, chỉ thêm ``tableId``.

    python tools/probe_promoted_sync.py --port 9223 --table 60103
"""

import json
import sys
import time
import urllib.parse as up

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402


def page_row(port):
    rows = [row for row in targets(port)
            if row.get("type") == "page" and "devtools://" not in (row.get("url") or "")]
    for row in rows:
        if "ddnew" in (row.get("url") or "").lower():
            return row
    return None


def go(port, url):
    import websocket
    row = page_row(port)
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=40)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                return reply.get("result") or {}
    finally:
        ws.close()


def main(argv):
    port = 9223
    table = "60103"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--table" in argv:
        table = str(argv[argv.index("--table") + 1])

    row = page_row(port)
    if not row:
        print("Tab chính chưa phải sảnh DG; chạy probe_promote_top.py trước.")
        return 1
    location = row["url"]
    print("tab chính:", location.split("?")[0], flush=True)
    print("tham số:", sorted(up.parse_qs(up.urlsplit(location).query).keys()), flush=True)

    new_url = DG._loader_url(location, "", table)
    parsed = up.urlsplit(new_url)
    print("\nURL loader (không in token):", parsed.path, flush=True)
    print("  tham số:", sorted(up.parse_qs(parsed.query).keys()), flush=True)
    print("  tableId:", (up.parse_qs(parsed.query).get("tableId") or [""])[0], flush=True)

    print("\n== điều hướng ==", flush=True)
    print(" ", go(port, new_url), flush=True)

    deadline = time.monotonic() + 40
    state = {}
    bet = {}
    while time.monotonic() < deadline:
        time.sleep(1.5)
        current = page_row(port)
        target = Target(current)
        try:
            state = target.eval(wrap(DG._DG_STATE_JS)) or {}
            bet = target.eval(wrap(DG._DG_BET_STATE_JS)) or {}
        finally:
            target.close()
        print("  in_table=%s table_id=%s round=%s"
              % (state.get("in_table"), state.get("table_id"), bet.get("round_id")),
              flush=True)
        if state.get("in_table"):
            break

    print("\nstate:", json.dumps({key: state.get(key) for key in
                                  ("ready", "in_table", "label", "table_id",
                                   "table_name", "url_table", "table_cards")},
                                 ensure_ascii=False), flush=True)
    keep = ("table_id", "table_name", "round_id", "state_id", "countdown", "bet_open",
            "min_k", "max_k", "balance_k", "balance_known")
    print("bet:", json.dumps({key: bet.get(key) for key in keep}, ensure_ascii=False),
          flush=True)
    return 0 if state.get("in_table") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
