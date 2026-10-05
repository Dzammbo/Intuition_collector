#!/usr/bin/env python3
"""Create auditable multi-source tennis player dossiers from a frozen universe.

The primary historical source is Valuebetennis' open ATP/WTA singles archive.
It is deliberately filtered to the frozen provider capture timestamp, so later
results cannot enter a prematch dossier.  It does not claim to provide fields
that it does not publish: rankings, serve/return splits, health information and
biographical attributes remain explicit UNKNOWNs until an attributable source
is collected.
"""

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
ELO_START = 1500.0
ELO_K = 24.0


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


def as_float(value: object) -> float | None:
    try:
        parsed = float(str(value or "").replace(",", "."))
    except ValueError:
        return None
    return parsed if parsed > 1.0 else None


def score_sets(score: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in re.findall(r"(?<!\d)(\d{1,2})-(\d{1,2})", str(score or ""))]


def score_features(row: dict, player_key: str) -> dict:
    sets = score_sets(row.get("score") or "")
    if not sets:
        return {"score_available": False, "tiebreak_sets": UNKNOWN, "deciding_set_played": UNKNOWN,
                "deciding_set_won": UNKNOWN}
    player_is_first = player_key == normalise(row.get("joueur1"))
    oriented = sets if player_is_first else [(b, a) for a, b in sets]
    player_sets = sum(a > b for a, b in oriented)
    opponent_sets = sum(a < b for a, b in oriented)
    before_last_player = sum(a > b for a, b in oriented[:-1])
    before_last_opponent = sum(a < b for a, b in oriented[:-1])
    deciding = len(oriented) >= 3 and before_last_player == before_last_opponent
    return {
        "score_available": True,
        "tiebreak_sets": sum({a, b} == {6, 7} for a, b in oriented),
        "deciding_set_played": deciding,
        "deciding_set_won": (player_sets > opponent_sets) if deciding else False,
    }


def price_band(odds: float) -> str:
    if odds < 1.50:
        return "LT_1_50"
    if odds < 1.80:
        return "1_50_TO_1_79"
    if odds < 2.20:
        return "1_80_TO_2_19"
    if odds < 3.00:
        return "2_20_TO_2_99"
    return "GE_3_00"


def closing_odds_for(row: dict, player_key: str) -> float | None:
    if player_key == normalise(row.get("joueur1")):
        return row.get("closing_odds_1")
    if player_key == normalise(row.get("joueur2")):
        return row.get("closing_odds_2")
    return None


def elo_expected(rating: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent - rating) / 400.0))


