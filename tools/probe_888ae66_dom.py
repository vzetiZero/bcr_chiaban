# -*- coding: utf-8 -*-
"""Xem DOM quanh thẻ DG của 888AE66 để biết phải bấm phần tử nào.

    python tools/probe_888ae66_dom.py --port 9224
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from cdp_eval import Client  # noqa: E402

JS = r"""
(function () {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const cls = (node) => String(node.getAttribute('class') || '');
  const desc = (node) => ({
    tag: node.tagName, cls: cls(node).slice(0, 70),
    id: String(node.getAttribute('id') || '').slice(0, 30),
    text: norm(node.textContent).slice(0, 24),
    kids: node.children.length,
    size: (() => { const r = node.getBoundingClientRect();
      return [Math.round(r.width), Math.round(r.height)]; })(),
    style: (() => { const s = getComputedStyle(node);
      return [s.display, s.visibility, s.opacity, s.transform.slice(0, 24)]; })(),
  });

  const imgs = [...document.querySelectorAll('img')]
    .filter((img) => /banner-dg/i.test(String(img.getAttribute('alt') || ''))
      || /banner-dg/i.test(String(img.getAttribute('src') || '')));

  const reports = imgs.map((img) => {
    const chain = [];
    let node = img;
    for (let depth = 0; depth < 7 && node; depth += 1) {
      chain.push(desc(node));
      node = node.parentElement;
    }
    const rect = img.getBoundingClientRect();
    return {
      rect: [Math.round(rect.x), Math.round(rect.y),
             Math.round(rect.width), Math.round(rect.height)],
      hitAtCenter: (() => {
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;
        const hit = document.elementFromPoint(x, y);
        return { x: Math.round(x), y: Math.round(y),
          tag: hit ? hit.tagName : '',
          cls: hit ? cls(hit).slice(0, 60) : '',
          alt: hit && hit.getAttribute ? String(hit.getAttribute('alt') || '') : '' };
      })(),
      chain,
    };
  });

  // Các panel danh mục đang hiện (mỗi nhóm nhà cung cấp là một panel).
  const panels = [...document.querySelectorAll(
      '[class*=panel], [class*=category], [class*=group], [class*=tab-content], [class*=sub]')]
    .filter((node) => node.querySelectorAll('img').length > 3)
    .map((node) => ({
      cls: cls(node).slice(0, 60),
      imgs: node.querySelectorAll('img').length,
      dg: [...node.querySelectorAll('img')].some((img) =>
        /banner-dg/i.test(String(img.getAttribute('alt') || ''))),
      style: (() => { const s = getComputedStyle(node);
        return [s.display, s.visibility, s.opacity]; })(),
      rect: (() => { const r = node.getBoundingClientRect();
        return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })(),
    }))
    .slice(0, 12);

  return { count: imgs.length, reports, panels };
})()
"""


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with Client(0, port) as client:
        value = client.eval(JS)
        print("imgs:", value.get("count"))
        for index, report in enumerate(value.get("reports") or []):
            print("\n=== img #%d rect=%s" % (index, report["rect"]))
            print("  center hit:", report["hitAtCenter"])
            for depth, node in enumerate(report["chain"]):
                print("   %d %-7s %-34s kids=%-3s %s %s"
                      % (depth, node["tag"], node["cls"], node["kids"],
                         node["size"], node["style"]))
        print("\n=== panels ===")
        for panel in value.get("panels") or []:
            print(" ", panel)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
