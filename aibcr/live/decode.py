# -*- coding: utf-8 -*-
"""Giải mã khung WebSocket của Petalive (BCR).

Khung thật có dạng chuỗi (không phải JSON thuần):

    ;game;petaball;onGetGameResult;0;0;{"issueId":"BCR_VV77842-261119-0369",
        "result":"22,8-3,49","roomId":"petaball-BCR_VV77842",
        "listBetTypeWin":["LIVE_BCR_PLAYER","LIVE_BCR_PLAYER_NATURAL", ...]}

    ;game;<room>;onGetGameInfo;0;0;{...state, timeRemains, result...}
    ;game;petaball;onChangeStateGame;0;0;{"issueId":..., "state":"BETTING", ...}

Field ``result`` = ``"<player cards>-<banker cards>"``, mỗi bên là danh sách id lá
(1..52) ngăn cách bằng dấu phẩy. Bên nào bốc 3 lá thì có 3 id.
"""

import json

EVENT_RESULT = "onGetGameResult"
EVENT_STATE = "onChangeStateGame"
EVENT_INFO = "onGetGameInfo"
EVENT_COUNTDOWN = "onGetGameCountDown"

ROOM_PREFIX = "petaball-"
BCR_MARKERS = ("BCR_", "LIVE_BCR_")


class Frame:
    """Một khung đã tách: kênh, phòng, sự kiện, payload."""

    __slots__ = ("channel", "room", "event", "payload", "raw")

    def __init__(self, channel, room, event, payload, raw=""):
        self.channel = channel
        self.room = room
        self.event = event
        self.payload = payload
        self.raw = raw

    @property
    def room_key(self):
        """Bỏ tiền tố ``petaball-`` để so khớp roomId trong payload."""
        return self.room[len(ROOM_PREFIX):] if self.room.startswith(ROOM_PREFIX) else self.room

    def __repr__(self):
        return "Frame(%s/%s/%s)" % (self.channel, self.room, self.event)


def split_frame(text):
    """Tách khung ``;channel;room;event;0;0;{json}``. Trả ``Frame`` hoặc ``None``."""
    if not isinstance(text, str) or not text.startswith(";"):
        return None
    body = text[1:]
    parts = body.split(";", 5)
    if len(parts) < 6:
        return None
    channel, room, event, _flag_a, _flag_b, rest = parts
    if not channel or not event:
        return None
    payload = None
    trimmed = rest.strip()
    if trimmed.startswith("{"):
        try:
            payload = json.loads(trimmed)
        except ValueError:
            payload = None
    return Frame(channel, room, event, payload, raw=text)


def parse_result(result):
    """``"22,8-3,49"`` -> ``([22,8], [3,49])``; dữ liệu hỏng thì trả ``None``."""
    if not isinstance(result, str) or result.count("-") != 1:
        return None
    player_text, banker_text = result.split("-")
    try:
        player = [int(part) for part in player_text.split(",") if part.strip()]
        banker = [int(part) for part in banker_text.split(",") if part.strip()]
    except ValueError:
        return None
    if not player or not banker:
        return None
    if any(not 1 <= card <= 52 for card in player + banker):
        return None
    return player, banker


def winner_from_bets(bets):
    """Cửa thắng theo ``listBetTypeWin``: P, B, T (None nếu khung không nói).

    Phải so khớp CHÍNH XÁC: danh sách còn chứa các cửa phụ như
    ``LIVE_BCR_PLAYER_EVEN`` / ``LIVE_BCR_PLAYER_DRAGON``; so theo chuỗi con sẽ
    nhận nhầm cửa chính.
    """
    exact = {str(item).strip().upper() for item in (bets or [])}
    if "LIVE_BCR_TIE" in exact:
        return "T"
    if "LIVE_BCR_PLAYER" in exact:
        return "P"
    if "LIVE_BCR_BANKER" in exact:
        return "B"
    return None


def is_baccarat_room(room_id):
    return isinstance(room_id, str) and any(mark in room_id for mark in BCR_MARKERS)


def room_table(room_id):
    """``petaball-BCR_VV77842`` / ``BCR_VV77842-261119-0369`` -> ``BCR_VV77842``."""
    if not isinstance(room_id, str):
        return ""
    text = room_id[len(ROOM_PREFIX):] if room_id.startswith(ROOM_PREFIX) else room_id
    return text.split("-", 1)[0]


def decode_round(frame, bcr_only=True):
    """Đổi ``Frame`` kết quả thành dict ván đấu; ``None`` nếu không phải kết quả BCR."""
    if not isinstance(frame, Frame) or frame.event != EVENT_RESULT:
        return None
    payload = frame.payload if isinstance(frame.payload, dict) else {}
    issue_id = payload.get("issueId") or ""
    room_id = payload.get("roomId") or frame.room_key
    if bcr_only and not (is_baccarat_room(room_id) or is_baccarat_room(issue_id)):
        return None
    parsed = parse_result(payload.get("result") or "")
    if parsed is None:
        return None
    player, banker = parsed
    bets = payload.get("listBetTypeWin") or []
    return {
        "issue_id": issue_id,
        "table": room_table(room_id) or room_table(issue_id),
        "room_id": room_id,
        "player_cards": player,
        "banker_cards": banker,
        "bets": [str(item) for item in bets],
        "winner": winner_from_bets(bets),
    }


def decode_state(frame):
    """Trạng thái bàn: ``BETTING`` / ``WAITING_SHOW_RESULT`` / ``SHOW_RESULT`` …"""
    if not isinstance(frame, Frame) or frame.event not in (EVENT_STATE, EVENT_INFO):
        return None
    payload = frame.payload if isinstance(frame.payload, dict) else {}
    issue_id = payload.get("issueId") or ""
    room_id = payload.get("roomId") or frame.room_key
    if not (is_baccarat_room(room_id) or is_baccarat_room(issue_id)):
        return None
    return {
        "issue_id": issue_id,
        "table": room_table(room_id) or room_table(issue_id),
        "state": payload.get("state") or "",
        "time_remains": payload.get("timeRemains"),
        "open_bet_at": payload.get("openBetAt"),
        "close_bet_at": payload.get("closeBetAt"),
        "result": payload.get("result") or "",
        "total_player": payload.get("totalPlayer"),
    }
