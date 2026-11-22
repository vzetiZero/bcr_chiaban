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

# Desktop uses `.popup_modal_close`; the mobile layout shows `.popup_container_v2`
# promos and a `.bottom-modal` "add to home screen" sheet, each with its own
# close control.
_PROMO_CLOSE_SELECTORS = (
    ".popup_modal_close",
    ".close-popup",
    ".announce-popup-close",
    ".popup_container_v2 [class*=close]",
    ".bottom-modal [class*=close]",
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
// Mobile: header `.login-btn` opens a dedicated `/m/login` page whose form uses
// `.form-content` with `input[name=username]` / `input[name=password]`.
const mobileForm = document.querySelector('form.form-content')
  || document.querySelector('.form-page-container form');
const form = document.querySelector('form.login-form') || mobileForm;
const user = document.querySelector('input.username_input')
  || document.querySelector('input[name=username]');
const pass = document.querySelector('input.password_input')
  || document.querySelector('input[name=password]');
const submit = (form && (form.querySelector('button.submit_btn')
  || form.querySelector('button.submit-btn')))
  || document.querySelector('button.submit-btn.login-btn');
return {
  modalVisible: !!modal,
  formPresent: !!form,
  submitVisible: submit ? visible(submit) : false,
  mobile: !modal && !!mobileForm,
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
const mobileForm = document.querySelector('form.form-content')
  || document.querySelector('.form-page-container form');
const form = document.querySelector('form.login-form') || mobileForm;
if (!modal && !form) {
  // Mobile header button: it only navigates to /m/login, so click it and let the
  // caller wait for the form to appear before submitting.
  const opener = document.querySelector('.login-btn, .login-register .login-btn');
  if (opener && visible(opener)) {
    opener.click();
    return {clicked: false, reason: 'opened-login-page', opened: true};
  }
  return {clicked: false, reason: 'no-form'};
}
const submit = (form && (form.querySelector('button.submit_btn')
  || form.querySelector('button.submit-btn')))
  || document.querySelector('button.submit-btn.login-btn');
const user = document.querySelector('input.username_input')
  || document.querySelector('input[name=username]');
const pass = document.querySelector('input.password_input')
  || document.querySelector('input[name=password]');
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

# Desktop renders the menu as `.nav-name`; the mobile layout (`/m/index.html`)
# uses a horizontal `.game-menu-item` strip with the same labels. Both are
# matched by exact text so a rename cannot silently click the wrong entry.
_CLICK_NAV_JS = r"""
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
const selectors = ['.nav-name', '.game-menu-item'];
const labels = [];
for (const selector of selectors) {
  for (const node of document.querySelectorAll(selector)) {
    const text = norm(node.textContent);
    if (text) labels.push(text);
    if (text === wanted && visible(node)) {
      node.scrollIntoView({block: 'center', inline: 'center'});
      node.click();
      return {ok: true, layout: selector};
    }
  }
}
return {ok: false, labels: labels.slice(0, 20)};
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
// Desktop cards are `.vendor-box`; the mobile page renders `.vendor-game-item`
// inside `.home-vendor-list`. Both expose the provider through an <img>.
const DESKTOP_CARD = '.vendor-box';
const MOBILE_CARD = '.vendor-game-item';
const boxes = [...document.querySelectorAll(DESKTOP_CARD + ',' + MOBILE_CARD)];
const providerOf = (src) => {
  // Desktop: `.../DG-DEFAULT.png`. Mobile: `.../gcs__live-DG_1792424580512.png`,
  // where the provider token sits right before the timestamp.
  const desktop = src.match(/\/([A-Za-z0-9]+)-(?:DEFAULT|ACTIVE)\.(?:png|webp)/i);
  if (desktop) return desktop[1].toUpperCase();
  const mobile = src.match(/([A-Za-z0-9]+)_\d+\.(?:png|webp|avif)$/i);
  return mobile ? mobile[1].toUpperCase() : '';
};
const names = boxes.map((box) => {
  const img = box.querySelector('img');
  return img ? providerOf(img.getAttribute('src') || '') : '';
});
const launchSelectors = ['.card-btn', '.vendor-game-item .play-btn',
                         '.vendor-game-item [class*=btn]'];
const launch = [];
for (const selector of launchSelectors) {
  for (const node of document.querySelectorAll(selector)) {
    if (!vis(node)) continue;
    launch.push(String(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 20));
  }
}
return {
  path: location.pathname,
  boxCount: boxes.length,
  vendorNames: names,
  launch: launch.slice(0, 8),
  mobile: document.querySelectorAll(MOBILE_CARD).length > 0
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
const boxes = [...document.querySelectorAll('.vendor-box,.vendor-game-item')];
const isDg = (box) => [...box.querySelectorAll('img')].some((img) => {
  const src = img.getAttribute('src') || '';
  // Desktop `DG-DEFAULT.png`, mobile `gcs__live-DG_<ts>.png`.
  return /\/DG-(?:DEFAULT|ACTIVE)\./i.test(src) || /-DG_\d+\./i.test(src)
    || /dream\s*gaming/i.test(img.alt || '');
});
const target = boxes.find(isDg);
if (!target) return {ok: false, count: boxes.length};
target.scrollIntoView({block: 'center', inline: 'center'});
(target.querySelector('.vendor-icon,.vendor-game-img') || target).click();
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
let target = buttons.find((node) => /chơi ngay|choi ngay|play now/i.test(node.textContent || ''))
  || buttons[buttons.length - 1];
let label = target ? String(target.textContent || '').replace(/\s+/g, ' ').trim() : '';
if (!target) {
  // Mobile: tapping the provider card itself opens the lobby.
  const dgCard = [...document.querySelectorAll('.vendor-game-item')].find((card) =>
    [...card.querySelectorAll('img')].some((img) => {
      const src = img.getAttribute('src') || '';
      return /\/DG-(?:DEFAULT|ACTIVE)\./i.test(src) || /-DG_\d+\./i.test(src);
    }));
  if (dgCard) {
    target = dgCard;
    label = 'vendor-card';
  }
}
if (!target) return {ok: false};
target.scrollIntoView({block: 'center'});
target.click();
return {ok: true, label};
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
    """Wait until the login form disappears after a successful sign-in.

    Desktop hides the modal; mobile leaves the `/m/login` page, so both the
    missing modal and the missing form count as success.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        state = login_state(driver)
        if not state.get("modalVisible") and not state.get("formPresent"):
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
    # Desktop shows a pre-filled modal; mobile shows a header button that opens
    # a separate `/m/login` page. Both paths are handled here.
    needs_login = bool(state.get("modalVisible") or state.get("mobile"))
    if needs_login and not state.get("formPresent"):
        # Mobile: press the header button, then wait for the login page form.
        opened = login_if_prompted(driver)
        if opened.get("opened"):
            report("Đã mở trang đăng nhập trên giao diện điện thoại.")
            deadline = time.monotonic() + remain(20.0)
            while time.monotonic() < deadline:
                time.sleep(0.5)
                state = login_state(driver)
                if state.get("formPresent"):
                    break
            if not state.get("formPresent"):
                report("Không mở được form đăng nhập trên giao diện điện thoại.", "error")
                return {"ok": False, "site_id": "e3951",
                        "error": "E3951 mobile không mở được form đăng nhập."}
    if needs_login and state.get("formPresent"):
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
    elif not needs_login:
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
        # The first click sometimes lands before the SPA finished wiring the
        # vendor card. Retry the launch once before reporting a hard failure.
        report("Sảnh DG chưa lên sau lần bấm đầu; thử bấm CHƠI NGAY lại.", "warning")
        retry = min(deadline, time.monotonic() + remain(60.0))
        for _ in range(2):
            if time.monotonic() >= retry:
                break
            driver.execute_script(_SELECT_DG_JS)
            time.sleep(1.0)
            driver.execute_script(_CLICK_LAUNCH_JS)
            sub = min(retry, time.monotonic() + 25.0)
            while time.monotonic() < sub:
                lobby = DG.lobby_tables(driver, wait=2.0)
                if lobby.get("ok"):
                    break
                time.sleep(1.0)
            if lobby.get("ok"):
                report("Lần bấm lại đã mở được sảnh DG.")
                break

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
