"""GK881-specific navigation into its Dream Gaming lobby popup."""

import time
from urllib.parse import urlsplit

from aibcr.adapters import febet as DG


def _activate_lobby_tab(driver, target_handle):
    """Keep the game popup selected and close only its GK881 opener."""
    source_handle = None
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            if "gk881.vip" in (driver.current_url or "").lower():
                source_handle = handle
                break
        except Exception:
            continue
    if source_handle and source_handle != target_handle:
        try:
            driver.switch_to.window(source_handle)
            driver.close()
        except Exception:
            pass
    driver.switch_to.window(target_handle)
    driver.switch_to.default_content()


def _safe_location(driver):
    """Return only host/path; never put query strings or session tokens in logs."""
    try:
        parsed = urlsplit(driver.current_url or "")
        return (parsed.hostname or "unknown") + (parsed.path or "/")
    except Exception:
        return "unknown"


def open_dg(driver, wait=120.0, log=None):
    """Open GK881's DG lobby using the live site's Casino > DG card flow.

    ``log`` is an optional callback used by the desktop controller to expose a
    sanitized trace in its activity log. Existing callers remain compatible.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    deadline = time.monotonic() + max(1.0, float(wait))
    stage = "khởi tạo"

    def report(message, level="info"):
        if log:
            try:
                log("GK881 · " + message, level)
            except Exception:
                pass

    def remain(maximum=20.0):
        return max(0.1, min(float(maximum), deadline - time.monotonic()))

    def visible(element):
        try:
            return element.is_displayed() and element.size.get("width", 0) > 0
        except Exception:
            return False

    report("Bắt đầu; trang hiện tại: %s." % _safe_location(driver))

    # Reuse an already loaded DG lobby on retries.
    stage = "kiểm tra sảnh DG đang mở"
    initial = DG.lobby_tables(driver, wait=1.0) if driver is not None else {"ok": False}
    if initial.get("ok"):
        target_handle = DG._dg_window(driver) or DG._lobby_handle(driver)
        if target_handle:
            report("Đã nhận diện sảnh DG đang mở; chuyển sang tab sảnh.")
            _activate_lobby_tab(driver, target_handle)
        report("Sảnh DG sẵn sàng; tìm thấy %s bàn." % len(initial.get("tables", [])))
        return {"ok": True, "already_open": True, "site_id": "gk881",
                "lobby_ready": True, "tables": initial.get("tables", []),
                "note": "Đã mở sảnh DG trên profile này."}

    source_handle = None
    try:
        # A prior attempt may already have created the DG popup while it loads.
        stage = "kiểm tra popup DG đang tải"
        existing_handle = DG._dg_window(driver) or DG._lobby_handle(driver)
        if existing_handle:
            report("Đã thấy popup/tab có iframe DG; chờ sảnh tải.")
            driver.switch_to.window(existing_handle)
            ready = DG.lobby_tables(driver, wait=remain())
            if ready.get("ok"):
                _activate_lobby_tab(driver, existing_handle)
                report("Sảnh DG đã tải; tìm thấy %s bàn." % len(ready.get("tables", [])))
                return {"ok": True, "already_open": True, "site_id": "gk881",
                        "lobby_ready": True, "tables": ready.get("tables", []),
                        "note": "Đã nhận diện popup DG GK881 đang mở."}
            report("Popup có iframe DG nhưng Laya chưa báo sảnh sẵn sàng.", "warning")
            return {"ok": False, "site_id": "gk881",
                    "error": "Popup DG GK881 đã mở nhưng sảnh chưa tải xong; sẽ quét lại mà không mở popup trùng."}

        # Prefer the GK881 page even if Chrome already has unrelated tabs open.
        stage = "tìm tab GK881"
        for handle in reversed(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                if "gk881.vip" in (driver.current_url or "").lower():
                    source_handle = handle
                    break
            except Exception:
                continue
        if source_handle is None:
            source_handle = driver.current_window_handle
        driver.switch_to.window(source_handle)
        driver.switch_to.default_content()
        report("Đang thao tác trên %s." % _safe_location(driver))

        # The balance/announcement modal is optional.
        stage = "đóng thông báo nếu có"
        close_selector = 'span[ng-click="$ctrl.ok()"][translate="Common_Closed"]'
        close_button = False
        try:
            close_button = WebDriverWait(driver, max(0.1, min(3.0, deadline - time.monotonic()))).until(
                lambda current: next((item for item in current.find_elements(By.CSS_SELECTOR, close_selector)
                                      if visible(item)), False))
        except Exception:
            close_button = False
        if close_button:
            try:
                close_button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", close_button)
            report("Đã đóng thông báo/số dư.")
        else:
            report("Không có thông báo cần đóng; tiếp tục.")

        # Current GK881 builds use the Casino navigation card. The old broad
        # i[ng-style="nav.style"] selector matched every category and clicked
        # the first item (Trang chủ), which made the later DG wait time out.
        stage = "mở danh sách sảnh Casino"

        def dg_card(current):
            for item in current.find_elements(By.CSS_SELECTOR, 'li[ng-click*="entrance.click"]'):
                try:
                    heading = item.find_elements(By.CSS_SELECTOR, "h2[nav-link-display]")
                    if heading and " ".join((heading[0].text or "").split()).casefold() == "dg trực tuyến":
                        return item
                except Exception:
                    continue
            return False

        if not dg_card(driver):
            def casino_nav(current):
                for item in current.find_elements(By.CSS_SELECTOR, 'a[ng-click="nav.click($event)"]'):
                    try:
                        label = " ".join((item.text or "").split()).casefold()
                        if visible(item) and label == "casino":
                            return item
                    except Exception:
                        continue
                return False

            casino = WebDriverWait(driver, remain()).until(casino_nav)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", casino)
            try:
                casino.click()
            except Exception:
                driver.execute_script("arguments[0].click();", casino)
            report("Đã chọn đúng mục Casino; chờ thẻ nhà cung cấp DG.")

        stage = "chờ thẻ DG Trực Tuyến"
        card = WebDriverWait(driver, remain()).until(dg_card)
        report("Đã tìm thấy thẻ DG Trực Tuyến; cuộn thẻ vào vùng nhìn.")
        driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'center'});", card)
        before = set(driver.window_handles)

        # Click the card's explicit entry button, matching the live DOM
        # (li > h2[model=entrance] + button), with the card as fallback.
        buttons = card.find_elements(By.CSS_SELECTOR, 'button[ng-click*="entrance.click"]')
        target = buttons[0] if buttons else card
        stage = "mở DG Trực Tuyến"
        try:
            target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        report("Đã bấm vào DG Trực Tuyến; chờ popup/iframe DG xuất hiện.")

        stage = "chờ iframe hoặc tab DG"
        target_handle = None
        next_trace = 0.0
        while time.monotonic() < deadline:
            handles = driver.window_handles
            new_handles = [item for item in handles if item not in before]
            for handle in reversed(new_handles):
                try:
                    driver.switch_to.window(handle)
                    driver.switch_to.default_content()
                    if "ddnewpc" in (driver.current_url or "").lower() or DG._lobby_handle(driver) == handle:
                        target_handle = handle
                        break
                except Exception:
                    continue
            if target_handle:
                break
            # Some builds reuse the source tab; others first open /Lobby/Navigation
            # with an Account/LoginToSupplier iframe, which later hosts ddnewpc.
            try:
                driver.switch_to.window(source_handle)
                driver.switch_to.default_content()
                if DG._dg_window(driver) == source_handle or DG._lobby_handle(driver) == source_handle:
                    target_handle = source_handle
                    break
            except Exception:
                pass
            if time.monotonic() >= next_trace:
                report("Vẫn chờ iframe DG tải; đã mở %s tab." % len(handles))
                next_trace = time.monotonic() + 5.0
            time.sleep(0.5)

        if target_handle is None:
            stage = "chờ iframe hoặc tab DG"
            report("Hết thời gian chờ; chưa thấy document ddnewpc hoặc iframe DG.", "error")
            return {"ok": False, "site_id": "gk881",
                    "error": "GK881 đã bấm DG Trực Tuyến nhưng chưa tải iframe DG trong thời gian chờ."}

        stage = "đọc trạng thái sảnh Laya"
        report("Đã thấy document DG; đang chờ Laya dựng danh sách bàn.")
        driver.switch_to.window(target_handle)
        ready = DG.lobby_tables(driver, wait=remain())
        if not ready.get("ok"):
            report("Iframe DG đã có nhưng Laya chưa sẵn sàng: %s" % (ready.get("error") or "chưa có bàn"), "warning")
            return {"ok": False, "site_id": "gk881",
                    "error": ready.get("error") or "Sảnh DG của GK881 chưa tải xong."}

        _activate_lobby_tab(driver, target_handle)
        report("Sảnh DG đã sẵn sàng; tìm thấy %s bàn." % len(ready.get("tables", [])))
        return {"ok": True, "site_id": "gk881", "already_open": False,
                "lobby_ready": True, "tables": ready.get("tables", []),
                "note": "Đã mở sảnh DG từ GK881 và chuyển tab DG thành tab đang dùng."}
    except Exception as exc:
        report("Dừng tại bước '%s' (%s)." % (stage, type(exc).__name__), "error")
        return {"ok": False, "site_id": "gk881",
                "error": "GK881 chưa hoàn tất bước '%s' (%s)." % (stage, type(exc).__name__)}
