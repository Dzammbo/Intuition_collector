import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from build_player_dossiers import prematch_safe_event_context
from collect_tennis_rankings import parse_atp_html, parse_wta_text
from collect_tennis_profiles import parse_profile_html, parse_search_html


class StaticProfileTests(unittest.TestCase):
    def test_search_and_profile_parser(self):
        search = '<a href="/player/hontama/">Hontama, Mai</a>'
        self.assertEqual(
            parse_search_html(search, "Mai Hontama"),
            ("https://www.tennisexplorer.com/player/hontama/", "EXACT_NORMALIZED_TOKEN_SET_NAME"),
        )
        fields = parse_profile_html(
            "Country: Japan Height / Weight: 164 cm / 55 kg Age: 27 (30. 8. 1999) "
            "Current/Highest rank - singles: 177. / 105. Sex: woman Plays: right"
        )
        self.assertEqual(fields["date_of_birth"], "1999-08-30")
        self.assertEqual(fields["handedness"], "RIGHT")
        self.assertEqual(fields["height_cm"], 164)
        self.assertEqual(fields["highest_singles_rank"], 105)


class RankingPublicationTests(unittest.TestCase):
    def test_parses_atp_rank_not_movement_column(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "atp.html"
            path.write_text(
                '<table><tr><td>631.</td><td>9</td><td><a href="/player/palan-dominik/">'
                'Palan Dominik</a></td><td>Czech Republic</td><td>59</td></tr></table>',
                encoding="utf-8",
            )
            rows = parse_atp_html(path)
            self.assertEqual(rows[0]["ranking"], 631)
            self.assertEqual(rows[0]["name"], "Palan Dominik")

    def test_parses_wta_numeric_pdf_text(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "wta.txt"
            path.write_text(
                " 177       (171)    HONTAMA, MAI                             JPN    440     32\n",
                encoding="utf-8",
            )
            rows = parse_wta_text(path)
            self.assertEqual(rows[0]["ranking"], 177)
            self.assertEqual(rows[0]["points"], 440)


class EventContextTests(unittest.TestCase):
    def test_live_fields_are_not_copied(self):
        row = {
            "id": "10",
            "time": "1791261300",
            "time_status": "1",
            "ss": "7-6,2-3",
            "stats": {"aces": [1, 2]},
            "events": [{"text": "live"}],
            "scores": {"1": {"home": "7", "away": "6"}},
            "league": {"id": "2", "name": "Test"},
            "home": {"id": "100", "name": "Home", "cc": "ru"},
            "away": {"id": "200", "name": "Away", "cc": "nl"},
            "extra": {
                "ground": "Hardcourt outdoor",
                "round": "25",
                "bestofsets": "3",
                "stadium_data": {"name": "Court 1", "city": "Moscow", "country": "Russia"},
            },
        }
        result = prematch_safe_event_context(row, datetime(2026, 10, 6, tzinfo=timezone.utc))
        for forbidden in ("time_status", "ss", "stats", "events", "scores"):
            self.assertNotIn(forbidden, result)
        self.assertEqual(result["surface"], "Hardcourt outdoor")
        self.assertEqual(result["round"], "25")
        self.assertEqual(result["format_best_of_sets"], "3")


class EndToEndDossierTests(unittest.TestCase):
    def test_layers_event_view_and_incremental_reuse(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            universe = {
                "stage": "TENNIS_SINGLES_SCOPE_CLASSIFICATION",
                "tiering_used": False,
                "source_captured_at": "2026-10-06T00:00:00Z",
                "events": {"TENNIS_SINGLES": [{
                    "id": "10", "time": "1791261300",
                    "league": {"id": "2", "name": "Test"},
                    "home": {"id": "100", "name": "Alice", "cc": "ru"},
                    "away": {"id": "200", "name": "Bob", "cc": "nl"},
                }]},
            }
            event_view = {
                "stage": "TENNIS_SINGLES_EVENT_VIEW", "input_singles": 1, "completed": 1,
                "records": [{
                    **universe["events"]["TENNIS_SINGLES"][0],
                    "time_status": "1", "ss": "1-0", "stats": {"aces": [1, 0]},
                    "extra": {"ground": "Clay", "round": "R16", "bestofsets": "3"},
                }], "errors": [],
            }
            ranking = lambda source, name, tour: {
                "schema_version": 2, "source": source,
                "provider_response_complete": True, "full_ranking_coverage": True,
                "pages_requested": 2,
                "results": [{"name": name, "ranking": 10, "points": 1000, "tour": tour}],
            }
            (root / "universe.json").write_text(json.dumps(universe), encoding="utf-8")
            (root / "event-view.json").write_text(json.dumps(event_view), encoding="utf-8")
            (root / "rank-1.json").write_text(
                json.dumps(ranking("TEST_ATP", "Alice", "ATP")), encoding="utf-8"
            )
            (root / "rank-3.json").write_text(
                json.dumps(ranking("TEST_WTA", "Bob", "WTA")), encoding="utf-8"
            )
            (root / "matches.csv").write_text(
                "match_id;date;tournoi;categorie;surface;tour;duree_min;joueur1;joueur1_id;joueur2;joueur2_id;vainqueur_id;score;genre;cote1_cloture;cote2_cloture\n"
                "m1;2026-10-01T12:00:00;Test;ITF;Clay;R32;90;Alice;a;Bob;b;a;6-4 6-4;W;1.80;2.00\n",
                encoding="utf-8",
            )
            (root / "profiles.json").write_text(json.dumps({
                "stage": "TENNIS_PLAYER_STATIC_PROFILE_SNAPSHOT",
                "source": "TEST_PROFILES", "source_url": "https://example.test",
                "retrieved_at_utc": "2026-10-06T00:30:00Z",
                "players_requested": 2, "profiles_resolved": 2,
                "players": [
                    {"provider_player_id": "100", "status": "RESOLVED", "source": "TEST_PROFILES",
                     "profile_url": "https://example.test/alice", "fields": {
                         "date_of_birth": "2000-10-07", "nationality": "Russia",
                         "handedness": "RIGHT", "height_cm": 170, "weight_kg": 60, "sex": "WOMAN"}},
                    {"provider_player_id": "200", "status": "RESOLVED", "source": "TEST_PROFILES",
                     "profile_url": "https://example.test/bob", "fields": {
                         "date_of_birth": "1998-01-01", "nationality": "Netherlands",
                         "handedness": "LEFT", "height_cm": 180, "weight_kg": 70, "sex": "MAN"}},
                ],
            }), encoding="utf-8")

            def run(previous=None):
                command = [
                    sys.executable, str(Path(__file__).with_name("build_player_dossiers.py")),
                    "--universe", str(root / "universe.json"),
                    "--event-view", str(root / "event-view.json"),
                    "--matches", str(root / "matches.csv"),
                    "--materialized-at-utc", "2026-10-06T01:00:00Z",
                    "--ranking-snapshots", str(root / "rank-1.json"), str(root / "rank-3.json"),
                    "--profile-snapshot", str(root / "profiles.json"),
                    "--history-output", str(root / "history.json"),
                    "--snapshot-output", str(root / "snapshot.json"),
                    "--match-context-output", str(root / "context.json"),
                    "--manifest-output", str(root / "manifest.json"),
                ]
                if previous:
                    command.extend(["--previous-player-history", str(previous)])
                subprocess.run(command, check=True, capture_output=True, text=True)

            run()
            first_history = json.loads((root / "history.json").read_text())
            self.assertEqual(first_history["stage"], "BASELINE_PLAYER_HISTORY_REGISTRY")
            alice = next(row for row in first_history["players"] if row["provider_player_id"] == "100")
            self.assertEqual(alice["identity"]["date_of_birth"], "2000-10-07")
            self.assertEqual(alice["identity"]["age_at_history_cutoff"], 25)
            self.assertEqual(alice["identity"]["handedness"], "RIGHT")
            context = json.loads((root / "context.json").read_text())
            self.assertEqual(context["events"][0]["surface"], "Clay")
            self.assertNotIn("ss", context["events"][0])
            saved = root / "previous.json"
            saved.write_text((root / "history.json").read_text(), encoding="utf-8")
            run(saved)
            snapshot = json.loads((root / "snapshot.json").read_text())
            self.assertEqual(snapshot["coverage"]["persistent_records_reused"], 2)


if __name__ == "__main__":
    unittest.main()
