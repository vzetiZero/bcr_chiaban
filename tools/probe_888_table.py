# -*- coding: utf-8 -*-
"""Do cach vao ban DG tren tab 888AE66 (``ddnewpc`` mo tu site dien thoai).

Cau hoi can tra loi truoc khi viet adapter:

1. Tab DG cua 888AE66 la ``ddnewpc/index.html``. Vao ban bang
   ``index.html?tableId=60101`` duoc khong?
2. Neu khong, ``direct1.html?tableId=...`` (loader desktop) co ton tai khong?

Khong in token: chi in host/path da bo query va ma ban doc duoc.

    python tools/probe_888_table.py --port 9224 [--try index|direct1|both]
"""

import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402
from urllib.parse import urlsplit, parse_qs, urlencode, urlunsplit  # noqa: E402

STATE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready: false};
  let inTable = false, viewTable = '', cards = 0, lobby = false;
  const walk = (n, d) => {
    if (!n || d > 12) return;
    const name = String(n.name || '');
    if (name === 'enterMC' || name === 'tableMC' || name === 'roadMC') lobby = true;
    if (n.tableId !== undefined && n.tableId !== null && String(n.tableId) !== '') cards++;
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) {
      inTable = true;
      const fromView = [n.tableId, n.gameInfo && n.gameInfo.tableId,
        n.playerInfo && n.playerInfo.tableId,
        n.tableInfoMan && n.tableInfoMan.tableId]
        .map((v) => (v === undefined || v === null) ? '' : String(v).trim())
        .find((v) => /^60\d{3,}$/.test(v)) || '';
      if (fromView) viewTable = fromView;
    }
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  const urlTable = (location.href.match(/tableId=([0-9]+)/) || [])[1] || '';
  return {ready: true, in_table: inTable, lobby: lobby || cards > 0,
    table_id: viewTable || urlTable, url_table: urlTable, table_cards: cards,
    path: location.pathname, has_token: /[?&]token=/.test(location.search)};
})()
"""


def targets(port):
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        return json.load(r)


class Conn:
    def __init__(self, row):
        self.ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                             suppress_origin=True, timeout=30)
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.n:
                return reply.get("result") or {}

    def eval(self, js, args=None):
        params = {"expression": js, "returnByValue": True, "awaitPromise": True}
        if args is not None:
            params["expression"] = "(function(){%s})()" % js if False else js
        result = self.call("Runtime.evaluate", params)
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:200]}
        return (result.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def loader_url(location, table_id, mode):
    parsed = urlsplit(location)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tableId"] = [table_id]
    base = parsed.path.rsplit("/", 1)[0]
    path = base + ("/index.html" if mode == "index" else "/direct1.html")
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), ""))


def main(argv):
    port = 9224
    mode = "both"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--try" in argv:
        mode = argv[argv.index("--try") + 1]
    rows = [r for r in targets(port)
            if "ddnew" in (r.get("url") or "").lower() and r.get("webSocketDebuggerUrl")]
    if not rows:
        print("khong co tab DG o cong", port)
        return 1
    row = rows[0]
    conn = Conn(row)
    try:
        print("truoc:", json.dumps(conn.eval(STATE_JS), ensure_ascii=False))
        location = conn.eval("location.href")
        tries = ["index", "direct1"] if mode == "both" else [mode]
        for attempt in tries:
            for table in ("60101", "60102"):
                url = loader_url(location, table, attempt)
                print("\n-- %s.html?tableId=%s" % (attempt, table))
                conn.eval("location.href = %s" % json.dumps(url))
                landed = {}
                for step in range(30):
                    time.sleep(1.0)
                    landed = conn.eval(STATE_JS) or {}
                    if landed.get("in_table") and str(landed.get("table_id")) == table:
                        break
                print("   sau %2ds: %s" % (step + 1, json.dumps(landed, ensure_ascii=False)))
                if landed.get("in_table") and str(landed.get("table_id")) == table:
                    print("   => OK voi", attempt)
                    return 0
    finally:
        conn.close()
    print("\nkhong vao duoc bang ca hai duong")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
