# -*- coding: utf-8 -*-
"""Mở Chrome có CDP rồi bắt luôn WebSocket của bàn — không cần gửi file dump.

Chrome thường (mở bằng tay) KHÔNG có cổng gỡ lỗi, nên không thể gắn vào. Tool này mở
một Chrome riêng có `--remote-debugging-port`, chờ bạn đăng nhập + mở bàn, rồi tự bắt
mọi khung WebSocket và in tại chỗ những khung nghi chứa lá bài / kết quả:

    python tools/cdp_capture.py --url "<link vào bàn, có token>"
    python tools/cdp_capture.py                    # đã có Chrome CDP đang mở sẵn
    python tools/cdp_capture.py --seconds 600       # ghi 10 phút
    python tools/cdp_capture.py --wait "live-games/bcr"

Nếu Chrome đang mở bằng tay, tool tự mở thêm cửa sổ với profile riêng
(`chrome_profile_cdp/`) để không đụng Chrome của bạn và không đá phiên đăng nhập.

Ra file (đã che token/cookie, nằm trong .gitignore):

    aibcr_ws_frames.jsonl          mọi khung
    aibcr_ws_frames.hits.jsonl     khung nghi có lá bài/kết quả
    aibcr_ws_frames.summary.txt    thống kê URL + chữ ký message
"""

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aibcr.adapters import browser as BR

SPEC = importlib.util.spec_from_file_location("dump_ws_frames",
                                              ROOT / "tools" / "dump_ws_frames.py")
DUMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DUMP)

DEFAULT_PROFILE = ROOT / "chrome_profile_cdp"
DEFAULT_OUT = ROOT / "aibcr_ws_frames.jsonl"


def pages(port):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as response:
        return [page for page in json.load(response)
                if isinstance(page, dict) and page.get("type") == "page"]


def wait_cdp(port, seconds=25.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1) as response:
                if response.status == 200:
                    return True
        except (URLError, OSError, ValueError):
            pass
        time.sleep(0.4)
    return False


def launch_chrome(port, profile, url):
    chrome = BR.chrome_path()
    if not chrome:
        return None, "Không tìm thấy chrome.exe."
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        chrome,
        "--user-data-dir=%s" % profile,
        "--remote-debugging-port=%d" % port,
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-extensions",
        "--window-size=1360,900", "--window-position=40,30",
        "--remote-allow-origins=*",
    ]
    if url:
        command.append(url)
    try:
        process = subprocess.Popen(command, close_fds=True)
    except OSError as exc:
        return None, "Không mở được Chrome (%s)." % type(exc).__name__
    return process, "Đã mở Chrome CDP %d · profile %s" % (port, profile.name)


def match_tab(tab_pages, pattern):
    """Tab khớp mẫu URL (regex) và đang ở trang game, không phải trang trắng."""
    if not pattern:
        return tab_pages[0] if tab_pages else None
    found = re.compile(pattern, re.I)
    for page in tab_pages:
        url = str(page.get("url") or "")
        if url and found.search(url):
            return page
    return None


def describe(record):
    """Một dòng gọn cho console: loại message + đoạn JSON ngắn."""
    body = record.get("json")
    if body is None:
        text = str(record.get("data") or "")
        return text[:220].replace("\n", " ")
    shape = DUMP.signature(body)
    return "%s · %s" % (shape, json.dumps(body, ensure_ascii=False)[:220])


class LivePrinter:
    """In khung nghi kết quả/lá bài tại chỗ, gộp theo chữ ký để không ngập màn hình."""

    def __init__(self, limit_per_signature=3, sink=None):
        self.seen = {}
        self.limit = max(1, int(limit_per_signature))
        self.hits = 0
        self.sink = sink or self._stdout

    @staticmethod
    def _stdout(text):
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"))

    def feed(self, record):
        line = json.dumps(record, ensure_ascii=False)
        if not DUMP.has_interesting_keyword(line):
            return
        self.hits += 1
        key = DUMP.signature(record.get("json")) if record.get("json") else "text"
        count = self.seen.get(key, 0) + 1
        self.seen[key] = count
        if count > self.limit:
            if count == self.limit + 1:
                self.sink("  … (%s: ẩn các khung trùng tiếp theo)" % key)
            return
        stamp = time.strftime("%H:%M:%S")
        self.sink("  [%s] %s" % (stamp, describe(record)[:400]))


class CaptureTab(threading.Thread):
    """Bắt WS của một tab; gọi ``on_record`` cho từng khung, ghi file qua Writer."""

    def __init__(self, page, port, writer, stop, on_record=None, max_bytes=DUMP.DEFAULT_MAX_BYTES):
        super().__init__(daemon=True, name="cap-%s" % str(page.get("id"))[:8])
        self.page = page
        self.port = port
        self.writer = writer
        self.stop = stop
        self.on_record = on_record
        self.max_bytes = max_bytes

    def run(self):
        import websocket

        target_id = str(self.page.get("id") or "")
        endpoint = self.page.get("webSocketDebuggerUrl") or ""
        try:
            ws = websocket.create_connection(
                endpoint, suppress_origin=True, timeout=10,
                http_no_proxy=["127.0.0.1", "localhost", "::1"], redirect_limit=0)
        except Exception as exc:
            emit("  ! không gắn được tab %s (%s)" % (target_id[:8], type(exc).__name__))
            return
        ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        urls = {}
        self.writer.opened_target(target_id)
        emit("  + đang bắt WS tab %s · %s" % (target_id[:8], DUMP.redact_url(self.page.get("url"))))
        try:
            while not self.stop.is_set():
                ws.settimeout(0.5)
                try:
                    message = json.loads(ws.recv())
                except Exception as exc:
                    if type(exc).__name__ in ("WebSocketTimeoutException", "TimeoutError"):
                        continue
                    break
                method = message.get("method")
                params = message.get("params") or {}
                request_id = params.get("requestId")
                if method == "Network.webSocketCreated":
                    url = DUMP.redact_url(params.get("url"))
                    urls[request_id] = url
                    self.writer.ws_open(target_id, url)
                    emit("  ~ WS mở: %s" % url)
                elif method in ("Network.webSocketFrameReceived",
                                "Network.webSocketFrameSent"):
                    response = params.get("response") or {}
                    direction = "recv" if method.endswith("Received") else "sent"
                    self.writer.frame(target_id, direction, urls.get(request_id, "unknown"),
                                      response.get("opcode", 1),
                                      response.get("payloadData") or "", self.max_bytes)
                    if direction == "recv" and self.on_record is not None:
                        payload = response.get("payloadData") or ""
                        parsed = None
                        try:
                            parsed = json.loads(payload)
                        except (ValueError, TypeError):
                            parsed = None
                        self.on_record({"json": parsed} if parsed is not None else
                                       {"data": payload})
                elif method == "Network.webSocketClosed":
                    emit("  - WS đóng: %s" % urls.get(request_id, "unknown"))
        finally:
            try:
                ws.close()
            except Exception:
                pass


