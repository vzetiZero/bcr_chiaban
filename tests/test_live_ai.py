# -*- coding: utf-8 -*-
"""Kiểm thử luồng AI local/API nối vào UI: prompt, schema, chặn override, RPC.

Không gọi mạng thật: ``urlopen`` được mock. Key trong test là chuỗi giả, không phải
key thật — repo không chứa API key.
"""

import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aibcr.controllers.baccarat import BaccaratController
from aibcr.live import ai
from aibcr.live.session import LiveSession

ROUND = {
    "issue_id": "BCR_VV77845-261119-0514",
    "table": "BCR_VV77845",
    "player_cards": [28, 32, 5],
    "banker_cards": [37, 41, 49],
    "winner": "B",
    "bets": [],
}

PREDICTION = {
    "ok": True,
    "probabilities": {"p_player": 0.44, "p_banker": 0.46, "p_tie": 0.10},
    "ev": {"P": -0.01, "B": -0.002, "T": -0.18},
    "ev_uncertainty": {"P": 0.008, "B": 0.008, "T": 0.004},
    "best_side": None,
    "least_bad_side": "B",
    "playable": False,
    "recommendation": "Bỏ tay: EV âm.",
    "trials": 600,
    "shoe": {"remaining": 410, "penetration": 0.015},
}


class FakeResponse:
    def __init__(self, content):
        self.content = content if isinstance(content, str) else json.dumps(content)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.content.encode("utf-8", "replace")


def api_reply(content):
    return {"choices": [{"message": {"content": content}}]}


