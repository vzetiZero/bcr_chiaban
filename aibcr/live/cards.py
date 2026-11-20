# -*- coding: utf-8 -*-
"""Mã hoá lá bài của Petalive BCR và theo dõi shoe.

Đã đối chiếu với dữ liệu thật (34/34 ván khớp ``listBetTypeWin``):

    id 1..52, rank-major theo 4 chất:
        rank = (id - 1) // 4 + 1     -> 1..13 (A,2..10,J,Q,K)
        giá trị điểm = rank nếu rank <= 10, ngược lại 0

Ví dụ: id 1..4 = A, id 5..8 = 2, id 49..52 = K.
"""

RANK_NAMES = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUIT_NAMES = ("♠", "♥", "♦", "♣")
DECK_SIZE = 52
DEFAULT_DECKS = 8


def valid_card(card_id):
    return isinstance(card_id, int) and not isinstance(card_id, bool) and 1 <= card_id <= DECK_SIZE


def card_rank(card_id):
    """Hạng 1..13 (A..K)."""
    if not valid_card(card_id):
        raise ValueError("card id ngoài 1..52: %r" % (card_id,))
    return (card_id - 1) // 4 + 1


def card_value(card_id):
    """Điểm Baccarat: A=1, 2..9 giữ nguyên, 10/J/Q/K = 0."""
    rank = card_rank(card_id)
    return rank if rank <= 9 else 0


def card_label(card_id):
    rank = card_rank(card_id)
    # Thứ tự chất chỉ mang tính hiển thị: id-1 chia 4 dư 0..3.
    return "%s%s" % (RANK_NAMES[rank - 1], SUIT_NAMES[(card_id - 1) % 4])


def hand_total(cards):
    """Tổng điểm một tay (mod 10)."""
    return sum(card_value(card) for card in cards) % 10


def is_natural(cards):
    """Natural 8/9 với đúng 2 lá đầu."""
    return len(cards) == 2 and hand_total(cards) in (8, 9)


class Shoe:
    """Bộ bài còn lại: đếm theo rank để tính xác suất lá kế tiếp."""

    def __init__(self, decks=DEFAULT_DECKS):
        if not isinstance(decks, int) or isinstance(decks, bool) or decks < 1:
            raise ValueError("số bộ bài phải là số nguyên >= 1")
        self.decks = decks
        self.counts = [0] * (DECK_SIZE + 1)
        for card_id in range(1, DECK_SIZE + 1):
            self.counts[card_id] = decks
        self.seen = []

    # ---------------------------------------------------------------- cập nhật
    def reset(self, decks=None):
        if decks is not None:
            self.decks = int(decks)
        self.__init__(self.decks)

    def take(self, card_id):
        if not valid_card(card_id):
            raise ValueError("card id ngoài 1..52: %r" % (card_id,))
        if self.counts[card_id] <= 0:
            raise ValueError("lá %d đã hết trong shoe (cần xào lại)" % card_id)
        self.counts[card_id] -= 1
        self.seen.append(card_id)
        return card_id

    def take_hand(self, player_cards, banker_cards):
        for card in list(player_cards) + list(banker_cards):
            self.take(card)

    # ----------------------------------------------------------------- trạng thái
    @property
    def remaining(self):
        return sum(self.counts[1:])

    @property
    def dealt(self):
        return len(self.seen)

    @property
    def penetration(self):
        total = DECK_SIZE * self.decks
        return self.dealt / total if total else 0.0

    def rank_counts(self):
        """Số lá còn lại theo rank 1..13."""
        out = [0] * 14
        for card_id in range(1, DECK_SIZE + 1):
            out[card_rank(card_id)] += self.counts[card_id]
        return out

    def value_counts(self):
        """Số lá còn lại theo giá trị điểm 0..9 (index 0 = 10/J/Q/K)."""
        out = [0] * 10
        for card_id in range(1, DECK_SIZE + 1):
            out[card_value(card_id)] += self.counts[card_id]
        return out

    def snapshot(self):
        return {
            "decks": self.decks,
            "remaining": self.remaining,
            "dealt": self.dealt,
            "penetration": round(self.penetration, 4),
            "rank_counts": self.rank_counts()[1:],
            "value_counts": self.value_counts(),
        }
