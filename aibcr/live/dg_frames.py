# -*- coding: utf-8 -*-
"""Giải mã khung WebSocket nhị phân của sảnh DG (Laya) cho bàn Baccarat.

DG không gửi JSON như Petalive và cũng không dùng protocol 21/24/25 như WM: nó gửi
**protobuf** qua WebSocket nhị phân. Đo trên bàn thật 60101 (GK881, `ddnewwap`) cho
thấy mỗi ván có hai khung:

    khung mở cược   field 1 = 1002, field 4 = pha, field 17 = thông tin bàn/ván
    khung kết quả   field 1 = 1003, field 14 = JSON lá bài, field 6 = mã bàn

Trong khung 1002, ``field 17`` là một message con:

    [1] tableId      60101
    [2] ?            số thứ tự
    [3] countDown    giây còn lại
    [4] stateId      pha (1 = mở cược, 2/5/8 = đã ngã)
    [7] JSON lá bài  {"banker":"44-28-0","player":"5-32-7"}
    [11] gameNo      "202611240011R1024"

Lá bài trong JSON có **hai dạng** tuỳ loại khung:

    "5-32-7"                    id lá (0 = ô chưa chia)
    ["3C227","7C229",""]        nhãn "<hạng><chất><số hiệu>"

Nhãn được đổi sang id 1..52 rank-major của ``aibcr.live.cards`` để dùng chung shoe và
phép tính điểm đã có test.

``warning`` — **id số của DG KHÔNG phải rank-major** như ``aibcr.live.cards`` mà là
suit-major, 13 lá một chất::

    dg_id = chất * 13 + hạng        (hạng 1..13 = A..K)
    hạng = (dg_id - 1) % 13 + 1

Thứ tự chất của DG theo kiểu Hoa là ♠ ♥ ♣ ♦. Đã đối chiếu trực tiếp với ảnh chụp bàn
60101: khung cho player ``[35, 11]``, ảnh hiện **9♣ + J♠**, header bàn ghi ``9 VS 0``;
suit-major ra đúng 9 điểm còn rank-major ra 2. Dùng nhầm sẽ quyết toán sai tiền.

Module này chỉ giải mã dữ liệu; không gắn CDP và không bấm gì.
"""

import json
import re

from aibcr.live import cards

# field 1 = loại bản tin
MSG_BET_STATE = 1002
MSG_RESULT = 1003

GAME_NO_RE = re.compile(r"^\d{12}R\d{4}$")
GAME_NO_ANY_RE = re.compile(r"\d{12}R\d{4}")
CARDS_JSON_RE = re.compile(r'^\{"(?:banker|player)"')

# Nhãn lá bài DG: "<rank><suit><số thứ tự>" — "3C227" = 3 Chuồn, "AS228" = Át Bích,
# "10H19" = 10 Cơ. Hậu tố là số hiệu lá trong shoe, không phải phần của lá.
# Thứ tự chất phải khớp ``aibcr.live.cards``: id = (rank-1)*4 + chỉ_số_chất + 1 với
# chỉ số ♠=0, ♥=1, ♦=2, ♣=3 (vì ``card_label`` lấy ``SUIT_NAMES[(id-1) % 4]``).
LABEL_SUIT_INDEX = {"S": 0, "H": 1, "D": 2, "C": 3}
LABEL_RANKS = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
               "9": 9, "10": 10, "T": 10, "J": 11, "Q": 12, "K": 13}
LABEL_TAIL_RE = re.compile(r"\d+$")

# DG xếp id theo **chất** (13 lá một chất), thứ tự Hoa: ♠ ♥ ♣ ♦. ``aibcr.live.cards``
# lại xếp ♠ ♥ ♦ ♣, nên phải đổi chất chứ không dùng thẳng id.
DG_SUIT_TO_CARDS = (0, 1, 3, 2)
DG_RANKS = 13

# field trong message con (field 17 của khung 1002)
SUB_TABLE_ID = 1
SUB_COUNTDOWN = 3
SUB_STATE_ID = 4
SUB_CARDS = 7
SUB_GAME_NO = 11

# field ở cấp ngoài
OUT_CARDS = 14
OUT_GAME_NO = 11
OUT_TABLE_ID = 6


def read_varint(buf, index):
    """Đọc một varint; trả ``(value, next_index)``."""
    shift = 0
    value = 0
    while index < len(buf):
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
        if shift > 63:
            raise ValueError("varint quá dài")
    raise ValueError("varint bị cắt")


