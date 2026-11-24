# -*- coding: utf-8 -*-
"""Đóng Chrome của app ở một cổng CDP, đúng cách (Browser.close), rồi chờ cổng tắt.

Chỉ đóng Chrome **do app mở** (có --remote-debugging-port). Không quét/kill tiến
trình Chrome khác của người dùng: nếu cổng đóng thì không làm gì cả.

    python tools/close_profile_chrome.py 9222
"""

import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def port_open(port, timeout=0.6):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port,
                                    timeout=timeout) as response:
            json.load(response)
        return True
    except Exception:
        return False


def main(argv):
    port = int(argv[0]) if argv else 9222
    if not port_open(port):
        print("CDP %d dang dong — khong co gi de dong." % port)
        return 0
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
            pages = json.load(response)
    except Exception as exc:
        print("Khong doc duoc /json/list:", exc)
        return 1
    browser_ws = ""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=5) as response:
            browser_ws = str(json.load(response).get("webSocketDebuggerUrl") or "")
    except Exception:
        browser_ws = ""
    if not browser_ws:
        print("Khong co webSocketDebuggerUrl; bo qua.")
        return 1
    import websocket
    try:
        ws = websocket.create_connection(browser_ws, suppress_origin=True, timeout=8)
        ws.send(json.dumps({"id": 1, "method": "Browser.close", "params": {}}))
        ws.close()
    except Exception as exc:
        print("Gui Browser.close loi:", exc)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not port_open(port, timeout=0.4):
            print("CDP %d da dong (%d tab truoc do)." % (port, len(pages)))
            return 0
        time.sleep(0.5)
    print("CDP %d van mo sau 15s." % port)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
