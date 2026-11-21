"""E3951-specific navigation into its Dream Gaming lobby.

Live site flow (Vue SPA observed on ``www.e3951.com/seamless``):

1. A pre-filled login modal (``.loginPopupModal`` / ``form.login-form``) opens on
   load. Its "Đăng nhập" button (``button.submit_btn``) signs in with the saved
   session. The promo/notice popups must **not** be dismissed with the login
   modal's own close button, so login runs before promo dismissal.
2. The top navigation holds ``.nav-item > .nav-name``; clicking the
   ``.nav-name`` for ``Casino`` routes the SPA to ``/live``.
3. ``/live`` renders a vendor strip of ``.vendor-box`` cards. Each holds two
   images: ``.vendor-icon-active`` (hover/active) and ``.vendor-icon-default``.
   DG is identified by ``DG-DEFAULT.png`` / ``DG-ACTIVE.png``.
4. After selecting the DG box, the page's single launch control is
   ``.card-btn`` labelled "CHƠI NGAY".
5. The Dream Gaming lobby then loads **inside the same window** (no popup), so
   the shared helpers in ``aibcr.adapters.febet`` can scan tables, sync a table
   and read bet state unchanged.
"""

import time
from urllib.parse import urlsplit

from aibcr.adapters import febet as DG

_PROMO_CLOSE_SELECTORS = (
    ".popup_modal_close",
    ".close-popup",
    ".announce-popup-close",
)

_DISMISS_PROMO_JS = r"""
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.05;
  } catch (error) { return false; }
};
// Never click a control that belongs to the login form.
const inLogin = (node) => !!node.closest('.loginPopupModal, form.login-form');

const closed = [];
for (const selector of arguments[0]) {
  for (const button of document.querySelectorAll(selector)) {
    if (!visible(button) || inLogin(button)) continue;
    const rect = button.getBoundingClientRect();
    if (rect.width > 140 || rect.height > 140) continue;
    try { button.click(); closed.push(selector); } catch (error) {}
  }
}
return {closed};
"""

_LOGIN_STATE_JS = r"""
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.05;
  } catch (error) { return false; }
};
const modal = [...document.querySelectorAll('.loginPopupModal')].find(visible);
const form = document.querySelector('form.login-form');
const user = document.querySelector('input.username_input');
const pass = document.querySelector('input.password_input');
const submit = form ? form.querySelector('button.submit_btn') : null;
return {
  modalVisible: !!modal,
  formPresent: !!form,
  submitVisible: submit ? visible(submit) : false,
  // Only boolean flags leave the page; credential text never does.
  hasUsername: !!(user && user.value.length > 0),
  hasPassword: !!(pass && pass.value.length > 0)
};
"""

_LOGIN_JS = r"""
const visible = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.05;
  } catch (error) { return false; }
};
const modal = [...document.querySelectorAll('.loginPopupModal')].find(visible);
if (!modal) return {clicked: false, reason: 'no-modal'};
const form = document.querySelector('form.login-form');
const submit = form ? form.querySelector('button.submit_btn') : null;
const user = document.querySelector('input.username_input');
const pass = document.querySelector('input.password_input');
if (!submit) return {clicked: false, reason: 'no-submit'};
if (!user || !pass || !user.value || !pass.value) {
  return {clicked: false, reason: 'empty-credentials',
          hasUsername: !!(user && user.value), hasPassword: !!(pass && pass.value)};
}
submit.scrollIntoView({block: 'center'});
// A Vue handler listens for the form submit, so fire the real form event first.
try { if (form.requestSubmit) form.requestSubmit(submit); } catch (error) {}
try { submit.click(); } catch (error) {}
return {clicked: true};
"""

_CLICK_NAV_JS = r"""
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const span = [...document.querySelectorAll('.nav-name')]
  .find((node) => norm(node.textContent) === arguments[0]);
if (!span) {
  return {ok: false, labels: [...document.querySelectorAll('.nav-name')]
    .map((node) => norm(node.textContent))};
}
span.scrollIntoView({block: 'center', inline: 'center'});
span.click();
return {ok: true};
"""

_LIVE_STATE_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const boxes = [...document.querySelectorAll('.vendor-box')];
const names = boxes.map((box) => {
  const img = box.querySelector('img');
  const src = img ? (img.getAttribute('src') || '') : '';
  const match = src.match(/\/([A-Za-z0-9]+)-(?:DEFAULT|ACTIVE)\.png/i);
  return match ? match[1].toUpperCase() : '';
});
return {
  path: location.pathname,
  boxCount: boxes.length,
  vendorNames: names,
  launch: [...document.querySelectorAll('.card-btn')]
    .filter(vis).map((node) => String(node.textContent || '').replace(/\s+/g, ' ').trim())
};
"""

_SELECT_DG_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const boxes = [...document.querySelectorAll('.vendor-box')];
const isDg = (box) => [...box.querySelectorAll('img')].some((img) =>
  /\/DG-(?:DEFAULT|ACTIVE)\.png$/i.test(img.getAttribute('src') || ''));
const target = boxes.find(isDg);
if (!target) return {ok: false, count: boxes.length};
target.scrollIntoView({block: 'center', inline: 'center'});
(target.querySelector('.vendor-icon') || target).click();
return {ok: true};
"""

