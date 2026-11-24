"""888AE66-specific navigation into its Dream Gaming lobby.

Live site flow (measured on ``https://www.888ae66.com/m`` and
``/gamelobby/live`` with a phone user-agent):

1. The mobile home is a Vue app with a left navigation. ``SÒNG BÀI`` is
   ``.nav-item.live`` and routes the SPA to ``/gamelobby/live``.
2. That page lists providers as ``li`` cards, each holding an ``img`` whose
   ``alt`` is the provider name. Dream Gaming is ``img[alt=banner-dg]``.
3. Tapping that card does **not** open an in-page iframe: Chrome opens a new
   tab on ``/launchgame`` which immediately becomes the DG document
   (``ddnewpc/index.html?...&token=…``). The site tab stays behind, so a profile
   ends up with **two** tabs.
4. Dream Gaming may gate the lobby with a slider captcha ("Xác minh an toàn" /
   "Kéo thanh trượt sang phải"). It appears *while* the lobby loads and is
   drawn with Laya nodes, so it is invisible to DOM queries. The operator solves
   it by hand; the adapter only detects it, reports it loudly and waits.
5. Tables are loaded with ``ddnewpc/direct1.html?tableId=<id>`` — the same
   desktop loader the shared helpers already use.

The one-tab rule the user asked for ("đóng tab site đi để chỉ còn duy nhất 1 tab
sảnh") is enforced by keeping the DG tab and closing the site tabs: the DG tab
already holds the live session, so closing the site tab neither reloads the
lobby nor drops the token. Measured on 888AE66: after closing the site tab the
remaining tab kept its whole Laya stage (7979 nodes) and its ``token``.

Table scanning, sync and bet state reuse the shared helpers in
``aibcr.adapters.febet``.
"""

import time
from urllib.parse import urlsplit

from aibcr.adapters import febet as DG

SITE_HOST = "888ae66.com"

# The home route of the mobile build; a sub-page such as ``/m/gameRecord`` has no
# navigation menu, so the flow returns here first.
_MOBILE_HOME = "/m"

# NOTE: Selenium's ``execute_script`` only returns a value when the script has
# an explicit ``return``. Wrapping the body in an IIFE without ``return`` makes
# every call evaluate to ``None`` — a silent failure that looks like "the card
# is not on the page". Measured site shape, then kept in the ``return`` form the
# other adapters use.
_LIVE_ROUTE_JS = r"""
const vis = (node) => {
  try {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 8 && rect.height > 8
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.05;
  } catch (error) { return false; }
};
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
// Signed-out profiles show "Đăng nhập" in the header; the operator signs in by
// hand before the lobby can be reached.
const loginBtn = [...document.querySelectorAll(
  'button.header-btn.login, .header-btn.login')].find(vis) || null;
// "SÒNG BÀI" is the live-casino entry of the left navigation.
const liveNav = [...document.querySelectorAll('.nav-item.live, [class*=nav-item]')]
  .find((node) => vis(node) && /^s[oò]ng\s*b[aà]i$/i.test(norm(node.textContent)))
  || null;
// The Dream Gaming card is the <img> whose alt is exactly banner-dg. Measured:
// the wrapping <li> carries an unrelated class (``vi-VN``), so matching the
// banner image is the only stable rule.
const dgImg = [...document.querySelectorAll('img')].find((img) =>
  vis(img) && /^banner-dg$/i.test(norm(img.getAttribute('alt')))) || null;
const center = (node) => {
  const rect = node.getBoundingClientRect();
  return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
          w: Math.round(rect.width), h: Math.round(rect.height)};
};
return {
  path: location.pathname,
  hasLogin: !!loginBtn,
  live: liveNav ? center(liveNav) : null,
  dg: dgImg ? Object.assign(center(dgImg),
    {alt: norm(dgImg.getAttribute('alt'))}) : null,
};
"""


def _safe_location(driver):
    """Return only host/path; the DG URL carries a session token."""
    try:
        parsed = urlsplit(driver.current_url or "")
        return (parsed.hostname or "unknown") + (parsed.path or "/")
    except Exception:
        return "unknown"


