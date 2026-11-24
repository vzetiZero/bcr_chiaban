"""Shared Dream Gaming entry, table selection and betting for casino profiles."""

import json
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

from aibcr.adapters import dg_pages


LOBBY_URL = "https://febet.kiwi/live-casino/baccarat"
MAX_FRAMES = 48
MAX_DEPTH = 5
MAX_OPTIONS = 120
_SENSITIVE_LABEL = re.compile(r"token|jwt|session|password|username|authorization|cookie", re.I)
# Iframe tiện ích của site (chat, captcha, analytics) không phải iframe game DG.
# Không loại chúng thì inspect báo "đã mở game" oan và openDG bỏ qua bước bấm ảnh DG.
_WIDGET_ORIGIN = re.compile(
    r"(^|\.)(livechatinc\.com|livechat\.com|google\.com|gstatic\.com|googleapis\.com"
    r"|recaptcha\.net|doubleclick\.net|facebook\.net|facebook\.com|zendesk\.com"
    r"|tawk\.to|crisp\.chat|hotjar\.com|intercom\.io|clarity\.ms|cloudflare\.com)$", re.I)


def _is_widget_origin(origin):
    try:
        host = urlsplit(origin or "").hostname or ""
    except ValueError:
        return True
    return not host or bool(_WIDGET_ORIGIN.search(host))


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
        host = (parsed.hostname or "").lower()
        is_febet_host = host == "febet.kiwi" or host.endswith(".febet.kiwi")
        return (parsed.scheme == "https" and is_febet_host
                and parsed.path.rstrip("/").endswith("/live-casino/baccarat")
                and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return False


def _febet_lobby_handle(driver):
    """Find the FEBET Baccarat page before its DG iframe has been launched."""
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            if _is_lobby(driver.current_url):
                return handle
        except Exception:
            continue
    return None


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
        game_tab = False
        for handle in reversed(handles):
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
                url = driver.current_url or ""
                if "ddnewpc" in url:
                    game_tab = True
                if target is None and _is_lobby(url):
                    target = handle
            except Exception:
                continue
        if target is None:
            return {"ok": False, "error": "Profile cần mở sảnh FEBET Baccarat trước."}
        driver.switch_to.window(target)
        driver.switch_to.default_content()

        frames = []
        labels_by_path = {}
        for path, info in _frame_contexts(driver):
            if not path:
                continue
            origin = _public_origin(info.get("url", ""))
            title = re.sub(r"\s+", " ", str(info.get("title") or "")).strip()[:100]
            frames.append({"path": list(path), "origin": origin, "title": title,
                           "has_content": bool(info.get("labels"))})
            labels_by_path[tuple(path)] = (origin, info.get("labels", []))
        driver.switch_to.window(target)
        driver.switch_to.default_content()
        # Iframe DG vẽ sảnh bằng canvas nên có thể không có nhãn DOM nào;
        # chỉ cần origin lạ (không phải site/widget) là dấu hiệu game đã mở.
        game_frames = [frame for frame in frames
                       if frame["origin"] and frame["origin"] != "https://febet.kiwi"
                       and not _is_widget_origin(frame["origin"])]
        game_paths = {tuple(frame["path"]) for frame in game_frames}
        option_map = {}
        for path, (origin, labels) in labels_by_path.items():
            if path not in game_paths:
                continue
            for item in labels:
                label = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
                normalized = label.upper()
                if (not label or len(label) > 80 or _SENSITIVE_LABEL.search(label)
                        or normalized == "XEM GAME"):
                    continue
                option_map[(path, label)] = {"path": list(path), "label": label, "origin": origin}
                if len(option_map) >= MAX_OPTIONS:
                    break
        options = list(option_map.values())
        if game_tab and not game_frames:
            note = "Game DG đã mở ở tab riêng của profile."
        elif game_frames and not options:
            note = "Game DG đã mở nhưng sảnh vẽ bằng canvas, không có nhãn bàn DOM."
        elif game_frames:
            note = "Đã quét iframe của game FEBET."
        else:
            note = "Chưa thấy iframe game; mở DG/XEM GAME rồi quét lại."
        return {"ok": True, "frames": frames, "options": options if game_frames else [],
                "loaded": bool(game_frames) or game_tab, "game_tab": game_tab, "note": note}
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
        # Detect a popup left by an earlier attempt before navigating back to FEBET.
        if _dg_window(driver) is not None:
            return {"ok": True, "already_open": True, "mode": "tab",
                    "note": "Game DG đã mở ở tab riêng của profile này."}
        # _lobby_handle only recognizes a DG iframe. Before clicking the provider
        # image that iframe does not exist, so select the FEBET page independently.
        page_handle = _febet_lobby_handle(driver)
        if page_handle is None:
            driver.switch_to.window(driver.window_handles[-1])
            driver.switch_to.default_content()
            driver.get(LOBBY_URL)
            page_handle = _febet_lobby_handle(driver)
        if page_handle is not None:
            driver.switch_to.window(page_handle)
            driver.switch_to.default_content()

        if _dg_window(driver) is not None:
            return {"ok": True, "already_open": True, "mode": "tab",
                    "note": "Game DG đã mở ở tab riêng của profile này."}
        existing = inspect(driver)
        if existing.get("ok") and existing.get("loaded"):
            return {"ok": True, "already_open": True, "note": "Iframe game đã mở trong profile này."}
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException

        try:
            image = WebDriverWait(driver, 45).until(lambda current: next((item for item in
                current.find_elements(By.CSS_SELECTOR, 'img[alt="partner"]')
                if "dream-gaming-square.webp" in (item.get_attribute("src") or "").lower()), None))
        except TimeoutException:
            return {"ok": False, "error": "Đã mở trang FEBET nhưng không tìm thấy ảnh Dream Gaming trong sảnh (%s)." % _safe_url(driver.current_url)}
        # Ảnh DG chỉ là logo nhỏ trong thẻ game; lớp phủ hover của thẻ che mất ảnh
        # nên phải bấm cả thẻ (div cursor-pointer), không bấm thẳng vào ảnh.
        try:
            card = image.find_element(
                By.XPATH, "./ancestor::*[contains(@class,'cursor-pointer')][1]")
        except Exception:
            card = image
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center',behavior:'instant'});",
            card)
        WebDriverWait(driver, 30).until(lambda _:
            card.is_displayed() and card.size.get("width", 0) > 0 and card.size.get("height", 0) > 0)
        time.sleep(0.25)
        try:
            card.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", card)
        clicked_xem_game = _click_xem_game(driver)

        # DG thường khởi tạo nhiều request trong iframe; giữ chờ tối đa 2 phút.
        frame_deadline = time.monotonic() + 120
        last = {"ok": True, "frames": [], "options": []}
        while time.monotonic() < frame_deadline:
            time.sleep(0.5)
            if _dg_window(driver) is not None:
                return {"ok": True, "already_open": False, "clicked_image": True,
                        "clicked_xem_game": clicked_xem_game, "mode": "tab",
                        "frames": [], "options": [],
                        "note": "Đã mở DG Baccarat ở tab riêng."}
            _lobby_handle(driver)
            clicked_xem_game = _click_xem_game(driver) or clicked_xem_game
            last = inspect(driver)
            if last.get("ok") and last.get("loaded"):
                return {"ok": True, "already_open": False, "clicked_image": True,
                        "clicked_xem_game": clicked_xem_game,
                        "frames": last["frames"],
                        "options": last["options"], "note": "Đã mở DG Baccarat trong iframe riêng."}
        return {"ok": False, "clicked_image": True,
                "clicked_xem_game": clicked_xem_game,
                "frames": last.get("frames", []), "options": last.get("options", []),
                "error": "Đã bấm ảnh DG nhưng chưa thấy nút XEM GAME hoặc iframe game trong 120 giây."}
    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return {"ok": False, "error": "Không mở được DG Baccarat (%s)." % type(exc).__name__}


def _click_xem_game(driver):
    """Find and click XEM GAME in the top page or any same profile frame/tab."""
    try:
        for handle in reversed(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
            except Exception:
                continue
            for path, info in _frame_contexts(driver):
                labels = info.get("labels") or []
                if not any(re.sub(r"\s+", " ", str(item.get("text") or "")).strip().upper()
                           == "XEM GAME" for item in labels):
                    continue
                try:
                    _enter_path(driver, path)
                    for button in driver.find_elements("css selector", "button"):
                        if not button.is_displayed() or not button.is_enabled():
                            continue
                        label = re.sub(r"\s+", " ", button.text or "").strip().upper()
                        if label != "XEM GAME":
                            continue
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center',inline:'center',behavior:'instant'});",
                            button)
                        try:
                            button.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", button)
                        return True
                finally:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
    except Exception:
        pass
    return False


_TABLE_ID = re.compile(r"^[0-9]{1,12}$")
_REAL_DG_TABLE_ID = re.compile(r"^60[0-9]{3,}$")


def _is_real_table_id(table_id):
    value = str(table_id or "")
    return bool(_TABLE_ID.fullmatch(value) and _REAL_DG_TABLE_ID.fullmatch(value))


def _lobby_handle(driver):
    """Find the current site tab whose frame tree contains the DG game.

    The operator may be embedded by FEBET, GK881, or another casino site.  The
    game origin is the shared DG marker; requiring a FEBET URL here prevented
    the common table/bet flow from working on other hosts.
    """
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            for _path, info in _frame_contexts(driver):
                if "ddnewpc" in str(info.get("url") or "").lower():
                    driver.switch_to.default_content()
                    return handle
            driver.switch_to.default_content()
        except Exception:
            continue
    return None


def _table_id_from_src(src):
    try:
        return (parse_qs(urlsplit(src or "").query).get("tableId") or [""])[0]
    except ValueError:
        return ""


def _dg_frame(driver, wait=15.0):
    """ ``(index, location)`` của iframe DG.

    Site có thể nạp qua trang chờ ``direct1.html`` rồi mới redirect sang
    ``index.html?...tableId=...``; thuộc tính ``src`` không phản ánh URL thật,
    nên phải vào từng frame đọc ``location.href`` và chờ tới khi có mã bàn.

    DG cũng có thể nằm ở **tab khác** (GK881 mở sảnh bằng ``window.open``).
    Chỉ quét tab hiện tại sẽ báo sai "Laya chưa tải", nên phải duyệt mọi tab
    rồi dừng lại ở tab chứa frame DG.
    """
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        try:
            for handle in list(reversed(driver.window_handles)):
                try:
                    driver.switch_to.window(handle)
                except Exception:
                    continue
                fallback = None
                for path, info in _frame_contexts(driver):
                    location = str(info.get("url") or "")
                    # ``ddnewpc`` is the desktop loader and ``ddnewwap`` the phone
                    # one; both are DG documents, so match the shared prefix.
                    if "ddnew" in location.lower():
                        driver.switch_to.default_content()
                        return path, location
                    # A lobby rendered without the ddnewpc marker: GK881 mobile
                    # embeds DG in an iframe whose URL stays on the hand-off page,
                    # and some builds draw the stage in the page body. Either way
                    # a Laya stage is the proof, so look inside this frame.
                    if fallback is None:
                        try:
                            _enter_path(driver, path)
                            if _has_top_laya(driver):
                                fallback = (path, location)
                        except Exception:
                            pass
                if fallback is not None:
                    path, location = fallback
                    _enter_path(driver, path)
                    return path, location
                driver.switch_to.default_content()
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return None, None
        time.sleep(0.5)


