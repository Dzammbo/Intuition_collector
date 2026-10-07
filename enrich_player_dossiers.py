#!/usr/bin/env python3
"""Build a non-scoring, event-specific dossier enrichment before deep research.

The output reorganizes frozen prematch-safe facts and explicit external observations.
It never assigns a side, probability, score, BET/PASS label, or eligibility gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UNKNOWN = "UNKNOWN"
STAGE = "TENNIS_PRE_DEEP_RESEARCH_ENRICHMENT"


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def known(value: Any) -> bool:
    return value not in (None, "", UNKNOWN)


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def surface_key(value: Any) -> str:
    text = re.sub(r"[^a-z]+", " ", str(value or "").casefold()).strip()
    if "clay" in text or "terre battue" in text:
        return "TERRE BATTUE"
    if "grass" in text or "gazon" in text:
        return "GAZON"
    if "carpet" in text or "moquette" in text:
        return "MOQUETTE"
    if "hard" in text or text == "dur":
        return "DUR"
    return str(value or UNKNOWN).upper()


def baseline_of(player: dict[str, Any]) -> dict[str, Any]:
    value = player.get("baseline_history")
    if isinstance(value, dict):
        return value
    value = player.get("snapshot")
    return value if isinstance(value, dict) else {}


def current_elo(history: dict[str, Any]) -> float | None:
    strength = history.get("archive_strength_context")
    if not isinstance(strength, dict):
        strength = history.get("opponent_strength_context")
    if not isinstance(strength, dict):
        return None
    return as_number(strength.get("current_archive_elo"))


def detail_rows(history: dict[str, Any]) -> list[dict[str, Any]]:
    last20 = history.get("last_20")
    rows = (last20 or {}).get("detail") if isinstance(last20, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def exact_surface_view(history: dict[str, Any], event_surface: Any) -> dict[str, Any]:
    key = surface_key(event_surface)
    records = history.get("surface_record")
    strength = history.get("archive_strength_context")
    if not isinstance(strength, dict):
        strength = history.get("opponent_strength_context")
    if not isinstance(strength, dict):
        strength = {}
    ratings = (strength or {}).get("current_surface_archive_elo")
    record = records.get(key, UNKNOWN) if isinstance(records, dict) else UNKNOWN
    rating = ratings.get(key, UNKNOWN) if isinstance(ratings, dict) else UNKNOWN
    matching = [row for row in detail_rows(history) if surface_key(row.get("surface")) == key]
    return {
        "event_surface_raw": event_surface or UNKNOWN,
        "archive_surface_key": key,
        "record": record,
        "archive_surface_elo": rating,
        "last_20_matching_surface_results": matching,
        "status": "AVAILABLE" if known(record) or known(rating) or matching else "UNAVAILABLE",
    }


def opponent_quality_view(
    history: dict[str, Any], opponent_history: dict[str, Any]
) -> dict[str, Any]:
    player_elo = current_elo(history)
    opponent_elo = current_elo(opponent_history)
    annotated = []
    known_elos = []
    for row in detail_rows(history):
        item = dict(row)
        past_elo = as_number(row.get("opponent_pre_match_archive_elo"))
        if past_elo is not None:
            known_elos.append(past_elo)
            item["difference_from_current_opponent_archive_elo"] = (
                round(past_elo - opponent_elo, 1) if opponent_elo is not None else UNKNOWN
            )
        else:
            item["difference_from_current_opponent_archive_elo"] = UNKNOWN
        annotated.append(item)
    if opponent_elo is not None:
        annotated.sort(key=lambda row: (
            abs(row["difference_from_current_opponent_archive_elo"])
            if isinstance(row["difference_from_current_opponent_archive_elo"], (int, float))
            else float("inf")
        ))
    return {
        "player_current_archive_elo": player_elo if player_elo is not None else UNKNOWN,
        "current_opponent_archive_elo": opponent_elo if opponent_elo is not None else UNKNOWN,
        "last_20_average_opponent_archive_elo": (
            round(sum(known_elos) / len(known_elos), 1) if known_elos else UNKNOWN
        ),
        "last_20_opponents_with_archive_elo": len(known_elos),
        "historical_matches_ordered_by_similarity_to_current_opponent": annotated,
        "similarity_note": "ABSOLUTE_ARCHIVE_ELO_DISTANCE_ONLY; NO_DECISION_THRESHOLD",
        "status": "AVAILABLE" if known_elos else "UNAVAILABLE",
    }


def workload_view(history: dict[str, Any]) -> dict[str, Any]:
    workload = history.get("workload_and_rest")
    if not isinstance(workload, dict):
        workload = history.get("workload_rest_travel_time_zone")
    rows = detail_rows(history)
    durations = [as_number(row.get("duration_minutes")) for row in rows]
    durations = [value for value in durations if value is not None]
    qualifying = [row for row in rows if re.search(r"(^|[^A-Z])Q(?:[1-9]|F)?($|[^A-Z])|QUAL", str(row.get("round") or "").upper())]
    latest = rows[0] if rows else {}
    return {
        "matches_previous_7_days": (workload or {}).get("matches_previous_7_days", UNKNOWN),
        "matches_previous_30_days": (workload or {}).get("matches_previous_30_days", UNKNOWN),
        "latest_completed_match_utc": (workload or {}).get("latest_completed_match_utc", UNKNOWN),
        "calendar_days_rest_at_frozen_cutoff": (workload or {}).get("calendar_days_rest_at_frozen_cutoff", UNKNOWN),
        "last_20_known_duration_count": len(durations),
        "last_20_known_duration_total_minutes": round(sum(durations), 1) if durations else UNKNOWN,
        "last_20_known_duration_average_minutes": round(sum(durations) / len(durations), 1) if durations else UNKNOWN,
        "archive_rows_marked_as_qualifying": qualifying,
        "latest_known_tournament": latest.get("tournament", UNKNOWN),
        "latest_known_match_surface": latest.get("surface", UNKNOWN),
        "status": "AVAILABLE" if workload or durations or rows else "UNAVAILABLE",
    }


def sample_view(player: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    identity = player.get("identity") if isinstance(player.get("identity"), dict) else {}
    rows = detail_rows(history)
    dates = [str(row.get("date_utc")) for row in rows if known(row.get("date_utc"))]
    score_metrics = history.get("score_derived_metrics")
    if not isinstance(score_metrics, dict):
        score_metrics = history.get("serve_return_hold_break_tiebreak_metrics")
    return {
        "date_of_birth": identity.get("date_of_birth", UNKNOWN),
        "age_at_frozen_cutoff": identity.get("age_at_history_cutoff", identity.get("source_reported_age_at_profile_retrieval", UNKNOWN)),
        "handedness": identity.get("handedness", UNKNOWN),
        "highest_published_singles_rank": identity.get("profile_highest_singles_rank", UNKNOWN),
        "historical_matches_found": (player.get("source_resolution") or {}).get("historical_matches_found", UNKNOWN),
        "last_20_rows_available": len(rows),
        "last_20_rows_with_score": sum(known(row.get("score")) for row in rows),
        "last_20_rows_with_duration": sum(as_number(row.get("duration_minutes")) is not None for row in rows),
        "last_20_rows_with_opponent_elo": sum(as_number(row.get("opponent_pre_match_archive_elo")) is not None for row in rows),
        "last_20_date_span": {"newest": max(dates), "oldest": min(dates)} if dates else UNKNOWN,
        "score_derived_sample": score_metrics or UNKNOWN,
    }


def external_for(observations: list[dict[str, Any]], event_id: str, player_id: str) -> dict[str, Any]:
    matched = [row for row in observations if str(row.get("event_id") or "") == event_id and str(row.get("player_id") or "") == player_id]
    for row in matched:
        sources = row.get("sources")
        if not isinstance(sources, list) or not sources or any(not isinstance(src, dict) or not known(src.get("source_ref")) for src in sources):
            raise ValueError(f"external observation for event {event_id} player {player_id} lacks exact source_ref")
    return {
        "observations": matched,
        "status": "AVAILABLE" if matched else "NOT_COLLECTED",
    }


def enrich_player(
    player: dict[str, Any], opponent: dict[str, Any], event: dict[str, Any],
    observations: list[dict[str, Any]], side: str,
) -> dict[str, Any]:
    history = baseline_of(player)
    opponent_history = baseline_of(opponent)
    player_id = str(player.get("provider_player_id") or "")
    external = external_for(observations, str(event["event_id"]), player_id)
    score_metrics = history.get("score_derived_metrics")
    if not isinstance(score_metrics, dict):
        score_metrics = history.get("serve_return_hold_break_tiebreak_metrics")
    retirement = history.get("retirement_walkover_evidence")
    workload = workload_view(history)
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    gaps = []
    if not isinstance(score_metrics, dict) or not known(score_metrics.get("serve_points_and_hold_rate")):
        gaps.append("SERVE_AND_HOLD")
    if not isinstance(score_metrics, dict) or not known(score_metrics.get("return_points_and_break_rate")):
        gaps.append("RETURN_AND_BREAK")
    if external["status"] == "NOT_COLLECTED":
        gaps.extend(["HEALTH_AND_READINESS", "CURRENT_NEWS"])
    if not known((venue or {}).get("city")) or not known(workload.get("latest_known_tournament")):
        gaps.append("TRAVEL_AND_TIME_ZONE")
    else:
        gaps.append("TRAVEL_DISTANCE_AND_TIME_ZONE_NOT_COMPUTED")
    return {
        "side": side,
        "player_id": player_id,
        "canonical_name": player.get("canonical_name") or UNKNOWN,
        "baseline_source_fingerprint": player.get("source_fingerprint") or UNKNOWN,
        "surface_form": exact_surface_view(history, event.get("surface")),
        "opponent_quality": opponent_quality_view(history, opponent_history),
        "serve_return": score_metrics or UNKNOWN,
        "workload_qualification_and_duration": workload,
        "travel_context": {
            "previous_tournament": workload.get("latest_known_tournament", UNKNOWN),
            "current_venue": venue or UNKNOWN,
            "distance_and_time_zone": UNKNOWN,
        },
        "comparable_style_and_level": {
            "player_handedness": (player.get("identity") or {}).get("handedness", UNKNOWN),
            "opponent_handedness": (opponent.get("identity") or {}).get("handedness", UNKNOWN),
            "level_comparison": opponent_quality_view(history, opponent_history),
            "style_comparison": "REQUIRES_VERIFIED_STYLE_OR_SERVE_RETURN_SOURCE",
        },
        "age_experience_and_sample": sample_view(player, history),
        "retirement_health_and_readiness": {
            "archive_evidence": retirement or UNKNOWN,
            "current_external_evidence": external,
        },
        "research_gaps": sorted(set(gaps)),
    }


def build(
    history_snapshot: dict[str, Any], match_context: dict[str, Any],
    external_observations: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if history_snapshot.get("stage") != "BASELINE_PLAYER_HISTORY_SNAPSHOT":
        raise ValueError("history snapshot has incompatible stage")
    if match_context.get("stage") != "MATCH_SPECIFIC_DOSSIER_CONTEXT":
        raise ValueError("match context has incompatible stage")
    players = {str(row.get("provider_player_id") or ""): row for row in history_snapshot.get("players") or []}
    observations = (external_observations or {}).get("observations") or []
    previous_by_event = {str(row.get("event_id") or ""): row for row in (previous or {}).get("events") or []}
    events = []
    reused = rebuilt = 0
    for event in match_context.get("events") or []:
        event_id = str(event.get("event_id") or "")
        home_id = str((event.get("home") or {}).get("id") or "")
        away_id = str((event.get("away") or {}).get("id") or "")
        missing = [player_id for player_id in (home_id, away_id) if player_id not in players]
        source = {"event": event, "players": [players.get(home_id), players.get(away_id)], "observations": [row for row in observations if str(row.get("event_id") or "") == event_id]}
        source_fingerprint = fingerprint(source)
        old = previous_by_event.get(event_id)
        if old and old.get("source_fingerprint") == source_fingerprint:
            events.append(old)
            reused += 1
            continue
        if missing:
            record = {"event_id": event_id, "status": "UNRESOLVED_PLAYER_IDENTITY", "missing_player_ids": missing, "source_fingerprint": source_fingerprint}
        else:
            record = {
                "event_id": event_id,
                "status": "READY_FOR_DEEP_RESEARCH",
                "source_fingerprint": source_fingerprint,
                "match_context": {key: event.get(key, UNKNOWN) for key in ("scheduled_start_utc", "tournament", "tournament_id", "surface", "round", "format_best_of_sets", "venue")},
                "players": [
                    enrich_player(players[home_id], players[away_id], event, observations, "HOME"),
                    enrich_player(players[away_id], players[home_id], event, observations, "AWAY"),
                ],
                "policy": {"non_scoring": True, "missing_optional_data_does_not_exclude": True, "deep_research_must_close_or_record_gaps": True},
            }
        events.append(record)
        rebuilt += 1
    return {
        "schema_version": 1,
        "stage": STAGE,
        "status": "READY",
        "materialized_at_utc": iso_now(),
        "frozen_data_cutoff_utc": history_snapshot.get("frozen_data_cutoff_utc", UNKNOWN),
        "coverage": {"input_events": len(match_context.get("events") or []), "output_events": len(events), "reused": reused, "rebuilt": rebuilt, "unresolved": sum(row.get("status") != "READY_FOR_DEEP_RESEARCH" for row in events)},
        "events": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-snapshot", required=True)
    parser.add_argument("--match-context", required=True)
    parser.add_argument("--external-observations")
    parser.add_argument("--previous-enrichment")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build(
        read_json(args.history_snapshot), read_json(args.match_context),
        read_json(args.external_observations) if args.external_observations else None,
        read_json(args.previous_enrichment) if args.previous_enrichment and Path(args.previous_enrichment).exists() else None,
    )
    write_json(args.output, payload)
    print(json.dumps(payload["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
