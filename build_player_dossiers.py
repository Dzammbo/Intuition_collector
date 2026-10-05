#!/usr/bin/env python3
"""Create auditable multi-source tennis player dossiers from a frozen universe."""
from __future__ import annotations
import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

VALUEBETENNIS_URL = "https://www.valuebetennis.com/en/donnees.htm"
SOURCE_NAME = "VALUEBETENNIS_OPEN_ATP_WTA_SINGLES_ARCHIVE"
UNKNOWN = "UNKNOWN"

def normalise(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())

def parse_stamp(value: str) -> datetime:
    text = str(value or "").strip().strip('"')
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None

def is_retirement(score: str) -> bool:
    score = str(score or "").casefold()
    return any(token in score for token in ("ret", "abandon", "walkover", "w/o", "wo"))

def result_for(row: dict, player_key: str) -> tuple[str, str, str]:
    p1 = normalise(row.get("joueur1"))
    p2 = normalise(row.get("joueur2"))
    if player_key == p1:
        opponent = str(row.get("joueur2") or "")
        winner = str(row.get("vainqueur_id") or "") == str(row.get("joueur1_id") or "")
    elif player_key == p2:
        opponent = str(row.get("joueur1") or "")
        winner = str(row.get("vainqueur_id") or "") == str(row.get("joueur2_id") or "")
    else:
        raise ValueError("player not present")
    return ("W" if winner else "L"), opponent, str(row.get("score") or "")

