# -*- coding: utf-8 -*-
"""Kiểm chứng: ``Page.getFrameTree`` có liệt kê URL THẬT của iframe khác tiến trình.

Nếu có, đây là cách xác nhận "frame DG này thuộc trang này" đáng tin hơn so sánh
host của ``<iframe src>`` (thuộc tính src có thể nói dối, và site có thể lồng frame
nhiều tầng).

    python tools/probe_frame_tree.py --port 9223
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))


def page_row(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        rows = json.load(response)
    for row in rows:
        if row.get("type") == "page" and "devtools://" not in (row.get("url") or ""):
            return row
    return None


def walk(node, depth=0, out=None):
    out = [] if out is None else out
    frame = node.get("frame") or {}
    url = str(frame.get("url") or "")
    if url and not url.startswith("about:"):
        out.append({"depth": depth,
                    "host": url.split("/")[2] if "//" in url else "",
                    "path": url.split("?")[0]})
    for child in node.get("childFrames") or []:
        walk(child, depth + 1, out)
    return out


def main(argv):
    port = 9223
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    row = page_row(port)
    if not row:
        print("không có tab page")
        return 1
    import websocket
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=20)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.getFrameTree"}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                tree = (reply.get("result") or {}).get("frameTree") or {}
                print("tab:", (row.get("url") or "").split("?")[0])
                print(json.dumps(walk(tree), ensure_ascii=False, indent=1))
                break
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