def parse_message(buf):
    """Tách một protobuf message thành ``[(field, wire, value)]``.

    ``wire == 2`` trả ``str`` nếu nội dung là UTF-8 in được, ngược lại là message con
    đã tách đệ quy. Field không xác định bị bỏ (chỉ cần đọc, không cần ghi lại).
    """
    out = []
    index = 0
    while index < len(buf):
        try:
            key, index = read_varint(buf, index)
        except ValueError:
            break
        field, wire = key >> 3, key & 7
        if field == 0:
            break
        if wire == 0:
            try:
                value, index = read_varint(buf, index)
            except ValueError:
                break
            out.append((field, 0, value))
        elif wire == 2:
            try:
                length, index = read_varint(buf, index)
            except ValueError:
                break
            chunk = buf[index:index + length]
            if len(chunk) != length:
                break
            index += length
            text = _printable(chunk)
            out.append((field, 2, text if text is not None else parse_message(chunk)))
        elif wire == 5:
            if index + 4 > len(buf):
                break
            index += 4
        elif wire == 1:
            if index + 8 > len(buf):
                break
            index += 8
        else:
            break
    return out


def _printable(chunk):
    """Chuỗi UTF-8 in được, hoặc ``None`` nếu là dữ liệu nhị phân."""
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return ""
    for char in text:
        code = ord(char)
        if code < 32 and char not in "\t\r\n":
            return None
        if code == 0x7F:
            return None
    return text


def field_values(message, field):
    """Mọi giá trị của một field trong message."""
    return [value for number, _wire, value in message if number == field]


def first(message, field, default=None):
    values = field_values(message, field)
    return values[0] if values else default


def card_id(value):
    """Id lá DG (1..52, xếp theo chất) -> id 1..52 của ``aibcr.live.cards``.

    ``None`` nếu ngoài phạm vi. Đây là chỗ duy nhất đổi bảng mã, để mọi đường đọc
    (khung 1002 và 1003) dùng chung một kết quả.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if not 1 <= number <= 52:
        return None
    suit = (number - 1) // DG_RANKS           # 0..3 theo thứ tự ♠ ♥ ♣ ♦ của DG
    rank = (number - 1) % DG_RANKS + 1        # 1..13 = A..K
    return (rank - 1) * 4 + DG_SUIT_TO_CARDS[suit] + 1


def card_ids(text):
    """``'44-28-0'`` -> id chuẩn của ``aibcr.live.cards``; ``0`` là ô chưa chia.

    Giá trị là id **DG** (suit-major) nên phải đổi qua ``card_id``; dùng thẳng sẽ
    tính sai điểm và quyết toán sai tiền.
    """
    out = []
    for part in str(text or "").split("-"):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return []
        number = int(part)
        if number == 0:
            continue                      # ô chưa chia
        converted = card_id(number)
        if not converted:
            return []                     # ngoài 1..52: khung hỏng, bỏ cả tay
        out.append(converted)
    return out


def label_to_card_id(label):
    """Nhãn lá DG -> id 1..52 của ``aibcr.live.cards``; ``None`` nếu không đọc được.

    DG ghi lá bằng tên chứ không bằng số: ``"3C227"`` là 3 Chuồn, ``"10H19"`` là 10 Cơ,
    ``"AS228"`` là Át Bích. Phần đuôi số là số hiệu lá trong shoe nên phải bỏ đi; chỉ
    giữ tên hạng + chất rồi đổi sang id rank-major giống mọi bộ đọc khác.
    """
    text = str(label or "").strip().upper()
    if not text:
        return None
    body = LABEL_TAIL_RE.sub("", text)
    if len(body) < 2:
        return None
    suit = body[-1]
    if suit not in LABEL_SUIT_INDEX:
        return None
    rank = LABEL_RANKS.get(body[:-1])
    if rank is None:
        return None
    return (rank - 1) * 4 + LABEL_SUIT_INDEX[suit] + 1


def card_ids_from_list(values):
    """Danh sách lá DG -> id chuẩn. Nhận cả nhãn ``"3C227"`` và số ``"44"``."""
    out = []
    for value in values or []:
        if isinstance(value, int) and not isinstance(value, bool):
            converted = card_id(value)
            if converted:
                out.append(converted)
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if text.isdigit():
            converted = card_id(int(text))
            if converted:
                out.append(converted)
            continue
        label = label_to_card_id(text)
        if label:
            out.append(label)
    return out


def cards_from_json(text):
    """Tách ``{"banker": "...", "player": "..."}`` thành hai danh sách id.

    DG dùng hai dạng trong hai loại khung: ``"5-32-7"`` (id, 0 = chưa chia) và
    ``["3C227", "7C229", ""]`` (nhãn lá). Cả hai đều nhận.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    return (_side_cards(data.get("player")), _side_cards(data.get("banker")))


