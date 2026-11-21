"""Shared Dream Gaming entry, table selection and betting for casino profiles."""

import json
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode


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
                for path, info in _frame_contexts(driver):
                    location = str(info.get("url") or "")
                    if "ddnewpc" in location.lower():
                        driver.switch_to.default_content()
                        return path, location
                driver.switch_to.default_content()
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return None, None
        time.sleep(0.5)


# DG vẽ sảnh và bàn bằng LayaAir (canvas): phân biệt trạng thái qua tên node —
# sảnh lưới bàn có thẻ enterMC, bàn thật có cửa cược Banker/Player hiện rõ.
_DG_STATE_JS = """
return (() => {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready: false};
  let lobby = false, inTable = false, label = '';
  const walk = (n, d) => {
    if (d > 10) return;
    const name = String(n.name || '');
    if (name === 'enterMC') lobby = true;
    if (name.toLowerCase() === 'banker' && n.visible) inTable = true;
    const t = typeof n.text === 'string' ? n.text.trim() : '';
    if (!label && t && t.length <= 30 && /(RB|S|SB)[0-9]+/.test(t)) label = t;
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  return {ready: true, lobby: lobby, in_table: inTable, label: label,
          url_table: (location.href.match(/tableId=([0-9]+)/) || [])[1] || ''};
})()
"""

