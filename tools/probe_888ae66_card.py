# -*- coding: utf-8 -*-
"""Soi DOM quanh the DG cua 888AE66 de biet phan tu nao that su bam duoc.

Chi doc DOM: khong bam, khong in token/cookie.

    python tools/probe_888ae66_card.py [--port 9224] [--url 888ae66]
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

JS = r"""
(function () {
  const norm = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const cls = (n) => String(n.getAttribute('class') || '');
  const desc = (n) => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return {
      tag: n.tagName, cls: cls(n).slice(0, 70),
      text: norm(n.textContent).slice(0, 26),
      kids: n.children.length,
      at: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      style: [s.display, s.visibility, s.opacity],
      click: [typeof n.onclick, n.getAttribute('onclick') ? 'attr' : '',
              n.tagName === 'A' ? String(n.getAttribute('href') || '') : ''],
    };
  };
  const imgs = [...document.querySelectorAll('img')].filter((img) =>
    /banner-dg/i.test(String(img.getAttribute('alt') || ''))
    || /banner-dg/i.test(String(img.getAttribute('src') || '')));
  const out = imgs.map((img) => {
    const chain = [];
    let node = img;
    for (let d = 0; d < 8 && node; d += 1) { chain.push(desc(node)); node = node.parentElement; }
    const r = img.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    return {
      img: desc(img),
      hitAtCenter: hit ? { tag: hit.tagName, cls: cls(hit).slice(0, 60),
        alt: String(hit.getAttribute ? (hit.getAttribute('alt') || '') : '') } : null,
      chain,
    };
  });
  // Moi the nha cung cap tren trang (de doi chieu ten lop that).
  const cards = [...document.querySelectorAll(
      '[class*=provider], [class*=vendor], [class*=game-item], [class*=live-list], [class*=sub] li')]
    .map((n) => ({ cls: cls(n).slice(0, 60), text: norm(n.textContent).slice(0, 30),
      imgs: [...n.querySelectorAll('img')].map((i) => String(i.getAttribute('alt') || '')).slice(0, 3) }))
    .slice(0, 25);
  return { count: imgs.length, path: location.pathname, out, cards };
})()
"""


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        return json.load(r)


def pick(port, mark):
    """Tab site, khong phai tab DG (URL DG cung co the chua ten site o ``return=``)."""
    for row in targets(port):
        url = (row.get("url") or "").lower()
        if row.get("type") != "page" or not row.get("webSocketDebuggerUrl"):
            continue
        if "ddnew" in url:
            continue
        if mark in url:
            return row
    return None


def main(argv):
    port = 9224
    mark = "888ae66"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--url" in argv:
        mark = argv[argv.index("--url") + 1]
    row = pick(port, mark)
    if not row:
        print("khong thay tab", mark)
        return 1
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=30)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": JS, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        value = ((reply.get("result") or {}).get("result") or {}).get("value") or {}
    finally:
        ws.close()
    print("path:", value.get("path"), "| the DG:", value.get("count"))
    for index, item in enumerate(value.get("out") or []):
        print("\n=== img #%d %s" % (index, item["img"]["at"]))
        print("   hit center:", item["hitAtCenter"])
        for depth, node in enumerate(item["chain"]):
            print("   %d %-6s %-36s %s kids=%-3s %s click=%s"
                  % (depth, node["tag"], node["cls"], node["at"], node["kids"],
                     node["style"], node["click"]))
    print("\n=== the nha cung cap ===")
    for card in value.get("cards") or []:
        print(" ", card)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
