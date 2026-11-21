"""GK881-specific navigation into its Dream Gaming lobby popup."""

import time

from aibcr.adapters import febet as DG


def open_dg(driver, wait=120.0):
    """Open GK881's DG lobby popup and make that lobby the profile's active tab."""
    initial = DG.lobby_tables(driver, wait=1.0) if driver is not None else {"ok": False}
    if initial.get("ok"):
        return {"ok": True, "already_open": True, "site_id": "gk881",
                "lobby_ready": True, "tables": initial.get("tables", []),
                "note": "Đã mở sảnh DG trên profile này."}
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    deadline = time.monotonic() + max(1.0, float(wait))
    source_handle = None
    try:
        # Prefer the GK881 page even if Chrome already has unrelated tabs open.
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

        close_selector = 'span[ng-click="$ctrl.ok()"][translate="Common_Closed"]'
        try:
            close_button = WebDriverWait(driver, max(1, min(8, deadline - time.monotonic()))).until(
                lambda current: next((item for item in current.find_elements(By.CSS_SELECTOR, close_selector)
                                      if item.is_displayed()), False))
            try:
                close_button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", close_button)
        except Exception:
            # The balance/announcement dialog is optional; continue when absent.
            pass

        # This icon is the site navigation control; avoid matching hidden templates.
        def visible_nav_icon(current):
            for item in current.find_elements(By.CSS_SELECTOR, 'i[ng-style="nav.style"]'):
                try:
                    if item.is_displayed() and item.size.get("width", 0) > 0:
                        return item
                except Exception:
                    continue
            return False

        icon = WebDriverWait(driver, max(1, min(20, deadline - time.monotonic()))).until(visible_nav_icon)
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center'});", icon)
        try:
            icon.click()
        except Exception:
            driver.execute_script("arguments[0].click();", icon)

        def dg_nav_link(current):
            for item in current.find_elements(
                    By.CSS_SELECTOR, 'span[nav-link-display][model="navLayer2"]'):
                try:
                    if item.is_displayed() and " ".join((item.text or "").split()).casefold() == "dg trực tuyến":
                        return item
                except Exception:
                    continue
            return False

        link = WebDriverWait(driver, max(1, min(20, deadline - time.monotonic()))).until(dg_nav_link)
        before = set(driver.window_handles)
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center'});", link)
        try:
            link.click()
        except Exception:
            driver.execute_script("arguments[0].click();", link)

        # GK881 opens DG in a new tab/window. Wait for it to exist and load its game
        # document; don't treat a slow blank popup as a failed profile.
        target_handle = None
        while time.monotonic() < deadline:
            handles = driver.window_handles
            new_handles = [item for item in handles if item not in before]
            for handle in reversed(new_handles):
                try:
                    driver.switch_to.window(handle)
                    driver.switch_to.default_content()
                    if "ddnewpc" in (driver.current_url or "").lower():
                        target_handle = handle
                        break
                    # Some GK881 builds wrap the game URL in an iframe.
                    if DG._lobby_handle(driver) == handle:
                        target_handle = handle
                        break
                except Exception:
                    continue
            if target_handle:
                break
            # Some builds reuse the source tab rather than creating a popup.
            try:
                driver.switch_to.window(source_handle)
                if DG._lobby_handle(driver) == source_handle:
                    target_handle = source_handle
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if target_handle is None:
            return {"ok": False, "site_id": "gk881",
                    "error": "GK881 chưa mở được tab DG; kiểm tra trạng thái đăng nhập và thử lại."}

        driver.switch_to.window(target_handle)
        ready = DG.lobby_tables(driver, wait=max(0.0, deadline - time.monotonic()))
        if not ready.get("ok"):
            return {"ok": False, "site_id": "gk881",
                    "error": ready.get("error") or "Sảnh DG của GK881 chưa tải xong."}

        # Keep the actual lobby tab selected so refresh/reload acts on DG directly.
        # Close only the original GK881 landing tab, and only after the lobby is ready.
        if target_handle != source_handle and source_handle in driver.window_handles:
            try:
                driver.switch_to.window(source_handle)
                driver.close()
            except Exception:
                pass
        driver.switch_to.window(target_handle)
        driver.switch_to.default_content()
        return {"ok": True, "site_id": "gk881", "already_open": False,
                "lobby_ready": True, "tables": ready.get("tables", []),
                "note": "Đã mở sảnh DG từ GK881 và chuyển tab DG thành tab đang dùng."}
    except Exception as exc:
        return {"ok": False, "site_id": "gk881",
                "error": "Không tự mở được sảnh DG GK881 (%s)." % type(exc).__name__}