def apply_archive_elo(rows: list[dict]) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    global_ratings: dict[str, float] = defaultdict(lambda: ELO_START)
    surface_ratings: dict[tuple[str, str], float] = defaultdict(lambda: ELO_START)
    for row in sorted(rows, key=lambda item: (item["date_utc"], item["match_id"])):
        p1 = normalise(row["joueur1"])
        p2 = normalise(row["joueur2"])
        r1, r2 = global_ratings[p1], global_ratings[p2]
        s1, s2 = surface_ratings[(p1, row["surface"])], surface_ratings[(p2, row["surface"])]
        row["joueur1_pre_elo"] = round(r1, 1)
        row["joueur2_pre_elo"] = round(r2, 1)
        row["joueur1_pre_surface_elo"] = round(s1, 1)
        row["joueur2_pre_surface_elo"] = round(s2, 1)
        p1_won = str(row.get("vainqueur_id")) == str(row.get("joueur1_id"))
        actual1 = 1.0 if p1_won else 0.0
        global_ratings[p1] = r1 + ELO_K * (actual1 - elo_expected(r1, r2))
        global_ratings[p2] = r2 + ELO_K * ((1.0 - actual1) - elo_expected(r2, r1))
        surface_ratings[(p1, row["surface"])] = s1 + ELO_K * (actual1 - elo_expected(s1, s2))
        surface_ratings[(p2, row["surface"])] = s2 + ELO_K * ((1.0 - actual1) - elo_expected(s2, s1))
    return dict(global_ratings), dict(surface_ratings)


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
        player_is_first = player_key == normalise(row.get("joueur1"))
        wins += result == "W"
        items.append({
            "date_utc": row["date_utc"],
            "result": result,
            "opponent": opponent,
            "tournament": row["tournament"],
            "category": row["category"],
            "surface": row["surface"],
            "round": row["round"],
            "score": score or UNKNOWN,
            "duration_minutes": row["duration_minutes"],
            "closing_odds": closing_odds_for(row, player_key) or UNKNOWN,
            "opponent_pre_match_archive_elo": (
                row.get("joueur2_pre_elo") if player_is_first else row.get("joueur1_pre_elo")
            ) or UNKNOWN,
        })
    return {"matches": len(rows), "wins": wins, "losses": len(rows) - wins, "detail": items}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--matches", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--materialized-at-utc", required=True)
    parser.add_argument("--ranking-snapshots", nargs="*", default=[])
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
            roster.setdefault(provider_id, {
                "provider_player_id": provider_id,
                "canonical_name": name,
                "provider_country_code": raw.get("cc") or UNKNOWN,
            })
            player_events[provider_id].append({
                "event_id": str(event.get("id") or ""),
                "scheduled_start_utc": datetime.fromtimestamp(int(event["time"]), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "tournament": (event.get("league") or {}).get("name") or UNKNOWN,
                "tournament_id": str((event.get("league") or {}).get("id") or UNKNOWN),
            })

    by_name: defaultdict[str, list[dict]] = defaultdict(list)
    all_rows: list[dict] = []
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
                packed = {
                    "match_id": str(row.get("match_id") or ""),
                    "date_utc": iso(when),
                    "tournament": str(row.get("tournoi") or UNKNOWN),
                    "category": str(row.get("categorie") or UNKNOWN),
                    "surface": str(row.get("surface") or UNKNOWN).upper(),
                    "round": str(row.get("tour") or UNKNOWN),
                    "duration_minutes": int(row["duree_min"]) if str(row.get("duree_min") or "").isdigit() else UNKNOWN,
                    "joueur1": str(row["joueur1"]),
                    "joueur1_id": str(row.get("joueur1_id") or UNKNOWN),
                    "joueur2": str(row["joueur2"]),
                    "joueur2_id": str(row.get("joueur2_id") or UNKNOWN),
                    "vainqueur_id": str(row.get("vainqueur_id") or UNKNOWN),
                    "score": str(row.get("score") or ""),
                    "gender": str(row.get("genre") or UNKNOWN).upper(),
                    "closing_odds_1": as_float(row.get("cote1_cloture")),
                    "closing_odds_2": as_float(row.get("cote2_cloture")),
                }
                all_rows.append(packed)
                archive_rows += 1

    global_elo, surface_elo = apply_archive_elo(all_rows)
    for packed in all_rows:
        by_name[normalise(packed["joueur1"])].append(packed)
        by_name[normalise(packed["joueur2"])].append(packed)

    rankings = {}
    ranking_sources = []
    for filename in args.ranking_snapshots:
        payload = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        rows = payload.get("results") or []
        for row in rows:
            player_id = str(row.get("id") or "").strip()
            if player_id:
                rankings[player_id] = {
                    "rank": row.get("ranking") or UNKNOWN,
                    "points": row.get("points") or UNKNOWN,
                    "provider_country": row.get("country") or UNKNOWN,
                }
        ranking_sources.append({
            "source": "BETSAPI_TENNIS_RANKING_SNAPSHOT",
            "file": Path(filename).name,
            "rows": len(rows),
            "retrieved_at_utc": iso(materialized_at),
            "use_constraint": "POST_CUTOFF_SNAPSHOT_NOT_FOR_RETROACTIVE_PREMATCH_REPAIR",
        })

    players = []
    counts = Counter()
    cutoff_date = cutoff.date()
    for provider_id, player in sorted(roster.items(), key=lambda item: (normalise(item[1]["canonical_name"]), item[0])):
        name_key = normalise(player["canonical_name"])
        matches = sorted(by_name.get(name_key, []), key=lambda row: row["date_utc"], reverse=True)
        unique_matches = {row["date_utc"] + "|" + row["joueur1_id"] + "|" + row["joueur2_id"]: row for row in matches}
        matches = sorted(unique_matches.values(), key=lambda row: row["date_utc"], reverse=True)
        if matches:
            counts["historical_match_resolved"] += 1
        else:
            counts["historical_match_unresolved"] += 1

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

        genders = Counter(row["gender"] for row in matches if row["gender"] != UNKNOWN)
        observed_gender = genders.most_common(1)[0][0] if genders else UNKNOWN
        score_history = [
            features for row in matches if row.get("score")
            for features in [score_features(row, name_key)] if features["score_available"]
        ]
        tiebreak_matches = sum(item["tiebreak_sets"] > 0 for item in score_history)
        deciding_matches = sum(item["deciding_set_played"] is True for item in score_history)
        deciding_wins = sum(item["deciding_set_won"] is True for item in score_history)

        band_stats: defaultdict[str, dict] = defaultdict(lambda: {"matches": 0, "wins": 0, "losses": 0, "profit_units": 0.0})
        for row in matches:
            odds = closing_odds_for(row, name_key)
            if odds is None:
                continue
            result, _, _ = result_for(row, name_key)
            band = band_stats[price_band(odds)]
            band["matches"] += 1
            band["wins"] += result == "W"
            band["losses"] += result == "L"
            band["profit_units"] += odds - 1.0 if result == "W" else -1.0
        price_history = {}
        for band_name, values in sorted(band_stats.items()):
            profit = round(values.pop("profit_units"), 2)
            price_history[band_name] = {
                **values,
                "profit_units_flat_stake": profit,
                "roi_pct_flat_stake": round(100.0 * profit / values["matches"], 1),
            }
        counts["gender_resolved" if observed_gender != UNKNOWN else "gender_unresolved"] += 1
        counts["score_history_resolved" if score_history else "score_history_unresolved"] += 1
        counts["price_history_resolved" if price_history else "price_history_unresolved"] += 1

        recent_opponent_elos = []
        for row in matches[:20]:
            player_is_first = name_key == normalise(row["joueur1"])
            value = row.get("joueur2_pre_elo") if player_is_first else row.get("joueur1_pre_elo")
            if isinstance(value, (int, float)):
                recent_opponent_elos.append(float(value))
        player_surface_elos = {
            surface_name: round(surface_elo[(name_key, surface_name)], 1)
            for surface_name in sorted(surface)
            if (name_key, surface_name) in surface_elo
        }
        strength_context = {
            "model": "ARCHIVE_ELO_K24_START1500_FROM_2024",
            "current_archive_elo": round(global_elo.get(name_key, ELO_START), 1),
            "current_surface_archive_elo": player_surface_elos or UNKNOWN,
            "last_20_average_opponent_pre_match_archive_elo": (
                round(sum(recent_opponent_elos) / len(recent_opponent_elos), 1) if recent_opponent_elos else UNKNOWN
            ),
            "last_20_opponents_with_elo": len(recent_opponent_elos),
            "role": "STRENGTH_PROXY_NOT_OFFICIAL_RANKING",
        }
        event_rows = player_events[provider_id]
        started_before_materialization = sum(parse_stamp(e["scheduled_start_utc"]) <= materialized_at for e in event_rows)
        still_prematch = len(event_rows) - started_before_materialization
        context = {
            "events_on_card": event_rows,
            "events_already_started_when_dossier_materialized": started_before_materialization,
            "events_still_prematch_when_dossier_materialized": still_prematch,
            "target_event_surface": UNKNOWN,
            "target_event_round": UNKNOWN,
            "target_event_format": UNKNOWN,
            "target_event_field_status": "UNKNOWN_EVENT_VIEW_NOT_USED_FOR_POST_START_REPAIR",
        }
        rank = rankings.get(provider_id)
        if rank:
            counts["ranking_resolved"] += 1
            ranking_and_movement = {
                "current_rank": rank["rank"],
                "ranking_points": rank["points"],
                "ranking_movement": UNKNOWN,
                "source": "BETSAPI_TENNIS_RANKING_SNAPSHOT",
                "retrieved_at_utc": iso(materialized_at),
                "use_constraint": "POST_CUTOFF_SNAPSHOT_NOT_FOR_RETROACTIVE_PREMATCH_REPAIR",
            }
            ranking_reason = "RANK_AND_POINTS_CAPTURED; MOVEMENT_NOT_PROVIDED"
        else:
            counts["ranking_unresolved"] += 1
            ranking_and_movement = UNKNOWN
            ranking_reason = "NO_PROVIDER_RANKING_MATCH_IN_COLLECTED_SINGLES_SNAPSHOTS"
        player_record = {
            **player,
            "identity": {
                "aliases": [player["canonical_name"]],
                "date_of_birth": UNKNOWN,
                "nationality": UNKNOWN,
                "handedness": UNKNOWN,
                "observed_gender": observed_gender,
                "identity_resolution": "PROVIDER_ID_AND_CANONICAL_NAME",
            },
            "source_resolution": {
                "historical_name_match": "EXACT_NORMALIZED_NAME" if matches else "UNRESOLVED_IN_VALUEBETENNIS_ARCHIVE",
                "historical_matches_found": len(matches),
                "match_data_source": SOURCE_NAME if matches else UNKNOWN,
            },
            "snapshot": {
                "ranking_and_movement": ranking_and_movement,
                "ranking_reason": ranking_reason,
                "last_5": compact_matches(matches, name_key, 5),
                "last_10": compact_matches(matches, name_key, 10),
                "last_20": compact_matches(matches, name_key, 20),
                "surface_record": {
                    surface_name: {"wins": value[0], "losses": value[1], "matches": sum(value)}
                    for surface_name, value in sorted(surface.items())
                } or UNKNOWN,
                "opponent_strength_context": strength_context if matches else UNKNOWN,
                "opponent_strength_reason": (
                    "DERIVED_FROM_CHRONOLOGICAL_ARCHIVE_RESULTS" if matches else "NO_RESOLVED_ARCHIVE_HISTORY"
                ),
                "serve_return_hold_break_tiebreak_metrics": {
                    "serve_points_and_hold_rate": UNKNOWN,
                    "return_points_and_break_rate": UNKNOWN,
                    "matches_with_score": len(score_history),
                    "matches_with_tiebreak": tiebreak_matches,
                    "tiebreak_sets_played": sum(item["tiebreak_sets"] for item in score_history),
                    "deciding_sets_played": deciding_matches,
                    "deciding_sets_won": deciding_wins,
                    "deciding_set_win_pct": round(100.0 * deciding_wins / deciding_matches, 1) if deciding_matches else UNKNOWN,
                    "source_scope": "SCORE_DERIVED_ONLY; SERVE_RETURN_REQUIRES_POINT_OR_MATCH_STATS_SOURCE",
                } if score_history else UNKNOWN,
                "retirement_walkover_evidence": {
                    "flagged_results_in_archive": retirements,
                    "supported_injury_information": UNKNOWN,
                },
                "workload_rest_travel_time_zone": {
                    "matches_previous_7_days": len(week),
                    "matches_previous_30_days": len(month),
                    "latest_completed_match_utc": iso(last_match_date),
                    "calendar_days_rest_at_frozen_cutoff": rest_days,
                    "travel_and_time_zone": UNKNOWN,
                },
                "historical_performance_by_price_band": price_history or UNKNOWN,
                "prior_system_decisions": UNKNOWN,
                "card_context": context,
            },
        }
        players.append(player_record)

    output = {
        "schema_version": 1,
        "stage": "MULTI_SOURCE_PLAYER_DOSSIER_SNAPSHOT",
        "status": "PARTIALLY_ENRICHED_WITH_EXPLICIT_FIELD_PROVENANCE",
        "regime_id": "intuition-v1-2026-10-05-tennis-singles",
        "frozen_data_cutoff_utc": iso(cutoff),
        "materialized_at_utc": iso(materialized_at),
        "policy": {
            "no_result_with_timestamp_at_or_after_cutoff_is_used": True,
            "target_event_fields_not_proven_prestart_are_unknown": True,
            "post_start_materialization_cannot_repair_started_event_decisions": True,
        },
        "sources": [{
            "source": SOURCE_NAME,
            "url": VALUEBETENNIS_URL,
            "scope": "ATP_WTA_ITF_CHALLENGER_SINGLES_RESULTS_AND_SURFACES_AS_PUBLISHED",
            "retrieved_at_utc": iso(materialized_at),
            "used_result_cutoff_utc": iso(cutoff),
            "confidence": "SECONDARY_OPEN_DATA_FILTERED_TO_FROZEN_CUTOFF",
        }] + ranking_sources,
        "coverage": {
            "eligible_matches": len(events),
            "unique_players": len(players),
            "players_with_exact_normalized_historical_match_data": counts["historical_match_resolved"],
            "players_without_resolved_historical_match_data": counts["historical_match_unresolved"],
            "players_with_observed_gender": counts["gender_resolved"],
            "players_with_score_derived_tiebreak_and_deciding_set_history": counts["score_history_resolved"],
            "players_with_closing_price_band_history": counts["price_history_resolved"],
            "players_with_archive_elo_strength_context": counts["historical_match_resolved"],
            "players_with_provider_ranking_snapshot": counts["ranking_resolved"],
            "players_without_provider_ranking_snapshot": counts["ranking_unresolved"],
            "archived_matches_processed_before_cutoff": archive_rows,
            "malformed_source_rows_ignored": malformed_rows,
        },
        "players": players,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
