# -*- coding: utf-8 -*-
"""Chạy live: gắn tab bàn Petalive, cập nhật shoe, in dự đoán trước mỗi ván.

    python tools/bcr_live.py                       # gắn tab đang mở (CDP 9222)
    python tools/bcr_live.py --decks 8 --trials 30000
    python tools/bcr_live.py --ai                  # gọi API AI nếu có BCR_AI_KEY
    python tools/bcr_live.py --table BCR_VV77842   # chỉ theo một bàn

Mỗi ván in: lá bài hai bên (kèm điểm), cửa thắng, xác suất/EV cho ván kế, và thời
điểm đưa ra dự đoán (trước khi ván mới chia) để bạn so với cửa sổ cược thật.
"""

import argparse
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aibcr.live import ai, cards, decode, predict
from aibcr.live.reader import LiveReader

RECENT_LIMIT = 40


def emit(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def fmt_hand(card_ids):
    return " ".join("%s(%d)" % (cards.card_label(card), cards.card_value(card))
                    for card in card_ids)


class Session:
    """Trạng thái một bàn: shoe, lịch sử B/P/T, dự đoán gần nhất."""

    def __init__(self, decks=8, trials=20000, markov_weight=0.15, table="", use_ai=False,
                 ai_every=5, seed=None):
        self.shoe = cards.Shoe(decks)
        self.trials = trials
        self.markov_weight = markov_weight
        self.table = table
        self.use_ai = use_ai
        self.ai_every = max(1, ai_every)
        self.seed = seed
        self.history = ""
        self.rounds = []
        self.prediction = None
        self.issue_seen = None
        self.duplicates = 0
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ ván mới
    def on_round(self, data):
        if self.table and data.get("table") != self.table:
            return
        with self.lock:
            # Cùng issueId phát lại nhiều lần (reconnect/mở lại tab) không được cộng
            # lá vào shoe lần thứ hai.
            if data.get("issue_id") and data["issue_id"] == self.issue_seen:
                self.duplicates += 1
                return
            self.issue_seen = data.get("issue_id")
            self.table = self.table or data.get("table") or ""
            before = self.prediction
            verdict = predict.advance_round(self.shoe, data["player_cards"],
                                            data["banker_cards"])
            winner = data.get("winner") or verdict["winner"]
            self.history += winner
            self.history = self.history[-400:]
            self.rounds.append(dict(data, **verdict))
            self.rounds = self.rounds[-RECENT_LIMIT:]
            self._print_round(data, verdict, winner, before)
            self._print_prediction()

    def _print_round(self, data, verdict, winner, before):
        stamp = time.strftime("%H:%M:%S")
        p_cards = fmt_hand(data["player_cards"])
        b_cards = fmt_hand(data["banker_cards"])
        hit = ""
        if before and before.get("ok") and before.get("best_side"):
            hit = " · dự đoán trước: %s %s" % (
                before["best_side"], "ĐÚNG" if before["best_side"] == winner else "SAI")
        elif before and before.get("ok"):
            hit = " · trước đó đã khuyên bỏ tay"
        emit("[%s] %s · P %s = %d · B %s = %d → %s%s" % (
            stamp, data.get("table") or "?", p_cards, verdict["player_total"],
            b_cards, verdict["banker_total"], winner, hit))
        if verdict.get("warning"):
            emit("   ! %s" % verdict["warning"])

    def _print_prediction(self):
        with self.lock:
            result = predict.predict(self.shoe, self.history, trials=self.trials,
                                     markov_weight=self.markov_weight, seed=self.seed)
            self.prediction = result
        if not result.get("ok"):
            emit("   dự đoán: %s" % result.get("error"))
            return
        probs = result["probabilities"]
        ev = result["ev"]
        emit("   → ván kế: P %.2f%% (EV %+.4f) · B %.2f%% (EV %+.4f) · T %.2f%% (EV %+.4f)"
             % (probs["p_player"] * 100, ev["P"], probs["p_banker"] * 100, ev["B"],
                probs["p_tie"] * 100, ev["T"]))
        emit("     %s · shoe còn %d lá (%.1f%% đã chia)" % (
            result["recommendation"], result["shoe"]["remaining"],
            result["shoe"]["penetration"] * 100))
        if self.use_ai and ai.available() and len(self.rounds) % self.ai_every == 0:
            reply = ai.analyze(result, recent_rounds=[
                {"hand": index + 1, "winner": item.get("winner"),
                 "player": item["player_cards"], "banker": item["banker_cards"]}
                for index, item in enumerate(self.rounds[-8:])], table=self.table)
            emit("     AI: %s" % (reply.get("text") if reply.get("ok") else reply.get("error")))

    def on_state(self, state):
        if self.table and state.get("table") != self.table:
            return
        if state.get("state") in ("SHOW_RESULT", "WAITING_SHOW_RESULT"):
            return
        if state.get("time_remains") in (None, ""):
            return

    def on_status(self, text, level="info"):
        emit("· %s" % text)


def main(argv=None):
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--table", default="", help="chỉ theo một bàn, vd BCR_VV77842")
    parser.add_argument("--decks", type=int, default=8, help="số bộ bài của shoe (mặc định 8)")
    parser.add_argument("--trials", type=int, default=20000, help="số ván Monte Carlo")
    parser.add_argument("--markov-weight", type=float, default=0.15,
                        help="trọng số Markov khi trộn với Monte Carlo (0 = tắt)")
    parser.add_argument("--seconds", type=float, default=0, help="0 = chạy tới Ctrl+C")
    parser.add_argument("--ai", action="store_true", help="gọi API AI nếu có BCR_AI_KEY")
    parser.add_argument("--ai-every", type=int, default=5, help="gọi AI mỗi N ván")
    args = parser.parse_args(argv)

    session = Session(decks=args.decks, trials=args.trials,
                      markov_weight=args.markov_weight, table=args.table,
                      use_ai=args.ai, ai_every=args.ai_every)
    stop = threading.Event()
    reader = LiveReader(on_round=session.on_round, on_state=session.on_state,
                        on_status=session.on_status, port=args.port, stop=stop)
    emit("Đang chờ kết quả BCR từ tab Petalive (CDP %d)…" % args.port)
    if args.ai and not ai.available():
        emit("(Chưa có BCR_AI_KEY — bỏ qua phần AI.)")
    reader.start()
    ended = time.monotonic() + args.seconds if args.seconds > 0 else None
    try:
        while reader.is_alive():
            if ended is not None and time.monotonic() >= ended:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        emit("\nDừng theo yêu cầu.")
    finally:
        stop.set()
        reader.join(timeout=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
