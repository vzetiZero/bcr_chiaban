# -*- coding: utf-8 -*-
"""In TÊN tham số (không in giá trị) trong URL của target DG.

Cần biết sảnh tự mang ``token``/``tableId`` hay không, vì đó là điều kiện để đưa
được URL sảnh lên tab chính thay cho ``/m/home``.

    python tools/probe_dg_url_params.py --port 9223
"""

import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))


def main(argv):
    port = 9223
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        targets = json.load(response)
    for row in targets:
        url = row.get("url") or ""
        if "ddnew" not in url.lower():
            continue
        import urllib.parse as up
        parsed = up.urlsplit(url)
        params = up.parse_qs(parsed.query, keep_blank_values=True)
        print("type:", row.get("type"))
        print("  host:", parsed.hostname)
        print("  path:", parsed.path)
        print("  params:", sorted(params.keys()))
        print("  has tableId:", "tableId" in params,
              "| value:", (params.get("tableId") or [""])[0])
        print("  has token:", "token" in params,
              "| len:", len((params.get("token") or [""])[0]))
        print("  lens:", {key: len(value[0]) for key, value in params.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
