"""Shared Dream Gaming entry, table selection and betting for casino profiles."""

import json
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode


LOBBY_URL = "https://febet.kiwi/live-casino/baccarat"
_DG_SITE_RULES = {
    "febet": {"label": "FEBET", "keywords": ("dream gaming", "dreamgaming", "dg baccarat"), "menu": ()},
    "e3951": {"label": "E3951", "keywords": ("dream gaming", "dreamgaming", "dg baccarat", "dg live"), "menu": ("live casino", "casino tr\u1ef1c tuy\u1ebfn")},
    "gk881": {"label": "GK881", "keywords": ("dream gaming", "dreamgaming", "dg baccarat", "dg live"), "menu": ("live casino", "s\u1ea3nh casino", "casino tr\u1ef1c tuy\u1ebfn")},
    "vnwtop": {"label": "VNWTop", "keywords": ("dream gaming", "dreamgaming", "dg baccarat", "dg live"), "menu": ("live casino", "casino tr\u1ef1c tuy\u1ebfn")},
    "888ae66": {"label": "888AE66", "keywords": ("dream gaming", "dreamgaming", "dg baccarat", "dg live"), "menu": ("live casino", "casino tr\u1ef1c tuy\u1ebfn")},
    "bum123": {"label": "BUM123", "keywords": ("dream gaming", "dreamgaming", "dg baccarat", "dg live"), "menu": ("live casino", "s\u1ea3nh casino", "casino tr\u1ef1c tuy\u1ebfn")},
}

_DG_PROVIDER_CLICK_JS = r"""
return (() => {
  const norm = value => String(value || '').replace(/[-_./]+/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = e => { const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>8&&r.height>8&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0; };
  const hints = arguments[0] || [];
  const candidates = [...document.querySelectorAll('img,button,a,[role="button"],[class*="cursor-pointer"]')];
  const ranked = [];
  for (const node of candidates) {
    if (!visible(node)) continue;
    const info = norm([node.innerText,node.getAttribute('aria-label'),node.title,node.alt,
      node.getAttribute('src'),node.getAttribute('data-provider'),node.className].join(' '));
    const score = hints.reduce((best,hint) => info.includes(hint) ? Math.max(best,hint.length+10) : best, 0);
    if (!score) continue;
    const target = node.closest('button,a,[role="button"],[class*="cursor-pointer"]') || node;
    if (!visible(target)) continue;
    ranked.push({target,score});
  }
  ranked.sort((a,b)=>b.score-a.score);
  if (!ranked.length) return {found:false};
  const best = ranked[0];
  const tied = ranked.filter(item=>item.score===best.score && item.target!==best.target);
  if (tied.length) return {found:true,ambiguous:true,candidates:ranked.length};
  best.target.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
  best.target.click();
  return {found:true,clicked:true,candidates:ranked.length};
})()
"""

_DG_LAUNCH_BUTTON_JS = r"""
return (() => {
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim().toUpperCase();
  const allowed = new Set(['XEM GAME','PLAY','PLAY NOW','ENTER','ENTER GAME','VÀO GAME','CHƠI NGAY']);
  const visible = e => { const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>8&&r.height>8&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0; };
  const hits = [...document.querySelectorAll('button,a,[role="button"],[class*="cursor-pointer"]')]
    .filter(visible).map(e=>({e,text:norm(e.innerText||e.getAttribute('aria-label')||e.title)}))
    .filter(x=>allowed.has(x.text));
  if (!hits.length) return {clicked:false};
  if (hits.length > 1) {
    const xem = hits.filter(x=>x.text==='XEM GAME');
    if (xem.length === 1) { xem[0].e.click(); return {clicked:true,label:xem[0].text}; }
    return {clicked:false,ambiguous:true};
  }
  hits[0].e.click();
  return {clicked:true,label:hits[0].text};
})()
"""

