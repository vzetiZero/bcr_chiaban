# -*- coding: utf-8 -*-
"""Kết nối Chrome đang mở (CDP 9222), click icon DG trên trang sảnh,
lấy URL iframe của sảnh DG rồi điều hướng trực tiếp tới URL đó.

Dùng khi Chrome đã mở ở trang sảnh của nhà cái (E3951, GK881, FEBET, VNWTop...)
nhưng chưa bấm vào icon DG. Script sẽ:
  1. Gắn CDP vào Chrome đang chạy ở port 9222.
  2. Liệt kê các tab, tìm tab chứa trang sảnh (chưa phải DG).
  3. Thử click các phần tử có tên DG / DreamGaming / CHƠI NGAY.
  4. Đợi iframe DG (ddnewpc) xuất hiện, đọc location.href của nó.
  5. Điều hướng tab cao nhất trực tiếp tới URL iframe đó.
"""

import json
import sys
import time
import urllib.request
from urllib.parse import urlsplit

CDP_PORT = 9222
CDP_BASE = "http://127.0.0.1:%d" % CDP_PORT


def cdp_get(resource, timeout=3):
    with urllib.request.urlopen("%s/json/%s" % (CDP_BASE, resource), timeout=timeout) as r:
        return json.load(r)


def cdp_ws(endpoint):
    import websocket
    return websocket.create_connection(endpoint, suppress_origin=True, timeout=8)


def cdp_cmd(ws, req_id, method, params):
    ws.send(json.dumps({"id": req_id, "method": method, "params": params}))
    deadline = time.monotonic() + 8
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("cdp_timeout")
        ws.settimeout(remaining)
        msg = json.loads(ws.recv())
        if msg.get("id") != req_id:
            continue
        if "error" in msg:
            raise RuntimeError("cdp_error: %s" % msg["error"])
        return msg.get("result", {})


def list_pages():
    targets = cdp_get("list")
    pages = []
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url") or ""
        ws_url = t.get("webSocketDebuggerUrl") or ""
        pages.append({"id": t.get("id"), "url": url, "title": t.get("title", ""), "ws": ws_url})
    return pages


