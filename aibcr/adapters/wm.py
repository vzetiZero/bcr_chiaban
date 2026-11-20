# -*- coding: utf-8 -*-
"""Đọc sảnh và bàn WM (M88) qua CDP: DOM sảnh + WebSocket nhị phân.

Đã đối chiếu với dữ liệu thật (783 ván, 100% khớp cửa thắng và cờ đôi):

    mã kết quả (protocol 26 ``historyArr``, protocol 25 ``result``)
        bit 0 = Banker thắng, bit 1 = Player thắng, bit 2 = Hoà
        (nên ``code & 3``: 1 = B, 2 = P, 0 = T)
        bit 3 (8) = Banker đôi, bit 4 (16) = Player đôi
        bit 5 (32) = có rút lá thứ 3, bit 6 (64) = không rút lá thứ 3
        bit 7 (128) = Banker natural, bit 8 (256) = Player natural

    id lá bài 1..80, mỗi chất chiếm 20 mã, chỉ dùng 13 mã đầu:
        rank  = (id - 1) % 20 + 1     (1..13 = A,2..10,J,Q,K)
        chất  = (id - 1) // 20        (0..3)
        điểm  = rank nếu rank <= 9, ngược lại 0

    protocol 26 ``historyData.resultObjArr[i].resultContent`` = "b:...;p:..."
        (b = Banker, p = Player; dấu phẩy cuối khi bên đó chỉ có 2 lá)

    protocol 25 ``dtCard``: khoá "1","3","5" là Player, "2","4","6" là Banker.

Mọi hàm ở đây thuần dữ liệu, không mở socket — ``lobby_stream`` và ``browser`` tự
lo phần CDP.
"""

import base64
import json
import re

LOBBY_FRAME = "iframe_109"
TABLE_FRAME = "iframe_101"
FRAME_RE = re.compile(r"iframe_(109|101)/", re.I)
SECTION_RE = re.compile(r"^groupBac_(\d+)_(\d+)_(\d+)$")
TABLE_KEY_RE = re.compile(r"^(\d{1,4})_(\d{1,6})$")

RANK_NAMES = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUIT_NAMES = ("♠", "♥", "♦", "♣")
SIDE_NAME = {"B": "Banker", "P": "Player", "T": "Hoà"}

PROTOCOL_TABLE = 21
PROTOCOL_CARD = 24
PROTOCOL_RESULT = 25
PROTOCOL_HISTORY = 26
PROTOCOL_COUNTDOWN = 38


def valid_card(card_id):
    if isinstance(card_id, bool) or not isinstance(card_id, int):
        return False
    rank = (card_id - 1) % 20 + 1
    return 1 <= card_id <= 80 and rank <= 13


def card_rank(card_id):
    return (int(card_id) - 1) % 20 + 1


def card_suit(card_id):
    return (int(card_id) - 1) // 20


def card_value(card_id):
    rank = card_rank(card_id)
    return rank if rank <= 9 else 0


def card_label(card_id):
    return "%s%s" % (RANK_NAMES[card_rank(card_id) - 1],
                     SUIT_NAMES[card_suit(card_id) % 4])


def canonical_card(card_id):
    """Đổi id WM sang id 1..52 kiểu Petalive (rank-major) để dùng chung bộ bài.

    ``aibcr.live.cards`` xếp id = (rank - 1) * 4 + chất + 1, nên giữ nguyên rank và
    chất là đủ; nhờ vậy shoe/predict của AI đọc đúng điểm và đếm bài còn lại.
    """
    return (card_rank(card_id) - 1) * 4 + (card_suit(card_id) % 4) + 1


def hand_total(cards):
    return sum(card_value(card) for card in cards) % 10


def winner_from_code(code):
    try:
        low = int(code) & 3
    except (TypeError, ValueError):
        return ""
    return "B" if low == 1 else ("P" if low == 2 else "T")


