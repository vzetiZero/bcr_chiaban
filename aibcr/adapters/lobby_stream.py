# -*- coding: utf-8 -*-
"""Quét sảnh Baccarat qua luồng WebSocket công khai của chính trang.

Chỉ đọc các message lobby.histories / lobby.historyUpdated (mã bàn + lịch sử cầu),
cuộn danh sách để sảnh tự gửi dữ liệu cho các bàn ngoài màn hình, rồi khôi phục vị trí cuộn.
Khi cần, bấm ô lọc “Ưa thích” và ô bàn bằng chuột người thật (human_mouse.py) để chỉ quét
những bàn đã thích. Không gọi API nội bộ, không đọc cookie/token, không bấm nút cược.
"""

import json
import random
import re
import time
from urllib.parse import urlsplit, urlunsplit

from aibcr.adapters import browser as BR
from aibcr.adapters import human_mouse as HM
from aibcr.adapters import table_bets as TB
from aibcr.adapters import wm as WM

HISTORY_TYPES = ("lobby.histories", "lobby.historyUpdated")
SIDE_BY_COLOR = {"R": "B", "B": "P"}
SPECIAL_IDS = frozenset((
    "LightningBac0001", "XXXtremeLB000001", "NoCommBac0000001", "gwbaccarat000001",
    "Empgwbaccarat001", "PTBaccarat000001", "InsuranceBac0001",
))
MAX_RESULTS = 400
MAX_TIES = 50
SCROLL_STEP = 500
SCROLL_SETTLE = 1.2
MAX_SCROLL_STEPS = 40
# Mỗi bước rời bàn (bấm nút X, đổi hash) có cửa sổ chờ riêng; bước cuối (mở lại URL
# sảnh tổng) dùng trọn wait_seconds vì phải chờ trang tải lại và render danh sách.
RETURN_STEP_WAIT = 8.0
# Hash mặc định của danh sách bàn Baccarat khi hash đang ở màn hình bàn không còn
# tham số nào khác ngoài table_id.
LOBBY_LIST_FRAGMENT = "category=all_games&game=baccarat&see=baccarat"

# Hồ sơ sảnh: AI_BCR chỉ phục vụ Baccarat nên giữ một hồ sơ duy nhất, không có nhánh
# trò khác. Nếu sàn đổi hash danh sách thì chỉ sửa ``fragment`` ở đây.
GAME_BACCARAT = {
    "key": "baccarat",
    "fragment": LOBBY_LIST_FRAGMENT,
    "game_types": ("baccarat", "luckybaccarat"),
}


def game_profile(key="baccarat"):
    """AI_BCR chỉ có Baccarat — luôn trả hồ sơ Baccarat, bỏ qua tên trò lạ."""
    return GAME_BACCARAT



def decode_results(results):
    """Trả về (letters, read_error); không suy đoán khi định dạng lạ."""
    if not isinstance(results, list):
        return "", "Không nhận được lịch sử bàn qua WebSocket."
    letters = ""
    for item in results:
        side = SIDE_BY_COLOR.get(item.get("c")) if isinstance(item, dict) else None
        ties = (item.get("ties") or 0) if isinstance(item, dict) else 0
        pos = item.get("pos") if isinstance(item, dict) else None
        if (not side or not isinstance(ties, int) or isinstance(ties, bool)
                or not 0 <= ties <= MAX_TIES or not isinstance(pos, list) or len(pos) != 2
                or not all(isinstance(p, int) and not isinstance(p, bool) and p >= 0 for p in pos)):
            return "", "Dữ liệu lịch sử không đúng định dạng; không suy đoán kết quả."
        letters += side + "T" * ties
        if len(letters) > MAX_RESULTS:
            return "", "Lịch sử vượt giới hạn %d tay." % MAX_RESULTS
    if results:
        first = results[0]
        head = first.get("pos") if isinstance(first, dict) else None
        if isinstance(head, list) and len(head) == 2 and head != [0, 0]:
            return letters, "Big Road bị cắt đầu; không đủ lịch sử để chọn bàn."
        if isinstance(first, dict) and first.get("ties"):
            return letters, "Ô đầu có hòa: Big Road không cho biết hòa trước hay sau tay đầu."
    return letters, ""


def is_special(table):
    details = (table or {}).get("gameDetails") or {}
    return (bool(((details.get("gameConfig") or {}).get("lightning")))
            or (table or {}).get("id") in SPECIAL_IDS
            or details.get("gameType") not in (None, "baccarat"))


TILES_JS = """(() => {
    const pick = () => {
        let n = document.querySelector('[data-role="table-tile"]');
        while (n) {
            const st = getComputedStyle(n);
            if (/(auto|scroll)/.test(st.overflowY) && n.scrollHeight > n.clientHeight + 20) return n;
            n = n.parentElement;
        }
        return document.scrollingElement;
    };
    const tableOf = (tile) => {
        const key = Object.keys(tile).find((n) => n.startsWith('__reactFiber$'));
        let f = key ? tile[key] : null;
        while (f && !(f.memoizedProps && f.memoizedProps.table && f.memoizedProps.table.gameDetails)) f = f.return;
        return f || null;
    };
    const historyOf = (fiber) => {
        const stack = [fiber];
        for (let seen = 0; stack.length && seen < 4000; seen++) {
            const f = stack.pop();
            const p = f.memoizedProps || {};
            if (Array.isArray(p.history) && p.type === 'BaccaratHistoryRoadTypeBig') return p.history;
            if (f.child) stack.push(f.child);
            if (f.sibling) stack.push(f.sibling);
        }
        return null;
    };
    // Sảnh bản mới đánh dấu bàn đã thích ngay trong ô bàn (svg data-role favoriteFilled/
    // favoriteEmpty, hoặc data-active trên nút sao), nên đọc ở đây là đủ, không cần bấm
    // ô lọc nào. Chỉ dùng selector CSS thường: thuộc tính có dấu ':' như xlink:href làm
    // querySelectorAll ném SyntaxError và cả đoạn script đọc bàn sẽ hỏng.
    const favOf = (tile) => {
        const star = tile.querySelector('[data-role="table-favorite-icon"], [data-role="hero-favorite-button"]');
        if (!star) return null;
        if (star.hasAttribute('data-active')) return star.getAttribute('data-active') === 'true';
        const marks = [...star.querySelectorAll('svg')].map((s) => s.getAttribute('data-role'));
        if (marks.includes('favoriteFilled')) return true;
        if (marks.includes('favoriteEmpty')) return false;
        return null;
    };
    return {tiles: [...document.querySelectorAll('[data-role="table-tile"]')].map((tile) => {
        const fiber = tableOf(tile);
        const table = (fiber && fiber.memoizedProps.table) || {};
        return {id: typeof table.id === 'string' ? table.id : '', title: typeof table.title === 'string' ? table.title : '',
                game_type: (table.gameDetails || {}).gameType || '',
                lightning: !!(table.gameDetails || {}).gameConfig?.lightning,
                favorite: favOf(tile),
                road: fiber ? historyOf(fiber) : null,
                top: Math.round(tile.getBoundingClientRect().top)};
    }).filter((r) => r.id), scroll: (() => { const sc = pick(); return {top: sc.scrollTop, max: sc.scrollHeight, client: sc.clientHeight}; })()};
})()"""

# ---------------------------------------------------------------- Petalive (site hiện tại)
# Sảnh Petalive không phát lobby.histories qua WebSocket và không dùng data-role="table-tile".
# Mỗi ô bàn là một React component với props.id / props.name; cầu được vẽ sẵn trong
# .live-games-result-grid-board-baccarat__cell.bead-road (chữ B/P/T). Đọc thẳng DOM ô bàn
# và bấm ô bằng chuột thật — cùng cơ chế với EVO, chỉ khác selector.
PETALIVE_ROOM_SELECTOR = ".live-games-lobby-room.live-games-lobby-room-baccarat"
PETALIVE_SCROLL_SELECTOR = ".wui-live-games-layout__body-container"
PETALIVE_TILES_JS = """(() => {
    const rooms = [...document.querySelectorAll(%s)];
    const scroller = (() => {
        const hint = document.querySelector(%s);
        if (hint && /(auto|scroll)/.test(getComputedStyle(hint).overflowY)) return hint;
        let n = rooms[0] || null;
        while (n) {
            if (/(auto|scroll)/.test(getComputedStyle(n).overflowY)) return n;
            n = n.parentElement;
        }
        return document.scrollingElement;
    })();
    const tiles = rooms.map((room) => {
        const fk = Object.keys(room).find((k) => k.startsWith('__reactFiber$'));
        let f = fk ? room[fk] : null, props = null;
        while (f && !props) {
            const q = f.memoizedProps || {};
            if (typeof q.id === 'string' && q.gameId === 'BCR') props = q;
            f = f.return;
        }
        const board = room.querySelector('.live-games-lobby-room__result-board');
        const beads = board
            ? [...board.querySelectorAll('.live-games-result-grid-board-baccarat__cell.bead-road')]
            : [];
        // Bead-road xếp theo CỘT, mỗi cột 6 hàng từ trên xuống: sort theo cột rồi hàng,
        // không dùng DOM order vì React có thể render lại ô theo thứ tự khác.
        beads.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return (Math.round(ra.x / 6) - Math.round(rb.x / 6)) || (ra.y - rb.y);
        });
        let letters = '', readError = '';
        for (const cell of beads) {
            // Đọc CHỮ trong ô: class có thể mang thêm player-pair/banker-pair (huy hiệu)
            // nên không được suy từ class — "banker player-pair" vẫn là B.
            const side = (cell.textContent || '').trim().toUpperCase();
            if (side !== 'B' && side !== 'P' && side !== 'T') {
                letters = '';
                readError = 'Cầu bàn có ký hiệu lạ; không suy đoán kết quả.';
                break;
            }
            letters += side;
            if (letters.length > 400) {
                letters = '';
                readError = 'Lịch sử vượt giới hạn 400 tay.';
                break;
            }
        }
        if (!letters && !readError) readError = 'Chưa đọc được cầu trong ô bàn.';
        return {
            id: (props && typeof props.id === 'string') ? props.id : '',
            title: (props && typeof props.name === 'string') ? props.name : '',
            game_type: 'baccarat',
            lightning: false,
            favorite: null,
            letters, read_error: readError,
            top: Math.round(room.getBoundingClientRect().top)
        };
    }).filter((r) => /^[A-Za-z0-9_-]{1,80}$/.test(r.id));
    return {tiles, scroll: {top: scroller.scrollTop, max: scroller.scrollHeight,
                            client: scroller.clientHeight}};
})()""" % (json.dumps(PETALIVE_ROOM_SELECTOR), json.dumps(PETALIVE_SCROLL_SELECTOR))

PETALIVE_SCROLL_JS = """(() => {
    let n = document.querySelector(%s);
    if (!n || !/(auto|scroll)/.test(getComputedStyle(n).overflowY)) {
        n = document.querySelector(%s);
        while (n) {
            if (/(auto|scroll)/.test(getComputedStyle(n).overflowY)) break;
            n = n.parentElement;
        }
    }
    if (!n) return -1;
    n.scrollTop = %d;
    return Math.round(n.scrollTop);
})()"""