def login_state(driver):
    """``{"needs_login": bool}`` — read from the header button, never the form."""
    try:
        data = driver.execute_script(_LIVE_ROUTE_JS) or {}
    except Exception:
        return {"needs_login": False, "path": ""}
    return {"needs_login": bool(data.get("hasLogin")), "path": data.get("path") or ""}


def wait_for_login(driver, report=None, timeout=300.0, poll=1.5, grace=8.0):
    """Wait for the operator to sign in on 888AE66; nothing is typed here.

    A redirect that resolves by itself must not be mistaken for a wall, so the
    button has to stay visible for ``grace`` seconds before the wait starts (and
    before the log line appears).
    """
    def say(message, level="info"):
        if report is not None:
            try:
                report(message, level)
            except Exception:
                pass

    limit = max(1.0, float(timeout))
    since = None
    started = None
    while True:
        state = login_state(driver)
        if not state.get("needs_login"):
            if started is not None:
                say("Đã đăng nhập xong sau %.0f giây; chạy tiếp."
                    % (time.monotonic() - started))
                return {"ok": True, "waited": time.monotonic() - started}
            return {"ok": True, "waited": 0.0}
        if since is None:
            since = time.monotonic()
        if started is None and time.monotonic() - since >= max(0.0, float(grace)):
            started = time.monotonic()
            say("888AE66 đang hiện nút Đăng nhập. Hãy đăng nhập trong cửa sổ "
                "Chrome của profile này; tool sẽ chờ tối đa %d giây rồi tự chạy "
                "tiếp." % int(limit), "action")
        if started is not None and time.monotonic() - started >= limit:
            say("Hết thời gian chờ đăng nhập (%.0f giây)." % limit, "error")
            return {"ok": False, "waited": time.monotonic() - started,
                    "error": "888AE66 vẫn đang ở màn hình đăng nhập; hãy đăng nhập "
                             "trong cửa sổ Chrome rồi chạy lại."}
        time.sleep(max(0.2, float(poll)))


