# -*- coding: utf-8 -*-
"""Chay chinh ``_DG_STATE_JS`` / ``_DG_BET_STATE_JS`` cua adapter tren tab DG.

Dung de kiem chung ban sua "chon view cuoc theo diem" ma khong phai mo lai trinh
duyet: script nap hai blob JS **tu file nguon** roi eval qua CDP thuan.

    python tools/probe_js_state.py --port 9224
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import websocket  # noqa: E402

from aibcr.adapters import febet as F  # noqa: E402


def dg_row(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        rows = json.load(r)
    return next((x for x in rows if x.get("type") == "page"
                 and "ddnew" in (x.get("url") or "").lower()
                 and x.get("webSocketDebuggerUrl")), None)


def evaluate(ws, expression):
    # Hai blob trong adapter bat dau bang ``return (...)()`` (chung duoc chay qua
    # ``execute_script``), nen phai boc trong mot ham truoc khi eval.
    wrapped = "(function(){ %s })()" % expression
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": wrapped, "returnByValue": True,
                                   "awaitPromise": True}}))
    while True:
        reply = json.loads(ws.recv())
        if reply.get("id") == 1:
            if reply.get("result", {}).get("exceptionDetails"):
                detail = reply["result"]["exceptionDetails"]
                description = ((detail.get("exception") or {}).get("description") or "")
                return {"error": str(detail.get("text") or "")[:120],
                        "detail": str(description)[:300]}
            return ((reply.get("result") or {}).get("result") or {}).get("value")


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    row = dg_row(port)
    if not row:
        print("khong co tab DG")
        return 1
    ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=30)
    try:
        for label, blob in (("_DG_STATE_JS", F._DG_STATE_JS),
                            ("_DG_BET_STATE_JS", F._DG_BET_STATE_JS)):
            value = evaluate(ws, blob)
            print("\n== %s" % label)
            print(json.dumps(value, ensure_ascii=False, indent=1))
    finally:
        ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
