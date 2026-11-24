# -*- coding: utf-8 -*-
"""Chay hai doan JS doc trang thai DG that (khong sua gi) tren tab dang mo."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cdp_eval import Client
from aibcr.adapters import febet as DG

KEEP = ("ready", "in_table", "lobby", "label", "table_id", "table_name", "url_table",
        "table_cards", "round_id", "state_id", "countdown", "bet_open", "scale",
        "min_k", "max_k", "balance_k", "balance_known", "denominations_k", "pending",
        "confirmed")


def main():
    with Client() as client:
        print("tab:", (client.page.get("url") or "").split("?")[0], flush=True)
        for name, code in (("state", DG._DG_STATE_JS), ("bet", DG._DG_BET_STATE_JS)):
            raw = client.eval("(function () {%s})()" % code.strip())
            if not isinstance(raw, dict):
                print(name, "->", raw, flush=True)
                continue
            slim = {key: raw.get(key) for key in KEEP if key in raw}
            print(name, "->", json.dumps(slim, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