def _side_cards(value):
    """Một cửa trong JSON lá bài: nhận danh sách hoặc chuỗi ``a-b-c``.

    Chuỗi có thể là id (``"5-32-7"``, 0 = ô chưa chia) hoặc nhãn (``"AS228-6H230"``),
    nên chỉ đi đường số học khi mọi mảnh đều là số.
    """
    if isinstance(value, list):
        return card_ids_from_list(value)
    if not isinstance(value, str):
        return []
    tokens = [part.strip() for part in value.split("-")]
    tokens = [part for part in tokens if part]
    if not tokens:
        return []
    if all(part.isdigit() for part in tokens):
        return card_ids(value)
    return card_ids_from_list(tokens)


def hand_verdict(player_cards, banker_cards):
    """Điểm và cửa thắng của một ván; ``''`` khi chưa đủ lá để kết luận."""
    if not player_cards or not banker_cards:
        return {"player_score": None, "banker_score": None, "winner": ""}
    player = cards.hand_total(player_cards)
    banker = cards.hand_total(banker_cards)
    winner = "T" if player == banker else ("P" if player > banker else "B")
    return {"player_score": player, "banker_score": banker, "winner": winner}


def decode_frame(raw):
    """Giải mã một khung nhị phân DG; trả ``None`` nếu không phải khung bàn cược.

    Trả dict:
        {kind, table_id, game_no, state_id, countdown,
         player_cards, banker_cards, player_score, banker_score, winner}
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    message = parse_message(bytes(raw))
    kind = first(message, 1)
    if kind not in (MSG_BET_STATE, MSG_RESULT):
        return None

    table_id = ""
    game_no = ""
    state_id = None
    countdown = None
    card_text = ""

    # Khung 1002: thông tin bàn nằm trong message con ở field 17.
    for sub in field_values(message, 17):
        if not isinstance(sub, list):
            continue
        table = first(sub, SUB_TABLE_ID)
        if table is not None and not table_id:
            table_id = str(table)
        game = first(sub, SUB_GAME_NO)
        if isinstance(game, str) and GAME_NO_RE.match(game) and not game_no:
            game_no = game
        state = first(sub, SUB_STATE_ID)
        if state is not None and state_id is None:
            state_id = int(state)
        count = first(sub, SUB_COUNTDOWN)
        if count is not None and countdown is None:
            countdown = int(count)
        cards_text = first(sub, SUB_CARDS)
        if isinstance(cards_text, str) and CARDS_JSON_RE.match(cards_text):
            card_text = cards_text

    # Khung 1003: kết quả ván, lá bài + mã bàn ở cấp ngoài.
    if not card_text:
        for value in field_values(message, OUT_CARDS):
            if isinstance(value, str) and CARDS_JSON_RE.match(value):
                card_text = value
                break
    if not table_id:
        table = first(message, OUT_TABLE_ID)
        if isinstance(table, int) and table > 0:
            table_id = str(table)
    if not game_no:
        for value in field_values(message, OUT_GAME_NO):
            if isinstance(value, str) and GAME_NO_RE.match(value):
                game_no = value
                break
    if not game_no:
        # Mã bàn có thể nằm lẫn trong chuỗi khác ("2611244141613").
        for _field, _wire, value in message:
            if isinstance(value, str):
                found = GAME_NO_ANY_RE.search(value)
                if found:
                    game_no = found.group(0)
                    break

    player_cards, banker_cards = cards_from_json(card_text) if card_text else ([], [])
    verdict = hand_verdict(player_cards, banker_cards)
    if not table_id and not game_no and not player_cards and not banker_cards:
        return None
    return {
        "kind": kind,
        "table_id": table_id,
        "game_no": game_no,
        "state_id": state_id,
        "countdown": countdown,
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "player_score": verdict["player_score"],
        "banker_score": verdict["banker_score"],
        "winner": verdict["winner"],
    }
