# -*- coding: utf-8 -*-
"""Kiem chung cach GIU 1 TAB khi bam the DG tren 888AE66.

Gia thuyet: the DG mo Dream Gaming bang ``window.open`` nen Chrome co them tab.
Neu chan ``window.open`` (cho no ``location.assign``) thi tab site **thanh**
chinh tai lieu sanh DG -> dung 1 tab.

Do lai that: dem so tab truoc/sau. Chi in host/path (bo query).

    python tools/probe_888_inplace.py --port 9224 [--apply]
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

# Ghi de window.open: moi lan site mo cua so moi thi dieu huong tab hien tai.
IN_PLACE_JS = r"""
if (!window.__aibcrInPlace) {
  window.__aibcrInPlace = true;
  window.__aibcrOpen = window.open;
  window.open = function (url) {
    const target = typeof url === 'string' ? url.trim() : '';
    if (target && !/^about:blank$/i.test(target)) {
      try { window.location.assign(target); } catch (error) {}
      return null;
    }
    return window.__aibcrOpen ? window.__aibcrOpen.apply(window, arguments) : null;
  };
  // Mot so build gan target=_blank tren the <a>; chan luon duong do.
  document.addEventListener('click', (event) => {
    const link = event.target && event.target.closest ? event.target.closest('a[target=_blank]') : null;
    if (!link) return;
    const href = String(link.getAttribute('href') || '').trim();
    if (!href || href === '#' || href.startsWith('javascript')) return;
    try {
      event.preventDefault();
      window.location.assign(new URL(href, location.href).href);
    } catch (error) {}
  }, true);
}
return true;
"""

CLICK_DG_JS = r"""
(function () {
  const vis = (n) => {
    try { const r = n.getBoundingClientRect();
      return r.width > 8 && r.height > 8; } catch (e) { return false; }
  };
  const img = [...document.querySelectorAll('img')].filter(vis).find((node) =>
    /banner-dg/i.test(String(node.getAttribute('alt') || ''))
    || /banner-dg/i.test(String(node.getAttribute('src') || '')));
  if (!img) return {ok: false, reason: 'no-banner-dg', path: location.pathname};
  img.scrollIntoView({block: 'center', inline: 'center'});
  const rect = img.getBoundingClientRect();
  return {ok: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
    path: location.pathname, alt: String(img.getAttribute('alt') || ''),
    link: (() => { const a = img.closest('a'); return a
      ? {href: String(a.getAttribute('href') || ''), target: String(a.getAttribute('target') || '')}
      : null; })()};
})()
"""

STATE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  let kids = 0, inTable = false, captcha = false;
  const walk = (n, d) => {
    if (!n || d > 16) return;
    kids += (n.numChildren || 0);
    for (const key of ['text', '_text', 'label']) {
      try {
        const v = n[key];
        if (typeof v === 'string'
            && /xac minh|xác minh|keo thanh|kéo thanh|truot|trượt/i.test(v)) captcha = true;
      } catch (e) {}
    }
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) inTable = true;
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  return {laya: true, kids, in_table: inTable, captcha, path: location.pathname};
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
                                                "awaitPromise": True, "userGesture": True})
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:120]}
        return (result.get("result") or {}).get("value")

    def click(self, x, y):
        base = {"x": float(x), "y": float(y), "button": "left", "clickCount": 1}
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.call("Input.dispatchMouseEvent", dict(base, type=kind, buttons=buttons))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    apply_change = "--apply" in argv
    rows = pages(port)
    print("truoc: %d tab" % len(rows))
    for row in rows:
        print("  ", short(row.get("url")))
    # Tab DG cung chua ten site o tham so ``return=``; phai loai theo ``ddnew``.
    site = next((r for r in rows
                 if "888ae66" in (r.get("url") or "").lower()
                 and "ddnew" not in (r.get("url") or "").lower()), None)
    if not site:
        print("khong thay tab 888ae66")
        return 1
    conn = Conn(site)
    try:
        print("\ntab site:", short(site.get("url")))
        print("  inject in-place:", conn.eval(IN_PLACE_JS))
        box = conn.eval(CLICK_DG_JS) or {}
        print("  the DG:", json.dumps(box, ensure_ascii=False))
        if not box.get("ok"):
            return 1
        if not apply_change:
            print("\n(chay lai voi --apply de bam that)")
            return 0
        conn.click(box["x"], box["y"])
        print("\n  da bam the DG; theo doi")
        for step in range(40):
            time.sleep(1.5)
            now = pages(port)
            state = conn.eval(STATE_JS) or {}
            current = short(conn.eval("location.href") or "")
            print("  +%4.1fs %d tab | tab0=%s | laya=%s kids=%s captcha=%s in_table=%s"
                  % ((step + 1) * 1.5, len(now), current, state.get("laya"),
                     state.get("kids"), state.get("captcha"), state.get("in_table")))
            if len(now) > 1:
                print("   -> CO THEM TAB:", [short(r.get("url")) for r in now])
                return 2
            if state.get("laya") and (state.get("kids") or 0) > 5:
                print("   -> 1 TAB, DG da dung trong tab site")
                return 0
    finally:
        conn.close()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