# DG vẽ sảnh và bàn bằng LayaAir (canvas): phân biệt trạng thái qua tên node —
# sảnh lưới bàn có thẻ enterMC (bản desktop) hoặc tableMC/roadMC (bản mobile
# ddnewwap), bàn thật có cửa cược Banker/Player hiện rõ.
_DG_STATE_JS = """
return (() => {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready: false};
  let lobby = false, inTable = false, label = '', cards = 0;
  let viewTable = '', viewName = '';
  // Bản ``ddnewpc`` dựng nhiều node cùng thoả "có betBtn": một view của bàn đang
  // chơi và các view phụ trong bảng cầu. Dừng ở node đầu tiên (cách cũ) làm
  // ``table_name`` ra ``QD07`` và ``table_id`` ra mã bàn khác trong khi người
  // chơi đang ở RB01 — cùng lỗi đã sửa trong ``_DG_BET_STATE_JS``. Chọn view
  // bằng điểm đo được: có ``tableInfoMan``, có giới hạn bàn thật, và
  // ``playerInfo.tableId`` trùng ``gameInfo.tableId``.
  const viewScore = (node) => {
    const info = node.gameInfo || (node.tableInfoMan && node.tableInfoMan.gameInfo) || {};
    const player = node.playerInfo || {};
    const limit = node.baccaratLimit || {};
    const infoTable = String(info.tableId === undefined || info.tableId === null
      ? '' : info.tableId).trim();
    const playerTable = String(player.tableId === undefined || player.tableId === null
      ? '' : player.tableId).trim();
    const minFloor = Number(limit.bpMin || limit.min || 0);
    const maxFloor = Number(limit.bpMax || limit.max || 0);
    let score = 0;
    if (node.tableInfoMan) score += 4;
    if (infoTable && playerTable && infoTable === playerTable) score += 4;
    if (minFloor > 0 && maxFloor > 0) score += 2;
    return score;
  };
  let bestScore = -1;
  const walk = (n, d) => {
    if (d > 10) return;
    const name = String(n.name || '');
    if (name === 'enterMC') lobby = true;
    // Bản mobile đặt lưới bàn trong 'tableMC' (kèm 'roadMC' cho cầu) chứ không
    // có 'enterMC', nên chỉ kiểm tra enterMC thì sảnh mobile bị coi là chưa tải.
    if (name === 'tableMC' || name === 'roadMC') lobby = true;
    if (n.tableId !== undefined && n.tableId !== null && String(n.tableId) !== '') cards++;
    // Màn hình bàn thật: bản desktop có node 'banker'; bản mobile không có node
    // tên đó mà dựng view cược với betBtn/betHandler (đo trực tiếp: sau khi vào
    // bàn mobile, _DG_STATE_JS cũ trả in_table=false trong khi view cược đã có).
    // Dùng cùng dấu hiệu với _DG_BET_STATE_JS để hai hàm không mâu thuẫn.
    if (name.toLowerCase() === 'banker' && n.visible) inTable = true;
    if (n.betBtn && (typeof n.betHandler === 'function' || n.betBtnMan
        || n.baccaratLimit || n.tableInfoMan)) {
      inTable = true;
      const score = viewScore(n);
      if (score > bestScore) {
        bestScore = score;
        // Mã bàn của **bàn đang chơi**: bản điện thoại vào bàn bằng cách bấm thẻ
        // thì URL không có tableId (đo trên tab 60101), nên phải đọc từ view cược.
        const fromView = [n.tableId, n.gameInfo && n.gameInfo.tableId,
          n.playerInfo && n.playerInfo.tableId, n.tableInfoMan && n.tableInfoMan.tableId]
          .map((value) => (value === undefined || value === null) ? '' : String(value).trim())
          .find((value) => /^60\\d{3,}$/.test(value)) || '';
        viewTable = fromView || viewTable;
        viewName = String((n.gameInfo && n.gameInfo.tableName)
          || (n.tableInfoMan && n.tableInfoMan.tableName) || '').trim() || viewName;
      }
    }
    const t = typeof n.text === 'string' ? n.text.trim() : '';
    if (!label && t && t.length <= 30 && /(RB|S|SB)[0-9]+/.test(t)) label = t;
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  const urlTable = (location.href.match(/tableId=([0-9]+)/) || [])[1] || '';
  return {ready: true, lobby: (lobby || cards > 0) && !inTable, in_table: inTable,
          label: label || viewName, table_id: viewTable || urlTable,
          table_name: viewName, url_table: urlTable,
          table_cards: cards};
})()
"""

_DG_BET_STATE_JS = r"""
return (() => {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready:false};
  // Bản ``ddnewpc`` (đo trên 888AE66) dựng **nhiều** node cùng thoả điều kiện
  // "có betBtn": một view của bàn đang chơi (RB01, gameNo
  // ``202611240024R1046``) và các view phụ trong bảng cầu (QC03/RB04/QD03/QD01,
  // gameNo ``2611244161928``). Lấy node đầu tiên — cách cũ — nên ``table_name``
  // ra ``QD07`` và ``round_id`` sai định dạng, làm ``groupBettingTick`` tưởng hai
  // profile lệch ván dù cùng bàn.
  //
  // Chọn view theo dấu hiệu **đo được**: chỉ view của bàn đang chơi mới có
  // ``tableInfoMan``, có ``baccaratLimit`` thật (min>0) và có
  // ``playerInfo.tableId`` trùng ``gameInfo.tableId``.
  const scoreView = (node) => {
    const info = node.gameInfo || (node.tableInfoMan && node.tableInfoMan.gameInfo) || {};
    const player = node.playerInfo || {};
    const limit = node.baccaratLimit || {};
    const infoTable = String(info.tableId === undefined || info.tableId === null
      ? '' : info.tableId).trim();
    const playerTable = String(player.tableId === undefined || player.tableId === null
      ? '' : player.tableId).trim();
    const minFloor = Number(limit.bpMin || limit.min || 0);
    const maxFloor = Number(limit.bpMax || limit.max || 0);
    let score = 0;
    if (node.tableInfoMan) score += 4;
    if (infoTable && playerTable && infoTable === playerTable) score += 4;
    if (minFloor > 0 && maxFloor > 0) score += 2;
    return score;
  };
  let view = null;
  let bestScore = -1;
  const walk = (node, depth) => {
    if (!node || depth > 60) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) {
      const score = scoreView(node);
      if (score > bestScore) { bestScore = score; view = node; }
    }
    const children = node._children || [];
    for (const child of children) walk(child, depth + 1);
  };
  walk(Laya.stage, 0);
  if (!view) return {ready:true, in_table:false};
  const info = view.gameInfo || view.tableInfoMan?.gameInfo || window.gameInfo || {};
  const player = view.playerInfo || window.playerInfo || {};
  // Mã bàn phải đọc từ **view cược**, không chỉ từ URL: trên bản điện thoại
  // (``ddnewwap``) vào bàn bằng cách bấm thẻ thì ``location`` không có ``tableId``
  // (đo trên tab 60101: URL trống nhưng ``view.tableId``/``gameInfo.tableId`` =
  // 60101). Thiếu bước này thì hai profile cùng bàn vẫn bị coi là khác bàn.
  const rawTableId = [view.tableId, info.tableId, player.tableId,
    view.tableInfoMan?.tableId, view.videoMan?.tableId, window.tableId]
    .map((value) => (value === undefined || value === null) ? '' : String(value).trim())
    .find((value) => /^60\d{3,}$/.test(value)) || '';
  const tableId = rawTableId || (location.href.match(/tableId=([0-9]+)/) || [])[1] || '';
  const tableName = String(info.tableName || view.tableName
    || view.tableInfoMan?.tableName || '').trim();
  const rawRoundId = String(info.gameNo || info.roundId || info.roundNo || info.issueNo
    || view.gameNo || '').trim();
  const roundId = /^[A-Za-z0-9_-]{1,64}$/.test(rawRoundId) ? rawRoundId : '';
  const rawMin = Number(view.baccaratLimit?.bpMin || view.baccaratLimit?.min
    || player.bpMin || player.limitMin || 0);
  const rawMax = Number(view.baccaratLimit?.bpMax || view.baccaratLimit?.max
    || player.bpMax || player.limitMax || 0);
  const currency = String(player.currency || player.currencyName || player.currencyCode || '').toUpperCase();
  const chipValues = (view.chipMan?.chipArray || []).map(chip =>
    Number(chip?.chipNum || chip?.value || chip?.amount || 0)).filter(value => value > 0);
  const maxRawChip = Math.max(0, ...chipValues);
  // Chỉ nhận nhãn giới hạn bàn thật ("10K-50M", "10,000-50,000,000").
  // Chuỗi dạng "954145/12" hay "1.7M/23" là tổng tiền cược / số người của từng
  // cửa, không phải sàn bàn, nên phải bỏ qua để min_k không bị sai.
  const parseFloor = (text) => {
    const raw = String(text || '');
    const bothUnits = raw.match(/([\d][\d,.]*)\s*([kKmM])\s*(?:-|~|đến|to)\s*([\d][\d,.]*)\s*([kKmM])/i);
    const oneUnit = raw.match(/([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)\s*([kKmM])(?![\d])/i);
    const plainDash = raw.match(/([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)(?:\s|$)/);
    const match = bothUnits || oneUnit || plainDash;
    if (!match) return 0;
    let value = Number(String(match[1]).replace(/,/g, ''));
    const unit = String(match[2] || '').toUpperCase();
    if (!Number.isFinite(value) || value <= 0) return 0;
    if (unit === 'M') value *= 1000;
    else if (unit === 'K' && value < 1000) value *= 1000;
    return value;
  };
  const findFloor = (node, depth = 0) => {
    if (!node || depth > 80) return 0;
    for (const text of [node.text, node._text, node.label, node._label, node.innerText,
      node.dataSource?.text, node.dataSource?.label]) {
      const value = parseFloor(text);
      if (value >= 80) return value;
    }
    for (const child of (node._children || [])) {
      const value = findFloor(child, depth + 1);
      if (value >= 80) return value;
    }
    return 0;
  };
  const screenFloor = findFloor(view.tableInfoMan);
  const floorRaw = screenFloor >= 80 ? screenFloor : rawMin;
  // DG trả số tiền theo ĐƠN VỊ HIỂN THỊ của bàn, không phải VND nguyên. Bằng chứng
  // đo trên bàn 60101 (GK881): nhãn giới hạn trên màn hình là "10-1000" và
  // ``baccaratLimit.bpMin/bpMax`` cũng đúng 10/1000; khay chip là
  // ``10, 100, 500, 1000, 10000, 500000`` hiển thị y hệt "10 … 500K"; số dư có
  // phần lẻ (``enterLimit`` 515.17). Nếu coi các số đó là VND thì bàn chỉ cho cược
  // 10đ–1.000đ, vô lý. Vậy 1 đơn vị DG = 1 "k" (1.000đ) = đúng thang của app, và
  // chia thêm 1000 sẽ gộp chip 500 với 1000 làm một rồi kéo mọi mức về 1k.
  const scale = 1;
  const values = (obj, names) => {
    for (const name of names) if (obj && Number(obj[name]) > 0) return Number(obj[name]);
    return 0;
  };
  const tmp = view.betMoneyTmp || {};
  const real = view.betMoneyTrue || {};
  const denoms = [];
  for (const chip of (view.chipMan?.chipArray || [])) {
    const raw = Number(chip?.chipNum || chip?.value || chip?.amount || 0);
    const normalized = scale ? Math.round(raw / scale) : 0;
    if (raw > 0 && normalized > 0) denoms.push(normalized);
  }
  const stateId = Number(info.stateId ?? info.state ?? view.stateId ?? 0);
  const countdown = Number(info.countDown ?? view.countDown ?? 0);
  const result = info.result && typeof info.result === 'object' ? info.result : {};
  const winnerRaw = String(info.winner || info.winSide || info.resultSide || info.winResult
    || info.winnerSide || info.winType || result.winner || result.winSide
    || result.result || view.winner || '').toUpperCase();
  let winner = /^(P|PLAYER|XIAN|1)$/.test(winnerRaw) ? 'P'
    : /^(B|BANKER|ZHUANG|2)$/.test(winnerRaw) ? 'B'
    : /^(T|TIE|DRAW|和|3)$/.test(winnerRaw) ? 'T' : '';
  const playerScore = Number(info.playerScore ?? info.playerPoint ?? result.playerScore);
  const bankerScore = Number(info.bankerScore ?? info.bankerPoint ?? result.bankerScore);
  if (!winner && stateId !== 1 && Number.isInteger(playerScore) && playerScore >= 0 && playerScore <= 9
      && Number.isInteger(bankerScore) && bankerScore >= 0 && bankerScore <= 9)
    winner = playerScore === bankerScore ? 'T' : playerScore > bankerScore ? 'P' : 'B';
  return {
    ready:true, in_table:true,
    table_id:tableId,
    table_name:tableName,
    round_id:roundId, state_id:stateId, countdown,
    bet_open:stateId === 1 && countdown >= 5,
    winner, scale, raw_min:rawMin, screen_floor:screenFloor,
    floor_source:screenFloor >= 80 ? 'table-info' : rawMin > 0 ? 'baccarat-limit' : 'fallback',
    min_k:scale ? Math.ceil(floorRaw / scale) : 0,
    max_k:scale && rawMax ? Math.floor(rawMax / scale) : 0,
    balance_k:scale ? Number(player.balance || 0) / scale : null,
    // ``balance_k`` = 0 vừa có thể là "hết tiền" vừa là "chưa đọc được chỗ khác"
    // (đo trên 60101: ``playerInfo.balance`` = 0 trong khi bàn in "Balance 0.00").
    // ``balance_known`` để UI phân biệt: chỉ chặn cược khi đã đọc được số dư thật.
    balance_known:Number.isFinite(Number(player.balance)) && Number(player.balance) > 0,
    denominations_k:[...new Set(denoms)].sort((a,b)=>b-a),
    pending:{P:values(tmp,['Player','player','PLAYER','xian','Xian','1']) / (scale || 1),
             B:values(tmp,['Banker','banker','BANKER','zhuang','Zhuang','2']) / (scale || 1),
             T:values(tmp,['Tie','tie','TIE','和','3']) / (scale || 1)},
    confirmed:{P:values(real,['Player','player','PLAYER','xian','Xian','1']) / (scale || 1),
               B:values(real,['Banker','banker','BANKER','zhuang','Zhuang','2']) / (scale || 1),
               T:values(real,['Tie','tie','TIE','和','3']) / (scale || 1)}
  };
})()
"""

