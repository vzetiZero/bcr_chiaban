# -*- coding: utf-8 -*-
"""Tầng Controller · Baccarat: đọc bàn, AI dự đoán, nhận lệnh cược từ UI, đặt chip.

Chỉ điều phối Model (``aibcr.models``) và Adapter (``aibcr.adapters``); không dùng tkinter
và không biết gì về Electron. Tầng transport (``aibcr.service.engine``) gọi
``dispatch`` để phục vụ giao diện Electron.

Không còn phương pháp 3-3/3-2, thang cược hay khối mạnh/yếu. Mỗi tay người dùng cấu
hình cửa + số chip trên UI (hoặc chọn “theo AI”), rồi bấm “Tự đặt cược”: controller
chốt lệnh, chờ ván mới rồi bấm chip thật và đối chiếu xác nhận.

Trách nhiệm:
    - mở/gắn Chrome (CDP 9222), nút “VÀO BÀN HỢP LỆ”, quét sảnh, theo dõi bàn
    - chạy luồng live Petalive + AI (xác suất/EV do ``predict`` tính, AI chỉ giải thích)
    - nhận lệnh ``bet.config`` / ``bet.place`` từ UI và tự đặt chip thật
    - ghi lãi/lỗ, chốt lời, lưu/khôi phục phiên

API key AI chỉ nằm trong RAM (``ai.key.set``), không ghi vào state file hay snapshot.
"""

import collections
import json
import pathlib
import queue
import threading
import time

from aibcr.adapters import browser as BR
from aibcr.adapters import febet as FEBET
from aibcr.adapters import lobby_stream as LS
from aibcr.adapters import table_bets as TB
from aibcr.adapters.wm_bet import WMBet
from aibcr.config import *  # noqa: F401,F403
from aibcr.live.reader import LiveReader
from aibcr.live.session import LiveSession
from aibcr.live.wm_reader import WMReader, find_wm_page, find_wm_table
from aibcr.live import ai as LIVE_AI
from aibcr.models import engine as E
from aibcr.models import money as M
from aibcr.models.live_sim import (LiveSimulation, compare_chips, table_is_clear,
                                   table_stats)

# Cấu hình mặc định của tab Baccarat (đơn vị VN2 như hiển thị trên sàn).
DEFAULT_CONFIG = {
    "capital": 3000.0,          # vốn phiên (VN2)
    "take_profit_pct": 25.0,    # chốt lời % vốn
    "favorites_only": True,
    "human_mouse": True,
    "auto_place": True,         # cho phép bấm chip thật khi bấm “Tự đặt cược”
    "auto_hunt": True,
    "auto_recover": True,
    "tables_to_play": 1,
    # Lệnh cược mặc định; cửa luôn do người dùng chọn trực tiếp.
    "bet_side": "P",            # P | B | T; wagering never follows AI output
    # 10 đơn vị = 10.000đ (WM in khay chip theo nghìn đồng, 1 đv = 1.000đ).
    "bet_stake": 10.0,          # số đơn vị cố định cho mỗi tay
    "start_url": BR.START_URL,
    "chrome_window": {"width": 1280, "height": 800, "percent": 100, "fullscreen": False},
    # AI live (site Petalive): off | local | api. Key AI CHỈ đọc từ env BCR_AI_KEY.
    "ai_mode": "api",
    "ai_url": "https://api.vilao.ai/v1/chat/completions",
    "ai_model": "chib/deepseek-v4.1-flash",
    "ai_every": 5,          # gọi AI mỗi N ván
    "ai_timeout": 8,        # ngắn hơn cửa cược ~25s
    "live_decks": 8,
    "live_trials": 20000,
    "live_markov_weight": 0.15,
}


