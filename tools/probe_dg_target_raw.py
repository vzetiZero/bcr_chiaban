# -*- coding: utf-8 -*-
"""In NGUYÊN VĂN kết quả _DG_STATE_JS / _DG_LOBBY_JS trên target DG."""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402
from aibcr.adapters import febet as DG  # noqa: E402

DIAG = """
const out = {laya: typeof Laya, stage: null, children: 0, names: []};
if (typeof Laya !== 'undefined' && Laya.stage) {
  out.stage = [Math.round(Laya.stage.width || 0), Math.round(Laya.stage.height || 0)];
  out.children = Laya.stage.numChildren || 0;
  const walk = (node, depth) => {
    if (!node || depth > 6 || out.names.length >= 40) return;
    const name = String(node.name || '');
    if (name) out.names.push(depth + ':' + name);
    for (let i = 0; i < (node.numChildren || 0); i++) walk(node.getChildAt(i), depth + 1);
  };
  walk(Laya.stage, 0);
}
return out;
"""


def main(argv):
    port = int(argv[0]) if argv else 9222
    rows = [row for row in targets(port) if "ddnew" in (row.get("url") or "").lower()]
    if not rows:
        print("Không có target DG.")
        return 1
    target = Target(rows[0])
    try:
        for name, code in (("diag", DIAG), ("state", DG._DG_STATE_JS),
                           ("lobby", DG._DG_LOBBY_JS)):
            value = target.eval(wrap(code))
            print("\n==", name, "==")
            print(json.dumps(value, ensure_ascii=False)[:2000], flush=True)
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
