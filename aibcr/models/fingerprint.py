# -*- coding: utf-8 -*-
"""Sinh dấu vết thiết bị Android cho từng profile Chrome.

Mỗi profile cần một bộ thông số riêng và ổn định (user-agent, kích thước màn
hình, DPR, ngôn ngữ, WebGL, nhiễu canvas) để giống một chiếc điện thoại thật và
không trùng nhau giữa các profile. Hàm :func:`generate` là hàm thuần: cùng một
``seed`` luôn cho cùng một bộ thông số, nên profile giữ nguyên dấu vết qua các
lần mở app.

Module này không đọc/ghi tệp và không phụ thuộc tầng Adapter/Controller.
"""

import random

# Thiết bị Android phổ biến (2024-2025). ``css`` là vùng nhìn thấy tính bằng
# CSS pixel, ``dpr`` là device-pixel-ratio — đúng như trình duyệt thật báo.
DEVICES = (
    {
        "model": "SM-S928B", "name": "Samsung Galaxy S24 Ultra",
        "css": (412, 915), "dpr": 3.5, "android": ("14",), "build": "UP1A.231005.007",
        "gpu": ("Qualcomm", "Adreno (TM) 750"),
    },
    {
        "model": "SM-S918B", "name": "Samsung Galaxy S23 Ultra",
        "css": (412, 915), "dpr": 3.5, "android": ("13", "14"), "build": "TP1A.220624.014",
        "gpu": ("Qualcomm", "Adreno (TM) 740"),
    },
    {
        "model": "SM-S911B", "name": "Samsung Galaxy S23",
        "css": (360, 780), "dpr": 3.0, "android": ("13", "14"), "build": "TP1A.220624.014",
        "gpu": ("Qualcomm", "Adreno (TM) 740"),
    },
    {
        "model": "SM-A546E", "name": "Samsung Galaxy A54",
        "css": (384, 854), "dpr": 2.8125, "android": ("13", "14"), "build": "TP1A.220624.014",
        "gpu": ("ARM", "Mali-G68"),
    },
    {
        "model": "Pixel 8 Pro", "name": "Google Pixel 8 Pro",
        "css": (448, 998), "dpr": 3.0, "android": ("14", "15"), "build": "AP1A.240505.004",
        "gpu": ("ARM", "Mali-G715"),
    },
    {
        "model": "Pixel 7", "name": "Google Pixel 7",
        "css": (412, 915), "dpr": 2.625, "android": ("13", "14"), "build": "TQ3A.230805.001",
        "gpu": ("ARM", "Mali-G710"),
    },
    {
        "model": "2211133G", "name": "Xiaomi 13",
        "css": (393, 873), "dpr": 2.75, "android": ("13", "14"), "build": "TKQ1.221114.001",
        "gpu": ("Qualcomm", "Adreno (TM) 740"),
    },
    {
        "model": "PHB110", "name": "OnePlus 11",
        "css": (412, 919), "dpr": 3.5, "android": ("13", "14"), "build": "TP1A.220905.001",
        "gpu": ("Qualcomm", "Adreno (TM) 740"),
    },
    {
        "model": "PGFM10", "name": "OPPO Find X6",
        "css": (413, 924), "dpr": 3.0, "android": ("13", "14"), "build": "TP1A.220905.001",
        "gpu": ("ARM", "Mali-G715"),
    },
)

# Ngôn ngữ hay gặp ở máy Android bán tại Việt Nam.
LANGUAGE_SETS = (
    ("vi-VN", "vi", "en-US", "en"),
    ("vi-VN", "vi", "en-US"),
    ("vi-VN", "vi"),
)

TIMEZONE = "Asia/Ho_Chi_Minh"


def _ua(device, android, build, chrome_major):
    return (
        "Mozilla/5.0 (Linux; Android {android}; {model} Build/{build}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{major}.0.0.0 Mobile Safari/537.36"
    ).format(android=android, model=device["model"], build=build,
             major=str(chrome_major or "157").split(".")[0])


def generate(seed=None, chrome_major="157"):
    """Trả về một bộ dấu vết Android hoàn chỉnh.

    ``seed`` cố định thì kết quả cố định; bỏ trống thì sinh ngẫu nhiên (dùng khi
    tạo profile mới).
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    device = rng.choice(DEVICES)
    android = rng.choice(device["android"])
    width, height = device["css"]
    vendor, renderer = device["gpu"]
    languages = list(rng.choice(LANGUAGE_SETS))
    # Điện thoại Android thật thường báo 8 nhân và 8GB (deviceMemory bị chặn ở 8).
    cores = rng.choice((8, 8, 8, 6, 4))
    memory = rng.choice((8, 8, 8, 4))
    canvas_seed = rng.randint(1, 2 ** 31 - 1)
    return {
        "device": device["name"],
        "model": device["model"],
        "android": android,
        "user_agent": _ua(device, android, device["build"], chrome_major),
        "platform": "Linux armv8l",
        "ua_platform": "Android",
        "languages": languages,
        "timezone": TIMEZONE,
        "screen": {"width": width, "height": height, "dpr": device["dpr"]},
        "touch": True,
        "max_touch_points": 5,
        "cores": cores,
        "memory": memory,
        "webgl_vendor": vendor,
        "webgl_renderer": renderer,
        "canvas_seed": canvas_seed,
        "mobile_layout": True,
    }


def describe(fingerprint):
    """Nhãn ngắn để hiển thị trong UI (không chứa thông tin phiên)."""
    if not isinstance(fingerprint, dict) or not fingerprint.get("device"):
        return "Chưa có dấu vết"
    screen = fingerprint.get("screen") or {}
    return "%s · Android %s · %s×%s" % (
        fingerprint.get("device"), fingerprint.get("android") or "?",
        screen.get("width", "?"), screen.get("height", "?"))


def regenerate(current=None, chrome_major="157"):
    """Sinh dấu vết mới, tránh trùng thiết bị với bộ hiện tại khi có thể."""
    previous = (current or {}).get("device")
    for _ in range(8):
        candidate = generate(chrome_major=chrome_major)
        if candidate["device"] != previous:
            return candidate
    return generate(chrome_major=chrome_major)