class AiConfigTests(unittest.TestCase):
    def setUp(self):
        cleaner = patch.dict(os.environ, {
            "BCR_AI_KEY": "", "BCR_AI_MODE": "", "BCR_AI_URL": "",
            "BCR_AI_MODEL": "", "BCR_AI_TIMEOUT": "",
        })
        cleaner.start()
        self.addCleanup(cleaner.stop)

    def test_modes(self):
        self.assertFalse(ai.available(ai.config({"mode": "off"})))
        self.assertTrue(ai.available(ai.config({
            "mode": "local", "url": "http://127.0.0.1:11434/v1/chat/completions"})))
        self.assertFalse(ai.available(ai.config({"mode": "api", "key": ""})))
        self.assertTrue(ai.available(ai.config({"mode": "api", "key": "dummy"})))

    def test_base_url_builds_chat_completions_endpoint(self):
        self.assertEqual(ai.completion_url("https://api.example.test/v1"),
                         "https://api.example.test/v1/chat/completions")
        self.assertEqual(ai.completion_url(
            "https://api.example.test/v1/chat/completions"),
            "https://api.example.test/v1/chat/completions")
        self.assertEqual(ai.completion_url("http://localhost:11434"),
                         "http://localhost:11434/v1/chat/completions")
        self.assertEqual(ai.completion_url("file:///tmp/model"), "")

    def test_check_model_uses_entered_key_and_does_not_return_it(self):
        fake = FakeResponse({"model": "demo-model", "choices": [
            {"message": {"content": "OK"}}]})
        with patch.object(ai, "urlopen", return_value=fake) as mocked:
            result = ai.check_model({"mode": "api", "url": "https://api.example.test/v1",
                                     "model": "demo-model", "key": "dummy-secret"})
        request = mocked.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertEqual(request.full_url,
                         "https://api.example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy-secret")
        self.assertNotIn("key", result)
        self.assertNotIn("dummy-secret", repr(result))

    def test_check_model_reports_invalid_key_without_echoing_request_data(self):
        error = HTTPError("https://api.example.test/v1/chat/completions", 401,
                          "unauthorized", {}, None)
        with patch.object(ai, "urlopen", side_effect=error):
            result = ai.check_model({"mode": "api", "url": "https://api.example.test/v1",
                                     "model": "demo-model", "key": "dummy-secret"})
        self.assertFalse(result["ok"])
        self.assertIn("401", result["error"])
        self.assertNotIn("dummy-secret", repr(result))

    def test_missing_key_reports_error(self):
        result = ai.analyze(PREDICTION, cfg={"mode": "api"})
        self.assertFalse(result["ok"])
        self.assertIn("BCR_AI_KEY", result["error"])

    def test_build_prompt_keeps_numbers_and_history(self):
        prompt = ai.build_prompt(PREDICTION, history="PBBPT", json_mode=True)
        self.assertIn('"probabilities"', prompt)
        self.assertIn('"playable": false', prompt)
        self.assertIn('"history_recent": "PBBPT"', prompt)

    def test_structured_forces_bo_tay_and_drops_ai_numbers(self):
        fake = {
            "verdict": "Đánh", "focus_side": "P", "confidence": "cao",
            "risk": "rủi ro giả", "explanation": "giải thích giả",
            "probabilities": {"p_player": 0.99},
        }
        with patch.object(ai, "urlopen", return_value=FakeResponse(api_reply(json.dumps(fake)))):
            result = ai.analyze_structured(PREDICTION, cfg={"mode": "api", "key": "dummy"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["verdict"], "BỎ TAY")
        self.assertEqual(result["confidence"], "thấp")
        self.assertEqual(result["focus_side"], "B")
        self.assertNotIn("probabilities", result)
        self.assertEqual(result["risk"], "rủi ro giả")

    def test_local_endpoint_needs_no_key(self):
        fake = {"verdict": "Cân nhắc", "focus_side": "B", "confidence": "trung bình",
                "risk": "", "explanation": "ổn"}
        cfg = {"mode": "local", "url": "http://localhost:11434/v1/chat/completions"}
        with patch.object(ai, "urlopen", return_value=FakeResponse(api_reply(json.dumps(fake)))):
            result = ai.analyze_structured(PREDICTION, cfg=cfg)
        self.assertTrue(result["ok"])
        self.assertEqual(result["verdict"], "BỎ TAY")  # playable=false vẫn là chốt

    def test_text_fallback_when_model_returns_plain_text(self):
        with patch.object(ai, "urlopen",
                          return_value=FakeResponse(api_reply("AI trả text thường"))):
            result = ai.analyze_structured(PREDICTION, cfg={"mode": "api", "key": "dummy"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "text")
        self.assertEqual(result["verdict"], "BỎ TAY")
        self.assertIn("AI trả text thường", result["explanation"])

    def test_retry_without_response_format_on_http_400(self):
        error = HTTPError("http://api", 400, "bad request", {}, None)
        second = api_reply(json.dumps({
            "verdict": "BỎ TAY", "risk": "", "explanation": "ok"}))
        with patch.object(ai, "urlopen", side_effect=[
                error, FakeResponse(second)]) as mocked:
            result = ai.analyze_structured(PREDICTION, cfg={"mode": "api", "key": "dummy"})
        self.assertTrue(result["ok"])
        self.assertEqual(mocked.call_count, 2)
        body = json.loads(mocked.call_args_list[0].args[0].data.decode("utf-8"))
        self.assertIn("response_format", body)
        body2 = json.loads(mocked.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertNotIn("response_format", body2)


class SessionTests(unittest.TestCase):
    def setUp(self):
        cleaner = patch.dict(os.environ, {"BCR_AI_KEY": "", "BCR_AI_MODE": ""})
        cleaner.start()
        self.addCleanup(cleaner.stop)

    def test_prediction_and_snapshot(self):
        session = LiveSession(trials=600, ai_mode="off")
        session.on_round(dict(ROUND))
        snapshot = session.snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertAlmostEqual(sum(snapshot["prediction"]["probabilities"].values()),
                               1.0, places=5)
        self.assertEqual(snapshot["rounds"], 1)
        self.assertIsNone(snapshot["analysis"])

    def test_duplicate_issue_does_not_touch_shoe(self):
        session = LiveSession(trials=600, ai_mode="off")
        session.on_round(dict(ROUND))
        dealt = session.shoe.dealt
        session.on_round(dict(ROUND))
        self.assertEqual(session.shoe.dealt, dealt)
        self.assertEqual(session.duplicates, 1)

    def test_analyze_now_without_config(self):
        session = LiveSession(trials=600, ai_mode="api")
        session.on_round(dict(ROUND))
        result = session.analyze_now()
        self.assertFalse(result["ok"])


class RpcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_controller(self):
        events = []

        class Emitter:
            def event(self, name, data):
                events.append((name, data))

        controller = BaccaratController(
            str(pathlib.Path(self.tmp.name) / "state.json"), Emitter())
        self.addCleanup(controller.shutdown)
        return controller, events

    @staticmethod
    def live_view(playable=True, best_side="P", focus_side="T"):
        return {
            "running": True, "rounds": 3, "table": "Bàn test",
            "prediction": {"ok": True, "playable": playable, "best_side": best_side,
                           "least_bad_side": "B"},
            # focus_side là lời AI: cố tình khác best_side để chứng minh AI không đổi cửa.
            "analysis": {"verdict": "Đánh", "focus_side": focus_side,
                         "confidence": "cao", "explanation": "AI nói"},
        }

    def test_live_methods_are_wired(self):
        controller, _ = self.make_controller()
        result, error = controller.dispatch("live.state", {})
        self.assertIsNone(error)
        self.assertFalse(result["running"])
        result, error = controller.dispatch("live.analyze", {})
        self.assertIsNone(error)
        self.assertFalse(result["ok"])

    def test_api_key_stays_in_ram_only(self):
        controller, _ = self.make_controller()
        result, error = controller.dispatch("ai.key.set", {"key": "dummy-ram-only"})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["has_key"])
        self.assertEqual(controller.ai_key_override, "dummy-ram-only")

    def test_ai_check_uses_unsaved_provider_values(self):
        from aibcr.controllers import baccarat as BC

        controller, _events = self.make_controller()
        values = {"mode": "api", "url": "https://provider.example/v1",
                  "model": "custom-model", "key": "temporary-key"}
        with patch.object(BC.LIVE_AI, "check_model",
                          return_value={"ok": True, "model": "custom-model"}) as check:
            result, error = controller.dispatch("ai.check", values)
        self.assertIsNone(error)
        self.assertTrue(result["ok"])
        self.assertEqual(check.call_args.args[0]["url"], values["url"])
        self.assertEqual(check.call_args.args[0]["key"], values["key"])
        self.assertEqual(controller.ai_key_override, "")

        # Khi live session đã tồn tại, key phải đi thẳng vào RAM của session đó.
        controller.live_session = LiveSession(ai_mode="api")
        result, error = controller.dispatch("ai.key.set", {"key": "dummy-second"})
        self.assertIsNone(error)
        self.assertEqual(controller.live_session.ai_key, "dummy-second")
        self.assertNotIn("dummy-second", json.dumps(controller.live_session.snapshot(),
                                                    ensure_ascii=False))

        for method in ("state", "config.get", "live.state"):
            result, error = controller.dispatch(method, {})
            self.assertIsNone(error)
            self.assertNotIn("dummy-second", json.dumps(result, ensure_ascii=False))
        controller._save_state()
        self.assertNotIn("dummy-second",
                         controller.state_path.read_text(encoding="utf-8"))

        result, error = controller.dispatch("ai.key.set", {"key": ""})
        self.assertIsNone(error)
        self.assertFalse(result["has_key"])
        self.assertEqual(controller.ai_key_override, "")

    def test_bet_place_uses_explicit_side_even_when_prediction_disagrees(self):
        controller, _ = self.make_controller()

        class FakeLive:
            def __init__(self, view):
                self.view = view

            def snapshot(self):
                return self.view

        controller.live_session = FakeLive(self.live_view())
        result, error = controller.dispatch("bet.config", {"side": "P", "stake": 123})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)

        row = {"key": "id:t1", "label": "Bàn test", "letters": "BBP",
               "ts": time.time(), "table_id": "t1", "stable": 3}
        controller.tables = {row["key"]: row}
        controller.sim.bind(row)
        self.assertTrue(controller.sim.start(row))
        controller.sim.entry_waiting = False
        controller.tool_running = True

        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))
        result, error = controller.dispatch("bet.place", {})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(placed), 1)
        # The user's selected side remains authoritative even when AI says T.
        self.assertEqual(placed[0]["side"], "P")
        self.assertEqual(placed[0]["stake"], 123.0)
        self.assertNotIn("AI", placed[0]["reason"])

    def test_ai_auto_side_is_rejected_and_explicit_side_is_allowed(self):
        controller, _ = self.make_controller()

        class FakeLive:
            def __init__(self, view):
                self.view = view

            def snapshot(self):
                return self.view

        controller.live_session = FakeLive(
            self.live_view(playable=False, best_side=None, focus_side="P"))
        result, error = controller.dispatch("bet.config", {"side": "AUTO", "stake": 90})
        self.assertIsNone(error)
        self.assertFalse(result["ok"])
        result, error = controller.dispatch("bet.config", {"side": "P", "stake": 90})
        row = {"key": "id:t1", "label": "Bàn test", "letters": "BBP",
               "ts": time.time(), "table_id": "t1", "stable": 3}
        controller.tables = {row["key"]: row}
        controller.sim.bind(row)
        controller.sim.start(row)
        controller.sim.entry_waiting = False
        controller.tool_running = True
        placed = []
        controller._place_armed_bet = lambda order: placed.append(dict(order))

        result, error = controller.dispatch("bet.place", {})
        self.assertIsNone(error)
        self.assertTrue(result["ok"], result)
        self.assertEqual(placed[-1]["side"], "P")


if __name__ == "__main__":
    unittest.main(verbosity=2)