PETALIVE_SCROLL_BOX_JS = """(() => {
    let n = document.querySelector(%s);
    if (!n || !/(auto|scroll)/.test(getComputedStyle(n).overflowY)) {
        n = document.querySelector(%s);
        while (n) {
            if (/(auto|scroll)/.test(getComputedStyle(n).overflowY)) break;
            n = n.parentElement;
        }
    }
    if (!n) return null;
    const r = n.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return null;
    return {x: r.x + r.width / 2, y: r.y + r.height / 2,
            width: r.width, height: r.height};
})()"""

PETALIVE_TILE_BOX_JS = """(() => {
    const id = %s;
    let found = null;
    for (const room of document.querySelectorAll(%s)) {
        const fk = Object.keys(room).find((k) => k.startsWith('__reactFiber$'));
        let f = fk ? room[fk] : null;
        while (f) {
            const q = f.memoizedProps || {};
            if (q.id === id && q.gameId === 'BCR') { found = {room, props: q}; break; }
            f = f.return;
        }
        if (found) break;
    }
    if (!found) return {reason: 'tile_not_found'};
    const room = found.room;
    room.scrollIntoView({block: 'center'});
    const rect = room.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return {reason: 'tile_hidden'};
    if (rect.top < 0 || rect.bottom > innerHeight || rect.left < 0 || rect.right > innerWidth) {
        return {reason: 'tile_offscreen'};
    }
    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2,
            title: found.props.name || id};
})()"""


def scroll_js(petalive, top):
    """Chọn JS đặt vị trí cuộn cho sảnh EVO hoặc Petalive."""
    if petalive:
        return PETALIVE_SCROLL_JS % (
            json.dumps(PETALIVE_SCROLL_SELECTOR), json.dumps(PETALIVE_ROOM_SELECTOR), int(top))
    return SCROLL_JS % int(top)


def tiles_js(petalive):
    """JS liệt kê ô bàn của sảnh EVO hoặc Petalive."""
    return PETALIVE_TILES_JS if petalive else TILES_JS


def tile_box_js(petalive, table_id):
    """JS tìm toạ độ ô bàn theo mã; Petalive khớp props.id thay vì data-role."""
    if petalive:
        return PETALIVE_TILE_BOX_JS % (
            json.dumps(table_id), json.dumps(PETALIVE_ROOM_SELECTOR))
    return TILE_BOX_JS % json.dumps(table_id)


def scroll_box_js(petalive):
    """JS đo hộp khung cuộn của sảnh EVO hoặc Petalive."""
    if petalive:
        return PETALIVE_SCROLL_BOX_JS % (
            json.dumps(PETALIVE_SCROLL_SELECTOR), json.dumps(PETALIVE_ROOM_SELECTOR))
    return SCROLL_BOX_JS


SCROLL_JS = """(() => {
    let n = document.querySelector('[data-role="table-tile"]');
    while (n) {
        const st = getComputedStyle(n);
        if (/(auto|scroll)/.test(st.overflowY) && n.scrollHeight > n.clientHeight + 20) {
            n.scrollTop = %d;
            return Math.round(n.scrollTop);
        }
        n = n.parentElement;
    }
    return -1;
})()"""

# Hộp (x, y, width, height) của khung cuộn danh sách bàn, để đặt chuột vào giữa
# trước khi lăn thật — không lăn tại một điểm cố định ngoài danh sách.
SCROLL_BOX_JS = """(() => {
    let n = document.querySelector('[data-role="table-tile"]');
    while (n) {
        const st = getComputedStyle(n);
        if (/(auto|scroll)/.test(st.overflowY) && n.scrollHeight > n.clientHeight + 20) {
            const r = n.getBoundingClientRect();
            if (r.width < 10 || r.height < 10) return null;
            return {x: r.x + r.width / 2, y: r.y + r.height / 2,
                    width: r.width, height: r.height};
        }
        n = n.parentElement;
    }
    return null;
})()"""

TILE_BOX_JS = """(() => {
    const id = %s;
    const found = [];
    for (const tile of document.querySelectorAll('[data-role="table-tile"]')) {
        const key = Object.keys(tile).find((n) => n.startsWith('__reactFiber$'));
        let f = key ? tile[key] : null;
        while (f && !(f.memoizedProps && f.memoizedProps.table && f.memoizedProps.table.gameDetails)) f = f.return;
        if (!f || f.memoizedProps.table.id !== id) continue;
        found.push({tile, title: f.memoizedProps.table.title || id});
    }
    // Sảnh có thể chưa gắn data-open (markup đổi) hoặc render một bản sao mờ của ô:
    // ưu tiên ô mở được, nhưng vẫn dùng ô khớp id thay vì báo tile_not_found oan.
    if (!found.length) return {reason: 'tile_not_found'};
    const chosen = found.find((m) => m.tile.getAttribute('data-open') === 'true') || found[0];
    const tile = chosen.tile;
    tile.scrollIntoView({block: 'center'});
    const rect = tile.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return {reason: 'tile_hidden'};
    if (rect.top < 0 || rect.bottom > innerHeight || rect.left < 0 || rect.right > innerWidth) {
        return {reason: 'tile_offscreen'};
    }
    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, title: chosen.title};
})()"""


EVO_ENTRY_JS = """(() => {
    if (window !== window.top) return {reason: 'not_top_frame'};
    // Trang vào đổi markup theo thời gian: bản cũ đánh dấu EVO bằng data-subprovider,
    // bản hiện tại bằng data-gp="evo" / data-id="LIVE-EVO" và nút "Bắt đầu" không có class.
    const items = [...document.querySelectorAll(
        '.game-item[data-subprovider="EVO"], .game-item[data-gp="evo"], .game-item[data-id="LIVE-EVO"]')];
    if (!items.length) return {reason: 'evo_item_not_found'};
    const score = (item) => {
        const img = item.querySelector('img');
        const alt = (((img && img.alt) || '')).trim().toLowerCase();
        if (alt === 'evolution') return 0;
        const tags = [item.getAttribute('data-subprovider'), item.getAttribute('data-gp'),
                      item.getAttribute('data-id')].join(' ').toLowerCase();
        return tags.includes('evo') ? 1 : 2;
    };
    const ranked = items.map((item) => ({item, s: score(item)})).sort((a, b) => a.s - b.s);
    if (ranked.length > 1 && ranked[0].s === ranked[1].s) {
        return {reason: 'evo_button_ambiguous', count: ranked.length};
    }
    const item = ranked[0].item;
    // Thẻ ở cuối danh sách chỉ render sau khi cuộn tới, nên phải cuộn rồi mới đo.
    item.scrollIntoView({block: 'center'});
    const inside = (r) => r.width >= 8 && r.height >= 8 && r.x >= 0 && r.y >= 0
                       && r.bottom <= innerHeight && r.right <= innerWidth;
    const center = (r) => ({x: r.x + r.width / 2, y: r.y + r.height / 2});
    const btn = item.querySelector('button.btn-main') || item.querySelector('button');
    if (btn && btn.disabled) return {reason: 'evo_button_not_found'};
    if (btn) {
        btn.scrollIntoView({block: 'center'});
        const rect = btn.getBoundingClientRect();
        // Bản markup cũ để nút "Bắt đầu" hiển thị thì bấm thẳng vào nút.
        if (inside(rect)) return {...center(rect), via: 'button',
                label: (btn.innerText || btn.getAttribute('title') || '').trim().slice(0, 40)};
    }
    const rect = item.getBoundingClientRect();
    // Cửa sổ bị kéo nhỏ hơn thẻ: bấm vào phần thẻ còn nhìn thấy thay vì bỏ cuộc.
    const left = Math.max(rect.x, 0), right = Math.min(rect.x + rect.width, innerWidth);
    const top = Math.max(rect.y, 0), bottom = Math.min(rect.y + rect.height, innerHeight);
    if (right - left < 24 || bottom - top < 24) return {reason: 'evo_button_pending'};
    // Bản markup hiện tại ẩn nút (display:none) nên đích bấm là cả thẻ EVO;
    // góc trên bên phải là ngôi sao yêu thích có onclick riêng nên điểm bấm lệch xuống dưới trái.
    const point = {x: Math.round(left + (right - left) * 0.4), y: Math.round(top + (bottom - top) * 0.62)};
    const hit = document.elementFromPoint(point.x, point.y);
    if (!hit || !item.contains(hit) || hit.closest('.favorite-game-icon-wrapper')) {
        return {reason: 'evo_card_blocked'};
    }
    return {...point, via: 'card', label: item.getAttribute('data-id') || 'EVO'};
})()"""

FAVORITE_JS = """(() => {
    // Ô lọc "Ưa thích" có hai đời markup: bản cũ <li id="favorite"><input id="favorite"
    // type="checkbox"><label>, bản mới là <button data-role="favourites-mobile-button"
    // data-active="false"><span>Yêu thích</span></button> trên thanh đầu trang.
    // Lớp CSS đổi liên tục nên chỉ bám vào id/data-role/label; không bấm vào ngôi sao
    // yêu thích nằm trên từng ô bàn.
    //
    // Sảnh hiện tại render CẢ HAI: li#favorite (desktop, có label bấm được) và nút
    // favourites-mobile-button. Nút mobile không chứa label nên target rơi xuống
    // input#favorite 1×1 px và bị coi là ẩn — vì vậy phải ưu tiên li#favorite trước.
    const usable = (node) => {
        if (!node) return false;
        const r = node.getBoundingClientRect();
        return r.width >= 8 && r.height >= 8;
    };
    let node = document.querySelector('li#favorite');
    if (!usable(node)) {
        const box = document.querySelector('input#favorite[type="checkbox"]');
        if (box && box.closest('li')) node = box.closest('li');
    }
    if (!usable(node)) {
        node = document.querySelector('button[data-role="favourites-mobile-button"], [data-role="favourites-button"]');
    }
    if (!node) {
        node = [...document.querySelectorAll('li,button')].find((candidate) =>
            /^(Ưa thích|Yêu thích|Favorites?)$/i.test((candidate.innerText || '').replace(/\\s+/g, ' ').trim())) || null;
    }
    if (!node) return {reason: 'favorite_filter_not_found'};
    const box = node.querySelector('input[type="checkbox"]') || document.querySelector('input#favorite[type="checkbox"]');
    const label = (box && box.id && node.querySelector('label[for="' + box.id + '"]')) || node.querySelector('label');
    const flag = node.querySelector('[data-selected]') || node.closest('[data-selected]') || node;
    const active = (flag && flag.getAttribute('data-selected') === 'true')
        || (flag && flag.getAttribute('aria-selected') === 'true')
        || (node.getAttribute('data-active') === 'true')
        || (node.getAttribute('aria-pressed') === 'true')
        || !!(box && box.checked);
    // Bấm vào label/nút hiển thị, không bao giờ bấm vào input ẩn 1×1.
    const target = (label && usable(label) ? label : null) || node;
    target.scrollIntoView({block: 'nearest', inline: 'nearest'});
    const rect = target.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return {reason: 'favorite_filter_hidden', active};
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {
        return {reason: 'favorite_filter_offscreen', active};
    }
    const hit = document.elementFromPoint(x, y);
    if (!hit || !node.contains(hit) || hit.closest('.favorite-game-icon-wrapper')) {
        return {reason: 'favorite_filter_blocked', active};
    }
    return {x, y, active, label: (node.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 40)};
})()"""

