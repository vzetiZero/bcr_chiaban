# -*- coding: utf-8 -*-
"""Xem nhanh trang dang mo: co dang nhap chua, co link vao casino khong.

    python tools/probe_page_overview.py 9222
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from cdp_eval import Client  # noqa: E402

JS = r"""
(function () {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const vis = (node) => {
    try {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none'
        && style.visibility !== 'hidden';
    } catch (error) { return false; }
  };
  const keywords = /(casino|sòng bài|song bai|live|baccarat|game|đăng nhập|dang nhap|nạp|nap|số dư|so du)/i;
  const items = [];
  const seen = new Set();
  for (const node of document.querySelectorAll('a,button,div,span')) {
    const text = norm(node.textContent || '');
    if (!text || text.length > 30) continue;
    if (!keywords.test(text)) continue;
    if (!vis(node)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 12 || rect.height < 8) continue;
    const key = text + '|' + Math.round(rect.x) + '|' + Math.round(rect.y);
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({ text, tag: node.tagName,
      cls: String(node.getAttribute('class') || '').slice(0, 50),
      href: String(node.getAttribute && (node.getAttribute('href') || '') || '').slice(0, 60),
      at: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)] });
    if (items.length >= 30) break;
  }
  return { host: location.hostname, path: location.pathname,
           title: document.title, items,
           bodyHead: norm(document.body ? document.body.innerText : '').slice(0, 300) };
})()
"""


def main(argv):
    port = int(argv[0]) if argv else 9222
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        targets = json.load(response)
    pages = [row for row in targets
             if row.get("type") == "page" and "devtools://" not in (row.get("url") or "")]
    if not pages:
        print("Khong co tab page.")
        return 1
    import websocket
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=25)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": JS, "returnByValue": True, "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                value = ((reply.get("result") or {}).get("result") or {}).get("value")
                print(json.dumps(value, ensure_ascii=False, indent=1))
                break
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
