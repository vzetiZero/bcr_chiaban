# -*- coding: utf-8 -*-
"""So host của ``<iframe src>`` trong trang site với host thật của target DG.

Đây chính là điều kiện mà ``_promote_cdp_frame`` dùng để chắc chắn target DG
thuộc **trang này**. Đo trên E3951: ``src`` ghi bản desktop còn tài liệu thật là
``ddnewwap`` ở host khác — nếu so host tuyệt đối thì phép kiểm tra luôn sai và
sảnh không bao giờ được đưa lên tab.

    python tools/probe_frame_hosts.py --port 9223
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cdp_eval import Client  # noqa: E402

IFRAMES = """
(function () {
  return [...document.querySelectorAll('iframe,frame')].map((node) => ({
    src: String(node.getAttribute('src') || '').slice(0, 120),
    host: (() => { try { return new URL(node.getAttribute('src') || '', location.href)
      .hostname.toLowerCase(); } catch (error) { return ''; } })(),
  }));
})()
"""


def main(argv):
    port = 9223
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        targets = json.load(response)
    pages = [row for row in targets if row.get("type") == "page"
             and "devtools://" not in (row.get("url") or "")]
    print("== tab site ==")
    for row in pages:
        print("  ", (row.get("url") or "").split("?")[0])
    print("\n== target DG ==")
    for row in targets:
        if "ddnew" in (row.get("url") or "").lower():
            print("  ", row.get("type"), "| host:",
                  (row.get("url") or "").split("/")[2])
    if pages:
        with Client(0, port) as client:
            print("\n== iframe trong trang ==")
            print(json.dumps(client.eval(IFRAMES), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