def _dg_tab_handle(driver, prefer=None):
    """Handle of the tab whose **URL** is the DG document (not an iframe).

    ``prefer`` is honoured when that handle is itself a DG tab — the caller
    already reads the lobby there, so a second DG tab must never win the vote.
    """
    if prefer is not None:
        try:
            driver.switch_to.window(prefer)
            driver.switch_to.default_content()
            if "ddnew" in (driver.current_url or "").lower():
                return prefer
        except Exception:
            pass
    try:
        handles = list(driver.window_handles)
    except Exception:
        return None
    for handle in reversed(handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            if "ddnew" in (driver.current_url or "").lower():
                return handle
        except Exception:
            continue
    return None


def _is_dg_candidate(url):
    """True for a DG tab **or** the site's ``/launchgame`` redirect to it.

    Measured on 888AE66: tapping the card opens ``/launchgame`` on the site host
    and that tab only becomes ``ddnewpc/index.html`` a moment later. Closing it
    as "a site tab" would kill the lobby before it loads, so a tab parked on
    ``/launchgame`` is never treated as disposable.
    """
    low = (url or "").lower()
    return "ddnew" in low or "/launchgame" in low


def _site_tabs(driver):
    """Handles of tabs that belong to the 888AE66 site (not the DG document)."""
    out = []
    try:
        handles = list(driver.window_handles)
    except Exception:
        return out
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            url = driver.current_url or ""
        except Exception:
            continue
        if _is_dg_candidate(url):
            continue
        out.append(handle)
    return out


def close_site_tabs(driver, report=None, keep_only_dg=False, prefer=None):
    """Close every site tab, keeping the DG tab: the profile ends with 1 tab.

    Order matters — the DG tab is located and selected **before** anything is
    closed, so the WebDriver session never points at a destroyed window.

    ``keep_only_dg`` drops the "don't touch ``/launchgame``" protection. It is
    only safe once the DG tab is **already drawing** (Laya stage loaded):
    before that, the ``/launchgame`` tab *is* the lobby being built and closing
    it kills the session. After the lobby is up, that redirect tab is a leftover
    and the user asked for exactly one tab.

    ``prefer`` is the DG handle the caller already read the lobby from, so the
    kept tab is that one — never a second DG tab that happens to exist.
    """
    def say(message, level="info"):
        if report is not None:
            try:
                report(message, level)
            except Exception:
                pass

    dg_handle = _dg_tab_handle(driver, prefer=prefer)
    if dg_handle is None:
        return {"ok": False, "closed": 0,
                "error": "Chưa thấy tab sảnh DG để giữ lại."}
    closable = [handle for handle in _site_tabs(driver) if handle != dg_handle]
    if keep_only_dg:
        try:
            every = list(driver.window_handles)
        except Exception:
            every = []
        closable = [handle for handle in every if handle != dg_handle]
    closed = 0
    for handle in closable:
        if handle == dg_handle:
            continue
        try:
            driver.switch_to.window(handle)
            driver.close()
            closed += 1
        except Exception:
            continue
    try:
        driver.switch_to.window(dg_handle)
        driver.switch_to.default_content()
    except Exception:
        return {"ok": False, "closed": closed,
                "error": "Đã đóng tab site nhưng không quay lại được tab sảnh DG."}
    remaining = len(driver.window_handles)
    if closed:
        say("Đã đóng %d tab site; chỉ còn tab sảnh DG." % closed)
    return {"ok": remaining == 1, "closed": closed, "tabs": remaining}


def _site_source_handle(driver):
    """The 888AE66 tab to drive — never the DG document.

    The DG URL carries ``backUrl=…888ae66.com…``/``return=`` in its query, so a
    plain substring test picks the game tab and the site's navigation script
    then runs on the lobby. DG candidates are skipped explicitly, and ``None``
    is returned when no site tab is left: driving the lobby with the site's
    navigation script would be worse than reporting "no tab".
    """
    try:
        handles = list(driver.window_handles)
    except Exception:
        return None
    for handle in reversed(handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            url = driver.current_url or ""
        except Exception:
            continue
        if _is_dg_candidate(url):
            continue
        if SITE_HOST in url.lower():
            return handle
    candidates = _site_tabs(driver)
    if candidates:
        return candidates[0]
    return None


def open_dg(driver, wait=180.0, log=None):
    """Open 888AE66's DG lobby and leave exactly one tab: the DG lobby itself."""
    budget = max(1.0, float(wait))
    deadline = time.monotonic() + budget
    stage = "khởi tạo"

    def report(message, level="info"):
        if log:
            try:
                log("888AE66 · " + message, level)
            except Exception:
                pass

    def remain(maximum=30.0):
        return max(0.1, min(float(maximum), deadline - time.monotonic()))

    if driver is None:
        return {"ok": False, "site_id": "888ae66",
                "error": "Chưa mở Chrome cho profile này."}

    report("Bắt đầu; trang hiện tại: %s." % _safe_location(driver))

    # ---- A DG document already open: reuse it, only drop the site tabs. ----
    stage = "kiểm tra sảnh DG đang mở"
    try:
        already = DG._dg_context(driver, wait=1.0)
    except Exception:
        already = None
    if already is not None:
        # The lobby may be sitting behind the slider captcha; announce it and
        # wait for the operator instead of reporting "no tables" and opening a
        # second DG tab on top of the live session.
        gate = DG.wait_for_captcha(driver, report,
                                   timeout=min(300.0, max(30.0, remain(300.0))))
        if not gate.get("ok"):
            return {"ok": False, "site_id": "888ae66", "stage": stage,
                    "captcha": True, "error": gate.get("error")}
        existing = DG.lobby_tables(driver, wait=min(60.0, max(3.0, remain(60.0))),
                                   log=report)
        if existing.get("ok"):
            report("Sảnh DG đã mở sẵn; tìm thấy %s bàn."
                   % len(existing.get("tables") or []))
            in_table = bool(existing.get("in_table"))
            if in_table:
                report("Profile đang trong bàn DG; giữ nguyên tab để không rời bàn.")
            # ``lobby_tables`` succeeded, so the DG tab is drawing: any other tab
            # (site or a leftover ``/launchgame`` redirect) is disposable and the
            # user wants exactly one.
            tidy = close_site_tabs(driver, report, keep_only_dg=True)
            if not tidy.get("ok") and tidy.get("error"):
                report(tidy["error"], "warning")
            host = ""
            try:
                host = urlsplit(driver.current_url or "").hostname or ""
            except Exception:
                host = ""
            return {"ok": True, "site_id": "888ae66", "already_open": True,
                    "lobby_ready": True, "tables": existing.get("tables") or [],
                    "in_table": in_table, "tabs": tidy.get("tabs"),
                    "host": host,
                    "note": "Đã nhận diện sảnh DG 888AE66 đang mở."}
        report("Sảnh DG đang mở nhưng chưa đọc được bàn (%s); thử lại từ site."
               % (existing.get("error") or "không rõ"), "warning")
        # Never open a second DG tab on top of a live lobby. If the DG document
        # is there but its grid is not readable, say so instead of walking back
        # through the site and launching the game again.
        if _dg_tab_handle(driver) is not None:
            reason = existing.get("error") or "Laya chưa vẽ xong lưới bàn"
            report("Sảnh DG đang mở nhưng chưa đọc được bàn (%s)." % reason, "error")
            return {"ok": False, "site_id": "888ae66", "stage": stage,
                    "tabs": len(driver.window_handles), "error": reason}

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    # ---- Work on the site tab, never on the DG tab. ----
    stage = "tìm tab 888AE66"
    source_handle = _site_source_handle(driver)
    if source_handle is None:
        return {"ok": False, "site_id": "888ae66", "stage": stage,
                "error": "Không tìm được tab 888AE66 để mở sảnh DG."}
    driver.switch_to.window(source_handle)
    driver.switch_to.default_content()
    report("Đang thao tác trên %s." % _safe_location(driver))

    # ---- A login button means the operator must sign in by hand. ----
    stage = "đăng nhập nếu có"
    login = wait_for_login(driver, report, timeout=min(300.0, remain(300.0)))
    if not login.get("ok"):
        return {"ok": False, "site_id": "888ae66", "error": login.get("error")}
    deadline += float(login.get("waited") or 0)

    # ---- Home page: open the live-casino list. ----
    stage = "mở danh sách SÒNG BÀI"
    routed = False
    for _ in range(3):
        state = driver.execute_script(_LIVE_ROUTE_JS) or {}
        if state.get("dg"):
            break
        if state.get("live"):
            if DG._cdp_click(driver, state["live"]["x"], state["live"]["y"]):
                report("Đã bấm SÒNG BÀI; chờ danh sách nhà cung cấp.")
                routed = True
            break
        # A sub-page such as ``/m/gameRecord`` has no navigation menu, and a
        # blank tab (profile just opened, no URL) has no menu either: both are
        # fixed by going to the mobile home.
        here = urlsplit(driver.current_url or "")
        if here.scheme in ("http", "https") and here.netloc:
            target = "%s://%s%s" % (here.scheme, here.netloc, _MOBILE_HOME)
        else:
            target = "https://%s%s" % (SITE_HOST, _MOBILE_HOME)
        report("Trang này không có menu vào sảnh; quay về %s." % _MOBILE_HOME)
        if not DG.navigate_top(driver, target):
            break
        time.sleep(3.0)

    # ---- Provider page: tap the Dream Gaming card. ----
    stage = "chờ thẻ DreamGaming"
    tapped = False
    dg_deadline = min(deadline, time.monotonic() + remain(60.0))
    while time.monotonic() < dg_deadline:
        state = driver.execute_script(_LIVE_ROUTE_JS) or {}
        if state.get("hasLogin"):
            # The site re-checked the session while navigating.
            again = wait_for_login(driver, report, timeout=min(300.0, remain(300.0)))
            if not again.get("ok"):
                return {"ok": False, "site_id": "888ae66",
                        "error": again.get("error")}
            dg_deadline += max(1.0, float(again.get("waited") or 0))
            continue
        if state.get("dg"):
            if DG._cdp_click(driver, state["dg"]["x"], state["dg"]["y"]):
                report("Đã chạm thẻ DreamGaming; chờ tab sảnh DG mở.")
                tapped = True
            break
        if state.get("live") and not routed:
            DG._cdp_click(driver, state["live"]["x"], state["live"]["y"])
            routed = True
        time.sleep(1.0)
    if not tapped:
        report("Chưa thấy thẻ DreamGaming (banner-dg) trên 888AE66.", "error")
        return {"ok": False, "site_id": "888ae66",
                "error": "888AE66 chưa hiển thị thẻ DreamGaming; hãy vào mục "
                         "SÒNG BÀI trên cửa sổ Chrome rồi chạy lại."}

    # ---- The game opens as a real tab (no iframe on this site). ----
    stage = "chờ tab sảnh DG"
    dg_handle = None
    poll = min(deadline, time.monotonic() + remain(120.0))
    while time.monotonic() < poll:
        dg_handle = _dg_tab_handle(driver)
        if dg_handle is not None:
            break
        time.sleep(1.0)
    if dg_handle is None:
        report("Hết thời gian chờ; Dream Gaming không mở tab sảnh.", "error")
        return {"ok": False, "site_id": "888ae66",
                "error": "888AE66 đã bấm DreamGaming nhưng chưa mở được tab sảnh DG."}
    driver.switch_to.window(dg_handle)
    driver.switch_to.default_content()
    report("Đã thấy tab sảnh DG (%s)." % _safe_location(driver))

    # ---- Captcha: never solved here, only announced and awaited. ----
    stage = "chờ captcha nếu có"
    gate = DG.wait_for_captcha(driver, report,
                               timeout=min(300.0, max(30.0, remain(300.0))))
    if not gate.get("ok"):
        return {"ok": False, "site_id": "888ae66", "stage": stage,
                "error": gate.get("error")}
    deadline += float(gate.get("waited") or 0)

    # ---- Keep one tab: the DG lobby, with the site tabs closed behind it. ----
    stage = "gộp về một tab sảnh"
    tidy = close_site_tabs(driver, report, prefer=dg_handle)
    if not tidy.get("ok"):
        report(tidy.get("error") or "Chưa gộp được về một tab.", "warning")

    # ---- Read the lobby tables. ----
    # ``report`` is passed so a captcha that appears while the grid is being
    # drawn is announced and awaited instead of silently returning "no tables".
    stage = "đọc danh sách bàn"
    lobby = DG.lobby_tables(driver, wait=min(60.0, remain(60.0)), log=report)
    if not lobby.get("ok"):
        error = lobby.get("error") or "Sảnh DG chưa tải xong."
        report("Sảnh DG chưa sẵn sàng: %s" % error, "error")
        return {"ok": False, "site_id": "888ae66", "stage": stage,
                "captcha": bool(lobby.get("captcha")), "error": error}

    # ---- Second pass: drop the ``/launchgame`` tab left behind by the redirect.
    # It was protected above because the lobby was still being built inside it.
    # Now the DG tab is drawing a table grid, so it is a disposable leftover —
    # and the user asked for exactly one tab.
    if (tidy.get("tabs") or 0) > 1:
        final = close_site_tabs(driver, report, keep_only_dg=True, prefer=dg_handle)
        if final.get("ok"):
            tidy = final
        else:
            report(final.get("error") or
                   "Vẫn còn %s tab; hãy đóng tab site còn lại bằng tay."
                   % (final.get("tabs") or "?"), "warning")

    tables = lobby.get("tables") or []
    host = ""
    try:
        host = urlsplit(driver.current_url or "").hostname or ""
    except Exception:
        host = ""
    report("Sảnh DG sẵn sàng; tìm thấy %s bàn, %s tab."
           % (len(tables), tidy.get("tabs") or "?"))
    return {"ok": True, "site_id": "888ae66", "already_open": False,
            "lobby_ready": True, "tables": tables, "tabs": tidy.get("tabs"),
            "host": host, "promoted": True,
            "note": "Đã mở sảnh DG từ 888AE66 và gộp về một tab sảnh duy nhất."}