_DG_BET_STATE_JS = r"""
return (() => {
  if (typeof Laya === 'undefined' || !Laya.stage) return {ready:false};
  let view = null;
  const walk = (node, depth) => {
    if (!node || depth > 60 || view) return;
    if (node.betBtn && (typeof node.betHandler === 'function' || node.betBtnMan
        || node.baccaratLimit || node.tableInfoMan)) { view = node; return; }
    const children = node._children || [];
    for (const child of children) walk(child, depth + 1);
  };
  walk(Laya.stage, 0);
  if (!view) return {ready:true, in_table:false};
  const info = view.gameInfo || view.tableInfoMan?.gameInfo || window.gameInfo || {};
  const player = view.playerInfo || window.playerInfo || {};
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
  const scale = floorRaw >= 1000 ? 1000 : floorRaw > 0 ? 1
    : currency === 'VND' || Number(player.balance || 0) >= 100000 ? 1000
    : maxRawChip >= 1000 ? 1000 : maxRawChip > 0 ? 1 : 0;
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
    table_id:(location.href.match(/tableId=([0-9]+)/) || [])[1] || '',
    round_id:roundId, state_id:stateId, countdown,
    bet_open:stateId === 1 && countdown >= 5,
    winner, scale, raw_min:rawMin, screen_floor:screenFloor,
    floor_source:screenFloor >= 80 ? 'table-info' : rawMin > 0 ? 'baccarat-limit' : 'fallback',
    min_k:scale ? Math.ceil(floorRaw / scale) : 0,
    max_k:scale && rawMax ? Math.floor(rawMax / scale) : 0,
    balance_k:scale ? Number(player.balance || 0) / scale : null,
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
  const scale = floorRaw >= 1000 ? 1000 : floorRaw > 0 ? 1
    : currency === 'VND' || Number(player.balance || 0) >= 100000 ? 1000
    : maxRawChip >= 1000 ? 1000 : maxRawChip > 0 ? 1 : 0;
  if (!scale) return {ok:false,error:'Không xác định được đơn vị tiền của bàn DG; đã dừng để tránh đặt sai số tiền.'};
  if (Number(info.stateId ?? info.state ?? view.stateId ?? 0) !== 1
      || Number(info.countDown ?? view.countDown ?? 0) < 5)
    return {ok:false,error:'Bàn chưa mở cược đủ lâu.'};
  const minK = Math.ceil(floorRaw / scale);
  const maxK = rawMax > 0 ? Math.floor(rawMax / scale) : 0;
  if (minK && amountK < minK) return {ok:false,error:`Mức ${amountK}k thấp hơn sàn bàn ${minK}k.`};
  if (maxK && amountK > maxK) return {ok:false,error:`Mức ${amountK}k vượt trần bàn ${maxK}k.`};
  const balK = Number(player.balance || 0) / scale;
  if (Number.isFinite(balK) && balK > 0 && amountK > balK)
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
  const invokeOnce = (node, args) => {
    if (node?.clickHandler && typeof node.clickHandler.run === 'function') { node.clickHandler.run(); return true; }
    if (node?.clickHandler && typeof node.clickHandler.runWith === 'function') { node.clickHandler.runWith(args); return true; }
    if (node && typeof node.event === 'function') { node.event('mousedown');node.event('mouseup');node.event('click');return true; }
    return false;
  };
  const chipValue = (chip) => Number(chip?.chipNum||chip?.value||chip?.amount||0);
  let stagedRaw = 0;
  for (const denom of best[amountK].sort((a,b)=>b-a)) {
    const chip = chips.find(c=>chipValue(c) === denom * scale);
    if (!chip || !invokeOnce(chip,[chip]))
      return {ok:false,staged_k:stagedRaw/scale,error:'Không kích hoạt được chip; dừng, không thử click lại.'};
    await sleep(80);
    const selected = view.chipMan?.selectChip || view.chipMan?.curChip;
    const selectedRaw = Number(selected?.chipNum||selected?.value||selected?.amount||player.selectChip||0);
    if (selected !== chip && selectedRaw !== denom * scale)
      return {ok:false,staged_k:stagedRaw/scale,error:'Không xác nhận được mệnh giá chip đang chọn; dừng trước khi đặt.'};
    const before = readTmp(side);
    if (!invokeOnce(spot,[spot]))
      return {ok:false,staged_k:stagedRaw/scale,error:'Không kích hoạt được ô cược; dừng, không click lại.'};
    const expectedDelta = denom * scale;
    const verifyDeadline = Date.now() + 2000;
    let after = readTmp(side);
    while (after - before !== expectedDelta && Date.now() < verifyDeadline) {
      await sleep(100);
      after = readTmp(side);
    }
    if (after - before !== expectedDelta) {
      const detail = `cần +${denom}k; đọc được +${((after-before)/scale).toFixed(3)}k `
        + `(ô ${ (before/scale).toFixed(3)}→${(after/scale).toFixed(3)}k, scale=${scale})`;
      return {ok:false,staged_k:stagedRaw/scale,
        error:`Số chip trên ô không tăng đúng mệnh giá sau khi chờ cập nhật; đã dừng, không bấm lại (${detail}).`};
    }
    stagedRaw += denom * scale;
  }
  if (stagedRaw !== amountK * scale)
    return {ok:false,staged_k:stagedRaw/scale,error:'Tổng chip đã xếp không khớp mức yêu cầu.'};
  if (!autoConfirm) return {ok:true,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK};
  const manager = view.betBtnMan || {};
  const confirm = manager.sureBtn || manager.confirmBtn || manager.btnSure || manager.okBtn || manager.btnOk
    || view.sureBtn || view.confirmBtn || view.btnSure || view.okBtn || view.btnOk;
  if (!confirm || !invokeOnce(confirm,[{}]))
    return {ok:false,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK,
      error:'Chip đã xếp nhưng không tìm thấy nút xác nhận; không thử click lại.'};
  await sleep(250);
  const real = view.betMoneyTrue || {};
  const realAmount = readTmp(side) === 0 ? Number(real[side === 'P' ? 'Player' : 'Banker']
    || real[side === 'P' ? 'player' : 'banker'] || 0) : 0;
  if (realAmount < amountK * scale)
    return {ok:false,staged:true,confirmed:false,round_id:roundId,side,amount_k:amountK,
      error:'Chip đã xếp nhưng chưa xác nhận được cược từ trạng thái DG.'};
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
    const name = String(valueOf(objects,
      ['tableName', 'table_name', 'name', 'tableCode', 'code', 'label']));
    if (tableId && /^60\d{3,}$/.test(tableId)
        && (n.tableInfo || n._tableInfo || n.tableData || n._tableData
            || /\b(RB|SB|S)\s*\d+\b/i.test(name))) {
      if (!seen.has(tableId)) {
        seen.add(tableId);
        tables.push({table_id: tableId, name: name.trim(),
                     online: Number(valueOf(objects, ['onlineCount', 'online_count', 'playerCount'])) || 0});
      }
    }
    for (let i = 0; i < (n.numChildren || 0); i++) walk(n.getChildAt(i), d + 1);
  };
  walk(Laya.stage, 0);
  return {ready: true, lobby: tables.length > 0, tables: tables};
})()
"""


