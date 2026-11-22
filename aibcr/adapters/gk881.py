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


# GK881 hands the player to Dream Gaming through a transient page instead of the
# lobby itself: ``/Account/LoginToSupplier?SupplierType=DG`` (mobile and desktop
# hosts alike) and ``/Lobby/Navigation``. Those pages have no Casino menu, so the
# navigation flow must wait for the DG document rather than click a menu.
_DG_ENTRY_MARKERS = (
    "/account/logintosupplier",
    "/lobby/navigation",
    "suppliertype=dg",
)


def _is_dg_entry_url(url):
    """True when the tab sits on a GK881 DG hand-off page, not the home page."""
    text = str(url or "").lower()
    return any(marker in text for marker in _DG_ENTRY_MARKERS)


# The mobile build (``m.gk881.vip`` with a phone user-agent) is a different
# Angular app: navigation is a ``.category-item`` strip, popups use plain
# buttons ("TÔI BIẾT RỒI", "Đóng", "×") and there are no ``ng-click`` attributes.
_MOBILE_CLOSE_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const wanted = ['tôi biết rồi', 'đóng', '×', 'x', 'đồng ý'];
const closed = [];
for (const button of document.querySelectorAll('button, [class*=close], .btn')) {
  if (!vis(button)) continue;
  const rect = button.getBoundingClientRect();
  if (rect.width > 200 || rect.height > 200) continue;
  const text = (button.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
  if (!wanted.includes(text)) continue;
  try { button.click(); closed.push(text); } catch (error) {}
}
return {closed};
"""

_MOBILE_CATEGORY_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const wanted = norm(arguments[0]);
const items = [...document.querySelectorAll('.category-item, [class*=category-item]')];
const labels = items.map((node) => norm(node.textContent)).filter(Boolean);
const target = items.find((node) => vis(node) && norm(node.textContent).includes(wanted));
if (!target) return {ok: false, labels: labels.slice(0, 20)};
target.scrollIntoView({block: 'center', inline: 'center'});
target.click();
return {ok: true};
"""

_MOBILE_STATE_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
return {
  isHub: /link truy cập/i.test(document.body.innerText || ''),
  categories: [...document.querySelectorAll('.category-item')]
    .filter(vis).map((node) => norm(node.textContent)).slice(0, 20),
  providers: [...document.querySelectorAll('[class*=provider],[class*=vendor],[class*=game-item]')]
    .filter(vis).map((node) => norm(node.textContent).slice(0, 24)).slice(0, 15),
  dgText: [...document.querySelectorAll('*')].some((node) =>
    vis(node) && node.children.length === 0 && /dream\s*gaming/i.test(norm(node.textContent))),
};
"""


def _is_mobile_layout(driver):
    """True when the page is the mobile build (no Angular ``ng-click`` menu)."""
    try:
        data = driver.execute_script(r"""
          return {
            ng: document.querySelectorAll('li[ng-click*="entrance"]').length,
            categories: document.querySelectorAll('.category-item').length,
            hub: /link truy cập/i.test(document.body.innerText || ''),
          };
        """) or {}
    except Exception:
        return False
    return bool(data.get("categories")) or bool(data.get("hub"))


def close_mobile_popups(driver, rounds=3):
    closed = []
    for _ in range(max(1, rounds)):
        try:
            result = driver.execute_script(_MOBILE_CLOSE_JS) or {}
        except Exception:
            return closed
        closed.extend(result.get("closed") or [])
        if not result.get("closed"):
            break
        time.sleep(0.6)
    return closed


def _safe_location(driver):
    """Return only host/path; never put query strings or session tokens in logs."""
    try:
        parsed = urlsplit(driver.current_url or "")
        return (parsed.hostname or "unknown") + (parsed.path or "/")
    except Exception:
        return "unknown"


_NAVIGATE_IN_PLACE_JS = r"""
if (!window.__aibcrInPlaceNav) {
  window.__aibcrInPlaceNav = true;
  window.__aibcrOriginalOpen = window.open;
  window.open = function (url) {
    const target = typeof url === 'string' ? url.trim() : '';
    if (target && !/^about:blank$/i.test(target)) {
      try { window.location.assign(target); } catch (error) {}
      return null;
    }
    return window.__aibcrOriginalOpen
      ? window.__aibcrOriginalOpen.apply(window, arguments) : null;
  };
}
return true;
"""


def _navigate_in_place(driver):
    """Make the site's ``window.open`` reuse this tab instead of a second window.

    GK881 opens the DG lobby with ``window.open('/Lobby/Navigation')``. Chrome
    then shows a second, badly positioned window next to the profile window, and
    both are driven at once. Overriding the call keeps a single window whose
    address becomes the DG lobby URL, which is what the desktop UI expects.
    The override lives only in this document, so it is applied right before the
    provider card is clicked.
    """
    try:
        driver.execute_script(_NAVIGATE_IN_PLACE_JS)
        return True
    except Exception:
        return False


def _merge_extra_window(driver, source_handle):
    """Fallback: move a stray popup URL into ``source_handle`` and close it.

    If the site bypasses ``window.open`` (e.g. an anchor with ``target=_blank``)
    a second window still appears. Keeping only the profile window is required,
    so the lobby URL is loaded in the source tab first and the extra window is
    closed afterwards. The URL is never logged because it carries a session token.
    """
    handles = [item for item in driver.window_handles if item != source_handle]
    if not handles:
        return False
    lobby_url = ""
    for handle in reversed(handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            current = driver.current_url or ""
            if "gk881" in current.lower() or "ddnewpc" in current.lower():
                lobby_url = current
                break
        except Exception:
            continue
    if not lobby_url:
        return False
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            driver.close()
        except Exception:
            continue
    driver.switch_to.window(source_handle)
    try:
        driver.get(lobby_url)
    except Exception:
        return False
    return True


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

        # ---- Mobile build: a different Angular app with a category strip. ----
        if _is_mobile_layout(driver):
            stage = "giao diện điện thoại"
            report("Phát hiện giao diện điện thoại GK881; dùng bộ chọn mobile.")
            closed = close_mobile_popups(driver)
            if closed:
                report("Đã đóng %s lớp che trên mobile." % len(closed))
            state = driver.execute_script(_MOBILE_STATE_JS) or {}
            if state.get("isHub") and not state.get("categories"):
                report("Trang hiện tại là trang tổng hợp link, không có menu Casino.", "error")
                return {"ok": False, "site_id": "gk881",
                        "error": "GK881 mobile đang ở trang tổng hợp link; hãy mở link casino chính thức rồi chạy lại."}
            # Open the Casino category, then wait for the DG provider card.
            nav = driver.execute_script(_MOBILE_CATEGORY_JS, "casino") or {}
            if nav.get("ok"):
                report("Đã chọn danh mục Casino trên mobile.")
                time.sleep(2)
                driver.execute_script(_MOBILE_CLOSE_JS)
            else:
                report("Không thấy danh mục Casino; thử tìm thẻ DreamGaming trực tiếp.",
                       "warning")
            # Tap the DreamGaming provider card when it appears.
            dg_deadline = min(deadline, time.monotonic() + remain(45.0))
            tapped = {}
            while time.monotonic() < dg_deadline:
                tapped = driver.execute_script(r"""
                  const vis = (node) => {
                    try {
                      const rect = node.getBoundingClientRect();
                      const style = window.getComputedStyle(node);
                      return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden' && style.display !== 'none';
                    } catch (error) { return false; }
                  };
                  const norm = (value) => String(value || '')
                    .replace(/\s+/g, ' ').trim().toLowerCase();
                  const cards = [...document.querySelectorAll(
                    '[class*=provider],[class*=vendor],[class*=game-item],[class*=category-item]')]
                    .filter(vis);
                  const dg = cards.find((node) => /dream\s*gaming|^dg$/i.test(norm(node.textContent))
                    || [...node.querySelectorAll('img')].some((img) =>
                      /DG-|dream/i.test((img.getAttribute('src') || '') + (img.alt || ''))));
                  if (!dg) return {ok: false, count: cards.length};
                  dg.scrollIntoView({block: 'center'});
                  dg.click();
                  return {ok: true};
                """) or {}
                if tapped.get("ok"):
                    report("Đã chạm thẻ DreamGaming trên mobile.")
                    break
                time.sleep(1.0)
            if not tapped.get("ok"):
                report("Chưa thấy thẻ DreamGaming trên mobile.", "error")
                return {"ok": False, "site_id": "gk881",
                        "error": "GK881 mobile chưa hiển thị thẻ DreamGaming sau khi chọn Casino."}
            # Wait for the DG lobby to mount.
            lobby = {}
            poll = min(deadline, time.monotonic() + remain(75.0))
            while time.monotonic() < poll:
                lobby = DG.lobby_tables(driver, wait=2.0)
                if lobby.get("ok"):
                    break
                time.sleep(1.0)
            if not lobby.get("ok"):
                error = lobby.get("error") or "Sảnh DG chưa tải xong."
                report("Sảnh DG mobile chưa sẵn sàng: %s" % error, "error")
                return {"ok": False, "site_id": "gk881", "error": error}
            tables = lobby.get("tables") or []
            report("Sảnh DG mobile sẵn sàng; tìm thấy %s bàn." % len(tables))
            return {"ok": True, "site_id": "gk881", "already_open": False,
                    "lobby_ready": True, "tables": tables, "layout": "mobile",
                    "note": "Đã mở sảnh DG từ giao diện điện thoại GK881."}

        # If the tab is already on GK881's DG hand-off page there is no Casino
        # menu to click: the DG document is still loading behind the redirect.
        # Wait for it, otherwise the flow reports a TimeoutException on a page
        # that never had that menu.
        if _is_dg_entry_url(driver.current_url or ""):
            stage = "chờ sảnh DG từ trang chuyển tiếp"
            report("Đang ở trang chuyển tiếp DG; chờ sảnh tải thay vì bấm menu Casino.")
            ready = DG.lobby_tables(driver, wait=remain())
            if ready.get("ok"):
                target_handle = DG._lobby_handle(driver) or DG._dg_window(driver) or source_handle
                _activate_lobby_tab(driver, target_handle)
                report("Sảnh DG đã sẵn sàng; tìm thấy %s bàn." % len(ready.get("tables", [])))
                return {"ok": True, "already_open": True, "site_id": "gk881",
                        "lobby_ready": True, "tables": ready.get("tables", []),
                        "note": "Đã nhận diện sảnh DG đang mở từ trang chuyển tiếp GK881."}
            error = ready.get("error") or "Sảnh DG chưa tải xong."
            report("Trang chuyển tiếp DG chưa có sảnh: %s" % error, "warning")
            return {"ok": False, "site_id": "gk881",
                    "error": "GK881 đang ở trang chuyển tiếp DG nhưng sảnh chưa tải xong: %s" % error}

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

        # Click its provider heading, matching the requested "DG Trực Tuyến"
        # control in the live DOM. Both the <li> and nested button have the
        # same ng-click; clicking the button bubbles and can invoke it twice.
        headings = card.find_elements(By.CSS_SELECTOR, "h2[nav-link-display][model=\"entrance\"]")
        target = headings[0] if headings else card
        stage = "mở DG Trực Tuyến"
        # The lobby is opened with window.open(), which gives Chrome a second
        # window. Patch it first so the DG lobby replaces this tab instead.
        if _navigate_in_place(driver):
            report("Đã chuyển sảnh DG sang mở trong tab hiện tại (1 cửa sổ Chrome).")
        try:
            target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        report("Đã bấm vào DG Trực Tuyến; chờ sảnh DG xuất hiện.")

        stage = "chờ iframe hoặc tab DG"
        target_handle = None
        next_trace = 0.0
        merged = False
        while time.monotonic() < deadline:
            handles = driver.window_handles
            extra = [item for item in handles if item not in before]
            if extra and not merged:
                # Some builds still open a popup (anchor target=_blank). Fold it
                # into the main window so only one Chrome window stays open.
                if _merge_extra_window(driver, source_handle):
                    merged = True
                    before = set(driver.window_handles)
                    report("Đã gộp cửa sổ DG vào tab chính; chỉ còn 1 cửa sổ Chrome.")
                    handles = driver.window_handles
            try:
                target_handle = DG._lobby_handle(driver) or DG._dg_window(driver)
            except Exception:
                target_handle = None
            if target_handle:
                break
            if time.monotonic() >= next_trace:
                report("Vẫn chờ iframe DG tải; đã mở %s tab." % len(handles))
                next_trace = time.monotonic() + 5.0
            time.sleep(1.0)

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
