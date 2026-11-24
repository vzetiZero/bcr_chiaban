# -*- coding: utf-8 -*-
"""Đưa tab E3951 (đã đăng nhập) vào sảnh DG bằng CDP thuần, trên Chrome đang mở.

Chọn đúng tab E3951 theo hostname, bấm bằng chuột thật (Input.dispatchMouseEvent)
để site xử lý như người dùng, rồi chờ target DG mới xuất hiện.

    python tools/probe_e3951_open.py 9222
"""

import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aibcr.adapters import e3951 as E
from cdp_eval import Client

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")


def list_targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


def dg_hosts(port):
    return {(row.get("url") or "").split("/")[2]
            for row in list_targets(port) if "ddnew" in (row.get("url") or "").lower()}


def find_site_client(port, host_part):
    """Client cho tab page có hostname chứa ``host_part``."""
    rows = list_targets(port)
    for index, row in enumerate([r for r in rows if r.get("type") == "page"
                                 and "devtools://" not in (r.get("url") or "")]):
        if host_part in (row.get("url") or "").lower():
            return Client(index, port)
    return None


def tap(client, selector_js):
    """Chạy JS tìm phần tử và bấm chuột thật vào tâm phần tử."""
    box = client.eval(r"""
(function () {
  const node = %s;
  if (!node) return {ok: false};
  node.scrollIntoView({block: 'center', inline: 'center'});
  const rect = node.getBoundingClientRect();
  if (!rect.width || !rect.height) return {ok: false, reason: 'zero-size'};
  return {ok: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
          text: String(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30)};
})()
""" % selector_js)
    if not isinstance(box, dict) or not box.get("ok"):
        return box
    client.click(box["x"], box["y"])
    time.sleep(1.0)
    return box


def main(argv):
    port = int(argv[0]) if argv else 9222
    before = dg_hosts(port)
    print("DG hosts trước:", sorted(before), flush=True)

    client = find_site_client(port, "e3951.com")
    if client is None:
        print("Không thấy tab e3951.com trên cổng", port)
        return 1
    try:
        print("tab:", (client.page.get("url") or "").split("?")[0], flush=True)

        print("\n== bấm Casino ==", flush=True)
        print(" ", json.dumps(tap(client, "[...document.querySelectorAll('.game-menu-item')]"
                                        ".find((n) => /casino/i.test(n.textContent || ''))"),
                              ensure_ascii=False), flush=True)
        time.sleep(3)

        live = client.eval("(function(){return (function(){%s})();})()"
                           % E._LIVE_STATE_JS.strip().replace("return ", "", 1))
        print("  live:", json.dumps(live, ensure_ascii=False)[:400], flush=True)

        print("\n== bấm thẻ DG ==", flush=True)
        dg = tap(client, "[...document.querySelectorAll('.vendor-game-item,.vendor-box')]"
                         ".find((b) => [...b.querySelectorAll('img')].some((i) =>"
                         " /DG-(?:DEFAULT|ACTIVE)\\./i.test(i.getAttribute('src') || '')"
                         " || /-DG_\\d+\\./i.test(i.getAttribute('src') || '')))")
        print(" ", json.dumps(dg, ensure_ascii=False), flush=True)
        time.sleep(3)

        print("\n== bấm Chơi ngay trong popup ==", flush=True)
        play = tap(client, "[...document.querySelectorAll('.chooser-btn')]"
                           ".find((n) => /chơi ngay|choi ngay/i.test(n.textContent || ''))")
        print(" ", json.dumps(play, ensure_ascii=False), flush=True)

        print("\n== chờ target DG mới ==", flush=True)
        deadline = time.monotonic() + 60
        fresh = None
        while time.monotonic() < deadline:
            now = dg_hosts(port)
            added = now - before
            if added:
                fresh = sorted(added)
                break
            time.sleep(2)
        print("  DG hosts sau:", sorted(dg_hosts(port)), "| mới:", fresh, flush=True)
        client.shot(str(OUT / "e3951_after_play.png"))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
