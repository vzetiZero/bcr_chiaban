# -*- coding: utf-8 -*-
"""Doc cac truong that cua view cuoc DG de lay dung ma ban / ma van / gioi han.

Ly do: tren tab 888AE66 (``ddnewpc``), ``_DG_BET_STATE_JS`` doc ra
``table_name = "QD07"`` va ``round_id = "2611244161928"`` trong khi man hinh ghi
"Ban 58 RB01" va GK881/E3951 cung ban lai tra ``round_id`` dang
``202611240023R1033``. Phai biet truong nao la that truoc khi dung no de ghep
nhom, neu khong ``groupBettingTick`` se bao lech van mai mai.

    python tools/probe_dg_fields.py --port 9224
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

FIELDS_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  const safe = (value) => {
    if (value === undefined || value === null) return null;
    const kind = typeof value;
    if (kind === 'string') return value.length > 60 ? value.slice(0, 60) + '…' : value;
    if (kind === 'number' || kind === 'boolean') return value;
    if (kind === 'function') return '[fn]';
    return '[' + kind + ']';
  };
  const dump = (obj, depth) => {
    if (!obj || typeof obj !== 'object' || depth > 2) return null;
    const out = {};
    let count = 0;
    for (const key of Object.keys(obj)) {
      if (count++ > 45) break;
      if (/token|session|cookie|password|auth/i.test(key)) continue;
      out[key] = safe(obj[key]);
    }
    return out;
  };
  let view = null;
  const walk = (node, depth) => {
    if (!node || depth > 60 || view) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) { view = node; return; }
    for (const child of (node._children || [])) walk(child, depth + 1);
  };
  walk(Laya.stage, 0);
  if (!view) return {laya: true, view: false};
  const info = view.gameInfo || (view.tableInfoMan && view.tableInfoMan.gameInfo) || {};
  const player = view.playerInfo || window.playerInfo || {};
  const limit = view.baccaratLimit || {};
  return {
    laya: true, view: true,
    tableId: safe(view.tableId),
    gameInfo: dump(info, 0),
    tableInfoMan: dump(view.tableInfoMan, 0),
    playerInfo: dump(player, 0),
    baccaratLimit: dump(limit, 0),
    windowGameInfo: dump(window.gameInfo, 0),
    windowPlayerInfo: dump(window.playerInfo, 0),
    windowTableId: safe(window.tableId),
    videoManTableId: safe(view.videoMan && view.videoMan.tableId),
    betBtnMan: dump(view.betBtnMan, 0),
    hasBetHandler: typeof view.betHandler === 'function',
  };
})()
"""


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        rows = json.load(r)
    row = next((x for x in rows if x.get("type") == "page"
                and "ddnew" in (x.get("url") or "").lower()
                and x.get("webSocketDebuggerUrl")), None)
    if not row:
        print("khong co tab DG")
        return 1
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=30)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": FIELDS_JS, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        value = ((reply.get("result") or {}).get("result") or {}).get("value") or {}
    finally:
        ws.close()
    print(json.dumps(value, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
