"""VNWTop-specific navigation into its Dream Gaming lobby.

Live flow observed on ``https://vnwtop.com/``:

1. An auth overlay (``.v5-auth-modal``) may cover the page on load. When the
   saved session is still valid it clears itself; otherwise its small close
   control is clicked. Credentials are never touched here.
2. The left menu holds ``.side-item > .side-text`` entries. Clicking the
   ``Casino trực tiếp`` label switches the panel to the live-casino list.
3. That list renders ``img.platform-banner-full`` cards whose ``alt`` is the
   provider name. The DreamGaming card opens the DG lobby.
4. Unlike E3951, VNWTop opens DG in a **second Chrome window**. The lobby URL is
   read from that window, loaded into the original profile tab, and the extra
   window is closed so the profile keeps a single window (the same behaviour as
   GK881/E3951).
5. DG on this site uses 100k-style chips (``min`` 20k, values 100k-100M), which
   matches FEBET rather than the 10-chip tables of GK881/E3951.

Table scanning, sync and bet state reuse the shared helpers in
``aibcr.adapters.febet``.
"""

import time
from urllib.parse import urlsplit

from aibcr.adapters import febet as DG

_CASINO_LABEL = "casino trực tiếp"
_DG_NAME = "dreamgaming"

_DISMISS_JS = r"""
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.05;
  } catch (error) { return false; }
};
const closed = [];
for (const selector of arguments[0]) {
  for (const button of document.querySelectorAll(selector)) {
    if (!visible(button)) continue;
    const rect = button.getBoundingClientRect();
    if (rect.width > 90 || rect.height > 90) continue;
    try { button.click(); closed.push(selector); } catch (error) {}
  }
}
return {closed};
"""

# Desktop lists categories as `.side-item > .side-text`. The mobile build keeps
# the same labels in a compact tab bar with other class names, so the lookup
# falls back to scanning every element whose text matches exactly.
_CLICK_SIDE_JS = r"""
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const wanted = norm(arguments[0]);
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const primary = [...document.querySelectorAll('.side-text')];
let side = primary.find((node) => norm(node.textContent) === wanted);
if (!side) {
  // Mobile tab bars: a leaf element carrying exactly the label.
  side = [...document.querySelectorAll(
    '.van-tab, .tab-item, [class*=tab], [class*=category], [class*=menu] span, nav span, nav a')]
    .find((node) => visible(node) && node.children.length === 0
      && norm(node.textContent) === wanted);
}
if (!side) {
  side = [...document.querySelectorAll('span, div, a, button, li')]
    .find((node) => visible(node) && node.children.length === 0
      && norm(node.textContent) === wanted);
}
if (!side) {
  return {ok: false, labels: primary.map((node) => norm(node.textContent)).slice(0, 20)};
}
const item = side.closest('.side-item') || side.parentElement || side;
side.scrollIntoView({block: 'center', inline: 'center'});
try { side.click(); } catch (error) {}
try { if (item && item !== side) item.click(); } catch (error) {}
return {ok: true};
"""

_LIVE_STATE_JS = r"""
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const banners = [...document.querySelectorAll('img.platform-banner-full, img[alt]')]
  .filter(visible);
return {
  path: location.pathname,
  bannerCount: banners.length,
  names: banners.map((node) => String(node.alt || '').trim()),
  active: [...document.querySelectorAll('.side-item.active')]
    .map((node) => String(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30)),
  modalVisible: [...document.querySelectorAll('.v5-auth-modal')].some(visible)
};
"""

_CLICK_DG_JS = r"""
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const banners = [...document.querySelectorAll('img.platform-banner-full, img[alt]')]
  .filter((node) => {
    try {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    } catch (error) { return false; }
  });
const target = banners.find((node) =>
  norm(node.alt).replace(/\s+/g, '') === arguments[0]);
if (!target) return {ok: false, names: banners.map((node) => node.alt).slice(0, 20)};
// The click handler sits on a wrapper above the banner image.
let node = target;
let clickable = target;
let hops = 0;
while (node && hops < 6) {
  const cls = String(node.className || '');
  if (node.tagName === 'A' || /item|card|platform|game/i.test(cls)) clickable = node;
  node = node.parentElement;
  hops += 1;
}
target.scrollIntoView({block: 'center', inline: 'center'});
try { target.click(); } catch (error) {}
try { clickable.click(); } catch (error) {}
return {ok: true, alt: target.alt};
"""

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


def _safe_location(driver):
    """Return only host/path; never put query strings or session tokens in logs."""
    try:
        parsed = urlsplit(driver.current_url or "")
        return (parsed.hostname or "unknown") + (parsed.path or "/")
    except Exception:
        return "unknown"


def dismiss_overlays(driver, rounds=3, pause=1.0):
    """Close the auth overlay or promo popups; credentials are never read."""
    selectors = [".van-icon-cross", ".van-popup__close-icon", ".popup_modal_close",
                 ".popup_modal_wrap [class*=close]", ".bottom-modal [class*=close]"]
    closed = []
    for _ in range(max(1, rounds)):
        try:
            result = driver.execute_script(_DISMISS_JS, selectors) or {}
        except Exception:
            return closed
        closed.extend(result.get("closed") or [])
        if not result.get("closed"):
            break
        time.sleep(pause)
    return closed


def _lobby_window(driver):
    """Handle of a window whose top-level URL is the DG lobby."""
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            if "ddnewpc" in (driver.current_url or "").lower():
                return handle
        except Exception:
            continue
    return None


