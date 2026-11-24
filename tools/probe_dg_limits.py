# -*- coding: utf-8 -*-
"""So giới hạn bàn mà hai bản DG báo (bpMin/bpMax, nhãn trên màn hình).

    python tools/probe_dg_limits.py --port 9222
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from probe_dg_targets import Target, targets, wrap  # noqa: E402

JS = """
const findView = () => {
  if (typeof Laya === 'undefined' || !Laya.stage) return null;
  let view = null;
  const walk = (node, depth) => {
    if (!node || view || depth > 60) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) { view = node; return; }
    for (const child of (node._children || [])) walk(child, depth + 1);
  };
  walk(Laya.stage, 0);
  return view;
};
const view = findView();
if (!view) return {ok: false};
const player = view.playerInfo || {};
const texts = [];
const collect = (node, depth) => {
  if (!node || depth > 9 || texts.length >= 60) return;
  const value = typeof node.text === 'string' ? node.text.trim() : '';
  if (value) texts.push(value.replace(/\\s+/g, ' ').slice(0, 30));
  for (const child of (node._children || [])) collect(child, depth + 1);
};
collect(view.tableInfoMan, 0);
return {
  ok: true,
  bpMin: view.baccaratLimit && view.baccaratLimit.bpMin,
  bpMax: view.baccaratLimit && view.baccaratLimit.bpMax,
  playerMin: player.bpMin, playerMax: player.bpMax,
  limitMin: player.limitMin, limitMax: player.limitMax,
  currency: player.currency,
  floorText: texts.filter((text) => /\\d\\s*[-~]\\s*\\d/.test(text)).slice(0, 6),
  texts: texts.slice(0, 20)
};
"""


def main(argv):
    port = 9222
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    rows = [row for row in targets(port) if "ddnew" in (row.get("url") or "").lower()]
    if not rows:
        print("no dg target on", port)
        return 1
    target = Target(rows[0])
    try:
        value = target.eval(wrap(JS))
        print(port, "|", rows[0]["url"].split("/")[2])
        print(json.dumps(value, ensure_ascii=False, indent=1))
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
