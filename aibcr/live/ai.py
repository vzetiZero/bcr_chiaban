# -*- coding: utf-8 -*-
"""Gọi AI local hoặc API (OpenAI-compatible) để diễn giải kết quả đã tính.

Nguyên tắc giữ nguyên:

    - Số liệu (xác suất, EV, shoe) do ``predict`` tính local; AI **không** được bịa
      hay sửa số, và **không** được đổi quyết định ``playable``.
    - Thiếu cấu hình thì mọi hàm trả ``{"ok": False, "error": ...}`` và app vẫn chạy.
    - Chỉ dùng ``urllib`` (có sẵn), không thêm thư viện.
    - Không lưu key vào repo/env file/state: key chỉ đọc từ ``BCR_AI_KEY`` hoặc nhận
      override RAM từ UI (``ai.key.set``).

Chế độ (``BCR_AI_MODE`` hoặc truyền qua ``cfg`` từ UI):

    off     không gọi AI
    local   endpoint localhost (Ollama, llama.cpp…), **không cần key**
    api     endpoint OpenAI-compatible, cần ``BCR_AI_KEY``

Biến môi trường:

    BCR_AI_MODE     off | local | api (để trống = tự suy từ key/URL)
    BCR_AI_KEY      API key (chỉ cần cho api) — KHÔNG lưu vào repo; UI có thể override RAM
    BCR_AI_MODEL    tên model (mặc định chib/deepseek-v4.1-flash)
    BCR_AI_URL      endpoint chat/completions (mặc định https://api.vilao.ai/...)
    BCR_AI_TIMEOUT  timeout giây (mặc định 8 cho UI)
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

DEFAULT_URL = "https://api.vilao.ai/v1/chat/completions"
DEFAULT_MODEL = "chib/deepseek-v4.1-flash"
TIMEOUT = 20           # giữ tương thích với CLI cũ
DEFAULT_TIMEOUT = 8    # cửa cược Petalive ~25s nên UI dùng 8s
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")
MODES = ("off", "local", "api")
VERDICTS = ("BỎ TAY", "Cân nhắc", "Đánh")
CONFIDENCES = ("thấp", "trung bình", "cao")

SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích Baccarat. Bạn KHÔNG được bịa xác suất: chỉ dùng đúng "
    "các con số được đưa trong JSON. Trả lời tiếng Việt, tối đa 5 câu, nêu: cửa có EV "
    "tốt nhất, mức chênh so với 2 cửa còn lại, rủi ro chính (shoe cạn/ván vừa đổi "
    "nhịp), và khuyến nghị cược hay bỏ tay. Không hứa thắng, không khuyến khích tăng "
    "cược khi EV âm."
)

SYSTEM_PROMPT_JSON = (
    "Bạn là trợ lý phân tích Baccarat. Dữ liệu đã được tính sẵn bằng Monte Carlo; "
    "KHÔNG được bịa hoặc sửa số liệu. Chỉ trả một đối tượng JSON hợp lệ, không markdown, "
    "gồm đúng các khoá: verdict (một trong 'BỎ TAY'|'Cân nhắc'|'Đánh'), "
    "focus_side (một trong 'P'|'B'|'T' hoặc null), confidence (một trong "
    "'thấp'|'trung bình'|'cao'), risk (chuỗi tối đa 200 ký tự), explanation "
    "(chuỗi tối đa 400 ký tự). Nếu computed.playable là false thì verdict BẮT BUỘC "
    "là 'BỎ TAY', confidence là 'thấp'. Không hứa thắng, không khuyến khích tăng cược "
    "khi EV âm. Trả tiếng Việt."
)


def _text(value, limit):
    """Khai thác chuỗi an toàn, cắt độ dài để UI không phình."""
    if value is None:
        return ""
    return str(value).strip()[:max(1, int(limit))]


def is_local_url(url):
    """True nếu endpoint trỏ tới máy local (Ollama/llama.cpp…)."""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def completion_url(url):
    """Accept a provider base URL or a complete chat-completions endpoint."""
    raw = _text(url, 300).rstrip("/")
    try:
        parts = urlparse(raw)
    except ValueError:
        return ""
    if (parts.scheme not in ("http", "https") or not parts.netloc
            or parts.username is not None or parts.password is not None):
        return ""
    try:
        _ = parts.port
    except ValueError:
        return ""
    path = parts.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions" if path else "/v1/chat/completions"
    return urlunparse(parts._replace(path=path))


def config(overrides=None):
    """Cấu hình hiệu lực: UI override > biến môi trường > mặc định."""
    override = overrides if isinstance(overrides, dict) else {}
    mode = _text(override.get("mode") or os.environ.get("BCR_AI_MODE"), 16).lower()
    if mode not in MODES:
        # Tương thích CLI cũ: có key -> api; endpoint local -> local; else off.
        url = _text(override.get("url") or os.environ.get("BCR_AI_URL"), 300) or DEFAULT_URL
        key = _text(override.get("key") or os.environ.get("BCR_AI_KEY"), 300)
        mode = "api" if key else ("local" if is_local_url(url) else "off")
    raw_url = _text(override.get("url") or os.environ.get("BCR_AI_URL"), 300) or DEFAULT_URL
    url = completion_url(raw_url)
    model = _text(override.get("model") or os.environ.get("BCR_AI_MODEL"), 80) or DEFAULT_MODEL
    key = _text(override.get("key") or os.environ.get("BCR_AI_KEY"), 300)
    try:
        timeout = int(float(override.get("timeout") or os.environ.get("BCR_AI_TIMEOUT")
                            or DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return {
        "mode": mode, "url": url, "model": model, "key": key,
        "timeout": min(30, max(2, timeout)),
    }


def available(cfg=None):
    """Chế độ local không cần key; api bắt buộc có key."""
    settings = cfg or config()
    mode = settings.get("mode")
    if mode == "local":
        return bool(settings.get("url"))
    if mode == "api":
        return bool(settings.get("key"))
    return False


def _config_error(settings):
    """Lỗi dễ hiểu, có tên biến môi trường để người dùng tự sửa."""
    mode = settings.get("mode")
    if mode == "api":
        return "Chưa cấu hình AI: đặt BCR_AI_KEY hoặc nhập key trong tab AI."
    if mode == "local":
        return "Chưa cấu hình AI local: kiểm tra BCR_AI_URL."
    return "Chưa bật AI: chọn chế độ local hoặc api."


def build_prompt(prediction, recent_rounds=None, table="", state="", time_remains=None,
                 history="", json_mode=False):
    """Prompt gọn: chỉ số liệu đã tính, không kèm dữ liệu nhạy cảm."""
    markov = prediction.get("markov") if isinstance(prediction.get("markov"), dict) else {}
    payload = {
        "table": str(table or ""),
        "state": str(state or ""),
        "time_remains": time_remains,
        "history_recent": str(history or "")[-60:],
        "computed": {
            "probabilities": prediction.get("probabilities"),
            "ev": prediction.get("ev"),
            "ev_uncertainty": prediction.get("ev_uncertainty"),
            "best_side": prediction.get("best_side"),
            "least_bad_side": prediction.get("least_bad_side"),
            "top_side": prediction.get("top_side"),
            "top_probability": prediction.get("top_probability"),
            "pattern_note": prediction.get("pattern_note"),
            "playable": bool(prediction.get("playable")),
            "recommendation": prediction.get("recommendation"),
            "monte_carlo": prediction.get("monte_carlo"),
            "markov": {key: markov.get(key) for key in
                       ("state", "transitions", "p_player", "p_banker", "p_tie")},
            "shoe": prediction.get("shoe"),
        },
        "recent_rounds": recent_rounds or [],
    }
    tail = ("Trả về JSON theo đúng schema yêu cầu."
            if json_mode else "Hãy diễn giải và khuyến nghị ngắn gọn.")
    return ("Dữ liệu đã tính sẵn (JSON) — KHÔNG được bịa hoặc sửa số:\n%s\n\n%s"
            % (json.dumps(payload, ensure_ascii=False), tail))


def _request(body, settings, timeout):
    request = Request(settings["url"], data=json.dumps(body).encode("utf-8"),
                      method="POST", headers={
                          "Content-Type": "application/json",
                          "Authorization": "Bearer " + settings["key"],
                      })
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace")), None
    except HTTPError as exc:
        return None, "AI trả lỗi HTTP %s." % exc.code
    except URLError:
        return None, "Không kết nối được API AI (mạng/tường lửa)."
    except (ValueError, OSError):
        return None, "Phản hồi AI không đọc được."


def _content(data):
    choices = (data or {}).get("choices") or []
    message = (choices[0] or {}).get("message") if choices else None
    return str((message or {}).get("content") or "").strip()


def check_model(cfg=None, timeout=12):
    """Make a tiny OpenAI-compatible request to verify URL, key, and model."""
    settings = config(cfg)
    if not settings["model"]:
        return {"ok": False, "error": "Nhập tên model trước khi kiểm tra."}
    if settings["mode"] == "off":
        return {"ok": False, "error": "Chọn chế độ API hoặc Local trước khi kiểm tra."}
    if settings["mode"] == "api" and not settings["key"]:
        return {"ok": False, "error": "Nhập API key hoặc đặt biến BCR_AI_KEY."}
    if not settings["url"]:
        return {"ok": False, "error": "Base URL không hợp lệ."}

    body = {
        "model": settings["model"],
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 4,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if settings["key"]:
        headers["Authorization"] = "Bearer " + settings["key"]
    request = Request(settings["url"], data=json.dumps(body).encode("utf-8"),
                      method="POST", headers=headers)
    try:
        with urlopen(request, timeout=max(2, min(20, int(timeout)))) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        messages = {
            400: "Đã tới API nhưng provider từ chối model/yêu cầu (HTTP 400).",
            401: "API key không hợp lệ hoặc đã hết hạn (HTTP 401).",
            403: "API key không có quyền dùng model này (HTTP 403).",
            404: "Không tìm thấy endpoint hoặc model (HTTP 404).",
            429: "API nhận được yêu cầu nhưng đang giới hạn tốc độ/hết quota (HTTP 429).",
        }
        return {"ok": False, "error": messages.get(
            exc.code, "API trả lỗi HTTP %d." % exc.code)}
    except URLError:
        return {"ok": False, "error": "Không kết nối được Base URL (mạng/tường lửa)."}
    except (ValueError, OSError, TypeError):
        return {"ok": False, "error": "Phản hồi từ API không đúng định dạng JSON."}

    if not isinstance(data, dict) or data.get("error"):
        return {"ok": False, "error": "Provider trả phản hồi lỗi; kiểm tra model và định dạng API."}
    if not _content(data):
        return {"ok": False, "error": "API đã phản hồi nhưng model không trả nội dung kiểm tra."}
    returned_model = _text(data.get("model"), 80)
    return {"ok": True, "model": returned_model or settings["model"],
            "message": "Kết nối thành công · model %s hoạt động." %
                       (returned_model or settings["model"])}


def analyze(prediction, recent_rounds=None, table="", timeout=TIMEOUT, cfg=None):
    """Gọi API AI; trả ``{"ok": True, "text": ...}`` hoặc lỗi có thể hiển thị."""
    settings = config(cfg)
    if not available(settings):
        return {"ok": False, "error": _config_error(settings)}
    if not isinstance(prediction, dict) or not prediction.get("ok"):
        return {"ok": False, "error": "Chưa có kết quả tính toán để phân tích."}
    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(prediction, recent_rounds, table)},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    data, error = _request(body, settings, timeout or settings["timeout"])
    if error:
        return {"ok": False, "error": error}
    text = _content(data)
    if not text:
        return {"ok": False, "error": "AI không trả nội dung."}
    return {"ok": True, "text": text, "model": settings["model"]}


def analyze_structured(prediction, recent_rounds=None, table="", state="",
                       time_remains=None, history="", timeout=None, cfg=None):
    """Nhận định dạng JSON cho UI. Không bao giờ trả số liệu do AI tự bịa.

    Model local cũ có thể không hỗ trợ ``response_format``: nếu API trả 400 thì tự
    retry không dùng khoá này, rồi fallback sang text nếu JSON vẫn hỏng.
    """
    settings = config(cfg)
    if not available(settings):
        return {"ok": False, "error": _config_error(settings)}
    if not isinstance(prediction, dict) or not prediction.get("ok"):
        return {"ok": False, "error": "Chưa có kết quả tính toán để phân tích."}
    playable = bool(prediction.get("playable"))
    focus_fallback = prediction.get("best_side") if playable else prediction.get("least_bad_side")
    body = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_JSON},
            {"role": "user", "content": build_prompt(
                prediction, recent_rounds, table, state, time_remains, history,
                json_mode=True)},
        ],
        "temperature": 0.1,
        "max_tokens": 320,
        "response_format": {"type": "json_object"},
    }
    data, error = _request(body, settings, timeout or settings["timeout"])
    if error and "400" in error:
        body.pop("response_format", None)
        data, error = _request(body, settings, timeout or settings["timeout"])
    if error:
        return {"ok": False, "error": error}
    content = _content(data)
    if not content:
        return {"ok": False, "error": "AI không trả nội dung."}

    obj = None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            obj = parsed
    except (ValueError, TypeError):
        obj = None

    if obj is None:
        return {
            "ok": True, "verdict": "Cân nhắc" if playable else "BỎ TAY",
            "focus_side": focus_fallback if focus_fallback in ("P", "B", "T") else None,
            "confidence": "thấp", "risk": "", "explanation": _text(content, 450),
            "playable": playable, "model": settings["model"], "source": "text",
        }

    verdict = _text(obj.get("verdict"), 24)
    if verdict not in VERDICTS:
        verdict = "Cân nhắc" if playable else "BỎ TAY"
    focus = obj.get("focus_side")
    if focus not in ("P", "B", "T"):
        focus = focus_fallback if focus_fallback in ("P", "B", "T") else None
    confidence = _text(obj.get("confidence"), 16)
    if confidence not in CONFIDENCES:
        confidence = "thấp"
    # Khoá an toàn: AI không được phép đổi quyết định đã tính bằng EV.
    if not playable:
        verdict, confidence = "BỎ TAY", "thấp"
        focus = focus_fallback if focus_fallback in ("P", "B", "T") else None
    return {
        "ok": True,
        "verdict": verdict,
        "focus_side": focus,
        "confidence": confidence,
        "risk": _text(obj.get("risk"), 220),
        "explanation": _text(obj.get("explanation"), 450),
        "playable": playable,
        "model": settings["model"],
        "source": "json",
    }