_CLICK_LAUNCH_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const buttons = [...document.querySelectorAll('.card-btn')].filter(vis);
const target = buttons.find((node) => /chơi ngay|choi ngay|play now/i.test(node.textContent || ''))
  || buttons[buttons.length - 1];
if (!target) return {ok: false};
target.scrollIntoView({block: 'center'});
target.click();
return {ok: true, label: String(target.textContent || '').replace(/\s+/g, ' ').trim()};
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


def _navigate_in_place(driver):
    """Keep the DG lobby in this window instead of a second Chrome window."""
    try:
        driver.execute_script(_NAVIGATE_IN_PLACE_JS)
        return True
    except Exception:
        return False


def dismiss_promos(driver, rounds=4, pause=1.0):
    """Close promo/notice popups without touching the login modal."""
    closed = []
    for _ in range(max(1, rounds)):
        try:
            result = driver.execute_script(_DISMISS_PROMO_JS,
                                           list(_PROMO_CLOSE_SELECTORS)) or {}
        except Exception:
            return closed
        closed.extend(result.get("closed") or [])
        if not result.get("closed"):
            break
        time.sleep(pause)
    return closed


def login_state(driver):
    try:
        return driver.execute_script(_LOGIN_STATE_JS) or {}
    except Exception:
        return {}


def login_if_prompted(driver):
    """Press the pre-filled login button; credentials never leave the page."""
    try:
        return driver.execute_script(_LOGIN_JS) or {"clicked": False}
    except Exception:
        return {"clicked": False}


