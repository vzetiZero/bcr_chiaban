# -*- coding: utf-8 -*-
"""Áp dấu vết thiết bị Android lên một phiên Chrome qua CDP.

``user-agent`` đặt bằng cờ khởi động và ``Network.setUserAgentOverride``; phần
còn lại (navigator, WebGL, nhiễu canvas) được chèn bằng
``Page.addScriptToEvaluateOnNewDocument`` nên chạy trước mọi script của trang.

Nhiễu canvas chỉ thay đổi *kết quả đọc* (``getImageData``/``toDataURL``) chứ
không sửa pixel đang vẽ, để không làm hỏng khung hình game.
"""

import json

_SCRIPT_TEMPLATE = r"""
(function () {
  var FP = __FP__;
  if (!FP || window.__aibcrDeviceApplied) { return; }
  window.__aibcrDeviceApplied = true;

  var define = function (target, prop, value) {
    try {
      Object.defineProperty(target, prop, {
        get: function () { return value; }, configurable: true
      });
    } catch (error) {}
  };

  define(navigator, 'platform', FP.platform);
  define(navigator, 'hardwareConcurrency', FP.cores);
  define(navigator, 'deviceMemory', FP.memory);
  define(navigator, 'maxTouchPoints', FP.maxTouchPoints);
  try {
    Object.defineProperty(navigator, 'languages', {
      get: function () { return FP.languages; }, configurable: true
    });
  } catch (error) {}
  // Selenium/Chrome-for-testing tự bật navigator.webdriver; trang thật thì không.
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: function () { return undefined; }, configurable: true
    });
  } catch (error) {}

  // Client Hints: giữ nhất quán với user-agent để không bị phát hiện mâu thuẫn.
  try {
    if (navigator.userAgentData) {
      Object.defineProperty(navigator.userAgentData, 'platform', {
        get: function () { return FP.uaPlatform; }, configurable: true
      });
      Object.defineProperty(navigator.userAgentData, 'mobile', {
        get: function () { return true; }, configurable: true
      });
    }
  } catch (error) {}

  // ---- Nhiễu canvas: chỉ ảnh hưởng bản sao dùng để đọc, không đổi khung hình.
  var seed = FP.canvasSeed;
  var noise = function (index) {
    var value = Math.sin(seed * 12.9898 + index * 78.233) * 43758.5453;
    return value - Math.floor(value);
  };
  var perturb = function (data) {
    try {
      // Fully transparent pixels are dropped by the PNG encoder, so noise there
      // would leave the exported hash unchanged. Only opaque pixels count.
      // Large canvases use a coarser stride to stay cheap.
      var step = data.length > 4000000 ? 4 * 61 : (data.length > 1000000 ? 4 * 7 : 4);
      for (var i = 0; i < data.length; i += step) {
        if (data[i + 3] === 0) { continue; }
        var roll = noise(i);
        if (roll < 0.5) { continue; }
        data[i] = (data[i] + (roll < 0.75 ? 1 : 255)) & 255;
      }
    } catch (error) {}
  };

  try {
    var originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function () {
      var result = originalGetImageData.apply(this, arguments);
      try { perturb(result.data); } catch (error) {}
      return result;
    };
  } catch (error) {}

  try {
    var originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function () {
      try {
        var width = this.width;
        var height = this.height;
        if (width && height) {
          var copy = document.createElement('canvas');
          copy.width = width;
          copy.height = height;
          var context = copy.getContext('2d');
          if (context) {
            context.drawImage(this, 0, 0);
            var image = context.getImageData(0, 0, width, height);
            perturb(image.data);
            context.putImageData(image, 0, 0);
            return originalToDataURL.apply(copy, arguments);
          }
        }
      } catch (error) {}
      return originalToDataURL.apply(this, arguments);
    };
  } catch (error) {}

  // ---- WebGL: giả lập GPU điện thoại.
  var patchWebGL = function (prototype) {
    if (!prototype || !prototype.getParameter) { return; }
    var original = prototype.getParameter;
    prototype.getParameter = function (parameter) {
      if (parameter === 37445) { return FP.webglVendor; }
      if (parameter === 37446) { return FP.webglRenderer; }
      return original.apply(this, arguments);
    };
  };
  try {
    if (window.WebGLRenderingContext) { patchWebGL(WebGLRenderingContext.prototype); }
    if (window.WebGL2RenderingContext) { patchWebGL(WebGL2RenderingContext.prototype); }
  } catch (error) {}
})();
"""


