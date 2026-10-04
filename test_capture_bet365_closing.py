import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import capture_bet365_closing as closing


class ClosingLineTests(unittest.TestCase):
    def test_selects_latest_prematch_bet365_quote_and_removes_margin(self):
        payload = {"results": {"stats": {"matching_dir": 1}, "odds": {"13_1": [
            {"home_od": "1.90", "away_od": "1.90", "add_time": "100"},
            {"home_od": "1.80", "away_od": "2.00", "add_time": "200"},
            {"home_od": "1.20", "away_od": "5.00", "add_time": "300", "ss": "1-0", "time_str": "12"},
        ]}}}
        target = {"market_key": "13_1", "market_type": "MONEYLINE", "side": "home", "line": None}
        quote = closing.select_prematch_quote(payload, target)
        self.assertEqual(quote["selected_odds"], 1.8)
        self.assertEqual(quote["quote_add_time"], 200)
        self.assertAlmostEqual(quote["selected_fair_probability"], 0.52631579)

    def test_reversed_match_swaps_named_sides(self):
        payload = {"results": {"stats": {"matching_dir": -1}, "odds": {"13_1": [
            {"home_od": "1.50", "away_od": "2.50", "add_time": "100"},
        ]}}}
        target = {"market_key": "13_1", "market_type": "MONEYLINE", "side": "home", "line": None}
        quote = closing.select_prematch_quote(payload, target)
        self.assertEqual(quote["selected_odds"], 2.5)

    def test_loads_bets_and_only_substantive_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "status").mkdir()
            checkpoint = root / "assessment_checkpoints" / "day"
            checkpoint.mkdir(parents=True)
            (root / "status" / "current-run.json").write_text(json.dumps({
                "assessment": {"checkpoint_root": "assessment_checkpoints/day"}
            }))
            rows = [
                {"event_id": "1", "scheduled_start_utc": "2026-10-05T10:00:00Z", "status": "PASS",
                 "evaluated_target": {"target_status": "RECORDED", "market_key": "13_1", "side": "away", "selection": "B", "captured_odds": 2.1}},
                {"event_id": "2", "scheduled_start_utc": "2026-10-05T11:00:00Z", "status": "PASS",
                 "evaluated_target": {"target_status": "UNAVAILABLE"}},
            ]
            (checkpoint / "batch.json").write_text(json.dumps({"decisions": rows}))
            targets = closing.load_targets(root, datetime(2026, 10, 4, tzinfo=timezone.utc))
            self.assertEqual([target["provider_event_id"] for target in targets], ["1"])


if __name__ == "__main__":
    unittest.main()
