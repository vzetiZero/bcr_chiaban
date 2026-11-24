# -*- coding: utf-8 -*-
"""Liệt kê tab + trạng thái đăng nhập sơ bộ của Chrome ở một cổng CDP.

    python tools/probe_two_sites.py 9222
    python tools/probe_two_sites.py 9223
"""

import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cdp_eval import Client  # noqa: E402

LOGIN_JS = r"""
(function () {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const vis = (node) => {
    try {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
        && style.display !== 'none' && Number(style.opacity) > 0.05;
    } catch (error) { return false; }
  };
  const loginWords = /^(đăng nhập|dang nhap|login|log in|đăng ký|dang ky)$/i;
  const hits = [];
  for (const node of document.querySelectorAll('a,button,div,span,input')) {
    const text = norm(node.textContent || node.value || '');
    if (!text || text.length > 24 || !loginWords.test(text)) continue;
    if (!vis(node)) continue;
    const rect = node.getBoundingClientRect();
    hits.push({ text, tag: node.tagName,
      cls: String(node.getAttribute('class') || '').slice(0, 60),
      rect: [Math.round(rect.x), Math.round(rect.y)] });
  }
  const body = norm(document.body ? document.body.innerText : '').slice(0, 200);
  return { host: location.hostname, path: location.pathname,
           hasLoginButton: hits.length > 0, hits: hits.slice(0, 6), body };
})()
"""


def main(argv):
    port = int(argv[0]) if argv else 9222
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        targets = json.load(response)
    print("CDP %d" % port, flush=True)
    for row in targets:
        if row.get("type") != "page":
            continue
        print("  page |", (row.get("url") or "").split("?")[0], flush=True)
    pages = [row for row in targets if row.get("type") == "page" and row.get("webSocketDebuggerUrl")]
    if not pages:
        print("  (khong co tab page)")
        return 1
    import websocket
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=25)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": LOGIN_JS, "returnByValue": True, "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                value = ((reply.get("result") or {}).get("result") or {}).get("value")
                print(" ", json.dumps(value, ensure_ascii=False, indent=1)[:1200], flush=True)
                break
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
