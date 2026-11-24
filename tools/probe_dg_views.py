# -*- coding: utf-8 -*-
"""Liet ke MOI node duoc coi la "view cuoc" tren tab DG, kem truong that.

Van de do duoc tren 888AE66 (``ddnewpc``): cung mot luc co nhieu node thoa dieu
kien ``betBtn + betHandler/tableInfoMan`` va chung mang du lieu khac nhau —
mot node la ban dang choi (RB01 / 202611240024R1046), node khac laai view phu
(QD07 / 2611244161928). Ham doc trang thai lay node dau tien nen co the bao sai
ma ban/ma van, lam ca nhom bi coi la lech van.

    python tools/probe_dg_views.py --port 9224
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

VIEWS_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  const views = [];
  const walk = (node, depth, path) => {
    if (!node || depth > 60) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) {
      const info = node.gameInfo || (node.tableInfoMan && node.tableInfoMan.gameInfo) || {};
      const player = node.playerInfo || {};
      const limit = node.baccaratLimit || {};
      let kids = 0;
      const count = (n, d) => { if (!n || d > 8) return;
        kids += (n.numChildren || 0);
        for (let i = 0; i < (n.numChildren || 0); i++) count(n.getChildAt(i), d + 1); };
      count(node, 0);
      views.push({
        path: path,
        cls: String((node.constructor && node.constructor.name) || '').slice(0, 30),
        name: String(node.name || ''),
        visible: node.visible !== false,
        depth: depth,
        kids: kids,
        tableId: node.tableId === undefined ? null : String(node.tableId),
        infoTableId: info.tableId === undefined ? null : String(info.tableId),
        gameNo: String(info.gameNo || ''),
        roundId: String(info.roundId || ''),
        tableName: String(info.tableName || ''),
        playerTableId: player.tableId === undefined ? null : String(player.tableId),
        min: Number(limit.bpMin || limit.min || 0),
        max: Number(limit.bpMax || limit.max || 0),
        hasHandler: typeof node.betHandler === 'function',
        hasBtnMan: !!node.betBtnMan,
        hasTableInfoMan: !!node.tableInfoMan,
      });
    }
    for (let i = 0; i < (node.numChildren || 0); i++) {
      walk(node.getChildAt(i), depth + 1, path + '.' + i);
    }
  };
  walk(Laya.stage, 0, 'stage');
  return {laya: true, count: views.length, views: views.slice(0, 20)};
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
                            "params": {"expression": VIEWS_JS, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        value = ((reply.get("result") or {}).get("result") or {}).get("value") or {}
    finally:
        ws.close()
    print("so view cuoc:", value.get("count"))
    for index, view in enumerate(value.get("views") or []):
        print("\n#%d %s" % (index, view["path"]))
        for key in ("cls", "name", "visible", "depth", "kids", "tableId", "infoTableId",
                    "tableName", "gameNo", "roundId", "playerTableId", "min", "max",
                    "hasHandler", "hasBtnMan", "hasTableInfoMan"):
            print("   %-16s %s" % (key, view.get(key)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
