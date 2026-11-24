# -*- coding: utf-8 -*-
"""Lấy mã ván + giới hạn của nhiều cổng CDP cùng lúc để so tính đồng bộ.

    python tools/probe_round_compare.py 9222 9223 --rounds 5
"""

import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402

KEEP = ("table_id", "table_name", "round_id", "state_id", "countdown", "bet_open",
        "min_k", "max_k", "balance_k", "balance_known", "denominations_k")


def read(port):
    rows = [row for row in targets(port) if "ddnew" in (row.get("url") or "").lower()]
    if not rows:
        return {"port": port, "ok": False, "error": "no-dg-target"}
    target = Target(rows[0])
    try:
        value = target.eval(wrap(DG._DG_BET_STATE_JS)) or {}
        slim = {key: value.get(key) for key in KEEP}
        slim.update(port=port, host=(rows[0].get("url") or "").split("/")[2])
        return slim
    finally:
        target.close()


def main(argv):
    ports = []
    rounds = 4
    rest = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--rounds":
            rounds = int(argv[index + 1])
            index += 2
            continue
        ports.append(int(item))
        index += 1
    if len(ports) < 2:
        print("cần ít nhất 2 cổng")
        return 1
    seen = {}
    for step in range(rounds):
        rows = [read(port) for port in ports]
        ids = [str(row.get("round_id")) for row in rows]
        same = len(set(ids)) == 1 and all(ids)
        print("\n[%d] cùng ván: %s | %s" % (step + 1, same, " / ".join(ids)), flush=True)
        for row in rows:
            print("   %s %s | bàn %s %s | cửa mở=%s | %s-%s | chip=%s"
                  % (row.get("port"), row.get("host"), row.get("table_id"),
                     row.get("table_name"), row.get("bet_open"), row.get("min_k"),
                     row.get("max_k"), ",".join(str(x) for x in
                                                (row.get("denominations_k") or [])[:8])),
                  flush=True)
        seen[ids[0] if same else "|".join(ids)] = True
        if step + 1 < rounds:
            time.sleep(12)
    print("\nván đã thấy:", list(seen))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
