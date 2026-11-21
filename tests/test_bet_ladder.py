import unittest

from aibcr.models.bet_ladder import BetLadder, parse_hop_rounds, parse_stakes


class BetLadderTests(unittest.TestCase):
    def test_parses_spaces_hyphens_and_commas(self):
        self.assertEqual(parse_stakes("10 20-30,40"), [10, 20, 30, 40])
        self.assertEqual(parse_stakes("553545"), [553545])

    def test_win_resets_loss_advances_and_tie_holds(self):
        ladder = BetLadder("10 20 30", min_stake=1, max_stake=100)
        self.assertEqual(ladder.on_result("LOSE"), 20)
        self.assertEqual(ladder.on_result("TIE"), 20)
        self.assertEqual(ladder.on_result("LOSE"), 30)
        self.assertEqual(ladder.on_result("LOSE"), 30)
        self.assertEqual(ladder.on_result("WIN"), 10)

    def test_limits_clamp_each_step(self):
        ladder = BetLadder("5 200 500", min_stake=20, max_stake=300)
        self.assertEqual(ladder.current_stake, 20)
        self.assertEqual(ladder.on_result("LOSE"), 200)
        self.assertEqual(ladder.on_result("LOSE"), 300)

    def test_empty_ladder_uses_default(self):
        self.assertEqual(parse_stakes(" , - ")[0], 260)

    def test_hop_schedule_supports_separators_without_splitting_compact_digits(self):
        self.assertEqual(parse_hop_rounds("3 4 2"), [3, 4, 2])
        self.assertEqual(parse_hop_rounds("3,4-2"), [3, 4, 2])
        self.assertEqual(parse_hop_rounds("553545"), [553545])


if __name__ == "__main__":
    unittest.main()
