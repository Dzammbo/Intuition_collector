import unittest
from datetime import datetime, timezone

import build_player_dossiers as b


class ArchiveAliasRegression(unittest.TestCase):
    def test_resolved_alias_keeps_player_orientation_and_elo(self):
        player = {"provider_player_id": "64507", "canonical_name": "Daniel Salazar", "provider_country_code": "co"}
        key, method = b.resolve_archive_name_key(player["canonical_name"], ["Daniel Salazar Martinez", "Other Player"])
        self.assertEqual(method, "UNIQUE_MULTI_TOKEN_SUBSET_ALIAS")
        player["archive_name_key"] = key
        base = {"match_id": "1", "date_utc": "2026-10-01T00:00:00Z", "tournament": "Test", "category": "ITF", "surface": "TERRE BATTUE", "round": "1", "duration_minutes": "UNKNOWN", "gender": "ATP", "closing_odds_1": None, "closing_odds_2": None}
        first = {**base, "joueur1": "Daniel Salazar Martinez", "joueur1_id": "1", "joueur2": "Other Player", "joueur2_id": "2", "vainqueur_id": "1", "score": "6-2 6-3", "joueur1_pre_elo": 1600., "joueur2_pre_elo": 1500.}
        second = {**base, "match_id": "2", "joueur2": "Daniel Salazar Martinez", "joueur2_id": "1", "joueur1": "Other Player", "joueur1_id": "2", "vainqueur_id": "1", "score": "2-6 3-6", "joueur2_pre_elo": 1600., "joueur1_pre_elo": 1500.}
        record = b.build_history_record(player, [first, second], None, {key: 1612.}, {(key, "TERRE BATTUE"): 1610.}, datetime(2026, 10, 19, tzinfo=timezone.utc), "test", None)
        history = record["baseline_history"]
        self.assertEqual(history["last_5"]["wins"], 2)
        self.assertEqual([r["opponent"] for r in history["last_5"]["detail"]], ["Other Player", "Other Player"])
        self.assertEqual(history["surface_record"]["TERRE BATTUE"]["wins"], 2)
        self.assertEqual(history["archive_strength_context"]["current_archive_elo"], 1612.)
        self.assertEqual(history["archive_strength_context"]["current_surface_archive_elo"]["TERRE BATTUE"], 1610.)
        self.assertEqual(history["score_derived_metrics"]["sets_won"], 4)

    def test_wrong_resolved_identity_is_rejected(self):
        player = {"canonical_name": "Daniel Salazar", "archive_name_key": "wrong"}
        with self.assertRaisesRegex(ValueError, "resolved archive identity"):
            b.build_history_record(player, [{"joueur1": "Daniel Salazar Martinez", "joueur2": "Other Player"}], None, {}, {}, datetime.now(timezone.utc), "test", None)


if __name__ == "__main__":
    unittest.main()
