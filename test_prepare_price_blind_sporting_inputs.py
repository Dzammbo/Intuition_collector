import json
import tempfile
import unittest
from pathlib import Path

from prepare_price_blind_sporting_inputs import build


class PreparePriceBlindSportingInputsTest(unittest.TestCase):
    def source(self):
        enrichment = {
            "stage": "TENNIS_PRE_DEEP_RESEARCH_ENRICHMENT",
            "events": [
                {
                    "event_id": "1",
                    "status": "READY_FOR_DEEP_RESEARCH",
                    "match_context": {"scheduled_start_utc": "2026-10-08T15:00:00Z"},
                    "players": [
                        {"side": "HOME", "player_id": "10", "canonical_name": "A"},
                        {"side": "AWAY", "player_id": "20", "canonical_name": "B"},
                    ],
                },
                {"event_id": "2", "status": "READY_FOR_DEEP_RESEARCH", "players": []},
            ],
        }
        timing = {
            "stage": "DEEP_RESEARCH_TIMING_CHECK",
            "date_moscow": "2026-10-08",
            "coverage": {"cleared_for_price_blind_sporting_freeze": 1, "time_gate_pass": 1},
            "events": [
                {"event_id": "2", "timing_status": "PASS"},
                {"event_id": "1", "timing_status": "CLEARED_FOR_PRICE_BLIND_SPORTING_FREEZE"},
            ],
        }
        return enrichment, timing

    def test_builds_only_cleared_events(self):
        enrichment, timing = self.source()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build(enrichment, timing, Path(tmp), date_moscow="2026-10-08")
            self.assertEqual(manifest["coverage"]["sporting_inputs"], 1)
            self.assertEqual(manifest["date_moscow"], "2026-10-08")
            payload = json.loads((Path(tmp) / "events/001-1.json").read_text())
            self.assertTrue(payload["market_data_redacted"])
            self.assertFalse(payload["price_information_consulted"])

    def test_redacts_market_keys(self):
        enrichment, timing = self.source()
        enrichment["events"][0]["odds"] = 1.8
        with tempfile.TemporaryDirectory() as tmp:
            build(enrichment, timing, Path(tmp), date_moscow="2026-10-08")
            payload = json.loads((Path(tmp) / "events/001-1.json").read_text())
            self.assertNotIn("odds", payload["sporting_research_baseline"])
            self.assertEqual(payload["market_fields_removed_count"], 1)


if __name__ == "__main__":
    unittest.main()