_DG_CATEGORY_CLICK_JS = r"""
return (() => {
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = e => { const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>12&&r.height>12&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0; };
  const labels = arguments[0] || [];
  const hits = [...document.querySelectorAll('button,a,[role="button"],[class*="cursor-pointer"]')]
    .filter(visible).map(e=>({e,text:norm(e.innerText||e.getAttribute('aria-label')||e.title)}))
    .map(x=>({...x,score:labels.indexOf(x.text)})).filter(x=>x.score>=0)
    .sort((a,b)=>a.score-b.score);
  if (!hits.length) return {clicked:false};
  const best=hits[0], tied=hits.filter(x=>x.score===best.score&&x.e!==best.e);
  if (tied.length) return {clicked:false,ambiguous:true};
  best.e.scrollIntoView({block:'center',inline:'center',behavior:'instant'});
  best.e.click();
  return {clicked:true,label:best.text};
})()
"""
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
        return (parsed.scheme == "https" and parsed.hostname == "febet.kiwi"
                and parsed.path.rstrip("/").endswith("/live-casino/baccarat")
                and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return False


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
        if _lobby_handle(driver) is None:
            driver.switch_to.window(driver.window_handles[-1])
            driver.switch_to.default_content()
            driver.get(LOBBY_URL)
        # Chờ điều hướng mạng chậm; đừng kết luận profile lỗi khi Chrome vừa mở.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if _is_lobby(driver.current_url):
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not _is_lobby(driver.current_url):
            return {"ok": False, "error": "FEBET chưa tải được sảnh Baccarat."}

        if _dg_window(driver) is not None:
            return {"ok": True, "already_open": True, "mode": "tab",
                    "note": "Game DG đã mở ở tab riêng của profile này."}
        existing = inspect(driver)
        if existing.get("ok") and existing.get("loaded"):
            return {"ok": True, "already_open": True, "note": "Iframe game đã mở trong profile này."}
        if _lobby_handle(driver) is None:
            return {"ok": False, "error": "FEBET chưa tải được sảnh Baccarat."}

        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import ElementClickInterceptedException

        image = WebDriverWait(driver, 45).until(lambda current: next((item for item in
            current.find_elements(By.CSS_SELECTOR, 'img[alt="partner"]')
            if "dream-gaming-square.webp" in (item.get_attribute("src") or "").lower()), None))
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
                "clicked_xem_game": False,
                "frames": last.get("frames", []), "options": last.get("options", []),
                "error": "Đã bấm ảnh DG nhưng chưa thấy nút XEM GAME hoặc iframe game trong 120 giây."}
    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return {"ok": False, "error": "Không mở được DG Baccarat (%s)." % type(exc).__name__}


