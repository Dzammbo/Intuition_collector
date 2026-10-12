import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import assessment_price_refresh as refresh


class PriceRefreshTests(unittest.TestCase):
    def test_abbreviated_player_name_matches(self):
        self.assertGreaterEqual(refresh.name_score("Bianca Andreescu", "B Andreescu"), 0.9)

    def test_candidate_requires_both_players_and_accepts_reversed_order(self):
        candidates = [{"fi": "77", "home": "M Ristic", "away": "B Andreescu", "start": datetime(2026, 10, 12, 8, tzinfo=timezone.utc)}]
        match = refresh.choose_candidate(candidates, "Bianca Andreescu", "Mia Ristic", datetime(2026, 10, 12, 8, tzinfo=timezone.utc))
        self.assertEqual(match["fi"], "77")
        self.assertTrue(match["reversed"])

    def test_ambiguous_candidate_is_rejected(self):
        start = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
        candidates = [
            {"fi": "1", "home": "B Andreescu", "away": "M Ristic", "start": start},
            {"fi": "2", "home": "B Andreescu", "away": "M Ristic", "start": start},
        ]
        self.assertIsNone(refresh.choose_candidate(candidates, "Bianca Andreescu", "Mia Ristic", start))

    def test_extracts_named_match_winner_market(self):
        payload = {"results": [
            {"type": "MA", "NA": "Match Winner"},
            {"type": "PA", "NA": "Bianca Andreescu", "OD": "1.80", "ID": "h"},
            {"type": "PA", "NA": "Mia Ristic", "OD": "2.00", "ID": "a"},
        ]}
        result = refresh.extract_match_winner(payload, "Bianca Andreescu", "Mia Ristic", False, datetime(2026, 10, 12, 7, tzinfo=timezone.utc))
        self.assertEqual(result["odds"]["13_1"][0]["home_od"], 1.8)
        self.assertEqual(result["odds"]["13_1"][0]["away_od"], 2.0)

    def test_reversed_candidate_order_does_not_swap_named_prices(self):
        payload = {"results": [
            {"type": "MA", "NA": "Match Winner"},
            {"type": "PA", "NA": "Bianca Andreescu", "OD": "1.80", "ID": "h"},
            {"type": "PA", "NA": "Mia Ristic", "OD": "2.00", "ID": "a"},
        ]}
        result = refresh.extract_match_winner(payload, "Bianca Andreescu", "Mia Ristic", True, datetime(2026, 10, 12, 7, tzinfo=timezone.utc))
        self.assertEqual(result["odds"]["13_1"][0]["home_od"], 1.8)
        self.assertEqual(result["odds"]["13_1"][0]["away_od"], 2.0)

    def test_non_match_winner_market_is_not_accepted(self):
        payload = {"results": [
            {"type": "MA", "NA": "Set 1 Winner"},
            {"type": "PA", "NA": "Bianca Andreescu", "OD": "1.80"},
            {"type": "PA", "NA": "Mia Ristic", "OD": "2.00"},
        ]}
        self.assertIsNone(refresh.extract_match_winner(payload, "Bianca Andreescu", "Mia Ristic", False, datetime.now(timezone.utc)))

    def test_generic_candidate_parser(self):
        payload = {"results": [{
            "id": 123,
            "time": "1791799200",
            "home": {"name": "Bianca Andreescu"},
            "away": {"name": "Mia Ristic"},
            "league": {"name": "UTR Beograd Women"},
        }]}
        rows = refresh.generic_candidates(payload)
        self.assertEqual(rows[0]["event_id"], "123")
        self.assertEqual(rows[0]["source"], "GENERIC_UPCOMING_SOURCE_BET365")


if __name__ == "__main__":
    unittest.main()
