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


def _promote_lobby(driver, report, wait=6.0, settle=25.0, prefer_handle=None):
    """Move the DG lobby out of the site iframe and into the tab URL.

    The mobile build keeps the lobby inside an iframe whose host is the DG
    origin, so the frame's real URL can be loaded as the page. That removes the
    site DOM and lets the shared table sync rewrite ``direct1.html`` so every
    profile joins the same table. Only the host is logged.
    """
    if not (hasattr(driver, "execute_cdp_cmd") or hasattr(driver, "get")):
        return {"ok": False, "promoted": False,
                "error": "Trình duyệt không hỗ trợ điều hướng tab."}
    promoted = DG.promote_lobby_to_tab(
        driver, site_hosts=("gk881.vip",), wait=wait, settle=settle,
        prefer_handle=prefer_handle)
    if promoted.get("ok"):
        report("Đã thay URL trang bằng sảnh DG (%s)."
               % (promoted.get("host") or "DG"))
    else:
        report("Chưa tách được iframe sảnh DG sang tab chính: %s"
               % (promoted.get("error") or "không rõ"), "warning")
    return promoted


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
      && style.visibility !== 'hidden' && style.display !== 'none'
      && style.opacity !== '0';
  } catch (error) { return false; }
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const wanted = ['tôi biết rồi', 'toi biet roi', 'đóng', 'dong', '×', 'x', '✕',
                'đồng ý', 'dong y', 'ok', 'đã hiểu', 'da hieu'];
const closed = [];
const backdrops = () => [...document.querySelectorAll(
  '.cdk-overlay-backdrop, [class*=overlay-backdrop], [class*=dialog-backdrop]')].filter(vis);
const panes = () => [...document.querySelectorAll('.cdk-overlay-pane, [role=dialog]')].filter(vis);
// GK881 mobile xếp lớp bằng Angular CDK: mỗi dialog là một .cdk-overlay-pane kèm
// .cdk-overlay-backdrop riêng, và có thể mở 2-3 cái chồng nhau ("TÔI BIẾT RỒI",
// "TIN TỨC MỚI NHẤT"). Nút đóng thật là <span class="close ...">X</span> chứ
// không phải <button>, nên phải quét cả 'span' và '[class*=close]'.
for (const pane of panes()) {
  const candidates = [...pane.querySelectorAll(
    'button, span, i, a, [class*=close], [class*=Close]')].filter(vis);
  for (const node of candidates) {
    const rect = node.getBoundingClientRect();
    if (rect.width > 300 || rect.height > 260) continue;
    const text = norm(node.textContent);
    const cls = String(node.className || '');
    const isClose = wanted.includes(text) || /(^|[\s_-])close([\s_-]|$)/i.test(cls);
    if (!isClose) continue;
    try { node.click(); closed.push(text || cls.slice(0, 20)); } catch (error) {}
    break;
  }
}
// Không còn pane nào nhưng backdrop vẫn còn -> bấm chính backdrop để đóng.
if (!panes().length) {
  for (const node of backdrops()) {
    try { node.click(); closed.push('backdrop'); } catch (error) {}
  }
}
return {closed, backdrops: backdrops().length, panes: panes().length};
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
// Ưu tiên tuyệt đối thanh danh mục trò chơi (.category-item). Bản mobile GK881
// có thêm các <li> ở header/footer ("Nạp Tiền", "ĐẠI LÝ", "CSKH 24/7") nằm TRƯỚC
// thanh danh mục trong DOM; quét chung 'li, a, div' từng khớp "đại lý" và bấm
// sang trang đại lý (bắt đăng nhập) thay vì mở Casino.
const strip = [...document.querySelectorAll('.category-item')].filter(vis);
const exact = strip.find((node) => norm(node.textContent) === wanted);
if (exact) {
  exact.scrollIntoView({block: 'center', inline: 'center'});
  try { exact.click(); } catch (error) {}
  const innerExact = exact.querySelector('span, div, img');
  if (innerExact) { try { innerExact.click(); } catch (error) {} }
  return {ok: true, label: norm(exact.textContent).slice(0, 30), via: 'category-item'};
}
// Không có thanh danh mục đúng chuẩn: chỉ xét các mục trò chơi, và loại hẳn
// các mục tài khoản/đại lý để không bấm nhầm.
const skip = ['trang chủ', 'trangchu', 'home', 'thể thao', 'the thao', 'tin tức', 'tin tuc',
              'khuyến mãi', 'khuyen mai', 'liên hệ', 'lien he', 'tải app', 'tai app',
              'đại lý', 'dai ly', 'nạp tiền', 'nap tien', 'rút tiền', 'rut tien',
              'cskh', 'tài khoản', 'tai khoan', 'đăng nhập', 'dang nhap',
              'đăng ký', 'dang ky', 'giới thiệu', 'gioi thieu'];