_DG_STAGE_BET_JS = r"""
const done = arguments[arguments.length - 1];
const side = String(arguments[0] || '').toUpperCase();
const amountK = Math.trunc(Number(arguments[1]));
const expectedRound = String(arguments[2] || '');
const autoConfirm = Boolean(arguments[3]);
(async () => {
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  if (!['P','B'].includes(side) || amountK <= 0 || !expectedRound)
    return {ok:false, error:'Lệnh cược không hợp lệ.'};
  if (typeof Laya === 'undefined' || !Laya.stage) return {ok:false,error:'Laya chưa sẵn sàng.'};
  let view = null;
  const walk = (node, depth) => {
    if (!node || depth > 60 || view) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) { view = node; return; }
    for (const child of (node._children || [])) walk(child, depth + 1);
  };
  walk(Laya.stage, 0);
  if (!view) return {ok:false,error:'Chưa thấy màn cược DG.'};
  const info = view.gameInfo || view.tableInfoMan?.gameInfo || window.gameInfo || {};
  const player = view.playerInfo || window.playerInfo || {};
  const rawRoundId = String(info.gameNo || info.roundId || info.roundNo || info.issueNo
    || view.gameNo || '').trim();
  const roundId = /^[A-Za-z0-9_-]{1,64}$/.test(rawRoundId) ? rawRoundId : '';
  if (roundId !== expectedRound) return {ok:false,error:'Ván đã đổi trước khi đặt chip.'};
  const rawMin = Number(view.baccaratLimit?.bpMin || view.baccaratLimit?.min
    || player.bpMin || player.limitMin || 0);
  const rawMax = Number(view.baccaratLimit?.bpMax || view.baccaratLimit?.max
    || player.bpMax || player.limitMax || 0);
  const currency = String(player.currency || player.currencyName || player.currencyCode || '').toUpperCase();
  let maxRawChip = Math.max(0,...(view.chipMan?.chipArray || []).map(c=>Number(c?.chipNum||c?.value||c?.amount||0)));
  // Chỉ nhận nhãn giới hạn bàn thật ("10K-50M", "10,000-50,000,000").
  // Chuỗi dạng "954145/12" hay "1.7M/23" là tổng tiền cược / số người của từng
  // cửa, không phải sàn bàn, nên phải bỏ qua để min_k không bị sai.
  const parseFloor = (text) => {
    const raw = String(text || '');
    const bothUnits = raw.match(/([\d][\d,.]*)\s*([kKmM])\s*(?:-|~|đến|to)\s*([\d][\d,.]*)\s*([kKmM])/i);
    const oneUnit = raw.match(/([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)\s*([kKmM])(?![\d])/i);
    const plainDash = raw.match(/([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)(?:\s|$)/);
    const match = bothUnits || oneUnit || plainDash;
    if (!match) return 0;
    let value = Number(String(match[1]).replace(/,/g, ''));
    const unit = String(match[2] || '').toUpperCase();
    if (!Number.isFinite(value) || value <= 0) return 0;
    if (unit === 'M') value *= 1000;
    else if (unit === 'K' && value < 1000) value *= 1000;
    return value;
  };
  const findFloor = (node, depth = 0) => {
    if (!node || depth > 80) return 0;
    for (const text of [node.text, node._text, node.label, node._label, node.innerText,
      node.dataSource?.text, node.dataSource?.label]) {
      const value = parseFloor(text);
      if (value >= 80) return value;
    }
    for (const child of (node._children || [])) {
      const value = findFloor(child, depth + 1);
      if (value >= 80) return value;
    }
    return 0;
  };
  const screenFloor = findFloor(view.tableInfoMan);
  const floorRaw = screenFloor >= 80 ? screenFloor : rawMin;
  // Cùng đơn vị với ``_DG_BET_STATE_JS``: 1 đơn vị DG = 1 "k" (1.000đ). Đo trên
  // bàn 60101: nhãn "10-1000" == bpMin/bpMax, khay chip 10…500000 hiển thị
  // "10 … 500K". Chia thêm 1000 sẽ khiến bước xác nhận tự đồng ý với chính cái
  // sai (kỳ vọng ``denom*scale`` và delta đọc được cùng bị chia), nên lỗi tiền
  // không bao giờ lộ ra.
  const scale = 1;
  if (!scale) return {ok:false,error:'Không xác định được đơn vị tiền của bàn DG; đã dừng để tránh đặt sai số tiền.'};
  if (Number(info.stateId ?? info.state ?? view.stateId ?? 0) !== 1
      || Number(info.countDown ?? view.countDown ?? 0) < 5)
    return {ok:false,error:'Bàn chưa mở cược đủ lâu.'};
  const minK = Math.ceil(floorRaw / scale);
  const maxK = rawMax > 0 ? Math.floor(rawMax / scale) : 0;
  if (minK && amountK < minK) return {ok:false,error:`Mức ${amountK}k thấp hơn sàn bàn ${minK}k.`};
  if (maxK && amountK > maxK) return {ok:false,error:`Mức ${amountK}k vượt trần bàn ${maxK}k.`};
  const balK = Number(player.balance || 0) / scale;
  // Đo trên bàn 60101: ``playerInfo.balance = 0`` và bàn in "Balance(VND2) 0.00";
  // ``checkBet`` của Laya chặn ngay khi ``balance == 0`` nên mọi cú bấm chip chỉ
  // bật hộp "NoBalance" và ``betMoneyTmp`` đứng yên. Số dư đọc được là 0 thì **không**
  // chặn cứng ở đây (có build chỉ điền số dư sau ván đầu), nhưng phải nhớ để khi
  // chip không lên thì báo đúng nghi phạm thay vì đổ lỗi cho mệnh giá chip.
  const balanceUnread = !(Number.isFinite(balK) && balK > 0);
  if (!balanceUnread && amountK > balK)
    return {ok:false,error:`Số dư bàn không đủ (${Math.floor(balK)}k).`};
  const readTmp = (s) => {
    const names = s === 'P' ? ['Player','player','PLAYER','xian','Xian','1']
      : ['Banker','banker','BANKER','zhuang','Zhuang','2'];
    const current = view.betMoneyTmp || {};
    for (const name of names) if (Number(current[name]) > 0) return Number(current[name]);
    return 0;
  };
  const beforeP = readTmp('P'), beforeB = readTmp('B');
  const pendingCurrent = view.betMoneyTmp || {};
  if (beforeP || beforeB || Number(pendingCurrent.Tie || pendingCurrent.tie || pendingCurrent['3'] || 0))
    return {ok:false,error:'Đã có chip chờ xác nhận trên bàn; không tự xóa hoặc cộng chồng.'};
  const chips = view.chipMan?.chipArray || [];
  const denoms = [...new Set(chips.map(c=>Math.round(Number(c?.chipNum||c?.value||c?.amount||0)/scale))
    .filter(n=>Number.isInteger(n)&&n>0))].sort((a,b)=>b-a);
  if (!denoms.length) return {ok:false,error:'Không đọc được mệnh giá chip thật từ khay DG.'};
  const best = Array(amountK + 1).fill(null); best[0] = [];
  for (let total = 1; total <= amountK; total++) {
    for (const denom of denoms) {
      if (denom > total) continue;
      const prev = best[total - denom];
      if (prev && (!best[total] || prev.length + 1 < best[total].length))
        best[total] = [...prev, denom];
    }
  }
  if (!best[amountK]) return {ok:false,error:`Không thể ghép đúng ${amountK}k bằng chip đang có (${denoms.join(', ')}k).`};
  const aliases = side === 'P'
    ? ['Player','player','PLAYER','betPlayer','btnPlayer','btn_player','pBtn','xian','Xian','1']
    : ['Banker','banker','BANKER','betBanker','btnBanker','btn_banker','bBtn','zhuang','Zhuang','2'];
  const sources = [view.betBtn,view.betBtnMan?.betBtn,view.betButtons];
  let spot = null;
  for (const source of sources) if (source) for (const key of aliases) if (source[key]) { spot=source[key];break; }
  if (!spot) return {ok:false,error:`Không tìm được ô ${side} của bàn DG.`};
  const chipValue = (chip) => Number(chip?.chipNum||chip?.value||chip?.amount||0);
  // Đo trên bàn 60101 (Laya của DG):
  //   * tự phát sự kiện chuột vào node chip/ô cược **không** đổi
  //     ``playerInfo.selectChip`` / ``betMoneyTmp`` — Laya chỉ chạy hit-test rồi mới
  //     phát sự kiện cấp view, nên gọi ``event`` trên node là vô hiệu;
  //   * ``chipMan.selectChipHandler(chip)`` đổi đúng ``playerInfo.selectChip``;
  //   * ``view.betHandler({buttonName:'Player'|'Banker'})`` là chính handler mà view
  //     gắn cho ô cược (đúng chữ ký ``betHandler(e){... e.buttonName ...}``);
  //   * mọi đường đều bị ``checkBet`` chặn khi ``playerInfo.balance == 0``.
  // Vì vậy bấm chip = gọi handler của view, và **luôn đọc lại** trạng thái sau mỗi
  // bước; lệch là dừng ngay, không bấm lại để khỏi cộng dồn sai tiền.
  const selectedChip = () => Number(view.playerInfo?.selectChip
    || view.chipMan?.currentChip?.chipNum || 0);
  const selectChip = async (chip) => {
    const want = chipValue(chip);
    if (selectedChip() === want) return true;
    if (typeof view.chipMan?.selectChipHandler === 'function') {
      try { view.chipMan.selectChipHandler(chip); } catch (error) { return false; }
      await sleep(60);
    }
    return selectedChip() === want;
  };
  const placeChip = async (denom) => {
    const name = side === 'P' ? 'Player' : 'Banker';
    if (typeof view.betHandler !== 'function') return false;
    const before = readTmp(side);
    try { view.betHandler({buttonName:name}); } catch (error) { return false; }
    await sleep(120);
    return readTmp(side) - before === denom * scale;
  };
  let stagedRaw = 0;
  for (const denom of best[amountK].sort((a,b)=>b-a)) {
    const chip = chips.find(c=>chipValue(c) === denom * scale);
    if (!chip) return {ok:false,staged_k:stagedRaw/scale,error:'Khay chip không còn mệnh giá cần dùng; dừng.'};
    if (!await selectChip(chip))
      return {ok:false,staged_k:stagedRaw/scale,
        error:`Không chọn được chip ${denom}k trong khay; dừng, không thử lại.`};
    const before = readTmp(side);
    if (!await placeChip(denom)) {
      const after = readTmp(side);
      const detail = `cần +${denom}k; đọc được +${((after-before)/scale).toFixed(3)}k `
        + `(ô ${(before/scale).toFixed(3)}→${(after/scale).toFixed(3)}k, scale=${scale})`;
      const hint = balanceUnread ? ' Số dư bàn DG đọc được là 0 — kiểm tra "Balance" trong bàn; '
        + 'DG sẽ từ chối mọi cú bấm chip khi số dư bằng 0.' : '';
      return {ok:false,staged_k:stagedRaw/scale,
        error:`Số chip trên ô không tăng đúng mệnh giá sau khi bấm; đã dừng, không bấm lại (${detail}).${hint}`};
    }
    stagedRaw += denom * scale;
  }
  if (!autoConfirm) return {ok:true,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK};
  // Đo trên bàn 60101: ``betBtnMan.confirmBtn.event('click')`` không chạy vì Laya chỉ
  // phát sự kiện qua hit-test; còn ``view.confirmBet()`` (chính handler mà
  // ``addAllEvent`` gắn cho ``confirmBtn``) là đường xác nhận thật của view.
  const manager = view.betBtnMan || {};
  const confirmBtn = manager.confirmBtn || manager.sureBtn || manager.btnSure
    || manager.okBtn || view.confirmBtn || view.sureBtn || view.btnSure;
  let confirmed = false;
  if (typeof view.confirmBet === 'function') {
    try { view.confirmBet(); confirmed = true; } catch (error) { confirmed = false; }
  } else if (confirmBtn && typeof view.betBtnMan?.clickHandler === 'function'
             && confirmBtn.buttonName) {
    try { view.betBtnMan.clickHandler(String(confirmBtn.buttonName)); confirmed = true; }
    catch (error) { confirmed = false; }
  }
  if (!confirmed)
    return {ok:false,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK,
      error:'Chip đã xếp nhưng không tìm thấy nút xác nhận; không thử click lại.'};
  await sleep(400);
  const real = view.betMoneyTrue || {};
  const readReal = () => Number(real[side === 'P' ? 'Player' : 'Banker']
    || real[side === 'P' ? 'player' : 'banker'] || 0) / scale;
  // DG ghi tiền vào ``betMoneyTrue`` sau khi server nhận cược, không tức thì; đọc một
  // lần ở 400ms là chưa đủ nên phải chờ tới ~2s như bản WM.
  const confirmDeadline = Date.now() + 2000;
  let realSide = readReal();
  while (realSide < amountK && Date.now() < confirmDeadline) {
    await sleep(150);
    realSide = readReal();
  }
  if (realSide < amountK)
    return {ok:false,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK,
      error:`Đã bấm xác nhận nhưng DG chỉ ghi nhận ${realSide.toFixed(3)}k thay vì ${amountK}k.`};
  return {ok:true,staged:true,confirmed:true,round_id:roundId,side,amount_k:amountK};
})().then(done).catch(error=>done({ok:false,error:'Lỗi Laya khi đặt chip ('+(error?.name||'Error')+').' }));
"""

