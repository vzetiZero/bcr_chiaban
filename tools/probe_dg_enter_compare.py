# -*- coding: utf-8 -*-
"""Vào một bàn DG trên target DG (iframe) bằng chuột thật, rồi đọc mã ván.

Dùng cho việc so hai sảnh: nếu hai profile cùng vào bàn 60101 thì ``round_id`` phải
trùng. Toàn bộ đi qua CDP thuần để Chrome không bị tắt.

    python tools/probe_dg_enter_compare.py --port 9222 --table 60101
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from aibcr.adapters import febet as DG
from probe_dg_targets import Target, targets, wrap

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")


def card_box_js(table_id):
    """``_LAYA_CARD_BOX_JS`` với mã bàn nhúng thẳng (CDP không truyền arguments)."""
    js = DG._LAYA_CARD_BOX_JS
    return js.replace("const wanted = String(arguments[0] || '');",
                      "const wanted = %s;" % json.dumps(str(table_id)))


def dg_target(port):
    rows = [row for row in targets(port)
            if "ddnew" in (row.get("url") or "").lower() and row.get("webSocketDebuggerUrl")]
    return rows[0] if rows else None


def click(target, x, y):
    base = {"x": float(x), "y": float(y), "button": "left", "clickCount": 1}
    target.call("Input.dispatchMouseEvent", dict(base, type="mouseMoved", buttons=0))
    target.call("Input.dispatchMouseEvent", dict(base, type="mousePressed", buttons=1))
    time.sleep(0.06)
    target.call("Input.dispatchMouseEvent", dict(base, type="mouseReleased", buttons=0))


def enter(port, table_id, wait=25.0):
    row = dg_target(port)
    if not row:
        return {"ok": False, "error": "no-dg-target"}
    target = Target(row)
    try:
        state = target.eval(wrap(DG._DG_STATE_JS)) or {}
        if state.get("in_table"):
            return {"ok": True, "already": True, "host": row["url"].split("/")[2],
                    "table_id": state.get("table_id"), "state": state}
        box = target.eval(wrap(card_box_js(table_id)))
        if not isinstance(box, dict) or not box.get("ok"):
            return {"ok": False, "error": "no-card", "box": box}
        click(target, box["x"], box["y"])
        deadline = time.monotonic() + wait
        last = {}
        while time.monotonic() < deadline:
            time.sleep(1.0)
            last = target.eval(wrap(DG._DG_STATE_JS)) or {}
            if last.get("in_table"):
                break
        bet = target.eval(wrap(DG._DG_BET_STATE_JS)) or {}
        return {"ok": True, "host": row["url"].split("/")[2], "clicked": box,
                "in_table": bool(last.get("in_table")),
                "table_id": bet.get("table_id") or last.get("table_id"),
                "table_name": bet.get("table_name") or last.get("table_name"),
                "round_id": bet.get("round_id"), "state_id": bet.get("state_id"),
                "countdown": bet.get("countdown"), "bet_open": bet.get("bet_open"),
                "balance_k": bet.get("balance_k"), "min_k": bet.get("min_k"),
                "max_k": bet.get("max_k")}
    finally:
        target.close()


def main(argv):
    port = 9222
    table = "60101"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--table" in argv:
        table = str(argv[argv.index("--table") + 1])
    result = enter(port, table)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok") and result.get("in_table") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