def compact_matches(matches: list[dict], player_key: str, take: int) -> dict:
    rows = matches[:take]
    wins = 0
    items = []
    for row in rows:
        result, opponent, score = result_for(row, player_key)
        wins += result == "W"
        items.append({"date_utc": row["date_utc"], "result": result, "opponent": opponent,
                      "tournament": row["tournament"], "category": row["category"],
                      "surface": row["surface"], "round": row["round"],
                      "score": score or UNKNOWN, "duration_minutes": row["duration_minutes"]})
    return {"matches": len(rows), "wins": wins, "losses": len(rows) - wins, "detail": items}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--matches", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--materialized-at-utc", required=True)
    args = parser.parse_args()
    universe = json.loads(Path(args.universe).read_text(encoding="utf-8-sig"))
    cutoff = parse_stamp(universe["source_captured_at"])
    materialized_at = parse_stamp(args.materialized_at_utc)
    events = universe.get("events", {}).get("TENNIS_SINGLES") or []
    roster: dict[str, dict] = {}
    player_events: defaultdict[str, list[dict]] = defaultdict(list)
    for event in events:
        for side in ("home", "away"):
            raw = event.get(side) or {}
            provider_id = str(raw.get("id") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not provider_id or not name:
                continue
            roster.setdefault(provider_id, {"provider_player_id": provider_id, "canonical_name": name,
                                           "provider_country_code": raw.get("cc") or UNKNOWN})
            player_events[provider_id].append({
                "event_id": str(event.get("id") or ""),
                "scheduled_start_utc": datetime.fromtimestamp(int(event["time"]), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "tournament": (event.get("league") or {}).get("name") or UNKNOWN,
                "tournament_id": str((event.get("league") or {}).get("id") or UNKNOWN)})
    by_name: defaultdict[str, list[dict]] = defaultdict(list)
    archive_rows = 0
    malformed_rows = 0
    for filename in args.matches:
        with Path(filename).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                try:
                    when = parse_stamp(row.get("date") or "")
                except ValueError:
                    malformed_rows += 1
                    continue
                if when >= cutoff:
                    continue
                if not row.get("joueur1") or not row.get("joueur2"):
                    malformed_rows += 1
                    continue
                packed = {"date_utc": iso(when), "tournament": str(row.get("tournoi") or UNKNOWN),
                          "category": str(row.get("categorie") or UNKNOWN),
                          "surface": str(row.get("surface") or UNKNOWN).upper(),
                          "round": str(row.get("tour") or UNKNOWN),
                          "duration_minutes": int(row["duree_min"]) if str(row.get("duree_min") or "").isdigit() else UNKNOWN,
                          "joueur1": str(row["joueur1"]), "joueur1_id": str(row.get("joueur1_id") or UNKNOWN),
                          "joueur2": str(row["joueur2"]), "joueur2_id": str(row.get("joueur2_id") or UNKNOWN),
                          "vainqueur_id": str(row.get("vainqueur_id") or UNKNOWN), "score": str(row.get("score") or "")}
                by_name[normalise(packed["joueur1"])].append(packed)
                by_name[normalise(packed["joueur2"])].append(packed)
                archive_rows += 1
    players = []
    counts = Counter()
    for provider_id, player in sorted(roster.items(), key=lambda item: (normalise(item[1]["canonical_name"]), item[0])):
        name_key = normalise(player["canonical_name"])
        matches = sorted(by_name.get(name_key, []), key=lambda row: row["date_utc"], reverse=True)
        unique_matches = {row["date_utc"] + "|" + row["joueur1_id"] + "|" + row["joueur2_id"]: row for row in matches}
        matches = sorted(unique_matches.values(), key=lambda row: row["date_utc"], reverse=True)
        counts["historical_match_resolved" if matches else "historical_match_unresolved"] += 1
        surface: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        retirements = 0
        last_match_date = None
        for row in matches:
            result, _, score = result_for(row, name_key)
            if row["surface"] != UNKNOWN:
                surface[row["surface"]][0 if result == "W" else 1] += 1
            retirements += is_retirement(score)
            if last_match_date is None:
                last_match_date = parse_stamp(row["date_utc"])
        week = [row for row in matches if (cutoff - parse_stamp(row["date_utc"])).days <= 7]
        month = [row for row in matches if (cutoff - parse_stamp(row["date_utc"])).days <= 30]
        rest_days = (cutoff.date() - last_match_date.date()).days if last_match_date else UNKNOWN
        event_rows = player_events[provider_id]
        started_before_materialization = sum(parse_stamp(e["scheduled_start_utc"]) <= materialized_at for e in event_rows)
        context = {"events_on_card": event_rows,
                   "events_already_started_when_dossier_materialized": started_before_materialization,
                   "events_still_prematch_when_dossier_materialized": len(event_rows) - started_before_materialization,
                   "target_event_surface": UNKNOWN, "target_event_round": UNKNOWN, "target_event_format": UNKNOWN,
                   "target_event_field_status": "UNKNOWN_EVENT_VIEW_NOT_USED_FOR_POST_START_REPAIR"}
        players.append({**player,
            "identity": {"aliases": [player["canonical_name"]], "date_of_birth": UNKNOWN, "nationality": UNKNOWN,
                         "handedness": UNKNOWN, "identity_resolution": "PROVIDER_ID_AND_CANONICAL_NAME"},
            "source_resolution": {"historical_name_match": "EXACT_NORMALIZED_NAME" if matches else "UNRESOLVED_IN_VALUEBETENNIS_ARCHIVE",
                                  "historical_matches_found": len(matches),
                                  "match_data_source": SOURCE_NAME if matches else UNKNOWN},
            "snapshot": {
                "ranking_and_movement": UNKNOWN, "ranking_reason": "OFFICIAL_RANKING_SNAPSHOT_NOT_COLLECTED_BY_AUTOMATED_SOURCE",
                "last_5": compact_matches(matches, name_key, 5), "last_10": compact_matches(matches, name_key, 10),
                "last_20": compact_matches(matches, name_key, 20),
                "surface_record": {surface_name: {"wins": value[0], "losses": value[1], "matches": sum(value)}
                                   for surface_name, value in sorted(surface.items())} or UNKNOWN,
                "opponent_strength_context": UNKNOWN, "opponent_strength_reason": "ARCHIVE_HAS_NO_RANKING_OR_STRENGTH_FIELD",
                "serve_return_hold_break_tiebreak_metrics": UNKNOWN,
                "retirement_walkover_evidence": {"flagged_results_in_archive": retirements, "supported_injury_information": UNKNOWN},
                "workload_rest_travel_time_zone": {"matches_previous_7_days": len(week), "matches_previous_30_days": len(month),
                    "latest_completed_match_utc": iso(last_match_date), "calendar_days_rest_at_frozen_cutoff": rest_days,
                    "travel_and_time_zone": UNKNOWN},
                "historical_performance_by_price_band": UNKNOWN, "prior_system_decisions": UNKNOWN, "card_context": context}})
    output = {"schema_version": 1, "stage": "MULTI_SOURCE_PLAYER_DOSSIER_SNAPSHOT",
      "status": "PARTIALLY_ENRICHED_WITH_EXPLICIT_FIELD_PROVENANCE",
      "regime_id": "intuition-v1-2026-10-05-tennis-singles",
      "frozen_data_cutoff_utc": iso(cutoff), "materialized_at_utc": iso(materialized_at),
      "policy": {"no_result_with_timestamp_at_or_after_cutoff_is_used": True,
                 "target_event_fields_not_proven_prestart_are_unknown": True,
                 "post_start_materialization_cannot_repair_started_event_decisions": True},
      "sources": [{"source": SOURCE_NAME, "url": VALUEBETENNIS_URL,
                   "scope": "ATP_WTA_ITF_CHALLENGER_SINGLES_RESULTS_AND_SURFACES_AS_PUBLISHED",
                   "retrieved_at_utc": iso(materialized_at), "used_result_cutoff_utc": iso(cutoff),
                   "confidence": "SECONDARY_OPEN_DATA_FILTERED_TO_FROZEN_CUTOFF"}],
      "coverage": {"eligible_matches": len(events), "unique_players": len(players),
                   "players_with_exact_normalized_historical_match_data": counts["historical_match_resolved"],
                   "players_without_resolved_historical_match_data": counts["historical_match_unresolved"],
                   "archived_matches_processed_before_cutoff": archive_rows, "malformed_source_rows_ignored": malformed_rows},
      "players": players}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["coverage"], ensure_ascii=False))

if __name__ == "__main__":
    main()
