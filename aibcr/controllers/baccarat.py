# -*- coding: utf-8 -*-
"""Tầng Controller · Baccarat: vào site → sảnh → bàn DG → xếp chip theo cấu hình.

Chỉ điều phối Model (``aibcr.models``) và Adapter (``aibcr.adapters``); không dùng
tkinter và không biết gì về Electron. Tầng transport (``aibcr.service.engine``) gọi
``dispatch`` để phục vụ giao diện Electron.

Phạm vi: **chỉ đặt cược**. Không đọc kết quả ván, không tính thắng/thua, không đổi
mức cược theo kết quả, không AI/dự đoán, không đồng bộ ví. Mỗi ván nhóm profile cấu
hình sẵn chia P/B đối lập và xếp cùng một mức cược.

Trách nhiệm:
    - mở/gắn Chrome, mở site, nhận tab sảnh, mở bàn
    - đọc danh sách bàn + trạng thái cược của bàn DG
    - xếp chip (staging) và xác nhận theo lệnh của UI
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
from aibcr.adapters.dg_pages import find_dg_page
from aibcr.adapters.wm_bet import WMBet
from aibcr.models import fingerprint as FP
from aibcr.controllers.sites.e3951 import E3951EntryController
from aibcr.controllers.sites.febet import FEBETEntryController
from aibcr.controllers.sites.gk881 import GK881EntryController
from aibcr.controllers.sites.vnwtop import VNWTopEntryController
from aibcr.config import *  # noqa: F401,F403
from aibcr.models.bet_ladder import (BetLadder, DEFAULT_STAKES,
                                     parse_hop_rounds, parse_stakes)
from aibcr.adapters.wm_pages import find_wm_table
from aibcr.models import engine as E
from aibcr.models import money as M
from aibcr.models.live_sim import (LiveSimulation, compare_chips, table_is_clear,
                                   table_stats)

# Cấu hình mặc định của tab Baccarat (đơn vị VN2 như hiển thị trên sàn).
DEFAULT_CONFIG = {
    "favorites_only": True,
    "human_mouse": True,
    "auto_place": True,         # cho phép bấm chip thật khi bấm “Tự đặt cược”
    "auto_hunt": True,
    # Xác nhận cược ngay sau khi xếp đủ chip (DG: bấm nút xác nhận trong bàn).
    # Tắt thì chip chỉ treo trên ô và người dùng tự bấm xác nhận.
    "auto_confirm": True,
    # Dấu vết thiết bị Android riêng của profile; sinh tự động ở lần cấu hình đầu.
    "fingerprint": None,
    # Mức cược hiện tại; cửa luôn do người dùng (hoặc nhóm P/B) chọn trực tiếp.
    "bet_side": "P",            # P | B | T
    # 10 đơn vị = 10.000đ (DG/WM in khay chip theo nghìn đồng, 1 đv = 1.000đ).
    "bet_stake": float(DEFAULT_STAKES[0]),
    "stakes": list(DEFAULT_STAKES),
    "min_t": 20,
    "max_t": 10000,
    # Số profile tối thiểu để "Chạy cược". Đo trên máy này: nhóm chỉ có 2 profile
    # (xen kẽ P/B), nên để 3 khiến nút từ chối "Cần 3 profile, hiện có 2" và không
    # bao giờ đặt được tay nào. Mức 2 vẫn giữ được ý nghĩa đối trọng P/B.
    "min_tk": 2,
    "total_bet": 5000,
    "hop_min": "2",
    "hop_rounds": [2],
    "hop_max": 5,
    "start_url": BR.START_URL,
    "chrome_window": {"width": 900, "height": 1200, "percent": 60, "fullscreen": False},
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
    """Điều phối một profile: Chrome → site → sảnh → bàn → xếp chip."""

    def __init__(self, state_path, emit, interval=2.0):
        self.state_path = pathlib.Path(state_path)
        self.emit = emit
        self.interval = float(interval or 2.0)
        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.logs = collections.deque(maxlen=300)
        self.config = self._load_config()

        self.browser = BR.BrowserSession()
        # Keep the persisted device identity across app restarts.
        if isinstance(self.config.get("fingerprint"), dict):
            self.browser.fingerprint = self.config["fingerprint"]
        self.febet_entry = FEBETEntryController(self)
        self.gk881_entry = GK881EntryController(self)
        self.e3951_entry = E3951EntryController(self)
        self.vnwtop_entry = VNWTopEntryController(self)
        self.stream = LS.LobbyStream(self.browser, human_mouse=self.config["human_mouse"],
                                     game="baccarat")
        self.sim = self._build_sim()

        self.tables = {}
        self.tool_running = False
        self._stop = threading.Event()
        self._thread = None

        self.bet_ladder = BetLadder(self.config["stakes"], self.config["min_t"],
                                    self.config["max_t"])
        self.bet_config = {"side": self.config["bet_side"],
                           "stake": self.config["bet_stake"]}

        # cờ bận cho các thao tác web
        self.chrome_busy = False
        self.scan_busy = False
        self.sweep_busy = False
        self.open_table_busy = False
        self.chip_busy = False
        self.place_busy = False
        # Đã báo "Chrome đã đóng" chưa (tránh spam log mỗi 2 giây khi mất kết nối).
        self.offline_noted = False
        # Đã từng kết nối Chrome trong phiên này chưa (phân biệt "chưa mở" với "vừa đóng").
        self.had_chrome = False

        self.next_scan = 0.0
        self.chip_live = None
        self.chip_read_at = 0.0
        self.place_status = {"ok": None, "note": ""}
        self.sweep_note = "Mở Chrome, vào sảnh Baccarat rồi bấm “VÀO BÀN HỢP LỆ”."
        self.connection_text = "Chưa kết nối Chrome."

        # vòng tự săn bàn
        self.cycle_waiting = False
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None

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
        # Chế độ một nút: “Chạy tool” = tự vào bàn + tự đặt cược từng tay. Biến này giữ
        # cầu của tay đã arm để không arm lặp lại cùng một tay.
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = ""
        # Lệnh vừa đặt gần nhất (side/stake). Giữa hai ván chip trên bàn thuộc lệnh này,
        # không phải lệnh tay kế (chưa bấm) — dùng để không báo "SAI CỬA" oan.
        self.last_order = None
        # (table_key, số tay) đã chốt lệnh — chặn đặt trùng khi nguồn phát lại một ván.
        self.placed_signatures = set()
        # Chưa có bàn (Chrome vừa mở/chưa đăng nhập) thì thử lại theo nhịp này.
        self.tool_retry_at = 0.0

        self.log("Engine Baccarat sẵn sàng (vào bàn · xếp chip theo cấu hình).")

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
                    "max_streak", "min_lead", "max_lead", "tie_side",
                    # Khoá của các khối đã bị bỏ khỏi dự án (AI, dự đoán, vốn/chốt
                    # lời, đồng bộ ví, số bàn mỗi phiên); xoá khỏi state cũ để file
                    # lưu không còn rác cấu hình chết.
                    "ai_mode", "ai_url", "ai_model", "ai_every", "ai_timeout",
                    "live_decks", "live_trials", "live_markov_weight",
                    "capital", "take_profit_pct", "auto_recover", "tables_to_play",
                    "cycle_max_attempts", "ladder_step"):
            config.pop(key, None)
        legacy_ai_side = str(config.get("bet_side") or "").strip().upper() == "AUTO"
        for key in ("favorites_only", "human_mouse", "auto_place", "auto_hunt"):
            config[key] = bool(config.get(key, DEFAULT_CONFIG[key]))
        if legacy_ai_side:
            config["auto_place"] = False
        side = str(config.get("bet_side") or "P").strip().upper()
        config["bet_side"] = side if side in ("P", "B", "T") else "P"
        config["bet_stake"] = min(1000000.0, max(1.0, _as_float(
            config.get("bet_stake"), DEFAULT_CONFIG["bet_stake"])))
        config["stakes"] = parse_stakes(config.get("stakes"))
        config["min_t"] = min(10000, max(1, _as_int(config.get("min_t"), 20)))
        config["max_t"] = min(10000, max(config["min_t"],
                                         _as_int(config.get("max_t"), 10000)))
        config["min_tk"] = min(15, max(2, _as_int(config.get("min_tk"), 2)))
        config["total_bet"] = max(1, _as_int(config.get("total_bet"), 5000))
        config["hop_min"] = str(config.get("hop_min") or "2").strip()[:120] or "2"
        config["hop_rounds"] = parse_hop_rounds(config["hop_min"])
        config["hop_max"] = min(48, max(1, _as_int(config.get("hop_max"), 5)))
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
        return LiveSimulation(unit=self.config["bet_stake"])

    def _save_state(self):
        with self.lock:
            data = {
                "format": "bet-only-v1",
                "game": "baccarat",
                "settings": dict(self.config),
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
        """Resolve the explicit user-selected side; nothing else selects a wager."""
        params = params or {}
        side = str(params.get("side", self.bet_config["side"])).strip().upper()
        stake = _as_float(params.get("stake", self.bet_config["stake"]),
                          self.bet_config["stake"])
        return {"side": side if side in ("P", "B", "T") else None,
                "stake": min(1000000.0, max(1.0, stake)),
                "reason": "Lệnh do người dùng chọn"}

    def _process_sim(self, row):
        """Đưa cầu mới của bàn đang theo dõi vào sim.

        Chỉ cập nhật cầu và vòng đời lệnh cược; không đọc kết quả và không đổi mức
        cược, nên không có bước tiến/lùi dãy cược ở đây.
        """
        return self.sim.process(row)

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
            sim = self.sim
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
                "cycle": {
                    "waiting": bool(self.cycle_waiting),
                    "attempts": self.cycle_attempts,
                    "retry_in": max(0.0, (self.cycle_retry_at or 0) - now),
                },
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
                    "hand": len(sim.letters or ""),
                    "running": sim.running,
                    "entry_waiting": sim.entry_waiting,
                    "note": sim.note,
                    "auto_note": self.auto_bet_note,
                },
                "plan": plan,
                "bet": {
                    "side": self.bet_config["side"],
                    "stake": _finite(self.bet_config["stake"]),
                    "pending": dict(sim.pending) if sim.pending else None,
                },
                "bet_ladder": {
                    "step": self.bet_ladder.step,
                    "steps": len(self.bet_ladder.stakes),
                    "stake": self.bet_ladder.current_stake,
                    "min": self.bet_ladder.min_stake,
                    "max": self.bet_ladder.max_stake,
                },
                "chips": {
                    "live": self.chip_live,
                    "check": chip_check,
                    "at": self.chip_read_at,
                },
                "place": dict(self.place_status),
                "tables": self.table_rows(),
                "config": json.loads(json.dumps(self.config)),
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

    def chrome_attach_omni(self, params):
        """Gắn WebDriver vào Chrome do OmniLogin mở; không sở hữu tiến trình Chrome."""
        params = params or {}
        try:
            port = int(params.get("port"))
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            return {"ok": False, "error": "Cổng CDP OmniLogin không hợp lệ."}
        BR.CDP_PORT = port
        if not self.browser.attach_external(port):
            return {"ok": False, "error": self.browser.last_error or "Không gắn được profile OmniLogin."}
        window = self._window()
        pos = self._window_pos(window)
        width = min(3840, max(520, _as_int(params.get("width"), window["width"])))
        height = min(2160, max(200, _as_int(params.get("height"), window["height"])))
        self.browser.resize_window({"width": width, "height": height,
                                    "percent": window.get("percent", 60), "fullscreen": False}, pos=pos)
        self.connection_text = "Đã kết nối profile OmniLogin · CDP %d." % port
        self._push_state()
        return {"ok": True, "note": self.connection_text,
                "width": width, "height": height, "cdp_port": port}

    def chrome_attach_external(self, params):
        params = dict(params or {})
        provider = str(params.get("provider") or "external").strip().title()
        result = self.chrome_attach_omni(params)
        if result.get("ok"):
            self.browser.mode = provider.lower()
            self.browser._driver_info = "%s · %s CDP %s" % (
                self.browser._driver_info.split(" · ", 1)[0], provider, result.get("cdp_port"))
            self.browser.note = "Đã gắn Chrome profile %s; profile do %s quản lý." % (provider, provider)
            self.connection_text = "Đã kết nối profile %s · CDP %s." % (provider, result.get("cdp_port"))
            result["note"] = self.connection_text
            self._push_state()
        return result

    def site_open(self, params):
        url = str((params or {}).get("url") or "").strip()
        if not BR.valid_site_url(url):
            return {"ok": False, "error": "URL site không hợp lệ; chỉ hỗ trợ HTTPS công khai."}
        self.config["start_url"] = url
        self._save_state()
        if getattr(self.browser, "external_browser", False) and self.browser.driver is not None:
            # Navigation must never be the reason a managed profile disappears.
            # A blocking page load waits up to the page-load timeout (20 s) and
            # raises on slow sites; the caller would then stop the profile, which
            # makes OmniLogin kill Chrome. Issue Page.navigate over CDP instead so
            # a slow page counts as "still loading", not as a failure.
            opened, note = self.browser.navigate(url)
            if not opened:
                return {"ok": False, "error": note}
            window = self._window()
            with self.browser.lock:
                self.browser.resize_window(window, pos=self._window_pos(window))
            self.connection_text = "Đã mở website trong profile OmniLogin."
            self._push_state()
            return {"ok": True, "note": self.connection_text}
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
        if params.get("cdp_port") is not None:
            try:
                cdp_port = int(params.get("cdp_port"))
                if not 1 <= cdp_port <= 65535:
                    raise ValueError
                BR.CDP_PORT = cdp_port
            except (TypeError, ValueError):
                return {"ok": False, "error": "Cổng CDP profile không hợp lệ."}
        if params.get("close"):
            self.tool_running = False
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
            self.browser.stop()
        except Exception as exc:
            return {"ok": False, "error": "Không đóng được Chrome profile (%s)." % type(exc).__name__}

        width = min(3840, max(520, _as_int(params.get("width"), 900)))
        height = min(2160, max(200, _as_int(params.get("height"), 1200)))
        percent = min(200, max(50, _as_int(params.get("scale"), 60)))
        left = max(0, _as_int(params.get("left"), 0))
        top = max(0, _as_int(params.get("top"), 0))
        BR.WINDOW_POSITION = (left, top)
        BR.PROXY_SERVER = proxy_server
        self.config["start_url"] = url
        self.config["chrome_window"] = {"width": width, "height": height,
                                        "percent": percent, "fullscreen": False}
        fingerprint = self._resolve_fingerprint(params)
        self.browser.fingerprint = fingerprint
        self._save_state()
        self._push_state()
        return {"ok": True, "note": "Đã áp dụng cấu hình profile.",
                "proxy_enabled": bool(proxy_server), "width": width,
                "height": height, "scale": percent,
                "device": FP.describe(fingerprint),
                "fingerprint": {key: fingerprint.get(key) for key in
                                ("device", "android", "user_agent")}}

    def _resolve_fingerprint(self, params=None):
        """Return this profile's Android identity, generating one on first use.

        A profile keeps its identity between launches; ``regenerate_fingerprint``
        draws a new device, and an explicit ``fingerprint`` payload overrides it.
        """
        params = params or {}
        supplied = params.get("fingerprint")
        if isinstance(supplied, dict) and supplied.get("user_agent"):
            self.config["fingerprint"] = supplied
            return supplied
        current = self.config.get("fingerprint")
        major = "157"
        try:
            detected = (BR.chrome_version() or "").split(".")[0]
            if detected.isdigit():
                major = detected
        except Exception:
            pass
        if params.get("regenerate_fingerprint"):
            fresh = FP.regenerate(current, chrome_major=major)
            self.config["fingerprint"] = fresh
            return fresh
        if not isinstance(current, dict) or not current.get("user_agent"):
            fresh = FP.generate(chrome_major=major)
            self.config["fingerprint"] = fresh
            return fresh
        return current

    def fingerprint_info(self, params=None):
        """Current device identity plus a regenerated one on request."""
        params = params or {}
        fingerprint = self._resolve_fingerprint(params)
        self.browser.fingerprint = fingerprint
        self._save_state()
        return {"ok": True, "device": FP.describe(fingerprint),
                "fingerprint": {key: fingerprint.get(key) for key in
                                ("device", "android", "user_agent", "cores",
                                 "memory", "webgl_renderer", "canvas_seed")}}

    def fingerprint_regenerate(self, params=None):
        params = dict(params or {})
        params["regenerate_fingerprint"] = True
        result = self.fingerprint_info(params)
        if result.get("ok"):
            self._push_state()
        return result

    def febet_current_table(self, params=None):
        params = params or {}
        try:
            wait = max(0.0, min(15.0, float(params.get("wait", 15.0))))
        except (TypeError, ValueError):
            wait = 0.0
        with self.browser.lock:
            return FEBET.current_table(self.browser.driver, wait=wait)

    def febet_lobby_tables(self, params=None):
        params = params or {}
        try:
            wait = max(0.0, min(25.0, float(params.get("wait", 25.0))))
        except (TypeError, ValueError):
            wait = 0.0
        with self.browser.lock:
            return FEBET.lobby_tables(self.browser.driver, wait=wait)

    def febet_sync_table(self, params):
        with self.browser.lock:
            return FEBET.sync_table(self.browser.driver, (params or {}).get("table_id"),
                                    wait=30.0, settle=120.0)

    def febet_bet_state(self, _params=None):
        with self.browser.lock:
            return FEBET.bet_state(self.browser.driver, wait=0.0)

    def febet_stage_bet(self, params):
        params = params or {}
        with self.browser.lock:
            return FEBET.stage_bet(
                self.browser.driver, params.get("side"), params.get("amount_k"),
                params.get("round_id"), confirm=bool(params.get("confirm")), wait=0.0)

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

    def leave_table(self):
        """Rời bàn hiện tại về sảnh."""
        if not self.tool_running:
            return {"ok": False, "error": "Tool chưa chạy nên không tự rời bàn."}
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
        self.log("Chạy tool: tự vào bàn, theo dõi và đặt cược từng tay.")
        self._push_state()
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
            changed = self._process_sim(self.tables.get(self.sim.table_key)) if self.sim.table_key else False
        if changed:
            self._save_state()
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
        if self._dg_mode():
            return self._dg_read_chips()
        try:
            return TB.read(self.browser, unit=TB.DEFAULT_CHIP_UNIT)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _dg_mode(self):
        """Chrome đang ở sảnh DG (``ddnewpc``/``ddnewwap``) chứ không phải WM/EVO."""
        if getattr(self.browser, "wm_page_id", None):
            return False
        try:
            return find_dg_page(getattr(BR, "CDP_PORT", 9222)) is not None
        except Exception:
            return False

    def _dg_read_chips(self):
        """Chip của chính mình đang treo trên bàn DG, đúng định dạng ``table_bets.read``.

        DG báo tiền theo ``betMoneyTmp`` (chip đã xếp, chờ xác nhận) và ``betMoneyTrue``
        (đã xác nhận). ``table_is_clear`` cần biết cả hai nên cộng lại; nếu chỉ đọc
        ``True`` thì lúc chip đang chờ sẽ bị coi là "bàn trống" và lệnh sau bấm chồng.
        """
        try:
            state = FEBET.bet_state(self.browser.driver, wait=0.0)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "spots": {}, "unit": 1,
                    "denominations": [], "ts": time.time()}
        if not state.get("ok"):
            return {"ok": False, "error": state.get("error") or "Chưa đọc được bàn DG.",
                    "spots": {}, "unit": 1, "denominations": [], "ts": time.time()}
        pending = state.get("pending") or {}
        confirmed = state.get("confirmed") or {}
        spots = {}
        for side in ("B", "P", "T"):
            amount = float(pending.get(side) or 0) + float(confirmed.get(side) or 0)
            spots[side] = {"amount": amount, "amount_vnd": amount, "chips": 0}
        total = sum(item["amount"] for item in spots.values())
        return {"ok": True, "error": "", "source": "dg", "spots": spots,
                "total": total, "total_units": total,
                "denominations": state.get("denominations_k") or [],
                "unit": 1, "wallet": "", "countdown": state.get("countdown") or "",
                "open_result": not bool(state.get("bet_open")),
                "ts": time.time(),
                "note": "Chip của bạn đang treo trên bàn DG (1 đv = 1.000đ)."}

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

    def _auto_bet_tick(self):
        """Xếp chip cho cửa đã chọn, mỗi ván một lần, khi tool đang chạy."""
        if not self.tool_running:
            return
        if not self.sim.running:
            # Sim bị pause (dữ liệu cũ / không đặt được chip): hiện đúng lý do pause,
            # không để ghi chú cũ treo trên UI gây hiểu lầm.
            if self.sim.table_key and self.sim.note:
                self.auto_bet_note = self.sim.note
            return
        if not self.config["auto_place"]:
            return
        if self.place_busy or self.sim.pending or self.sim.entry_waiting:
            return
        if not self.sim.table_key:
            return
        letters = self.sim.letters
        if letters == self.auto_bet_letters and self.sim.table_key == self.auto_bet_key:
            return
        # Số tay của lệnh sắp đặt: đếm theo cầu đã đọc của bàn (không cần bộ đọc khung).
        hand_no = len(letters) + 1
        # Số tay phải tăng dần trong một bàn: bản phát lại/lịch sử về muộn không được
        # arm lệnh cho tay cũ hơn tay đã chốt.
        if self.sim.table_key == self.auto_bet_key and self.auto_bet_hand \
                and hand_no <= self.auto_bet_hand:
            self.auto_bet_letters = letters
            self.auto_bet_note = "Tay này đã được xử lý · chờ tay kế."
            return
        # Chốt an toàn chống đặt trùng cho cùng một tay của cùng một bàn.
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
            note = "Chưa chọn được cửa; sẽ thử lại ở nhịp sau."
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

                if self._dg_mode():
                    # DG: chip được xếp đúng mệnh giá, đọc lại từng bước bên trong Laya
                    # rồi mới xác nhận, nên không bao giờ đặt thiếu/lệch mệnh giá.
                    round_id = ""
                    try:
                        state = FEBET.bet_state(self.browser.driver, wait=0.0)
                        round_id = str(state.get("round_id") or "")
                    except Exception:
                        round_id = ""
                    if not round_id:
                        self.events.put(("placed", (
                            False, "Không đọc được mã ván DG; chưa bấm chip.", plan)))
                        return
                    result = FEBET.stage_bet(
                        self.browser.driver, side, int(round(stake)), round_id,
                        confirm=bool(self.config.get("auto_confirm", True)),
                        wait=BET_GATE_TIMEOUT)
                    if result.get("ok") and result.get("confirmed"):
                        plan["placed_at"] = time.time()
                    note = result.get("error") or ""
                    if not note:
                        note = ("Đã xếp và xác nhận %sk vào %s ở ván %s."
                                % (int(round(stake)), E.SIDE_NAME.get(side, side), round_id))
                    self.events.put(("placed", (bool(result.get("ok")
                                                     and result.get("confirmed")), note, plan)))
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
        """Chờ bàn gom hết chip ván trước rồi mới bấm (tránh bấm chồng ván cũ).

        DG khác WM/EVO: cổng cược được bảo vệ bằng ``stateId``/``countDown`` và mã ván
        ngay trong Laya (``stage_bet`` từ chối khi ván đã đổi), còn chip chờ xác nhận
        được đọc lại từng mệnh giá. Vì vậy ở đây chỉ cần xác nhận còn đọc được bàn;
        dùng ``table_is_clear`` cho DG sẽ chặn oan vì DG giữ chip đã xác nhận trên ô
        suốt ván.
        """
        if self._dg_mode():
            state = self._read_chip_state()
            if state.get("ok"):
                return True, ""
            return False, ("Không tự đặt: chưa đọc được bàn DG (%s)."
                           % (state.get("error") or "no_read"))
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
                        "auto_hunt", "auto_confirm"):
                if key in params:
                    config[key] = bool(params[key])
                    changed.append(key)
            for key in ("bet_side", "bet_stake"):
                if key in params:
                    config[key] = params[key]
                    changed.append(key)
            if "start_url" in params:
                config["start_url"] = params["start_url"]
                changed.append("start_url")

            normalized = self._normalize_config(config)
            self.config = normalized
            self.bet_config = {"side": normalized["bet_side"], "stake": normalized["bet_stake"]}
            self.stream.human_mouse = normalized["human_mouse"]
            self._save_state()

        self.log("Đã lưu cấu hình: %s." % (", ".join(sorted(set(changed))) or "không đổi"))
        self._push_state()
        return {"ok": True, "note": "Đã lưu cấu hình.", "changed": sorted(set(changed))}

    # ---------------------------------------------------------------- phiên
    def session_reset(self):
        """Reset phiên: quên bàn đang theo dõi, giữ cấu hình và lệnh cược hiện tại."""
        with self.lock:
            self.sim = self._build_sim()
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            self.auto_start_key = None
            self.chip_live = None
            self.placed_signatures = set()
        self._save_state()
        self.log("Đã reset phiên Baccarat.")
        self._push_state()
        return {"ok": True, "note": "Đã reset phiên."}

    def session_new(self, params):
        """Tạo phiên mới từ lệnh cược mới (lưu bản sao state cũ)."""
        params = params or {}
        with self.lock:
            config = dict(self.config)
            for key in ("bet_side", "bet_stake"):
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
            self.sim = self._build_sim()
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.chip_live = None
            self.last_order = None
            self.placed_signatures = set()
        self._save_state()
        self.log("Đã tạo phiên mới: cược %s %s đv." % (
            self.config["bet_side"], M.fmt_money(self.config["bet_stake"])))
        self._push_state()
        return {"ok": True, "note": "Đã tạo phiên mới."}


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
        if ok:
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            with self.lock:
                self.sim.detach("Đã rời bàn · đang ở sảnh.")
            self.lobby_sweep()
        elif self._auth_blame():
            self._session_lost(note)
        else:
            self.cycle_waiting = True
            self.cycle_retry_at = time.time() + CYCLE_RETRY_SECONDS
            self.sweep_note = "%s · sẽ thử đóng bàn lại sau %d giây." % (note, CYCLE_RETRY_SECONDS)

    def _session_lost(self, note):
        self.session_lost = True
        self.cycle_waiting = False
        self.cycle_attempts = 0
        self.cycle_retry_at = 0.0
        self.cycle_table_key = None
        self.auto_start_key = None
        with self.lock:
            self.sim.pause("Sảnh báo phiên đăng nhập không còn hợp lệ. Đăng nhập lại trang gốc "
                           "rồi bấm “VÀO BÀN HỢP LỆ”.")
        self.auto_bet_letters = None
        self.auto_bet_key = None
        self.auto_bet_hand = 0
        self.auto_bet_note = "Mất phiên đăng nhập · đã dừng đặt. Đăng nhập lại rồi chạy tool."
        self.sweep_note = note
        self.log("Mất phiên: " + note, "error")

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
        # Đã hết lượt thử rồi thì dừng vòng săn, không lặp vô hạn.
        max_attempts = int(self.config.get("cycle_max_attempts", CYCLE_MAX_ATTEMPTS) or CYCLE_MAX_ATTEMPTS)
        if self.cycle_attempts >= max_attempts:
            self.cycle_waiting = False
            self.cycle_retry_at = 0.0
            self.cycle_table_key = None
            self.sweep_note = ("Đã quét %d lượt mà không tìm được bàn; dừng tự săn. "
                               "Mở sảnh và chọn bàn thủ công, hoặc bấm lại “TÌM BÀN”." % self.cycle_attempts)
            self.log(self.sweep_note, "error")
            return False
        first_attempt = self.cycle_attempts == 0
        self.cycle_attempts += 1
        wait = 0 if first_attempt else CYCLE_RETRY_SECONDS
        self.cycle_retry_at = time.time() + wait
        self.sweep_note = ("%s · quét lại ngay…" % reason if first_attempt else
                          "%s · tự quét lại sau %d giây (đã thử %d/%d lượt)." % (
                              reason, CYCLE_RETRY_SECONDS, self.cycle_attempts, max_attempts))
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
            if key == self.sim.table_key:
                # Lượt quét CDP bắt đầu trước khi ván mới về sẽ trả cầu ngắn hơn cầu
                # đang theo dõi. Nhận nó là "Cầu đổi nguồn" oan → huỷ lệnh đang chờ chip;
                # nên với bàn đang theo dõi, giữ cầu đã biết nếu bản mới ngắn hơn.
                known = str((self.tables.get(key) or {}).get("letters") or "")
                if known and len(letters) < len(known) and known.startswith(letters):
                    letters = known
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
        if self.sim.running:
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
        # Vào bàn xong là theo dõi luôn; không đồng bộ ví, không chặn theo vốn.
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
        manual_enter = bool(self.enter_valid)
        if not (self.cycle_waiting and (self.config["auto_hunt"] or manual_enter)
                and self.cycle_retry_at and now >= self.cycle_retry_at):
            return
        self.cycle_retry_at = 0.0
        if self.sim.running or self.auto_start_key:
            return
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
            changed = self._process_sim(self.tables.get(self.sim.table_key))
        if changed:
            self._save_state()

    def _tick(self):
        self._drain()
        if not self.browser.connected:
            # Nút “VÀO BÀN HỢP LỆ” gắn Chrome ở thread riêng: lần đầu chưa có kết nối là
            # bình thường, không được coi là "Chrome đã đóng" rồi huỷ chế độ vừa bật.
            if not (self.enter_valid and not self.had_chrome):
                self._on_chrome_lost()
        else:
            self._on_chrome_ready()
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

    def bet_ladder_config_set(self, params):
        """Save ladder and participation/turnover/table-cycle limits."""
        params = params or {}
        with self.lock:
            config = dict(self.config)
            config["stakes"] = parse_stakes(params.get("stakes", config["stakes"]))
            for key in ("min_t", "max_t", "min_tk", "total_bet", "hop_max"):
                if key in params:
                    config[key] = params[key]
            if "hop_min" in params:
                config["hop_min"] = params["hop_min"]
            normalized = self._normalize_config(config)
            side = str(params.get("side", self.bet_config["side"])).strip().upper()
            if side not in ("P", "B", "T"):
                return {"ok": False, "error": "Cửa cược phải là P, B hoặc T."}
            self.config = normalized
            self.bet_ladder.configure(normalized["stakes"], normalized["min_t"],
                                      normalized["max_t"], step=0)
            stake = self.bet_ladder.current_stake
            self.bet_config = {"side": side, "stake": stake}
            self.config["bet_side"] = side
            self.config["bet_stake"] = stake
        self._save_state()
        self._push_state()
        return {"ok": True, "side": side, "stake": stake,
                "step": self.bet_ladder.step,
                "stakes": list(self.bet_ladder.stakes),
                "min_tk": self.config["min_tk"],
                "total_bet": self.config["total_bet"],
                "hop_min": self.config["hop_min"],
                "hop_max": self.config["hop_max"],
                "note": "Đã lưu dãy cược và cấu hình cho profile."}

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
                return {"ok": False, "error": "Chưa có cửa để đặt: hãy chọn P/B/T trong cấu hình cược."}
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
            "chrome.attachOmni": self.chrome_attach_omni,
            "chrome.attachExternal": self.chrome_attach_external,
            "site.open": self.site_open,
            "profile.configure": self.profile_configure,
            "fingerprint.info": self.fingerprint_info,
            "fingerprint.regenerate": self.fingerprint_regenerate,
            "febet.table": self.febet_current_table,
            "febet.tables": self.febet_lobby_tables,
            "febet.syncTable": self.febet_sync_table,
            "dg.table": self.febet_current_table,
            "dg.tables": self.febet_lobby_tables,
            "dg.syncTable": self.febet_sync_table,
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
            "table.leave": lambda p: self.leave_table(),
            "tool.start": lambda p: self.tool_start(),
            "tool.stop": lambda p: self.tool_stop(),
            "scan": lambda p: self.scan_now(),
            "chips.read": lambda p: self.chips_read(),
            "config.get": lambda p: dict(self.config),
            "config.set": self.config_set,
            "session.reset": lambda p: self.session_reset(),
            "session.new": self.session_new,
            "log.clear": lambda p: {"ok": True},
            "bet.config": self.bet_config_set,
            "bet.ladder.configure": self.bet_ladder_config_set,
            "bet.place": lambda p: self.bet_place(),
            "febet.betState": self.febet_bet_state,
            "febet.stageBet": self.febet_stage_bet,
            "dg.betState": self.febet_bet_state,
            "dg.stageBet": self.febet_stage_bet,
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
            self._save_state()
        except Exception:
            pass
        try:
            self.browser.stop()
        except Exception:
            pass
