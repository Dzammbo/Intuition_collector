import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from build_player_dossiers import prematch_safe_event_context
from collect_tennis_rankings import RankingCollectionError, collect_ranking_type


class RankingPaginationTests(unittest.TestCase):
    def test_collects_every_page_from_pager(self):
        payloads = {
            1: {"success": 1, "pager": {"total": 3, "per_page": 2}, "results": [{"id": 1}, {"id": 2}]},
            2: {"success": 1, "pager": {"total": 3, "per_page": 2}, "results": [{"id": 3}]},
        }
        result = collect_ranking_type(1, lambda _type, page: payloads[page])
        self.assertTrue(result["pagination_complete"])
        self.assertEqual(result["pages_requested"], 2)
        self.assertEqual(result["unique_rows"], 3)

    def test_without_pager_continues_until_empty_page(self):
        payloads = {
            1: {"success": 1, "results": [{"id": 1}]},
            2: {"success": 1, "results": [{"id": 2}]},
            3: {"success": 1, "results": []},
        }
        result = collect_ranking_type(3, lambda _type, page: payloads[page])
        self.assertEqual(result["completion_reason"], "EMPTY_PAGE")
        self.assertEqual(result["unique_rows"], 2)

    def test_repeated_page_fails_closed(self):
        payload = {"success": 1, "results": [{"id": 1}]}
        with self.assertRaises(RankingCollectionError):
            collect_ranking_type(1, lambda _type, _page: payload)


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
            ranking = lambda kind, player: {
                "schema_version": 1, "type_id": kind, "pagination_complete": True,
                "pages_requested": 2, "reported_total": 1,
                "results": [{"id": player, "ranking": 10, "points": 1000}],
            }
            (root / "universe.json").write_text(json.dumps(universe), encoding="utf-8")
            (root / "event-view.json").write_text(json.dumps(event_view), encoding="utf-8")
            (root / "rank-1.json").write_text(json.dumps(ranking(1, "100")), encoding="utf-8")
            (root / "rank-3.json").write_text(json.dumps(ranking(3, "200")), encoding="utf-8")
            (root / "matches.csv").write_text(
                "match_id;date;tournoi;categorie;surface;tour;duree_min;joueur1;joueur1_id;joueur2;joueur2_id;vainqueur_id;score;genre;cote1_cloture;cote2_cloture\n"
                "m1;2026-10-01T12:00:00;Test;ITF;Clay;R32;90;Alice;a;Bob;b;a;6-4 6-4;W;1.80;2.00\n",
                encoding="utf-8",
            )

            def run(previous=None):
                command = [
                    sys.executable, str(Path(__file__).with_name("build_player_dossiers.py")),
                    "--universe", str(root / "universe.json"),
                    "--event-view", str(root / "event-view.json"),
                    "--matches", str(root / "matches.csv"),
                    "--materialized-at-utc", "2026-10-06T01:00:00Z",
                    "--ranking-snapshots", str(root / "rank-1.json"), str(root / "rank-3.json"),
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
