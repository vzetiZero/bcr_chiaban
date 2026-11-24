# -*- coding: utf-8 -*-
"""Đọc/ghi nhanh một tab Chrome đang mở qua CDP, không làm tắt Chrome.

Vì sao phải có file này: khi gắn Selenium/chromedriver vào Chrome ngoài, tiến
trình chromedriver tắt là Chrome bị đóng theo. Muốn dò DOM/Laya nhiều lần mà
không mất phiên đăng nhập thì chỉ được nói chuyện bằng websocket CDP thuần.

Dùng:

    python tools/cdp_eval.py                 # liệt kê tab
    python tools/cdp_eval.py "1+1"           # eval biểu thức
    python tools/cdp_eval.py --tab 0 --file js.txt
    python tools/cdp_eval.py --shot a.png
"""

import json
import pathlib
import sys
import urllib.request

PORT = 9222


def _targets(port=None):
    port = PORT if port is None else int(port)
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


def _page(index=0, port=None):
    pages = [row for row in _targets(port)
             if row.get("type") == "page" and row.get("webSocketDebuggerUrl")
             and "devtools://" not in (row.get("url") or "")]
    if not pages:
        raise SystemExit("Không có tab page nào để đọc.")
    return pages[max(0, min(index, len(pages) - 1))]


class Client:
    def __init__(self, index=0, port=None):
        import websocket
        self.port = PORT if port is None else int(port)
        self.page = _page(index, self.port)
        self.ws = websocket.create_connection(self.page["webSocketDebuggerUrl"],
                                              suppress_origin=True, timeout=30)
        self.next_id = 0

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, method, params=None):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(str(reply["error"]))
                return reply.get("result") or {}

    def eval(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": True, "userGesture": True})
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:200],
                    "detail": str((result["exceptionDetails"].get("exception") or {})
                                  .get("description") or "")[:200]}
        return (result.get("result") or {}).get("value")

    def click(self, x, y):
        base = {"x": float(x), "y": float(y), "button": "left", "clickCount": 1}
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.call("Input.dispatchMouseEvent", dict(base, type=kind, buttons=buttons))
        return True

    def shot(self, path):
        data = self.call("Page.captureScreenshot", {"format": "png"}).get("data") or ""
        import base64
        pathlib.Path(path).write_bytes(base64.b64decode(data))
        return path

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def main(argv):
    index = 0
    expression = ""
    target = ""
    while argv:
        item = argv.pop(0)
        if item == "--tab":
            index = int(argv.pop(0))
        elif item == "--file":
            target = argv.pop(0)
        elif item == "--shot":
            with Client(index) as client:
                print(client.shot(argv.pop(0)))
            return 0
        else:
            expression = item
    if target:
        expression = pathlib.Path(target).read_text(encoding="utf-8")
    with Client(index) as client:
        if not expression:
            print("tab:", client.page["url"].split("?")[0])
            for row in _targets():
                print(" ", row.get("type"), "|", (row.get("url") or "").split("?")[0])
            return 0
        print(json.dumps(client.eval(expression), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
