# -*- coding: utf-8 -*-
"""Dump khung WebSocket của Chrome (CDP) để tìm message kết quả / lá bài của site.

Cách dùng (Chrome đang mở site, có --remote-debugging-port=9222 và đã đăng nhập):

    python tools/dump_ws_frames.py                      # ghi 120 giây
    python tools/dump_ws_frames.py --seconds 300        # ghi 5 phút
    python tools/dump_ws_frames.py --list               # chỉ liệt kê tab đang mở
    python tools/dump_ws_frames.py --match bcr          # chỉ tab có "bcr" trong URL

Kết quả:

    aibcr_ws_frames.jsonl          mọi khung (đã che token/cookie)
    aibcr_ws_frames.hits.jsonl     khung nghi chứa kết quả/lá bài
    aibcr_ws_frames.summary.txt    thống kê URL + chữ ký message

Token, cookie, Authorization trong URL và trong payload đều bị thay bằng ***;
file .jsonl không được commit (xem .gitignore).
"""

import argparse
import base64
import json
import pathlib
import sys
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 9222
DEFAULT_OUT = "aibcr_ws_frames.jsonl"
DEFAULT_SECONDS = 120
DEFAULT_MAX_BYTES = 60000

SENSITIVE_KEYS = frozenset((
    "token", "accesstoken", "access_token", "refreshtoken", "refresh_token",
    "idtoken", "id_token", "jwt", "authorization", "auth", "session",
    "sessionid", "session_id", "sid", "ticket", "password", "passwd", "secret",
    "apikey", "api_key", "signature", "sig", "cookie", "setcookie", "set_cookie",
    "bearer", "credential", "credentials",
))
INTERESTING_KEYWORDS = (
    "card", "cards", "deck", "suit", "rank", "shoe", "result", "results",
    "score", "scores", "player", "banker", "history", "road", "round",
    "hand", "winner", "tie", "outcome", "bet", "poker", "point", "points",
)


def _key(name):
    return str(name or "").strip().lower().replace("-", "").replace("_", "")


_SENSITIVE = frozenset(_key(item) for item in SENSITIVE_KEYS)


def is_sensitive(name):
    return _key(name) in _SENSITIVE