def promote_lobby_to_tab(driver, source_handle):
    """Load the DG lobby URL in the profile tab and drop any extra window.

    VNWTop opens DreamGaming with ``window.open``, so a second Chrome window
    appears next to the profile window. The lobby URL is read from that window,
    loaded into ``source_handle``, and the extras are closed so only one window
    remains. The URL holds a session token, so it is never logged or returned.
    """
    if driver is None:
        return False
    lobby_url = ""
    extra = []
    for handle in driver.window_handles:
        if handle == source_handle:
            continue
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            current = driver.current_url or ""
        except Exception:
            continue
        extra.append(handle)
        if "ddnewpc" in current.lower():
            lobby_url = current
    if not lobby_url:
        return False
    for handle in extra:
        try:
            driver.switch_to.window(handle)
            driver.close()
        except Exception:
            continue
    try:
        driver.switch_to.window(source_handle)
        driver.switch_to.default_content()
    except Exception:
        return False
    # CDP navigation keeps an OmniLogin/Hidemium session alive; ``get`` would
    # rebind the target and make the manager close Chrome.
    return DG.navigate_top(driver, lobby_url)


def open_dg(driver, wait=150.0, log=None):
    """Open VNWTop's DG lobby: overlays -> Casino trực tiếp -> DreamGaming."""
    deadline = time.monotonic() + max(1.0, float(wait))

    def report(message, level="info"):
        if log:
            try:
                log("VNWTop · " + message, level)
            except Exception:
                pass

    def remain(maximum=30.0):
        return max(0.1, min(float(maximum), deadline - time.monotonic()))

    if driver is None:
        return {"ok": False, "site_id": "vnwtop", "error": "Chưa mở Chrome cho profile này."}

    report("Bắt đầu; trang hiện tại: %s." % _safe_location(driver))

    existing = DG.lobby_tables(driver, wait=1.0)
    if existing.get("ok"):
        report("Sảnh DG đã mở sẵn; tìm thấy %s bàn." % len(existing.get("tables") or []))
        return {"ok": True, "site_id": "vnwtop", "already_open": True, "lobby_ready": True,
                "tables": existing.get("tables") or [],
                "note": "Đã nhận diện sảnh DG VNWTop đang mở."}

    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    source_handle = driver.current_window_handle
    before = set(driver.window_handles)

    closed = dismiss_overlays(driver)
    if closed:
        report("Đã đóng %s lớp che (đăng nhập/quảng cáo)." % len(closed))

    stage = "mở mục Casino trực tiếp"
    nav = driver.execute_script(_CLICK_SIDE_JS, _CASINO_LABEL) or {}
    if not nav.get("ok"):
        report("Không tìm thấy mục Casino trực tiếp trong menu trái.", "error")
        return {"ok": False, "site_id": "vnwtop",
                "error": "Không tìm thấy mục Casino trực tiếp trên VNWTop."}

    stage = "chờ danh sách nhà cung cấp"
    live = {}
    live_deadline = min(deadline, time.monotonic() + remain(40.0))
    while time.monotonic() < live_deadline:
        live = driver.execute_script(_LIVE_STATE_JS) or {}
        names = [str(name).lower().replace(" ", "") for name in live.get("names") or []]
        if _DG_NAME in names:
            break
        time.sleep(0.75)
    names = [str(name).lower().replace(" ", "") for name in live.get("names") or []]
    if _DG_NAME not in names:
        report("Chưa thấy thẻ DreamGaming trong sảnh Casino.", "error")
        return {"ok": False, "site_id": "vnwtop",
                "error": "VNWTop chưa hiển thị thẻ DreamGaming sau khi vào Casino trực tiếp."}
    report("Sảnh Casino hiển thị %s nhà cung cấp." % live.get("bannerCount"))

    stage = "bấm DreamGaming"
    # Prefer in-place navigation so no second window appears at all.
    try:
        driver.execute_script(_NAVIGATE_IN_PLACE_JS)
    except Exception:
        pass
    click = driver.execute_script(_CLICK_DG_JS, _DG_NAME) or {}
    if not click.get("ok"):
        report("Không bấm được thẻ DreamGaming.", "error")
        return {"ok": False, "site_id": "vnwtop",
                "error": "VNWTop không mở được DreamGaming từ thẻ nhà cung cấp."}
    report("Đã bấm thẻ DreamGaming; chờ sảnh DG tải.")

    stage = "chờ sảnh DG"
    lobby = {}
    poll_deadline = min(deadline, time.monotonic() + remain(60.0))
    while time.monotonic() < poll_deadline:
        lobby = DG.lobby_tables(driver, wait=2.0)
        if lobby.get("ok"):
            break
        # A stray popup window may exist; fold it into the profile tab.
        if any(handle not in before for handle in driver.window_handles):
            if promote_lobby_to_tab(driver, source_handle):
                report("Đã gộp cửa sổ DG vào tab chính; chỉ còn 1 cửa sổ Chrome.")
                before = set(driver.window_handles)
                continue
        time.sleep(1.0)

    if not lobby.get("ok") and promote_lobby_to_tab(driver, source_handle):
        report("Đã gộp cửa sổ DG vào tab chính; chỉ còn 1 cửa sổ Chrome.")
        lobby = DG.lobby_tables(driver, wait=25.0)

    if not lobby.get("ok"):
        error = lobby.get("error") or "Sảnh DG chưa tải xong."
        report("Sảnh DG chưa sẵn sàng: %s" % error, "error")
        return {"ok": False, "site_id": "vnwtop", "error": error}

    tables = lobby.get("tables") or []
    report("Sảnh DG sẵn sàng; tìm thấy %s bàn." % len(tables))
    return {"ok": True, "site_id": "vnwtop", "already_open": False, "lobby_ready": True,
            "tables": tables,
            "note": "Đã mở sảnh DG từ VNWTop trong 1 cửa sổ Chrome."}
