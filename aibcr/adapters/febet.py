"""User-driven FEBET Dream Gaming table selection across independent Chrome profiles."""

import json
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode


LOBBY_URL = "https://febet.kiwi/live-casino/baccarat"
MAX_FRAMES = 48
MAX_DEPTH = 5
MAX_OPTIONS = 120
_SENSITIVE_LABEL = re.compile(r"token|jwt|session|password|username|authorization|cookie", re.I)
# Iframe tiện ích của site (chat, captcha, analytics) không phải iframe game DG.
# Không loại chúng thì inspect báo "đã mở game" oan và openDG bỏ qua bước bấm ảnh DG.
_WIDGET_ORIGIN = re.compile(
    r"(^|\.)(livechatinc\.com|livechat\.com|google\.com|gstatic\.com|googleapis\.com"
    r"|recaptcha\.net|doubleclick\.net|facebook\.net|facebook\.com|zendesk\.com"
    r"|tawk\.to|crisp\.chat|hotjar\.com|intercom\.io|clarity\.ms|cloudflare\.com)$", re.I)


def _is_widget_origin(origin):
    try:
        host = urlsplit(origin or "").hostname or ""
    except ValueError:
        return True
    return not host or bool(_WIDGET_ORIGIN.search(host))


def _public_origin(url):
    try:
        parsed = urlsplit(url or "")
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            return ""
        return "%s://%s" % (parsed.scheme, parsed.hostname)
    except (TypeError, ValueError):
        return ""


def _is_lobby(url):
    try:
        parsed = urlsplit(url or "")
        return (parsed.scheme == "https" and parsed.hostname == "febet.kiwi"
                and parsed.path.rstrip("/").endswith("/live-casino/baccarat")
                and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return False


def _enter_path(driver, path):
    from selenium.webdriver.common.by import By

    driver.switch_to.default_content()
    for index in path:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        if index >= len(frames):
            raise IndexError("frame_changed")
        driver.switch_to.frame(frames[index])


def _frame_contexts(driver):
    from selenium.webdriver.common.by import By

    queue = [()]
    visited = 0
    while queue and visited < MAX_FRAMES:
        path = queue.pop(0)
        try:
            _enter_path(driver, path)
            info = driver.execute_script("""
              const frames=[...document.querySelectorAll('iframe,frame')];
              const candidates=[...document.querySelectorAll(
                'button,a,[role="button"],[tabindex="0"],[class*="cursor-pointer"]')];
              const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
              return {url:location.href,title:document.title||'',frames:frames.length,
                labels:candidates.filter(visible).map(e=>({
                  text:(e.innerText||e.getAttribute('aria-label')||e.title||'').replace(/\\s+/g,' ').trim(),
                  tag:e.tagName,role:e.getAttribute('role')||''
                })).filter(x=>x.text&&x.text.length<=100)};
            """) or {}
        except Exception:
            visited += 1
            continue
        yield path, info
        visited += 1
        if len(path) < MAX_DEPTH:
            room = MAX_FRAMES - visited - len(queue)
            queue.extend(path + (index,) for index in range(min(info.get("frames", 0), max(0, room))))


def inspect(driver):
    """Return iframe origins and visible clickable labels without returning frame URLs."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi quét bàn FEBET."}
    try:
        handles = driver.window_handles
        target = None
        for handle in reversed(handles):
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
                if _is_lobby(driver.current_url):
                    target = handle
                    break
            except Exception:
                continue
        if target is None:
            return {"ok": False, "error": "Profile cần mở sảnh FEBET Baccarat trước."}

        frames = []
        labels_by_path = {}
        for path, info in _frame_contexts(driver):
            if not path:
                continue
            origin = _public_origin(info.get("url", ""))
            title = re.sub(r"\s+", " ", str(info.get("title") or "")).strip()[:100]
            frames.append({"path": list(path), "origin": origin, "title": title,
                           "has_content": bool(info.get("labels"))})
            labels_by_path[tuple(path)] = (origin, info.get("labels", []))
        driver.switch_to.window(target)
        driver.switch_to.default_content()
        # Iframe DG vẽ sảnh bằng canvas nên có thể không có nhãn DOM nào;
        # chỉ cần origin lạ (không phải site/widget) là dấu hiệu game đã mở.
        game_frames = [frame for frame in frames
                       if frame["origin"] and frame["origin"] != "https://febet.kiwi"
                       and not _is_widget_origin(frame["origin"])]
        game_paths = {tuple(frame["path"]) for frame in game_frames}
        option_map = {}
        for path, (origin, labels) in labels_by_path.items():
            if path not in game_paths:
                continue
            for item in labels:
                label = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
                normalized = label.upper()
                if (not label or len(label) > 80 or _SENSITIVE_LABEL.search(label)
                        or normalized == "XEM GAME"):
                    continue
                option_map[(path, label)] = {"path": list(path), "label": label, "origin": origin}
                if len(option_map) >= MAX_OPTIONS:
                    break
        options = list(option_map.values())
        if game_frames and not options:
            note = "Game DG đã mở nhưng sảnh vẽ bằng canvas, không có nhãn bàn DOM."
        elif game_frames:
            note = "Đã quét iframe của game FEBET."
        else:
            note = "Chưa thấy iframe game; mở DG/XEM GAME rồi quét lại."
        return {"ok": True, "frames": frames, "options": options if game_frames else [],
                "loaded": bool(game_frames), "note": note}
    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return {"ok": False, "error": "Không quét được iframe FEBET (%s)." % type(exc).__name__}


def open_dream_gaming_baccarat(driver):
    """Open the DG Baccarat lobby by scrolling to and clicking its provider image."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi khởi chạy DG."}
    from selenium.webdriver.common.by import By

    try:
        if not driver.window_handles:
            return {"ok": False, "error": "Không tìm thấy cửa sổ Chrome."}
        driver.switch_to.window(driver.window_handles[-1])
        driver.switch_to.default_content()
        if not _is_lobby(driver.current_url):
            driver.get(LOBBY_URL)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if _is_lobby(driver.current_url):
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not _is_lobby(driver.current_url):
            return {"ok": False, "error": "FEBET chưa tải được sảnh Baccarat."}

        existing = inspect(driver)
        if existing.get("ok") and existing.get("loaded"):
            return {"ok": True, "already_open": True, "note": "Iframe game đã mở trong profile này."}

        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import ElementClickInterceptedException

        image = WebDriverWait(driver, 20).until(lambda current: next((item for item in
            current.find_elements(By.CSS_SELECTOR, 'img[alt="partner"]')
            if "dream-gaming-square.webp" in (item.get_attribute("src") or "").lower()), None))
        # Ảnh DG chỉ là logo nhỏ trong thẻ game; lớp phủ hover của thẻ che mất ảnh
        # nên phải bấm cả thẻ (div cursor-pointer), không bấm thẳng vào ảnh.
        try:
            card = image.find_element(
                By.XPATH, "./ancestor::*[contains(@class,'cursor-pointer')][1]")
        except Exception:
            card = image
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center',behavior:'instant'});",
            card)
        WebDriverWait(driver, 10).until(lambda _:
            card.is_displayed() and card.size.get("width", 0) > 0 and card.size.get("height", 0) > 0)
        time.sleep(0.25)
        try:
            card.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", card)
        clicked_xem_game = _click_xem_game(driver)

        frame_deadline = time.monotonic() + 25
        last = {"ok": True, "frames": [], "options": []}
        while time.monotonic() < frame_deadline:
            time.sleep(0.5)
            clicked_xem_game = _click_xem_game(driver) or clicked_xem_game
            last = inspect(driver)
            if last.get("ok") and last.get("loaded"):
                return {"ok": True, "already_open": False, "clicked_image": True,
                        "clicked_xem_game": clicked_xem_game,
                        "frames": last["frames"],
                        "options": last["options"], "note": "Đã mở DG Baccarat trong iframe riêng."}
        return {"ok": False, "clicked_image": True,
                "clicked_xem_game": False,
                "frames": last.get("frames", []), "options": last.get("options", []),
                "error": "Đã bấm ảnh DG nhưng chưa thấy nút XEM GAME hoặc iframe game trong 25 giây."}
    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return {"ok": False, "error": "Không mở được DG Baccarat (%s)." % type(exc).__name__}