def emit(text):
    """In ra console, không chết khi terminal Windows dùng code page cũ."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def main(argv=None):
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=BR.CDP_PORT, help="cổng CDP (mặc định 9222)")
    parser.add_argument("--url", default="", help="link bàn cần mở (chứa token của bạn)")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE),
                        help="profile Chrome riêng cho tool (mặc định chrome_profile_cdp)")
    parser.add_argument("--wait", default="live-games|/bcr/|table",
                        help="mẫu URL của tab bàn cần bắt (regex, mặc định live-games|/bcr/|table)")
    parser.add_argument("--wait-seconds", type=float, default=180.0,
                        help="thời gian chờ bạn đăng nhập + mở bàn (mặc định 180s)")
    parser.add_argument("--seconds", type=float, default=1800.0,
                        help="thời gian ghi sau khi gắn được tab (mặc định 1800s)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="file JSONL đầu ra")
    parser.add_argument("--max-bytes", type=int, default=DUMP.DEFAULT_MAX_BYTES)
    parser.add_argument("--show", type=int, default=3,
                        help="số khung mẫu in ra mỗi chữ ký message (mặc định 3)")
    parser.add_argument("--attach-only", action="store_true",
                        help="không mở Chrome mới, chỉ gắn Chrome CDP đang mở")
    args = parser.parse_args(argv)

    process = None
    if not args.attach_only and not wait_cdp(args.port, seconds=1.0):
        process, note = launch_chrome(args.port, pathlib.Path(args.profile), args.url)
        emit(note)
        if process is None:
            return 2
        if not wait_cdp(args.port):
            emit("Chrome mở nhưng CDP %d chưa lên. Kiểm tra Chrome/tường lửa rồi thử lại."
                 % args.port)
            return 2
    else:
        emit("Gắn Chrome CDP đang mở ở cổng %d." % args.port)

    emit("Chờ tab bàn khớp “%s” (tối đa %ds)…" % (args.wait, int(args.wait_seconds)))
    deadline = time.monotonic() + max(1.0, args.wait_seconds)
    page = None
    while time.monotonic() < deadline:
        try:
            page = match_tab(pages(args.port), args.wait)
        except (URLError, OSError, ValueError):
            page = None
        if page:
            break
        time.sleep(1.0)
    if page is None:
        emit("Chưa thấy tab bàn. Đăng nhập, mở bàn rồi chạy lại tool "
             "(hoặc tăng --wait-seconds).")
        if process is not None:
            emit("Chrome vẫn đang mở — đăng nhập xong chạy: "
                 "python tools/cdp_capture.py --attach-only")
        return 2

    emit("Bắt đầu bắt WS · tab: %s" % DUMP.redact_url(page.get("url")))

    out_path = pathlib.Path(args.out)
    writer = DUMP.Writer(out_path, out_path.with_name(out_path.stem + ".hits.jsonl"))
    printer = LivePrinter(limit_per_signature=args.show)
    stop = threading.Event()
    active = {}
    ended = time.monotonic() + max(1.0, args.seconds)
    try:
        while time.monotonic() < ended:
            try:
                current = pages(args.port)
            except (URLError, OSError, ValueError):
                break
            for target_id in list(active):
                if not active[target_id].is_alive():
                    active.pop(target_id, None)
            for item in current:
                target_id = str(item.get("id") or "")
                if not target_id or target_id in active:
                    continue
                if not match_tab([item], args.wait):
                    continue
                thread = CaptureTab(item, args.port, writer, stop,
                                    on_record=printer.feed, max_bytes=args.max_bytes)
                thread.start()
                active[target_id] = thread
            left = max(0, int(ended - time.monotonic()))
            emit("… recv=%d · khung nghi kết quả=%d · còn %ds" % (
                writer.recv, printer.hits, left))
            time.sleep(1.0)
    except KeyboardInterrupt:
        emit("\nDừng theo yêu cầu.")
    finally:
        stop.set()
        for thread in active.values():
            thread.join(timeout=2)
        writer.close()

    summary = writer.summary()
    summary_path = out_path.with_name(out_path.stem + ".summary.txt")
    summary_path.write_text(summary, encoding="utf-8")
    emit("\n\n" + summary)
    emit("\nĐã ghi: %s" % out_path)
    emit("Khung nghi kết quả/lá bài: %s" % out_path.with_name(out_path.stem + ".hits.jsonl"))
    emit("Chrome vẫn mở để bạn xem lại bàn; đóng cửa sổ đó khi xong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