def _as_float(value, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if number == number else float(fallback)


def _as_int(value, fallback):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(fallback)


def _finite(value, fallback=0.0):
    """JSON của Electron không nhận NaN/Infinity; mọi số ra ngoài đều phải hữu hạn."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if number != number or number in (float("inf"), float("-inf")):
        return float(fallback)
    return number


class BaccaratController:
    """Điều phối một phiên Baccarat: Chrome → sảnh → bàn → cược → chuyển bàn."""

    def __init__(self, state_path, emit, interval=2.0):
        self.state_path = pathlib.Path(state_path)
        self.emit = emit
        self.interval = float(interval or 2.0)
        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.logs = collections.deque(maxlen=300)
        self.config = self._load_config()

        self.browser = BR.BrowserSession()
        self.stream = LS.LobbyStream(self.browser, human_mouse=self.config["human_mouse"],
                                     game="baccarat")
        self.sim = self._build_sim()

        self.tables = {}
        self.tool_running = False
        self._stop = threading.Event()
        self._thread = None

        # Luồng AI live (WebSocket Petalive) — chạy riêng, không chặn _loop().
        self.live_session = None
        self.live_reader = None
        self.live_stop_event = threading.Event()
        self.live_reader_probe_at = 0.0
        self.live_hand = 0
        # API key nhập từ UI: CHỈ RAM. Không đưa vào self.config, state file hay snapshot.
        self.ai_key_override = ""
        self.bet_config = {"side": self.config["bet_side"], "stake": self.config["bet_stake"]}

        # cờ bận cho các thao tác web (giống controller Tk)
        self.chrome_busy = False
        self.scan_busy = False
        self.sweep_busy = False
        self.open_table_busy = False
        self.chip_busy = False
        self.place_busy = False
        self.recover_busy = False
        # Đã báo "Chrome đã đóng" chưa (tránh spam log mỗi 2 giây khi mất kết nối).
        self.offline_noted = False
        # Đã từng kết nối Chrome trong phiên này chưa (phân biệt "chưa mở" với "vừa đóng").
        self.had_chrome = False

        self.next_scan = 0.0
        self.chip_live = None
        self.chip_read_at = 0.0
        self.place_status = {"ok": None, "note": ""}
        self.wallet_text = "Số dư ví trên web: chưa đọc được"
        self.sweep_note = "Mở Chrome, vào sảnh Baccarat rồi bấm “VÀO BÀN HỢP LỆ”."
        self.connection_text = "Chưa kết nối Chrome."

        # vòng tự săn bàn
        self.cycle_waiting = False
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None
        self.tables_done = 0

        # bàn vừa mở, chờ đọc được cầu rồi theo dõi
        self.auto_start_key = None
        # Nút “Vào bàn hợp lệ”: tìm + mở + kiểm tra cầu nhưng KHÔNG theo dõi/đặt chip.
        self.enter_valid = False
        self.valid_check_done = False
        self.valid_note = ""
        self.enter_attempts = 0
        self.enter_deadline = 0.0
        self.auto_start_deadline = 0.0

        self.session_lost = False
        self.recover_attempts = 0
        # Chế độ một nút: “Chạy tool” = tự vào bàn + tự đặt cược từng tay. Biến này giữ
        # cầu của tay đã arm để không arm lặp lại cùng một tay.
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = ""
        # Mốc Chrome rời bàn (về sảnh/đăng nhập) trong khi sim vẫn bám bàn cũ: quá
        # ngưỡng thì rời bàn để tool tự vào lại, thay vì treo ở "chờ dữ liệu WS".
        self.lobby_since = None
        # Lệnh vừa đặt gần nhất (side/stake). Giữa hai ván chip trên bàn thuộc lệnh này,
        # không phải lệnh tay kế (chưa bấm) — dùng để không báo "SAI CỬA" oan.
        self.last_order = None
        # (table_key, số tay) đã chốt lệnh — chặn đặt trùng khi nguồn phát lại một ván.
        self.placed_signatures = set()
        # Cầu của bộ đọc WebSocket khi AI live đang chạy. Lượt quét CDP có thể trả về
        # bản cũ (bắt đầu trước khi ván mới về); không được để nó ghi đè/đảo cầu live.
        self.live_road = ""
        # Chưa có bàn (Chrome vừa mở/chưa đăng nhập) thì thử lại theo nhịp này.
        self.tool_retry_at = 0.0

        self.log("Engine Baccarat sẵn sàng (đọc live + AI · tự đặt cược theo lệnh UI).")

    # ------------------------------------------------------------- cấu hình
    def _load_config(self):
        config = dict(DEFAULT_CONFIG)
        saved = {}
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        settings = saved.get("settings") if isinstance(saved, dict) else None
        if isinstance(settings, dict):
            for key in config:
                if key in settings and settings[key] is not None:
                    config[key] = settings[key]
        self._saved_session = saved if isinstance(saved, dict) else {}
        self.config = self._normalize_config(config)
        return self.config

    def _normalize_config(self, config):
        # Dọn config của phiên cũ: không để 3-3/3-2 sống sót qua file state.
        for key in ("profile", "ladder", "ladder_mode", "ladder_base", "block_mode",
                    "live_exit_streak", "auto_cycle", "min_hands", "max_hands",
                    "max_streak", "min_lead", "max_lead", "tie_side"):
            config.pop(key, None)
        legacy_ai_side = str(config.get("bet_side") or "").strip().upper() == "AUTO"
        config["capital"] = max(1.0, _as_float(config.get("capital"), DEFAULT_CONFIG["capital"]))
        config["take_profit_pct"] = max(1.0, _as_float(config.get("take_profit_pct"),
                                                       DEFAULT_CONFIG["take_profit_pct"]))
        for key in ("favorites_only", "human_mouse", "auto_place", "auto_hunt", "auto_recover"):
            config[key] = bool(config.get(key, DEFAULT_CONFIG[key]))
        if legacy_ai_side:
            config["auto_place"] = False
        side = str(config.get("bet_side") or "P").strip().upper()
        config["bet_side"] = side if side in ("P", "B", "T") else "P"
        config["bet_stake"] = min(1000000.0, max(1.0, _as_float(
            config.get("bet_stake"), DEFAULT_CONFIG["bet_stake"])))
        config["tables_to_play"] = max(1, _as_int(config.get("tables_to_play"), 1))
        mode = str(config.get("ai_mode") or "off").strip().lower()
        config["ai_mode"] = mode if mode in ("off", "local", "api") else "off"
        ai_url = str(config.get("ai_url") or "").strip()[:300]
        config["ai_url"] = ai_url if (not ai_url or
                                      ai_url.startswith(("http://", "https://"))) else ""
        config["ai_model"] = str(config.get("ai_model") or "").strip()[:80]
        config["ai_every"] = min(60, max(1, _as_int(config.get("ai_every"), 5)))
        config["ai_timeout"] = min(30, max(2, _as_int(config.get("ai_timeout"), 8)))
        config["live_decks"] = min(16, max(1, _as_int(config.get("live_decks"), 8)))
        config["live_trials"] = min(200000, max(100, _as_int(config.get("live_trials"), 20000)))
        config["live_markov_weight"] = max(0.0, min(1.0, _as_float(
            config.get("live_markov_weight"), DEFAULT_CONFIG["live_markov_weight"])))
        url = config.get("start_url")
        config["start_url"] = url if isinstance(url, str) and BR.valid_site_url(url.strip()) \
            else BR.START_URL
        window = config.get("chrome_window")
        if not isinstance(window, dict):
            window = dict(DEFAULT_CONFIG["chrome_window"])
        config["chrome_window"] = BR.normalize_window(
            (window.get("width"), window.get("height")),
            window.get("percent"), window.get("fullscreen"))
        return config

    def _build_sim(self):
        config = self.config
        book = M.MoneyBook(capital=config["capital"], unit=config["bet_stake"],
                           take_profit_pct=config["take_profit_pct"])
        sim = LiveSimulation(book, unit=config["bet_stake"])
        # Khôi phục sổ vốn + lịch sử tay của phiên trước (nếu có).
        saved = getattr(self, "_saved_session", {}) or {}
        if saved.get("format") == "live-v2-engine":
            money = saved.get("money") or {}
            for key in ("balance", "hands_played", "wins", "losses", "pushes", "ties_bet",
                        "total_staked", "total_returned", "peak", "max_drawdown",
                        "loss_streak"):
                if key in money:
                    try:
                        setattr(book, key, float(money[key]))
                    except (TypeError, ValueError):
                        pass
            if isinstance(saved.get("log"), list):
                sim.log = list(saved["log"])
        return sim

    def _save_state(self):
        with self.lock:
            book = self.sim.money
            data = {
                "format": "live-v2-engine",
                "game": "baccarat",
                "settings": dict(self.config),
                "money": {key: getattr(book, key) for key in
                          ("start_capital", "balance", "hands_played", "wins", "losses",
                           "pushes", "ties_bet", "total_staked", "total_returned",
                           "peak", "max_drawdown", "loss_streak")},
                "log": self.sim.log[-500:],
            }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
            return True
        except OSError as exc:
            self.log("Không lưu được phiên (%s)." % type(exc).__name__, "error")
            return False

    # --------------------------------------------------------------- tiện ích
    def log(self, text, level="info"):
        entry = {"at": time.strftime("%H:%M:%S"), "level": level, "text": str(text)}
        self.logs.append(entry)
        try:
            self.emit.event("log", entry)
        except Exception:
            pass
        return entry

    def _busy(self):
        return (self.chrome_busy or self.scan_busy or self.sweep_busy or self.open_table_busy)

    def _busy_chrome(self):
        """Bận vì thao tác Chrome/sảnh — KHÔNG tính nhịp đọc cầu (scan) đang chạy.

        Vòng săn bàn cần đọc sảnh/mở ô bàn ngay cả khi nhịp đọc cầu 1,5–4 giây đang
        chạy nền; nếu chặn theo ``_busy()`` thì mỗi lượt săn đều bị đẩy lùi vô hạn.
        """
        return self.chrome_busy or self.sweep_busy or self.open_table_busy

    def _cdp_available(self):
        try:
            if self.browser.cdp_attached:
                return True
            if self.browser.driver is None:
                return False
            return self.browser._cdp_page() is not None
        except AttributeError:
            return False
        except Exception:
            return False

    def _auth_blame(self):
        if getattr(self.stream, "session_lost", False):
            return True
        diag = getattr(self.browser, "last_diag", None)
        if not isinstance(diag, dict):
            return False
        # root_left_site: tab bị đẩy sang trang đăng nhập/domain khác → mất phiên,
        # không phải lỗi quét tạm thời; phải dừng đặt và báo đăng nhập lại.
        return diag.get("reason") in ("authentication_required", "root_left_site")

    def _window(self):
        return self.config["chrome_window"]

    def _window_pos(self, window):
        if window.get("fullscreen"):
            return None
        return getattr(BR, "WINDOW_POSITION", (40, 40))

    def _window_text(self, window):
        return ("CHROME · toàn màn hình · tỉ lệ %d%%" % window["percent"] if window.get("fullscreen")
                else "CHROME · %d × %d · tỉ lệ %d%%" % (window["width"], window["height"],
                                                        window["percent"]))

    def _tables_target(self):
        return max(1, _as_int(self.config.get("tables_to_play"), 1))

    def _session_complete(self):
        return self.tables_done >= self._tables_target()

    # ---------------------------------------------------------------- snapshot
    def table_rows(self):
        """Danh sách bàn đọc được (không còn chấm điều kiện lọc cầu)."""
        now = time.time()
        rows = []
        # Không còn Chrome thì không có dữ liệu sống: đừng hiện bàn cũ trên UI.
        if not getattr(self.browser, "connected", False):
            return rows
        for key, row in list(self.tables.items()):
            age = now - row["ts"]
            if age > LIVE_STALE and key != self.sim.table_key:
                continue
            info = table_stats(list(row["letters"]))
            if row.get("read_error"):
                verdict = row["read_error"]
            elif row.get("table_id"):
                verdict = "Sẵn sàng vào bàn"
            else:
                verdict = "Chưa có mã bàn"
            if row.get("conflict"):
                status = "Xung đột"
            elif row.get("stable", 0) < 2:
                status = "Chờ xác nhận đọc"
            elif age > LIVE_STALE:
                status = "Dữ liệu cũ"
            else:
                status = "Mới · %ds" % int(age)
            rows.append({
                "key": key,
                "id": row.get("table_id") or key,
                "table_id": row.get("table_id", ""),
                "label": row.get("label", key),
                "letters": row.get("letters", ""),
                "hands": len(row.get("letters") or ""),
                "strong": info["strong"],
                "strong_name": E.SIDE_NAME.get(info["strong"], "—"),
                "banker": info.get("banker"),
                "player": info.get("player"),
                "lead": info.get("lead"),
                "tie_break": info.get("tie_break"),
                "tie_side": E.BANKER,
                "eligible": True,
                "ready": bool(row.get("table_id")),
                "verdict": verdict,
                "status": status,
                "read_error": row.get("read_error", ""),
                "current": key == self.sim.table_key,
            })
        rows.sort(key=lambda item: (not item["ready"], item["label"].casefold()))
        return rows

    def _resolve_order(self, params=None):
        """Resolve the explicit user-selected side; prediction output never selects a wager."""
        params = params or {}
        side = str(params.get("side", self.bet_config["side"])).strip().upper()
        stake = _as_float(params.get("stake", self.bet_config["stake"]),
                          self.bet_config["stake"])
        return {"side": side if side in ("P", "B", "T") else None,
                "stake": min(1000000.0, max(1.0, stake)),
                "reason": "Lệnh do người dùng chọn"}

    def _plan(self):
        """Current wager plan based on the explicit user choice."""
        order = self._resolve_order()
        pending = self.sim.pending
        return {
            "action": "bet" if order["side"] else "wait",
            "side": order["side"],
            "side_name": E.SIDE_NAME.get(order["side"], ""),
            "stake": order["stake"],
            "reason": order["reason"],
            "armed": pending is not None,
            "source": self.bet_config["side"],
        }

    def snapshot(self):
        with self.lock:
            book = self.sim.money
            sim = self.sim
            decisive = book.wins + book.losses
            money = {
                "capital": _finite(book.start_capital),
                "balance": _finite(book.balance),
                "profit": _finite(book.profit),
                "roi": _finite((book.profit / book.start_capital * 100)
                               if book.start_capital else 0.0),
                "wins": int(book.wins),
                "losses": int(book.losses),
                "pushes": int(book.pushes),
                "hands": int(book.hands_played),
                "drawdown": _finite(book.max_drawdown),
                "win_rate": _finite((book.wins / decisive * 100) if decisive else 0.0),
                "blocked": list(book.blocked) if book.blocked else None,
            }
            history = [{
                "time": _finite(entry.get("time")),
                "at": time.strftime("%H:%M:%S", time.localtime(_finite(entry.get("time"),
                                                                      time.time()))),
                "table": str(entry.get("table") or ""),
                "hand": int(_finite(entry.get("hand"))),
                "bet": str(entry.get("bet") or ""),
                "result": str(entry.get("result") or ""),
                "stake": _finite(entry.get("stake")),
                "delta": _finite(entry.get("delta")),
                "outcome": str(entry.get("outcome") or ""),
                "balance_after": _finite(entry.get("balance_after")),
            } for entry in sim.log[-200:]]
            plan = self._plan()
            chip_check = self.chip_check() if self.sim.table_key else None
            now = time.time()
            return {
                "game": "baccarat",
                "chrome_connected": bool(getattr(self.browser, "connected", False)),
                "chrome_mode": getattr(self.browser, "mode", ""),
                "chrome_note": (getattr(self.browser, "note", "") or self.connection_text),
                "driver_info": getattr(self.browser, "driver_info", "Chưa kết nối Chrome."),
                "cdp_ready": self._cdp_available(),
                "tool_running": self.tool_running,
                "session_lost": self.session_lost,
                "busy": {
                    "chrome": self.chrome_busy, "scan": self.scan_busy,
                    "sweep": self.sweep_busy, "open_table": self.open_table_busy,
                    "place": self.place_busy, "chip": self.chip_busy,
                },
                "sweep_note": self.sweep_note,
                "wallet_text": self.wallet_text,
                "cycle": {
                    "waiting": bool(self.cycle_waiting),
                    "attempts": self.cycle_attempts,
                    "retry_in": max(0.0, (self.cycle_retry_at or 0) - now),
                },
                "tables_done": self.tables_done,
                "tables_target": self._tables_target(),
                "enter_valid": {
                    "active": bool(self.enter_valid),
                    "checked": bool(self.valid_check_done),
                    "note": getattr(self, "valid_note", ""),
                    "attempts": int(self.enter_attempts),
                    "remain": max(0.0, (self.enter_deadline or 0) - now) if self.enter_valid else 0.0,
                },
                "table": {
                    "key": sim.table_key,
                    "name": sim.table_name,
                    "letters": sim.letters,
                    "hands": len(sim.letters or ""),
                    "hand": max(len(sim.letters or ""),
                                int(getattr(self, "live_hand", 0) or 0)),
                    "running": sim.running,
                    "entry_waiting": sim.entry_waiting,
                    "note": sim.note,
                    "place_skips": sim.place_skips,
                    "take_profit_done": bool(sim.take_profit_done),
                    "auto_note": self.auto_bet_note,
                },
                "plan": plan,
                "bet": {
                    "side": self.bet_config["side"],
                    "stake": _finite(self.bet_config["stake"]),
                    "pending": dict(sim.pending) if sim.pending else None,
                },
                "money": money,
                "chips": {
                    "live": self.chip_live,
                    "check": chip_check,
                    "at": self.chip_read_at,
                },
                "place": dict(self.place_status),
                "tables": self.table_rows(),
                "live": self.live_snapshot(),
                "config": json.loads(json.dumps(self.config)),
                "history": history,
                "log_tail": list(sim.log[-15:]),
            }

    def _push_state(self):
        state = self.snapshot()
        try:
            self.emit.event("state", state)
        except Exception:
            pass
        return state

    # ----------------------------------------------------------------- Chrome
    def chrome_open(self):
        if self.browser.connected:
            return {"ok": True, "note": "Chrome đã kết nối."}
        if self.chrome_busy:
            return {"ok": False, "error": "Đang mở Chrome, chờ một chút."}
        self.chrome_busy = True
        self.connection_text = "Đang mở Chrome / gắn CDP 9222…"
        window = self._window()
        pos = self._window_pos(window)

        def work():
            try:
                attached = self.browser.attach()
                if not attached and self.browser.last_diag.get("reason") == "evo_entry_auth_error":
                    self.events.put(("open_error", self.browser.note))
                    return
                if attached and getattr(self, "_pending_site_navigation", None):
                    ok, note = self.browser.navigate(self._pending_site_navigation)
                    self._pending_site_navigation = None
                    if not ok:
                        self.events.put(("open_error", note))
                        return
                if not attached:
                    ok = self.browser.start(self.config["start_url"], pos=pos, cdp=True,
                                            window=window)
                    if not ok:
                        self.events.put(("open_error", self.browser.last_error or "Không mở được Chrome."))
                        return
                    self.browser.wait_for_cdp()
                    self._pending_site_navigation = None
                try:
                    self.browser.resize_window(window, pos=pos)
                except Exception:
                    pass
                self.events.put(("opened", "%s · Website đã mở."
                                 % self.browser.driver_info))
            except Exception as exc:
                self.events.put(("open_error", "Không mở được Chrome (%s)." % type(exc).__name__))

        threading.Thread(target=work, daemon=True, name="ba-chrome").start()
        self._push_state()
        return {"ok": True, "note": "Đang mở Chrome…"}

    def site_open(self, params):
        url = str((params or {}).get("url") or "").strip()
        if not BR.valid_site_url(url):
            return {"ok": False, "error": "URL site không hợp lệ; chỉ hỗ trợ HTTPS công khai."}
        self.config["start_url"] = url
        self._save_state()
        if self.browser.connected:
            ok, note = self.browser.navigate(url)
            if not ok:
                return {"ok": False, "error": note}
            self.connection_text = note
            self._push_state()
            return {"ok": True, "note": note}
        self._pending_site_navigation = url
        return self.chrome_open()

    def profile_configure(self, params):
        """Apply ephemeral proxy and per-profile window settings before launching Chrome."""
        params = params or {}
        if params.get("close"):
            self.tool_running = False
            try:
                self.live_stop()
            except Exception:
                pass
            try:
                self.browser.stop()
            except Exception as exc:
                return {"ok": False, "error": "Không đóng được Chrome profile (%s)." % type(exc).__name__}
            self._push_state()
            return {"ok": True, "note": "Đã đóng profile."}

        url = str(params.get("url") or self.config.get("start_url") or "").strip()
        if not BR.valid_site_url(url):
            return {"ok": False, "error": "URL website không hợp lệ."}
        proxy_server = str(params.get("proxy_server") or "").strip()
        if proxy_server:
            try:
                from urllib.parse import urlsplit
                parsed = urlsplit(proxy_server)
                if (parsed.scheme not in ("http", "https", "socks4", "socks5") or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None
                        or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                    raise ValueError("invalid_proxy")
                parsed.port  # Force validation of malformed ports.
            except (TypeError, ValueError):
                return {"ok": False, "error": "Proxy profile không hợp lệ."}

        self.tool_running = False
        try:
            self.live_stop()
        except Exception:
            pass
        try:
            self.browser.stop()
        except Exception as exc:
            return {"ok": False, "error": "Không đóng được Chrome profile (%s)." % type(exc).__name__}

        width = min(3840, max(520, _as_int(params.get("width"), 900)))
        height = min(2160, max(200, _as_int(params.get("height"), 500)))
        percent = min(200, max(50, _as_int(params.get("scale"), 100)))
        left = max(0, _as_int(params.get("left"), 0))
        top = max(0, _as_int(params.get("top"), 0))
        BR.WINDOW_POSITION = (left, top)
        BR.PROXY_SERVER = proxy_server
        self.config["start_url"] = url
        self.config["chrome_window"] = {"width": width, "height": height,
                                        "percent": percent, "fullscreen": False}
        self._save_state()
        self._push_state()
        return {"ok": True, "note": "Đã áp dụng cấu hình profile.",
                "proxy_enabled": bool(proxy_server), "width": width,
                "height": height, "scale": percent}

    def febet_open_dg(self, _params=None):
        deadline = time.monotonic() + 60
        while self.browser.driver is None and self.chrome_busy and time.monotonic() < deadline:
            time.sleep(0.2)
        with self.browser.lock:
            return FEBET.open_dream_gaming_baccarat(self.browser.driver)

    def febet_current_table(self, _params=None):
        with self.browser.lock:
            return FEBET.current_table(self.browser.driver)

    def febet_lobby_tables(self, _params=None):
        with self.browser.lock:
            return FEBET.lobby_tables(self.browser.driver)

    def febet_sync_table(self, params):
        with self.browser.lock:
            return FEBET.sync_table(self.browser.driver, (params or {}).get("table_id"))

    def chrome_attach(self):
        if self.chrome_busy:
            return {"ok": False, "error": "Đang bận thao tác Chrome."}
        self.chrome_busy = True

        def work():
            try:
                ok = self.browser.attach()
                if ok:
                    try:
                        self.browser.resize_window(self._window(), pos=self._window_pos(self._window()))
                    except Exception:
                        pass
                self.events.put(("opened" if ok else "open_error",
                                 self.browser.note or "Không gắn được Chrome."))
            except Exception as exc:
                self.events.put(("open_error", "Không gắn được Chrome (%s)." % type(exc).__name__))

        threading.Thread(target=work, daemon=True, name="ba-attach").start()
        self._push_state()
        return {"ok": True, "note": "Đang gắn Chrome…"}

    def chrome_close(self):
        self.tool_running = False
        with self.lock:
            self.sim.pause("Đã ngắt kết nối Chrome.")
        self.chrome_busy = True

        def work():
            try:
                self.browser.stop()
            finally:
                self.events.put(("stopped", "Đã ngắt kết nối Chrome."))

        threading.Thread(target=work, daemon=True, name="ba-stop").start()
        self._push_state()
        return {"ok": True, "note": "Đang ngắt kết nối…"}

    def apply_window(self, params):
        if params.get("left") is not None and params.get("top") is not None:
            try:
                BR.WINDOW_POSITION = (int(params["left"]), int(params["top"]))
            except (TypeError, ValueError):
                pass
        window = BR.normalize_window(
            (params.get("width", self._window()["width"]),
             params.get("height", self._window()["height"])),
            params.get("percent", self._window()["percent"]),
            params.get("fullscreen", self._window()["fullscreen"]))
        if params.get("tile"):
            window["width"] = min(7680, max(520, _as_int(params.get("width"), window["width"])))
            window["height"] = min(4320, max(200, _as_int(params.get("height"), window["height"])))
        self.config["chrome_window"] = window
        self._save_state()
        if not self.browser.connected:
            self.sweep_note = "Đã lưu cửa sổ Chrome (%s). Mở Chrome là áp dụng ngay." % \
                              self._window_text(window)
            self._push_state()
            return {"ok": True, "note": self.sweep_note}
        self.chrome_busy = True

        def work():
            try:
                ok, note = self.browser.resize_window(window, pos=self._window_pos(window))
                self.events.put(("window_applied", (ok, note or self._window_text(window))))
            except Exception as exc:
                self.events.put(("window_applied", (False, "Không đổi được cửa sổ (%s)."
                                                  % type(exc).__name__)))

        threading.Thread(target=work, daemon=True, name="ba-window").start()
        return {"ok": True, "note": "Đang áp dụng cửa sổ Chrome…"}

    # ------------------------------------------------------------------ sảnh
    def lobby_enter(self):
        if self.sweep_busy or self.chrome_busy:
            return {"ok": False, "error": "Đang bận thao tác sảnh."}
        if not self._cdp_available():
            self.sweep_note = "Chưa bật CDP: mở trang Baccarat trong Chrome rồi bấm “VÀO BÀN HỢP LỆ”."
            self._push_state()
            return {"ok": False, "error": self.sweep_note}
        self.sweep_busy = True
        self.session_lost = False
        self.recover_attempts = 0
        self.sweep_note = "Đang tìm tab sảnh Baccarat bạn đã tự mở…"

        def work():
            try:
                ok, note = self.stream.find_lobby_tab()
                self.events.put(("lobby_entered", (ok, note)))
            except Exception as exc:
                self.events.put(("lobby_entered", (False, "Không nhận được tab sảnh (%s)."
                                                  % type(exc).__name__)))

        threading.Thread(target=work, daemon=True, name="ba-lobby").start()
        self._push_state()
        return {"ok": True, "note": self.sweep_note}

    def lobby_sweep(self, params=None):
        params = params or {}
        if self.sweep_busy or self.chrome_busy:
            return {"ok": False, "error": "Đang bận thao tác sảnh."}
        if not self._cdp_available():
            self.sweep_note = "Bấm “VÀO BÀN HỢP LỆ” khi Chrome đã mở sảnh Baccarat."
            self._push_state()
            return {"ok": False, "error": self.sweep_note}
        favorites = params.get("favorites_only")
        favorites = self.config["favorites_only"] if favorites is None else bool(favorites)
        self.config["favorites_only"] = favorites
        self.sweep_busy = True
        self.sweep_note = ("Đang quét sảnh · chỉ bàn Ưa thích…" if favorites else "Đang quét sảnh…")

        def work():
            try:
                rows = self.stream.sweep(favorites_only=favorites)
                self.events.put(("sweep", (rows, self.stream.last_error, time.time())))
            except Exception as exc:
                self.events.put(("sweep", ([], "Quét sảnh lỗi (%s)." % type(exc).__name__, time.time())))

        threading.Thread(target=work, daemon=True, name="ba-sweep").start()
        self._push_state()
        return {"ok": True, "note": self.sweep_note}

    def lobby_back(self):
        if self._busy():
            return {"ok": False, "error": "Đang bận, chờ một chút."}
        if not self._cdp_available():
            return {"ok": False, "error": "Chưa gắn Chrome CDP."}
        self.sweep_busy = True

        def work():
            try:
                self.events.put(("cycle_back", self.stream.back_to_lobby()))
            except Exception as exc:
                self.events.put(("cycle_back", (False, "Không về được sảnh (%s)."
                                                % type(exc).__name__)))

        threading.Thread(target=work, daemon=True, name="ba-back").start()
        self._push_state()
        return {"ok": True, "note": "Đang rời bàn…"}

    # ------------------------------------------------------------------- bàn
    def open_table(self, key):
        """Mở bàn từ sảnh (bấm đúng ô bàn) rồi chờ xác nhận cầu trước khi theo dõi."""
        if self.open_table_busy or self.sweep_busy:
            return {"ok": False, "error": "Đang bận, chờ một chút."}
        row = self.tables.get(key)
        if not row:
            return {"ok": False, "error": "Không tìm thấy bàn trong danh sách đã quét."}
        if not row.get("table_id"):
            return {"ok": False, "error": "Bàn chưa có mã bàn nên không mở được từ sảnh."}
        self.open_table_busy = True
        self.sweep_note = "Đang mở %s…" % row["label"]

        def work():
            try:
                ok, note = self.stream.open_table(row["table_id"])
                self.events.put(("table_opened", (ok, note, key)))
            except Exception as exc:
                self.events.put(("table_opened", (False, "Không mở được bàn (%s)."
                                                  % type(exc).__name__, key)))

        threading.Thread(target=work, daemon=True, name="ba-open-table").start()
        self._push_state()
        return {"ok": True, "note": self.sweep_note}

    def select_table(self, key):
        """Theo dõi ngay bàn đã đọc được (không cần mở tab bàn)."""
        row = self.tables.get(key)
        if not row:
            return {"ok": False, "error": "Không tìm thấy bàn trong danh sách đã quét."}
        with self.lock:
            self.sim.bind(row)
            started = self.sim.start(row)
            note = self.sim.note
        self.chip_live = None
        self.chip_read_at = 0.0
        self.last_order = None
        self._save_state()
        self.log(("Bắt đầu theo dõi %s · %s" % (row["label"], note)) if started
                 else ("Chưa theo dõi được %s · %s" % (row["label"], note)),
                 "info" if started else "error")
        self._push_state()
        return {"ok": True, "note": note, "started": bool(started)}

    def enter_valid_table(self):
        """Nút duy nhất “VÀO BÀN HỢP LỆ”.

        Gắn Chrome → nhận tab sảnh → quét sảnh → mở bàn đầu tiên có mã → đọc cầu trong
        bàn rồi **đứng chờ, chưa đặt cược**.
        Chỉ khi tool đang chạy thì sau bước xác nhận mới arm và cược như cũ.
        """
        if self._busy_chrome() or self.open_table_busy:
            return {"ok": False, "error": "Đang bận thao tác Chrome/sảnh, chờ một chút."}
        if self.sim.running:
            return {"ok": False, "error": "Đang chạy phiên trong bàn. Dừng tool trước khi "
                                          "vào bàn hợp lệ khác."}
        self.enter_valid = True
        self.valid_check_done = False
        self.valid_note = "Đang tìm bàn hợp lệ…"
        self.enter_attempts = 0
        self.enter_deadline = time.time() + ENTER_VALID_TIMEOUT
        self.cycle_waiting = True
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None
        self.sweep_note = self.valid_note

        def work():
            try:
                if not self.browser.connected:
                    attached = self.browser.attach()
                    if not attached:
                        window = self._window()
                        pos = self._window_pos(window)
                        if not self.browser.start(self.config["start_url"], pos=pos, cdp=True,
                                                  window=window):
                            self.events.put(("valid_fail", self.browser.last_error
                                             or "Không mở/gắn được Chrome CDP 9222."))
                            return
                        self.browser.wait_for_cdp()
                        try:
                            self.browser.resize_window(window, pos=pos)
                        except Exception:
                            pass
                        # Chrome vừa mở: người dùng còn phải đăng nhập + mở EVO. Không
                        # tự bấm sảnh; báo rõ để họ làm rồi bấm lại nút.
                        self.events.put(("valid_fail", "Đã mở Chrome · hãy đăng nhập và mở "
                                                       "sảnh Baccarat rồi bấm “VÀO BÀN HỢP LỆ” lần nữa."))
                        return
                # Đang đứng sẵn trong bàn WM (vd. mở lại app khi tab vẫn ở bàn): theo
                # bàn đó luôn. Quét sảnh lúc này sẽ hỏng vì iframe sảnh đã bị ẩn.
                try:
                    wm_page, _detect = find_wm_table(getattr(BR, "CDP_PORT", 9222))
                except Exception:
                    wm_page = None
                if wm_page is not None:
                    self.scan()
                    open_key = getattr(self.browser, "wm_open_key", "") or ""
                    key = "id:" + open_key if open_key else ""
                    if key:
                        row = self.tables.get(key)
                        if row is None:
                            row = {"key": key, "label": "WM " + open_key, "letters": "",
                                   "table_id": open_key, "game_type": "baccarat",
                                   "read_error": "", "conflict": False, "source": "live-ws",
                                   "ts": time.time(), "stable": 2}
                            self.tables[key] = row
                        if not row.get("letters"):
                            # Cầu có thể chưa về (mới gắn WS giữa shoe): lấy từ bộ đọc
                            # live nếu đã có, không thì để trống rồi để live đồng bộ sau.
                            live = (self.live_snapshot()
                                    if self.live_session is not None else {})
                            live_table = str(live.get("table") or "").replace("WM ", "").strip()
                            if live.get("running") and live_table == open_key \
                                    and live.get("history"):
                                row["letters"] = live["history"]
                                row["ts"] = time.time()
                        self.events.put(("table_opened", (
                            True, "Đang ở trong bàn %s · theo dõi tiếp." % row["label"], key)))
                        return
                ok, note = self.stream.find_lobby_tab()
                if not ok:
                    self.events.put(("valid_fail", note))
                    return
                # Đang ở SẢNH WM: tải lại tab một lần ngay tại đây để hook bắt được
                # WebSocket (lệnh cược sau đó đi thẳng qua WS, không cần tải lại nữa và
                # không đụng tới bàn đang đứng). Trong bàn thì tuyệt đối không tải lại.
                if getattr(self.stream, "lobby_kind", "") == "wm" and "màn hình bàn" not in note:
                    self._wm_warm_socket_lobby()
                self.events.put(("valid_lobby", (True, note)))
            except Exception as exc:
                self.events.put(("valid_fail", "Không vào được sảnh (%s)." % type(exc).__name__))

        threading.Thread(target=work, daemon=True, name="ba-enter-valid").start()
        self._push_state()
        return {"ok": True, "note": self.valid_note}


    def _wm_warm_socket_lobby(self):
        """Đang ở sảnh WM: cài hook WebSocket sẵn cho lần vào bàn (KHÔNG tải lại tab).

        ``Page.addScriptToEvaluateOnNewDocument`` áp cho iframe bàn được tạo khi mở bàn,
        nên chỉ cần cài hook là đủ — không reload, không làm Chrome nhảy trang.
        """
        from aibcr.adapters.wm_ws import get_socket

        socket = get_socket(self.browser, start=False, reload_on_start=False,
                            on_status=lambda text, level="info": self.log(text, level))
        if not socket.is_alive():
            socket.start()
        self.log("WM: đã cài hook WebSocket · cược sẽ đi qua WS khi bàn mở cược.")

    def leave_table(self, take_profit=False):
        """Rời bàn hiện tại về sảnh; take_profit=True nghĩa là đã chốt lời."""
        take_profit = bool(take_profit or getattr(self.sim, "take_profit_done", False))
        if not take_profit and not self.tool_running:
            return {"ok": False, "error": "Chưa chốt lời và tool chưa chạy nên không tự rời bàn."}
        self.cycle_waiting = True
        self.cycle_attempts = 0
        self.cycle_table_key = self.sim.table_key
        self.cycle_retry_at = 0.0
        with self.lock:
            self.sim.pause("Đang rời bàn…")
        return self.lobby_back()

    # ------------------------------------------------------------------ tool
    def tool_start(self):
        """Một nút duy nhất: tự vào bàn + theo dõi + tự đặt cược từng tay.

        Người dùng chỉ cần Chrome đang mở ở sảnh; mọi bước còn lại (gắn Chrome, quét
        sảnh, mở bàn, đọc cầu, chốt lệnh, bấm chip) do tool tự làm và lặp lại mỗi tay
        cho tới khi bấm “Dừng tool”.
        """
        if self.tool_running:
            return {"ok": True, "note": "Tool đang chạy."}
        self.tool_running = True
        self.next_scan = 0.0
        self.session_lost = False
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = ""
        # Đang đứng ở bàn đã xác nhận: theo dõi tiếp ngay, không quét lại sảnh.
        if self.sim.table_key:
            row = self.tables.get(self.sim.table_key)
            if row:
                with self.lock:
                    self.sim.start(row)
                self.valid_check_done = False
                self.valid_note = "Tool đang chạy · " + self.sim.note
        self.log("Chạy tool: tự vào bàn, phân tích và đặt cược từng tay.")
        self._push_state()
        # Tự bật bộ đọc lá bài để có dự đoán ngay — người dùng không phải bấm thêm nút.
        if self.live_reader is None:
            try:
                self.live_start()
            except Exception as exc:
                self.log("Không bật được AI live (%s)." % type(exc).__name__, "warn")
        # Chưa có bàn: tự gắn/mở Chrome rồi tìm bàn hợp lệ (không cần bấm thêm nút nào).
        self.tool_retry_at = time.time() + 15.0
        if not self.sim.table_key and not self.enter_valid:
            self.enter_valid_table()
        if getattr(self.browser, "wm_page_id", None):
            threading.Thread(target=self._wm_prepare_socket, daemon=True,
                             name="ba-wm-socket").start()
        return {"ok": True, "note": "Tool đang chạy · đang tự vào bàn và đặt cược."}

    def _wm_prepare_socket(self):
        """Cài hook WebSocket của WM — **không bao giờ tải lại tab**.

        Tải lại tab sẽ đẩy Chrome về sảnh và làm mất bàn đang đứng, nên hook chỉ được cài
        sẵn; nếu chưa bắt được socket thì cược đi bằng đường bấm chip (đọc lại số tiền sau
        từng chip nên vẫn đúng). Không có trường hợp nào tự đổi trang.
        """
        from aibcr.adapters.wm_ws import get_socket

        socket = get_socket(self.browser, start=False, reload_on_start=False,
                            on_status=lambda text, level="info": self.log(text, level))
        if not socket.is_alive():
            socket.start()
        if socket.ready():
            self.log("WM: socket sẵn sàng · đặt cược gửi thẳng qua WebSocket.", "win")
        else:
            self.log("WM: đặt cược bằng bấm chip (WebSocket sẽ dùng khi bàn mở lại).", "info")

    def tool_stop(self):
        """Dừng tool và rời bàn về sảnh (đúng như quy tắc một nút)."""
        self.tool_running = False
        self.cycle_waiting = False
        self.cycle_retry_at = 0.0
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = ""
        self.last_order = None
        self.tool_retry_at = 0.0
        if self.enter_valid:
            self.enter_valid = False
            self.valid_note = "Đã dừng tool · huỷ tìm bàn hợp lệ."
        in_table = bool(self.sim.table_key) or bool(self.valid_check_done)
        with self.lock:
            if self.sim.running:
                self.sim.pause("Đã dừng tool.")
        self.log("Đã dừng tool Baccarat." + (" Đang rời bàn về sảnh." if in_table else ""))
        self._push_state()
        if in_table:
            def back():
                try:
                    ok, note = self.stream.back_to_lobby()
                    self.sweep_note = note
                    self.connection_text = note
                    self.log(note, "info" if ok else "warn")
                except Exception as exc:
                    self.log("Không rời bàn được (%s)." % type(exc).__name__, "warn")
                with self.lock:
                    self.sim.detach("Đã dừng tool · đang ở sảnh.")
                self.valid_check_done = False
                self._push_state()

            threading.Thread(target=back, daemon=True, name="ba-back-lobby").start()
        return {"ok": True, "note": "Đã dừng tool · đang về sảnh."}

    # -------------------------------------------------------------- đọc chip
    def chip_check(self):
        pending = self.sim.pending
        if pending is not None:
            order = {"side": pending.get("side"), "stake": pending.get("stake")}
        elif self.last_order is not None:
            # Chưa chốt lệnh tay kế: chip còn trên bàn là của lệnh vừa đặt, so với lệnh
            # mới sẽ báo "SAI CỬA" dù người dùng vừa đặt đúng.
            order = self.last_order
        else:
            order = self._resolve_order()
        unit = (self.chip_live or {}).get("unit") or TB.DEFAULT_CHIP_UNIT
        try:
            return compare_chips(order.get("side"), order.get("stake") or 0,
                                 self.chip_live, unit=unit)
        except Exception:
            return None

    def scan(self):
        """Quét bàn một lần (đồng bộ) rồi trả snapshot — dùng cho CLI/test."""
        try:
            reports = self.browser.scan() or []
        except Exception as exc:
            self.log("Quét bàn lỗi: %s" % type(exc).__name__, "error")
            return self.snapshot()
        rows = []
        for report in reports:
            for table in (report.get("tables") or []):
                rows.append(table)
        self._ingest(rows)
        with self.lock:
            if self.sim.table_key:
                self.sim.process(self.tables.get(self.sim.table_key))
        return self.snapshot()

    def scan_now(self):
        """Đọc lại cầu bàn ngay (nút “Đọc lại”)."""
        if not self.browser.connected:
            return {"ok": False, "error": "Hãy mở Chrome trước khi đọc dữ liệu."}
        if self.scan_busy:
            return {"ok": False, "error": "Đang đọc bàn, chờ một chút."}
        self.next_scan = 0.0
        self._scan()
        return {"ok": True, "note": "Đang đọc lại cầu bàn…"}

    def chips_read(self):
        if self.chip_busy:
            return {"ok": False, "error": "Đang đọc chip."}
        if not self.browser.connected or not self.sim.table_key:
            return {"ok": False, "error": "Chưa ở trong bàn để đọc chip."}
        self.chip_busy = True

        def work():
            self.events.put(("chips", self._read_chip_state()))

        threading.Thread(target=work, daemon=True, name="ba-chips").start()
        return {"ok": True, "note": "Đang đọc chip…"}

    def _read_chip_state(self):
        if getattr(self.browser, "wm_page_id", None):
            # WM: đọc chip của CHÍNH MÌNH đang treo trên từng cửa (mybet_money).
            return WMBet(self.browser).read_bets()
        try:
            return TB.read(self.browser, unit=TB.DEFAULT_CHIP_UNIT)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

    # ------------------------------------------------------- đặt chip tự động
    def _tool_retry_enter(self, now):
        """Tool đang chạy nhưng chưa có bàn: tự thử vào bàn lại.

        Xảy ra khi Chrome vừa mở (người dùng còn đăng nhập) hoặc tab bị đóng/mất sảnh:
        không cần bấm thêm nút nào, tool tự thử lại mỗi 15 giây.
        """
        if not self.tool_running or self.sim.table_key or self.enter_valid:
            return
        if self.open_table_busy or self.sweep_busy or self.chrome_busy:
            return
        if now < self.tool_retry_at:
            return
        self.tool_retry_at = now + 15.0
        self.enter_valid_table()

    def _live_bound(self, live=None):
        """Bộ đọc live đang bám đúng bàn theo dõi (không phải bàn vừa rời).

        Sau khi mở bàn mới, ``WMReader`` chuyển bàn trong vài giây; trước đó snapshot
        vẫn là cầu/số tay của bàn cũ, không được dùng để chốt lệnh cho bàn mới.
        """
        if not isinstance(live, dict):
            if self.live_session is None:
                return False
            try:
                live = self.live_snapshot()
            except Exception:
                return False
        if not live.get("running"):
            return False
        key = str(self.sim.table_key or "")
        table = str(live.get("table") or "").replace("WM ", "").strip()
        if not key or not table:
            return False
        return key == table or key.endswith(table) or table.endswith(key)

    def _auto_bet_tick(self):
        """Place the explicitly selected side once per hand while the tool is running."""
        if not self.tool_running:
            return
        if not self.sim.running:
            # Sim bị pause (dữ liệu cũ / không đặt được chip): hiện đúng lý do pause,
            # không để ghi chú "chờ WebSocket" cũ treo trên UI gây hiểu lầm.
            if self.sim.table_key and self.sim.note:
                self.auto_bet_note = self.sim.note
            return
        if not self.config["auto_place"]:
            return
        if self.place_busy or self.sim.pending or self.sim.entry_waiting:
            return
        if not self.sim.table_key:
            return
        # Chưa bám đúng bàn (vừa mở bàn khác): chờ WebSocket nạp cầu bàn mới thay vì
        # đặt theo số tay/xác suất của bàn vừa rời.
        live = {}
        if self.live_session is not None:
            try:
                live = self.live_snapshot()
            except Exception:
                live = {}
        if not self._live_bound(live):
            live_table = str(live.get("table") or "").replace("WM ", "").strip()
            note = ("Đang chờ dữ liệu bàn mới từ WebSocket · chưa đặt tay nào."
                    if live_table else
                    "Chưa thấy bàn WM trong Chrome (có thể mất đăng nhập) · chưa đặt tay nào.")
            if note != self.auto_bet_note:
                self.auto_bet_note = note
                self.log(note, "info")
            return
        letters = self.sim.letters
        if letters == self.auto_bet_letters and self.sim.table_key == self.auto_bet_key:
            return
        # Số tay thật của lệnh sắp đặt (không dùng len(cầu): cầu đã bị cắt bớt khi
        # shoe dài hơn giới hạn lưu lịch sử).
        hand_no = self._next_hand_no(len(letters) + 1, live)
        # Số tay phải tăng dần trong một bàn: bản phát lại/lịch sử về muộn không được
        # arm lệnh cho tay cũ hơn tay đã chốt (tránh đặt trùng hai lệnh một cửa sổ cược).
        if self.sim.table_key == self.auto_bet_key and self.auto_bet_hand \
                and hand_no <= self.auto_bet_hand:
            self.auto_bet_letters = letters
            self.auto_bet_note = "Tay này đã được xử lý · chờ tay kế."
            return
        # Chốt an toàn chống đặt trùng: nếu sổ đã có tay này cho cùng bàn thì không đặt lại
        # (bảo vệ khi nguồn dữ liệu phát lại cùng một ván).
        signature = (self.sim.table_key, hand_no)
        if signature in self.placed_signatures:
            self.auto_bet_letters = letters
            self.auto_bet_key = self.sim.table_key
            self.auto_bet_hand = max(self.auto_bet_hand, hand_no)
            self.auto_bet_note = "Tay này đã được xử lý · chờ tay kế."
            return
        order = self._resolve_order()
        side = order.get("side")
        if not side:
            # Chưa có xác suất (dự đoán đang chạy/nạp lịch sử): KHÔNG khoá tay này,
            # tick sau thử lại ngay khi predict xong — nhờ vậy tay đầu tiên sau khi
            # nạp cầu cũ vẫn được đặt trong cửa sổ cược hiện tại.
            note = "Chua chon duoc cua; will retry on the next tick."
            if note != self.auto_bet_note:
                self.auto_bet_note = note
                self.log(note, "info")
            return
        pending = self.sim.set_order(side, order["stake"], reason=order["reason"])
        if pending is None:
            return
        self.last_order = {"side": side, "stake": order["stake"]}
        self.placed_signatures.add(signature)
        if len(self.placed_signatures) > 500:
            self.placed_signatures = set(list(self.placed_signatures)[-200:])
        self.auto_bet_letters = letters
        self.auto_bet_key = self.sim.table_key
        self.auto_bet_hand = hand_no
        self.auto_bet_note = "Tự đặt tay %d · %s %s đv · %s" % (
            hand_no, E.SIDE_NAME.get(side, side),
            M.fmt_money(order["stake"]), order["reason"])
        self.log(self.auto_bet_note, "info")
        self._place_armed_bet(pending)

    def _next_hand_no(self, fallback, live=None):
        """Số tay của lệnh sắp đặt, lấy từ bộ đọc live (số tay thật của bàn).

        Kết quả ván vừa rồi có ``result_hand``; nếu 21/38 đã báo vòng đang mở cược
        (BETTING) thì chính vòng đó mới là tay sẽ nhận kết quả.
        """
        if not isinstance(live, dict):
            live = {}
            if self.live_session is not None:
                try:
                    live = self.live_snapshot()
                except Exception:
                    live = {}
        result_hand = int(live.get("result_hand") or 0)
        state = str(live.get("state") or "")
        betting = int(live.get("hand") or 0)
        if state == "BETTING" and betting > result_hand:
            return betting
        if result_hand:
            return result_hand + 1
        if betting:
            return betting + 1
        return fallback

    def _place_armed_bet(self, plan):
        """Đặt chip thật theo lệnh đã chốt (chạy ở thread nền)."""
        if not self.config["auto_place"]:
            with self.lock:
                self.sim.mark_placing(plan)
                self.sim.mark_placed(False, "Chưa đặt: bật “Tự đặt chip” để chỉ tính tay đã được xác nhận.",
                                     plan)
            self.place_status = {"ok": False, "note": "Tay chưa đặt: đang tắt tự đặt chip."}
            return
        side, stake = plan.get("side"), float(plan.get("stake") or 0)
        with self.lock:
            self.sim.mark_placing(plan)
        if not side or stake <= 0:
            with self.lock:
                self.sim.mark_placed(False, "Chưa đặt: lệnh cược không hợp lệ.", plan)
            return
        if self.place_busy:
            with self.lock:
                self.sim.mark_placed(False, "Lượt bấm chip trước chưa xong nên tay này chưa được bấm.",
                                     plan)
            return
        self.place_busy = True
        # WM in tiền theo nghìn đồng trên khay chip (10 = 10.000đ); EVO in theo VN2.
        unit_name = ("đv (1 đv = 1.000đ)" if getattr(self.browser, "wm_page_id", None)
                     else "VN2")
        self.place_status = {"ok": None,
                            "note": "Đang tự đặt %s %s vào %s…" % (M.fmt_money(stake), unit_name,
                                                                   E.SIDE_NAME.get(side, side))}

        def work():
            try:
                ok_gate, gate_note = self._wait_for_next_hand()
                if not ok_gate:
                    self.events.put(("placed", (False, gate_note, plan)))
                    return
                row_letters = (self.tables.get(self.sim.table_key) or {}).get("letters")
                if row_letters and row_letters != plan.get("baseline"):
                    self.events.put(("placed", (False, "Kết quả tay này đã về trước khi bấm chip; "
                                                       "không bấm sang cửa sổ tay sau.", plan)))
                    return

                if getattr(self.browser, "wm_page_id", None):
                    # Bàn WM: chip treo lên ô trước, đọc lại số tiền, đủ mới bấm xác nhận
                    # — cùng nguyên tắc an toàn của bản LONG-LONG (không đặt thiếu/lệch).
                    result = WMBet(self.browser).place(side, stake, confirm=True,
                                                       wait_seconds=BET_GATE_TIMEOUT)
                    plan["placed_at"] = time.time()
                    note = result.get("note") or result.get("error") or ""
                    self.events.put(("placed", (bool(result.get("ok")), note, plan)))
                    return

                def record_click():
                    plan["placed_at"] = time.time()

                ok, note, _placed = TB.place_bet(
                    self.browser, side, [], unit=TB.DEFAULT_CHIP_UNIT,
                    human_mouse=self.config["human_mouse"], amount=stake,
                    on_bet_click=record_click)
                self.events.put(("placed", (ok, note, plan)))
            except Exception as exc:
                self.events.put(("placed", (False, "Lỗi khi tự đặt chip (%s)." % type(exc).__name__,
                                            plan)))

        threading.Thread(target=work, daemon=True, name="ba-place").start()

    def _wait_for_next_hand(self, timeout=BET_GATE_TIMEOUT, poll=BET_GATE_POLL):
        """Chờ bàn gom hết chip ván trước rồi mới bấm (tránh bấm chồng ván cũ)."""
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if not self.tool_running:
                return False, "Tool đã dừng, huỷ tự đặt chip."
            live = self._read_chip_state()
            if table_is_clear(live):
                return True, ""
            last_error = "" if (live or {}).get("ok") else ((live or {}).get("error") or "no_read")
            time.sleep(poll)
        if last_error:
            return False, ("Không tự đặt: sau %ds vẫn không đọc được bàn (%s) nên chưa bấm chip."
                           % (int(timeout), last_error))
        return False, ("Không tự đặt: sau %ds bàn vẫn còn chip ván trước, chưa chắc đang ở lượt "
                       "đặt cược mới." % int(timeout))

    # ------------------------------------------------------------- cấu hình
    def config_set(self, params):
        params = params or {}
        changed = []
        with self.lock:
            config = dict(self.config)
            for key in ("favorites_only", "human_mouse", "auto_place",
                        "auto_hunt", "auto_recover"):
                if key in params:
                    config[key] = bool(params[key])
                    changed.append(key)
            for key in ("bet_side", "bet_stake"):
                if key in params:
                    config[key] = params[key]
                    changed.append(key)
            if "tables_to_play" in params:
                config["tables_to_play"] = params["tables_to_play"]
                changed.append("tables_to_play")
            if "start_url" in params:
                config["start_url"] = params["start_url"]
                changed.append("start_url")
            for key in ("ai_mode", "ai_url", "ai_model"):
                if key in params:
                    config[key] = params[key]
                    changed.append(key)
            for key in ("ai_every", "ai_timeout", "live_decks", "live_trials",
                        "live_markov_weight"):
                if key in params:
                    config[key] = params[key]
                    changed.append(key)

            normalized = self._normalize_config(config)
            # đổi vốn / chốt lời chỉ khi chưa có tay nào, tránh làm sai lãi/lỗ
            for key in ("capital", "take_profit_pct"):
                if key in params:
                    value = _as_float(params[key], normalized[key])
                    if self.sim.money.hands_played and abs(value - float(self.config[key])) >= 0.005:
                        return {"ok": False,
                                "error": "Phiên đã có %d tay; không đổi %s giữa phiên. "
                                         "Dùng “Phiên mới” nếu muốn áp dụng."
                                         % (self.sim.money.hands_played,
                                            "vốn" if key == "capital" else "chốt lời")}
                    normalized[key] = value
                    changed.append(key)

            self.config = normalized
            self.bet_config = {"side": normalized["bet_side"], "stake": normalized["bet_stake"]}
            book = self.sim.money
            book.take_profit_pct = normalized["take_profit_pct"]
            if not book.hands_played:
                book.unit = float(normalized["bet_stake"])
                book.capital = book.start_capital = book.balance = normalized["capital"]
                book.peak = normalized["capital"]
                book.max_drawdown = 0.0
            book.check_limits()
            self.stream.human_mouse = normalized["human_mouse"]
            self._apply_live_config()
            self._save_state()

        self.log("Đã lưu cấu hình: %s." % (", ".join(sorted(set(changed))) or "không đổi"))
        self._push_state()
        return {"ok": True, "note": "Đã lưu cấu hình.", "changed": sorted(set(changed))}

    # ---------------------------------------------------------------- phiên
    def session_reset(self):
        """Reset phiên: xoá lịch sử tay, giữ cấu hình và lệnh cược hiện tại."""
        with self.lock:
            book = M.MoneyBook(capital=self.config["capital"], unit=self.config["bet_stake"],
                               take_profit_pct=self.config["take_profit_pct"])
            sim = LiveSimulation(book, unit=self.config["bet_stake"])
            self.sim = sim
            self.tables_done = 0
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            self.auto_start_key = None
            self.chip_live = None
        self._save_state()
        self.log("Đã reset phiên Baccarat (vốn %s VN2)." % M.fmt_money(self.config["capital"]))
        self._push_state()
        return {"ok": True, "note": "Đã reset phiên."}

    def session_new(self, params):
        """Tạo phiên mới từ vốn/chốt lời/lệnh cược mới (lưu bản sao state cũ)."""
        params = params or {}
        with self.lock:
            config = dict(self.config)
            for key in ("capital", "take_profit_pct", "bet_side", "bet_stake"):
                if key in params:
                    config[key] = params[key]
            config = self._normalize_config(config)
            # lưu bản sao phiên cũ trước khi tạo mới
            try:
                if self.state_path.exists():
                    archive = self.state_path.with_name(
                        "aibcr-session-%s-%d.json" % (time.strftime("%Y%m%d-%H%M%S"),
                                                    time.time_ns()))
                    archive.write_bytes(self.state_path.read_bytes())
            except OSError:
                pass
            self.config = config
            self.bet_config = {"side": config["bet_side"], "stake": config["bet_stake"]}
            book = M.MoneyBook(capital=config["capital"], unit=config["bet_stake"],
                               take_profit_pct=config["take_profit_pct"])
            sim = LiveSimulation(book, unit=config["bet_stake"])
            self.sim = sim
            self.tables_done = 0
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.chip_live = None
            self.last_order = None
        self._save_state()
        self.log("Đã tạo phiên mới: vốn %s VN2 · chốt lời %.0f%% · cược %s." % (
            M.fmt_money(self.config["capital"]), self.config["take_profit_pct"],
            self.config["bet_side"]))
        self._push_state()
        return {"ok": True, "note": "Đã tạo phiên mới."}

    def session_recover(self):
        if self.recover_busy:
            return {"ok": False, "error": "Đang phục hồi phiên."}
        if not self.config["auto_recover"]:
            return {"ok": False, "error": "Đang tắt tự phục hồi phiên."}
        self._try_recover_session(force=True)
        return {"ok": True, "note": "Đang mở lại EVO…"}

    def _try_recover_session(self, force=False):
        if not force and (self.recover_busy or not self.config["auto_recover"]):
            return
        if self.recover_attempts >= 3:
            self.sweep_note = ("Đã tự mở lại EVO 3 lần nhưng phiên vẫn bị văng. Hãy đăng nhập lại "
                               "trang gốc rồi bấm “VÀO BÀN HỢP LỆ”.")
            self._push_state()
            return
        self.recover_busy = True
        self.recover_attempts += 1
        self.sweep_note = "Phát hiện văng phiên · đang tự mở lại EVO (lần %d/3)…" % self.recover_attempts

        def work():
            try:
                ok, note = self.stream.open_lobby_from_portal()
                if not ok:
                    reloaded, reload_note = self.stream.reload_portal()
                    if reloaded:
                        ok, note = self.stream.open_lobby_from_portal()
                    else:
                        note = reload_note or note
            except Exception as exc:
                ok, note = False, "Không mở lại được EVO (%s)." % type(exc).__name__
            self.events.put(("recovered", (ok, note)))

        threading.Thread(target=work, daemon=True, name="ba-recover").start()
        self._push_state()

    # ----------------------------------------------------------------- vòng
    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ba-loop")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.tool_running = False

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.log("Lỗi vòng đọc: %s" % type(exc).__name__, "error")
            self._stop.wait(self.interval)

    def _drain(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                return
            self._handle(kind, data)

    def _handle(self, kind, data):
        if kind == "scan":
            self._handle_scan(*data)
        elif kind == "opened":
            self.chrome_busy = False
            self.connection_text = str(data)
            self.next_scan = 0.0
            self.sweep_note = str(data)
            self._on_chrome_ready()
            self.log("Chrome: " + str(data))
        elif kind == "open_error":
            self.chrome_busy = False
            self.connection_text = str(data)
            with self.lock:
                self.sim.pause("Chưa kết nối Chrome. Phiên theo dõi đã dừng.")
            self.tables.clear()
            self.log(str(data), "error")
        elif kind == "stopped":
            self.chrome_busy = False
            self.connection_text = str(data)
            self.tables.clear()
            self.chip_live = None
        elif kind == "lobby_entered":
            self.sweep_busy = False
            ok, note = data
            self.sweep_note = note
            if ok:
                self.session_lost = False
                self.next_scan = 0.0
                self.log("Đã nhận tab sảnh Baccarat.")
            else:
                self.log(note, "error")
        elif kind == "valid_lobby":
            self.sweep_busy = False
            ok, note = data
            self.sweep_note = note
            if ok:
                self.log("Đã nhận tab sảnh · đang quét tìm bàn hợp lệ…")
                self.lobby_sweep({"favorites_only": self.config["favorites_only"]})
            else:
                self._valid_failed(note)
        elif kind == "valid_fail":
            self.sweep_busy = False
            self._valid_failed(str(data))
        elif kind == "sweep":
            self.sweep_busy = False
            rows, error, observed_at = data
            self._on_sweep(rows, error, observed_at)
        elif kind == "table_opened":
            self.open_table_busy = False
            ok, note, key = data
            self.sweep_note = note
            if ok and key in self.tables:
                self.session_lost = False
                with self.lock:
                    self.sim.bind(self.tables[key])
                self.auto_start_key = key
                self.auto_start_deadline = time.time() + ENTRY_WAIT
                self.sweep_note = "Đã vào bàn · đang xác nhận dữ liệu…"
                self.next_scan = 0.0
                self.chip_live = None
                self.chip_read_at = 0.0
                self.last_order = None
                self.log("Đã mở bàn %s." % self.tables[key]["label"])
            elif not ok:
                if self._auth_blame():
                    self._session_lost(note)
                else:
                    self._schedule_cycle_retry(note, exclude_key=key)
                self.log(note, "error")
        elif kind == "cycle_back":
            self.sweep_busy = False
            self._on_cycle_back(*data)
        elif kind == "chips":
            self.chip_busy = False
            self.chip_live = data
        elif kind == "placed":
            self.place_busy = False
            ok, note, plan = data
            with self.lock:
                self.sim.mark_placed(ok, note, plan)
            self.place_status = {"ok": bool(ok), "note": note}
            self.log(("Đặt chip OK: " + note) if ok else ("Chưa đặt được chip: " + note),
                     "win" if ok else "error")
        elif kind == "recovered":
            self.recover_busy = False
            ok, note = data
            if ok:
                self.session_lost = False
                self.recover_attempts = 0
                self.sweep_note = "Đã mở lại EVO · quét sảnh để tìm bàn…"
                self.lobby_sweep()
            else:
                self.sweep_note = "Tự phục hồi chưa xong: " + note
                self.cycle_waiting = True
                self.cycle_retry_at = time.time() + CYCLE_RETRY_SECONDS
                self.log(self.sweep_note, "error")
        elif kind == "window_applied":
            self.chrome_busy = False
            ok, note = data
            self.sweep_note = note if ok else ("Đã lưu cấu hình. " + note)

    def _on_sweep(self, rows, error, observed_at):
        if error and self._auth_blame():
            self._session_lost("Quét sảnh không thành công: " + error)
            return
        if error:
            self.sweep_note = "Quét sảnh không thành công: " + error
            self.log(self.sweep_note, "error")
            self._schedule_cycle_retry(self.sweep_note)
            return
        if not rows:
            self.sweep_note = ("Không có bàn nào trong mục Ưa thích đọc được lịch sử. Thêm bàn vào "
                               "Ưa thích trên sảnh rồi quét lại."
                               if self.config["favorites_only"] else
                               "Không đọc được lịch sử bàn ở sảnh. Mở tab sảnh Baccarat rồi bấm "
                               "“VÀO BÀN HỢP LỆ” để app tự quét tiếp.")
            if not self.cycle_waiting and self.config["auto_hunt"] and not self.session_lost:
                self.cycle_waiting = True
                self.cycle_attempts = 0
                self.cycle_table_key = None
            self._schedule_cycle_retry(self.sweep_note)
            return
        self.session_lost = False
        self._ingest(rows, observed_at)
        if self.config["favorites_only"]:
            allowed = {"id:" + row["table_id"] for row in rows if row.get("table_id")}
            self.tables = {k: v for k, v in self.tables.items()
                           if k in allowed or k == self.sim.table_key}
        matched = sum(1 for row in rows if row.get("road_match"))
        self.sweep_note = "Đã quét %d bàn%s · %d bàn khớp lịch sử." % (
            len(rows), " trong mục Ưa thích" if self.config["favorites_only"] else "", matched)
        self.log(self.sweep_note)
        # tự mở bàn nếu đang săn và chưa vào bàn nào
        if not self.sim.running:
            self.auto_open_table(allow_sweep=self.cycle_waiting,
                                 exclude_key=self.cycle_table_key if self.cycle_waiting else None)

    def _on_cycle_back(self, ok, note):
        self.sweep_note = note
        take_profit = bool(getattr(self.sim, "take_profit_done", False))
        if take_profit:
            if ok:
                self.cycle_waiting = False
                self.cycle_retry_at = 0.0
                self.cycle_table_key = None
                self.tables_done += 1
                with self.lock:
                    self.sim.table_key = None
                    self.sim.table_name = "Chưa chọn bàn"
                    self.sim.letters = ""
                    self.sim.take_profit_done = False
                if self._session_complete():
                    self.sweep_note = ("Đã đạt mục tiêu lãi %.0f%% vốn (%s) · đã đóng bàn và dừng "
                                       "phiên (xong %d/%d bàn)." % (
                                           self.sim.money.take_profit_pct,
                                           M.fmt_money(self.sim.money.profit),
                                           self.tables_done, self._tables_target()))
                    self.log(self.sweep_note, "win")
                else:
                    self._start_next_table()
            elif self._auth_blame():
                self._session_lost(note)
            else:
                self.cycle_waiting = True
                self.cycle_retry_at = time.time() + CYCLE_RETRY_SECONDS
                self.sweep_note = "%s · sẽ thử đóng bàn lại sau %d giây." % (note, CYCLE_RETRY_SECONDS)
            return
        if ok:
            self.lobby_sweep()
        elif self._auth_blame():
            self._session_lost(note)
        else:
            self._schedule_cycle_retry(note)

    def _start_next_table(self):
        book = self.sim.money
        balance = book.rebase_to_balance()
        with self.lock:
            self.config["capital"] = float(balance)
        self.sim.take_profit_done = False
        self.sim.note = "Bàn trước đã chốt lời · vốn mới %s · đang tìm bàn kế tiếp." % \
                        M.fmt_money(balance)
        self.cycle_waiting = True
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None
        self.sweep_note = "Bàn %d/%d đã chốt lời · vốn mới %s · đang quét tìm bàn kế tiếp…" % (
            self.tables_done, self._tables_target(), M.fmt_money(balance))
        self._save_state()
        self.lobby_sweep()

    def _session_lost(self, note):
        self.session_lost = True
        self.cycle_waiting = False
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None
        self.auto_start_key = None
        with self.lock:
            self.sim.pause("Sảnh báo phiên Evolution không còn hợp lệ. Đăng nhập lại trang gốc, "
                           "bấm thẻ Evolution một lần rồi bấm “VÀO BÀN HỢP LỆ”.")
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = "Mất phiên đăng nhập · đã dừng đặt. Đăng nhập lại rồi chạy tool."
        self.sweep_note = note
        self.log("Mất phiên: " + note, "error")
        self._try_recover_session()

    def cancel_enter_valid(self):
        """Huỷ “vào bàn hợp lệ” khi người dùng bấm Dừng (không đụng phiên đang chạy)."""
        if self.enter_valid:
            self.enter_valid = False
            self.valid_check_done = False
            self.valid_note = self.sweep_note = "Đã huỷ tìm bàn hợp lệ."
            self.cycle_waiting = False
            self.cycle_attempts = 0
            self.cycle_retry_at = 0.0
            self.auto_start_key = None
            self.log(self.valid_note)
            self._push_state()
        return {"ok": True, "note": "Đã huỷ vào bàn hợp lệ."}

    def _valid_failed(self, note, level="error"):
        """Huỷ chế độ “vào bàn hợp lệ” và báo lý do (không tự đặt cược)."""
        self.enter_valid = False
        self.valid_check_done = False
        self.valid_note = "Chưa vào được bàn hợp lệ: " + str(note or "")
        self.cycle_waiting = False
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.auto_start_key = None
        self.sweep_note = self.valid_note
        self.log(self.valid_note, level)
        self._push_state()

    def _schedule_cycle_retry(self, reason, exclude_key=None):
        if self.session_lost or (self.tool_running is False and not self.enter_valid):
            return False
        manual_enter = bool(self.enter_valid)
        if not (self.cycle_waiting and (self.config["auto_hunt"] or manual_enter)):
            return False
        if exclude_key:
            self.cycle_table_key = exclude_key
        hunting = not getattr(self.sim, "take_profit_done", False)
        first_attempt = hunting and self.cycle_attempts == 0
        self.cycle_attempts += 1
        wait = 0 if first_attempt else CYCLE_RETRY_SECONDS
        self.cycle_retry_at = time.time() + wait
        self.sweep_note = ("%s · quét lại ngay…" % reason if first_attempt else
                          "%s · tự quét lại sau %d giây (đã thử %d lượt)." % (
                              reason, CYCLE_RETRY_SECONDS, self.cycle_attempts))
        return True

    def _ingest(self, rows, now=None):
        """Gộp kết quả quét/scan vào bảng bàn, giữ độ "ổn định" của cầu."""
        now = time.time() if now is None else now
        incoming = {}
        for raw in rows:
            letters = raw.get("letters", "")
            label = " ".join(str(raw.get("label") or raw.get("title") or "").split())[:80]
            if not label or not isinstance(letters, str):
                continue
            if any(ch not in "BPT" for ch in letters) or len(letters) > 400:
                continue
            table_id = raw.get("table_id") or raw.get("id") or ""
            if not isinstance(table_id, str) or not table_id or len(table_id) > 80:
                table_id = ""
            key = "id:" + table_id if table_id else "".join(label.split()).casefold()
            if (self.live_road and key == self.sim.table_key
                    and not letters.startswith(self.live_road)):
                # Lượt quét CDP bắt đầu trước khi ván mới về sẽ trả cầu ngắn hơn cầu
                # WebSocket. Nhận nó là "Cầu đổi nguồn" oan → huỷ lệnh đang chờ chip;
                # nên khi live đang chạy, cầu live là chuẩn cho bàn đang theo dõi.
                letters = self.live_road
            previous = incoming.get(key)
            old = self.tables.get(key)
            conflict = bool(previous and previous["letters"] != letters)
            incoming[key] = {
                "key": key, "label": label, "letters": letters, "ts": now,
                "table_id": table_id, "game_type": raw.get("game_type", ""),
                "read_error": raw.get("read_error", ""),
                "source": raw.get("source", ""), "conflict": conflict,
            }
            if raw.get("road_match") is True:
                incoming[key]["ws_confirmed_letters"] = letters
            elif old:
                confirmed = old.get("ws_confirmed_letters", "")
                incoming[key]["ws_confirmed_letters"] = confirmed if (
                    letters.startswith(confirmed) or confirmed.startswith(letters)) else ""
        for key, row in incoming.items():
            old = self.tables.get(key)
            row["stable"] = (old["stable"] + 1
                             if old and old["letters"] == row["letters"]
                             and not (old["conflict"] or row["conflict"]
                                      or now - old["ts"] > LIVE_STALE) else 1)
            row["screen_stable"] = (old.get("screen_stable", 0) + 1
                                    if row["source"] == "evo-bead" and old
                                    and old.get("source") == "evo-bead"
                                    and old["letters"] == row["letters"]
                                    else (1 if row["source"] == "evo-bead" else 0))
            self.tables[key] = row
        self.tables = {k: r for k, r in self.tables.items()
                       if now - r["ts"] < 300 or k == self.sim.table_key}

    # ------------------------------------------------------------ tự săn bàn
    def auto_open_table(self, allow_sweep=False, exclude_key=None):
        """Mở bàn đầu tiên có mã bàn — không còn điều kiện lọc cầu."""
        if self._busy_chrome() or not (self.tool_running or self.enter_valid):
            return
        if self.sim.running or getattr(self.sim, "take_profit_done", False):
            return
        candidates = [row for row in self.tables.values()
                      if row.get("table_id") and row["key"] != exclude_key]
        if not candidates:
            if not self.cycle_waiting and self.config["auto_hunt"]:
                self.cycle_waiting = True
                self.cycle_attempts = 0
                self.cycle_table_key = exclude_key
            reason = "Chưa có bàn nào để vào"
            if self._schedule_cycle_retry(reason, exclude_key=exclude_key):
                return
            if self.cycle_waiting or not allow_sweep:
                self.sweep_note = ("Chưa có bàn nào có mã bàn · bấm “VÀO BÀN HỢP LỆ” để quét lại, "
                                   "hoặc bật “Tự săn bàn” để app tự lặp tới khi vào được.")
                return
            self.lobby_sweep()
            return
        row = candidates[0]
        info = table_stats(list(row.get("letters") or ""))
        self.sweep_note = "Đang mở %s (%d tay, bên mạnh %s)…" % (
            row["label"], info["hands"], E.SIDE_NAME.get(info["strong"], "—"))
        self.open_table(row["key"])

    def _auto_start_verified_table(self):
        key = self.auto_start_key
        if not key:
            return
        row = self.tables.get(key)
        if not row:
            if time.time() > self.auto_start_deadline:
                self.sweep_note = ("Vào bàn rồi nhưng %d giây chưa đọc được cầu bàn. "
                                   "Đang tìm bàn khác…" % ENTRY_WAIT)
                self.auto_start_key = None
                self._cycle_search(key)
            return
        info = table_stats(list(row.get("letters") or ""))
        if self.enter_valid and not self.tool_running:
            # Nút “VÀO BÀN HỢP LỆ”: đã vào bàn → chỉ báo rồi đứng chờ người dùng bật
            # tool; tuyệt đối không arm/đặt chip ở đây.
            with self.lock:
                self.sim.bind(row)
            self.enter_valid = False
            self.valid_check_done = True
            self.auto_start_key = None
            self.cycle_waiting = False
            self.cycle_attempts = 0
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            self.valid_note = ("Đã vào bàn · %s · %d tay · mạnh %s · "
                               "CHƯA đặt cược (bật tool để chạy)." % (
                                   row["label"], info["hands"],
                                   E.SIDE_NAME.get(info["strong"], "—")))
            self.sweep_note = self.valid_note
            self.log(self.valid_note, "win")
            return
        # Đồng bộ vốn theo số dư THẬT trước khi bắt đầu theo dõi: sau khi start, vốn bị
        # khoá để giữ đúng lãi/lỗ. Thiếu bước này phiên dùng vốn mặc định và bị chặn
        # "hết vốn" ngay từ tay đầu. (Đọc CDP ngoài lock để không chặn vòng quét.)
        self._wallet_sync_once()
        with self.lock:
            started = self.sim.start(row)
            note = self.sim.note
            if started:
                self.enter_valid = False
                self.valid_check_done = False
        if started:
            self.sweep_note = "Đã vào bàn và bắt đầu theo dõi · %s" % note
            self.auto_start_key = None
            self.cycle_waiting = False
            self.cycle_attempts = 0
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            self.log("Bắt đầu theo dõi %s." % row["label"])
        else:
            self.sweep_note = "Chưa thể bắt đầu: " + note
            self.auto_start_key = None
            self._cycle_search(key)

    def _cycle_search(self, key):
        if self.cycle_waiting:
            self.auto_open_table(allow_sweep=True, exclude_key=key)

    def _resume_cycle_hunt(self, now):
        take_profit = bool(getattr(self.sim, "take_profit_done", False))
        manual_enter = bool(self.enter_valid)
        if not (self.cycle_waiting and (self.config["auto_hunt"] or manual_enter or take_profit)
                and self.cycle_retry_at and now >= self.cycle_retry_at):
            return
        self.cycle_retry_at = 0.0
        if self.sim.running or self.auto_start_key:
            return
        if take_profit:
            self.leave_table(take_profit=True)
            return
        if self.session_lost:
            self._try_recover_session()
            if self.session_lost:
                self.cycle_retry_at = now + CYCLE_RETRY_SECONDS
            return
        if self._busy_chrome() or not self._cdp_available():
            self.cycle_retry_at = now + CYCLE_RETRY_SECONDS
            return
        self.sweep_note = "Đang tự quét sảnh tìm bàn có mã bàn (lượt %d)…" % (self.cycle_attempts + 1)
        self.lobby_sweep()

    # --------------------------------------------------------------- nhịp làm việc
    def _scan(self):
        """Đọc cầu bàn đang mở (CDP) để tiến trình cược chạy tiếp."""
        if self.scan_busy:
            return
        self.scan_busy = True

        def work():
            try:
                reports = self.browser.scan()
                self.events.put(("scan", (reports, self.browser.last_error, time.time())))
            except Exception as exc:
                self.events.put(("scan", ([], str(exc).splitlines()[0][:180], time.time())))

        threading.Thread(target=work, daemon=True, name="ba-scan").start()

    def _handle_scan(self, reports, error, observed_at):
        self.scan_busy = False
        if error:
            self.connection_text = "Đọc cầu chưa thành công: " + error
            if self._auth_blame():
                self._session_lost(error)
                return
            with self.lock:
                self.sim.pause("Mất kết nối/đọc cầu lỗi. Hãy đối chiếu lại trước khi tiếp tục.")
            return
        self.session_lost = False
        self._sync_wallet(reports)
        rows = []
        for report in reports:
            for table in report.get("tables", []):
                rows.append(table)
        if rows:
            self._ingest(rows, observed_at)
        count = len(rows)
        if count:
            self.connection_text = "Đang đọc %d bàn." % count
        elif (self.browser.last_diag or {}).get("kind") == "wm":
            # WM chỉ gửi kết quả mỗi ván một lần; giữa hai ván không có gì để đọc.
            self.connection_text = "Đang đọc bàn WM · chờ ván kế tiếp."
        else:
            self.connection_text = "Chưa thấy bàn Baccarat."
        with self.lock:
            changed = self.sim.process(self.tables.get(self.sim.table_key))
        if changed:
            self._save_state()
            if self.sim.cycle_done:
                self.sim.cycle_done = False
                self.leave_table(take_profit=self.sim.take_profit_done)

    def _wallet_sync_once(self):
        """Đọc số dư thật một lần rồi đồng bộ vốn phiên (dùng khi bật tool)."""
        try:
            if getattr(self.browser, "wm_page_id", None):
                wallet = self.browser.read_wm_wallet()
            else:
                wallet = {}
            if wallet.get("ok"):
                with self.lock:
                    self._apply_wallet(wallet["value"], wallet.get("text") or "")
                self._push_state()
        except Exception:
            pass

    def _sync_wallet(self, reports):
        text = next((str((report.get("page") or {}).get("wallet_balance") or "").strip()
                     for report in reports
                     if (report.get("page") or {}).get("wallet_balance")), "")
        if not text and getattr(self.browser, "wm_page_id", None):
            # WM: số dư thật nằm trong iframe bàn (#userBalanceBox), không nằm ở trang.
            wallet = self.browser.read_wm_wallet()
            if wallet.get("ok"):
                self._apply_wallet(wallet["value"], wallet.get("text") or "")
            return
        if not text:
            return
        try:
            value = M.parse_money(text)
        except (TypeError, ValueError):
            self.wallet_text = "Số dư ví trên web: không đọc được giá trị"
            return
        self._apply_wallet(value, text)

    def _apply_wallet(self, value, raw):
        """Đồng bộ vốn phiên theo số dư thật đọc được trên web.

        CHỈ đồng bộ khi phiên chưa theo dõi và chưa có tay nào. Nếu đồng bộ giữa phiên,
        số dư sổ sách bị ghi đè bằng số dư ví sau mỗi lần đặt cược → lãi/lỗ hiển thị sai
        và trông như "tiền bốc hơi". Trong phiên chỉ cập nhật nhãn hiển thị.
        """
        self.wallet_text = "Số dư ví: %s đv (= %sđ)" % (
            M.fmt_money(value), M.fmt_money(value * 1000))
        book = self.sim.money
        if self.sim.running or book.hands_played:
            return
        ok, _note = book.sync_capital(value)
        if not ok:
            return
        self.config["capital"] = float(value)
        # Đơn vị cược phải ≤ số dư thật, nếu không phiên bị chặn "hết vốn" ngay.
        stake = float(self.bet_config["stake"] or 10.0)
        if stake > value:
            stake = max(1.0, float(int(value)))
            self.bet_config["stake"] = stake
            self.config["bet_stake"] = stake
        book.unit = stake
        self.sim.unit = stake
        self.wallet_text += " · vốn phiên đã đồng bộ"
        self._save_state()

    def _watch_live_reader(self):
        """Bộ đọc live chết vì lỗi CDP/mạng: gắn lại bộ đọc mới, giữ nguyên cầu."""
        reader = self.live_reader
        session = self.live_session
        if reader is None or session is None or reader.is_alive() \
                or self.live_stop_event.is_set():
            return
        self.log("AI live: bộ đọc đã dừng (%s) · tự gắn lại."
                 % (getattr(reader, "last_error", "") or "thread"), "warn")
        with self.lock:
            self.live_reader = self._make_live_reader(session)
            reader = self.live_reader
        reader.start()

    def _refresh_live_reader_kind(self):
        """Switch live decoders when Chrome changes between WM and other sites.

        The reader is selected when AI live starts. A still-alive Petalive reader
        would otherwise keep running forever if WM opens afterward.
        """
        reader = self.live_reader
        session = self.live_session
        if reader is None or session is None or not reader.is_alive() \
                or self.live_stop_event.is_set():
            return
        now = time.monotonic()
        if now < self.live_reader_probe_at:
            return
        self.live_reader_probe_at = now + 3.0
        try:
            page, _detect = find_wm_page(getattr(BR, "CDP_PORT", 9222))
        except Exception:
            return
        wants_wm = page is not None
        if wants_wm == isinstance(reader, WMReader):
            return

        # The replacement owns a fresh event so a slow old CDP shutdown cannot
        # stop the new reader.
        old_stop = self.live_stop_event
        new_stop = threading.Event()
        old_stop.set()
        with self.lock:
            if self.live_reader is not reader or self.live_session is not session:
                return
            self.live_stop_event = new_stop
            replacement = self._make_live_reader(session, wm_detected=wants_wm)
            self.live_reader = replacement
        replacement.start()
        reader.join(timeout=0.2)
        self.log("AI live: đã chuyển bộ đọc theo tab Chrome đang mở.", "info")

    def _tick(self):
        self._drain()
        self._watch_live_reader()
        if not self.browser.connected:
            # Nút “VÀO BÀN HỢP LỆ” gắn Chrome ở thread riêng: lần đầu chưa có kết nối là
            # bình thường, không được coi là "Chrome đã đóng" rồi huỷ chế độ vừa bật.
            if not (self.enter_valid and not self.had_chrome):
                self._on_chrome_lost()
        else:
            self._on_chrome_ready()
            self._refresh_live_reader_kind()
            if self.enter_valid:
                self._watch_enter_valid(time.time())
            if self.tool_running or self.enter_valid or self.valid_check_done:
                now = time.time()
                if not self.session_lost and now >= self.next_scan and not self._busy():
                    self.next_scan = now + (FAST_SCAN if (self.auto_start_key or self.sim.running)
                                            else SCAN_SECONDS)
                    self._scan()
                if (self.sim.table_key and not self.chip_busy
                        and now - self.chip_read_at >= CHIP_REFRESH):
                    self.chip_read_at = now
                    self.chips_read()      # đọc chip ở thread riêng, không chặn vòng chính
                self._auto_start_verified_table()
                self._follow_open_table()
                self._recover_from_lobby()
                self._auto_bet_tick()
                self._tool_retry_enter(now)
                self._resume_cycle_hunt(now)
        self._push_state()

    def _watch_enter_valid(self, now):
        """Hết thời gian chờ “vào bàn hợp lệ” thì huỷ, không để chế độ treo vô hạn."""
        if self.valid_check_done or not self.enter_deadline:
            return
        if now <= self.enter_deadline:
            return
        self._valid_failed("quá %d giây chưa mở được bàn nào." % ENTER_VALID_TIMEOUT)

    def _on_chrome_lost(self):
        """Chrome bị đóng (người dùng tắt cửa sổ): dọn danh sách bàn, tạm dừng phiên.

        Nhờ vậy UI thấy ``chrome_connected = false`` ngay và nút “Mở Chrome” bấm lại được;
        chỉ ghi log một lần cho tới khi kết nối lại.
        """
        if self.offline_noted:
            return
        self.offline_noted = True
        had_session = bool(self.tables) or bool(self.sim.running) or bool(self.sim.table_key)
        self.tables.clear()
        self.chip_live = None
        self.chip_read_at = 0.0
        self.auto_start_key = None
        self.live_road = ""
        if self.enter_valid:
            self.enter_valid = False
            self.valid_note = "Chrome đã đóng · huỷ tìm bàn hợp lệ."
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
        with self.lock:
            if self.sim.running or self.sim.table_key:
                self.sim.detach("Chrome đã đóng · phiên tạm dừng. Bấm “Mở Chrome” để mở lại.")
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = "Chrome đã đóng/mất kết nối · đã dừng đặt. Mở Chrome rồi chạy tool."
        self.lobby_since = None
        self.sweep_note = getattr(self.browser, "note", "") or \
            "Chrome đã đóng · bấm “Mở Chrome” để mở lại."
        self.connection_text = self.sweep_note
        if had_session:
            self.log(self.sweep_note, "error")

    def _on_chrome_ready(self):
        self.had_chrome = True
        if self.offline_noted:
            self.offline_noted = False
            self.next_scan = 0.0

    # ------------------------------------------------------------- AI live
    def _live_cfg(self):
        """Config an toàn, được trả về snapshot/UI — KHÔNG chứa API key."""
        cfg = self.config
        return {
            "decks": cfg["live_decks"],
            "trials": cfg["live_trials"],
            "markov_weight": cfg["live_markov_weight"],
            "ai_mode": cfg["ai_mode"],
            "ai_url": cfg["ai_url"],
            "ai_model": cfg["ai_model"],
            "ai_every": cfg["ai_every"],
            "ai_timeout": cfg["ai_timeout"],
        }

    def _live_cfg_private(self):
        """Chỉ dùng khi tạo/cấu hình LiveSession; key không bao giờ ra snapshot."""
        cfg = self._live_cfg()
        cfg["ai_key"] = self.ai_key_override
        return cfg

    def _apply_live_config(self):
        if self.live_session is not None:
            self.live_session.configure(**self._live_cfg_private())

    def live_snapshot(self):
        if self.live_session is None:
            return {
                "ok": False, "running": False, "table": "", "rounds": 0,
                "prediction": None, "analysis": None,
                "ai": {"mode": self.config["ai_mode"], "available": False,
                       "busy": False, "error": ""},
                "config": self._live_cfg(),
                "note": "Chưa bật AI live — bấm “Bật AI live” để đọc bàn đang mở (WM/Petalive).",
            }
        return self.live_session.snapshot()

    def _follow_open_table(self):
        """Chrome đang ở bàn khác bàn theo dõi: chuyển theo đúng bàn thật đang mở.

        Xảy ra khi người dùng tự đổi bàn trong Chrome hoặc ô bấm mở nhầm bàn. Nếu
        không đổi theo, lệnh treo mãi ở "chờ dữ liệu bàn mới" vì bộ đọc live bám bàn
        khác bàn đang theo dõi. Chỉ đổi khi CDP xác nhận bàn đang mở khớp bộ đọc.
        """
        if self.live_session is None or not self.sim.table_key or self.place_busy:
            return
        try:
            live = self.live_snapshot()
        except Exception:
            return
        if not live.get("running"):
            return
        table = str(live.get("table") or "").replace("WM ", "").strip()
        wm_key = str(getattr(self.browser, "wm_open_key", "") or "")
        if not table or table != wm_key:
            return
        key = "id:" + table
        if key == self.sim.table_key:
            return
        letters = str(live.get("history") or "")
        with self.lock:
            row = self.tables.get(key)
            if row is None:
                row = {"key": key, "label": str(live.get("table") or ("WM " + table)),
                       "letters": letters, "table_id": table, "game_type": "baccarat",
                       "read_error": "", "conflict": False, "source": "live-ws",
                       "ts": time.time(), "stable": 2}
                self.tables[key] = row
            elif letters:
                row["letters"] = letters
                row["ts"] = time.time()
            self.sim.bind(row)
            self.sim.start(row)
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.last_order = None
        self.chip_live = None
        self.chip_read_at = 0.0
        self.log("Đã chuyển theo bàn đang mở %s." % row["label"], "info")
        self._push_state()

    def _recover_from_lobby(self):
        """Chrome rời bàn (về sảnh/đăng nhập) quá lâu: rời bàn để tool tự vào lại.

        Không có bước này thì sim vẫn bám bàn cũ trong khi bộ đọc không còn dữ liệu
        bàn đó, khiến ghi chú treo mãi ở "chờ dữ liệu bàn mới từ WebSocket". Xử lý cả
        khi sim đã bị pause (dữ liệu cũ) chứ không chỉ khi đang chạy: pause + vẫn bám
        bàn là trạng thái treo mà ``_tool_retry_enter`` không tự thoát được.
        """
        if not self.tool_running or not self.sim.table_key:
            self.lobby_since = None
            return
        if self.sim.money.blocked or self.sim.take_profit_done:
            self.lobby_since = None
            return
        if not self.browser.connected:
            self.lobby_since = None
            return
        wm_key = str(getattr(self.browser, "wm_open_key", "") or "")
        if wm_key:
            self.lobby_since = None
            # Chrome còn trong bàn nhưng sim bị pause vì dữ liệu cũ: chạy lại tiếp.
            if not self.sim.running and wm_key == self.sim.table_key.replace("id:", ""):
                row = self.tables.get(self.sim.table_key)
                if row is not None:
                    self.sim.start(row)
                    self.auto_bet_note = self.sim.note
                    self.log("Tiếp tục theo dõi bàn %s sau khi dữ liệu bị ngắt." % row["label"])
            return
        now = time.monotonic()
        if self.lobby_since is None:
            self.lobby_since = now
            return
        if now - self.lobby_since < 20.0:
            return
        self.lobby_since = None
        self.sim.detach("Chrome không còn trong bàn WM (về sảnh/đăng nhập) · tìm bàn lại.")
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = self.sim.note
        self.last_order = None
        self.chip_live = None
        self.chip_read_at = 0.0
        self.log(self.sim.note, "warn")
        self._push_state()

    def _sync_live_to_sim(self, live):
        """Đưa cầu đọc được từ WebSocket vào bàn đang theo dõi ngay lập tức.

        Trước đây cầu chỉ cập nhật theo nhịp quét sảnh nên UI chậm 2 tay so với bàn
        thật. WebSocket là nguồn realtime, nên mỗi ván về là ghi thẳng vào bàn.
        """
        if not isinstance(live, dict):
            return False
        letters = str(live.get("history") or "")
        key = self.sim.table_key
        if not key:
            if live.get("running"):
                self.live_hand = int(live.get("hand") or 0)
            self.live_road = ""
            return False
        # Chỉ nhận cầu live làm chuẩn khi bộ đọc đang chạy và đã có cầu của đúng bàn.
        live_table = str(live.get("table") or "").replace("WM ", "").strip()
        same_table = bool(live.get("running")) and (
            not live_table or key.endswith(live_table) or live_table.endswith(key))
        if same_table:
            # Live là nguồn số tay thật của bàn đang mở; gán (không lấy max) để khi
            # đổi bàn số tay không dính bàn cũ.
            self.live_hand = int(live.get("hand") or 0)
        self.live_road = letters if same_table else ""
        if not letters:
            return False
        with self.lock:
            row = self.tables.get(key)
            if row is None:
                row = {"key": key, "label": self.sim.table_name, "letters": "",
                       "table_id": "", "game_type": "baccarat", "read_error": "",
                       "conflict": False, "source": "live-ws"}
                self.tables[key] = row
            if row.get("letters") == letters:
                return False
            row["letters"] = letters
            row["ts"] = time.time()
            row["stable"] = max(2, int(row.get("stable") or 0))
            row["source"] = "live-ws"
            row["read_error"] = ""
            row["conflict"] = False
            changed = self.sim.process(row)
        if changed:
            self._save_state()
        return bool(changed)

    def _emit_live(self, data=None):
        live = data if isinstance(data, dict) else self.live_snapshot()
        try:
            changed = self._sync_live_to_sim(live)
        except Exception:
            changed = False
        try:
            self.emit.event("live_prediction", live)
        except Exception:
            pass
        if changed:
            self._push_state()

    def _make_live_reader(self, session, wm_detected=None):
        """Chọn bộ đọc theo tab đang mở: WM đọc khung nhị phân, Petalive đọc text."""
        port = getattr(BR, "CDP_PORT", 9222)
        if wm_detected is None:
            try:
                wm_page, _detect = find_wm_page(port)
            except Exception:
                wm_page = None
            wm_detected = wm_page is not None
        if wm_detected:
            return WMReader(on_round=session.on_round, on_state=session.on_state,
                            on_status=lambda text, level="info":
                            self.log("AI live: %s" % text, level),
                            port=port, stop=self.live_stop_event)
        return LiveReader(on_round=session.on_round, on_state=session.on_state,
                          on_status=lambda text, level="info":
                          self.log("AI live: %s" % text, level),
                          port=port, stop=self.live_stop_event)

    def live_start(self):
        with self.lock:
            if self.live_reader is not None:
                return {"ok": True, "note": "AI live đã chạy."}
            self.live_stop_event.clear()
            self.live_reader_probe_at = 0.0
            session = LiveSession(
                on_prediction=self._emit_live,
                on_status=lambda text, level="info": self.log("AI live: %s" % text, level),
                **self._live_cfg_private())
            session.running = True
            reader = self._make_live_reader(session)
            boot_note = ("Đã bật AI live · đọc bàn WM qua WebSocket."
                         if isinstance(reader, WMReader)
                         else "Đã bật AI live · chờ tab bàn Petalive.")
            self.live_session = session
            self.live_reader = reader
        reader.start()
        self.log("AI live: đang đọc lá bài từ tab bàn qua CDP.", "info")
        self._push_state()
        return {"ok": True, "note": boot_note}

    def live_stop(self):
        with self.lock:
            reader = self.live_reader
            session = self.live_session
            self.live_reader = None
            self.live_session = None
        self.live_stop_event.set()
        if reader is not None:
            reader.join(timeout=2)
        if session is not None:
            session.running = False
        self._emit_live(self.live_snapshot())
        self._push_state()
        return {"ok": True, "note": "Đã tắt AI live."}

    def live_state(self):
        return self.live_snapshot()

    def live_analyze(self):
        with self.lock:
            session = self.live_session
        if session is None:
            return {"ok": False, "error": "Chưa bật AI live."}
        result = session.analyze_now()
        self._emit_live(self.live_snapshot())
        return result

    def ai_key_set(self, params):
        """Nhận API key từ UI: chỉ lưu RAM, không ghi file/log/snapshot."""
        params = params or {}
        key = str(params.get("key") or "").strip()[:300]
        with self.lock:
            self.ai_key_override = key
            self._apply_live_config()
        return {"ok": True, "has_key": bool(key),
                "note": "Đã lưu API key trong phiên này (chỉ RAM)." if key
                        else "Đã xoá API key tuỳ biến; dùng BCR_AI_KEY nếu có."}

    def ai_check(self, params):
        """Probe the currently entered provider settings without saving the key."""
        params = params or {}
        cfg = {
            "mode": params.get("mode") or self.config.get("ai_mode"),
            "url": params.get("url") or self.config.get("ai_url"),
            "model": params.get("model") or self.config.get("ai_model"),
            "key": params.get("key") or self.ai_key_override,
        }
        return LIVE_AI.check_model(cfg)

    def bet_config_set(self, params):
        """Configure the next hand using an explicit P/B/T choice and fixed stake."""
        params = params or {}
        with self.lock:
            side = str(params.get("side", self.bet_config["side"])).strip().upper()
            if side not in ("P", "B", "T"):
                return {"ok": False, "error": "Cửa phải là P, B hoặc T; không hỗ trợ chọn cửa bằng AI."}
            stake = _as_float(params.get("stake", self.bet_config["stake"]),
                              self.bet_config["stake"])
            if not 1.0 <= stake <= 1000000.0:
                return {"ok": False,
                        "error": "Số đơn vị mỗi tay phải nằm trong 1 – 1.000.000 (1 đv = 1.000đ)."}
            self.bet_config = {"side": side, "stake": stake}
            self.config["bet_side"] = side
            self.config["bet_stake"] = stake
        self._save_state()
        self._push_state()
        return {"ok": True, "side": side, "stake": stake,
                "note": "Lệnh tay kế: %s · %s đv (= %sđ)." % (
                    side, M.fmt_money(stake), M.fmt_money(stake * 1000))}

    def bet_place(self):
        """Nút “Tự đặt cược”: chốt lệnh rồi bấm chip thật (có gate chờ ván mới)."""
        with self.lock:
            if not self.config["auto_place"]:
                return {"ok": False, "error": "Đang tắt tự đặt chip — bật lại trong Cấu hình."}
            if self.place_busy:
                return {"ok": False, "error": "Lượt bấm chip trước chưa xong."}
            if not self.sim.table_key:
                return {"ok": False, "error": "Chưa vào bàn — bấm “VÀO BÀN HỢP LỆ” trước."}
            if not self.tool_running:
                return {"ok": False, "error": "Chưa chạy tool — bấm “Chạy tool” rồi mới đặt cược."}
            if self.sim.entry_waiting:
                return {"ok": False, "error": "Đang chờ tay hiện tại kết thúc; thử lại khi bàn sẵn sàng."}
            order = self._resolve_order()
            if not order["side"]:
                return {"ok": False, "error": "Chưa có cửa để đặt: hãy chọn P/B/T hoặc bật AI live."}
            pending = self.sim.set_order(order["side"], order["stake"], reason=order["reason"])
            if pending is None:
                return {"ok": False, "error": "Lệnh cược không hợp lệ."}
            self.last_order = {"side": order["side"], "stake": order["stake"]}
        self._place_armed_bet(pending)
        self._push_state()
        return {"ok": True, "side": order["side"], "stake": order["stake"],
                "note": "Đã gửi lệnh %s · %s đv (= %sđ) · đang chờ ván mới để bấm chip." % (
                    E.SIDE_NAME[order["side"]], M.fmt_money(order["stake"]),
                    M.fmt_money(order["stake"] * 1000))}

    # ------------------------------------------------------------- dispatch
    def dispatch(self, method, params):
        params = params or {}
        table = {
            "ping": lambda p: {"ok": True, "pong": True, "game": "baccarat"},
            "state": lambda p: self.snapshot(),
            "chrome.open": lambda p: self.chrome_open(),
            "site.open": self.site_open,
            "profile.configure": self.profile_configure,
            "febet.openDG": self.febet_open_dg,
            "febet.table": self.febet_current_table,
            "febet.tables": self.febet_lobby_tables,
            "febet.syncTable": self.febet_sync_table,
            "chrome.attach": lambda p: self.chrome_attach(),
            "chrome.close": lambda p: self.chrome_close(),
            "chrome.window": self.apply_window,
            "chrome.status": lambda p: {"connected": bool(self.browser.connected),
                                        "mode": self.browser.mode,
                                        "note": self.browser.note},
            "lobby.enter": lambda p: self.lobby_enter(),
            "lobby.sweep": self.lobby_sweep,
            "lobby.back": lambda p: self.lobby_back(),
            "tables": lambda p: {"tables": self.table_rows(),
                                 "note": self.sweep_note},
            "table.open": lambda p: self.open_table(p.get("key") or ""),
            "table.select": lambda p: self.select_table(p.get("key") or ""),
            "table.enterValid": lambda p: self.enter_valid_table(),
            "table.cancelEnter": lambda p: self.cancel_enter_valid(),
            "table.leave": lambda p: self.leave_table(take_profit=bool(p.get("take_profit"))),
            "tool.start": lambda p: self.tool_start(),
            "tool.stop": lambda p: self.tool_stop(),
            "scan": lambda p: self.scan_now(),
            "chips.read": lambda p: self.chips_read(),
            "config.get": lambda p: dict(self.config),
            "config.set": self.config_set,
            "session.reset": lambda p: self.session_reset(),
            "session.new": self.session_new,
            "session.recover": lambda p: self.session_recover(),
            "log.clear": lambda p: {"ok": True},
            "export": lambda p: {"log": list(self.sim.log)},
            "live.start": lambda p: self.live_start(),
            "live.stop": lambda p: self.live_stop(),
            "live.state": lambda p: self.live_state(),
            "live.analyze": lambda p: self.live_analyze(),
            "ai.check": self.ai_check,
            "ai.key.set": self.ai_key_set,
            "bet.config": self.bet_config_set,
            "bet.place": lambda p: self.bet_place(),
        }
        handler = table.get(method)
        if handler is None:
            return None, "Method không hỗ trợ: %s" % method
        try:
            return handler(params), None
        except Exception as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)

    def shutdown(self):
        self.stop()
        try:
            self.live_stop()
        except Exception:
            pass
        try:
            self._save_state()
        except Exception:
            pass
        try:
            self.browser.stop()
        except Exception:
            pass
