# -*- coding: utf-8 -*-
"""Đi từng bước trên 888AE66: SÒNG BÀI -> thẻ DG -> chờ target DG, in trạng thái.

Chỉ dùng CDP thuần. Không in token: chỉ host/path, tên tham số.

    python tools/probe_888ae66_step.py --port 9224 [--click-live] [--click-dg]
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from cdp_eval import Client  # noqa: E402

STATE_JS = r"""
(function () {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const vis = (node) => {
    try {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 8 && rect.height > 8 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity) > 0.05;
    } catch (error) { return false; }
  };
  const cls = (node) => String(node.getAttribute('class') || '').slice(0, 70);

  const liveNav = [...document.querySelectorAll('.nav-item.live, [class*=nav-item]')]
    .filter((node) => norm(node.textContent) === 'SÒNG BÀI');
  const dgCards = [...document.querySelectorAll(
      '[class*=game-item], [class*=provider], [class*=sub-live], li, div')]
    .filter((node) => {
      const alt = [...node.querySelectorAll('img')]
        .map((img) => String(img.getAttribute('alt') || '').toLowerCase());
      const src = [...node.querySelectorAll('img')]
        .map((img) => String(img.getAttribute('src') || '').toLowerCase());
      return alt.some((value) => /banner-dg|^dg$|dream/.test(value))
        || src.some((value) => /banner-dg/.test(value));
    })
    .filter(vis)
    .map((node) => {
      const rect = node.getBoundingClientRect();
      return { tag: node.tagName, cls: cls(node),
        text: norm(node.textContent).slice(0, 30),
        at: [Math.round(rect.x), Math.round(rect.y),
             Math.round(rect.width), Math.round(rect.height)] };
    });
  const liveCards = [...document.querySelectorAll('img')]
    .filter((img) => /banner-/.test(String(img.getAttribute('alt') || '').toLowerCase()))
    .filter(vis)
    .map((img) => String(img.getAttribute('alt')));
  const loginBtn = document.querySelector('button.header-btn.login');
  return {
    path: location.pathname, title: document.title,
    loggedIn: !loginBtn || !vis(loginBtn),
    liveNav: liveNav.map((node) => ({ cls: cls(node),
      at: (() => { const rect = node.getBoundingClientRect();
        return [Math.round(rect.x), Math.round(rect.y)]; })() })),
    dgCards: dgCards.slice(0, 6),
    liveCards: liveCards.slice(0, 24),
    canvas: document.querySelectorAll('canvas').length,
    bodyHead: norm(document.body ? document.body.innerText : '').slice(0, 160),
  };
})()
"""

CLICK_JS = r"""
(function (arg) {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const vis = (node) => {
    try {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 8 && rect.height > 8 && style.display !== 'none';
    } catch (error) { return false; }
  };
  let hit = null;
  if (arg.mode === 'live') {
    hit = [...document.querySelectorAll('.nav-item.live, [class*=nav-item]')]
      .find((node) => vis(node) && norm(node.textContent) === 'SÒNG BÀI') || null;
  } else {
    const cards = [...document.querySelectorAll(
        '[class*=game-item], [class*=provider], [class*=live-list], [class*=sub], li')]
      .filter(vis)
      .filter((node) => [...node.querySelectorAll('img')].some((img) =>
        /banner-dg/i.test(String(img.getAttribute('alt') || ''))
        || /banner-dg/i.test(String(img.getAttribute('src') || ''))));
    // Thẻ ngoài cùng chứa ảnh; chọn thẻ nhỏ nhất để bấm đúng ảnh.
    hit = cards.sort((a, b) => a.querySelectorAll('*').length
      - b.querySelectorAll('*').length)[0] || null;
  }
  if (!hit) return { ok: false };
  hit.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = hit.getBoundingClientRect();
  return { ok: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
    tag: hit.tagName, cls: String(hit.getAttribute('class') || '').slice(0, 60),
    text: norm(hit.textContent).slice(0, 30) };
})(%s)
"""


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


def list_dg(port):
    out = []
    for row in targets(port):
        url = row.get("url") or ""
        if "ddnew" in url.lower():
            out.append("%s | %s" % (row.get("type"), url.split("?")[0]))
    return out


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    before = set(list_dg(port))
    with Client(0, port) as client:
        print("tab:", (client.page.get("url") or "").split("?")[0], flush=True)
        print("state:", json.dumps(client.eval(STATE_JS), ensure_ascii=False)[:700], flush=True)

        if "--click-live" in argv:
            box = client.eval(CLICK_JS % json.dumps({"mode": "live"}))
            print("\nclick SÒNG BÀI:", json.dumps(box, ensure_ascii=False), flush=True)
            if box.get("ok"):
                client.click(box["x"], box["y"])
                time.sleep(4)
            print("tab sau:", (client.page.get("url") or "").split("?")[0], flush=True)
            print("state sau:", json.dumps(client.eval(STATE_JS), ensure_ascii=False)[:900],
                  flush=True)

        if "--click-dg" in argv:
            box = client.eval(CLICK_JS % json.dumps({"mode": "dg"}))
            print("\nclick thẻ DG:", json.dumps(box, ensure_ascii=False), flush=True)
            if box.get("ok"):
                client.click(box["x"], box["y"])
                for step in range(8):
                    time.sleep(3)
                    now = list_dg(port)
                    print("  +%2ds DG targets: %s | tab: %s"
                          % ((step + 1) * 3, now or "chưa có",
                             (client.page.get("url") or "").split("?")[0]), flush=True)
                    if now:
                        break
    print("\nDG targets (trước -> sau):", sorted(before), "->", list_dg(port), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
