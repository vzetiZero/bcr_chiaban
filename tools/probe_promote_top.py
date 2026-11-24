# -*- coding: utf-8 -*-
"""Đưa tab site sang CHÍNH URL sảnh DG trong iframe (không để lại ``/m/home``).

Đo trên E3951: sảnh DG là target ``type: iframe`` tại
``new-dd-cn.dingdangmail.com/ddnewwap/index.html?token=…``. Script này điều hướng
tab của site tới đúng URL đó rồi kiểm tra Laya của sảnh có sống ở tab chính
không, và có đọc được danh sách bàn không.

Không in token: chỉ in host/path và tên tham số.

    python tools/probe_promote_top.py --port 9223 [--restore]
"""

import json
import sys
import time
import urllib.parse as up
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402


def dg_row(port):
    rows = [row for row in targets(port)
            if "ddnew" in (row.get("url") or "").lower() and row.get("webSocketDebuggerUrl")]
    return rows[0] if rows else None


def site_row(port):
    rows = [row for row in targets(port)
            if row.get("type") == "page" and "devtools://" not in (row.get("url") or "")]
    return rows[0] if rows else None


def navigate(port, url):
    """Điều hướng tab page đầu tiên qua CDP (không dùng Selenium).

    ``Page.navigate`` phải gửi trên websocket của **chính tab** đó; gửi qua
    websocket cấp browser thì lệnh bị bỏ qua và trang vẫn nguyên ``/m/home``
    (đã đo: phản hồi ``{}`` nhưng URL không đổi).
    """
    import websocket
    row = site_row(port)
    if not row or not row.get("webSocketDebuggerUrl"):
        return {"error": "no-page-target"}
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=40)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                if "error" in reply:
                    return {"error": reply["error"]}
                return reply.get("result") or {}
    finally:
        ws.close()


def read_top(port, timeout=45.0):
    """Đọc state/lobby từ trang ở tab chính (không phải target iframe)."""
    deadline = time.monotonic() + timeout
    last = ({}, {})
    while time.monotonic() < deadline:
        row = site_row(port)
        if not row:
            time.sleep(1.0)
            continue
        target = Target(row)
        try:
            state = target.eval(wrap(DG._DG_STATE_JS)) or {}
            lobby = target.eval(wrap(DG._DG_LOBBY_JS)) or {}
            last = (state, lobby)
            if (lobby.get("tables") or state.get("in_table")):
                return last
        finally:
            target.close()
        time.sleep(2.0)
    return last


def main(argv):
    port = 9223
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    row = dg_row(port)
    if not row:
        print("Không có target DG nào ở cổng", port)
        return 1
    url = row["url"]
    parsed = up.urlsplit(url)
    print("target DG:", parsed.hostname, parsed.path, flush=True)
    print("tham số:", sorted(up.parse_qs(parsed.query).keys()), flush=True)
    print("tab site trước:",
          (site_row(port).get("url") or "").split("?")[0], flush=True)

    print("\n== điều hướng tab chính tới URL sảnh ==", flush=True)
    print(" ", navigate(port, url), flush=True)
    time.sleep(5)

    state, lobby = read_top(port)
    tables = lobby.get("tables") or []
    print("\ntab chính sau:", (site_row(port).get("url") or "").split("?")[0], flush=True)
    print("state:", json.dumps({key: state.get(key) for key in
                                ("ready", "in_table", "lobby", "label", "table_id",
                                 "table_name", "url_table", "table_cards")},
                               ensure_ascii=False), flush=True)
    print("sảnh: %d bàn" % len(tables), flush=True)
    for item in tables[:10]:
        print("  ", item.get("table_id"), "|", item.get("name"), "|", item.get("online"),
              flush=True)
    return 0 if tables else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
