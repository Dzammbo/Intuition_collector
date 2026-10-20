import unittest

from underdog_gate import classify, expected_card_decision, validate_gate


class UnderdogGateTests(unittest.TestCase):
    def gate(self, **changes):
        value = {
            "policy_version": "2026-10-20-underdog-only-v1",
            "classification_method": "TWO_SIDED_BET365_MATCH_WINNER_COMPARISON",
            "selected_side": "AWAY",
            "home_odds": 1.60,
            "away_odds": 2.30,
            "market_role": "UNDERDOG",
            "captured_at_utc": "2026-10-20T20:00:00Z",
        }
        value.update(changes)
        return value

    def test_relative_prices_define_underdog_without_absolute_band(self):
        self.assertEqual(classify("AWAY", 1.60, 2.30)["market_role"], "UNDERDOG")
        self.assertEqual(classify("HOME", 1.60, 2.30)["market_role"], "FAVORITE")

    def test_only_supported_underdog_can_reach_main_card(self):
        self.assertEqual(expected_card_decision("BET", "UNDERDOG"), "BET")
        self.assertEqual(expected_card_decision("BET", "FAVORITE"), "PASS")
        self.assertEqual(expected_card_decision("BET", "EVEN"), "PASS")
        self.assertEqual(expected_card_decision("PASS", "UNDERDOG"), "PASS")

    def test_gate_requires_two_sided_quote_and_side_lock(self):
        validate_gate(self.gate(), "AWAY", 2.30)
        with self.assertRaisesRegex(ValueError, "both match-winner prices"):
            validate_gate(self.gate(home_odds=None), "AWAY", 2.30)
        with self.assertRaisesRegex(ValueError, "side differs"):
            validate_gate(self.gate(), "HOME", 1.60)

    def test_equal_prices_are_not_underdog(self):
        self.assertEqual(classify("HOME", 1.91, 1.91)["market_role"], "EVEN")


if __name__ == "__main__":
    unittest.main()
