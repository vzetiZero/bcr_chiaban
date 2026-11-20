# -*- coding: utf-8 -*-
"""Trạng thái một bàn Petalive dùng chung cho CLI và Electron.

Tách từ ``tools/bcr_live.py`` để hai luồng (terminal và UI) cùng dùng một cơ chế:

    khung WS -> decode -> on_round() -> Shoe -> predict.predict() -> snapshot()

AI được gọi **bất đồng bộ** trong thread daemon: vòng đọc WebSocket và vòng điều
phối của controller không bao giờ bị chặn bởi timeout của API.
"""

import math
import threading
import time

from aibcr.live import ai, cards, predict, road

RECENT_LIMIT = 40
HISTORY_LIMIT = 400
# Số ván cuối của lịch sử nạp về mới được trừ khỏi shoe: shoe thật đã chia hết
# từ lâu sau vài trăm tay, mô phỏng lại toàn bộ sẽ làm số lá còn lại sai.
SEED_SHOE_LIMIT = 40


def _num(value):
    """Số hữu hạn để Electron JSON không nhận NaN/Infinity."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    """Số nguyên an toàn cho số tay (bỏ bool/chuỗi rác)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


class LiveSession:
    """Một bàn: shoe, lịch sử B/P/T, dự đoán gần nhất và nhận định AI."""

    def __init__(self, decks=8, trials=predict.DEFAULT_TRIALS,
                 markov_weight=predict.DEFAULT_MARKOV_WEIGHT, table="",
                 ai_mode="off", ai_url="", ai_model="", ai_key="", ai_every=5, ai_timeout=8,
                 on_prediction=None, on_status=None):
        self.shoe = cards.Shoe(decks)
        self.decks = int(decks)
        self.trials = int(trials)
        self.markov_weight = float(markov_weight)
        self.table = str(table or "")
        self.ai_mode = str(ai_mode or "off")
        self.ai_url = str(ai_url or "")
        self.ai_model = str(ai_model or "")
        # Chỉ nằm trong RAM; env BCR_AI_KEY là mặc định khi rỗng.
        self.ai_key = str(ai_key or "")
        self.ai_every = max(1, int(ai_every))
        self.ai_timeout = max(2, int(ai_timeout))
        self.on_prediction = on_prediction
        self.on_status = on_status

        self.history = ""
        self.rounds = []
        # Mã shoe (WM: gameNo). Đổi shoe thì phải xoá cầu/shoe cũ, nếu không số tay
        # và xác suất sẽ trộn hai shoe vào nhau.
        self.shoe_id = None
        # Chống nhân đôi: protocol 26 phát lại lịch sử sau protocol 25 nên cùng một ván
        # có thể tới hai lần; khoá theo (game_no, gameNoRound) hoặc theo bộ lá.
        self._row_keys = set()
        self._seed_rows = []
        self.state = None
        self.prediction = None
        self.analysis = None
        self.issue_seen = None
        self.duplicates = 0
        # Số tay của bàn (WM gửi gameNoRound; Petalive không có nên đếm theo lịch sử).
        self.hand_no = 0
        self.ai_busy = False
        self.ai_error = ""
        self.running = False
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ cấu hình
    def configure(self, **kwargs):
        """Cập nhật cấu hình từ UI mà không tạo lại shoe/lịch sử."""
        allowed = ("decks", "trials", "markov_weight", "ai_mode", "ai_url",
                   "ai_model", "ai_key", "ai_every", "ai_timeout")
        with self.lock:
            for key in allowed:
                if key in kwargs and kwargs[key] is not None:
                    setattr(self, key, kwargs[key])
            self.ai_every = max(1, int(self.ai_every))
            self.ai_timeout = max(2, int(self.ai_timeout))

    def _ai_cfg(self):
        return {"mode": self.ai_mode, "url": self.ai_url, "model": self.ai_model,
                "key": self.ai_key, "timeout": self.ai_timeout}

    def _notify(self):
        if self.on_prediction is None:
            return
        try:
            self.on_prediction(self.snapshot())
        except Exception:
            pass

    def _status(self, text, level="info"):
        if self.on_status is None:
            return
        try:
            self.on_status(text, level)
        except Exception:
            pass

    # ------------------------------------------------------------------ ván mới
    def reset_table(self, table):
        """Đổi sang bàn khác: xoá shoe/lịch sử cũ để không trộn hai bàn vào một cầu."""
        with self.lock:
            self.shoe = cards.Shoe(self.decks)
            self.history = ""
            self.rounds = []
            self.prediction = None
            self.analysis = None
            self.issue_seen = None
            self.duplicates = 0
            self.table = str(table or "")
            self.state = None
            self.hand_no = 0
            self.shoe_id = None
            self._row_keys = set()
            self._seed_rows = []

    # ------------------------------------------------------- gộp ván không trùng
    @staticmethod
    def _row_key(data):
        """Khoá duy nhất của một ván trong shoe hiện tại."""
        game_no = data.get("game_no")
        round_no = _int(data.get("round"))
        if game_no is not None and round_no is not None:
            return ("r", str(game_no), round_no)
        if data.get("issue_id"):
            return ("i", str(data["issue_id"]))
        player = tuple(sorted(data.get("player_cards") or []))
        banker = tuple(sorted(data.get("banker_cards") or []))
        if player or banker:
            return ("c", player, banker)
        return ("empty", len(data.get("player_cards") or []),
                len(data.get("banker_cards") or []))

    def _adopt_shoe(self, data):
        """Cập nhật shoe đang chơi; trả True khi vừa chuyển sang shoe mới."""
        game_no = data.get("game_no")
        if game_no is None:
            return False
        game_no = str(game_no)
        if self.shoe_id is None:
            self.shoe_id = game_no
            return False
        if game_no == self.shoe_id:
            return False
        self.shoe = cards.Shoe(self.decks)
        self.shoe_id = game_no
        self.rounds = []
        self.history = ""
        self.prediction = None
        self.analysis = None
        self.issue_seen = None
        self._row_keys = set()
        self._seed_rows = []
        self.hand_no = 0
        return True

    def _refresh_history(self):
        self.history = "".join(row.get("winner") or "" for row in self.rounds)[-HISTORY_LIMIT:]

    @staticmethod
    def _round_value(row):
        value = _int(row.get("round"))
        return 10 ** 9 if value is None else value

    def _append_round(self, data):
        """Thêm một ván live (protocol 25) vào shoe/cầu; trả cảnh báo nếu có."""
        verdict = predict.advance_round(self.shoe, data.get("player_cards") or [],
                                        data.get("banker_cards") or [])
        winner = data.get("winner") or verdict.get("winner") or ""
        row = dict(data)
        row.update(verdict)
        row["winner"] = winner
        self.rounds.append(row)
        self.rounds = self.rounds[-HISTORY_LIMIT:]
        self._refresh_history()
        round_no = _int(data.get("round"))
        self.hand_no = round_no or max(self.hand_no, len(self.history))
        return verdict.get("warning") or ""

    def _merge_seed_rows(self, batch):
        """Ghép lịch sử cũ (protocol 26) vào cầu theo đúng thứ tự tay.

        Lịch sử có thể tới **sau** ván live đầu tiên; phải sắp lại theo số tay và bỏ
        các ván trùng, nếu không cầu bị nhân đôi và lệnh đang chờ chip bị huỷ.

        Cả shoe được nạp (tối đa ``HISTORY_LIMIT`` tay) để số tay và cầu khớp bàn,
        nhưng chỉ ``SEED_SHOE_LIMIT`` tay cuối được trừ khỏi shoe dự phòng.
        """
        batch = sorted(batch, key=self._round_value)
        recent = {id(data) for data in batch[-SEED_SHOE_LIMIT:]}
        for data in batch:
            if id(data) in recent:
                verdict = predict.advance_round(self.shoe, data.get("player_cards") or [],
                                                data.get("banker_cards") or [])
            else:
                verdict = {}
            row = dict(data)
            row.update(verdict)
            row["winner"] = data.get("winner") or verdict.get("winner") or ""
            self.rounds.append(row)
        self.rounds.sort(key=self._round_value)
        self.rounds = self.rounds[-HISTORY_LIMIT:]
        self._refresh_history()
        last = self._round_value(self.rounds[-1]) if self.rounds else None
        if last is not None and last < 10 ** 9:
            self.hand_no = max(self.hand_no, last)

    def on_round(self, data):
        incoming = data.get("table") or ""
        if self.table and incoming and incoming != self.table:
            self.reset_table(incoming)
        is_seed = bool(data.get("seed"))
        notify = False
        warning = ""
        with self.lock:
            self.table = self.table or incoming
            shoe_changed = self._adopt_shoe(data)
            notify = shoe_changed
            key = self._row_key(data)
            duplicate = key in self._row_keys
            if duplicate:
                self.duplicates += 1
            else:
                self._row_keys.add(key)
            if is_seed:
                if not duplicate:
                    self._seed_rows.append(dict(data))
                if data.get("seed_last"):
                    batch, self._seed_rows = self._seed_rows, []
                    if batch:
                        self._merge_seed_rows(batch)
                        notify = True
            elif not duplicate:
                warning = self._append_round(data)
                notify = True
            if not notify:
                return
            self.prediction = predict.predict(
                self.shoe, self.history, trials=self.trials,
                markov_weight=self.markov_weight)
        if warning:
            self._status(warning, "warn")
        self._notify()
        self._schedule_analysis()

    def on_state(self, state):
        incoming = state.get("table") or ""
        if self.table and incoming and incoming != self.table:
            # Đổi bàn: xoá cầu/shoe cũ để số tay và xác suất không dính bàn trước.
            self.reset_table(incoming)
        with self.lock:
            old_state = (self.state or {}).get("state")
            old_round = (self.state or {}).get("round")
            self.state = dict(state)
            self.table = self.table or state.get("table") or ""
            round_no = _int(state.get("round"))
            if round_no:
                self.hand_no = round_no
            changed = (old_state != state.get("state") or old_round != state.get("round"))
        # Đẩy UI ngay khi pha cược đổi hoặc số tay đổi; không bắn theo từng tick
        # betMilliSecond để khỏi spam sự kiện.
        if changed:
            self._notify()

    # ---------------------------------------------------------------------- AI
    def _analysis_input(self):
        """Chụp dữ liệu dưới lock rồi đưa sang thread AI."""
        with self.lock:
            return {
                "prediction": self.prediction,
                "recent_rounds": [{
                    "hand": index + 1,
                    "winner": item.get("winner"),
                    "player": item.get("player_cards"),
                    "banker": item.get("banker_cards"),
                } for index, item in enumerate(self.rounds[-8:])],
                "table": self.table,
                "state": (self.state or {}).get("state", ""),
                "time_remains": (self.state or {}).get("time_remains"),
                "history": self.history,
                "round": int(self.hand_no or len(self.rounds)),
            }

    def _schedule_analysis(self):
        cfg = ai.config(self._ai_cfg())
        if not ai.available(cfg):
            return
        with self.lock:
            if self.ai_busy or not self.prediction or not self.ai_every:
                return
            if self.ai_every > 1 and len(self.rounds) % self.ai_every != 0:
                return
            self.ai_busy = True
        payload = self._analysis_input()
        threading.Thread(target=self._run_analysis, args=(payload,),
                         daemon=True, name="bcr-live-ai").start()

    def _run_analysis(self, payload):
        try:
            result = ai.analyze_structured(
                payload["prediction"], recent_rounds=payload["recent_rounds"],
                table=payload["table"], state=payload["state"],
                time_remains=payload["time_remains"], history=payload["history"],
                timeout=self.ai_timeout, cfg=self._ai_cfg())
            result = dict(result)
        except Exception as exc:
            result = {"ok": False, "error": "Lỗi AI: %s" % type(exc).__name__}
        with self.lock:
            self.ai_busy = False
            self.ai_error = "" if result.get("ok") else str(result.get("error") or "")
            if result.get("ok"):
                result["round"] = payload["round"]
                result["at"] = time.time()
                self.analysis = result
        self._notify()

    def analyze_now(self):
        """Nút “Phân tích ngay”: gọi đồng bộ, trả kết quả cho RPC."""
        payload = self._analysis_input()
        if not payload["prediction"]:
            return {"ok": False, "error": "Chưa có ván nào để phân tích."}
        cfg = ai.config(self._ai_cfg())
        if not ai.available(cfg):
            return {"ok": False, "error": "Chưa cấu hình AI (chế độ/key/endpoint)."}
        result = ai.analyze_structured(
            payload["prediction"], recent_rounds=payload["recent_rounds"],
            table=payload["table"], state=payload["state"],
            time_remains=payload["time_remains"], history=payload["history"],
            timeout=self.ai_timeout, cfg=self._ai_cfg())
        result = dict(result)
        with self.lock:
            self.ai_error = "" if result.get("ok") else str(result.get("error") or "")
            if result.get("ok"):
                result["round"] = payload["round"]
                result["at"] = time.time()
                self.analysis = result
        self._notify()
        return result

    # ------------------------------------------------------------------ snapshot
    def snapshot(self):
        with self.lock:
            pred = self.prediction
            probabilities = {}
            ev = {}
            uncertainty = {}
            if pred:
                probabilities = {key: _num(value) for key, value in
                                 (pred.get("probabilities") or {}).items()}
                ev = {key: _num(value) for key, value in (pred.get("ev") or {}).items()}
                uncertainty = {key: _num(value) for key, value in
                               (pred.get("ev_uncertainty") or {}).items()}
                shoe = pred.get("shoe") if isinstance(pred.get("shoe"), dict) else {}
                shoe_view = {"remaining": _num(shoe.get("remaining")),
                             "penetration": _num(shoe.get("penetration"))}
            else:
                shoe_view = {"remaining": None, "penetration": None}
            prediction_view = None
            if pred:
                prediction_view = {
                    "ok": bool(pred.get("ok")),
                    "error": pred.get("error"),
                    "probabilities": probabilities,
                    "ev": ev,
                    "ev_uncertainty": uncertainty,
                    "best_side": pred.get("best_side"),
                    "least_bad_side": pred.get("least_bad_side"),
                    "top_side": pred.get("top_side"),
                    "top_probability": _num(pred.get("top_probability")),
                    "pattern_note": pred.get("pattern_note"),
                    "patterns": pred.get("patterns"),
                    "playable": bool(pred.get("playable")),
                    "recommendation": pred.get("recommendation"),
                    "trials": pred.get("trials"),
                    "shoe": shoe_view,
                }
            cfg = ai.config(self._ai_cfg())
            last_row = self.rounds[-1] if self.rounds else {}
            return {
                "ok": bool(pred and pred.get("ok")),
                "running": bool(self.running),
                "table": self.table,
                "state": (self.state or {}).get("state", "") if self.state else "",
                "time_remains": (self.state or {}).get("time_remains") if self.state else None,
                "rounds": len(self.rounds),
                "hand": max(int(self.hand_no or 0), len(self.history)),
                # Tay của ván vừa có kết quả (số tay thật của bàn); lệnh tay kế = +1.
                "result_hand": _int(last_row.get("round")),
                "duplicates": self.duplicates,
                "history": self.history[-400:],
                "history_tail": self.history[-60:],
                "road": road.big_road(self.history),
                "prediction": prediction_view,
                "analysis": dict(self.analysis) if isinstance(self.analysis, dict) else None,
                "ai": {
                    "mode": cfg["mode"],
                    "url": cfg["url"] if cfg["mode"] == "local" else "",
                    "model": cfg["model"],
                    "available": ai.available(cfg),
                    "busy": bool(self.ai_busy),
                    "error": self.ai_error,
                },
                "config": {
                    "decks": self.decks,
                    "trials": self.trials,
                    "markov_weight": _num(self.markov_weight),
                    "ai_every": self.ai_every,
                    "ai_timeout": self.ai_timeout,
                },
            }
