import unittest

from aibcr.models.bet_ladder import BetLadder, parse_hop_rounds, parse_stakes


class BetLadderTests(unittest.TestCase):
    def test_parses_spaces_hyphens_and_commas(self):
        self.assertEqual(parse_stakes("10 20-30,40"), [10, 20, 30, 40])
        self.assertEqual(parse_stakes("553545"), [553545])

    def test_step_never_moves_with_results(self):
        """Không còn đọc thắng/thua: dãy cược đứng yên ở mức đã cấu hình."""
        ladder = BetLadder("10 20 30", min_stake=1, max_stake=100)
        self.assertEqual(ladder.current_stake, 10)
        self.assertEqual(ladder.step, 0)
        self.assertFalse(hasattr(ladder, "on_result"),
                         "không được tiến/lùi bước theo kết quả ván")

    def test_limits_clamp_the_configured_step(self):
        ladder = BetLadder("5 200 500", min_stake=20, max_stake=300, step=1)
        self.assertEqual(ladder.current_stake, 200)
        ladder.configure("5 200 500", min_stake=20, max_stake=300, step=2)
        self.assertEqual(ladder.current_stake, 300)

    def test_empty_ladder_uses_default(self):
        self.assertEqual(parse_stakes(" , - ")[0], 260)

    def test_hop_schedule_supports_separators_without_splitting_compact_digits(self):
        self.assertEqual(parse_hop_rounds("3 4 2"), [3, 4, 2])
        self.assertEqual(parse_hop_rounds("3,4-2"), [3, 4, 2])
        self.assertEqual(parse_hop_rounds("553545"), [553545])


if __name__ == "__main__":
    unittest.main()