_DG_LOBBY_JS = r"""
return (() => {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready: false, tables: []};
  const tables = [];
  const seen = new Set();
  const valueOf = (objects, keys) => {
    for (const object of objects) {
      if (!object || typeof object !== 'object') continue;
      for (const key of keys) {
        const value = object[key];
        if (value !== undefined && value !== null && value !== '') return value;
      }
    }
    return '';
  };
  const walk = (n, d) => {
    if (d > 12 || tables.length >= 60) return;
    // Laya build versions expose card data on different wrappers. Keep the
    // table item itself and its common data/model fields, without walking the
    // whole object graph (which also contains session and loader internals).
    const info = n.tableInfo || n._tableInfo || n.tableData || n._tableData
      || n.data || n._data || n.dataSource || n._dataSource || n.model || n._model;
    const objects = [n, info];
    const tableId = String(valueOf(objects,
      ['tableId', 'tableID', 'table_id', 'gameTableId', 'game_table_id']));
    // The mobile build (ddnewwap) keeps the id and the label on the card node
    // itself: ``tableId="60101"``, ``gameType="Baccarat"``, name drawn by child
    // ``Text`` nodes ("Baccarat RB01" / "BLAIR"). It has no tableInfo wrapper,
    // so the old check rejected every row and the lobby looked empty even
    // though "Baccarat RB01/02..." was on screen.
    const name = String(valueOf(objects,
      ['tableName', 'table_name', 'name', 'tableCode', 'code', 'label']));
    const gameType = String(valueOf(objects, ['gameType', 'game_type']));
    let label = name.trim();
    if (!label) {
      // Read the first meaningful child text ("Baccarat RB01", "BLAIR").
      const texts = [];
      const collect = (node, depth) => {
        if (depth > 5 || texts.length >= 6) return;
        const value = typeof node.text === 'string' ? node.text.trim() : '';
        if (value) texts.push(value.replace(/\s+/g, ' '));
        for (let i = 0; i < (node.numChildren || 0); i++) {
          collect(node.getChildAt(i), depth + 1);
        }
      };
      collect(n, 0);
      label = texts.find((value) => /\b(RB|SB|S)\s*\d+\b/i.test(value))
        || texts.find((value) => value.length <= 24) || '';
    }
    const baccarat = /baccarat/i.test(gameType) || /baccarat/i.test(label)
      || /\b(RB|SB|S)\s*\d+\b/i.test(label);
    if (tableId && /^60\d{3,}$/.test(tableId) && baccarat) {
      if (!seen.has(tableId)) {
        seen.add(tableId);
        tables.push({table_id: tableId,
                     name: label || ('Bàn ' + tableId),
                     online: Number(valueOf(objects,
                       ['onlineNum', 'onlineCount', 'online_count', 'playerCount'])) || 0});
      }
    }
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  return {ready: true, lobby: tables.length > 0, tables: tables};
})()
"""


# Some sites (GK881 mobile) render the DG lobby directly in the page that hands
# the player over — ``/Account/LoginToSupplier?SupplierType=DG`` — instead of a
# DG iframe. The lobby is then a Laya stage in the top document, so the frame
# walkers below would never see it.
#
# Sảnh DG có thể chặn bằng captcha "Xác minh an toàn" (đo trên 888AE66: hiện
# đúng lúc vào bàn, che giữa màn hình). **Không giải captcha** — người dùng tự
# kéo thanh trượt. Adapter chỉ phát hiện, phát âm thanh báo và chờ.

# Đọc captcha từ **cả** cây node Laya và DOM. Đo trên 888AE66: lúc thanh trượt
# hiện, ``document.body.innerText`` rỗng và không có ``[class*=captcha]`` nào —
# toàn bộ là node Laya, nên chỉ soi DOM sẽ báo "không có captcha".
_DG_CAPTCHA_JS = r"""
return (() => {
  const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const hits = [];
  if (typeof Laya !== 'undefined' && Laya.stage) {
    const walk = (node, depth) => {
      if (!node || depth > 18 || hits.length >= 12) return;
      for (const key of ['text', '_text', 'label', '_label']) {
        try {
          const value = node[key];
          if (typeof value === 'string' && value.trim()) hits.push(norm(value));
        } catch (error) {}
      }
      const data = node.dataSource;
      if (data && typeof data === 'object') {
        for (const key of ['text', 'label', 'title']) {
          if (typeof data[key] === 'string' && data[key].trim()) hits.push(norm(data[key]));
        }
      }
      for (let i = 0; i < (node.numChildren || 0); i++) walk(node.getChildAt(i), depth + 1);
    };
    walk(Laya.stage, 0);
  }
  const domText = norm(document.body ? document.body.innerText : '');
  const slider = document.querySelector(
    '[class*=captcha],[id*=captcha],[class*=slider],[id*=slider],[class*=verify]');
  return {texts: hits, domText: domText.slice(0, 300), slider: !!slider,
          url: location.pathname};
})()
"""

# Captcha "Xác minh thành công" là thông báo thoáng qua; nếu coi nó là "đang bị
# chặn" thì tool báo động mãi sau khi người dùng đã vượt qua. Chỉ hai câu dưới
# đây mới là dấu hiệu **đang chặn**.
#
# Đo lại trên 888AE66 (25/11/2026) sau khi đưa khung DG lên tab chính: bản Laya
# hiện tại vẽ captcha bằng **tiếng Anh** — node ``sliderBtn``/``System`` mang chữ
# "SafetyVerify" và "Drag the slider". Không có mẫu tiếng Anh thì tool tưởng sảnh
# trống và quét bàn mãi trong khi màn hình đang chờ người kéo thanh trượt.
_CAPTCHA_BLOCK_RE = re.compile(
    r"kéo thanh trượt|keo thanh truot|xác minh an toàn|xac minh an toan"
    r"|drag the slider|safety\s*verify", re.I)
