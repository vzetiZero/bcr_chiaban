# -*- coding: utf-8 -*-
"""Mở một tab mới trên Chrome đang chạy (CDP), không tắt Chrome.

    python tools/cdp_new_tab.py 9222 "https://e39d5d05qc.e3951.com/m/home"
"""

import json
import sys
import urllib.request


def main(argv):
    port = int(argv[0]) if argv else 9222
    url = argv[1] if len(argv) > 1 else "about:blank"
    with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=5) as response:
        browser_ws = json.load(response).get("webSocketDebuggerUrl") or ""
    if not browser_ws:
        print("Không lấy được webSocketDebuggerUrl.")
        return 1
    import websocket
    ws = websocket.create_connection(browser_ws, suppress_origin=True, timeout=15)
    try:
        ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                            "params": {"url": url}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                if "error" in reply:
                    print("Lỗi:", reply["error"])
                    return 1
                print("tab:", (reply.get("result") or {}).get("targetId"))
                return 0
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
