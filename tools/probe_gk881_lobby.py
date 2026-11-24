# -*- coding: utf-8 -*-
"""Đưa Chrome GK881 (đang đăng nhập) vào sảnh DG bằng CDP thuần và đọc danh sách bàn.

Không dùng Selenium: chromedriver tắt là Chrome tắt theo, mà Chrome này còn phải
sống để profile E3951 ở cổng khác so bàn cùng lúc.

    python tools/probe_gk881_lobby.py [--port 9222]
"""

import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aibcr.adapters import gk881 as GK
from aibcr.adapters import febet as DG
from cdp_eval import Client

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")


def wrap(js, *args):
    """Bọc một đoạn JS kiểu ``execute_script`` thành biểu thức eval được."""
    body = js.strip()
    names = ", ".join("a%d" % index for index in range(len(args)))
    calls = ", ".join(json.dumps(arg) for arg in args)
    head = "(function (%s) {" % names if args else "(function () {"
    if body.startswith("const ") or body.startswith("return "):
        return "%s\n%s\n})(%s)" % (head, body, calls)
    # Đoạn bắt đầu bằng câu lệnh thường (vd `if (...) {...}`) vẫn hợp lệ trong hàm.
    return "%s\n%s\n})(%s)" % (head, body, calls)


def wait_for(client, expression, want, timeout=40.0, interval=1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.eval(expression)
        if want(last):
            return last
        time.sleep(interval)
    return last


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


def main(argv):
    port = 9222
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with Client(port) as client:
        print("tab:", (client.page.get("url") or "").split("?")[0], flush=True)

        state = client.eval(wrap(GK._MOBILE_STATE_JS))
        print("state:", json.dumps(state, ensure_ascii=False)[:400], flush=True)

        print("\n== bấm CASINO ==", flush=True)
        nav = client.eval(wrap(GK._MOBILE_CATEGORY_JS, "casino"))
        print(" ", json.dumps(nav, ensure_ascii=False)[:300], flush=True)
        time.sleep(4)

        print("\n== bấm thẻ DG ==", flush=True)
        card = wait_for(client, wrap(GK._MOBILE_DG_CARD_JS),
                        lambda value: isinstance(value, dict) and value.get("ok"),
                        timeout=30)
        print(" ", json.dumps(card, ensure_ascii=False)[:400], flush=True)

        print("\n== chờ sảnh DG (target list) ==", flush=True)
        deadline = time.monotonic() + 60
        found = None
        while time.monotonic() < deadline:
            for row in targets(port):
                url = (row.get("url") or "").lower()
                if "ddnew" in url:
                    found = row
                    break
            if found:
                break
            time.sleep(2)
        if not found:
            print("  chưa thấy target DG; các tab hiện có:", flush=True)
            for row in targets(port):
                print("   ", row.get("type"), "|", (row.get("url") or "").split("?")[0], flush=True)
            client.shot(str(OUT / "gk881_no_lobby.png"))
            return 1
        print("  target DG:", found.get("type"), "|", found.get("url").split("?")[0], flush=True)

        print("\n== chờ Laya của sảnh vẽ xong ==", flush=True)
        lobby = wait_for(client, wrap(DG._DG_LOBBY_JS),
                         lambda value: isinstance(value, dict) and value.get("lobby"),
                         timeout=60, interval=2)
        rows = (lobby or {}).get("tables") or []
        print("  sảnh: ok=%s, %d bàn" % (bool(rows), len(rows)), flush=True)
        for row in rows[:12]:
            print("   ", row.get("table_id"), "|", row.get("name"), "|",
                  row.get("online"), flush=True)
        client.shot(str(OUT / "gk881_lobby.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