def build_script(fingerprint):
    """Chuỗi JS chèn vào mỗi document mới; rỗng nếu chưa có dấu vết."""
    if not isinstance(fingerprint, dict) or not fingerprint.get("user_agent"):
        return ""
    payload = {
        "platform": fingerprint.get("platform") or "Linux armv8l",
        "uaPlatform": fingerprint.get("ua_platform") or "Android",
        "languages": list(fingerprint.get("languages") or ["vi-VN", "vi"]),
        "cores": int(fingerprint.get("cores") or 8),
        "memory": int(fingerprint.get("memory") or 8),
        "maxTouchPoints": int(fingerprint.get("max_touch_points") or 5),
        "canvasSeed": int(fingerprint.get("canvas_seed") or 1),
        "webglVendor": fingerprint.get("webgl_vendor") or "Qualcomm",
        "webglRenderer": fingerprint.get("webgl_renderer") or "Adreno (TM) 740",
    }
    return _SCRIPT_TEMPLATE.replace("__FP__", json.dumps(payload, ensure_ascii=False))


def _client_hints(fingerprint, major):
    """userAgentMetadata đi kèm setUserAgentOverride (Chromium mới yêu cầu)."""
    version = "%s.0.0.0" % major
    return {
        "brands": [
            {"brand": "Chromium", "version": str(major)},
            {"brand": "Google Chrome", "version": str(major)},
            {"brand": "Not?A_Brand", "version": "24"},
        ],
        "fullVersionList": [
            {"brand": "Chromium", "version": version},
            {"brand": "Google Chrome", "version": version},
            {"brand": "Not?A_Brand", "version": "24.0.0.0"},
        ],
        "fullVersion": version,
        "platform": "Android",
        "platformVersion": "%s.0.0" % (fingerprint.get("android") or "14"),
        "architecture": "",
        "model": fingerprint.get("model") or "",
        "mobile": True,
        "bitness": "",
        "wow64": False,
    }


def _fit_viewport_to_area(viewport, screen, area):
    """Khung nhìn khớp đúng vùng trang thật để trang phủ kín cửa sổ Chrome.

    Chrome **thu mặt phẳng render** của khung nhìn emulate cho vừa vùng trang của
    cửa sổ. Vì vậy trang chỉ phủ kín khung khi tỉ lệ khung nhìn trùng tỉ lệ vùng
    trang. Số đo thật bằng ``Page.getLayoutMetrics`` trên máy (khung Rộng 900 ×
    Cao 1200 × Scale 60% → vùng trang 533 × 665 điểm ảnh):

    ==========================  ======================  ===========
    khung nhìn                  mặt phẳng render thật    phủ khung
    ==========================  ======================  ===========
    412 × 915  (tỉ lệ 0.450)    248 × 549               47% × 83%
    412 × 514  (tỉ lệ 0.801)    248 × 309               47% × 46%
    888 × 1108 (tỉ lệ 0.801)    533 × 665              100% × 100%
    ==========================  ======================  ===========

    Tỉ lệ 0.450 so với 0.801 là nguyên nhân giao diện "bé hơn khung": Chrome thu
    theo chiều cao nên bề ngang chỉ còn 47 %, phần còn lại là nền trống. Không
    thể vừa giữ khung nhìn điện thoại 412 × 915 vừa phủ kín khung 900 × 1200 —
    hai tỉ lệ khác nhau về mặt hình học.

    Nên khung nhìn lấy đúng vùng trang (``area``) và ``deviceScaleFactor`` lấy
    đúng ``devicePixelRatio`` của cửa sổ: ánh xạ 1:1, không thu, không dải trống,
    chữ vẫn sắc nét. ``mobile_layout`` + touch + user-agent Android vẫn giữ nên
    site tiếp tục trả giao diện di động.
    """
    area_width = int((area or {}).get("width") or 0)
    area_height = int((area or {}).get("height") or 0)
    if min(area_width, area_height) <= 0:
        return None
    ratio = float((area or {}).get("dpr") or 0)
    if ratio <= 0:
        ratio = float(screen.get("dpr") or viewport.get("dpr") or 1)
    return {"width": area_width, "height": area_height,
            "deviceScaleFactor": round(min(8.0, max(0.1, ratio)), 4),
            "screenWidth": area_width, "screenHeight": area_height}