def _click_xem_game(driver):
    """Click the site's explicit XEM GAME action when its balance modal appears."""
    try:
        for button in driver.find_elements("css selector", "button"):
            if not button.is_displayed() or not button.is_enabled():
                continue
            label = re.sub(r"\s+", " ", button.text or "").strip().upper()
            if label == "XEM GAME":
                button.click()
                return True
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
    from selenium.webdriver.common.by import By

    for handle in reversed(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            for frame in frames:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(frame)
                    location = driver.execute_script("return location.href") or ""
                    if "ddnewpc" in location.lower():
                        driver.switch_to.default_content()
                        return handle
                except Exception:
                    continue
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
    """
    from selenium.webdriver.common.by import By

    deadline = time.monotonic() + max(0.0, wait)
    while True:
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        except Exception:
            frames = []
        for index in range(len(frames)):
            location = ""
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frames[index])
                location = driver.execute_script("return location.href") or ""
            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
            # A DG lobby may not have a tableId yet, or may expose only a
            # lobby identifier. Detect the DG document first; validate 60xxx
            # only when selecting a real baccarat table.
            if "ddnewpc" in location.lower():
                return index, location
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
  const scale = rawMin >= 1000 ? 1000 : rawMin > 0 ? 1
    : currency === 'VND' ? 1000 : Number(player.balance || 0) >= 100000 ? 1000 : 0;
  const values = (obj, names) => {
    for (const name of names) if (obj && Number(obj[name]) > 0) return Number(obj[name]);
    return 0;
  };
  const tmp = view.betMoneyTmp || {};
  const real = view.betMoneyTrue || {};
  const denoms = [];
  for (const chip of (view.chipMan?.chipArray || [])) {
    const raw = Number(chip?.chipNum || chip?.value || chip?.amount || 0);
    if (raw > 0 && scale > 0 && Number.isInteger(raw / scale)) denoms.push(raw / scale);
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
    winner, scale,
    min_k:scale ? Math.ceil(rawMin / scale) : 0,
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
  const scale = rawMin >= 1000 ? 1000 : rawMin > 0 ? 1
    : currency === 'VND' ? 1000 : Number(player.balance || 0) >= 100000 ? 1000
    : maxRawChip > 0 && maxRawChip < 1000 ? 1 : 0;
  if (!scale) return {ok:false,error:'Không xác định được đơn vị tiền của bàn DG; đã dừng để tránh đặt sai số tiền.'};
  if (Number(info.stateId ?? info.state ?? view.stateId ?? 0) !== 1
      || Number(info.countDown ?? view.countDown ?? 0) < 5)
    return {ok:false,error:'Bàn chưa mở cược đủ lâu.'};
  const minK = Math.ceil(rawMin / scale);
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
    await sleep(120);
    const after = readTmp(side);
    if (after - before !== denom * scale)
      return {ok:false,staged_k:stagedRaw/scale,error:'Số chip trên ô không tăng đúng mệnh giá; dừng để tránh cược lệch.'};
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
        elif _lobby_handle(driver) is not None:
            index, location = _dg_frame(driver, wait=0)
            if index is not None:
                from selenium.webdriver.common.by import By

                driver.switch_to.default_content()
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
                driver.switch_to.frame(frames[index])
                return {"mode": "iframe", "index": index, "location": location}
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def _click_dg_category(driver, labels):
    from selenium.common.exceptions import WebDriverException

    for path, _info in _frame_contexts(driver):
        try:
            _enter_path(driver, path)
            result = driver.execute_script(_DG_CATEGORY_CLICK_JS, list(labels)) or {}
        except WebDriverException:
            continue
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
        if result.get("clicked"):
            return str(result.get("label") or "")
    return ""


def _click_dg_provider_tile(driver, keywords):
    from selenium.common.exceptions import WebDriverException

    for path, _info in _frame_contexts(driver):
        try:
            _enter_path(driver, path)
            result = driver.execute_script(_DG_PROVIDER_CLICK_JS, list(keywords)) or {}
        except WebDriverException:
            continue
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
        if result.get("ambiguous"):
            return {"ok": False, "ambiguous": True,
                    "error": "Site có nhiều thẻ giống Dream Gaming; không tự chọn để tránh mở nhầm game."}
        if result.get("clicked"):
            return {"ok": True, "clicked": True}
    return {"ok": True, "clicked": False}


def _click_dg_launch_button(driver):
    from selenium.common.exceptions import WebDriverException

    for path, _info in _frame_contexts(driver):
        try:
            _enter_path(driver, path)
            result = driver.execute_script(_DG_LAUNCH_BUTTON_JS) or {}
        except WebDriverException:
            continue
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
        if result.get("ambiguous"):
            continue
        if result.get("clicked"):
            return str(result.get("label") or "")
    return ""


def open_dg_for_site(driver, site_id, wait=120.0):
    """Open the DG Baccarat lobby from a selected casino site, or reuse it if open."""
    site_id = str(site_id or "").strip().lower()
    rule = _DG_SITE_RULES.get(site_id)
    if rule is None:
        return {"ok": False, "error": "Site chưa có cấu hình vào Dream Gaming."}
    if driver is None:
        return {"ok": False, "error": "Mở profile trước khi vào sảnh DG."}
    if site_id == "febet":
        result = open_dream_gaming_baccarat(driver)
        if not result.get("ok"):
            return result
        ready = lobby_tables(driver, wait=min(30.0, wait))
        if not ready.get("ok"):
            return {"ok": False, "error": ready.get("error") or "Sảnh DG của FEBET chưa tải xong."}
        return {**result, "site_id": site_id, "lobby_ready": True}

    initial = lobby_tables(driver, wait=1.0)
    if initial.get("ok"):
        return {"ok": True, "already_open": True, "site_id": site_id,
                "lobby_ready": True, "note": "Sảnh DG đã mở trên profile này."}

    clicked_tile = False
    clicked_launch = False
    clicked_category = False
    last_category_check = 0.0
    deadline = time.monotonic() + max(1.0, float(wait))
    last_error = ""
    while time.monotonic() < deadline:
        if not clicked_tile:
            tile = _click_dg_provider_tile(driver, rule["keywords"])
            if not tile.get("ok"):
                return {**tile, "site_id": site_id}
            clicked_tile = bool(tile.get("clicked"))
            now = time.monotonic()
            if not clicked_tile and rule["menu"] and not clicked_category and now - last_category_check >= 5.0:
                last_category_check = now
                clicked_category = bool(_click_dg_category(driver, rule["menu"]))
                if clicked_category:
                    time.sleep(0.5)
                    continue
        if clicked_tile and not clicked_launch:
            clicked_launch = bool(_click_dg_launch_button(driver))

        ready = lobby_tables(driver, wait=0.25)
        if ready.get("ok"):
            return {"ok": True, "already_open": False, "site_id": site_id,
                    "clicked_provider": clicked_tile, "clicked_launch": clicked_launch,
                    "lobby_ready": True, "tables": ready.get("tables", []),
                    "note": "Đã mở sảnh Dream Gaming từ site profile."}
        last_error = str(ready.get("error") or "")
        time.sleep(0.5)

    if not clicked_tile:
        return {"ok": False, "site_id": site_id,
                "error": "Không tìm thấy thẻ Dream Gaming trên site này. Hãy kiểm tra đăng nhập/trang game và thử lại."}
    return {"ok": False, "site_id": site_id,
            "error": last_error or "Đã chọn Dream Gaming nhưng sảnh chưa tải xong trong thời gian chờ."}


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
            index = ctx["index"]
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