const aliases = ['casino', 'sòng bạc', 'song bac', 'live casino', 'baccarat'];
const items = [...document.querySelectorAll(
  '.category-item, [class*=category-item], li, a, div[role="button"], .menu-item, .tab-item')]
  .filter(vis);
const labels = items.map((node) => norm(node.textContent)).filter(Boolean);
const target = items.find((node) => {
  const text = norm(node.textContent);
  if (!text || skip.some((s) => text === s || text.startsWith(s))) return false;
  return aliases.some((a) => text === a || text.includes(a));
});
if (!target) return {ok: false, labels: labels.slice(0, 20)};
target.scrollIntoView({block: 'center', inline: 'center'});
target.click();
return {ok: true, label: norm(target.textContent).slice(0, 30), via: 'fallback'};
"""

# Mobile provider grid: a list of <li> cards, each with an <img> and a label
# <span> like "DG Trực Tuyến". No provider/vendor class exists, so the card is
# found by its label text (or a DG-looking image name) and the whole card tapped.
_MOBILE_DG_CARD_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  } catch (error) { return false; }
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const isDgLabel = (text) => {
  const value = norm(text);
  return value === 'dg' || value === 'dg trực tuyến' || value === 'dg truc tuyen'
    || value.startsWith('dg trực tuyến') || value.startsWith('dg truc tuyen')
    || value.startsWith('dream gaming') || value.startsWith('dreamgaming');
};
// Có khung còn marquee "DG CASINO <tên bàn> <số người>" — đó là dòng quảng cáo bàn
// đang chơi, không phải thẻ nhà cung cấp; nhãn dài quá thì bỏ qua.
const isProviderCard = (node) => {
  const text = norm(node.textContent);
  if (!text || text.length > 40) return false;
  return isDgLabel(text);
};
const cards = [...document.querySelectorAll(
  'li, div, a, [class*=provider], [class*=vendor], [class*=game-item], [class*=item]')]
  .filter((node) => vis(node) && node.querySelector('img'));
const labelMatch = cards.find(isProviderCard);
const imageMatch = cards.find((node) => [...node.querySelectorAll('img')].some((img) =>
  /dg[-_]|dream|dg\./i.test((img.getAttribute('src') || '') + ' ' + (img.alt || '')))
  && norm(node.textContent).length <= 40);
const target = labelMatch || imageMatch;
if (!target) {
  return {ok: false, count: cards.length,
          labels: cards.map((node) => norm(node.textContent).slice(0, 24))
            .filter(Boolean).slice(0, 12)};
}
target.scrollIntoView({block: 'center', inline: 'center'});
try { target.click(); } catch (error) {}
const inner = target.querySelector('span, div, img');
if (inner) { try { inner.click(); } catch (error) {} }
return {ok: true, label: norm(target.textContent).slice(0, 30)};
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
    """True when the browser is presenting the mobile build.

    The decisive signal is the mobile user-agent: only the phone build lacks the
    Angular ``ng-click`` menu, and page markup changes between lobby screens
    (``/Lobby/RecommendGame`` has no ``.category-item``), so DOM probing alone
    misclassified those pages as desktop and the desktop flow then timed out.
    """
    try:
        data = driver.execute_script(r"""
          const ua = navigator.userAgent || '';
          const touch = navigator.maxTouchPoints || 0;
          return {
            mobileUa: /Android|Mobile|iPhone|iPad/i.test(ua),
            touch,
            ng: document.querySelectorAll('li[ng-click*="entrance"]').length,
            categories: document.querySelectorAll('.category-item').length,
            hub: /link truy cập/i.test(document.body.innerText || ''),
          };
        """) or {}
    except Exception:
        return False
    if data.get("mobileUa"):
        return True
    if int(data.get("touch") or 0) > 0 and not data.get("ng"):
        return True
    return bool(data.get("categories")) or bool(data.get("hub"))


def _is_login_wall(driver):
    """True when the tab is sitting on the GK881 login/maintenance page.

    This is *not* an immediate hard stop: a measured run showed
    ``/Account/Login?loginToGame=…`` resolving by itself into
    ``/Account/LoginToSupplier?SupplierType=DG`` (the DG hand-off page, which
    mounts the phone lobby even for a signed-out profile). Callers therefore use
    this only to explain a timeout — the wait itself must go on, which is what
    "chạy đúng đến khi vào bàn được" needs. Reporting the login error too early
    would fail runs that do reach the lobby.
    """
    try:
        data = driver.execute_script(r"""
          const path = String(location.pathname || '').toLowerCase();
          const visible = (node) => {
            try {
              const rect = node.getBoundingClientRect();
              const style = getComputedStyle(node);
              return rect.width > 0 && rect.height > 0
                && style.visibility !== 'hidden' && style.display !== 'none';
            } catch (error) { return false; }
          };
          const password = [...document.querySelectorAll('input[type="password"]')]
            .some(visible);
          return {
            path: path,
            password: password,
            maintenance: /\/maintenance/.test(path),
            handoff: /logintosupplier/.test(path),
          };
        """) or {}
    except Exception:
        return False
    if data.get("handoff"):
        return False
    if data.get("maintenance"):
        return True
    return bool(data.get("password"))


_LOGIN_HINT = ("Profile chưa đăng nhập GK881: trang đang dừng ở màn hình đăng nhập. "
               "Hãy đăng nhập trên cửa sổ Chrome rồi chạy lại.")

# A rendered password box only exists on the real login screen; the DG hand-off
# page (``LoginToSupplier``) has none. Measured on the live site, the login page
# does not resolve by itself, so it needs a human — but aborting immediately
# throws away a run the operator is willing to finish by hand. The flow
# therefore hands control over and waits for the sign-in to complete.
_LOGIN_WAIT = 300.0          # how long to let the operator sign in
_LOGIN_POLL = 1.0
# A measured run showed ``/Account/Login?loginToGame=…`` resolving by itself into
# the DG hand-off page, while a really signed-out profile stays on the form. The
# route alone is therefore not proof of a wall: it must persist for this grace
# before the operator is asked to type anything.
_LOGIN_GRACE = 8.0


def _login_page_state(driver):
    """Snapshot used while waiting for a human to finish signing in.

    Returns ``{"wall": bool, "signed_in": bool, "reason": str}``. ``signed_in``
    is deliberately conservative: it only counts when the login form is gone
    *and* the page is no longer the site's login/maintenance route.
    """
    try:
        data = driver.execute_script(r"""
          const path = String(location.pathname || '').toLowerCase();
          const visible = (node) => {
            try {
              const rect = node.getBoundingClientRect();
              const style = getComputedStyle(node);
              return rect.width > 0 && rect.height > 0
                && style.visibility !== 'hidden' && style.display !== 'none';
            } catch (error) { return false; }
          };
          const password = [...document.querySelectorAll('input[type="password"]')]
            .some(visible);
          const loginRoutes = /\/account\/login|\/maintenance/;
          return {
            path: path,
            password: password,
            onLoginRoute: loginRoutes.test(path),
            handoff: /logintosupplier/.test(path),
            hasUserBox: [...document.querySelectorAll(
              'input[name*="user" i], input[name*="account" i], input[id*="user" i]')]
              .some(visible),
          };
        """) or {}
    except Exception:
        return {"wall": False, "signed_in": False, "reason": "script-error"}
    if data.get("handoff"):
        return {"wall": False, "signed_in": True, "reason": "handoff"}
    wall = bool(data.get("password")) or bool(data.get("onLoginRoute"))
    return {"wall": wall, "signed_in": not wall,
            "reason": "form" if data.get("password") else ("route" if wall else "ok"),
            "user_box": bool(data.get("hasUserBox"))}


def wait_for_login(driver, report=None, timeout=None, log=None, grace=None):
    """Wait for the operator to sign in on the site's login screen.

    The user asked for exactly this: when the site shows a login form, wait
    (while the element exists) instead of failing the run. Returns
    ``{"ok": True}`` as soon as the form is gone, otherwise ``{"ok": False,
    "error": ...}`` after ``timeout``. Nothing is typed or submitted here: the
    profile keeps its own credentials and the human stays in control.

    A redirect that resolves by itself (measured:
    ``/Account/Login?loginToGame=…`` → ``/Account/LoginToSupplier``) is not a
    wall, so the form must persist for ``grace`` seconds before the wait (and
    its log line) even starts.
    """
    def say(message, level="info"):
        if report is not None:
            report(message, level)

    grace = _LOGIN_GRACE if grace is None else max(0.0, float(grace))
    limit = _LOGIN_WAIT if timeout is None else max(1.0, float(timeout))
    wall_since = None
    started = None
    while True:
        state = _login_page_state(driver)
        if not state.get("wall"):
            if started is not None:
                waited = time.monotonic() - started
                say("Đã đăng nhập xong sau %.0f giây; chạy tiếp." % waited)
                return {"ok": True, "waited": waited}
            return {"ok": True, "waited": 0.0}
        if wall_since is None:
            wall_since = time.monotonic()
        if (started is None and time.monotonic() - wall_since >= grace):
            started = time.monotonic()
            say("GK881 đang ở màn hình đăng nhập. Hãy đăng nhập trong cửa sổ Chrome; "
                "tool sẽ chờ tối đa %d giây rồi tự chạy tiếp." % int(limit))
        if started is not None and time.monotonic() - started >= limit:
            say("Hết thời gian chờ đăng nhập (%.0f giây)." % limit, "error")
            return {"ok": False, "error": _LOGIN_HINT,
                    "waited": time.monotonic() - started}
        time.sleep(_LOGIN_POLL)


def close_mobile_popups(driver, rounds=6, require_clear=True):
    """Đóng mọi lớp che (dialog/thông báo) cho tới khi không còn backdrop.

    GK881 mobile có thể mở nhiều dialog chồng nhau và mở lại sau khi điều hướng,
    nên một lượt là không đủ: lặp tới khi báo cáo ``backdrops == 0``. Trả về danh
    sách nhãn đã bấm để controller ghi log.
    """
    closed = []
    for _ in range(max(1, rounds)):
        try:
            result = driver.execute_script(_MOBILE_CLOSE_JS) or {}
        except Exception:
            return closed
        closed.extend(result.get("closed") or [])
        if not require_clear:
            if not result.get("closed"):
                break
            time.sleep(0.5)
            continue
        if not result.get("backdrops") and not result.get("panes"):
            break
        time.sleep(0.5)
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

    Waiting for a human to sign in is *not* charged to ``wait``: the timeout is
    the site's own budget, and a login screen has to stay open until the operator
    finishes. ``deadline`` is therefore extended whenever the flow waits for a
    sign-in, so the remaining steps still get their full allowance.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    budget = max(1.0, float(wait))
    deadline = time.monotonic() + budget
    stage = "khởi tạo"

    def report(message, level="info"):
        if log:
            try:
                log("GK881 · " + message, level)
            except Exception:
                pass

    def remain(maximum=20.0):
        return max(0.1, min(float(maximum), deadline - time.monotonic()))

    # Watched *without blocking*: a measured redirect
    # (/Account/Login?loginToGame=… → /Account/LoginToSupplier) resolves by
    # itself while the normal lobby polling is what discovers it. Blocking the
    # poll to "wait for login" would mistake that redirect for a real wall.
    watch = {"since": None, "started": None}

    def login_gate():
        """Return False only after the operator was asked for too long."""
        nonlocal deadline
        state = _login_page_state(driver)
        now = time.monotonic()
        if not state.get("wall"):
            if watch["started"] is not None:
                report("Đã đăng nhập xong; chạy tiếp.")
                deadline += now - watch["started"]
            watch["since"] = watch["started"] = None
            return True
        watch["since"] = watch["since"] or now
        if watch["started"] is None and now - watch["since"] >= _LOGIN_GRACE:
            watch["started"] = now
            report("GK881 đang ở màn hình đăng nhập. Hãy đăng nhập trong cửa sổ "
                   "Chrome; tool sẽ chờ tối đa %d giây rồi tự chạy tiếp."
                   % int(_LOGIN_WAIT))
        if (watch["started"] is not None
                and now - watch["started"] >= _LOGIN_WAIT):
            report("Hết thời gian chờ đăng nhập (%.0f giây)." % _LOGIN_WAIT, "error")
            return False
        # While the operator is signing in, the loop budget must not drain: the
        # remaining steps still need their full allowance afterwards.
        if watch["started"] is not None:
            deadline += _LOGIN_POLL
        return True

    def waiting_for_login():
        return watch["started"] is not None

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
        promoted = _promote_lobby(driver, report, wait=4.0,
                                  settle=min(30.0, remain(30.0)),
                                  prefer_handle=target_handle)
        if promoted.get("ok"):
            refreshed = DG.lobby_tables(driver, wait=min(20.0, remain(20.0)))
            if refreshed.get("ok") or not initial.get("tables"):
                initial = refreshed
        report("Sảnh DG sẵn sàng; tìm thấy %s bàn." % len(initial.get("tables", [])))
        return {"ok": True, "already_open": True, "site_id": "gk881",
                "lobby_ready": True, "tables": initial.get("tables", []),
                "promoted": bool(promoted.get("ok")),
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
                promoted = _promote_lobby(driver, report, wait=min(6.0, remain(6.0)),
                                          settle=min(30.0, remain(30.0)),
                                          prefer_handle=existing_handle)
                tables = ready.get("tables", [])
                if promoted.get("ok"):
                    refreshed = DG.lobby_tables(driver, wait=min(20.0, remain(20.0)))
                    if refreshed.get("ok"):
                        tables = refreshed.get("tables") or tables
                report("Sảnh DG đã tải; tìm thấy %s bàn." % len(tables))
                return {"ok": True, "already_open": True, "site_id": "gk881",
                        "lobby_ready": True, "tables": tables,
                        "promoted": bool(promoted.get("ok")),
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

            def clear_mobile_layers():
                """Đóng mọi lớp che; trả về số nhãn vừa bấm."""
                try:
                    hits = close_mobile_popups(driver, rounds=4)
                except Exception:
                    return 0
                if hits:
                    report("Đã đóng %s lớp che trên mobile." % len(hits))
                return len(hits)

            clear_mobile_layers()
            state = driver.execute_script(_MOBILE_STATE_JS) or {}
            if state.get("isHub") and not state.get("categories"):
                report("Trang hiện tại là trang tổng hợp link, không có menu Casino.", "error")
                return {"ok": False, "site_id": "gk881",
                        "error": "GK881 mobile đang ở trang tổng hợp link; hãy mở link casino chính thức rồi chạy lại."}
            # A signed-out profile is parked on the login form before it can even
            # show the category strip. The gate below runs inside every polling
            # loop instead of blocking one, so a redirect that resolves by itself
            # is never mistaken for a real login wall.
            # Open the Casino category, then wait for the DG provider card.
            nav = driver.execute_script(_MOBILE_CATEGORY_JS, "casino") or {}
            if nav.get("ok"):
                report("Đã chọn danh mục Casino trên mobile (%s)." % (nav.get("via") or "menu"))
                time.sleep(2)
                clear_mobile_layers()
            else:
                report("Không thấy danh mục Casino; thử tìm thẻ DreamGaming trực tiếp.",
                       "warning")
            # Tap the DreamGaming provider card when it appears. The site reopens
            # its announcement/news dialogs after a category switch, and their
            # backdrop swallows the card tap (the click then lands on the
            # backdrop and the site bounces to /Maintenance or /Account/Login),
            # so the layers are cleared again on every pass before tapping.
            dg_deadline = min(deadline, time.monotonic() + remain(45.0))
            tapped = {}
            while time.monotonic() < dg_deadline:
                # A login form may appear here when the site re-checks the session
                # on the card tap. Keep polling and let the operator sign in.
                before_gate = time.monotonic()
                if not login_gate():
                    return {"ok": False, "site_id": "gk881", "error": _LOGIN_HINT}
                if waiting_for_login() or time.monotonic() - before_gate > 1.5:
                    dg_deadline += max(1.0, time.monotonic() - before_gate)
                clear_mobile_layers()
                tapped = driver.execute_script(_MOBILE_DG_CARD_JS) or {}
                if tapped.get("ok"):
                    report("Đã chạm thẻ DreamGaming trên mobile.")
                    break
                time.sleep(1.0)
            if not tapped.get("ok"):
                report("Chưa thấy thẻ DreamGaming trên mobile.", "error")
                details = tapped.get("labels") or []
                return {"ok": False, "site_id": "gk881",
                        "error": "GK881 mobile chưa hiển thị thẻ DreamGaming sau khi chọn Casino."
                                 + (" Thẻ đang thấy: %s." % ", ".join(details[:6])
                                    if details else "")}
            # Wait for the DG lobby to mount. Announcement dialogs can reappear on
            # the hand-off page as well, so keep clearing them while polling. A
            # login form that shows up here also waits for the operator.
            lobby = {}
            poll = min(deadline, time.monotonic() + remain(75.0))
            while time.monotonic() < poll:
                before_gate = time.monotonic()
                if not login_gate():
                    return {"ok": False, "site_id": "gk881", "error": _LOGIN_HINT}
                if waiting_for_login() or time.monotonic() - before_gate > 1.5:
                    poll += max(1.0, time.monotonic() - before_gate)
                clear_mobile_layers()
                lobby = DG.lobby_tables(driver, wait=2.0)
                if lobby.get("ok"):
                    break
                time.sleep(1.0)
            if not lobby.get("ok"):
                error = lobby.get("error") or "Sảnh DG chưa tải xong."
                if watch["started"] is not None:
                    # Still on the login form at the end: name the real cause.
                    return {"ok": False, "site_id": "gk881", "error": _LOGIN_HINT}
                report("Sảnh DG mobile chưa sẵn sàng: %s" % error, "error")
                return {"ok": False, "site_id": "gk881", "error": error}
            tables = lobby.get("tables") or []
            # The lobby is still inside the site page here. Load the DG document
            # as the tab URL so the site DOM is gone and the table can be synced
            # through the DG loader (same table for every profile).
            promoted = _promote_lobby(driver, report, wait=min(6.0, remain(6.0)),
                                      settle=min(30.0, remain(30.0)),
                                      prefer_handle=source_handle)
            if promoted.get("ok"):
                refreshed = DG.lobby_tables(driver, wait=min(20.0, remain(20.0)))
                if refreshed.get("ok"):
                    tables = refreshed.get("tables") or tables
                else:
                    report("Sảnh DG trên tab chính chưa đọc được bàn: %s"
                           % (refreshed.get("error") or "chưa rõ"), "warning")
            target_handle = DG._dg_window(driver) or DG._lobby_handle(driver)
            if target_handle:
                _activate_lobby_tab(driver, target_handle)
            report("Sảnh DG mobile sẵn sàng; tìm thấy %s bàn." % len(tables))
            return {"ok": True, "site_id": "gk881", "already_open": False,
                    "lobby_ready": True, "tables": tables, "layout": "mobile",
                    "promoted": bool(promoted.get("ok")),
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
                promoted = _promote_lobby(driver, report, wait=min(6.0, remain(6.0)),
                                          settle=min(30.0, remain(30.0)),
                                          prefer_handle=target_handle)
                tables = ready.get("tables", [])
                if promoted.get("ok"):
                    refreshed = DG.lobby_tables(driver, wait=min(20.0, remain(20.0)))
                    if refreshed.get("ok"):
                        tables = refreshed.get("tables") or tables
                report("Sảnh DG đã sẵn sàng; tìm thấy %s bàn." % len(tables))
                return {"ok": True, "already_open": True, "site_id": "gk881",
                        "lobby_ready": True, "tables": tables,
                        "promoted": bool(promoted.get("ok")),
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
        promoted = _promote_lobby(driver, report, wait=min(6.0, remain(6.0)),
                                  settle=min(30.0, remain(30.0)),
                                  prefer_handle=target_handle)
        tables = ready.get("tables", [])
        if promoted.get("ok"):
            refreshed = DG.lobby_tables(driver, wait=min(20.0, remain(20.0)))
            if refreshed.get("ok"):
                tables = refreshed.get("tables") or tables
        report("Sảnh DG đã sẵn sàng; tìm thấy %s bàn." % len(tables))
        return {"ok": True, "site_id": "gk881", "already_open": False,
                "lobby_ready": True, "tables": tables,
                "promoted": bool(promoted.get("ok")),
                "note": "Đã mở sảnh DG từ GK881 và chuyển tab DG thành tab đang dùng."}
    except Exception as exc:
        report("Dừng tại bước '%s' (%s)." % (stage, type(exc).__name__), "error")
        return {"ok": False, "site_id": "gk881",
                "error": "GK881 chưa hoàn tất bước '%s' (%s)." % (stage, type(exc).__name__)}
