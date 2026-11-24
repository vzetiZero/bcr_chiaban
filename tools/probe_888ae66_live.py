# -*- coding: utf-8 -*-
"""Mo tab 888AE66 /m tren Chrome profile 1 (CDP 9222) va do hinh dang trang."""
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, r"C:\Users\Administrator\Desktop\bcr_chiaban")
from tools.cdp_eval import Client, _targets  # noqa: E402

PORT = 9222
URL = "https://www.888ae66.com/m"

# 1. Tab hien co
print("== tabs truoc")
for row in _targets(PORT):
    if row.get("type") == "page":
        print("  ", (row.get("url") or "")[:100])

# 2. Mo tab moi qua HTTP /json/new
req = urllib.request.Request("http://127.0.0.1:%d/json/new?%s" % (PORT, urllib.parse.quote(URL, safe="")),
                             method="PUT")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        created = json.load(r)
    print("created", created.get("id"), (created.get("url") or "")[:80])
except Exception as exc:
    print("create failed", exc)
    sys.exit(1)

time.sleep(12)
pages = [row for row in _targets(PORT) if row.get("type") == "page"]
index = next((i for i, row in enumerate(pages) if row.get("id") == created.get("id")), 0)
print("== tab index", index)

JS = r"""
(() => {
const vis = (n) => { try { const r = n.getBoundingClientRect(); const s = getComputedStyle(n);
  return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none'; } catch(e) { return false; } };
const norm = (v) => String(v || '').replace(/\s+/g, ' ').trim();
const dg = [...document.querySelectorAll('img')].filter(i => /banner-dg/i.test(i.getAttribute('alt') || ''));
const navs = [...document.querySelectorAll('[class*=nav], [class*=home-quick]')].filter(vis)
  .map(n => ({cls: n.className, txt: norm(n.textContent).slice(0, 30),
              r: n.getBoundingClientRect().toJSON()}))
  .filter(n => /s[oò]ng\s*b[aà]i|casino|live/i.test(n.txt)).slice(0, 8);
const overlays = [...document.querySelectorAll('[class*=modal],[class*=popup],[class*=dialog],[class*=mask],[class*=overlay]')]
  .filter(vis).slice(0, 10).map(n => ({cls: String(n.className).slice(0, 80),
    r: n.getBoundingClientRect().toJSON()}));
return {
  url: location.href.split('?')[0],
  path: location.pathname,
  title: document.title,
  w: innerWidth, h: innerHeight, dpr: devicePixelRatio,
  loginBtn: !!document.querySelector('.header-btn.login, button.header-btn.login'),
  dgCount: dg.length,
  dg: dg.slice(0, 3).map(i => ({alt: i.getAttribute('alt'),
      r: i.getBoundingClientRect().toJSON(), src: (i.getAttribute('src') || '').slice(0, 60)})),
  navs, overlays,
  textSample: norm(document.body.innerText).slice(0, 300),
};
})()
"""

with Client(index, PORT) as client:
    print(json.dumps(client.eval(JS), ensure_ascii=False, indent=1))
    client.shot(r"C:\Users\Administrator\AppData\Local\Temp\opencode\ae888_home.png")