def _click_xem_game(driver):
    """Click the site's explicit XEM GAME action when its balance modal appears."""
    try:
        for button in driver.find_elements("css selector", "button"):
            if not button.is_displayed() or not button.is_enabled():
                continue
            label = re.sub(r"\s+", " ", button.text or "").strip().upper()
            if label == "XEM GAME":
                button.click()
                return True
    except Exception:
        pass
    return False


_TABLE_ID = re.compile(r"^[0-9]{1,12}$")


def _lobby_handle(driver):
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            if _is_lobby(driver.current_url):
                return handle
        except Exception:
            continue
    return None


def _table_id_from_src(src):
    try:
        return (parse_qs(urlsplit(src or "").query).get("tableId") or [""])[0]
    except ValueError:
        return ""


def _dg_frame(driver, wait=15.0):
    """ ``(index, location)`` của iframe DG.

    Site có thể nạp qua trang chờ ``direct1.html`` rồi mới redirect sang
    ``index.html?...tableId=...``; thuộc tính ``src`` không phản ánh URL thật,
    nên phải vào từng frame đọc ``location.href`` và chờ tới khi có mã bàn.
    """
    from selenium.webdriver.common.by import By

    deadline = time.monotonic() + max(0.0, wait)
    while True:
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        except Exception:
            frames = []
        for index in range(len(frames)):
            location = ""
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frames[index])
                location = driver.execute_script("return location.href") or ""
            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
            if "ddnewpc" in location and _TABLE_ID.match(_table_id_from_src(location)):
                return index, location
        if time.monotonic() >= deadline:
            return None, None
        time.sleep(0.5)


