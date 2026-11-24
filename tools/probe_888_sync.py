# -*- coding: utf-8 -*-
"""Kiem chung vao ban tren tab DG cua 888AE66 (``ddnewpc``) bang CDP thuan.

Lan do truoc bi captcha chan giua luc dang tai nen ket qua "khong vao ban" chua
ket luan duoc. Probe nay:

1. doc trang thai + phat hien captcha "Xac minh an toan";
2. dieu huong toi loader ``direct1.html?tableId=<id>`` (cung URL ma
   ``febet.sync_table`` dung cho ban desktop);
3. cho toi khi ``in_table`` va ``table_id`` khop;
4. bao ro dang bi captcha (khong tu giai).

    python tools/probe_888_sync.py --port 9224 --table 60101 [--show]
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402
from urllib.parse import urlsplit, parse_qs, urlencode, urlunsplit  # noqa: E402

STATE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready: false};
  let inTable = false, viewTable = '', name = '', round = '', cards = 0, lobby = false;
  let captcha = false, captchaText = '';
  const walk = (n, d) => {
    if (!n || d > 16) return;
    const nodeName = String(n.name || '');
    if (nodeName === 'enterMC' || nodeName === 'tableMC' || nodeName === 'roadMC') lobby = true;
    if (n.tableId !== undefined && n.tableId !== null && String(n.tableId) !== '') cards++;
    for (const key of ['text', '_text', 'label', '_label']) {
      try {
        const v = n[key];
        if (typeof v === 'string' && /xac minh|xác minh|keo thanh|kéo thanh|truot|trượt/i
            .test(v.toLowerCase())) { captcha = true; captchaText = v.trim().slice(0, 40); }
      } catch (e) {}
    }
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) {
      inTable = true;
      const info = n.gameInfo || (n.tableInfoMan && n.tableInfoMan.gameInfo) || {};
      const found = [n.tableId, info.tableId, n.playerInfo && n.playerInfo.tableId,
        n.tableInfoMan && n.tableInfoMan.tableId]
        .map((v) => (v === undefined || v === null) ? '' : String(v).trim())
        .find((v) => /^60\d{3,}$/.test(v)) || '';
      if (found) viewTable = found;
      name = String(info.tableName || (n.tableInfoMan && n.tableInfoMan.tableName) || '');
      round = String(info.gameNo || info.roundId || '');
    }
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  const urlTable = (location.href.match(/tableId=([0-9]+)/) || [])[1] || '';
  return {ready: true, in_table: inTable, lobby: lobby || cards > 0,
    table_id: viewTable || urlTable, view_table: viewTable, url_table: urlTable,
    table_name: name, round_id: round, table_cards: cards,
    captcha: captcha, captcha_text: captchaText, path: location.pathname};
})()
"""


def dg_row(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        rows = json.load(r)
    return next((x for x in rows if x.get("type") == "page"
                 and "ddnew" in (x.get("url") or "").lower()
                 and x.get("webSocketDebuggerUrl")), None)


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

    def eval(self, js):
        result = self.call("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                                "awaitPromise": True})
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:120]}
        return (result.get("result") or {}).get("value")

    def shot(self, path):
        import base64
        import pathlib
        data = self.call("Page.captureScreenshot", {"format": "png"}).get("data") or ""
        pathlib.Path(path).write_bytes(base64.b64decode(data))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def loader_url(location, table_id):
    parsed = urlsplit(location)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tableId"] = [table_id]
    base = parsed.path.rsplit("/", 1)[0]
    if "ddnewwap" in (location or "").lower():
        path = base + "/index.html"
    else:
        path = base + "/direct1.html"
    return urlunsplit((parsed.scheme, parsed.netloc, path,
                       urlencode(query, doseq=True), ""))


def main(argv):
    port = 9224
    table = "60101"
    show = "--show" in argv
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--table" in argv:
        table = argv[argv.index("--table") + 1]
    row = dg_row(port)
    if not row:
        print("khong co tab DG")
        return 1
    conn = Conn(row)
    try:
        here = conn.eval("location.href") or ""
        print("truoc:", json.dumps(conn.eval(STATE_JS), ensure_ascii=False))
        target = loader_url(here, table)
        print("dieu huong toi loader tableId=%s (%s)" % (table, urlsplit(target).path))
        conn.eval("location.href = %s" % json.dumps(target))
        landed = {}
        captcha_seen = False
        for step in range(45):
            time.sleep(1.0)
            landed = conn.eval(STATE_JS) or {}
            if landed.get("captcha") and not captcha_seen:
                captcha_seen = True
                print("  +%2ds CAN CAPTCHA: %r -> cho nguoi dung tu thao tac"
                      % (step + 1, landed.get("captcha_text")))
                if show:
                    conn.shot(str(__import__("pathlib").Path.home()
                                  / "AppData/Local/Temp/opencode/dg888_captcha.png"))
            if landed.get("in_table") and str(landed.get("table_id")) == table:
                print("  +%2ds VAO BAN: %s" % (step + 1, json.dumps(landed, ensure_ascii=False)))
                return 0
            if step % 5 == 4:
                print("  +%2ds %s" % (step + 1, json.dumps(landed, ensure_ascii=False)))
        print("khong xac nhan duoc ban", table, "| cuoi:", json.dumps(landed, ensure_ascii=False))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
