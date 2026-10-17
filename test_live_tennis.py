import tempfile
import unittest
from pathlib import Path
from live_tennis import match_type, parse_prices, usable_cache


class LiveTennisTest(unittest.TestCase):
    def payload(self, home="1.65", stamp=990, direction=1):
        return {"success": 1, "results": {"stats": {"matching_dir": direction, "odds_update": {"13_1": 999}}, "odds": {"13_1": [{"home_od": home, "away_od": "2.2", "add_time": stamp}]}}}

    def test_price_direction_and_freshness(self):
        result = parse_prices(self.payload(direction=-1), {"time_status": 1}, 1000)
        self.assertEqual(result["home"], 2.2)
        self.assertEqual(result["status"], "FRESH_NEEDS_SCORE_REVIEW")
        self.assertEqual(parse_prices(self.payload(stamp=800), {"time_status": 1}, 1000)["status"], "STALE_OR_UNKNOWN")

    def test_suspended_latest_is_not_backfilled(self):
        payload = self.payload()
        payload["results"]["odds"]["13_1"].append({"home_od": "-", "away_od": "-", "add_time": 999})
        self.assertEqual(parse_prices(payload, {"time_status": 1}, 1000)["status"], "SUSPENDED")

    def test_singles_and_doubles_are_separate(self):
        self.assertEqual(match_type({"home": {"name": "A"}, "away": {"name": "B"}}), "SINGLES")
        self.assertEqual(match_type({"home": {"name": "A / B"}, "away": {"name": "C / D"}}), "DOUBLES")

    def test_cache_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text('{"captured_at_epoch":999,"response":{}}')
            self.assertIsNotNone(usable_cache(path, 1000))
            self.assertIsNone(usable_cache(path, 1000 + 8 * 24 * 60 * 60))


if __name__ == "__main__":
    unittest.main()
