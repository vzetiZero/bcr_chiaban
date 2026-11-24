# -*- coding: utf-8 -*-
"""Doc nhanh mot tab theo host: URL/khung/iframe/Laya, khong in query (token).

    python tools/probe_tab_info.py --port 9224 --host k8bnn2ct
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

JS = r"""
(function () {
  const vis = (n) => {
    try { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
    catch (e) { return false; }
  };
  return {
    host: location.hostname, path: location.pathname,
    title: String(document.title || ''),
    laya: typeof Laya,
    stage: (typeof Laya !== 'undefined' && Laya.stage)
      ? [Laya.stage.width, Laya.stage.height, Laya.stage.numChildren || 0] : null,
    canvas: document.querySelectorAll('canvas').length,
    iframes: [...document.querySelectorAll('iframe,frame')].map((f) => {
      let host = '';
      try { host = new URL(f.getAttribute('src') || '', location.href).hostname; } catch (e) {}
      return {host: host, vis: vis(f),
        size: (() => { const r = f.getBoundingClientRect();
          return [Math.round(r.width), Math.round(r.height)]; })()};
    }),
    nav: [...document.querySelectorAll('a,button')].filter(vis)
      .map((n) => String(n.textContent || '').replace(/\s+/g, ' ').trim())
      .filter((t) => t && t.length < 26).slice(0, 25),
    text: String(document.body ? document.body.innerText : '')
      .replace(/\s+/g, ' ').trim().slice(0, 220),
  };
})()
"""


def main(argv):
    port = 9224
    host = ""
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--host" in argv:
        host = argv[argv.index("--host") + 1].lower()
    elif "--target" in argv:
        host = argv[argv.index("--target") + 1].lower()
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        rows = json.load(r)
    for row in rows:
        if row.get("type") != "page" or not row.get("webSocketDebuggerUrl"):
            continue
        if host and host not in (row.get("url") or "").lower():
            continue
        ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                         suppress_origin=True, timeout=25)
        try:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                "params": {"expression": JS, "returnByValue": True,
                                           "awaitPromise": True}}))
            while True:
                reply = json.loads(ws.recv())
                if reply.get("id") == 1:
                    break
            value = ((reply.get("result") or {}).get("result") or {}).get("value")
        finally:
            ws.close()
        print(json.dumps(value, ensure_ascii=False, indent=1))
        return 0
    print("khong thay tab", host)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
