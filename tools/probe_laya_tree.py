# -*- coding: utf-8 -*-
"""Xem Laya stage của sảnh DG bản desktop (ddnewpc) đang dựng gì.

Dùng khi ``_DG_STATE_JS`` báo ``ready`` mà ``lobby=false`` và ``table_cards=0``:
cần biết cây node thật để nhận diện sảnh/ bàn.

    python tools/probe_laya_tree.py --port 9224
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from probe_dg_targets import Target, targets  # noqa: E402

TREE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return { laya: false };
  const out = [];
  const walk = (node, depth) => {
    if (!node || depth > 5 || out.length >= 120) return;
    const name = String(node.name || '');
    const text = typeof node.text === 'string' ? node.text.trim().slice(0, 24) : '';
    let tableId = '';
    try {
      if (node.tableId !== undefined && node.tableId !== null) tableId = String(node.tableId);
    } catch (error) {}
    const kids = node.numChildren || 0;
    if (name || text || tableId || depth <= 2) {
      out.push({ d: depth, n: name.slice(0, 30), t: text, id: tableId, k: kids,
        v: node.visible !== false });
    }
    for (let i = 0; i < kids; i += 1) walk(node.getChildAt(i), depth + 1);
  };
  walk(Laya.stage, 0);

  // Tên lớp của các node gốc: nhận diện màn hình (lobby / table / loading).
  const classes = [];
  const top = Laya.stage;
  for (let i = 0; i < (top.numChildren || 0); i += 1) {
    const child = top.getChildAt(i);
    classes.push({ name: String(child.name || ''),
      cls: String((child.constructor && child.constructor.name) || '').slice(0, 40),
      kids: child.numChildren || 0 });
  }
  return { laya: true, stage: [Laya.stage.width, Laya.stage.height],
    top: classes, nodes: out };
})()
"""


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    rows = [row for row in targets(port)
            if "ddnew" in (row.get("url") or "").lower() and row.get("webSocketDebuggerUrl")]
    if not rows:
        print("Không có target DG ở cổng", port)
        return 1
    target = Target(rows[0])
    try:
        value = target.eval(TREE_JS)
        print("target:", rows[0].get("type"), "|", (rows[0].get("url") or "").split("?")[0])
        print("stage:", value.get("stage"), "| top:")
        for node in value.get("top") or []:
            print("  ", node)
        print("nodes (%d):" % len(value.get("nodes") or []))
        for node in value.get("nodes") or []:
            print("  %s %-28s %-24s id=%-8s kids=%-4s vis=%s"
                  % ("  " * node["d"], node["n"], node["t"], node["id"], node["k"], node["v"]))
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
