# -*- coding: utf-8 -*-
"""Doc cau truc captcha "Xac minh an toan" cua sanh DG (Laya).

Muc dich: tim dau hieu **on dinh** de bao "co captcha" ma khong phu thuoc vao
toa do hay ten node tam thoi. In cay node co text, khong bam gi.

    python tools/probe_dg_captcha.py --port 9224
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import websocket  # noqa: E402

TREE_JS = r"""
(function () {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  const norm = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const walk = (node, depth) => {
    if (!node || depth > 16 || out.length > 400) return;
    let text = '';
    for (const key of ['text', '_text', 'label', '_label']) {
      try {
        const value = node[key];
        if (typeof value === 'string' && value.trim()) { text = norm(value); break; }
      } catch (error) {}
    }
    const ds = node.dataSource || null;
    if (!text && ds && typeof ds === 'object') {
      for (const key of ['text', 'label', 'title']) {
        if (typeof ds[key] === 'string' && ds[key].trim()) { text = norm(ds[key]); break; }
      }
    }
    const name = String(node.name || '');
    if (text || name) {
      out.push({d: depth, n: name.slice(0, 32), t: text.slice(0, 46),
        cls: String((node.constructor && node.constructor.name) || '').slice(0, 26),
        kids: node.numChildren || 0, vis: node.visible !== false});
    }
    for (let i = 0; i < (node.numChildren || 0); i++) walk(node.getChildAt(i), depth + 1);
  };
  walk(Laya.stage, 0);
  // Chuoi quet nhanh: co chu nao lien quan xac minh/keo thanh truot khong.
  const all = out.map((x) => x.t + ' ' + x.n).join(' | ');
  return {
    laya: true,
    hits: out.filter((x) => /xac minh|xác minh|keo|kéo|truot|trượt|captcha|verify|slider/i
      .test(x.t + ' ' + x.n)),
    nodes: out,
    domText: norm(document.body ? document.body.innerText : '').slice(0, 200),
    domCaptcha: !!document.querySelector(
      '[class*=captcha],[id*=captcha],[class*=slider],[id*=slider],[class*=verify]'),
    sample: all.slice(0, 600),
  };
})()
"""


def targets(port):
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as r:
        return json.load(r)


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    rows = [r for r in targets(port)
            if "ddnew" in (r.get("url") or "").lower() and r.get("webSocketDebuggerUrl")]
    if not rows:
        print("khong co tab DG")
        return 1
    ws = websocket.create_connection(rows[0]["webSocketDebuggerUrl"],
                                     suppress_origin=True, timeout=30)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": TREE_JS, "returnByValue": True,
                                       "awaitPromise": True}}))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == 1:
                break
        value = ((reply.get("result") or {}).get("result") or {}).get("value") or {}
    finally:
        ws.close()
    print("dom captcha:", value.get("domCaptcha"), "| dom text:", repr(value.get("domText")))
    print("\n=== node nghi captcha (%d) ===" % len(value.get("hits") or []))
    for node in value.get("hits") or []:
        print("  %s n=%-30s t=%-44s cls=%s kids=%s vis=%s"
              % ("  " * node["d"], node["n"], node["t"], node["cls"], node["kids"], node["vis"]))
    print("\n=== nodes co text/name (%d) ===" % len(value.get("nodes") or []))
    for node in value.get("nodes") or []:
        print("  %s %-30s %-44s %s" % ("  " * node["d"], node["n"], node["t"], node["cls"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