def wait_logged_in(driver, timeout=30.0):
    """Wait until the login modal disappears after a successful sign-in."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        state = login_state(driver)
        if not state.get("modalVisible"):
            return True
        time.sleep(0.75)
    return False


def promote_lobby_to_tab(driver):
    """Load the DG lobby URL in the profile tab so E39's popups disappear.

    The lobby runs inside an E3951 iframe, so the site's own promo overlays
    (public notice, ticket/reward popups) keep covering the table. Reading the
    DG document URL and navigating the top-level tab to it removes the site DOM
    entirely; only the Dream Gaming page is left in the window.

    The URL carries a session token, so it is never logged or returned.
    """
    if driver is None:
        return False
    try:
        ctx = DG._dg_context(driver, wait=10.0)
    except Exception:
        return False
    if not ctx:
        return False
    if ctx.get("mode") == "tab":
        return True
    location = str(ctx.get("location") or "")
    if "ddnewpc" not in location.lower():
        return False
    try:
        driver.switch_to.default_content()
        driver.get(location)
    except Exception:
        return False
    return True


def open_dg(driver, wait=150.0, log=None):
    """Open E3951's DG lobby: login -> Casino -> DG vendor -> CHƠI NGAY."""
    deadline = time.monotonic() + max(1.0, float(wait))
    stage = "khởi tạo"

    def report(message, level="info"):
        if log:
            try:
                log("E3951 · " + message, level)
            except Exception:
                pass

    def remain(maximum=30.0):
        return max(0.1, min(float(maximum), deadline - time.monotonic()))

    if driver is None:
        return {"ok": False, "site_id": "e3951", "error": "Chưa mở Chrome cho profile này."}

    report("Bắt đầu; trang hiện tại: %s." % _safe_location(driver))

    stage = "kiểm tra sảnh DG đang mở"
    existing = DG.lobby_tables(driver, wait=1.0)
    if existing.get("ok"):
        report("Sảnh DG đã mở sẵn; tìm thấy %s bàn." % len(existing.get("tables") or []))
        return {"ok": True, "site_id": "e3951", "already_open": True, "lobby_ready": True,
                "tables": existing.get("tables") or [],
                "note": "Đã nhận diện sảnh DG E3951 đang mở."}

    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    source_handle = driver.current_window_handle

    # Login comes first: the promo close button and the login close button share
    # markup, so dismissing promos first can close the login form we still need.
    stage = "đăng nhập nếu có"
    state = login_state(driver)
    if state.get("modalVisible") and state.get("formPresent"):
        if state.get("hasUsername") and state.get("hasPassword"):
            result = login_if_prompted(driver)
            if result.get("clicked"):
                report("Đã bấm Đăng nhập bằng thông tin lưu sẵn; chờ vào trang.")
                if wait_logged_in(driver, remain(45.0)):
                    report("Đăng nhập thành công.")
                else:
                    report("Đã bấm Đăng nhập nhưng hộp đăng nhập vẫn còn.", "warning")
            else:
                report("Không bấm được nút Đăng nhập (%s)."
                       % (result.get("reason") or "không rõ"), "warning")
        else:
            report("Hộp đăng nhập chưa có thông tin lưu sẵn; cần đăng nhập thủ công.", "warning")
            return {"ok": False, "site_id": "e3951",
                    "error": "E3951 đang yêu cầu đăng nhập thủ công cho profile này."}
    else:
        report("Phiên đăng nhập còn hiệu lực; không cần đăng nhập lại.")

    stage = "đóng popup quảng cáo"
    closed = dismiss_promos(driver)
    if closed:
        report("Đã đóng %s popup quảng cáo." % len(closed))
    else:
        report("Không có popup quảng cáo cần đóng; tiếp tục.")

    stage = "mở mục Casino"
    nav = driver.execute_script(_CLICK_NAV_JS, "casino") or {}
    if not nav.get("ok"):
        report("Không tìm thấy mục Casino trên thanh điều hướng.", "error")
        return {"ok": False, "site_id": "e3951",
                "error": "Không tìm thấy mục Casino trên E3951."}
    report("Đã chọn mục Casino; chờ danh sách nhà cung cấp.")

    stage = "chờ sảnh Casino"
    live = {}
    live_deadline = min(deadline, time.monotonic() + remain(45.0))
    while time.monotonic() < live_deadline:
        live = driver.execute_script(_LIVE_STATE_JS) or {}
        if live.get("boxCount"):
            break
        time.sleep(0.75)
    if not live.get("boxCount"):
        # The route may have demanded a fresh sign-in after the navigation.
        if login_if_prompted(driver).get("clicked"):
            report("Trang Casino yêu cầu đăng nhập lại; đã bấm Đăng nhập.", "warning")
            wait_logged_in(driver, remain(30.0))
            live_deadline = min(deadline, time.monotonic() + remain(30.0))
            while time.monotonic() < live_deadline:
                live = driver.execute_script(_LIVE_STATE_JS) or {}
                if live.get("boxCount"):
                    break
                time.sleep(0.75)
    if not live.get("boxCount"):
        report("Chưa thấy danh sách nhà cung cấp sau khi vào Casino.", "error")
        return {"ok": False, "site_id": "e3951",
                "error": "E3951 chưa hiển thị danh sách nhà cung cấp sau khi vào Casino."}
    report("Sảnh Casino hiển thị %s nhà cung cấp (đường dẫn %s)."
           % (live.get("boxCount"), live.get("path")))

    stage = "chọn nhà cung cấp DG"
    select = driver.execute_script(_SELECT_DG_JS) or {}
    if not select.get("ok"):
        report("Không thấy nhà cung cấp DG trong sảnh Casino.", "error")
        return {"ok": False, "site_id": "e3951",
                "error": "E3951 không có nhà cung cấp DG trong sảnh Casino."}
    report("Đã chọn nhà cung cấp DG; chờ nút CHƠI NGAY.")

    stage = "bấm CHƠI NGAY"
    _navigate_in_place(driver)
    before = set(driver.window_handles)
    launch = driver.execute_script(_CLICK_LAUNCH_JS) or {}
    if not launch.get("ok"):
        report("Không thấy nút CHƠI NGAY sau khi chọn DG.", "error")
        return {"ok": False, "site_id": "e3951",
                "error": "E3951 không hiển thị nút CHƠI NGAY cho DG."}
    report("Đã bấm %s; chờ sảnh Dream Gaming tải." % (launch.get("label") or "CHƠI NGAY"))

    stage = "chờ sảnh DG"
    lobby = {}
    poll_deadline = min(deadline, time.monotonic() + remain(75.0))
    while time.monotonic() < poll_deadline:
        lobby = DG.lobby_tables(driver, wait=2.0)
        if lobby.get("ok"):
            break
        time.sleep(1.0)

    if not lobby.get("ok"):
        error = lobby.get("error") or "Sảnh DG chưa tải xong."
        report("Sảnh DG chưa sẵn sàng: %s" % error, "error")
        return {"ok": False, "site_id": "e3951", "error": error}

    stage = "đưa sảnh DG lên tab chính"
    promoted = promote_lobby_to_tab(driver)
    if promoted:
        report("Đã thay URL tab bằng sảnh DG; loại bỏ hoàn toàn popup của trang.")
        promoted_lobby = DG.lobby_tables(driver, wait=20.0)
        if promoted_lobby.get("ok"):
            lobby = promoted_lobby
        else:
            report("Sảnh DG trên tab chính chưa đọc được bàn: %s"
                   % (promoted_lobby.get("error") or "chưa rõ"), "warning")
    else:
        report("Chưa tách được sảnh DG sang tab chính; vẫn dùng iframe của trang.", "warning")

    extra = [item for item in driver.window_handles if item not in before]
    if extra:
        report("Có thêm %s cửa sổ Chrome do site tự mở." % len(extra), "warning")

    tables = lobby.get("tables") or []
    report("Sảnh DG sẵn sàng; tìm thấy %s bàn." % len(tables))
    return {"ok": True, "site_id": "e3951", "already_open": False, "lobby_ready": True,
            "tables": tables,
            "note": "Đã mở sảnh DG từ E3951."}
