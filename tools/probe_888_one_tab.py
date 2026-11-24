# -*- coding: utf-8 -*-
"""Do ky thuat "1 tab": dua URL sanh DG sang tab site (tab 0) roi dong tab DG.

Van de do duoc tren 888AE66: bam the DG mo Dream Gaming thanh **tab rieng**
(``ddnewpc/index.html``) nen Chrome co 2 tab (site + DG). Yeu cau: tab 0 phai
chay chinh tai lieu sanh DG, tab DG dong lai -> con dung 1 tab.

Chi in host/path (bo query) vi URL mang token phien.

    python tools/probe_888_one_tab.py --port 9224 [--apply]
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
  let kids = 0;
  const walk = (n, d) => { if (!n || d > 14) return;
    kids += (n.numChildren || 0);
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1); };
  walk(Laya.stage, 0);
  let inTable = false;
  const scan = (n, d) => { if (!n || d > 14 || inTable) return;
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) { inTable = true; return; }
    for (let i = 0; i < (n.numChildren || 0); i++) scan(n.getChildAt(i), d + 1); };
  scan(Laya.stage, 0);
  return {laya: true, stage: [Laya.stage.width, Laya.stage.height],
    kids: kids, in_table: inTable, path: location.pathname,
    title: String(document.title || '')};
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


class Conn:
    def __init__(self, row):
        self.row = row
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

    def eval(self, js):
        result = self.call("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                                "awaitPromise": True})
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:120]}
        return (result.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def close_target(port, target_id):
    request = urllib.request.Request("http://127.0.0.1:%d/json/close/%s" % (port, target_id))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    apply_change = "--apply" in argv
    rows = pages(port)
    print("truoc: %d tab" % len(rows))
    for row in rows:
        print("  ", short(row.get("url")))

    dg = next((r for r in rows if "ddnew" in (r.get("url") or "").lower()), None)
    site = next((r for r in rows if "ddnew" not in (r.get("url") or "").lower()), None)
    if not dg or not site:
        print("thieu tab DG hoac tab site")
        return 1
    lobby_url = dg.get("url") or ""
    print("\ntab DG:", short(lobby_url), "| id", dg.get("id"))
    print("tab site:", short(site.get("url")), "| id", site.get("id"))

    if not apply_change:
        print("\n(chay lai voi --apply de thuc hien)")
        return 0

    # Tab 0 = tab site. No phai chay chinh tai lieu sanh DG.
    conn = Conn(site)
    try:
        conn.call("Page.navigate", {"url": lobby_url})
        print("\nda gui Page.navigate tren websocket cua tab site")
        landed = {}
        for step in range(45):
            time.sleep(1.0)
            landed = conn.eval(STATE_JS) or {}
            current = conn.eval("location.href") or ""
            if "ddnew" in current.lower() and landed.get("laya") and landed.get("kids"):
                print("  +%2ds tab 0 = %s | laya=%s kids=%s in_table=%s"
                      % (step + 1, short(current), landed.get("laya"),
                         landed.get("kids"), landed.get("in_table")))
                break
            if step % 5 == 4:
                print("  +%2ds dang tai: %s | laya=%s"
                      % (step + 1, short(current), landed.get("laya")))
    finally:
        conn.close()

    closed = close_target(port, dg.get("id"))
    time.sleep(2)
    after = pages(port)
    print("\ndong tab DG:", closed, "| sau: %d tab" % len(after))
    for row in after:
        print("  ", short(row.get("url")))
    for row in after:
        check = Conn(row)
        try:
            print("   state:", json.dumps(check.eval(STATE_JS), ensure_ascii=False))
        finally:
            check.close()
    return 0 if len(after) == 1 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