def redact_url(url):
    """Bỏ userinfo, fragment và mọi query value nhạy cảm (token, session, sig…)."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return "***"
    query = [(key, "***" if is_sensitive(key) else value)
             for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port is None else "%s:%d" % (host, port)
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ""))


def redact_payload(value, depth=0):
    """Thay giá trị của mọi field nhạy cảm trong JSON; giữ nguyên phần còn lại."""
    if depth > 12:
        return "***"
    if isinstance(value, dict):
        return {key: ("***" if is_sensitive(key) else redact_payload(item, depth + 1))
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, depth + 1) for item in value[:2000]]
    return value


def truncate_text(text, max_bytes):
    raw = str(text)
    data = raw.encode("utf-8", "replace")
    if len(data) <= max_bytes:
        return raw, False
    cut = data[:max_bytes].decode("utf-8", "ignore")
    return cut + "…[truncated %d bytes]" % (len(data) - max_bytes), True


def signature(payload):
    """Chữ ký ngắn của một message: loại + các field cấp 1, để gom nhóm nhanh."""
    if not isinstance(payload, dict):
        return "text"
    kind = next((payload.get(key) for key in
                 ("type", "op", "event", "cmd", "method", "topic", "t")
                 if isinstance(payload.get(key), (str, int))), "")
    keys = ",".join(sorted(str(key) for key in payload.keys())[:12])
    return "%s|%s" % (kind, keys)


def has_interesting_keyword(text):
    low = str(text or "").casefold()
    return [word for word in INTERESTING_KEYWORDS if word in low]


def list_pages(port):
    with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:
        return json.load(response)


class Writer:
    """Ghi JSONL an toàn từ nhiều thread, kèm bộ đếm và mẫu chữ ký."""

    def __init__(self, path, hits_path):
        self.path = pathlib.Path(path)
        self.hits_path = pathlib.Path(hits_path)
        self.lock = threading.Lock()
        self.counts = {}
        self.signatures = {}
        self.samples = {}
        self.keywords = {}
        self.recv = 0
        self.sent = 0
        self.opened = {}
        self.targets = set()
        self._file = self.path.open("w", encoding="utf-8")
        self._hits = self.hits_path.open("w", encoding="utf-8")

    def close(self):
        with self.lock:
            self._file.close()
            self._hits.close()

    def opened_target(self, target_id):
        with self.lock:
            self.targets.add(target_id)

    def ws_open(self, target_id, url):
        with self.lock:
            self.opened[url] = self.opened.get(url, 0) + 1
            self._file.write(json.dumps({
                "ts": round(time.time(), 3), "target": target_id,
                "dir": "open", "url": url}, ensure_ascii=False) + "\n")

    def frame(self, target_id, direction, url, opcode, payload_data, max_bytes):
        if direction == "recv":
            with self.lock:
                self.recv += 1
        else:
            with self.lock:
                self.sent += 1
        text, truncated = truncate_text(payload_data, max_bytes)
        parsed = None
        if opcode == 1 and not truncated:
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                parsed = None
        record = {
            "ts": round(time.time(), 3), "target": target_id, "dir": direction,
            "url": url, "opcode": opcode, "len": len(str(payload_data)),
        }
        if opcode == 2:
            record["b64"] = base64.b64encode(str(payload_data).encode("utf-8", "replace")
                                             [:max_bytes]).decode("ascii")
            record["truncated"] = truncated
        elif parsed is not None:
            record["json"] = redact_payload(parsed)
        else:
            record["data"] = text
            record["truncated"] = truncated
        line = json.dumps(record, ensure_ascii=False) + "\n"
        sig = signature(parsed if parsed is not None else text)
        interesting = has_interesting_keyword(line)
        with self.lock:
            self._file.write(line)
            self.counts[url] = self.counts.get(url, 0) + 1
            self.signatures.setdefault(url, {})
            self.signatures[url][sig] = self.signatures[url].get(sig, 0) + 1
            bucket = self.samples.setdefault(url, {})
            bucket.setdefault(sig, {"count": 0, "sample": text[:600]})
            bucket[sig]["count"] += 1
            for word in interesting:
                self.keywords[word] = self.keywords.get(word, 0) + 1
            if interesting:
                self._hits.write(line)

    def summary(self):
        lines = ["== WS DUMP SUMMARY ==",
                 "tabs: %d" % len(self.targets),
                 "frames: recv=%d sent=%d" % (self.recv, self.sent), ""]
        for url in sorted(self.counts):
            lines.append("%s  frames=%d" % (url, self.counts[url]))
            ranked = sorted(self.signatures.get(url, {}).items(),
                            key=lambda item: -item[1])[:10]
            for sig, count in ranked:
                lines.append("    %6d  %s" % (count, sig))
            sample = (self.samples.get(url) or {}).get(ranked[0][0]) if ranked else None
            if sample:
                lines.append("    sample: %s" % sample["sample"].replace("\n", " ")[:300])
            lines.append("")
        if self.keywords:
            lines.append("keyword hits: " + ", ".join(
                "%s=%d" % item for item in sorted(self.keywords.items())))
        return "\n".join(lines)


class TabReader(threading.Thread):
    """Một thread đọc CDP của một tab; Network.enable để nhận mọi khung WebSocket."""

    def __init__(self, target, writer, stop, max_bytes, url_filter=None):
        super().__init__(daemon=True, name="ws-%s" % target.get("id", "?")[:8])
        self.target = target
        self.writer = writer
        self.stop = stop
        self.max_bytes = max_bytes
        self.url_filter = url_filter

    def run(self):
        import websocket

        target_id = str(self.target.get("id") or "")
        endpoint = self.target.get("webSocketDebuggerUrl") or ""
        try:
            ws = websocket.create_connection(
                endpoint, suppress_origin=True, timeout=10,
                http_no_proxy=["127.0.0.1", "localhost", "::1"], redirect_limit=0)
        except Exception as exc:
            self.writer.ws_open(target_id, "connect_error:%s" % type(exc).__name__)
            return
        ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        urls = {}
        self.writer.opened_target(target_id)
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
                    url = redact_url(params.get("url"))
                    urls[request_id] = url
                    self.writer.ws_open(target_id, url)
                elif method in ("Network.webSocketFrameReceived",
                                "Network.webSocketFrameSent"):
                    url = urls.get(request_id, "unknown")
                    if self.url_filter and self.url_filter not in url:
                        continue
                    response = params.get("response") or {}
                    direction = "recv" if method.endswith("Received") else "sent"
                    self.writer.frame(target_id, direction, url,
                                      response.get("opcode", 1),
                                      response.get("payloadData") or "",
                                      self.max_bytes)
                elif method in ("Network.webSocketClosed", "Network.webSocketFrameError"):
                    url = urls.get(request_id, "unknown")
                    self.writer.ws_open(target_id, "closed:%s" % url)
        finally:
            try:
                ws.close()
            except Exception:
                pass


def render_pages(pages):
    for page in pages:
        print("%s  %s" % (page.get("id", "")[:12], page.get("url", "")))


def main(argv=None):
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="cổng CDP của Chrome (mặc định 9222)")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                        help="thời gian ghi (mặc định 120 giây)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="file JSONL đầu ra")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help="giới hạn mỗi khung được ghi (mặc định 60000)")
    parser.add_argument("--match", default="",
                        help="chỉ đọc tab có chuỗi này trong URL trang")
    parser.add_argument("--url", default="",
                        help="chỉ ghi khung WebSocket có chuỗi này trong URL WS")
    parser.add_argument("--list", action="store_true", help="chỉ liệt kê tab rồi thoát")
    args = parser.parse_args(argv)

    try:
        pages = [page for page in list_pages(args.port)
                 if isinstance(page, dict) and page.get("type") == "page"]
    except Exception as exc:
        print("Không thấy Chrome CDP ở cổng %d (%s)." % (args.port, type(exc).__name__))
        print("Mở Chrome kèm --remote-debugging-port=%d rồi đăng nhập site." % args.port)
        return 2

    if args.match:
        pages = [page for page in pages if args.match in str(page.get("url") or "")]
    if args.list:
        render_pages(pages or [])
        return 0
    if not pages:
        print("Không có tab nào khớp bộ lọc.")
        return 2

    out_path = pathlib.Path(args.out)
    writer = Writer(out_path, out_path.with_name(out_path.stem + ".hits.jsonl"))
    stop = threading.Event()
    ended = time.monotonic() + max(1.0, args.seconds)
    active = {}
    print("Đang ghi %d tab tới %s (Ctrl+C để dừng sớm)…" % (len(pages), out_path.name))
    try:
        while time.monotonic() < ended:
            try:
                current = [page for page in list_pages(args.port)
                           if isinstance(page, dict) and page.get("type") == "page"
                           and (not args.match or args.match in str(page.get("url") or ""))]
            except Exception:
                current = [page for page in pages if page.get("id") not in active]
            known = {str(page.get("id")) for page in current}
            for target_id in list(active):
                thread = active[target_id]
                if not thread.is_alive() or target_id not in known:
                    active.pop(target_id, None)
            for page in current:
                target_id = str(page.get("id") or "")
                if target_id and target_id not in active:
                    thread = TabReader(page, writer, stop, args.max_bytes,
                                       url_filter=args.url or None)
                    thread.start()
                    active[target_id] = thread
            remaining = max(0, int(ended - time.monotonic()))
            print("… recv=%d sent=%d · còn %ds" % (writer.recv, writer.sent, remaining),
                  end="\r")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nDừng theo yêu cầu.")
    finally:
        stop.set()
        for thread in active.values():
            thread.join(timeout=2)
        writer.close()

    summary = writer.summary()
    summary_path = out_path.with_name(out_path.stem + ".summary.txt")
    summary_path.write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print("\nĐã ghi: %s" % out_path)
    print("Khung nghi kết quả/lá bài: %s" % out_path.with_name(out_path.stem + ".hits.jsonl"))
    print("Thống kê: %s" % summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