def _dg_window(driver):
    """Handle của tab DG riêng — vài account mở game ở tab mới thay vì iframe."""
    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            if "ddnewpc" in (driver.current_url or "").lower():
                return handle
        except Exception:
            continue
    return None


def _dg_context(driver, wait=15.0):
    """Đặt driver vào đúng document DG (tab riêng hoặc iframe của site bất kỳ)."""
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        if _dg_window(driver) is not None:
            location = driver.current_url or ""
            return {"mode": "tab", "location": location}
        else:
            path, location = _dg_frame(driver, wait=0)
            if path is not None:
                _enter_path(driver, path)
                return {"mode": "iframe", "path": path, "location": location}
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def _loader_url(location, src, table_id):
    base = src if "ddnewpc" in (src or "") else location
    parsed = urlsplit(base)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tableId"] = [table_id]
    path = parsed.path
    if "direct1.html" not in path:
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
        table_id = state.get("url_table") or _table_id_from_src(ctx["location"])
        in_table = bool(state.get("in_table")) and _is_real_table_id(table_id)
        return {"ok": True, "mode": ctx["mode"],
                "table_id": table_id,
                "in_table": in_table,
                "lobby": bool(state.get("lobby")) or not in_table,
                "label": state.get("label") or ""}
    except Exception as exc:
        return {"ok": False, "error": "Không đọc được bàn DG (%s)." % type(exc).__name__}


def lobby_tables(driver, wait=25.0):
    """Danh sách bàn thật (tableId 60101…) đọc từ các thẻ sảnh Laya của DG."""
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi quét sảnh DG."}
    try:
        deadline = time.monotonic() + max(0.0, wait)
        last_data = {"ready": False, "tables": []}
        last_state = {}
        while True:
            ctx = _dg_context(driver, wait=min(0.5, max(0.0, deadline - time.monotonic())))
            if ctx is not None:
                last_state = driver.execute_script(_DG_STATE_JS) or {}
                last_data = driver.execute_script(_DG_LOBBY_JS) or last_data
                current_id = str(last_state.get("url_table") or _table_id_from_src(ctx["location"]))
                if last_state.get("in_table") and _is_real_table_id(current_id):
                    return {"ok": True, "in_table": True,
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
            if time.monotonic() >= deadline:
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


def sync_table(driver, table_id, wait=30.0, settle=120.0):
    """Đưa profile này vào bàn DG mang table_id (mã thật, vd 60101 = RB01).

    Nạp qua trang chờ direct1.html với tableId thật: game tự vào thẳng bàn.
    Gán thẳng index.html khiến game thoát iframe; mã sảnh (10101) chỉ ra lưới bàn.
    """
    table_id = str(table_id or "").strip()
    if not _is_real_table_id(table_id):
        return {"ok": False, "error": "Mã bàn DG không hợp lệ; dùng mã bàn Baccarat dải 60xxx (ví dụ 60102)."}
    if driver is None:
        return {"ok": False, "error": "Mở profile Chrome trước khi đồng bộ bàn DG."}
    try:
        ctx = _dg_context(driver, wait)
        if ctx is None:
            return {"ok": False, "error": "Chưa mở game DG trong profile này; bấm chạy DG trước."}
        state = driver.execute_script(_DG_STATE_JS) or {}
        current = state.get("url_table") or _table_id_from_src(ctx["location"])
        if current == table_id and state.get("in_table"):
            return {"ok": True, "table_id": table_id, "already": True,
                    "in_table": bool(state.get("in_table")),
                    "note": "Profile đã ở sẵn bàn %s, giữ nguyên phiên game." % table_id}
        if ctx["mode"] == "tab":
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
        while time.monotonic() < deadline:
            time.sleep(1.0)
            if _dg_context(driver, wait=0) is None:
                continue
            landed = driver.execute_script(_DG_STATE_JS) or {}
            if landed.get("url_table") != table_id:
                continue
            if landed.get("in_table"):
                return {"ok": True, "table_id": table_id, "in_table": True,
                        "label": landed.get("label") or "",
                        "note": "Đã vào bàn DG %s." % table_id}
        return {"ok": False, "table_id": table_id, "in_table": False,
                "error": "Đã yêu cầu vào bàn %s nhưng DG vẫn chưa xác nhận màn hình bàn sau 120 giây." % table_id}
    except Exception as exc:
        return {"ok": False, "error": "Không đồng bộ được bàn DG (%s)." % type(exc).__name__}
