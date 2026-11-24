"""Parse and advance a user-configured stake ladder."""

import re


DEFAULT_STAKES = (260, 280, 300, 240, 220, 280, 320, 340, 380, 400,
                  360, 420, 440, 480, 500, 420, 340, 380, 440, 280,
                  400, 360, 300, 340, 280, 400, 360, 300, 280)


def parse_stakes(value, fallback=DEFAULT_STAKES):
    """Accept a list or a string separated by whitespace, commas, or hyphens."""
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = re.split(r"[\s,-]+", str(value or "").strip())
    stakes = []
    for part in parts:
        try:
            number = int(str(part).strip())
        except (TypeError, ValueError):
            continue
        if number > 0:
            stakes.append(number)
    if stakes:
        return stakes
    if fallback is None:
        return []
    if fallback is DEFAULT_STAKES:
        return list(DEFAULT_STAKES)
    return parse_stakes(fallback, fallback=DEFAULT_STAKES)


def parse_hop_rounds(value, fallback=(2,)):
    """Parse per-table hand counts; an unseparated digit string stays one number."""
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = re.split(r"[\s,-]+", str(value or "").strip())
    rounds = []
    for part in parts:
        try:
            number = int(str(part).strip())
        except (TypeError, ValueError):
            continue
        if number > 0:
            rounds.append(number)
    return rounds or [int(fallback[0])]


class BetLadder:
    """Dãy cược cố định: chỉ chọn mức đang dùng, không tiến/lùi theo kết quả ván."""

    def __init__(self, stakes=DEFAULT_STAKES, min_stake=20, max_stake=10000, step=0):
        self.configure(stakes, min_stake, max_stake, step=step)

    def configure(self, stakes, min_stake=20, max_stake=10000, step=0):
        self.stakes = parse_stakes(stakes)
        self.min_stake = max(1, int(min_stake))
        self.max_stake = max(self.min_stake, int(max_stake))
        self.step = min(max(0, int(step)), len(self.stakes) - 1)
        return self.current_stake

    @property
    def current_stake(self):
        value = self.stakes[self.step]
        return min(self.max_stake, max(self.min_stake, value))