_CAPTCHA_PASS_RE = re.compile(
    r"xác minh thành công|xac minh thanh cong|verified successfully"
    r"|verification (?:successful|complete)", re.I)

# Bao lâu thì chờ người dùng tự kéo thanh trượt. Captcha hiện lúc sảnh/bàn đang
# tải, người dùng thường ở ngay màn hình nên 300 giây là đủ; quá hạn thì báo
# lỗi rõ ràng thay vì treo mãi.
_CAPTCHA_WAIT = 300.0


def captcha_state(driver):
    """Có captcha đang chặn sảnh DG không — chỉ đọc, không bao giờ giải.

    Trả ``{"blocked": bool, "text": str, "passed": bool}``. Người dùng tự kéo
    thanh trượt; hàm này chỉ nói cho UI biết để bật còi và hiện hướng dẫn.
    """
    if driver is None:
        return {"blocked": False, "text": "", "passed": False}
    try:
        data = driver.execute_script(_DG_CAPTCHA_JS) or {}
    except Exception:
        return {"blocked": False, "text": "", "passed": False}
    texts = [str(item) for item in (data.get("texts") or []) if item]
    blob = " | ".join(texts + [str(data.get("domText") or "")])
    blocked_text = ""
    for text in texts:
        if _CAPTCHA_BLOCK_RE.search(text):
            blocked_text = text
            break
    if not blocked_text and _CAPTCHA_BLOCK_RE.search(blob):
        blocked_text = _CAPTCHA_BLOCK_RE.search(blob).group(0)
    passed = bool(_CAPTCHA_PASS_RE.search(blob)) and not blocked_text
    return {"blocked": bool(blocked_text), "text": blocked_text,
            "passed": passed, "slider": bool(data.get("slider")),
            "url": str(data.get("url") or "")}


def wait_for_captcha(driver, report=None, timeout=300.0, poll=2.0):
    """Chờ người dùng tự vượt captcha; không tự động giải.

    Trả ``{"ok": True, "waited": float}`` khi hết captcha, hoặc
    ``{"ok": False, "error": ...}`` khi quá hạn. Trong lúc chờ, mỗi lần phát
    hiện captcha sẽ gọi ``report`` với ``level="action"`` để UI bật còi một lần
    (không lặp mỗi vòng poll).
    """
    def say(message, level="info"):
        if report is not None:
            try:
                report(message, level)
            except Exception:
                pass

    limit = max(1.0, float(timeout))
    started = None
    announced = False
    while True:
        state = captcha_state(driver)
        if not state.get("blocked"):
            if started is not None:
                waited = time.monotonic() - started
                say("Đã vượt captcha sau %.0f giây; chạy tiếp." % waited)
                return {"ok": True, "waited": waited}
            return {"ok": True, "waited": 0.0}
        if started is None:
            started = time.monotonic()
        if not announced:
            announced = True
            say("Sảnh DG đang chặn bằng captcha \"%s\". Hãy tự kéo thanh trượt "
                "trong cửa sổ Chrome của profile này; tool sẽ chờ tối đa %d giây."
                % (state.get("text") or "xác minh an toàn", int(limit)), "action")
        if time.monotonic() - started >= limit:
            say("Hết thời gian chờ captcha (%.0f giây)." % limit, "error")
            return {"ok": False, "waited": time.monotonic() - started,
                    "error": "Sảnh DG vẫn đang chờ captcha; hãy kéo thanh trượt "
                             "trong cửa sổ Chrome rồi chạy lại."}
        if not state.get("blocked"):
            continue
        time.sleep(max(0.2, float(poll)))


_TOP_LAYA_JS = r"""
try {
  if (typeof Laya === 'undefined' || !Laya.stage) return {laya: false};
  return {laya: true, stageKids: Laya.stage.numChildren || 0,
          width: Laya.stage.width || 0, height: Laya.stage.height || 0};
} catch (error) { return {laya: false}; }
"""


def _has_top_laya(driver):
    """True when the current document itself hosts a Laya stage."""
    try:
        data = driver.execute_script(_TOP_LAYA_JS) or {}
    except Exception:
        return False
    # A stage with no children is still loading; treat it as ready only when it
    # has drawn something, otherwise the caller keeps waiting.
    return bool(data.get("laya")) and int(data.get("stageKids") or 0) > 0


def _dg_window(driver):
    """Handle của tab DG riêng.

    Ba biến thể đã gặp: game mở ở tab ``ddnewpc`` riêng; game mở ngay trong tab
    của site; và GK881 mobile render sảnh Laya **trực tiếp** trong trang
    ``/Account/LoginToSupplier`` (không có iframe ``ddnewpc``).
    """
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            url = (driver.current_url or "").lower()
            # ``ddnewpc`` (desktop) and ``ddnewwap`` (phone) are both DG tabs.
            if "ddnew" in url:
                return handle
            if _has_top_laya(driver):
                return handle
        except Exception:
            continue
    return None


def _site_handle(driver):
    """Handle của tab site (không phải tab DG) — nơi sảnh DG sẽ được đưa lên.

    Giữ nguyên tab đang điều khiển nếu nó không phải tab DG, để hành vi của
    profile một-tab (E3951) không thay đổi.
    """
    try:
        handles = list(driver.window_handles)
    except Exception:
        return None
    try:
        current = driver.current_window_handle
    except Exception:
        current = None
    candidates = []
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            url = (driver.current_url or "").lower()
        except Exception:
            continue
        if "ddnew" in url:
            continue
        candidates.append(handle)
    chosen = current if current in candidates else (candidates[0] if candidates else None)
    if chosen is None:
        return None
    try:
        driver.switch_to.window(chosen)
        driver.switch_to.default_content()
    except Exception:
        return None
    return chosen


# Host của mọi ``<iframe src>`` trong trang hiện tại. Dùng để chắc chắn target
# đọc từ CDP đúng là frame mà **trang này** đã dựng, chứ không phải một tab DG
# khác trong cùng Chrome (nhiều profile có thể mở song song).
_IFRAME_HOSTS_JS = r"""
try {
  const hosts = [];
  for (const node of document.querySelectorAll('iframe,frame')) {
    const src = node.getAttribute('src') || '';
    if (!src) continue;
    try { hosts.push(new URL(src, location.href).hostname.toLowerCase()); }
    catch (error) {}
  }
  return hosts;
} catch (error) { return []; }
"""


def _promote_cdp_frame(driver, settle=20.0):
    """Đưa frame DG **khác tiến trình** (OOPIF) lên tab chính, nếu có.

    Đo trên ``e39d5d05qc.e3951.com/m/home``: ``<iframe src>`` ghi
    ``ddnewpc/direct1.html`` nhưng tài liệu thật lại là ``ddnewwap/index.html``,
    và CDP liệt kê nó thành target ``type: iframe``. WebDriver không switch được
    vào frame đó, nên đây là đường duy nhất để chạm tới sảnh.

    Chỉ hành động khi host của target trùng host một iframe trong trang hiện tại —
    nhờ vậy không bao giờ kéo nhầm tab DG của profile khác.
    """
    if driver is None or not hasattr(driver, "execute_cdp_cmd"):
        return {"ok": False, "promoted": False, "error": "không hỗ trợ CDP"}
    try:
        hosts = driver.execute_script(_IFRAME_HOSTS_JS) or []
    except Exception:
        return {"ok": False, "promoted": False, "error": "không đọc được iframe"}
    hosts = {str(host).lower() for host in hosts if host}
    if not hosts:
        return {"ok": False, "promoted": False, "error": "trang không có iframe"}
    target = find_game_frame(driver, wait=0)
    if not target or target.get("type") != "iframe":
        return {"ok": False, "promoted": False, "error": "không có target DG dạng iframe"}
    if _frame_host(target["url"]) not in hosts:
        return {"ok": False, "promoted": False, "error": "target DG không thuộc trang này"}
    _site_handle(driver)
    return promote_frame_to_tab(driver, target, settle=settle)


def _dg_context(driver, wait=15.0):
    """Đặt driver vào đúng document DG (tab riêng hoặc iframe của site bất kỳ)."""
    deadline = time.monotonic() + max(0.0, wait)
    tried_promote = False
    while True:
        window = _dg_window(driver)
        if window is not None:
            location = driver.current_url or ""
            # Distinguish a real DG tab (desktop ``ddnewpc`` / phone ``ddnewwap``)
            # from a page that hosts the lobby in its own body (GK881 mobile
            # hand-off page).
            mode = "tab" if "ddnew" in location.lower() else "top"
            return {"mode": mode, "location": location}
        else:
            path, location = _dg_frame(driver, wait=0)
            if path == ():
                # Lobby lives in the top document itself.
                driver.switch_to.default_content()
                return {"mode": "top", "location": location}
            if path is not None:
                _enter_path(driver, path)
                mode = "iframe" if "ddnew" in (location or "").lower() else "laya-frame"
                return {"mode": mode, "path": path, "location": location}
            # No DG frame: the lobby may be a Laya stage in this document.
            if _has_top_laya(driver):
                return {"mode": "top", "location": driver.current_url or ""}
            # WebDriver cannot enter a cross-process frame, so a lobby hosted in
            # one stays invisible here even while it runs. Measured on E3951
            # mobile: the game document is a CDP target ``type: iframe``
            # (``ddnewwap/index.html``) while the page's ``<iframe src>`` still
            # points at the desktop loader. Promoting that URL to the tab is the
            # only way WebDriver can reach it, and it also strips the site's
            # promo overlays, so try it once per call.
            if not tried_promote:
                tried_promote = True
                moved = _promote_cdp_frame(
                    driver, settle=min(25.0, max(6.0, deadline - time.monotonic())))
                if moved.get("ok"):
                    continue
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def _frame_host(url):
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _is_site_host(host, site_hosts):
    for site in site_hosts or ():
        name = str(site or "").strip().lower()
        if name and (host == name or host.endswith("." + name)):
            return True
    return False


def game_frame(driver, site_hosts=(), wait=6.0, handles=None):
    """Find the iframe that hosts the Dream Gaming document.

    Mobile GK881 embeds the lobby in an iframe whose host is not the site host,
    so the frame is identified by its own document URL: a ``ddnewpc`` document
    wins, otherwise any non-site, non-widget frame that already runs a Laya
    stage. Returns ``{"handle", "path", "url"}`` or ``None``. The URL carries a
    session token, so callers must never log or return it.
    """
    if driver is None:
        return None
    try:
        if handles is None:
            handles = list(reversed(list(driver.window_handles)))
    except Exception:
        return None
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        for handle in handles:
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
            except Exception:
                continue
            fallback = None
            try:
                contexts = list(_frame_contexts(driver))
            except Exception:
                contexts = []
            for path, info in contexts:
                url = str(info.get("url") or "")
                host = _frame_host(url)
                if not host:
                    continue
                if "ddnew" in url.lower():
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                    return {"handle": handle, "path": path, "url": url}
                if (fallback is None and not _is_site_host(host, site_hosts)
                        and not _is_widget_origin(url)):
                    fallback = (path, url)
            if fallback is not None:
                path, url = fallback
                try:
                    _enter_path(driver, path)
                    if _has_top_laya(driver):
                        driver.switch_to.default_content()
                        return {"handle": handle, "path": path, "url": url}
                except Exception:
                    pass
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.4)


