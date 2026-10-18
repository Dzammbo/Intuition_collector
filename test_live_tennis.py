import tempfile
import unittest
from pathlib import Path
from live_tennis import match_type, parse_prices, usable_cache


class LiveTennisTest(unittest.TestCase):
    def payload(self, home="1.65", stamp=990, direction=1):
        return {"success": 1, "results": {"stats": {"matching_dir": direction, "odds_update": {"13_1": 999}}, "odds": {"13_1": [{"home_od": home, "away_od": "2.2", "add_time": stamp}]}}}

    def test_price_direction_and_unrestricted_age(self):
        result = parse_prices(self.payload(direction=-1), {"time_status": 1}, 1000)
        self.assertEqual(result["home"], 2.2)
        self.assertEqual(result["status"], "AVAILABLE_NEEDS_SCORE_REVIEW")
        self.assertEqual(parse_prices(self.payload(stamp=800), {"time_status": 1}, 1000)["status"], "AVAILABLE_NEEDS_SCORE_REVIEW")

    def test_missing_timestamps_do_not_block_and_ages_are_visible(self):
        payload = self.payload(stamp=None)
        payload["results"]["stats"]["odds_update"] = {}
        result = parse_prices(payload, {"time_status": 1}, 1000)
        self.assertEqual(result["status"], "AVAILABLE_NEEDS_SCORE_REVIEW")
        self.assertIsNone(result["quote_age_seconds"])
        self.assertIsNone(result["check_age_seconds"])
        old = parse_prices(self.payload(stamp=1), {"time_status": 1}, 1000000)
        self.assertEqual(old["status"], "AVAILABLE_NEEDS_SCORE_REVIEW")
        self.assertEqual(old["quote_age_seconds"], 999999)
        self.assertEqual(parse_prices(self.payload(stamp=1), {"time_status": 3}, 1000000)["status"], "NOT_LIVE")
        self.assertEqual(parse_prices(self.payload(direction=0), {"time_status": 1}, 1000)["status"], "UNVERIFIED")

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