LOBBY_HEALTH_JS = """(() => {
    const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
    return {
        href: location.href,
        title: document.title,
        ready: document.readyState,
        tiles: document.querySelectorAll('[data-role="table-tile"]').length,
        roads: document.querySelectorAll('[data-role="history-roads"] canvas').length,
        loading: !!document.querySelector('[data-role="loading-screen"], [data-role="loading-bar"]'),
        rooms: document.querySelectorAll('.live-games-lobby-room.live-games-lobby-room-baccarat').length,
        auth: /User authentication failed|your session may be expired|Error Code:\\s*EV\\.7|Bạn đã đăng xuất|You have been logged out/i.test(text),
        launch_failed: /Mở game không thành công|launch game fail/i.test(text),
        body: text.slice(0, 180)
    };
})()"""

# Nút X đóng màn hình bàn của EVO. Chỉ ĐO vị trí chứ không bấm bằng JS: btn.click()
# là sự kiện tổng hợp, site có thể phớt lờ (đúng lỗi "nút đóng bàn không click được").
# Cú bấm thật do _click_close_table gửi qua chuột CDP — cùng đường đã bấm mở ô bàn.
# Kèm frame_offset giống TARGETS_JS của table_bets: nút có thể nằm trong iframe, toạ
# độ đo ở khung nào phải cộng lệch khung đó trước khi bấm theo khung gốc của tab.
CLOSE_TABLE_JS = """(() => {
    const btn = document.querySelector('[data-role="close-button"]');
    if (!btn) return null;
    const r = btn.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    const x = r.x + r.width / 2, y = r.y + r.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (!hit || !btn.contains(hit)) return {reason: 'close_button_blocked'};
    const frameOffset = (() => {
        let x = 0, y = 0, w = window, depth = 0;
        while (w !== w.top) {
            let el = null;
            try { el = w.frameElement; } catch (e) { return null; }
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            const st = w.parent.getComputedStyle(el);
            const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
            x += rect.x + num(st.borderLeftWidth) + num(st.paddingLeft);
            y += rect.y + num(st.borderTopWidth) + num(st.paddingTop);
            w = w.parent;
            depth += 1;
            if (depth > 8) return null;
        }
        return {x: Math.round(x), y: Math.round(y), depth};
    })();
    return {x, y, frame_offset: frameOffset};
})()"""

# Đổi hash về danh sách là điều hướng CÙNG document: SPA sảnh tự route về danh sách
# bàn mà không tải lại trang, nên không bao giờ đụng mục /entry dùng một lần trong
# lịch sử tab (lùi tới đó bằng history.back() là EVO trả EV.7).
LIST_HASH_JS = """(() => {
    location.hash = %s;
    return location.href;
})()"""


def lobby_list_url(url, fragment=None):
    """URL sảnh tổng của chính tab đang mở bàn: giữ origin/path, bỏ table_id.

    Giữ các tham số còn lại của hash/query (category, game, see…) để về đúng chế độ
    xem sảnh người dùng đang dùng; không còn gì thì dùng hash danh sách mặc định
    (``fragment`` truyền vào cho từng trò; mặc định Baccarat).
    """
    parsed = urlsplit(url)
    # Petalive đổi URL path khi vào bàn (/live-games/bcr/<id>), không dùng hash table_id.
    if BR.is_petalive_table_url(url):
        return urlunsplit((parsed.scheme, parsed.netloc, BR.PETALIVE_LOBBY_PATH, "", ""))

    def keep(part):
        return [p for p in part.split("&") if p and p.split("=", 1)[0] != "table_id"]

    default_fragment = fragment or LOBBY_LIST_FRAGMENT
    kept = keep(parsed.fragment)
    fragment_part = "&".join(kept) or default_fragment
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                       "&".join(keep(parsed.query)), fragment_part))