def navigate_top(driver, url):
    """Navigate the active tab to ``url`` without tearing down a managed session.

    ``driver.get`` rebinds the WebDriver target; on an OmniLogin/Hidemium profile
    that makes the manager kill Chrome and every later call fails with
    InvalidSessionIdException. ``Page.navigate`` over CDP keeps the session
    alive, so it is tried first and ``get`` is only a last resort.
    """
    if driver is None or not url:
        return False
    if hasattr(driver, "execute_cdp_cmd"):
        try:
            driver.execute_cdp_cmd("Page.navigate", {"url": url})
            return True
        except Exception:
            pass
    try:
        driver.get(url)
        return True
    except Exception:
        return False


def _cdp_port():
    """Cổng gỡ lỗi của Chrome đang dùng (engine đổi cổng theo từng trò)."""
    try:
        from aibcr.adapters import browser as BR
        return int(getattr(BR, "CDP_PORT", dg_pages.DEFAULT_PORT))
    except Exception:
        return dg_pages.DEFAULT_PORT


def find_game_frame(driver, wait=6.0, port=None):
    """Target DG đọc thẳng từ CDP, kể cả iframe **khác tiến trình** (OOPIF).

    Đo trên ``e39d5d05qc.e3951.com/m/home``: game DG là một target
    ``type: iframe`` có tài liệu thật ``ddnewwap/index.html``, còn thẻ ``<iframe>``
    trong trang vẫn ghi ``src=ddnewpc/direct1.html``. WebDriver không switch vào
    được frame đó, nên ``_frame_contexts``/``game_frame`` luôn báo không thấy game
    và mọi bước sau (đọc bàn, xếp chip) chết ở "Laya chưa tải". ``/json/list`` là
    đường duy nhất thấy nó.

    Trả ``{"url", "type", "port"}`` hoặc ``None``. URL mang token phiên nên chỉ
    dùng để điều hướng, không log/không trả ra ngoài.
    """
    if driver is None:
        return None
    port = _cdp_port() if port is None else int(port)
    try:
        target = dg_pages.find_game_target(port, wait=wait)
    except Exception:
        return None
    if not target:
        return None
    url = str(target.get("url") or "")
    if not url:
        return None
    return {"url": url, "type": str(target.get("type") or ""), "port": port}


def _wait_promoted(driver, url, settle):
    """Chờ tab chính thật sự chạy tài liệu DG --- không chỉ tin ``navigate`` trả về."""
    result = {"ok": False, "promoted": False, "mode": "", "host": "",
              "error": ""}
    deadline = time.monotonic() + max(1.0, float(settle))
    while time.monotonic() < deadline:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        try:
            current = driver.current_url or ""
        except Exception:
            current = ""
        try:
            laya = _has_top_laya(driver)
        except Exception:
            laya = False
        if "ddnew" in current.lower() or laya:
            result.update(ok=True, promoted=True, mode="tab",
                          host=_frame_host(current) or _frame_host(url),
                          note="Đã thay URL trang bằng sảnh DG.")
            return result
        time.sleep(0.5)
    result.update(host=_frame_host(url),
                  error="Đã điều hướng nhưng sảnh DG chưa tải xong trên tab chính.")
    return result


def promote_frame_to_tab(driver, found, settle=20.0):
    """Đưa URL của một target DG (tab hoặc OOPIF) lên chính tab của site.

    Dùng chung cho iframe mà WebDriver thấy được và iframe khác tiến trình: cả
    hai chỉ cần một URL thật rồi ``navigate_top``. Nhờ vậy sảnh DG rời khỏi trang
    site, mọi popup khuyến mãi/overlay biến mất, và ``sync_table`` đổi bàn được
    bằng loader của chính sảnh.
    """
    result = {"ok": False, "promoted": False, "mode": "", "host": "",
              "error": ""}
    url = str((found or {}).get("url") or "")
    if not url:
        result["error"] = "Không có URL sảnh DG để tải sang tab chính."
        return result
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    if not navigate_top(driver, url):
        result.update(host=_frame_host(url),
                      error="Không điều hướng được tab chính tới sảnh DG.")
        return result
    return _wait_promoted(driver, url, settle)


def promote_lobby_to_tab(driver, site_hosts=(), wait=6.0, settle=20.0,
                         prefer_handle=None):
    """Replace the site page URL with the DG lobby document.

    The lobby normally lives inside a site iframe; navigating the tab to the
    frame's real URL removes the site DOM (popups, promo layers) and turns the
    lobby into the page itself. ``sync_table`` can then rewrite ``direct1.html``
    so every profile joins the same table. Only the host is reported, never the
    tokenised URL.
    """
    result = {"ok": False, "promoted": False, "mode": "", "host": "",
              "error": ""}
    if driver is None:
        result["error"] = "Chưa mở Chrome."
        return result
    if not (hasattr(driver, "execute_cdp_cmd") or hasattr(driver, "get")):
        result["error"] = "Trình duyệt này không hỗ trợ điều hướng tab."
        return result
    try:
        ctx = _dg_context(driver, wait=2.0)
    except Exception:
        ctx = None
    if ctx and ctx.get("mode") == "tab":
        result.update(ok=True, promoted=True, mode="tab",
                      host=_frame_host(ctx.get("location")),
                      note="Sảnh DG đã ở tab chính.")
        return result
    handles = None
    if prefer_handle:
        try:
            handles = [prefer_handle] + [handle for handle in
                                         reversed(list(driver.window_handles))
                                         if handle != prefer_handle]
        except Exception:
            handles = None
    found = game_frame(driver, site_hosts=site_hosts, wait=wait, handles=handles)
    if not found:
        # The frame may be out-of-process, which WebDriver cannot enter (measured
        # on E3951 mobile: real document is ``ddnewwap/index.html`` while the
        # ``src`` attribute still says ``ddnewpc/direct1.html``). CDP targets are
        # the only place that URL exists, so fall back to them before failing.
        moved = _promote_cdp_frame(driver, settle=settle)
        if moved.get("promoted"):
            return moved
        result["error"] = "Chưa thấy iframe sảnh DG để tách sang tab chính."
        return result
    try:
        driver.switch_to.window(found["handle"])
        driver.switch_to.default_content()
    except Exception:
        pass
    if not navigate_top(driver, found["url"]):
        result.update(host=_frame_host(found["url"]),
                      error="Không điều hướng được tab chính tới sảnh DG.")
        return result
    return _wait_promoted(driver, found["url"], settle)


# Thẻ bàn trong sảnh Laya (GK881 mobile vẽ sảnh ngay trong body, nên không có
# URL ``direct1.html`` để sửa). Tìm thẻ theo ``tableId`` rồi **đổi toạ độ stage →
# client** để bấm chuột thật; Laya chỉ phản ứng với hit-test thật, không với
# ``event('click')`` hay handler gọi tay.
_LAYA_CARD_BOX_JS = r"""
const wanted = String(arguments[0] || '');
if (typeof Laya === 'undefined' || !Laya.stage) return {ok: false, reason: 'no-laya'};
const stage = Laya.stage;
let hit = null;
const walk = (node, depth) => {
  if (!node || hit || depth > 40) return;
  let id = '';
  try {
    if (node.tableId !== undefined && node.tableId !== null) id = String(node.tableId);
  } catch (error) {}
  if (id && id === wanted) { hit = node; return; }
  for (let i = 0; i < (node.numChildren || 0); i++) walk(node.getChildAt(i), depth + 1);
};
walk(stage, 0);
if (!hit) return {ok: false, reason: 'no-card'};
// Laya hit-tests in stage space, so the node centre must be converted to client
// pixels of the canvas that actually receives the mouse event.
const canvas = stage._canvas || document.getElementById('layaCanvas')
  || document.querySelector('canvas');
if (!canvas) return {ok: false, reason: 'no-canvas'};
const rect = canvas.getBoundingClientRect();
const stageW = Number(stage.width) || rect.width || 0;
const stageH = Number(stage.height) || rect.height || 0;
if (!stageW || !stageH) return {ok: false, reason: 'no-stage-size'};
const box = hit.hitArea || {x: 0, y: 0, width: hit.width, height: hit.height};
const local = new Laya.Point(Number(box.x || 0) + Number(box.width || 0) / 2,
                             Number(box.y || 0) + Number(box.height || 0) / 2);
const global = hit.localToGlobal(local);
const x = rect.left + global.x * rect.width / stageW;
const y = rect.top + global.y * rect.height / stageH;
if (!Number.isFinite(x) || !Number.isFinite(y)) return {ok: false, reason: 'no-point'};
if (x < rect.left || y < rect.top || x > rect.left + rect.width || y > rect.top + rect.height)
  return {ok: false, reason: 'outside-canvas'};
return {ok: true, x, y, table_id: wanted,
        stage: [Math.round(stageW), Math.round(stageH)],
        canvas: [Math.round(rect.width), Math.round(rect.height),
                 Math.round(rect.left), Math.round(rect.top)]};
"""


# Dự phòng khi không bấm được bằng chuột: tìm thẻ bàn trong sảnh Laya và gọi
# thẳng handler của nó. Đo trên bàn 60101 của DG: handler ``run()`` trả "ok" mà
# sảnh **vẫn đứng nguyên**, nên đường này chỉ dùng sau ``_LAYA_CARD_BOX_JS`` +
# ``_cdp_click`` (chuột thật mới qua được hit-test của Laya).
_LAYA_ENTER_JS = r"""
const wanted = String(arguments[0] || '');
const wantedName = String(arguments[1] || '').toLowerCase();
if (typeof Laya === 'undefined' || !Laya.stage) return {ok: false, reason: 'no-laya'};
const nodes = [];
const walk = (node, depth) => {
  if (!node || depth > 40 || nodes.length > 4000) return;
  nodes.push(node);
  for (let i = 0; i < (node.numChildren || 0); i++) walk(node.getChildAt(i), depth + 1);
};
walk(Laya.stage, 0);
const labelOf = (node) => {
  for (const key of ['text', '_text', 'label', '_label']) {
    try { const value = node[key];
      if (typeof value === 'string' && value.trim()) return value.trim(); } catch (error) {}
  }
  return '';
};
// The mobile build (ddnewwap) keeps the id on the card node itself and draws the
// name in child Text nodes ("Baccarat RB01"), so matching the label against the
// numeric id never hit a card there.
const idOf = (node) => {
  try {
    const value = node.tableId;
    if (value !== undefined && value !== null && String(value) !== '') return String(value);
  } catch (error) {}
  return '';
};
const textsOf = (node, limit) => {
  const out = [];
  const collect = (current, depth) => {
    if (!current || depth > 4 || out.length >= limit) return;
    const value = labelOf(current);
    if (value) out.push(value.replace(/\s+/g, ' '));
    for (let i = 0; i < (current.numChildren || 0); i++) {
      collect(current.getChildAt(i), depth + 1);
    }
  };
  collect(node, 0);
  return out;
};
const clickable = (node) => {
  let cur = node;
  let hops = 0;
  while (cur && hops < 8) {
    try {
      if (cur.clickHandler && typeof cur.clickHandler.run === 'function') return cur;
      if (typeof cur.event === 'function') return cur;
    } catch (error) {}
    cur = cur.parent; hops += 1;
  }
  return null;
};
const byId = wanted ? nodes.filter((node) => idOf(node) === wanted) : [];
const byLabel = nodes.filter((node) => {
  const label = labelOf(node);
  if (!label) return false;
  if (wantedName && label.toLowerCase().includes(wantedName)) return true;
  if (wanted && label.includes(wanted)) return true;
  if (wantedName && textsOf(node, 6).some((text) =>
        text.toLowerCase().includes(wantedName))) return true;
  return false;
});
const match = byId.find((node) => clickable(node))
  || byLabel.find((node) => clickable(node))
  || byId[0] || byLabel[0];
if (!match) return {ok: false, reason: 'no-card', scanned: nodes.length};
const target = clickable(match);
if (!target) return {ok: false, reason: 'no-handler'};
try {
  if (target.clickHandler && typeof target.clickHandler.run === 'function') {
    target.clickHandler.run();
  } else {
    target.event('mousedown'); target.event('mouseup'); target.event('click');
  }
  return {ok: true, label: labelOf(match) || idOf(match),
          table_id: idOf(match)};
} catch (error) {
  return {ok: false, reason: 'throw'};
}
"""


