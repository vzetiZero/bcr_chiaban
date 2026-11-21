# -*- coding: utf-8 -*-
"""Tests for DG bet-limit parsing: table floor vs per-side wager counters."""

import re
import unittest

from aibcr.adapters import febet as F


def parse_floor_js():
    """Extract the parseFloor function source from a DG script block."""
    pattern = r"const parseFloor = \(text\) => \{.*?\n  \};"
    match = re.search(pattern, F._DG_BET_STATE_JS, re.S)
    if not match:
        raise AssertionError("parseFloor not found in _DG_BET_STATE_JS")
    return match.group(0)


def all_parse_floor_blocks():
    pattern = r"const parseFloor = \(text\) => \{.*?\n  \};"
    return re.findall(pattern, F._DG_BET_STATE_JS + F._DG_STAGE_BET_JS, re.S)


class FloorParserSourceTest(unittest.TestCase):
    def test_rejects_per_side_wager_counters(self):
        """'954145/12' is stake/counter, not the table floor."""
        source = parse_floor_js()
        # The old pattern accepted a bare '/' separator, which matched counters.
        self.assertNotIn(r"\s*(?:-|~|\/)\s*", source)
        self.assertIn("bothUnits", source)
        self.assertIn("plainDash", source)

    def test_requires_dash_or_tilde_between_limits(self):
        source = parse_floor_js()
        self.assertIn(r"(?:-|~|đến|to)", source)

    def test_unit_suffix_is_multiplied(self):
        source = parse_floor_js()
        self.assertIn("unit === 'M'", source)
        self.assertIn("unit === 'K'", source)

    def test_both_parser_blocks_stay_in_sync(self):
        """The bet-state and stage-bet scripts must parse limits identically."""
        blocks = all_parse_floor_blocks()
        self.assertEqual(len(blocks), 2, "expected parseFloor in both DG scripts")
        self.assertEqual(blocks[0], blocks[1])


class FloorParserBehaviourTest(unittest.TestCase):
    """Run the extracted JS logic through an equivalent Python port."""

    @staticmethod
    def parse(text):
        both = re.search(
            r"([\d][\d,.]*)\s*([kKmM])\s*(?:-|~|đến|to)\s*([\d][\d,.]*)\s*([kKmM])",
            str(text or ""), re.I)
        one = re.search(
            r"([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)\s*([kKmM])(?![\d])",
            str(text or ""), re.I)
        plain = re.search(r"([\d][\d,.]*)\s*(?:-|~)\s*([\d][\d,.]*)(?:\s|$)", str(text or ""))
        match = both or one or plain
        if not match:
            return 0
        value = float(str(match.group(1)).replace(",", ""))
        unit = str(match.group(2) or "").upper()
        if value <= 0:
            return 0
        if unit == "M":
            value *= 1000
        elif unit == "K" and value < 1000:
            value *= 1000
        return value

    def test_reads_febet_limit_label(self):
        self.assertEqual(self.parse("10K-50M"), 10000)

    def test_reads_gk881_limit_label(self):
        self.assertEqual(self.parse("10-1K"), 10)

    def test_reads_plain_thousands(self):
        self.assertEqual(self.parse("10,000-50,000,000"), 10000)

    def test_ignores_stake_and_player_counters(self):
        for text in ("954145/12", "1.7M/15", "0/0", "26/1", "129/1"):
            self.assertEqual(self.parse(text), 0, text)

    def test_ignores_round_ids_and_names(self):
        for text in ("11210026R1042", "RB01", "ZYRA", "Lucky 6"):
            self.assertEqual(self.parse(text), 0, text)


if __name__ == "__main__":
    unittest.main()
