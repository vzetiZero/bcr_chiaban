# -*- coding: utf-8 -*-
"""Đọc cấu trúc trang 888AE66 để tìm đường vào sảnh DG.

Chỉ đọc: liệt kê menu/danh mục đang hiển thị, các thẻ nhà cung cấp, và tên site
đang mở. Không bấm gì, không in token/cookie.

    python tools/probe_888ae66.py --port 9224
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from cdp_eval import Client  # noqa: E402

SCAN_JS = r"""
(function () {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const vis = (node) => {
    try {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 8 && rect.height > 8 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity) > 0.05;
    } catch (error) { return false; }
  };
  const cls = (node) => String(node.getAttribute('class') || '').slice(0, 70);

  // Nhãn ngắn, đang hiện, có thể bấm — đây là ứng viên menu/danh mục.
  const labels = [];
  const seen = new Set();
  for (const node of document.querySelectorAll(
      'a,button,div,span,li,[role=button],[class*=nav],[class*=menu],[class*=tab],[class*=categ]')) {
    const text = norm(node.textContent);
    if (!text || text.length > 26) continue;
    if (node.children.length > 2) continue;
    if (!vis(node)) continue;
    const key = text + '|' + cls(node);
    if (seen.has(key)) continue;
    seen.add(key);
    const rect = node.getBoundingClientRect();
    labels.push({ text, tag: node.tagName, cls: cls(node),
      at: [Math.round(rect.x), Math.round(rect.y),
           Math.round(rect.width), Math.round(rect.height)] });
    if (labels.length >= 120) break;
  }

  // Thẻ nhà cung cấp thường là <img> có alt hoặc lớp provider/banner.
  const providers = [];
  for (const img of document.querySelectorAll('img')) {
    if (!vis(img)) continue;
    const alt = norm(img.getAttribute('alt'));
    const src = String(img.getAttribute('src') || '');
    if (!alt && !/provider|banner|game|logo/i.test(src)) continue;
    const rect = img.getBoundingClientRect();
    providers.push({ alt, file: src.split('/').pop().split('?')[0].slice(0, 60),
      at: [Math.round(rect.x), Math.round(rect.y)] });
    if (providers.length >= 60) break;
  }

  return {
    host: location.hostname, path: location.pathname, title: document.title,
    mobile: /\/m(\/|$)/.test(location.pathname),
    canvas: document.querySelectorAll('canvas').length,
    iframes: [...document.querySelectorAll('iframe')].map((node) => ({
      cls: cls(node),
      host: (() => { try { return new URL(node.getAttribute('src') || '', location.href).hostname; }
        catch (error) { return ''; } })(),
    })),
    hasLogin: !!document.querySelector('button.header-btn.login, .login-btn'),
    labels: labels.slice(0, 90),
    providers: providers.slice(0, 40),
    bodyHead: norm(document.body ? document.body.innerText : '').slice(0, 240),
  };
})()
"""


def main(argv):
    port = 9224
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with Client(0, port) as client:
        print("tab:", (client.page.get("url") or "").split("?")[0], flush=True)
        print(json.dumps(client.eval(SCAN_JS), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