def _laya_enter_table(driver, table_id, name=""):
    """Tap a table card inside a Laya lobby rendered in the page body.

    Measured on the DG phone lobby (``ddnewwap``, table 60101): calling
    ``clickHandler.run()`` on the card returns success but leaves the stage in
    the lobby. Laya only reacts to a real hit-test, so the card is located by
    ``tableId``, its centre converted from stage space to client pixels, and a
    genuine mouse event is dispatched with ``Input.dispatchMouseEvent``.
    """
    table_id = str(table_id or "")
    box = {}
    try:
        box = driver.execute_script(_LAYA_CARD_BOX_JS, table_id) or {}
    except Exception:
        box = {}
    if box.get("ok"):
        clicked = _cdp_click(driver, box.get("x"), box.get("y"))
        if clicked:
            return {"ok": True, "label": table_id, "table_id": table_id,
                    "via": "cdp-mouse"}
    try:
        return driver.execute_script(_LAYA_ENTER_JS, table_id, str(name or "")) or {}
    except Exception:
        return {"ok": False, "reason": "script-error"}


def _cdp_click(driver, x, y):
    """Bấm chuột thật tại ``(x, y)`` client của tab đang điều khiển."""
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return False
    if not hasattr(driver, "execute_cdp_cmd"):
        return False
    base = {"x": x, "y": y, "button": "left", "clickCount": 1}
    try:
        driver.execute_cdp_cmd("Input.dispatchMouseEvent",
                               dict(base, type="mouseMoved", buttons=0))
        driver.execute_cdp_cmd("Input.dispatchMouseEvent",
                               dict(base, type="mousePressed", buttons=1))
        time.sleep(0.05)
        driver.execute_cdp_cmd("Input.dispatchMouseEvent",
                               dict(base, type="mouseReleased", buttons=0))
        return True
    except Exception:
        return False


def _loader_url(location, src, table_id):
    # The desktop build (``ddnewpc``) loads a table through ``direct1.html``.
    # The phone build (``ddnewwap``) has no such file — measured live, requesting
    # ``ddnewwap/direct1.html`` returns a 404 page with no Laya at all. Phone
    # tables open from ``index.html?tableId=<id>``, so its own file name must be
    # kept instead of forcing the desktop loader.
    base = src if "ddnew" in (src or "").lower() else location
    parsed = urlsplit(base)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tableId"] = [table_id]
    path = parsed.path
    if "ddnewwap" in base.lower():
        if not path.lower().endswith(".html"):
            path = path.rsplit("/", 1)[0] + "/index.html"
    elif "direct1.html" not in path:
        path = path.rsplit("/", 1)[0] + "/direct1.html"
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), ""))


def exact_chip_sequence(amount, denominations):
    """Return the fewest exact chip denominations, or an empty list if impossible."""
    try:
        target = int(amount)
    except (TypeError, ValueError):
        return []
    denoms = set()
    for value in denominations or []:
        try:
            denomination = int(value)
        except (TypeError, ValueError):
            continue
        if denomination > 0:
            denoms.add(denomination)
    denoms = sorted(denoms, reverse=True)
    if target <= 0 or target > 10000 or not denoms:
        return []
    best = [None] * (target + 1)
    best[0] = []
    for total in range(1, target + 1):
        for denomination in denoms:
            if denomination > total:
                continue
            previous = best[total - denomination]
            if previous is not None and (best[total] is None
                                         or len(previous) + 1 < len(best[total])):
                best[total] = previous + [denomination]
    return sorted(best[target] or [], reverse=True)


def bet_state(driver, wait=0.0):
    """Read a sanitized DG round, limits and chip state from its Laya frame."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đọc trạng thái cược DG."}
    try:
        ctx = _dg_context(driver, wait)
        if ctx is None:
            return {"ok": False, "error": "Chưa thấy frame game DG đang tải."}
        state = driver.execute_script(_DG_BET_STATE_JS) or {}
        if not state.get("in_table"):
            return {"ok": False, "in_table": False, "error": "Profile chưa ở trong bàn DG."}
        state["ok"] = True
        return state
    except Exception as exc:
        return {"ok": False, "error": "Không đọc được trạng thái cược DG (%s)." % type(exc).__name__}


def stage_bet(driver, side, amount_k, round_id, confirm=False, wait=0.0):
    """Stage an exact DG chip amount once; confirmation is opt-in and verified."""
    side = str(side or "").strip().upper()
    if side not in ("P", "B"):
        return {"ok": False, "error": "Cửa DG chỉ hỗ trợ Player hoặc Banker."}
    try:
        amount = int(amount_k)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Mức chip không hợp lệ."}
    if amount <= 0 or amount > 10000:
        return {"ok": False, "error": "Mức chip phải nằm trong 1–10.000k."}
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đặt chip DG."}
    try:
        ctx = _dg_context(driver, wait)
        if ctx is None:
            return {"ok": False, "error": "Chưa thấy frame game DG đang tải."}
        return driver.execute_async_script(_DG_STAGE_BET_JS, side, amount,
                                           str(round_id or ""), bool(confirm)) or {}
    except Exception as exc:
        return {"ok": False, "error": "Không đặt được chip DG (%s)." % type(exc).__name__}


def current_table(driver, wait=15.0):
    """Read the DG tableId of the game iframe; never expose the iframe URL/token."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đọc bàn DG."}
    try:
        ctx = _dg_context(driver, wait)
        if ctx is None:
            return {"ok": False, "error": "Chưa mở game DG hoặc bàn chưa tải xong."}
        state = driver.execute_script(_DG_STATE_JS) or {}
        # Bản điện thoại không ghi ``tableId`` vào URL khi vào bàn bằng cách bấm
        # thẻ, nên mã bàn lấy từ view cược trước rồi mới tới URL/iframe src.
        table_id = (state.get("table_id") or state.get("url_table")
                    or _table_id_from_src(ctx["location"]))
        in_table = bool(state.get("in_table")) and _is_real_table_id(table_id)
        return {"ok": True, "mode": ctx["mode"],
                "table_id": table_id,
                "in_table": in_table,
                "lobby": bool(state.get("lobby")) or not in_table,
                "label": state.get("label") or ""}
    except Exception as exc:
        return {"ok": False, "error": "Không đọc được bàn DG (%s)." % type(exc).__name__}


def lobby_tables(driver, wait=25.0, log=None):
    """Danh sách bàn thật (tableId 60101…) đọc từ các thẻ sảnh Laya của DG.

    ``log`` (tuỳ chọn) là callback ``(text, level)``: khi có, sảnh DG bị captcha
    sẽ được báo ngay ở mức ``action`` để UI bật còi và chờ người dùng tự kéo
    thanh trượt. Không truyền ``log`` (nhịp dò ``dg.table``) thì hàm chỉ đọc một
    lượt, không bao giờ treo chờ.
    """
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi quét sảnh DG."}
    try:
        # Một số build (GK881 desktop) chặn ngay bằng captcha trước khi Laya vẽ
        # gì. Vòng đọc bên dưới cũng tự phát hiện captcha hiện muộn, nên ở đây
        # chỉ cần đọc nhanh một lượt: chờ 300 giây ngay từ đầu sẽ làm UI im lặng
        # trong khi màn hình còn đang tải.
        if log is not None:
            gate = captcha_state(driver)
            if gate.get("blocked"):
                gate = wait_for_captcha(driver, log, timeout=_CAPTCHA_WAIT, poll=2.0)
                if not gate.get("ok"):
                    return {"ok": False, "captcha": True, "error": gate.get("error")}
                wait = float(wait) + float(gate.get("waited") or 0)
        deadline = time.monotonic() + max(0.0, wait)
        last_data = {"ready": False, "tables": []}
        last_state = {}
        announced = False
        next_gate = time.monotonic() + 2.0
        while True:
            ctx = _dg_context(driver, wait=min(0.5, max(0.0, deadline - time.monotonic())))
            if ctx is not None:
                last_state = driver.execute_script(_DG_STATE_JS) or {}
                last_data = driver.execute_script(_DG_LOBBY_JS) or last_data
                current_id = str(last_state.get("table_id") or last_state.get("url_table")
                                 or _table_id_from_src(ctx["location"]))
                if last_state.get("in_table") and _is_real_table_id(current_id):
                    return {"ok": True, "in_table": True,
                            "table_id": current_id,
                            "tables": [{"table_id": current_id,
                                        "name": last_state.get("label") or "Bàn " + current_id,
                                        "online": 0}], "current_table": True}
                tables = []
                seen = set()
                for row in last_data.get("tables") or []:
                    table_id = str(row.get("table_id") or "").strip()
                    if not _is_real_table_id(table_id) or table_id in seen:
                        continue
                    seen.add(table_id)
                    tables.append({"table_id": table_id,
                                   "name": str(row.get("name") or "Bàn " + table_id).strip(),
                                   "online": max(0, int(row.get("online") or 0))})
                if tables:
                    return {"ok": True, "in_table": bool(last_state.get("in_table")),
                            "tables": tables}
                # Captcha có thể hiện **sau** cổng chờ đầu tiên (đo trên 888AE66:
                # thanh trượt bật lên đúng lúc Laya vẽ sảnh). Nếu chỉ đọc ở hạn
                # chót thì còi kêu chậm và người dùng thấy "chưa có bàn" trước.
                if log is not None and time.monotonic() >= next_gate:
                    next_gate = time.monotonic() + 2.0
                    gate = captcha_state(driver)
                    if gate.get("blocked") and not announced:
                        announced = True
                        # Hú còi rồi **chờ** tới khi người dùng kéo xong, thay vì
                        # trả lỗi sau 60 giây: người dùng thường đang nhìn màn
                        # hình khác, hết hạn sớm chỉ làm họ phải chạy lại cả luồng.
                        gate = wait_for_captcha(driver, log,
                                                timeout=_CAPTCHA_WAIT, poll=2.0)
                        if not gate.get("ok"):
                            return {"ok": False, "captcha": True,
                                    "error": gate.get("error")}
                        waited = float(gate.get("waited") or 0.0)
                        deadline += waited
                        wait = float(wait) + waited
                        continue
            if time.monotonic() >= deadline:
                # Luôn đọc captcha để câu lỗi nói đúng nguyên nhân (UI sẽ hú còi
                # vì khớp mẫu "xác minh an toàn"); chỉ **chờ** khi caller truyền
                # ``log``, để nhịp dò 5 giây không bị treo.
                gate = captcha_state(driver)
                if gate.get("blocked"):
                    return {"ok": False, "captcha": True,
                            "error": "Sảnh DG đang chặn bằng captcha \"%s\"; hãy kéo thanh "
                                     "trượt trong cửa sổ Chrome của profile này rồi chạy lại."
                                     % (gate.get("text") or "xác minh an toàn")}
                if last_data.get("ready"):
                    return {"ok": False,
                            "error": "Laya đã tải nhưng chưa tìm thấy node bàn thật trong sảnh DG.",
                            "laya_ready": True, "table_count": 0}
                return {"ok": False,
                        "error": "Laya của sảnh DG chưa tải xong nên chưa đọc được danh sách bàn.",
                        "laya_ready": False, "table_count": 0}
            time.sleep(0.25)
    except Exception as exc:
        return {"ok": False, "error": "Không quét được sảnh DG (%s)." % type(exc).__name__}