def code_flags(code):
    """Các cờ phụ của một mã kết quả (đôi/natural/lá thứ 3)."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return {}
    return {
        "banker_pair": bool(code & 8),
        "player_pair": bool(code & 16),
        "third_card": bool(code & 32),
        "no_third_card": bool(code & 64),
        "banker_natural": bool(code & 128),
        "player_natural": bool(code & 256),
    }


def table_key(game_id, group_id):
    return "%s_%s" % (int(game_id), int(group_id))


def parse_table_key(key):
    match = TABLE_KEY_RE.match(str(key or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def parse_section_id(section_id):
    match = SECTION_RE.match(str(section_id or ""))
    if not match:
        return None
    return {"section": section_id, "game": int(match.group(1)),
            "group": int(match.group(2)), "type": int(match.group(3))}


def _cards(text):
    out = []
    for part in str(text or "").split(","):
        part = part.strip()
        if part.isdigit():
            card = int(part)
            if valid_card(card):
                out.append(card)
    return out


def decode_result_content(text):
    """``"b:10,29,;p:45,31,"`` -> ``{"banker": [...], "player": [...]}``."""
    result = {"banker": [], "player": []}
    for part in str(text or "").split(";"):
        part = part.strip()
        if part.startswith("b:"):
            result["banker"] = _cards(part[2:])
        elif part.startswith("p:"):
            result["player"] = _cards(part[2:])
    return result


def decode_history(data):
    """Đổi payload protocol 26 thành danh sách ván (cũ → mới) của một bàn."""
    data = data if isinstance(data, dict) else {}
    history = data.get("historyData") if isinstance(data.get("historyData"), dict) else {}
    rows = history.get("resultObjArr") if isinstance(history.get("resultObjArr"), list) else []
    codes = data.get("historyArr") if isinstance(data.get("historyArr"), list) else []
    rounds = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cards = decode_result_content(row.get("resultContent"))
        code = row.get("result")
        if not isinstance(code, int):
            code = codes[index] if index < len(codes) else 0
        if not cards["banker"] or not cards["player"]:
            continue
        flags = code_flags(code)
        rounds.append({
            "game_no": row.get("gameNo"),
            "round": row.get("gameNoRound"),
            "code": code,
            "winner": winner_from_code(code),
            "banker_cards": cards["banker"],
            "player_cards": cards["player"],
            "banker_score": hand_total(cards["banker"]),
            "player_score": hand_total(cards["player"]),
            **flags,
        })
    if rounds:
        return rounds
    # Không có resultObjArr (một số bàn chỉ gửi mảng mã): vẫn trả cửa thắng.
    return [{"code": code, "winner": winner_from_code(code), "banker_cards": [],
             "player_cards": [], "banker_score": None, "player_score": None,
             "game_no": None, "round": None} for code in codes]


def decode_round(data):
    """Đổi payload protocol 25 (ván vừa ngã) thành dict ván đấu."""
    data = data if isinstance(data, dict) else {}
    cards = data.get("dtCard") if isinstance(data.get("dtCard"), dict) else {}
    player, banker = [], []
    for key in ("1", "2", "3", "4", "5", "6"):
        slot = cards.get(key)
        if not isinstance(slot, dict):
            continue
        card = slot.get("cardID")
        if not valid_card(card):
            continue
        (player if key in ("1", "3", "5") else banker).append(int(card))
    code = data.get("result")
    return {
        "game_id": data.get("gameID"),
        "group_id": data.get("groupID"),
        "game_no": data.get("gameNo"),
        "round": data.get("gameNoRound"),
        "code": code,
        "winner": winner_from_code(code),
        "player_cards": player,
        "banker_cards": banker,
        "player_score": data.get("playerScore"),
        "banker_score": data.get("bankerScore"),
        "win_bet_areas": data.get("winBetAreaArr") or [],
        **code_flags(code),
    }


def decode_table(data):
    """Payload protocol 21: thông tin bàn đang mở (mã bàn, tên, giới hạn, pha cược)."""
    data = data if isinstance(data, dict) else {}
    extend = data.get("tableDtExtend") if isinstance(data.get("tableDtExtend"), dict) else {}
    return {
        "game_id": data.get("gameID"),
        "group_id": data.get("groupID"),
        "group_type": data.get("groupType"),
        "game_no": data.get("gameNo"),
        "round": data.get("gameNoRound"),
        "game_stage": data.get("gameStage"),
        "bet_milliseconds": data.get("betMilliSecond"),
        "table_name": extend.get("tableName") or "",
        "min_bet": data.get("tableMinBet"),
        "max_bet": data.get("tableMaxBet"),
        "dealer": data.get("dealerName") or "",
    }


def letters(rounds):
    """Chuỗi B/P/T của danh sách ván (cũ → mới)."""
    return "".join(row.get("winner") or "" for row in (rounds or []) if row.get("winner"))


def merge_result(rounds, round_data):
    """Ghép kết quả ván vừa ngã (protocol 25) vào lịch sử (protocol 26).

    ``protocol 26`` chỉ được sàn đẩy theo nhịp (khoảng 20–30 giây/bàn), trong khi
    ``protocol 25`` tới ngay khi ván kết thúc. Nếu chỉ chờ 26 thì cầu trên UI trễ cả tay
    — đây chính là lý do cầu "đứng im". Hàm này chèn ván mới vào cuối, bỏ qua nếu đã có.
    """
    rounds = list(rounds or [])
    if not isinstance(round_data, dict) or not round_data.get("winner"):
        return rounds
    key = (round_data.get("game_no"), round_data.get("round"))
    for row in rounds:
        if key[0] is not None and (row.get("game_no"), row.get("round")) == key:
            return rounds
        # Protocol 25 không kèm game_no ở một số bàn: so theo bộ lá để tránh trùng.
        if (row.get("banker_cards") == round_data.get("banker_cards")
                and row.get("player_cards") == round_data.get("player_cards")):
            return rounds
    rounds.append({
        "game_no": round_data.get("game_no"),
        "round": round_data.get("round"),
        "code": round_data.get("code"),
        "winner": round_data.get("winner"),
        "banker_cards": round_data.get("banker_cards") or [],
        "player_cards": round_data.get("player_cards") or [],
        "banker_score": round_data.get("banker_score"),
        "player_score": round_data.get("player_score"),
        "source": "ws-25",
    })
    return rounds


def decode_frame(payload_data, opcode=2):
    """Giải một khung WebSocket của WM (nhị phân base64 hoặc text JSON).

    Trả ``dict`` payload gốc (có ``protocol``) hoặc ``None``.
    """
    text = payload_data or ""
    if opcode == 2:
        try:
            text = base64.b64decode(text).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("protocol"), int):
        return None
    return data


# ---------------------------------------------------------------- JS phía sảnh
# Danh sách ô bàn + vùng cuộn. Ô bàn luôn có trong DOM (kể cả ngoài khung nhìn),
# nên quét một lượt là biết đủ bàn; toạ độ chỉ đo khi thật sự cần bấm.
WM_TILES_JS = r"""(() => {
    const tiles = [];
    for (const node of document.querySelectorAll('section.game_list.roomItem')) {
        const m = /^groupBac_(\d+)_(\d+)_(\d+)$/.exec(node.id || '');
        if (!m) continue;
        const nameEl = node.querySelector('[id$="_room-name"]');
        const dealerEl = node.querySelector('.dealer_name');
        const rect = node.getBoundingClientRect();
        tiles.push({
            section: node.id,
            game: parseInt(m[1], 10),
            group: parseInt(m[2], 10),
            type: parseInt(m[3], 10),
            title: ((nameEl && nameEl.textContent) || '').replace(/\s+/g, ' ').trim(),
            dealer: ((dealerEl && dealerEl.textContent) || '').replace(/\s+/g, ' ').trim(),
            visible: rect.width > 0 && rect.height > 0
        });
    }
    const box = document.getElementById('game_list_box');
    return {
        tiles,
        scroll: box ? {top: box.scrollTop, max: box.scrollHeight, client: box.clientHeight} : null,
        href: location.href
    };
})()"""

# Toạ độ bấm ô bàn theo tiền tố id (groupBac_<game>_<group>_).
# Sảnh gắn lớp hiệu ứng (chia bài/hover) đè lên ô nên một điểm duy nhất có thể bị che:
# JS thử nhiều điểm trong ô và trả điểm đầu tiên mà lớp trên cùng vẫn nằm trong ô, kèm
# lệch iframe để bấm đúng toạ độ khung gốc.
WM_TILE_BOX_JS = r"""(() => {
    const prefix = %s;
    let node = null;
    for (const item of document.querySelectorAll('section.game_list.roomItem')) {
        if ((item.id || '').startsWith(prefix)) { node = item; break; }
    }
    if (!node) return {reason: 'tile_missing'};
    const rect = node.getBoundingClientRect();
    let ox = 0, oy = 0, w = window, depth = 0;
    while (w !== w.top) {
        let el = null;
        try { el = w.frameElement; } catch (e) { el = null; }
        if (!el) { ox = oy = 0; break; }
        const fr = el.getBoundingClientRect();
        const st = w.parent.getComputedStyle(el);
        const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
        ox += fr.x + num(st.borderLeftWidth) + num(st.paddingLeft);
        oy += fr.y + num(st.borderTopWidth) + num(st.paddingTop);
        w = w.parent;
        if (++depth > 8) { ox = oy = 0; break; }
    }
    // Thử lần lượt: giữa ô, rồi các điểm lệch (tránh lớp phủ hiệu ứng ở giữa).
    const points = [
        [0.5, 0.5], [0.5, 0.78], [0.22, 0.5], [0.78, 0.5],
        [0.5, 0.25], [0.12, 0.82], [0.88, 0.82]
    ];
    const seen = [];
    for (const [px, py] of points) {
        const x = rect.x + rect.width * px, y = rect.y + rect.height * py;
        if (x <= 0 || y <= 0 || x >= innerWidth || y >= innerHeight) continue;
        const hit = document.elementFromPoint(x, y);
        seen.push((hit && (hit.id || '') + '.' + (hit.className || '').toString().slice(0, 24)) || '');
        if (hit && node.contains(hit)) {
            return {x: x + ox, y: y + oy, w: rect.width, h: rect.height,
                    top: rect.top, bottom: rect.bottom, inside: true,
                    vh: innerHeight, hit: seen[seen.length - 1]};
        }
    }
    return {
        x: rect.x + rect.width / 2 + ox, y: rect.y + rect.height / 2 + oy,
        w: rect.width, h: rect.height, top: rect.top, bottom: rect.bottom,
        inside: false, vh: innerHeight, hits: seen
    };
})()"""

# Đưa ô bàn vào giữa khung danh sách bằng chính thanh cuộn của sảnh (không dùng
# scrollIntoView vì trang cuộn cả khung ngoài và làm lệch toạ độ bấm).
WM_SCROLL_TO_TILE_JS = r"""(() => {
    const prefix = %s;
    let node = null;
    for (const item of document.querySelectorAll('section.game_list.roomItem')) {
        if ((item.id || '').startsWith(prefix)) { node = item; break; }
    }
    const box = document.getElementById('game_list_box');
    if (!node) return -1;
    // Cuộn mọi khung chứa thật sự cuộn được (sảnh có thể lồng nhiều lớp), rồi để
    // scrollIntoView căn giữa — cách này đúng cả khi ô nằm trong cột khác.
    let parent = node.parentElement;
    while (parent) {
        const style = getComputedStyle(parent);
        if (/(auto|scroll)/.test(style.overflowY) && parent.scrollHeight > parent.clientHeight) {
            const pr = parent.getBoundingClientRect(), nr = node.getBoundingClientRect();
            parent.scrollTop = Math.max(0, parent.scrollTop + (nr.top - pr.top)
                                        - (pr.height - nr.height) / 2);
        }
        parent = parent.parentElement;
    }
    try { node.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
    return box ? box.scrollTop : -1;
})()"""

WM_SCROLL_TO_JS = r"""(() => {
    const box = document.getElementById('game_list_box');
    if (!box) return -1;
    box.scrollTop = %d;
    return box.scrollTop;
})()"""

# Nhận diện tab WM ở khung gốc: hai iframe cố định của site. Không dựa vào tên miền
# vì mirror đổi liên tục; chỉ dựa vào cấu trúc iframe_109 (sảnh) / iframe_101 (bàn).
WM_DETECT_JS = r"""(() => {
    const frames = {};
    for (const frame of document.querySelectorAll('iframe')) {
        const src = frame.getAttribute('src') || '';
        // WM may change the iframe URL format between mirrors/releases while
        // keeping the stable iframe_109/iframe_101 DOM ids.
        const idMatch = /^iframe_(109|101)$/.exec(frame.id || '');
        const m = /iframe_(109|101)(?:\/|$|[?#])/.exec(src);
        const frameKind = (idMatch || m || [])[1];
        if (!frameKind) continue;
        const style = getComputedStyle(frame);
        const rect = frame.getBoundingClientRect();
        frames[frameKind] = {
            id: frame.id || '',
            src: src.slice(0, 200),
            display: style.display,
            visible: style.display !== 'none' && style.visibility !== 'hidden'
                     && rect.width > 0 && rect.height > 0
        };
    }
    const lobby = frames['109'] || null;
    const table = frames['101'] || null;
    return {
        is_wm: !!(lobby || table),
        kind: (table && table.visible) ? 'table' : (lobby ? 'lobby' : ''),
        frames,
        href: location.href
    };
})()"""

# Bàn đang mở: khung bàn gắn mã trò + mã bàn vào class của #container
# (``game101 group1355 grouptype86``). Đây là manh mối duy nhất phân biệt bàn đang
# xem với các bàn khác cùng được sảnh đẩy dữ liệu qua WebSocket.
WM_TABLE_KEY_JS = r"""(() => {
    const box = document.getElementById('container');
    if (!box) return null;
    const cls = (box.className || '').toString();
    const game = /(?:^|\s)game(\d+)/.exec(cls);
    const group = /(?:^|\s)group(\d+)/.exec(cls);
    const dealer = document.getElementById('ui_8_dealer_name');
    const name = document.querySelector('.table_info_box .title, .title');
    return {
        game: game ? parseInt(game[1], 10) : null,
        group: group ? parseInt(group[1], 10) : null,
        dealer: dealer ? (dealer.textContent || '').replace(/\s+/g, ' ').trim() : '',
        title: name ? (name.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) : '',
        href: location.href
    };
})()"""

# Bàn đang mở, đọc từ khung gốc qua iframe cùng origin: nhanh hơn và không phải dò
# từng context. Iframe bàn cùng origin với trang nên contentDocument truy cập được;
# khác origin thì trả lý do để lớp gọi tự bỏ qua.
WM_OPEN_TABLE_JS = r"""(() => {
    const frame = document.getElementById('iframe_101') ||
        Array.from(document.querySelectorAll('iframe')).find((item) =>
            /iframe_101(?:\/|$|[?#])/.test(item.getAttribute('src') || ''));
    if (!frame) return {reason: 'no_table_frame'};
    const style = getComputedStyle(frame);
    const rect = frame.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden'
            || rect.width < 10 || rect.height < 10) {
        return {reason: 'table_hidden'};
    }
    let doc = null;
    try { doc = frame.contentDocument; } catch (e) { return {reason: 'cross_origin'}; }
    if (!doc) return {reason: 'no_document'};
    const box = doc.getElementById('container');
    if (!box) return {reason: 'no_container'};
    const cls = (box.className || '').toString();
    const game = /(?:^|\s)game(\d+)/.exec(cls);
    const group = /(?:^|\s)group(\d+)/.exec(cls);
    const dealer = doc.getElementById('ui_8_dealer_name');
    const name = doc.querySelector('.table_info_box .title, .title');
    return {
        game: game ? parseInt(game[1], 10) : null,
        group: group ? parseInt(group[1], 10) : null,
        dealer: dealer ? (dealer.textContent || '').replace(/\s+/g, ' ').trim() : '',
        title: name ? (name.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) : ''
    };
})()"""

# Tổng cược 3 cửa đang hiện trên bàn (đơn vị VNDK). Đây là tổng của CẢ BÀN, không
# phải riêng người dùng — WM không tách chip của từng người trên màn hình.
WM_BETS_JS = r"""(() => {
    const frame = document.getElementById('iframe_101') ||
        Array.from(document.querySelectorAll('iframe')).find((item) =>
            /iframe_101(?:\/|$|[?#])/.test(item.getAttribute('src') || ''));
    if (!frame) return {reason: 'no_table_frame'};
    if (getComputedStyle(frame).display === 'none') return {reason: 'table_hidden'};
    let doc = null;
    try { doc = frame.contentDocument; } catch (e) { return {reason: 'cross_origin'}; }
    if (!doc) return {reason: 'no_document'};
    const read = (id) => {
        const el = doc.getElementById(id);
        if (!el) return null;
        const value = parseFloat((el.textContent || '').replace(/[^0-9.]/g, ''));
        return Number.isFinite(value) ? value : 0;
    };
    return {banker: read('moneyBoxBanker'), player: read('moneyBoxPlayer'),
            tie: read('moneyBoxTie')};
})()"""

# Số dư ví thật của bàn WM: nằm trong iframe bàn (``#userBalanceBox`` in ``VNDK 80.84``,
# tức 80.84 đơn vị = 80.840đ). Đây là con số người dùng thấy trên màn hình.
WM_WALLET_JS = r"""(() => {
    const frame = document.getElementById('iframe_101') ||
        Array.from(document.querySelectorAll('iframe')).find((item) =>
            /iframe_101(?:\/|$|[?#])/.test(item.getAttribute('src') || ''));
    let doc = document;
    try { if (frame && frame.contentDocument) doc = frame.contentDocument; } catch (e) {}
    const el = doc.getElementById('userBalanceBox');
    if (!el) return {reason: 'no_wallet'};
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    const m = /([0-9][0-9.,]*)/.exec(text);
    return {text: text, value: m ? m[1] : '', unit: 'VNDK'};
})()"""

# Nút thoát bàn của WM nằm ở khung gốc (góc phải trên) — đo rồi bấm chuột thật.
WM_EXIT_JS = r"""(() => {
    const btn = document.getElementById('exit_game_btn');
    if (!btn) return {reason: 'exit_missing'};
    const rect = btn.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return {reason: 'exit_hidden'};
    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
})()"""

# Trạng thái bàn: bảng cầu lớn đã vẽ (để biết trang bàn đã render) và đồng hồ cược.
WM_TABLE_DOM_JS = r"""(() => {
    const road = document.getElementById('bigRoadContainer');
    const cells = road ? road.querySelectorAll('.cardroad-item i').length : 0;
    const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
    const wallet = /([0-9][0-9.,]*)\s*VNDK/.exec(text);
    return {
        road_cells: cells,
        wallet: wallet ? wallet[1] : '',
        open_card: !!document.querySelector('#opencard-wrapper.wrapper.on'),
        ready: !!road
    };
})()"""
