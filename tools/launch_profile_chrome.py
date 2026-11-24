# -*- coding: utf-8 -*-
"""Mở Chrome của app ở một URL và để nó chạy TÁCH RỜI (không chết theo script).

Dùng khi cần người dùng đăng nhập bằng tay: script thoát ngay, Chrome vẫn mở, và
các script sau gắn vào qua CDP như app thật.

    python tools/launch_profile_chrome.py "https://m.gk881.vip/"
    python tools/launch_profile_chrome.py "https://...e3951.com/m/home" --profile 2 --port 9223

``--profile 2`` dùng thư mục ``chrome_profile_2`` + cổng 9223, đúng như app xếp
profile thứ hai, nên hai site có thể mở song song mà không giành cookie.
"""

import json
import pathlib
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aibcr.adapters import browser as BR

ROOT = pathlib.Path(__file__).resolve().parents[1]


def parse(argv):
    url = BR.START_URL
    index = 1
    port = None
    pos = (40, 40)
    remaining = list(argv)
    while remaining:
        item = remaining.pop(0)
        if item == "--profile":
            index = max(1, int(remaining.pop(0)))
        elif item == "--port":
            port = int(remaining.pop(0))
        elif item in ("--left", "--top"):
            value = int(remaining.pop(0))
            pos = (value, pos[1]) if item == "--left" else (pos[0], value)
        else:
            url = item
    return url, index, port or (9222 + index - 1), pos


def main():
    url, index, port, pos = parse(sys.argv)
    if not BR.valid_site_url(url):
        print("URL khong hop le (chi https cong khai).")
        return 1
    state = {}
    state_file = ROOT / ("aibcr_state_baccarat.json" if index == 1
                         else "aibcr_state_baccarat_%d.json" % index)
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    settings = state.get("settings") or {}
    window = settings.get("chrome_window") or {}
    fingerprint = settings.get("fingerprint")

    BR.PROFILE_DIR = str(ROOT / ("chrome_profile" if index == 1 else "chrome_profile_%d" % index))
    BR.CDP_PORT = port
    chrome = BR.chrome_path()
    if not chrome:
        print("Khong tim thay chrome.exe")
        return 1
    # Cùng một profile không thể mở hai lần; nếu cổng đã mở thì chỉ cần điều
    # hướng tab hiện có thay vì mở thêm một cửa sổ tranh profile.
    if BR.BrowserSession._port_open(port, timeout=0.4):
        print("CDP %d dang mo san (profile %d) — khong mo them cua so." % (port, index))
        return 0
    flags = BR.build_flags(pos=pos, cdp=True, window=window or None,
                           fingerprint=fingerprint)
    cmd = [chrome] + flags + [url]
    parsed = urlsplit(url)
    print("Mo Chrome: %s%s" % (parsed.hostname, parsed.path))
    print("CDP: %d | profile: %s | mobile: %s"
          % (port, pathlib.Path(BR.PROFILE_DIR).name,
             bool(isinstance(fingerprint, dict) and fingerprint.get("user_agent"))))

    creation = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(cmd, creationflags=creation, close_fds=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PID:", proc.pid)

    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if BR.BrowserSession._port_open(port, timeout=0.5):
            print("CDP %d da mo." % port)
            return 0
        time.sleep(0.5)
    print("CDP chua mo sau 40s.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
