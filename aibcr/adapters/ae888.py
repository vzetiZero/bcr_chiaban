"""888AE66-specific navigation into its Dream Gaming lobby.

Live site flow, re-measured on 25/11/2026 in Chrome profile 1
(``https://www.888ae66.com/m``, mobile fingerprint):

1. The mobile home is a Vue SPA. ``SÒNG BÀI`` is
   ``.swiper-slide.nav-anchor.home-quick-item.navigation-PRODUCT`` (measured at
   x≈249, y≈604 on an 880×1103 viewport) and routes the SPA to
   ``/gamelobby/live``. The older ``.nav-item.live`` markup is kept for other
   builds.
2. ``/gamelobby/live`` opens with a promo modal (``.nrc-modal.fade-in``)
   covering the page. Its close button is a ``div.iconClose`` at the modal's
   top-right corner. **Nothing on the page is clickable until it is closed**, so
   closing popups is a real step of the flow, not a nicety.
3. The Dream Gaming card is ``div.game-item.DG.customized`` wrapping
   ``img[src*=live-dg]`` — measured: that image has **no** ``alt`` attribute, so
   the old ``img[alt=banner-dg]`` rule matched nothing and the run sat in the
   lobby forever. The class token ``DG`` and the ``live-dg`` file name are the
   two stable handles; ``banner-dg`` is still accepted for other builds.
4. Tapping the card does **not** create a DG tab: the tab itself moves to
   ``/launchgame``, and the lobby runs as a **cross-process iframe**
   (``ddnewwap/index.html`` on ``new-dd-cloudfront.ywjxi.com``). WebDriver cannot
   enter an out-of-process frame, so the only way to drive the lobby is to read
   the real document URL from CDP and navigate the tab to it.
5. After that promotion Dream Gaming gates the lobby with a slider captcha whose
   text is **English**: Laya nodes named ``sliderBtn``/``System`` hold
   ``"SafetyVerify"`` and ``"Drag the slider"``. ``document.body.innerText`` is
   empty and no ``[class*=captcha]`` exists, so only a Laya walk sees it. The
   tool never solves it: it rings the siren and waits for the operator.
6. Tables then load through the phone loader ``ddnewwap/index.html?tableId=<id>``.

The one-tab rule the user asked for ("đóng tab site đi để chỉ còn duy nhất 1 tab
sảnh") is enforced by keeping the DG tab and closing the site tabs. Measured
earlier on 888AE66: after closing the site tab the remaining tab kept its whole
Laya stage and its ``token``.

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
const box = (node) => {
  const rect = node.getBoundingClientRect();
  return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
          w: Math.round(rect.width), h: Math.round(rect.height),
          top: Math.round(rect.top), left: Math.round(rect.left)};
};
// Selenium/CDP bấm theo toạ độ **viewport**. Đo trên ``/gamelobby/live``: thẻ DG
// nằm ở ``y≈2406`` trong khi viewport cao 1103px, nên bấm thẳng vào toạ độ đó
// không trúng gì. Cuộn thẻ vào giữa màn hình rồi mới đọc lại hình chữ nhật.
const bring = (node) => {
  if (!node) return null;
  try { node.scrollIntoView({block: 'center', inline: 'center'}); } catch (error) {}
  return box(node);
};
// Signed-out profiles show "Đăng nhập" in the header; the operator signs in by
// hand before the lobby can be reached.
const loginBtn = [...document.querySelectorAll(
  'button.header-btn.login, .header-btn.login')].find(vis) || null;
// "SÒNG BÀI" is the live-casino entry. The signed-in mobile home uses a Swiper
// quick-nav, not ``.nav-item.live``: measured on the real profile the item is
// ``.swiper-slide.nav-anchor.home-quick-item.navigation-PRODUCT`` and fully
// visible. Keep the older selector for other site builds.
const liveNav = [...document.querySelectorAll(
  '.nav-item.live, [class*=nav-item], .home-quick-item, .nav-anchor, [class*=navigation]')]
  .find((node) => vis(node) && /^s[oò]ng\s*b[aà]i$/i.test(norm(node.textContent)))
  || null;
// A promo modal covers ``/gamelobby/live`` and swallows every click until it is
// dismissed. Only a real close control counts: the measured one is
// ``div.iconClose`` inside ``.nrc-modal``; several other nodes carry
// "close" in their class but are off-screen or 12px icon dots.
const OVERLAY_SEL = '[class*=modal],[class*=popup],[class*=dialog],[class*=mask],'
  + '[class*=overlay],[class*=nrc-]';
const CLOSE_SEL = 'img[alt=modal-close-button],.iconClose,[class*=iconClose],'
  + '[class*=close-button],[class*=closeBtn],[class*=close-btn]';
const overlays = [...document.querySelectorAll(OVERLAY_SEL)].filter(vis);
// A close control only counts when a real hit-test lands on it: ``/gamelobby/live``
// also ships an off-screen ``div.close-button`` parked at (0,0) and 12px icon dots
// (``i.mps-close``). Blind-clicking those navigates away from the page.
const isCloseControl = (node) => {
  if (!node || !vis(node)) return false;
  const rect = node.getBoundingClientRect();
  if (rect.width < 16 || rect.height < 16) return false;
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
  const hit = document.elementFromPoint(x, y);
  return !!hit && (hit === node || node.contains(hit));
};
const closers = [];
for (const layer of overlays) {
  const found = [...layer.querySelectorAll(CLOSE_SEL)].filter(isCloseControl);
  if (found.length) closers.push(found[0]);
}
if (!closers.length) {
  // Some builds draw the button as a sibling of the dialog body.
  for (const node of document.querySelectorAll(CLOSE_SEL)) {
    if (isCloseControl(node)) closers.push(node);
  }
}
// The Dream Gaming card. Measured markup: ``div.game-item.DG.customized`` with
// an ``img`` whose src ends in ``live-dg.png`` and whose ``alt`` is EMPTY. Keep
// ``banner-dg`` for other builds, but the DG class token and the file name are
// what actually matched.
const cards = [...document.querySelectorAll(
  '.game-item, [class*=game-item], img[src*=live-dg], img[alt=banner-dg]')];
const isDg = (node) => {
  const alt = norm(node.getAttribute && node.getAttribute('alt'));
  const src = String((node.getAttribute && node.getAttribute('src')) || '');
  const cls = String(node.className || '');
  return /^banner-dg$/i.test(alt) || /live-dg/i.test(src)
    || /(^|\s)DG(\s|$)/.test(cls)
    || !!node.querySelector('img[src*=live-dg], img[alt=banner-dg]');
};
let dgNode = cards.find((node) => vis(node) && isDg(node)) || null;
if (dgNode && dgNode.tagName === 'IMG') {
  dgNode = dgNode.closest('.game-item') || dgNode.parentElement || dgNode;
}
return {
  path: location.pathname,
  hasLogin: !!loginBtn,
  live: liveNav ? box(liveNav) : null,
  dg: dgNode ? Object.assign(bring(dgNode), {
    cls: String(dgNode.className || '').slice(0, 60)}) : null,
  overlays: overlays.map((node) => String(node.className || '').slice(0, 60)),
  closers: closers.map((node) => Object.assign(box(node), {
    sel: node.tagName + '.' + String(node.className || '').slice(0, 40),
    alt: norm(node.getAttribute('alt'))})),
  scrollY: Math.round(window.scrollY || 0),
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


def page_state(driver):
    """One read of the measured page shape, or ``{}`` when the read fails."""
    try:
        return driver.execute_script(_LIVE_ROUTE_JS) or {}
    except Exception:
        return {}


def close_popups(driver, report=None, rounds=3):
    """Dismiss every visible promo modal by its **own** close button.

    Measured on ``/gamelobby/live``: a ``.nrc-modal`` covers the page and only
    ``div.iconClose`` at its top-right corner closes it; while it is up, taps on
    the DG card land on the modal and nothing happens. Only a visible close
    control inside a visible overlay (or a bare visible close control) is used —
    no "click the backdrop" guesswork, because that navigates away on this site.

    Returns ``{"closed": int, "left": int}``: how many controls were tapped and
    how many overlays are still visible afterwards.
    """
    def say(message, level="info"):
        if report is not None:
            try:
                report(message, level)
            except Exception:
                pass

    closed = 0
    left = 0
    for _ in range(max(1, int(rounds))):
        state = page_state(driver)
        closers = state.get("closers") or []
        overlays = state.get("overlays") or []
        left = len(overlays)
        if not closers:
            break
        target = closers[0]
        name = target.get("sel") or target.get("alt") or "nút đóng"
        if not DG._cdp_click(driver, target.get("x"), target.get("y")):
            say("Thấy nút đóng popup (%s) nhưng không bấm được." % name, "warning")
            break
        closed += 1
        say("Đã đóng popup %s." % name)
        time.sleep(0.8)
        left = len(page_state(driver).get("overlays") or [])
        if not left:
            break
    if left:
        say("Vẫn còn %d lớp popup trên trang." % left, "warning")
    return {"closed": closed, "left": left}


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

    # ---- Promo popups: close them before touching anything else. ----
    # Measured on ``/gamelobby/live``: a ``.nrc-modal`` covers the whole viewport
    # and every tap on the DG card lands on the modal, so the flow stalls with no
    # visible error. The user asked for this explicitly ("nếu có popup nào hiện
    # lên đóng hoàn toàn cho tôi").
    stage = "đóng popup"
    popup = close_popups(driver, report)

    # ---- Home page: open the live-casino list. ----
    stage = "mở danh sách SÒNG BÀI"
    routed = False
    for _ in range(3):
        state = page_state(driver)
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
        close_popups(driver, report)

    # ---- Provider page: tap the Dream Gaming card. ----
    stage = "chờ thẻ DreamGaming"
    tapped = False
    dg_deadline = min(deadline, time.monotonic() + remain(60.0))
    while time.monotonic() < dg_deadline:
        state = page_state(driver)
        if state.get("hasLogin"):
            # The site re-checked the session while navigating.
            again = wait_for_login(driver, report, timeout=min(300.0, remain(300.0)))
            if not again.get("ok"):
                return {"ok": False, "site_id": "888ae66",
                        "error": again.get("error")}
            dg_deadline += max(1.0, float(again.get("waited") or 0))
            continue
        if state.get("dg"):
            if state.get("closers"):
                # A popup re-opened (carousel autoresize) and would eat the tap.
                close_popups(driver, report, rounds=1)
                continue
            card = state["dg"]
            if DG._cdp_click(driver, card["x"], card["y"]):
                report("Đã chạm thẻ DreamGaming (%s) tại %s,%s; chờ sảnh DG mở."
                       % (card.get("cls") or "game-item", int(card["x"]),
                          int(card["y"])))
                tapped = True
            break
        if state.get("live") and not routed:
            DG._cdp_click(driver, state["live"]["x"], state["live"]["y"])
            routed = True
        time.sleep(1.0)
    if not tapped:
        left = len(page_state(driver).get("closers") or [])
        if left:
            return {"ok": False, "site_id": "888ae66", "stage": "đóng popup",
                    "error": "888AE66 vẫn còn %d popup che trang; không bấm được thẻ "
                             "DreamGaming." % left}
        report("Chưa thấy thẻ DreamGaming trên 888AE66 (trang %s)."
               % _safe_location(driver), "error")
        return {"ok": False, "site_id": "888ae66",
                "error": "888AE66 chưa hiển thị thẻ DreamGaming; hãy vào mục "
                         "SÒNG BÀI trên cửa sổ Chrome rồi chạy lại."}

    # ---- Dream Gaming loads as a cross-process iframe, not a new tab.
    # Measured: tapping the card moves **this** tab to ``/launchgame`` and the
    # lobby runs as an OOPIF ``ddnewwap/index.html`` on another host. WebDriver
    # cannot enter that frame, so wait for the CDP target and navigate the tab
    # to the real document URL. A separate "ddnew" tab may still appear on other
    # builds, and is handled by the same wait below.
    stage = "chờ sảnh DG tải"
    dg_handle = None
    promoted = False
    poll = min(deadline, time.monotonic() + remain(150.0))
    while time.monotonic() < poll:
        dg_handle = _dg_tab_handle(driver)
        if dg_handle is not None:
            promoted = True
            report("Đã thấy tab sảnh DG (%s)." % _safe_location(driver))
            break
        try:
            found = DG.find_game_frame(driver, wait=0)
        except Exception:
            found = None
        if found:
            report("Thấy khung DG (%s); đưa lên tab chính để điều khiển được."
                   % ("ddnewwap" if "wap" in str(found.get("url") or "")
                      else "ddnewpc"))
            moved = DG.promote_frame_to_tab(driver, found,
                                            settle=min(45.0, max(6.0, remain(45.0))))
            if moved.get("ok"):
                promoted = True
                report("Sảnh DG đã chạy trên tab chính (%s)." % _safe_location(driver))
                break
            report("Chưa đưa được khung DG lên tab chính (%s); thử lại."
                   % (moved.get("error") or "không rõ"), "warning")
        time.sleep(1.5)
    if not promoted:
        report("Hết thời gian chờ; Dream Gaming không mở sảnh.", "error")
        return {"ok": False, "site_id": "888ae66", "stage": stage,
                "error": "888AE66 đã bấm DreamGaming nhưng chưa mở được sảnh DG."}
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

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
