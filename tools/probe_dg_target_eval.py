# -*- coding: utf-8 -*-
"""Kiểm tra nhanh: target DG có eval được không, Laya có sẵn không."""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from probe_dg_targets import Target, targets  # noqa: E402


def main(argv):
    port = int(argv[0]) if argv else 9222
    rows = [row for row in targets(port) if "ddnew" in (row.get("url") or "").lower()]
    if not rows:
        print("Không có target DG.")
        return 1
    target = Target(rows[0])
    try:
        for expression in (
            "1+1",
            "location.href.split('?')[0]",
            "typeof Laya",
            "document.readyState",
            "document.querySelectorAll('canvas').length",
            "typeof Laya !== 'undefined' && !!Laya.stage",
            "typeof Laya !== 'undefined' && Laya.stage ? (Laya.stage.numChildren||0) : -1",
        ):
            print(expression, "->", json.dumps(target.eval(expression), ensure_ascii=False),
                  flush=True)
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
