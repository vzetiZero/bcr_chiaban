# -*- coding: utf-8 -*-
"""Gỡ lỗi: in nguyên phản hồi CDP khi eval _DG_STATE_JS trên target DG."""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402


def main(argv):
    port = int(argv[0]) if argv else 9222
    rows = [row for row in targets(port) if "ddnew" in (row.get("url") or "").lower()]
    target = Target(rows[0])
    body = DG._DG_STATE_JS.strip()
    if body.startswith("return "):
        body = body[len("return "):]
    expression = "(function () {\n%s\n})()" % body
    print("== biểu thức ==", flush=True)
    print(expression[:400], flush=True)
    try:
        raw = target.call("Runtime.evaluate", {"expression": expression,
                                               "returnByValue": True,
                                               "awaitPromise": True})
        print("\n== phản hồi thô ==", flush=True)
        print(json.dumps(raw, ensure_ascii=False)[:2000], flush=True)
        print("\n== kiểu giá trị ==", flush=True)
        print(type((raw.get("result") or {}).get("value")), flush=True)
        print(json.dumps((raw.get("result") or {}).get("value"), ensure_ascii=False)[:1500],
              flush=True)
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
