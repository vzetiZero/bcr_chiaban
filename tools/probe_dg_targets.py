# -*- coding: utf-8 -*-
"""Đọc sảnh DG trên một cổng CDP, kể cả khi sảnh nằm trong iframe khác tiến trình.

Vì sao cần: đo trên cả GK881 và E3951 (bản điện thoại), sảnh DG là CDP target
``type: iframe`` với tài liệu thật ``ddnewwap/index.html``; ``Runtime.evaluate``
trên tab site **không** thấy Laya của sảnh. Phải nối thẳng vào websocket của
target DG thì mới đọc được danh sách bàn.

    python tools/probe_dg_targets.py --port 9222
"""

import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aibcr.adapters import febet as DG
from cdp_eval import Client

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


class Target:
    """Một target CDP bất kỳ (page hoặc iframe), eval được như tab."""

    def __init__(self, row):
        import websocket
        self.row = row
        self.ws = websocket.create_connection(row["webSocketDebuggerUrl"],
                                              suppress_origin=True, timeout=40)
        self.next_id = 0

    def call(self, method, params=None):
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method,
                                 "params": params or {}}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(str(reply["error"]))
                return reply.get("result") or {}

    def eval(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            return {"error": str(result["exceptionDetails"].get("text") or "")[:160]}
        return (result.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wrap(js):
    """Chuẩn hoá một blob JS kiểu ``execute_script`` thành biểu thức eval được.

    Các blob của adapter đều có dạng ``return <biểu thức>;`` — bỏ đúng chữ
    ``return`` là còn một biểu thức, nên trả về nguyên văn. Nếu bọc thêm
    ``(function(){ ... })()`` thì câu lệnh ``return`` bị bỏ lửng bên trong và
    ``Runtime.evaluate`` trả ``undefined`` (đã gặp khi đo: state/lobby = null
    trong khi Laya vẫn sống).
    """
    body = js.strip()
    if body.startswith("return "):
        return body[len("return "):]
    return "(function () {\n%s\n})()" % body


def read_lobby(port, timeout=45.0):
    """Chờ và đọc sảnh DG từ target DG; trả (target, state, tables)."""
    deadline = time.monotonic() + timeout
    last = (None, {}, [])
    while time.monotonic() < deadline:
        rows = [row for row in targets(port)
                if "ddnew" in (row.get("url") or "").lower()
                and row.get("webSocketDebuggerUrl")]
        for row in rows:
            target = Target(row)
            try:
                state = target.eval(wrap(DG._DG_STATE_JS)) or {}
                data = target.eval(wrap(DG._DG_LOBBY_JS)) or {}
                tables = (data.get("tables") or [])
                last = (row, state, tables)
                if tables or state.get("in_table"):
                    return last
            finally:
                target.close()
        time.sleep(2.0)
    return last


def main(argv):
    port = 9222
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    print("CDP", port)
    for row in targets(port):
        print("  ", row.get("type"), "|", (row.get("url") or "").split("?")[0], flush=True)
    row, state, tables = read_lobby(port)
    if not row:
        print("Không thấy target DG nào trên cổng này.")
        return 1
    print("\ntarget DG:", row.get("type"), "|", row.get("url").split("?")[0], flush=True)
    print("state:", json.dumps({key: state.get(key) for key in
                                ("ready", "in_table", "lobby", "label", "table_id",
                                 "table_name", "url_table", "table_cards")},
                               ensure_ascii=False), flush=True)
    print("sảnh: %d bàn" % len(tables), flush=True)
    for item in tables[:20]:
        print("  ", item.get("table_id"), "|", item.get("name"), "|", item.get("online"),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
