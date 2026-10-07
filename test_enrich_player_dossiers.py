import unittest

from enrich_player_dossiers import build


def player(player_id, name, elo, hand):
    return {
        "provider_player_id": player_id,
        "canonical_name": name,
        "source_fingerprint": "fp-" + player_id,
        "identity": {"date_of_birth": "2000-01-01", "age_at_history_cutoff": 26, "handedness": hand},
        "source_resolution": {"historical_matches_found": 30},
        "baseline_history": {
            "last_20": {"detail": [{
                "date_utc": "2026-10-01T10:00:00Z", "result": "W", "opponent": "Past",
                "tournament": "M25 Test", "surface": "DUR", "round": "Q1", "score": "6-4 6-4",
                "duration_minutes": 91, "opponent_pre_match_archive_elo": elo - 10,
            }]},
            "surface_record": {"DUR": {"matches": 12, "wins": 8, "losses": 4}},
            "archive_strength_context": {"current_archive_elo": elo, "current_surface_archive_elo": {"DUR": elo + 5}},
            "score_derived_metrics": {"matches_with_score": 20, "serve_points_and_hold_rate": "UNKNOWN", "return_points_and_break_rate": "UNKNOWN"},
            "workload_and_rest": {"matches_previous_7_days": 2, "matches_previous_30_days": 7, "latest_completed_match_utc": "2026-10-01T10:00:00Z", "calendar_days_rest_at_frozen_cutoff": 5},
            "retirement_walkover_evidence": {"flagged_results_in_archive": 0, "supported_injury_information": "UNKNOWN"},
        },
    }


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.history = {
            "stage": "BASELINE_PLAYER_HISTORY_SNAPSHOT", "frozen_data_cutoff_utc": "2026-10-06T00:00:00Z",
            "players": [player("1", "Alice", 1600, "RIGHT"), player("2", "Bob", 1550, "LEFT")],
        }
        self.context = {
            "stage": "MATCH_SPECIFIC_DOSSIER_CONTEXT",
            "events": [{"event_id": "10", "scheduled_start_utc": "2026-10-06T12:00:00Z", "tournament": "Test", "tournament_id": "5", "surface": "Hardcourt outdoor", "round": "R16", "format_best_of_sets": 3, "venue": {"city": "Paris", "country": "France"}, "home": {"id": "1"}, "away": {"id": "2"}}],
        }

    def test_builds_non_scoring_two_player_packet(self):
        output = build(self.history, self.context)
        self.assertEqual(output["coverage"]["output_events"], 1)
        event = output["events"][0]
        self.assertEqual(event["status"], "READY_FOR_DEEP_RESEARCH")
        self.assertEqual({row["side"] for row in event["players"]}, {"HOME", "AWAY"})
        home = event["players"][0]
        self.assertEqual(home["surface_form"]["archive_surface_key"], "DUR")
        self.assertEqual(home["opponent_quality"]["current_opponent_archive_elo"], 1550.0)
        self.assertIn("SERVE_AND_HOLD", home["research_gaps"])
        self.assertTrue(event["policy"]["non_scoring"])
        self.assertNotIn("decision", event)

    def test_external_observation_requires_exact_source(self):
        observations = {"observations": [{"event_id": "10", "player_id": "1", "dimensions": {"health": "READY"}, "sources": []}]}
        with self.assertRaises(ValueError):
            build(self.history, self.context, observations)

    def test_reuses_unchanged_event(self):
        first = build(self.history, self.context)
        second = build(self.history, self.context, previous=first)
        self.assertEqual(second["coverage"]["reused"], 1)
        self.assertEqual(second["events"][0]["source_fingerprint"], first["events"][0]["source_fingerprint"])


if __name__ == "__main__":
    unittest.main()