def apply_to_driver(driver, fingerprint, chrome_major=None, page_area=None,
                    skip_metrics=False):
    """Áp dấu vết lên driver hiện có. Trả về danh sách bước đã áp.

    ``page_area`` là vùng trang thật của cửa sổ (CSS pixel, đã trừ viền/tab của
    Chrome). Khi có, metrics được thu cho vừa đúng vùng đó để trang phủ kín khung
    thay vì để trống một dải bên phải/dưới.

    ``skip_metrics`` dùng cho lượt áp **trước khi điều hướng**: lúc đó chưa đo
    được vùng trang thật, nên chỉ đặt user-agent (để site trả markup mobile) và
    để lượt áp sau điều hướng đặt metrics đúng.
    """
    if driver is None or not isinstance(fingerprint, dict) or not fingerprint.get("user_agent"):
        return []
    applied = []
    major = str(chrome_major or "157").split(".")[0]

    def attempt(name, method, params):
        try:
            driver.execute_cdp_cmd(method, params)
            applied.append(name)
        except Exception:
            pass

    attempt("ua", "Network.enable", {})
    override = {
        "userAgent": fingerprint["user_agent"],
        "acceptLanguage": ",".join(fingerprint.get("languages") or ["vi-VN"]),
        "platform": fingerprint.get("platform") or "Linux armv8l",
    }
    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", dict(
            override, userAgentMetadata=_client_hints(fingerprint, major)))
        applied.append("ua")
    except Exception:
        attempt("ua", "Network.setUserAgentOverride", override)

    screen = fingerprint.get("screen") or {}
    viewport = fingerprint.get("viewport") or screen
    if skip_metrics:
        metrics = None
    else:
        metrics = _fit_viewport_to_area(viewport, screen, page_area) if page_area else None
        if metrics is None and viewport.get("width") and viewport.get("height"):
            metrics = {
                "width": int(viewport["width"]),
                "height": int(viewport["height"]),
                # Cap the ratio: 3.5 makes every glyph huge inside a desktop window.
                "deviceScaleFactor": min(3.0, float(screen.get("dpr") or 1)),
                "screenWidth": int(screen.get("width") or 0) or int(viewport["width"]),
                "screenHeight": int(screen.get("height") or 0) or int(viewport["height"]),
            }
    if metrics is not None:
        attempt("metrics", "Emulation.setDeviceMetricsOverride", {
            **metrics,
            "mobile": bool(fingerprint.get("mobile_layout", True)),
            "screenOrientation": {"type": "portraitPrimary", "angle": 0},
        })
        attempt("touch", "Emulation.setTouchEmulationEnabled",
                {"enabled": True, "maxTouchPoints": int(fingerprint.get("max_touch_points") or 5)})

    script = build_script(fingerprint)
    if script:
        attempt("script", "Page.addScriptToEvaluateOnNewDocument", {"source": script})
    return applied

# Chrome draws its own tab strip and address bar above the page. These are the
# approximate outer-window extras on Windows at 100% display scaling.
CHROME_UI_HEIGHT = 90
CHROME_UI_WIDTH = 16


def mobile_window(fingerprint, preferred_width=430):
    """Outer window size for a portrait phone layout.

    Only used when a caller wants a phone-shaped *window*. The normal app path
    keeps the user's configured window (900 × 1200 @ 60 %) and instead fits the
    emulated viewport to the window's real page area — see
    ``_fit_viewport_to_area``.
    """
    screen = (fingerprint or {}).get("screen") or {}
    width = float(screen.get("width") or 393)
    height = float(screen.get("height") or 873)
    if width <= 0 or height <= 0:
        width, height = 393.0, 873.0
    ratio = height / width
    page_width = int(max(360, min(520, preferred_width)))
    page_height = int(round(page_width * ratio))
    return {
        "width": page_width + CHROME_UI_WIDTH,
        "height": page_height + CHROME_UI_HEIGHT,
        "viewport": {"width": page_width, "height": page_height},
    }


def with_viewport(fingerprint, viewport):
    """Copy of ``fingerprint`` whose metrics target ``viewport``."""
    if not isinstance(fingerprint, dict):
        return fingerprint
    copy = dict(fingerprint)
    copy["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
    return copy