def _lobby_url_from(location):
    """URL sảnh của chính tab DG: bỏ ``tableId`` nhưng giữ nguyên token phiên."""
    parsed = urlsplit(location or "")
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("tableId", None)
    door = (query.get("door") or query.get("Door") or [""])[0]
    path = parsed.path
    if "ddnewwap" in (location or "").lower():
        if not path.lower().endswith(".html"):
            path = path.rsplit("/", 1)[0] + "/index.html"
    elif "direct1.html" not in path:
        path = path.rsplit("/", 1)[0] + "/direct1.html"
    if door and "door" not in {key.lower() for key in query}:
        query["door"] = [door]
    return urlunsplit((parsed.scheme, parsed.netloc, path,
                       urlencode(query, doseq=True), ""))


def leave_table(driver, wait=20.0):
    """Đưa tab DG về sảnh của chính nó (bỏ ``tableId``), chờ Laya vẽ lại lưới bàn.

    Không trả URL ra ngoài: URL mang token phiên. Chỉ báo trạng thái/đếm bàn.
    """
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi rời bàn DG."}
    try:
        ctx = _dg_context(driver, wait=5.0)
        if ctx is None:
            return {"ok": False, "error": "Chưa thấy màn DG để rời bàn."}
        state = driver.execute_script(_DG_STATE_JS) or {}
        if not state.get("in_table"):
            return {"ok": True, "lobby": True, "in_table": False,
                    "note": "Đã ở sảnh DG sẵn."}
        if ctx["mode"] != "tab":
            # Iframe của site: trả iframe về tài liệu sảnh của chính nó.
            path = tuple(ctx.get("path") or (ctx.get("index"),))
            driver.switch_to.default_content()
            _enter_path(driver, path[:-1])
            index = path[-1]
            lobby_url = _lobby_url_from(ctx.get("location") or "")
            script = ("return (() => { const f = document.querySelectorAll('iframe,frame')[%d];"
                      " if (!f) return {ok: false}; f.src = %s; return {ok: true}; })()"
                      % (index, json.dumps(lobby_url)))
            landed = driver.execute_script(script) or {}
            if not landed.get("ok"):
                return {"ok": False, "error": "Không đưa được iframe DG về sảnh."}
        else:
            lobby_url = _lobby_url_from(ctx.get("location") or "")
            if not navigate_top(driver, lobby_url):
                return {"ok": False, "error": "Không điều hướng được tab DG về sảnh."}
        deadline = time.monotonic() + max(0.0, float(wait))
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if _dg_context(driver, wait=0) is None:
                continue
            probe = driver.execute_script(_DG_STATE_JS) or {}
            if not probe.get("in_table") and (probe.get("lobby") or probe.get("ready")):
                return {"ok": True, "lobby": True, "in_table": False,
                        "tables": int(probe.get("table_cards") or 0),
                        "note": "Đã về sảnh DG."}
        return {"ok": False,
                "error": "Đã bỏ mã bàn nhưng %d giây chưa thấy lại lưới bàn DG." % int(wait)}
    except Exception as exc:
        return {"ok": False, "error": "Không rời bàn DG được (%s)." % type(exc).__name__}


def sync_table(driver, table_id, wait=30.0, settle=120.0, log=None):
    """Đưa profile này vào bàn DG mang table_id (mã thật, vd 60101 = RB01).

    Nạp qua trang chờ direct1.html với tableId thật: game tự vào thẳng bàn.
    Gán thẳng index.html khiến game thoát iframe; mã sảnh (10101) chỉ ra lưới bàn.

    ``log`` (tuỳ chọn) bật chế độ chờ captcha: sảnh DG có thể chặn bằng thanh
    trượt "Xác minh an toàn" (đo trên 888AE66) và khi đó việc nạp bàn im lặng
    thất bại. Không truyền ``log`` để giữ nguyên hành vi cũ cho các caller khác.
    """
    table_id = str(table_id or "").strip()
    if not _is_real_table_id(table_id):
        return {"ok": False, "error": "Mã bàn DG không hợp lệ; dùng mã bàn Baccarat dải 60xxx (ví dụ 60102)."}
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đồng bộ bàn DG."}
    try:
        if log is not None:
            gate = wait_for_captcha(driver, log, timeout=_CAPTCHA_WAIT, poll=2.0)
            if not gate.get("ok"):
                return {"ok": False, "captcha": True, "error": gate.get("error")}
            wait = float(wait) + float(gate.get("waited") or 0)
        ctx = _dg_context(driver, wait)
        if ctx is None:
            return {"ok": False, "error": "Chưa mở game DG trong profile này; bấm chạy DG trước."}
        state = driver.execute_script(_DG_STATE_JS) or {}
        current = (state.get("table_id") or state.get("url_table")
                   or _table_id_from_src(ctx["location"]))
        if current == table_id and state.get("in_table"):
            return {"ok": True, "table_id": table_id, "already": True,
                    "in_table": bool(state.get("in_table")),
                    "note": "Profile đã ở sẵn bàn %s, giữ nguyên phiên game." % table_id}
        if ctx["mode"] == "top":
            # The mobile hand-off page draws the lobby in its own body. If the
            # game still lives in a frame, promote it to the tab URL first so
            # the table can be selected with the DG loader instead of tapping a
            # card that may not be rendered on the phone layout.
            promoted = promote_lobby_to_tab(
                driver, wait=1.5, settle=min(30.0, max(6.0, float(settle))))
            if promoted.get("ok"):
                ctx = _dg_context(driver, wait=2.0) or ctx
                state = driver.execute_script(_DG_STATE_JS) or {}
        if ctx["mode"] == "top":
            # Lobby lives in the page body; there is no direct1.html to rewrite.
            # Tap the table card in the Laya lobby instead.
            name = ""
            for row in (lobby_tables(driver, wait=2.0).get("tables") or []):
                if str(row.get("table_id")) == table_id:
                    name = str(row.get("name") or "")
                    break
            entered = _laya_enter_table(driver, table_id, name)
            if not entered.get("ok"):
                return {"ok": False,
                        "error": "Sảnh DG trên giao diện điện thoại không đổi bàn tự động được "
                                 "(%s); hãy chọn bàn trên màn hình." % (entered.get("reason") or "không rõ")}
        elif ctx["mode"] == "tab":
            new_url = _loader_url(ctx["location"], "", table_id)
            driver.execute_script("location.href = %s;" % json.dumps(new_url))
        else:
            if _lobby_handle(driver) is None:
                return {"ok": False, "error": "Profile cần mở sảnh DG trên site trước khi đồng bộ bàn."}
            path = tuple(ctx.get("path") or (ctx.get("index"),))
            driver.switch_to.default_content()
            _enter_path(driver, path[:-1])
            index = path[-1]
            src = driver.execute_script(
                "return (() => { const f = document.querySelectorAll('iframe,frame')[%d];"
                " return f ? (f.getAttribute('src') || '') : ''; })()" % index) or ""
            new_url = _loader_url(ctx["location"], src, table_id)
            # URL chứa token phiên chỉ nhúng vào JS trong trang, không trả ra ngoài/log.
            script = ("return (() => { const f = document.querySelectorAll('iframe,frame')[%d];"
                      " if (!f) return {ok: false}; f.src = %s; return {ok: true}; })()"
                      % (index, json.dumps(new_url)))
            result = driver.execute_script(script) or {}
            if not result.get("ok"):
                return {"ok": False, "error": "Không đổi được iframe DG của profile này."}
        deadline = time.monotonic() + max(0.0, settle)
        # Mã bàn được đọc từ **view cược** ở mọi chế độ (``view.tableId``), nên
        # không cần phân biệt: bấm thẻ trên bản điện thoại tuy không đổi URL
        # nhưng ``table_id`` vẫn có, còn loader thì có ``tableId`` trong URL.
        announced_captcha = False
        while time.monotonic() < deadline:
            time.sleep(1.0)
            if _dg_context(driver, wait=0) is None:
                continue
            landed = driver.execute_script(_DG_STATE_JS) or {}
            landed_id = str(landed.get("table_id") or landed.get("url_table") or "")
            if landed.get("in_table") and landed_id == table_id:
                return {"ok": True, "table_id": table_id, "in_table": True,
                        "label": landed.get("label") or "",
                        "note": "Đã vào bàn DG %s." % table_id}
            # Captcha có thể hiện **giữa** lúc nạp bàn (đo trên 888AE66): khi đó
            # view cược không bao giờ vẽ ra. Báo một lần và nới hạn chờ để người
            # dùng kịp tự kéo thanh trượt.
            if log is not None and not announced_captcha:
                gate = captcha_state(driver)
                if gate.get("blocked"):
                    announced_captcha = True
                    deadline += _CAPTCHA_WAIT
                    try:
                        log("Sảnh DG đang chặn bằng captcha \"%s\". Hãy tự kéo thanh "
                            "trượt trong cửa sổ Chrome của profile này; tool đang chờ."
                            % (gate.get("text") or "xác minh an toàn"), "action")
                    except Exception:
                        pass
        if log is not None and captcha_state(driver).get("blocked"):
            return {"ok": False, "table_id": table_id, "in_table": False, "captcha": True,
                    "error": "Sảnh DG vẫn đang chờ captcha nên chưa vào được bàn %s; "
                             "hãy kéo thanh trượt trong cửa sổ Chrome rồi chạy lại."
                             % table_id}
        return {"ok": False, "table_id": table_id, "in_table": False,
                "error": "Đã yêu cầu vào bàn %s nhưng DG vẫn chưa xác nhận màn hình bàn sau 120 giây." % table_id}
    except Exception as exc:
        return {"ok": False, "error": "Không đồng bộ được bàn DG (%s)." % type(exc).__name__}