def find_dg_iframe_url(driver_cdp_ws, timeout=20.0):
    """Quét các frame trong tab hiện tại, trả URL iframe chứa 'ddnewpc' nếu tìm thấy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Lấy cây frame từ DOM của trang cao nhất
            res = cdp_cmd(driver_cdp_ws, 1, "Runtime.evaluate", {
                "expression": """
                (() => {
                  const frames = [];
                  const walk = (win, depth) => {
                    if (depth > 6) return;
                    try {
                      const frs = win.frames || [];
                      for (let i = 0; i < frs.length; i++) {
                        try {
                          const f = frs[i];
                          const loc = f.location.href || '';
                          frames.push({index: i, url: loc, depth: depth});
                          walk(f, depth + 1);
                        } catch (e) {}
                      }
                    } catch (e) {}
                  };
                  walk(window, 0);
                  return frames;
                })()
                """,
                "returnByValue": True,
            })
            frames = (res or {}).get("result", {}).get("value") or []
            for f in frames:
                url = f.get("url") or ""
                if "ddnewpc" in url.lower():
                    return url
        except Exception:
            pass
        time.sleep(0.5)
    return None


def click_dg_icon(driver_cdp_ws, timeout=30.0):
    """Thử click các phần tử liên quan đến DG trên trang cao nhất."""
    deadline = time.monotonic() + timeout
    js = """
    (() => {
      const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const dgKeywords = ['dg', 'dream gaming', 'dreamgaming', 'dg trực tuyến', 'dg truc tuyen',
                          'chơi ngay', 'choi ngay', 'play now', 'xem game'];
      const candidates = [];
      const push = (node) => {
        if (!node || !node.offsetParent && node.style.display !== 'none') return;
        const text = norm(node.textContent || node.value || '');
        const tag = (node.tagName || '').toLowerCase();
        const cls = node.className || '';
        const id = node.id || '';
        const score = dgKeywords.reduce((s, k) => s + (norm(text).includes(k) ? 1 : 0)
                                        + (norm(cls).includes(k) ? 1 : 0)
                                        + (norm(id).includes(k) ? 1 : 0), 0);
        if (score > 0) {
          candidates.push({node: node, score: score, text: text.slice(0, 40), tag: tag});
        }
      };
      document.querySelectorAll('button, a, div, li, span, img, [role="button"]').forEach(push);
      candidates.sort((a, b) => b.score - a.score);
      if (candidates.length === 0) return {ok: false, reason: 'no-dg-elements'};
      const best = candidates[0].node;
      best.scrollIntoView({block: 'center', inline: 'center'});
      try { best.click(); return {ok: true, clicked: best.tagName, text: norm(best.textContent || best.value || '').slice(0, 40)}; }
      catch (e) { return {ok: false, reason: 'click_failed: ' + String(e)}; }
    })()
    """
    while time.monotonic() < deadline:
        try:
            res = cdp_cmd(driver_cdp_ws, 1, "Runtime.evaluate", {
                "expression": js,
                "returnByValue": True,
            })
            val = (res or {}).get("result", {}).get("value")
            if val and val.get("ok"):
                return True, val
            if val and val.get("reason") == "no-dg-elements":
                return False, val
        except Exception:
            pass
        time.sleep(0.5)
    return False, {"reason": "timeout"}


def main():
    print("Ket noi CDP tai %s..." % CDP_BASE)
    try:
        pages = list_pages()
    except Exception as exc:
        print("LOI: Khong the ket noi CDP %s (%s). Chrome co chay voi --remote-debugging-port=9222 khong?"
              % (CDP_BASE, exc))
        return 1

    if not pages:
        print("Khong tim thay tab trang web nao trong CDP.")
        return 1

    print("Tim thay %d tab:" % len(pages))
    for p in pages:
        print("  id=%s title=%r url=%s" % (p["id"], p["title"], p["url"]))

    # Chon tab dang o trang site (khong phai DDG lobby)
    target = None
    for p in pages:
        u = (p["url"] or "").lower()
        if "ddnewpc" in u:
            print("Tab id=%s da la sảnh DG (ddnewpc), bo qua." % p["id"])
            continue
        if p["url"] and p["url"].startswith("http"):
            target = p
            break

    if target is None:
        print("Khong tim thay tab trang site de click DG.")
        return 1

    print("\nDang chon tab id=%s (%s)..." % (target["id"], target["url"]))
    ws = cdp_ws(target["ws"])

    # B1: Click icon DG
    print("Dang tim va click icon DG...")
    ok, info = click_dg_icon(ws)
    print("Ket qua click: ok=%s info=%s" % (ok, info))
    if not ok:
        print("Khong click duoc icon DG. Hay ban tu bấm vao icon DG, sau khi sảnh DG hien thi thi chay lai script.")
        ws.close()
        return 1

    # Doi iframe DG xuat hien
    print("Doi iframe DG (ddnewpc) xuat hien...")
    iframe_url = find_dg_iframe_url(ws, timeout=30.0)
    ws.close()

    if not iframe_url:
        print("Khong tim thay iframe DG trong 30 giay. Hay kiem tra lai.")
        return 1

    print("\nTim thay iframe DG: %s" % iframe_url)

    # B2: Dieu huong tab cao nhất toi URL iframe DG
    print("\nDang dieu huong tab chinh toi URL iframe DG...")
    try:
        pages2 = list_pages()
    except Exception as exc:
        print("LOI khong lay lai danh sach tab: %s" % exc)
        return 1

    target2 = None
    for p in pages2:
        if p["id"] == target["id"]:
            target2 = p
            break

    if target2 is None:
        print("Khong tim thay tab id=%s sau khi click." % target["id"])
        return 1

    ws2 = cdp_ws(target2["ws"])
    parsed = urlsplit(iframe_url)
    nav_url = "%s://%s%s" % (parsed.scheme, parsed.hostname, parsed.path)
    if parsed.query:
        nav_url += "?" + parsed.query

    try:
        cdp_cmd(ws2, 1, "Page.navigate", {"url": nav_url})
        print("Da yeu cau Chrome mo: %s" % nav_url)
        print("(Token/session duoc giu nguyen trong URL iframe, khong ghi log.)")
    except Exception as exc:
        print("LOI dieu huong: %s" % exc)
        ws2.close()
        return 1

    ws2.close()
    print("\nHoan tat. Chrome hien dang o sảnh DG (URL iframe), khong lai lien quan den trang site goc.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