class LobbyStream:
    """Đọc luồng message sảnh qua CDP chỉ đọc trên Chrome đang mở."""

    def __init__(self, session=None, human_mouse=True, game="baccarat"):
        self.session = session or BR.BrowserSession()
        self.profile = game_profile(game)
        self.game = self.profile["key"]
        self.note = ""
        self.last_error = ""
        self.diag = {}
        self.frames = 0
        self.contexts = []
        self.context_frames = {}
        self.histories = {}
        # WM (M88) gửi lịch sử bằng WebSocket nhị phân: tách riêng khỏi histories EVO
        # để hai định dạng không lẫn nhau khi cùng mở nhiều tab.
        self.wm_histories = {}
        self.wm_tables = {}
        self._seq = 0
        self.human_mouse = bool(human_mouse)
        self._cursor = None
        self._cursor_overlay_shown = False
        # True nếu lần bấm gần nhất phải rơi về cú bấm 3-sự-kiện vì HumanMouse lỗi
        # giữa chừng (gói ghost-cursor hỏng, mất kết nối CDP tạm thời...). UI có thể
        # đọc cờ này để biết vì sao chuột ảo không di chuyển cho một cú bấm cụ thể.
        self.last_mouse_fallback = False
        self.rng = random.Random()
        self.session_lost = False
        self.favorite_mode = ""
        # "evo" hoặc "petalive"; đặt lại mỗi lần _lobby_context đọc được danh sách bàn.
        self.lobby_kind = ""

    def _reset(self):
        self.contexts, self.histories, self._seq = [], {}, 0
        self.wm_histories, self.wm_tables = {}, {}
        self.context_frames = {}
        self.frames = 0
        self.diag = {}
        self.last_error = ""
        self.session_lost = False
        self.favorite_mode = ""

    def _evaluate(self, ws, expression, context_id):
        return self._command(ws, "Runtime.evaluate", {
            "expression": expression, "contextId": context_id,
            "returnByValue": True, "silent": True, "timeout": BR.SCRIPT_TIMEOUT * 1000})

    def _command(self, ws, method, params=None):
        self._seq = getattr(self, "_seq", 0) + 1
        ws.send(json.dumps({"id": self._seq, "method": method, "params": params or {}}))
        deadline = time.monotonic() + BR.SCRIPT_TIMEOUT * 3
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("cdp_timeout")
            ws.settimeout(remaining)
            message = json.loads(ws.recv())
            if message.get("method") == "Runtime.executionContextCreated":
                context = message.get("params", {}).get("context", {})
                if (context.get("auxData") or {}).get("isDefault"):
                    self.contexts.append(context["id"])
                    self.context_frames[context["id"]] = (context.get("auxData") or {}).get("frameId")
            if message.get("method") == "Runtime.executionContextDestroyed":
                dead = (message.get("params") or {}).get("executionContextId")
                if dead in self.contexts:
                    self.contexts.remove(dead)
                    self.context_frames.pop(dead, None)
            if message.get("method") == "Runtime.executionContextsCleared":
                self.contexts = []
                self.context_frames = {}
            if message.get("method") == "Network.webSocketFrameReceived":
                self._absorb(message.get("params", {}).get("response", {}))
            if message.get("id") == self._seq:
                if "error" in message:
                    raise RuntimeError("cdp_command_failed")
                return message.get("result", {})

    def _absorb(self, frame):
        if not isinstance(frame, dict):
            return
        if frame.get("opcode") == 2:
            self._absorb_wm(frame)
            return
        if frame.get("opcode") != 1:
            return
        try:
            message = json.loads(frame.get("payloadData", ""))
        except (ValueError, TypeError):
            return
        if not isinstance(message, dict) or message.get("type") not in HISTORY_TYPES:
            return
        args = message.get("args")
        if not isinstance(args, dict):
            return
        rows = args.get("histories") if message["type"] == "lobby.histories" else args
        if not isinstance(rows, dict):
            return
        for table_id, row in rows.items():
            results = row.get("results") if isinstance(row, dict) else None
            if (not isinstance(table_id, str) or not BR.valid_table_id(table_id)
                    or not isinstance(results, list)):
                continue
            current = self.histories.get(table_id)
            if current is None or len(results) >= len(current["results"]):
                self.histories[table_id] = {"results": results, "source": message["type"],
                                            "ts": time.time(), "samples": 1}
            elif self.histories[table_id]["results"] == results:
                self.histories[table_id]["samples"] += 1
            self.histories[table_id]["messages"] = self.histories[table_id].get("messages", 0) + 1

    def _absorb_wm(self, frame):
        """Gom lịch sử WM từ khung nhị phân (protocol 26) và thông tin bàn (21)."""
        message = WM.decode_frame(frame.get("payloadData"), 2)
        if not message:
            return
        protocol = message.get("protocol")
        data = message.get("data")
        if not isinstance(data, dict):
            return
        self.frames += 1
        if protocol == WM.PROTOCOL_HISTORY:
            game, group = data.get("gameID"), data.get("groupID")
            rounds = WM.decode_history(data)
            if game is None or group is None or not rounds:
                return
            key = WM.table_key(game, group)
            current = self.wm_histories.get(key)
            if current is None or len(rounds) >= len(current["rounds"]):
                self.wm_histories[key] = {"rounds": rounds, "ts": time.time(),
                                          "group_type": data.get("groupType"),
                                          "messages": (current or {}).get("messages", 0) + 1}
            else:
                current["messages"] = current.get("messages", 0) + 1
        elif protocol == WM.PROTOCOL_TABLE:
            game, group = data.get("gameID"), data.get("groupID")
            if game is None or group is None:
                return
            self.wm_tables[WM.table_key(game, group)] = WM.decode_table(data)
        elif protocol == WM.PROTOCOL_RESULT:
            game, group = data.get("gameID"), data.get("groupID")
            if game is None or group is None:
                return
            self.wm_tables.setdefault(WM.table_key(game, group), {}).update(
                {"last_round": WM.decode_round(data)})

    def _value(self, ws, expression, context_id):
        return self._evaluate(ws, expression, context_id).get("result", {}).get("value")

    def _try_value(self, ws, expression, context_id):
        """Đọc một khung; iframe đóng giữa chừng không được làm hỏng cả lượt quét."""
        try:
            return self._value(ws, expression, context_id)
        except Exception:
            if context_id in self.contexts:
                self.contexts.remove(context_id)
                self.context_frames.pop(context_id, None)
            return None

    def _dispatch_click(self, ws, x, y):
        """Bấm tối thiểu 3 sự kiện: đường dự phòng khi chuột người thật lỗi."""
        for event in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": event, "x": x, "y": y}
            if event != "mouseMoved":
                params.update(button="left", clickCount=1)
            self._command(ws, "Input.dispatchMouseEvent", params)

    def _click_at(self, ws, x, y):
        """Bấm một điểm bằng chuột người thật; lỗi giữa chừng thì vẫn bấm đúng đích."""
        # Tab ẩn (cửa sổ bị thu nhỏ/che) làm mỗi sự kiện chuột chờ ~5 giây mới trả lời.
        # Đưa tab lên trước để chuột chạy đúng nhịp; lỗi quyền/không hỗ trợ thì bỏ qua.
        try:
            self._command(ws, "Page.bringToFront")
        except Exception:
            pass
        if not self.human_mouse:
            self._dispatch_click(ws, x, y)
            self._cursor = (float(x), float(y))
            return
        try:
            command = lambda method, params=None: self._command(ws, method, params)
            if not self._cursor_overlay_shown:
                # Lớp con trỏ xanh giống mouse_demo.py: chỉ hiển thị, không chiếm
                # quyền chuột hệ điều hành và không đổi dữ liệu gửi đi.
                HM.install_cursor_overlay(command)
                self._cursor_overlay_shown = True
            mouse = HM.HumanMouse(command)
            if self._cursor is not None:
                mouse.last = self._cursor
            mouse.click(x, y)
            self._cursor = (float(x), float(y))
            self.last_mouse_fallback = False
        except Exception:
            # Không để một cú lướt chuột hỏng chặn việc vào bàn. Ghi lại để biết
            # chuột người thật đã tạm rơi về cú bấm 3-sự-kiện cho lượt này — nếu
            # không, "không thấy chuột ảo di chuyển" sẽ không có dấu vết nào để tra.
            self.last_mouse_fallback = True
            self._dispatch_click(ws, x, y)
            self._cursor = (float(x), float(y))

    def _wheel_scroll_to(self, ws, context_id, target_top, box, petalive=False):
        """Cuộn danh sách bàn bằng chuột lăn thật, thay vì gán ``scrollTop`` bằng JS.

        Di chuột (ghost-cursor) tới giữa khung danh sách rồi gửi nhiều cú lăn nhỏ
        qua ``Input.dispatchMouseWheelEvent`` cho tới khi đạt ``target_top`` hoặc hết
        kiên nhẫn — mô phỏng người dùng lăn chuột, không nhảy thẳng một bước lớn.
        Trả vị trí cuộn đọc được cuối cùng (``int``) hoặc ``-1`` nếu hỏng.
        ``petalive=True`` dùng bộ selector cuộn của sảnh Petalive.
        """
        set_js = scroll_js(petalive, target_top)
        if not self.human_mouse or box is None:
            result = self._evaluate(ws, set_js, context_id)
            return result.get("result", {}).get("value", -1)
        command = lambda method, params=None: self._command(ws, method, params)
        if not self._cursor_overlay_shown:
            HM.install_cursor_overlay(command)
            self._cursor_overlay_shown = True
        mouse = HM.HumanMouse(command)
        if self._cursor is not None:
            mouse.last = self._cursor
        px = box["x"] + box["width"] * 0.5
        py = box["y"] + box["height"] * 0.5
        try:
            mouse.move_to(px, py)
            self._cursor = (px, py)
        except Exception:
            pass
        current = self._try_value(ws, scroll_js(petalive, -1), context_id)
        current = current if isinstance(current, (int, float)) else 0
        remaining = float(target_top) - float(current)
        attempts = 0
        # Mỗi cú lăn chỉ đi một đoạn nhỏ (như bàn di chuột thật), tối đa 14 cú mỗi lượt
        # gọi để không treo lâu nếu trang không phản hồi scroll.
        while abs(remaining) > 4 and attempts < 14:
            step = max(-220.0, min(220.0, remaining)) * self.rng.uniform(0.55, 0.95)
            try:
                self._command(ws, "Input.dispatchMouseWheelEvent", {
                    "x": px, "y": py, "deltaX": 0, "deltaY": step})
            except Exception:
                break
            time.sleep(0.03 + 0.03 * random.random())
            current = self._try_value(ws, SCROLL_JS % -1, context_id)
            if not isinstance(current, (int, float)):
                break
            remaining = float(target_top) - float(current)
            attempts += 1
        # Chốt đúng vị trí đích bằng JS: lăn chuột có thể bị trình duyệt làm tròn/giới
        # hạn tốc độ nên không khớp pixel tuyệt đối; việc đọc bảng cầu cần đúng vị trí.
        result = self._evaluate(ws, SCROLL_JS % int(target_top), context_id)
        return result.get("result", {}).get("value", -1)

    @staticmethod
    def _star_favorites(snapshot):
        """id các bàn có sao "đã thích", hoặc None nếu markup ô bàn không lộ trạng thái.

        Trả None là tín hiệu để quay về cách bấm ô lọc cũ; trả tập rỗng nghĩa là sảnh
        đang hiện bàn mà chưa bàn nào được thích, một tình huống có thật.
        """
        rows = (snapshot or {}).get("tiles") or []
        marks = [(row.get("id"), row.get("favorite")) for row in rows if row.get("id")]
        if not marks or all(favorite is None for _, favorite in marks):
            return None
        return {table_id for table_id, favorite in marks if favorite is True}

    def _favorite_state(self, ws, context_id):
        value = self._try_value(ws, FAVORITE_JS, context_id)
        return value if isinstance(value, dict) else {"reason": "favorite_filter_not_found"}

    def _set_favorite_filter(self, ws, context_id, active, wait_seconds=8):
        """Bật/tắt ô lọc “Ưa thích” đúng một lần. Trả (ok, supported, note).

        Sảnh đã ở đúng trạng thái thì không bấm, nhờ vậy quét lại nhiều lượt
        không vô tình tắt bộ lọc của người dùng.
        """
        active = bool(active)
        state = self._favorite_state(ws, context_id)
        reason = state.get("reason")
        if reason == "favorite_filter_not_found":
            return False, False, "Không thấy ô lọc “Ưa thích” trên sảnh."
        # Đã ở đúng trạng thái thì không cần bấm, kể cả khi nút đang bị ẩn.
        if bool(state.get("active")) == active:
            return True, True, ""
        if reason:
            return False, True, "Không bấm được ô lọc “Ưa thích” (%s)." % reason
        try:
            self._click_at(ws, float(state["x"]), float(state["y"]))
        except Exception:
            return False, True, "Không bấm được ô lọc “Ưa thích” trên sảnh."
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(0.4)
            state = self._favorite_state(ws, context_id)
            if not state.get("reason") and bool(state.get("active")) == active:
                # Danh sách bàn cần một nhịp render lại sau khi đổi bộ lọc.
                time.sleep(0.8)
                return True, True, ""
        return (False, True, "Đã bấm “Ưa thích” nhưng sảnh chưa %s bộ lọc sau %d giây." % (
            "bật" if active else "tắt", wait_seconds))

    def _lobby_context(self, ws):
        """Tìm khung đang render danh sách bàn — EVO, Petalive hoặc WM."""
        for context_id in list(self.contexts):
            value = self._try_value(ws, TILES_JS, context_id)
            if isinstance(value, dict) and value.get("tiles"):
                self.frames += 1
                self.lobby_kind = "evo"
                return context_id, value
            value = self._try_value(ws, PETALIVE_TILES_JS, context_id)
            if isinstance(value, dict) and value.get("tiles"):
                self.frames += 1
                self.lobby_kind = "petalive"
                return context_id, value
            value = self._try_value(ws, WM.WM_TILES_JS, context_id)
            if isinstance(value, dict) and value.get("tiles"):
                self.frames += 1
                self.lobby_kind = "wm"
                return context_id, value
        return None, None

    def _wait_lobby_context(self, ws, seconds=25.0):
        """Vừa mở tab là SPA còn đang tải danh sách bàn; chỉ bỏ cuộc khi hết thời gian chờ."""
        deadline = time.monotonic() + seconds
        while True:
            context_id, snapshot = self._lobby_context(ws)
            if context_id is not None or time.monotonic() >= deadline:
                return context_id, snapshot
            if not self.contexts:
                # Chưa có context nào: gửi một lệnh rẻ để đọc tiếp sự kiện context mới
                # (iframe sảnh vừa render lại sau khi thoát bàn).
                try:
                    self._command(ws, "Runtime.evaluate", {
                        "expression": "1", "returnByValue": True, "silent": True})
                except Exception:
                    pass
            time.sleep(1.5)

    def _sweep_petalive(self, ws, context_id, snapshot, max_seconds, favorites_only):
        """Quét sảnh Petalive: cầu nằm sẵn trong ô bàn, không có WebSocket lobby.histories.

        Khác EVO ở ba điểm: selector ô bàn, nguồn cầu (DOM thay vì WS) và cờ Ưa thích
        (sảnh này không có). Phần còn lại — cuộn chuột thật, gom mọi vị trí cuộn, khôi
        phục vị trí — giữ nguyên để không lỡ bàn ngoài khung nhìn.
        """
        if favorites_only:
            self.favorite_mode = "unsupported"
        deadline = time.monotonic() + max_seconds
        start_top = snapshot["scroll"]["top"]
        scroll_box = self._try_value(ws, scroll_box_js(True), context_id)
        scroll_box = scroll_box if isinstance(scroll_box, dict) else None
        steps, position, stagnant = 0, 0, 0
        seen, tiles = set(), {}
        while time.monotonic() < deadline and steps < MAX_SCROLL_STEPS:
            self._wheel_scroll_to(ws, context_id, position, scroll_box, petalive=True)
            time.sleep(SCROLL_SETTLE)
            result = self._evaluate(ws, PETALIVE_TILES_JS, context_id)
            snapshot = result.get("result", {}).get("value") or snapshot
            for tile in snapshot.get("tiles", []):
                if tile.get("id"):
                    tiles[tile["id"]] = tile
            ids = {tile["id"] for tile in snapshot.get("tiles", [])}
            bottom = max(snapshot["scroll"]["max"] - snapshot["scroll"]["client"], 0)
            stagnant = 0 if (ids - seen or position < bottom) else stagnant + 1
            seen |= ids
            if stagnant >= 2:
                break
            position = min(position + SCROLL_STEP, bottom)
            steps += 1
        self._wheel_scroll_to(ws, context_id, start_top, scroll_box, petalive=True)
        if not tiles:
            self.diag = {"tiles_in_dom": 0, "scroll_steps": steps,
                         "favorites_only": bool(favorites_only), "lobby": "petalive"}
            self.last_error = ("Sảnh Petalive chưa hiển thị ô bàn sau %d giây; hãy đợi trang tải "
                               "xong rồi quét lại." % int(max_seconds))
            return []
        rows = []
        for table_id, tile in tiles.items():
            letters = tile.get("letters") or ""
            rows.append({
                "table_id": table_id,
                "label": tile.get("title") or table_id,
                "letters": letters,
                "game_type": "baccarat",
                "read_error": tile.get("read_error") or "",
                "source": "petalive-board",
                "ws_hands": len(letters),
                "road_match": True,  # cầu trên ô bàn là nguồn duy nhất của sảnh này
                "observed_at": time.time(),
                "messages": 1,
                "favorite": False,
            })
        rows.sort(key=lambda r: r["label"].casefold())
        self.diag = {"tiles_in_dom": len(tiles), "ws_tables": len(rows),
                     "scroll_steps": steps, "matched_road": len(rows),
                     "favorites_only": bool(favorites_only), "favorite_mode": self.favorite_mode,
                     "lobby": "petalive"}
        self.note = "Quét %d bước cuộn · %d bàn Petalive · cầu đọc từ ô bàn." % (steps, len(rows))
        return rows

    def _sweep_wm(self, ws, context_id, snapshot, max_seconds, favorites_only):
        """Quét sảnh WM: ô bàn đọc từ DOM, cầu/lá bài đọc từ protocol 26.

        Sảnh WM đẩy ``protocol 26`` (lịch sử + danh sách lá) cho mọi bàn đang hiển thị
        qua WebSocket nhị phân. Không có khái niệm bàn Ưa thích nên cờ đó bị bỏ qua và
        ghi rõ trong ``diag`` để UI không báo nhầm là đã lọc.
        """
        if favorites_only:
            self.favorite_mode = "unsupported"
        tiles = {tile["section"]: tile for tile in snapshot.get("tiles", []) if tile.get("section")}
        if not tiles:
            self.last_error = ("Sảnh WM chưa hiển thị ô bàn nào; hãy đợi trang tải xong rồi "
                               "quét lại.")
            return []
        keys = {WM.table_key(tile["game"], tile["group"]) for tile in tiles.values()}
        scroll = snapshot.get("scroll") or {}
        start_top = int(scroll.get("top") or 0)
        bottom = max(int(scroll.get("max") or 0) - int(scroll.get("client") or 0), 0)
        # Sảnh đẩy lịch sử theo nhịp riêng (vài giây/lượt) nên phải chờ; đồng thời lăn
        # danh sách để các ô ngoài khung nhìn cũng được cập nhật. Sảnh có thể render lại
        # danh sách giữa chừng (context chết) — lấy lại context thay vì bỏ cả lượt quét.
        position, steps, passes = 0, 0, 0
        deadline = time.monotonic() + max(10.0, min(float(max_seconds), 25.0))
        while time.monotonic() < deadline:
            self._try_value(ws, WM.WM_SCROLL_TO_JS % position, context_id)
            time.sleep(1.2)
            try:
                self._evaluate(ws, "1", context_id)
            except Exception:
                fresh, _ = self._lobby_context(ws)
                if fresh is None:
                    break
                context_id = fresh
            if keys and keys <= set(self.wm_histories):
                break
            if position >= bottom:
                passes += 1
                position = 0
                if passes >= 4:
                    break
            else:
                position = min(position + 400, bottom)
                steps += 1
        self._try_value(ws, WM.WM_SCROLL_TO_JS % start_top, context_id)
        rows = []
        missing = 0
        for tile in tiles.values():
            key = WM.table_key(tile["game"], tile["group"])
            entry = self.wm_histories.get(key) or {}
            rounds = entry.get("rounds") or []
            letters = WM.letters(rounds)
            if not letters:
                # Bàn chưa kịp gửi lịch sử: bỏ khỏi danh sách để không bị chọn nhầm
                # (mở bàn không có cầu thì AI không có gì để phân tích).
                missing += 1
                continue
            label = tile.get("title") or key
            if tile.get("dealer"):
                label = "%s · %s" % (label, tile["dealer"])
            # Chia sẻ lịch sử vừa đọc cho vòng quét bàn (browser.scan) dùng lại: sảnh chỉ
            # gửi protocol 26 mỗi ván một lần nên không thể chờ lại từ đầu trong bàn.
            cache = getattr(self.session, "wm_cache", None)
            if cache is None:
                cache = self.session.wm_cache = {}
            cache[key] = rounds
            rows.append({
                "table_id": key,
                "label": label[:80],
                "letters": letters,
                "game_type": "baccarat",
                "read_error": "",
                "source": "wm-ws-26",
                "ws_hands": len(rounds),
                "road_match": True,
                "observed_at": entry.get("ts") or time.time(),
                "messages": entry.get("messages", 0),
                "favorite": False,
            })
        rows.sort(key=lambda row: row["label"].casefold())
        self.diag = {"tiles_in_dom": len(tiles), "ws_tables": len(rows),
                     "matched_road": len(rows),
                     "favorites_only": bool(favorites_only), "favorite_mode": self.favorite_mode,
                     "lobby": "wm", "scroll_steps": steps}
        if not rows:
            self.last_error = ("Sảnh WM chưa gửi lịch sử bàn nào trong %d giây; hãy đợi "
                               "trang tải xong rồi quét lại." % int(max_seconds))
            return []
        self.note = "Quét sảnh WM · %d bàn có cầu (lá bài đọc từ WebSocket)." % len(rows)
        if missing:
            self.note += " %d bàn chưa kịp gửi lịch sử." % missing
        return rows

    def sweep(self, max_seconds=75, favorites_only=False):
        """Cuộn hết danh sách để sảnh gửi lịch sử mọi bàn, rồi trả về danh sách bàn.

        favorites_only=True: ưu tiên đọc dấu sao "đã thích" trong từng ô bàn và chỉ giữ
        các bàn có sao, không cần bấm gì trên sảnh. Đời markup không có dấu sao trong ô
        bàn thì mới bấm ô lọc “Ưa thích”. Tắt cờ này thì app bấm bỏ lọc (nếu đang bật)
        để không lẫn bàn ngoài danh sách.
        """
        self._reset()
        self.note = ""
        ws = None
        try:
            self._ensure_wm_page()
            page = self.session._cdp_page()
            if page is None:
                self.last_error = "Không có tab sảnh Baccarat trong Chrome CDP 9222."
                return []
            import websocket
            ws = websocket.create_connection(BR.validated_endpoint(page), suppress_origin=True,
                                             timeout=BR.SCRIPT_TIMEOUT, redirect_limit=0,
                                             http_no_proxy=["127.0.0.1", "localhost", "::1"])
            self._command(ws, "Network.enable")
            self._command(ws, "Runtime.enable")
            # WM: đang trong bàn thì iframe sảnh bị che, phải thoát về sảnh trước khi quét.
            wm_state = self._wm_detect(ws)
            if wm_state.get("is_wm") and wm_state.get("kind") == "table":
                ok, note = self._back_to_lobby_wm(ws, wm_state, 20)
                if not ok:
                    self.last_error = note
                    return []
                self.contexts, self.context_frames = [], {}
                self._command(ws, "Runtime.enable")
            context_id, snapshot = self._wait_lobby_context(ws)
            if context_id is None:
                if self._lost_session(ws):
                    return []
                self.last_error = ("Sảnh chưa hiển thị danh sách bàn sau 25 giây chờ; "
                                   "hãy mở lại trang Baccarat.")
                return []
            if self.lobby_kind == "petalive":
                return self._sweep_petalive(ws, context_id, snapshot, max_seconds, favorites_only)
            if self.lobby_kind == "wm":
                return self._sweep_wm(ws, context_id, snapshot, max_seconds, favorites_only)
            star_ids = self._star_favorites(snapshot) if favorites_only else None
            if favorites_only and star_ids is not None:
                self.favorite_mode = "stars"
                if not star_ids:
                    self.last_error = ("Không có bàn nào được đánh dấu Ưa thích trong sảnh; "
                                       "tắt ô “Chỉ bàn Ưa thích” để quét toàn bộ.")
                    return []
            else:
                ok, supported, why = self._set_favorite_filter(ws, context_id, favorites_only)
                if not ok and (favorites_only or supported):
                    self.last_error = why
                    return []
                # Đọc lại sau khi đổi bộ lọc: danh sách và chiều cao cuộn đã khác.
                fresh = self._try_value(ws, TILES_JS, context_id)
                if isinstance(fresh, dict) and fresh.get("tiles"):
                    snapshot = fresh
            deadline = time.monotonic() + max_seconds
            start_top = snapshot["scroll"]["top"]
            scroll_box = self._try_value(ws, SCROLL_BOX_JS, context_id)
            if not isinstance(scroll_box, dict):
                scroll_box = None
            steps = 0
            seen = set()
            tiles = {}
            stagnant = 0
            position = 0
            while time.monotonic() < deadline and steps < MAX_SCROLL_STEPS:
                self._wheel_scroll_to(ws, context_id, position, scroll_box)
                time.sleep(SCROLL_SETTLE)
                result = self._evaluate(ws, TILES_JS, context_id)
                snapshot = result.get("result", {}).get("value") or snapshot
                # Gom qua mọi vị trí cuộn: sảnh chỉ render ô bàn đang nhìn thấy,
                # nên chỉ nhìn khung cuối sẽ mất các bàn ưa thích ở trên.
                for tile in snapshot.get("tiles", []):
                    if tile.get("id"):
                        tiles[tile["id"]] = tile
                ids = {tile["id"] for tile in snapshot["tiles"]}
                bottom = max(snapshot["scroll"]["max"] - snapshot["scroll"]["client"], 0)
                at_bottom = position >= bottom
                # Sảnh bản mới render hết ô bàn ra DOM nên "hết bàn mới" rất nhanh, còn
                # lobby.histories tới qua WebSocket chậm hơn nhiều. Chưa có lịch sử thì
                # chưa được nghỉ sớm, nếu không lượt quét kết thúc sau ~4 giây với 0 bàn.
                stagnant = 0 if (ids - seen or not at_bottom or not self.histories) else stagnant + 1
                seen |= ids
                if stagnant >= 2:
                    break
                position = min(position + SCROLL_STEP, bottom)
                steps += 1
            self._wheel_scroll_to(ws, context_id, start_top, scroll_box)
            favorite_ids = None
            if favorites_only:
                if self.favorite_mode == "stars":
                    favorite_ids = set(star_ids) | {tid for tid, tile in tiles.items()
                                                    if tile.get("favorite")}
                    if not favorite_ids:
                        self.last_error = ("Không có bàn nào được đánh dấu Ưa thích trong sảnh; "
                                           "tắt ô “Chỉ bàn Ưa thích” để quét toàn bộ.")
                        return []
                else:
                    state = self._favorite_state(ws, context_id)
                    if state.get("reason") or not state.get("active"):
                        self.last_error = ("Bộ lọc “Ưa thích” bị tắt giữa lúc quét; bỏ kết quả để "
                                           "tránh lẫn bàn ngoài danh sách.")
                        return []
                    favorite_ids = set(tiles)
            if not self.histories:
                # Sảnh bị site đá ra hộp “Bạn đã đăng xuất”/EV.7 cũng im lặng y hệt trường
                # hợp WebSocket chưa kịp gửi. Phải phân biệt ở đây, nếu không vòng 15 giây
                # cứ cuộn tiếp trên trang chết (đã thấy trong aibcr_trace.jsonl).
                if self._lost_session(ws):
                    return []
                self.diag = {"tiles_in_dom": len(tiles), "ws_tables": 0, "scroll_steps": steps,
                             "favorites_only": bool(favorites_only), "favorite_mode": self.favorite_mode,
                             "favorite_tiles": len(favorite_ids or tiles), "frames": self.frames}
                self.last_error = ("Sảnh không gửi lịch sử bàn qua WebSocket trong %d giây "
                                   "(nhận %d khung, thấy %d ô bàn). Bấm “Nhận tab sảnh” rồi quét lại."
                                   % (int(max_seconds), self.frames, len(tiles)))
                return []
            rows = []
            for table_id, entry in self.histories.items():
                if favorite_ids is not None and table_id not in favorite_ids:
                    continue
                letters, read_error = decode_results(entry["results"])
                tile = tiles.get(table_id)
                road = decode_results(tile["road"])[0] if tile and tile.get("road") is not None else None
                special = is_special({"id": table_id, "gameDetails": {"gameType": (tile or {}).get("game_type") or "baccarat",
                                                                      "gameConfig": {"lightning": (tile or {}).get("lightning")}}})
                if special and not read_error:
                    read_error = "Bàn có luật trả thưởng đặc biệt; chỉ xem cầu, không giả lập theo bàn chuẩn."
                rows.append({
                    "table_id": table_id,
                    "label": (tile or {}).get("title") or table_id,
                    "letters": letters,
                    "game_type": (tile or {}).get("game_type") or "",
                    "read_error": read_error,
                    "source": "evo-ws-" + entry["source"].split(".")[-1],
                    "ws_hands": len(entry["results"]),
                    "road_match": bool(road) and road == letters,
                    "observed_at": entry["ts"],
                    "messages": entry.get("messages", 1),
                    "favorite": table_id in favorite_ids if favorite_ids is not None else False,
                })
            rows.sort(key=lambda r: r["label"].casefold())
            self.diag = {"tiles_in_dom": len(tiles), "ws_tables": len(rows),
                         "scroll_steps": steps, "matched_road": sum(1 for r in rows if r["road_match"]),
                         "favorites_only": bool(favorites_only), "favorite_mode": self.favorite_mode,
                         "favorite_tiles": len(favorite_ids or tiles)}
            self.note = "Quét %d bước cuộn · %d bàn qua WebSocket · %d bàn khớp cầu đang vẽ%s." % (
                steps, len(rows), self.diag["matched_road"],
                " · %d bàn Ưa thích (%s)" % (self.diag["favorite_tiles"], self.favorite_mode)
                if favorites_only else "")
            return rows
        except Exception as exc:
            # Không đưa chi tiết CDP/socket thô vào UI.
            self.last_error = (BR.CDP_CLOSED_NOTE if BR.cdp_port_closed(exc) else
                               "Không quét được luồng sảnh (%s)." % type(exc).__name__)
            return []
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _find_tile_box(self, ws, context_id, table_id, timeout=15.0):
        """Tìm toạ độ ô bàn, cuộn danh sách nếu ô chưa được render.

        Sảnh chỉ render các ô đang nằm trong khung nhìn; lượt quét gom ô ở mọi vị trí
        cuộn rồi trả con trỏ về đầu danh sách. Vì vậy bàn vừa chọn có thể không còn
        trong DOM lúc mở — phải lăn tới đúng chỗ rồi mới đo, thay vì báo tile_not_found
        rồi bỏ bàn oan (4 lần liên tiếp trong aibcr_trace.jsonl).
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        petalive = self.lobby_kind == "petalive"
        box = self._try_value(ws, tile_box_js(petalive, table_id), context_id)
        if isinstance(box, dict) and "x" in box:
            return box
        snapshot = self._try_value(ws, tiles_js(petalive), context_id)
        if not isinstance(snapshot, dict):
            return box
        scroll = snapshot.get("scroll") or {}
        try:
            bottom = max(int(scroll.get("max") or 0) - int(scroll.get("client") or 0), 0)
        except (TypeError, ValueError):
            bottom = 0
        scroll_box = self._try_value(ws, scroll_box_js(petalive), context_id)
        scroll_box = scroll_box if isinstance(scroll_box, dict) else None
        position, steps = 0, 0
        while time.monotonic() < deadline and steps < MAX_SCROLL_STEPS:
            try:
                self._wheel_scroll_to(ws, context_id, position, scroll_box, petalive=petalive)
                time.sleep(SCROLL_SETTLE)
                box = self._try_value(ws, tile_box_js(petalive, table_id), context_id)
            except Exception:
                break
            if isinstance(box, dict) and "x" in box:
                return box
            if position >= bottom:
                break
            position = min(position + SCROLL_STEP, bottom)
            steps += 1
        return box

    def open_table(self, table_id, wait_seconds=25):
        """Mở bàn bằng pointer event thật trên ô bàn của sảnh; không chạm khu vực cược."""
        if not BR.valid_table_id(table_id):
            return False, "Mã bàn không hợp lệ."
        ws = None
        self._reset()
        try:
            self._ensure_wm_page()
            page = self.session._cdp_page()
            if page is None:
                return False, "Không có tab sảnh Baccarat trong Chrome CDP 9222."
            import websocket
            ws = websocket.create_connection(BR.validated_endpoint(page), suppress_origin=True,
                                             timeout=BR.SCRIPT_TIMEOUT, redirect_limit=0,
                                             http_no_proxy=["127.0.0.1", "localhost", "::1"])
            self._command(ws, "Runtime.enable")
            # WM: đang ở bàn khác thì phải thoát về sảnh trước, nếu không ô bàn bị che.
            wm_state = self._wm_detect(ws)
            if wm_state.get("is_wm") and wm_state.get("kind") == "table":
                ok, note = self._back_to_lobby_wm(ws, wm_state, 20)
                if not ok:
                    return False, note
                self.contexts, self.context_frames = [], {}
                self._command(ws, "Runtime.enable")
            context_id, _ = self._lobby_context(ws)
            if context_id is None:
                if self._lost_session(ws):
                    return False, self.last_error
                return False, "Sảnh chưa hiển thị danh sách bàn; hãy mở lại trang Baccarat."
            if self.lobby_kind == "wm":
                return self._open_table_wm(ws, context_id, table_id, wait_seconds)
            # Ô bàn ngoài khung nhìn chưa chắc đã render: dành riêng một cửa sổ để lăn
            # danh sách tìm ô, rồi vẫn giữ trọn thời gian chờ điều hướng sau cú bấm.
            find_timeout = min(15.0, max(3.0, float(wait_seconds) - 8.0))
            box = self._find_tile_box(ws, context_id, table_id, timeout=find_timeout)
            if not isinstance(box, dict) or "x" not in box:
                return False, "Không tìm thấy ô bàn để mở (%s)." % (box or {}).get("reason", "tile_missing")
            self._click_at(ws, box["x"], box["y"])
            deadline = time.monotonic() + max(5.0, float(wait_seconds))
            if self.lobby_kind == "petalive":
                pattern = re.compile(r"/live-games/bcr/%s(?:/|[?#]|$)" % re.escape(table_id))
            else:
                pattern = re.compile(r"[?&#]table_id=%s(?=&|$)" % re.escape(table_id))
            while time.monotonic() < deadline:
                time.sleep(1.5)
                now_url = (self.session._cdp_page() or {}).get("url", "")
                if pattern.search(now_url):
                    return True, "Đã mở bàn %s qua ô bàn của sảnh." % box.get("title", table_id)
                # Bấm ô Petalive có thể mở tab mới thay vì đổi tab hiện tại.
                if self.lobby_kind == "petalive" and any(
                        BR.is_petalive_table_url((page or {}).get("url"))
                        and pattern.search((page or {}).get("url", ""))
                        for page in self.session._cdp_pages()):
                    return True, "Đã mở bàn %s trong tab mới." % box.get("title", table_id)
            return False, "Đã bấm ô bàn nhưng chưa chuyển vào bàn %s." % table_id
        except Exception as exc:
            return False, "Không mở được bàn (%s)." % type(exc).__name__
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _wm_detect(self, ws):
        """Đọc cấu trúc iframe của tab WM ở khung gốc (không cần context của iframe)."""
        return self._wm_eval(ws, WM.WM_DETECT_JS)

    def _wm_eval(self, ws, expression):
        """Chạy JS trong khung gốc của tab (nơi WM đặt nút thoát bàn và hai iframe)."""
        try:
            value = self._command(ws, "Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "silent": True,
                "timeout": BR.SCRIPT_TIMEOUT * 1000}).get("result", {}).get("value")
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _back_to_lobby_wm(self, ws, state, wait_seconds):
        """Rời bàn WM bằng nút thoát ở khung gốc, chờ sảnh hiện lại danh sách bàn."""
        if state.get("kind") != "table":
            self.note = "Đã ở sảnh WM."
            return True, "Đã ở sảnh WM · không cần rời bàn."
        box = self._wm_eval(ws, WM.WM_EXIT_JS)
        if not box or "x" not in box:
            return False, "Không thấy nút thoát bàn của WM (%s)." % (
                (box or {}).get("reason", "exit_missing"))
        self._click_at(ws, float(box["x"]), float(box["y"]))
        deadline = time.monotonic() + max(5.0, float(wait_seconds))
        while time.monotonic() < deadline:
            time.sleep(1.0)
            if self._wm_detect(ws).get("kind") == "lobby":
                self.note = "Đã về sảnh WM."
                return True, "Đã rời bàn · sảnh WM hiển thị lại danh sách bàn."
        return False, "Đã bấm thoát bàn WM nhưng %d giây chưa thấy lại sảnh." % int(wait_seconds)

    def _open_table_wm(self, ws, context_id, table_id, wait_seconds):
        """Mở bàn WM bằng chuột thật trên ô bàn của sảnh rồi chờ iframe bàn hiện ra.

        Ô bàn WM nằm trong iframe_109; iframe này phủ đúng khung nhìn nên toạ độ đo
        trong khung được cộng thêm lệch iframe (JS trả kèm ``x``/``y`` đã cộng lệch).
        """
        parts = WM.parse_table_key(table_id)
        if not parts:
            return False, "Mã bàn WM không hợp lệ."
        prefix = "groupBac_%d_%d_" % parts
        # Sảnh vẽ lại danh sách và gắn lớp hiệu ứng lên ô, nên phải đo → cuộn → bấm
        # theo vòng: bấm xong chưa thấy bàn thì cuộn lại và bấm tiếp, thay vì bỏ cuộc.
        deadline = time.monotonic() + max(8.0, float(wait_seconds))
        box = None
        attempts = 0
        while time.monotonic() < deadline:
            box = self._try_value(ws, WM.WM_TILE_BOX_JS % json.dumps(prefix), context_id)
            if not isinstance(box, dict) or box.get("reason") == "tile_missing":
                fresh, _ = self._lobby_context(ws)
                if fresh is not None:
                    context_id = fresh
                time.sleep(0.5)
                continue
            if box.get("reason"):
                time.sleep(0.5)
                continue
            if not box.get("inside"):
                self._try_value(ws, WM.WM_SCROLL_TO_TILE_JS % json.dumps(prefix),
                                context_id)
                time.sleep(0.5)
                continue
            attempts += 1
            self._click_at(ws, float(box["x"]), float(box["y"]))
            # Chờ bàn hiện ra trong vài giây; chưa lên thì thử lại (tối đa 4 lần).
            settle = time.monotonic() + min(5.0, max(2.0, deadline - time.monotonic()))
            while time.monotonic() < settle:
                if self._wm_detect(ws).get("kind") == "table":
                    self.note = "Đã mở bàn WM %s." % table_id
                    return True, "Đã mở bàn WM %s qua ô bàn của sảnh." % table_id
                time.sleep(0.6)
            if attempts >= 4:
                break
            self._try_value(ws, WM.WM_SCROLL_TO_TILE_JS % json.dumps(prefix), context_id)
            time.sleep(0.4)
        if not isinstance(box, dict) or box.get("reason"):
            return False, "Không tìm thấy ô bàn WM để mở (%s)." % (
                (box or {}).get("reason", "tile_missing"))
        return False, "Đã bấm ô bàn WM %d lần nhưng chưa thấy màn hình bàn %s." % (
            attempts, table_id)

    def _click_close_table(self, ws):
        """Bấm nút X đóng bàn bằng chuột thật ở khung đang vẽ màn hình bàn; True nếu đã bấm.

        Toạ độ đo trong khung nào phải cộng lệch khung đó (bàn có thể nằm trong iframe);
        không đo được lệch thì không bấm liều, đường về URL sảnh tổng phía sau sẽ xử lý.
        Lỗi CDP giữa cú bấm coi như đã bấm: điều hướng thường phá context đang chạy lệnh,
        vòng chờ phía sau xác nhận lại bằng danh sách bàn thật.
        """
        clicked = False
        for context_id in list(self.contexts):
            box = self._try_value(ws, CLOSE_TABLE_JS, context_id)
            if not isinstance(box, dict) or "x" not in box:
                continue
            offset = box.get("frame_offset")
            if offset is None:
                offset = TB.frame_offset_via_cdp(
                    lambda method, params=None: self._command(ws, method, params),
                    self.context_frames.get(context_id))
            point = TB.page_point(box, offset)
            if point is None:
                continue
            try:
                self._click_at(ws, point["x"], point["y"])
                clicked = True
            except Exception:
                clicked = True
        return clicked

    def _assign_list_hash(self, ws, fragment):
        """Đổi hash tab về danh sách bàn (cùng document, không tải lại trang).

        Không truyền contextId: lệnh chạy trong khung gốc của tab — đúng chỗ SPA sảnh
        giữ route. Context chết giữa lệnh (điều hướng phá) thì trả False để bước sau
        mở thẳng URL sảnh tổng.
        """
        try:
            self._command(ws, "Runtime.evaluate", {
                "expression": LIST_HASH_JS % json.dumps(fragment),
                "returnByValue": True, "silent": True, "timeout": BR.SCRIPT_TIMEOUT * 1000})
            return True
        except Exception:
            return False

    def _navigate_to_list(self, ws, list_url):
        """Mở thẳng URL sảnh tổng khi đổi hash không đưa được tab về danh sách.

        Lỗi CDP/errorText không phải án tử: điều hướng có thể phá context chạy lệnh,
        việc thành bại quyết định bằng vòng chờ danh sách bàn render lại phía sau.
        """
        try:
            self._command(ws, "Page.navigate", {"url": list_url})
        except Exception:
            pass

    def _list_is_back(self, ws, wait_seconds):
        """True khi tab hết màn hình bàn VÀ danh sách bàn render lại (thấy ô bàn thật)."""
        deadline = time.monotonic() + wait_seconds
        while True:
            page = self.session._cdp_page() or {}
            now_url = page.get("url", "")
            if (not BR.is_petalive_table_url(now_url)
                    and "table_id" not in urlsplit(now_url).fragment
                    and "table_id=" not in now_url):
                if not self.contexts:
                    self._wait_context(ws)
                if self._lobby_context(ws)[0]:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(1.5)

    def back_to_lobby(self, wait_seconds=25):
        """Rời màn hình bàn về URL sảnh tổng để chọn lại bàn.

        Thứ tự: nút X của EVO (chuột thật) → đổi hash về danh sách (SPA tự route,
        không tải lại trang) → mở thẳng URL sảnh tổng (bỏ table_id). Không dùng
        history.back(): mục lịch sử đầu của tab launch là /entry dùng một lần, lùi
        tới đó là EVO trả "User authentication failed (EV.7)".
        """
        import websocket

        ws = None
        try:
            page = self.session._cdp_page()
            url = (page or {}).get("url", "")
            petalive_table = BR.is_petalive_table_url(url)
            ws = websocket.create_connection(BR.validated_endpoint(page), suppress_origin=True,
                                             timeout=BR.SCRIPT_TIMEOUT, redirect_limit=0,
                                             http_no_proxy=["127.0.0.1", "localhost", "::1"])
            # Context của kết nối trước không dùng được trên kết nối mới; giữ lại chỉ
            # tổ bấm nhầm vào id chết. Runtime.enable gửi lại đủ context thật.
            self.contexts, self.context_frames = [], {}
            self._command(ws, "Runtime.enable")
            # Sảnh WM không có đường dẫn cố định (mirror đổi liên tục): nhận diện bằng
            # hai iframe iframe_109/iframe_101 trước khi áp luật URL của EVO.
            wm_state = self._wm_detect(ws)
            if wm_state.get("is_wm"):
                return self._back_to_lobby_wm(ws, wm_state, wait_seconds)
            if not BR.is_lobby_url(url) and not petalive_table:
                return False, "Không có tab sảnh Baccarat trong Chrome CDP 9222."
            if not self._wait_context(ws):
                return False, "Không lấy được ngữ cảnh trang sảnh để trở về danh sách bàn."
            if petalive_table:
                # Sảnh Petalive route theo path (/live-games/bcr/<id>), không có hash
                # table_id để đổi và không có nút X của EVO: mở thẳng URL sảnh tổng.
                self._navigate_to_list(ws, lobby_list_url(url))
                if self._list_is_back(ws, wait_seconds):
                    self.note = "Đã về danh sách bàn Baccarat."
                    return True, "Đã rời bàn · mở lại sảnh Petalive."
                return False, ("Đã thử mở lại sảnh Petalive nhưng %d giây chưa thấy danh "
                               "sách bàn." % wait_seconds)
            fragment = urlsplit(url).fragment
            if "table_id" not in fragment and "table_id=" not in url:
                self.note = "Đã ở danh sách bàn Baccarat sẵn."
                return True, "Đã ở danh sách bàn · không cần rời bàn."
            list_url = lobby_list_url(url)
            if self._click_close_table(ws) and self._list_is_back(
                    ws, min(RETURN_STEP_WAIT, wait_seconds)):
                self.note = "Đã về danh sách bàn Baccarat."
                return True, "Đã rời bàn · danh sách bàn Baccarat hiển thị trở lại."
            # Nút X không ăn (site đổi markup/chặn cú bấm): đưa tab về URL sảnh tổng.
            if self._assign_list_hash(ws, urlsplit(list_url).fragment) and self._list_is_back(
                    ws, min(RETURN_STEP_WAIT, wait_seconds)):
                self.note = "Đã về danh sách bàn Baccarat."
                return True, "Đã rời bàn · về URL sảnh tổng bằng đổi hash."
            self._navigate_to_list(ws, list_url)
            if self._list_is_back(ws, wait_seconds):
                self.note = "Đã về danh sách bàn Baccarat."
                return True, "Đã rời bàn · mở lại URL sảnh tổng."
            state = self._health(ws)
            if state.get("status") == "auth":
                self.session_lost = True
            return False, (self._health_note(state) if state.get("status") == "auth" else
                           "Đã thử nút X và về URL sảnh tổng nhưng %d giây chưa thấy lại danh sách "
                           "bàn; bấm nút quay lại sảnh của EVO hoặc “Nhận tab sảnh” để thử lại."
                           % wait_seconds)
        except Exception as exc:
            return False, "Không về được danh sách bàn (%s)." % type(exc).__name__
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _wait_lobby_page(self, portal_socket, wait_seconds):
        """Chờ tab sảnh EVO; nếu sảnh nằm trong iframe của trang vào thì nhận ra ở đó.

        Đồng thời đọc trang vào để phát hiện sớm “Mở game không thành công”/EV.7 thay vì
        chờ hết thời gian rồi báo chung chung.
        """
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(1.5)
            try:
                pages = self.session._cdp_pages()
            except Exception:
                continue
            lobby = next((page for page in pages if BR.is_lobby_url(page.get("url"))), None)
            if lobby is not None:
                return lobby, False, {}
            if any(isinstance(page, dict) and page.get("type") == "page"
                   and BR.is_evo_entry_url(page.get("url"))
                   for page in (self.session._last_cdp_targets
                                if isinstance(self.session._last_cdp_targets, list) else [])):
                return None, False, {"status": "auth", "entry": True}
            if not any(BR.is_portal_url(page.get("url")) for page in pages):
                continue  # trang vào đã tự chuyển sang hướng khác; chờ lượt sau.
            try:
                if self._lobby_context(portal_socket)[0] is not None:
                    return None, True, {}
                state = self._health(portal_socket)
                if state.get("status") in ("auth", "launch_failed"):
                    return None, False, state
            except Exception:
                continue
        return None, False, {}

    def _wait_context(self, ws, seconds=6.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.contexts:
            try:
                self._command(ws, "Runtime.evaluate", {"expression": "1", "returnByValue": True})
            except Exception:
                break
        return bool(self.contexts)

    def _health(self, ws):
        """Đọc trạng thái tốt nhất từ các context đang mở của một tab EVO."""
        fallback = {}
        for context_id in list(self.contexts):
            value = self._try_value(ws, LOBBY_HEALTH_JS, context_id)
            if not isinstance(value, dict):
                continue
            if value.get("auth"):
                return dict(value, status="auth")
            if value.get("launch_failed"):
                return dict(value, status="launch_failed")
            if value.get("tiles") or value.get("roads") or value.get("rooms"):
                return dict(value, status="ok")
            if value.get("loading") or not fallback:
                fallback = value
        return dict(fallback, status="loading" if fallback.get("loading") else "unknown")

    def _lobby_status(self, page, wait_seconds=0.0):
        """Một lần đọc ngắn trạng thái tab sảnh: ok/loading/auth/launch_failed/unknown."""
        import websocket

        ws = None
        # Context của tab trước không dùng được trên kết nối mới.
        self.contexts = []
        try:
            ws = websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            self._command(ws, "Runtime.enable")
            if not self._wait_context(ws):
                return {}
            deadline = time.monotonic() + wait_seconds
            while True:
                state = self._health(ws)
                if (state.get("status") in ("ok", "auth", "launch_failed")
                        or time.monotonic() >= deadline):
                    return state
                time.sleep(0.8)
        except Exception:
            return {}
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    @staticmethod
    def _health_note(state):
        status = (state or {}).get("status")
        if status == "auth":
            if state.get("entry"):
                return ("Evolution returned /entry: the launch token was rejected or expired "
                        "(EV.3/EV.7). Sign in again at the portal and open EVO from its game button; "
                        "do not reload or paste /entry.")
            return ("Tab sảnh báo phiên Evolution không còn hiệu lực (EV.7 hay hộp “Bạn đã "
                    "đăng xuất”). Hãy đăng nhập lại ở trang gốc rồi mở lại EVO; app không đổi link sảnh.")
        if status == "launch_failed":
            return ("Trang vào báo “Mở game không thành công”. Site có thể đang bảo trì hoặc tài "
                    "khoản chưa được phép mở EVO; thử lại sau hoặc dùng tài khoản khác.")
        if status == "loading":
            return "Tab sảnh Evolution còn đang tải; chờ vài giây rồi bấm “Quét toàn sảnh”."
        return ""

    def _lost_session(self, ws):
        """Phân biệt "mất phiên thật" với "trang còn đang tải" trước khi bấm tiếp.

        Sảnh đã EV.7 thì mọi cú bấm/ cuộn tiếp theo chỉ ăn nhầm trên trang lỗi, nên
        cờ session_lost bật lên cho app dừng vòng tự động.
        """
        state = self._health(ws)
        if state.get("status") != "auth":
            return False
        self.session_lost = True
        self.last_error = self._health_note(state)
        return True

    def _ensure_wm_page(self):
        """Nhận diện tab WM khi người dùng quét/mở bàn mà chưa bấm “Nhận tab sảnh”."""
        if self.session.wm_page_id:
            return True
        # Kết quả âm được nhớ ngắn: mỗi vòng quét không phải mở CDP dò lại tab cổng.
        if time.time() - getattr(self, "_wm_probe_at", 0.0) < 30.0:
            return False
        self._wm_probe_at = time.time()
        try:
            pages = self.session._cdp_pages()
        except Exception:
            return False
        for page in reversed(pages):
            if BR.is_lobby_url(page.get("url")):
                continue
            state = self._probe_wm(page)
            if not state.get("is_wm"):
                continue
            self.session.wm_page_id = page.get("id")
            self.session.start_wm_watch()
            self.contexts, self.context_frames = [], {}
            return True
        self.contexts, self.context_frames = [], {}
        return False

    def _probe_wm(self, page):
        """Dò nhanh một tab xem có phải sảnh/bàn WM không (mở CDP, đọc iframe, đóng)."""
        import websocket

        ws = None
        try:
            ws = websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            self.contexts, self.context_frames = [], {}
            self._command(ws, "Runtime.enable")
            return self._wm_detect(ws)
        except Exception:
            return {}
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def find_lobby_tab(self):
        """Nhận tab sảnh do người dùng tự mở; app không bấm vào sảnh hộ, không sửa URL.

        Tab mở từ launch của site gắn với một phiên EVO dùng một lần. Đổi hash/URL có
        thể làm EVO tải lại /entry và trả 403/EV.7, nên chỉ đọc và báo trạng thái.
        """
        self._reset()
        try:
            pages = self.session._cdp_pages()
        except Exception as exc:
            if BR.cdp_port_closed(exc):
                return False, BR.CDP_CLOSED_NOTE
            return False, "Không đọc được danh sách tab Chrome CDP 9222 (%s)." % type(exc).__name__
        lobbies = [page for page in pages if (BR.is_lobby_url(page.get("url"))
                                              or BR.is_petalive_table_url(page.get("url")))]
        # Sảnh WM (M88) chạy trong iframe của một tab có URL bất kỳ: dò cấu trúc
        # iframe_109/iframe_101 trước, vì đây là sảnh người dùng đang dùng.
        for page in reversed(pages):
            if BR.is_lobby_url(page.get("url")):
                continue
            state = self._probe_wm(page)
            if not state.get("is_wm"):
                continue
            self.session.wm_page_id = page.get("id")
            self.session.start_wm_watch()
            self.lobby_kind = "wm"
            self.note = "Đã nhận tab sảnh WM."
            if state.get("kind") == "table":
                return True, ("Đã nhận tab sảnh WM · đang ở màn hình bàn; bấm “Quay lại "
                              "sảnh” nếu muốn quét toàn sảnh.")
            return True, "Đã nhận tab sảnh WM · %s" % BR._safe_url(page.get("url"))
        if not lobbies:
            if any(isinstance(page, dict) and page.get("type") == "page"
                   and BR.is_evo_entry_url(page.get("url"))
                   for page in (self.session._last_cdp_targets
                                if isinstance(self.session._last_cdp_targets, list) else [])):
                return False, self._health_note({"status": "auth", "entry": True})
            return False, ("Chưa thấy tab sảnh Baccarat. Hãy tự mở trang cổng của bạn → EVO → Baccarat "
                           "trong cửa sổ Chrome rồi bấm lại nút này.")
        expired = ""
        # Tab vừa launch thường nằm cuối danh sách; thử tab mới trước, bỏ qua tab cũ đã EV.7.
        for lobby in reversed(lobbies):
            state = self._lobby_status(lobby)
            status = state.get("status")
            if status == "auth":
                self.session_lost = True
                expired = self._health_note(state)
                continue
            if status == "launch_failed":
                return False, self._health_note(state)
            url = lobby.get("url", "")
            self.note = "Đã nhận tab sảnh Baccarat."
            if (BR.is_petalive_table_url(url) or "table_id" in urlsplit(url).fragment
                    or "table_id=" in urlsplit(url).query):
                return True, ("Đã nhận tab sảnh Baccarat · đang ở màn hình bàn; bấm “Quay lại "
                              "sảnh” nếu muốn quét toàn sảnh.")
            if status == "loading":
                return True, ("Đã nhận tab sảnh Baccarat · sảnh còn đang tải; chờ vài giây rồi "
                              "bấm “Quét toàn sảnh”.")
            return True, "Đã nhận tab sảnh Baccarat · %s" % BR._safe_url(url)
        return False, expired or ("Tab sảnh báo phiên Evolution không còn hợp lệ. Hãy đăng nhập lại "
                                  "ở trang gốc rồi mở lại EVO; app không đổi link sảnh.")

    def reload_portal(self, wait_seconds=20):
        """Tải lại tab trang vào NEO79 (an toàn: đây là trang thường, không phải /entry).

        Dùng khi sảnh EVO đã bị site đá phiên và nút “Chơi game” không còn mở được tab mới:
        trang vào có thể đã mất trạng thái. Tải lại trang vào lấy lại phiên cổng để lần bấm
        sau mở EVO bằng một launch token mới thay vì lặp lại token cũ đã chết.

        Không đụng tới tab EVO, không sửa URL sảnh, không chạm khu vực cược.
        """
        import websocket

        self._reset()
        ws = None
        try:
            portal = next((page for page in self.session._cdp_pages()
                           if BR.is_portal_url(page.get("url"))), None)
            if portal is None:
                return False, ("Không có tab HTTPS nào để tải lại; hãy mở trang cổng của bạn "
                               "và đăng nhập.")
            ws = websocket.create_connection(
                BR.validated_endpoint(portal), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])
            self._command(ws, "Page.enable")
            self._command(ws, "Page.reload", {"ignoreCache": False})
            ws.close()
            ws = None
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                time.sleep(1.0)
                page = next((p for p in self.session._cdp_pages()
                             if BR.is_portal_url(p.get("url"))), None)
                if page is None:
                    continue
                state = self._lobby_status(page, wait_seconds=2.0)
                status = state.get("status")
                if status == "ok":
                    return True, "Đã tải lại trang vào, phiên cổng còn hiệu lực."
                if status == "auth":
                    return False, ("Tải lại trang vào xong nhưng cổng vẫn báo đăng xuất; "
                                   "hãy đăng nhập lại trên trang cổng rồi thử lại.")
            return True, "Đã tải lại trang vào; nếu nút “Chơi game” vẫn không mở, hãy đăng nhập lại."
        except Exception as exc:
            return False, "Không tải lại được trang vào (%s)." % type(exc).__name__
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def open_lobby_from_portal(self, wait_seconds=30):
        """Bấm “Chơi game” của Evolution trên trang vào và nhận tab sảnh vừa mở.

        Không đổi URL/hash của sảnh sau khi launch: phiên EVO gắn với đúng ngữ cảnh
        mà site vừa mở. Chỉ điều hướng giữa trang vào và sảnh, không chạm khu vực cược.
        """
        import websocket

        def connect(page):
            return websocket.create_connection(
                BR.validated_endpoint(page), suppress_origin=True, timeout=BR.SCRIPT_TIMEOUT,
                redirect_limit=0, http_no_proxy=["127.0.0.1", "localhost", "::1"])

        ws = None
        self._reset()
        try:
            portal = next((page for page in self.session._cdp_pages()
                           if BR.is_portal_url(page.get("url"))), None)
            if portal is None:
                return False, ("Không có tab HTTPS nào đang mở trong Chrome CDP 9222; hãy mở trang "
                               "cổng của bạn, đăng nhập, rồi bấm lại nút này.")
            ws = connect(portal)
            self._command(ws, "Runtime.enable")
            box, reason, deadline = None, "evo_item_not_found", time.monotonic() + wait_seconds
            while box is None:
                # iframe luôn trả not_top_frame; chỉ lý do từ khung chính đáng tin nên vòng
                # retry phải chạy tiếp tới hạn chót, không bỏ cuộc vì một iframe.
                for context_id in list(self.contexts):
                    value = self._try_value(ws, EVO_ENTRY_JS, context_id)
                    if not isinstance(value, dict):
                        continue
                    if "x" in value:
                        box = value
                        break
                    if value.get("reason") != "not_top_frame":
                        reason = value.get("reason", reason)
                if box is not None or time.monotonic() >= deadline:
                    break
                # Trang vào render trễ: thẻ EVO nằm ngoài màn hình nên cần cuộn rồi chờ thêm lượt.
                time.sleep(1.2)
            if box is None:
                return False, "Không bấm được nút “Chơi game” của Evolution (%s)." % reason
            self.diag["evo_click"] = box
            self._click_at(ws, box["x"], box["y"])
            lobby, embedded, failure = self._wait_lobby_page(ws, wait_seconds)
            ws.close()
            ws = None
            if failure:
                return False, self._health_note(failure)
            if embedded:
                self.note = "Sảnh Evolution hiện trong trang vào."
                return True, "Đã vào sảnh qua iframe · bấm “Quét toàn sảnh” để lấy lịch sử bàn."
            if lobby is None:
                return False, ("Đã bấm nhưng %d giây chưa thấy tab sảnh Evolution; "
                               "trang vào có thể đòi đăng nhập trước." % wait_seconds)
            url = lobby.get("url", "")
            self.note = "Đã vào sảnh Evolution."
            if "table_id" in urlsplit(url).fragment or "table_id=" in urlsplit(url).query:
                return True, ("Đã vào sảnh Evolution · đang ở màn hình bàn; bấm nút quay lại "
                              "sảnh của EVO nếu muốn quét toàn sảnh.")
            return True, "Đã vào sảnh Evolution · %s" % BR._safe_url(url)
        except Exception as exc:
            return False, "Không vào được sảnh Evolution (%s)." % type(exc).__name__
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
