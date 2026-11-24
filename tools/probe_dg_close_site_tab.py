# -*- coding: utf-8 -*-
"""Kiem chung: giu tab sanh DG, dong tab site -> con dung 1 tab.

Do tren 888AE66: bam the DG lam Chrome co 2 tab
    [0] new-dd-cn.<dg-host>/ddnewpc/index.html?...   (sanh DG)
    [1] www.888ae66.com/gamelobby/live               (site game)
Yeu cau: dong tab site, chi con tab sanh.

Kiem tra sau khi dong: tab con lai van co Laya, van doc duoc ban/van dang choi
(khong bi day ve sanh, khong mat phien).

    python tools/probe_dg_close_site_tab.py --port 9224 [--apply]
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

STATE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  let kids = 0, inTable = false, viewTable = '', name = '', round = '';
  const walk = (n, d) => {
    if (!n || d > 16) return;
    kids += (n.numChildren || 0);
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) {
      inTable = true;
      const info = n.gameInfo || (n.tableInfoMan && n.tableInfoMan.gameInfo) || {};
      const fromView = [n.tableId, info.tableId,
        n.playerInfo && n.playerInfo.tableId,
        n.tableInfoMan && n.tableInfoMan.tableId]
        .map((v) => (v === undefined || v === null) ? '' : String(v).trim())
        .find((v) => /^60\d{3,}$/.test(v)) || '';
      if (fromView) viewTable = fromView;
      name = String(info.tableName || (n.tableInfoMan && n.tableInfoMan.tableName) || '');
      round = String(info.gameNo || info.roundId || '');
    }
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  return {laya: true, kids, in_table: inTable, table_id: viewTable,
    table_name: name, round_id: round, path: location.pathname,
    has_token: /[?&]token=/.test(location.search)};
})()
"""


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        return json.load(r)


def pages(port):
    return [row for row in targets(port)
            if row.get("type") == "page" and row.get("webSocketDebuggerUrl")
            and "devtools://" not in (row.get("url") or "")]


def short(url):
    try:
        parsed = urlsplit(url or "")
        return (parsed.hostname or "") + (parsed.path or "")
    except Exception:
        return "?"


def eval_on(row, js):
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=25)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": js, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        return ((reply.get("result") or {}).get("result") or {}).get("value")
    finally:
        ws.close()


def close_target(port, target_id):
    request = urllib.request.Request(
        "http://127.0.0.1:%d/json/close/%s" % (port, target_id))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200
    except Exception as exc:
        return "%s" % type(exc).__name__


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    apply_change = "--apply" in argv

    rows = pages(port)
    print("truoc: %d tab" % len(rows))
    for index, row in enumerate(rows):
        print("  [%d] %-46s | %s" % (index, short(row.get("url")),
                                     eval_on(row, "typeof Laya !== 'undefined' && !!Laya.stage")))

    dg = next((r for r in rows if "ddnew" in (r.get("url") or "").lower()), None)
    site = next((r for r in rows if "ddnew" not in (r.get("url") or "").lower()), None)
    if dg is None:
        print("khong co tab sanh DG")
        return 1
    print("\ntruoc khi dong, sanh DG:")
    before = eval_on(dg, STATE_JS) or {}
    print(" ", json.dumps(before, ensure_ascii=False))

    if site is None:
        print("\nchi co 1 tab: dung yeu cau")
        return 0
    print("\ntab site se dong:", short(site.get("url")), "| id", site.get("id"))
    if not apply_change:
        print("\n(chay lai voi --apply de dong that)")
        return 0

    closed = close_target(port, site.get("id"))
    print("\nda dong tab site:", closed)
    time.sleep(3)

    after = pages(port)
    print("sau: %d tab" % len(after))
    ok = len(after) == 1
    for index, row in enumerate(after):
        state = eval_on(row, STATE_JS) or {}
        print("  [%d] %-46s | %s" % (index, short(row.get("url")),
                                     json.dumps(state, ensure_ascii=False)))
        if not state.get("laya") or not (state.get("kids") or 0):
            ok = False
    print("\nket luan:", "CON DUNG 1 TAB, SANH DG VAN SONG" if ok else "CHUA DAT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
