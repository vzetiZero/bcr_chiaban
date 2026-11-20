"""User-driven FEBET Dream Gaming table selection across independent Chrome profiles."""

import re
import time
from urllib.parse import urlsplit


LOBBY_URL = "https://febet.kiwi/live-casino/baccarat"
MAX_FRAMES = 48
MAX_DEPTH = 5
MAX_OPTIONS = 120
_SENSITIVE_LABEL = re.compile(r"token|jwt|session|password|username|authorization|cookie", re.I)


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
        option_map = {}
        for path, info in _frame_contexts(driver):
            if not path:
                continue
            origin = _public_origin(info.get("url", ""))
            title = re.sub(r"\s+", " ", str(info.get("title") or "")).strip()[:100]
            frames.append({"path": list(path), "origin": origin, "title": title,
                           "has_content": bool(info.get("labels"))})
            for item in info.get("labels", []):
                label = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
                normalized = label.upper()
                if (not label or len(label) > 80 or _SENSITIVE_LABEL.search(label)
                        or normalized == "XEM GAME"):
                    continue
                key = (tuple(path), label)
                option_map[key] = {"path": list(path), "label": label, "origin": origin}
                if len(option_map) >= MAX_OPTIONS:
                    break
        driver.switch_to.window(target)
        driver.switch_to.default_content()
        options = list(option_map.values())
        game_frames = [frame for frame in frames
                       if frame["origin"] and frame["origin"] != "https://febet.kiwi"]
        return {"ok": True, "frames": frames, "options": options if game_frames else [],
                "loaded": bool(game_frames), "note": "Đã quét iframe của game FEBET." if game_frames
                else "Chưa thấy iframe game; mở DG/XEM GAME rồi quét lại."}
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

        image = WebDriverWait(driver, 20).until(lambda current: next((item for item in
            current.find_elements(By.CSS_SELECTOR, 'img[alt="partner"]')
            if "dream-gaming-square.webp" in (item.get_attribute("src") or "").lower()), None))
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center',behavior:'instant'});",
            image)
        WebDriverWait(driver, 10).until(lambda _:
            image.is_displayed() and image.size.get("width", 0) > 0 and image.size.get("height", 0) > 0)
        time.sleep(0.25)
        image.click()
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
