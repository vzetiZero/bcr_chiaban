# -*- coding: utf-8 -*-
"""Kiem tra ``direct1.html`` co ton tai tren host DG cua 888AE66 khong.

Khong dieu huong tab: chi ``fetch`` HEAD/GET tu trong trang DG va bao status +
xem co canvas Laya trong HTML tra ve hay khong. Nho vay khong lam mat phien
dang choi va khong phai giai captcha lai.

    python tools/probe_888_loader.py --port 9224
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

FETCH_JS = r"""
(async () => {
  const base = location.pathname.replace(/[^/]*$/, '');
  const query = location.search.replace(/([?&])tableId=[^&]*/g, '$1').replace(/[?&]$/, '');
  const out = [];
  for (const name of ['direct1.html', 'index.html']) {
    const url = base + name + query;
    try {
      const response = await fetch(url, {credentials: 'include'});
      const text = await response.text();
      out.push({
        file: name,
        status: response.status,
        ok: response.ok,
        bytes: text.length,
        hasLaya: /laya/i.test(text),
        hasCanvas: /<canvas/i.test(text),
        title: (text.match(/<title>([^<]*)<\/title>/i) || [])[1] || '',
      });
    } catch (error) {
      out.push({file: name, status: 0, ok: false, error: String(error).slice(0, 60)});
    }
  }
  return {path: location.pathname, host: location.hostname, out};
})()
"""


def main(argv):
    import urllib.request
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        rows = json.load(r)
    row = next((x for x in rows
                if "ddnew" in (x.get("url") or "").lower() and x.get("webSocketDebuggerUrl")), None)
    if not row:
        print("khong co tab DG")
        return 1
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=40)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": FETCH_JS, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        value = ((reply.get("result") or {}).get("result") or {}).get("value") or {}
    finally:
        ws.close()
    print("host:", value.get("host"), "|", value.get("path"))
    for item in value.get("out") or []:
        print(" ", json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