def current_table(driver, wait=15.0):
    """Read the DG tableId of the game iframe; never expose the iframe URL/token."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đọc bàn DG."}
    try:
        if _lobby_handle(driver) is None:
            return {"ok": False, "error": "Profile cần mở sảnh FEBET Baccarat trước."}
        index, location = _dg_frame(driver, wait)
        if index is None:
            return {"ok": False, "error": "Chưa mở game DG hoặc bàn chưa tải xong."}
        return {"ok": True, "table_id": _table_id_from_src(location)}
    except Exception as exc:
        return {"ok": False, "error": "Không đọc được bàn DG (%s)." % type(exc).__name__}


def sync_table(driver, table_id, wait=15.0, settle=25.0):
    """Point this profile's DG iframe at the same tableId as the leader profile."""
    table_id = str(table_id or "").strip()
    if not _TABLE_ID.match(table_id):
        return {"ok": False, "error": "Mã bàn DG không hợp lệ (chỉ chữ số, tối đa 12)."}
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đồng bộ bàn DG."}
    try:
        if _lobby_handle(driver) is None:
            return {"ok": False, "error": "Profile cần mở sảnh FEBET Baccarat trước."}
        index, location = _dg_frame(driver, wait)
        if index is None:
            return {"ok": False, "error": "Chưa mở game DG trong profile này; bấm chạy DG trước."}
        if _table_id_from_src(location) == table_id:
            return {"ok": True, "table_id": table_id, "already": True,
                    "note": "Profile đã ở sẵn bàn %s, giữ nguyên phiên game." % table_id}
        src = driver.execute_script(
            "return (() => { const f = document.querySelectorAll('iframe,frame')[%d];"
            " return f ? (f.getAttribute('src') || '') : ''; })()" % index) or ""
        # Phải nạp lại qua trang chờ direct1.html: gán thẳng index.html khiến game
        # thoát khỏi iframe và chiếm cả trang (đã kiểm chứng thực tế).
        base = src if "ddnewpc" in src else location
        parsed = urlsplit(base)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["tableId"] = [table_id]
        path = parsed.path
        if "direct1.html" not in path:
            path = path.rsplit("/", 1)[0] + "/direct1.html"
        new_url = urlunsplit((parsed.scheme, parsed.netloc, path,
                              urlencode(query, doseq=True), ""))
        # URL chứa token phiên chỉ nhúng vào JS trong trang, không trả ra ngoài/log.
        script = ("return (() => { const f = document.querySelectorAll('iframe,frame')[%d];"
                  " if (!f) return {ok: false}; f.src = %s; return {ok: true}; })()"
                  % (index, json.dumps(new_url)))
        result = driver.execute_script(script) or {}
        if not result.get("ok"):
            return {"ok": False, "error": "Không đổi được iframe DG của profile này."}
        deadline = time.monotonic() + max(0.0, settle)
        while time.monotonic() < deadline:
            time.sleep(1.0)
            _, landed = _dg_frame(driver, wait=0)
            if (landed and "direct1" not in landed
                    and _table_id_from_src(landed) == table_id):
                return {"ok": True, "table_id": table_id,
                        "note": "Đã chuyển DG sang bàn %s." % table_id}
        return {"ok": False, "error": "Đã gửi bàn %s nhưng game chưa tải xong bàn mới." % table_id}
    except Exception as exc:
        return {"ok": False, "error": "Không đồng bộ được bàn DG (%s)." % type(exc).__name__}


def select_table(driver, label):
    """Click an exact visible table label inside the game iframe, never copy its URL."""
    label = re.sub(r"\s+", " ", str(label or "")).strip()
    if not driver or not label or len(label) > 80 or _SENSITIVE_LABEL.search(label):
        return {"ok": False, "error": "Tên bàn không hợp lệ."}
    from selenium.webdriver.common.by import By

    try:
        target = None
        target_path = None
        for path, info in _frame_contexts(driver):
            if not path:
                continue
            _enter_path(driver, path)
            candidates = driver.find_elements(By.CSS_SELECTOR,
                'button,a,[role="button"],[tabindex="0"],[class*="cursor-pointer"]')
            for element in candidates:
                try:
                    text = re.sub(r"\s+", " ", element.text or "").strip()
                    if text == label and element.is_displayed() and element.is_enabled():
                        target, target_path = element, path
                        break
                except Exception:
                    continue
            if target is not None:
                break
        if target is None:
            driver.switch_to.default_content()
            return {"ok": False, "error": "Profile này chưa thấy bàn '%s' trong iframe DG." % label}
        target.click()
        driver.switch_to.default_content()
        return {"ok": True, "label": label, "note": "Đã chọn bàn trong iframe DG."}
    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return {"ok": False, "error": "Không chọn được bàn trong iframe (%s)." % type(exc).__name__}
