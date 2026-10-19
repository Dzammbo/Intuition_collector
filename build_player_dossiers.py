#!/usr/bin/env python3
"""Build baseline player history and a separate match-specific context layer.

This collector intentionally does not call the result a full multi-source dossier.
The baseline layer contains provider identity, Valuebetennis history-derived metrics
and complete ATP/WTA singles ranking snapshots. Event View is consumed only through
a prematch-safe whitelist and is stored in a separate match-context snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
DOSSIER_FEATURE_SCHEMA_VERSION = 4


def normalise(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def ranking_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(sorted(re.findall(r"[a-z0-9]+", text.casefold())))


def name_tokens(value: object) -> frozenset[str]:
    """Return an order-independent identity token set for conservative alias recovery."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return frozenset(re.findall(r"[a-z0-9]+", text.casefold()))


def resolve_archive_name_key(canonical_name: str, archive_names: list[str]) -> tuple[str | None, str]:
    """Resolve exact names first, then one unique multi-token subset alias.

    The fallback repairs common provider/archive differences such as a missing middle
    given name or reversed token order. Ambiguous candidates remain unresolved.
    """
    exact = normalise(canonical_name)
    exact_candidates = sorted({name for name in archive_names if normalise(name) == exact})
    if len(exact_candidates) == 1:
        return exact, "EXACT_NORMALIZED_NAME"
    wanted = name_tokens(canonical_name)
    if len(wanted) < 2:
        return None, "UNRESOLVED_IN_VALUEBETENNIS_ARCHIVE"
    candidates = []
    for candidate in archive_names:
        tokens = name_tokens(candidate)
        if len(tokens) < 2:
            continue
        if tokens <= wanted or wanted <= tokens:
            candidates.append(candidate)
    candidates = sorted(set(candidates))
    if len(candidates) == 1:
        return normalise(candidates[0]), "UNIQUE_MULTI_TOKEN_SUBSET_ALIAS"
    if candidates:
        return None, "AMBIGUOUS_MULTI_TOKEN_SUBSET_ALIAS"
    return None, "UNRESOLVED_IN_VALUEBETENNIS_ARCHIVE"


def parse_stamp(value: str) -> datetime:
    text = str(value or "").strip().strip('"')
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_float(value: object) -> float | None:
    try:
        parsed = float(str(value or "").replace(",", "."))
    except ValueError:
        return None
    return parsed if parsed > 1.0 else None


def score_sets(score: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in re.findall(r"(?<!\d)(\d{1,2})-(\d{1,2})", str(score or ""))]


def is_retirement(score: str) -> bool:
    value = str(score or "").casefold()
    return any(token in value for token in ("ret", "abandon", "walkover", "w/o", "wo"))


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


def elo_expected(rating: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent - rating) / 400.0))


def load_archive(paths: list[str], cutoff: datetime) -> tuple[list[dict], int]:
    rows: list[dict] = []
    malformed = 0
    for filename in paths:
        with Path(filename).open(encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle, delimiter=";"):
                try:
                    when = parse_stamp(source.get("date") or "")
                except (TypeError, ValueError):
                    malformed += 1
                    continue
                if when >= cutoff or not source.get("joueur1") or not source.get("joueur2"):
                    continue
                rows.append({
                    "match_id": str(source.get("match_id") or ""),
                    "date_utc": iso(when),
                    "tournament": str(source.get("tournoi") or UNKNOWN),
                    "category": str(source.get("categorie") or UNKNOWN),
                    "surface": str(source.get("surface") or UNKNOWN).upper(),
                    "round": str(source.get("tour") or UNKNOWN),
                    "duration_minutes": (
                        int(source["duree_min"]) if str(source.get("duree_min") or "").isdigit() else UNKNOWN
                    ),
                    "joueur1": str(source["joueur1"]),
                    "joueur1_id": str(source.get("joueur1_id") or UNKNOWN),
                    "joueur2": str(source["joueur2"]),
                    "joueur2_id": str(source.get("joueur2_id") or UNKNOWN),
                    "vainqueur_id": str(source.get("vainqueur_id") or UNKNOWN),
                    "score": str(source.get("score") or ""),
                    "gender": str(source.get("genre") or UNKNOWN).upper(),
                    "closing_odds_1": as_float(source.get("cote1_cloture")),
                    "closing_odds_2": as_float(source.get("cote2_cloture")),
                })
    return rows, malformed


def apply_archive_elo(rows: list[dict]) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    global_ratings: dict[str, float] = defaultdict(lambda: ELO_START)
    surface_ratings: dict[tuple[str, str], float] = defaultdict(lambda: ELO_START)
    for row in sorted(rows, key=lambda item: (item["date_utc"], item["match_id"])):
        p1, p2 = normalise(row["joueur1"]), normalise(row["joueur2"])
        r1, r2 = global_ratings[p1], global_ratings[p2]
        s1, s2 = surface_ratings[(p1, row["surface"])], surface_ratings[(p2, row["surface"])]
        row["joueur1_pre_elo"], row["joueur2_pre_elo"] = round(r1, 1), round(r2, 1)
        won = str(row["vainqueur_id"]) == str(row["joueur1_id"])
        actual = 1.0 if won else 0.0
        global_ratings[p1] = r1 + ELO_K * (actual - elo_expected(r1, r2))
        global_ratings[p2] = r2 + ELO_K * ((1.0 - actual) - elo_expected(r2, r1))
        surface_ratings[(p1, row["surface"])] = s1 + ELO_K * (actual - elo_expected(s1, s2))
        surface_ratings[(p2, row["surface"])] = s2 + ELO_K * ((1.0 - actual) - elo_expected(s2, s1))
    return dict(global_ratings), dict(surface_ratings)


def result_for(row: dict, player_key: str) -> tuple[str, str]:
    if player_key == normalise(row["joueur1"]):
        won = str(row["vainqueur_id"]) == str(row["joueur1_id"])
        return ("W" if won else "L"), row["joueur2"]
    won = str(row["vainqueur_id"]) == str(row["joueur2_id"])
    return ("W" if won else "L"), row["joueur1"]


def closing_odds_for(row: dict, player_key: str) -> float | None:
    return row["closing_odds_1"] if player_key == normalise(row["joueur1"]) else row["closing_odds_2"]


def opponent_pre_elo_for(row: dict, player_key: str) -> float | None:
    value = row["joueur2_pre_elo"] if player_key == normalise(row["joueur1"]) else row["joueur1_pre_elo"]
    return float(value) if isinstance(value, (int, float)) else None


def player_pre_elo_for(row: dict, player_key: str) -> float | None:
    value = row["joueur1_pre_elo"] if player_key == normalise(row["joueur1"]) else row["joueur2_pre_elo"]
    return float(value) if isinstance(value, (int, float)) else None


def compact_matches(matches: list[dict], player_key: str, take: int) -> dict:
    detail = []
    wins = 0
    for row in matches[:take]:
        result, opponent = result_for(row, player_key)
        wins += result == "W"
        detail.append({
            "date_utc": row["date_utc"],
            "result": result,
            "opponent": opponent,
            "tournament": row["tournament"],
            "category": row["category"],
            "surface": row["surface"],
            "round": row["round"],
            "score": row["score"] or UNKNOWN,
            "duration_minutes": row["duration_minutes"],
            "closing_odds": closing_odds_for(row, player_key) or UNKNOWN,
            "opponent_pre_match_archive_elo": opponent_pre_elo_for(row, player_key) or UNKNOWN,
            "player_pre_match_archive_elo": player_pre_elo_for(row, player_key) or UNKNOWN,
        })
    return {"matches": len(detail), "wins": wins, "losses": len(detail) - wins, "detail": detail}


def descriptive_window(matches: list[dict], player_key: str, cutoff: datetime, days: int) -> dict:
    rows = [row for row in matches if 0 <= (cutoff - parse_stamp(row["date_utc"])).days <= days]
    durations = [
        float(row["duration_minutes"]) for row in rows
        if isinstance(row.get("duration_minutes"), (int, float))
    ]
    wins = sum(result_for(row, player_key)[0] == "W" for row in rows)
    return {
        "calendar_window_days": days,
        "matches": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "match_days": len({parse_stamp(row["date_utc"]).date().isoformat() for row in rows}),
        "known_duration_count": len(durations),
        "known_duration_total_minutes": round(sum(durations), 1) if durations else UNKNOWN,
        "known_duration_average_minutes": (
            round(sum(durations) / len(durations), 1) if durations else UNKNOWN
        ),
    }


def latest_consecutive_match_days(matches: list[dict]) -> int:
    days = sorted({parse_stamp(row["date_utc"]).date() for row in matches}, reverse=True)
    if not days:
        return 0
    streak = 1
    for newer, older in zip(days, days[1:]):
        if (newer - older).days != 1:
            break
        streak += 1
    return streak


def ranking_timeline(ranking: dict | None, previous_record: dict | None) -> tuple[list[dict], object]:
    previous_history = ((previous_record or {}).get("baseline_history") or {}).get("ranking_history")
    timeline = [dict(row) for row in previous_history] if isinstance(previous_history, list) else []
    if not ranking:
        return timeline, UNKNOWN
    observation = {
        "observed_at_utc": ranking.get("retrieved_at_utc") or UNKNOWN,
        "rank": ranking.get("current_rank") or UNKNOWN,
        "points": ranking.get("ranking_points") or UNKNOWN,
        "tour": ranking.get("tour") or UNKNOWN,
        "source": ranking.get("source") or UNKNOWN,
    }
    if not timeline or timeline[-1] != observation:
        timeline.append(observation)
    previous_rank = next(
        (row.get("rank") for row in reversed(timeline[:-1]) if isinstance(row.get("rank"), int)),
        None,
    )
    current_rank = observation["rank"] if isinstance(observation["rank"], int) else None
    movement = ({
        "previous_rank": previous_rank,
        "current_rank": current_rank,
        "positions_improved": previous_rank - current_rank,
        "interpretation": "POSITIVE_MEANS_IMPROVED",
    } if previous_rank is not None and current_rank is not None else UNKNOWN)
    return timeline, movement


def load_rankings(paths: list[str]) -> tuple[dict[str, list[dict]], list[dict]]:
    rankings: defaultdict[str, list[dict]] = defaultdict(list)
    sources = []
    for filename in paths:
        payload = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        if payload.get("provider_response_complete") is not True:
            raise ValueError(f"ranking snapshot is not provider-response-complete: {filename}")
        if payload.get("full_ranking_coverage") is not True:
            raise ValueError(f"ranking snapshot is not full-coverage: {filename}")
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise ValueError(f"ranking snapshot has no results list: {filename}")
        for row in rows:
            name = str(row.get("name") or "").strip()
            if name and isinstance(row.get("ranking"), int):
                rankings[ranking_key(name)].append({
                    "current_rank": row.get("ranking") or UNKNOWN,
                    "ranking_points": row.get("points") or UNKNOWN,
                    "ranking_country": row.get("country") or UNKNOWN,
                    "ranking_name": name,
                    "tour": row.get("tour") or UNKNOWN,
                    "source": payload.get("source") or UNKNOWN,
                    "retrieved_at_utc": payload.get("retrieved_at_utc") or UNKNOWN,
                    "match_method": "EXACT_NORMALIZED_TOKEN_SET_NAME",
                })
        sources.append({
            "source": payload.get("source") or UNKNOWN,
            "source_url": payload.get("source_url") or UNKNOWN,
            "file": Path(filename).name,
            "pages_requested": payload.get("pages_requested"),
            "rows": len(rows),
            "provider_response_complete": True,
            "full_ranking_coverage": True,
        })
    return dict(rankings), sources


def load_profiles(path: str) -> tuple[dict[str, dict], dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("stage") != "TENNIS_PLAYER_STATIC_PROFILE_SNAPSHOT":
        raise ValueError("profile snapshot has incompatible stage")
    rows = payload.get("players")
    if not isinstance(rows, list):
        raise ValueError("profile snapshot has no players list")
    profiles: dict[str, dict] = {}
    for row in rows:
        player_id = str(row.get("provider_player_id") or "").strip()
        if not player_id or player_id in profiles:
            raise ValueError("profile snapshot player ids must be non-empty and unique")
        profiles[player_id] = row
    return profiles, {
        "source": payload.get("source") or UNKNOWN,
        "source_url": payload.get("source_url") or UNKNOWN,
        "file": Path(path).name,
        "retrieved_at_utc": payload.get("retrieved_at_utc") or UNKNOWN,
        "players_requested": payload.get("players_requested"),
        "profiles_resolved": payload.get("profiles_resolved"),
    }


def age_on(date_of_birth: object, cutoff: datetime) -> int | str:
    if not isinstance(date_of_birth, str) or date_of_birth == UNKNOWN:
        return UNKNOWN
    try:
        born = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
    except ValueError:
        return UNKNOWN
    day = cutoff.date()
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def static_identity(profile: dict | None, player: dict, cutoff: datetime) -> dict:
    profile = profile or {}
    fields = profile.get("fields") if isinstance(profile.get("fields"), dict) else {}
    status = str(profile.get("status") or "UNRESOLVED")
    source = str(profile.get("source") or UNKNOWN)
    url = str(profile.get("profile_url") or UNKNOWN)
    dob = fields.get("date_of_birth") or UNKNOWN
    nationality = fields.get("nationality") or player.get("provider_country_code") or UNKNOWN
    return {
        "aliases": [player["canonical_name"]],
        "date_of_birth": dob,
        "age_at_history_cutoff": age_on(dob, cutoff),
        "source_reported_age_at_profile_retrieval": fields.get("source_reported_age") or UNKNOWN,
        "nationality": nationality,
        "handedness": fields.get("handedness") or UNKNOWN,
        "height_cm": fields.get("height_cm") or UNKNOWN,
        "weight_kg": fields.get("weight_kg") or UNKNOWN,
        "sex": fields.get("sex") or UNKNOWN,
        "profile_current_singles_rank": fields.get("current_singles_rank") or UNKNOWN,
        "profile_highest_singles_rank": fields.get("highest_singles_rank") or UNKNOWN,
        "profile_resolution_status": status,
        "profile_source": source,
        "profile_url": url,
        "field_provenance": {
            key: ({"source": source, "url": url} if fields.get(key) not in (None, "", UNKNOWN) else UNKNOWN)
            for key in ("date_of_birth", "nationality", "handedness", "height_cm", "weight_kg", "sex")
        },
        "identity_resolution": "PROVIDER_ID_CANONICAL_NAME_AND_STATIC_PROFILE",
    }


def resolve_ranking(player: dict, rankings: dict[str, list[dict]]) -> tuple[dict | None, str]:
    candidates = rankings.get(ranking_key(player["canonical_name"])) or []
    if not candidates:
        return None, "NO_EXACT_NAME_MATCH_IN_COMPLETE_ATP_WTA_SNAPSHOTS"
    if len(candidates) > 1:
        return None, "AMBIGUOUS_EXACT_NAME_MATCH_IN_COMPLETE_ATP_WTA_SNAPSHOTS"
    return candidates[0], "EXACT_NAME_MATCH_IN_COMPLETE_ATP_WTA_SNAPSHOT"


def load_previous_history(path: str | None) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("stage") != "BASELINE_PLAYER_HISTORY_REGISTRY":
        raise ValueError("previous player history has incompatible stage")
    return {str(row["provider_player_id"]): row for row in payload.get("players") or []}


def load_prior_system_decisions(root: str | None, before_date_moscow: str | None) -> dict[str, dict]:
    if not root:
        return {}
    if not before_date_moscow:
        raise ValueError("--card-date-moscow is required with --prior-system-diagnostics-root")
    directory = Path(root)
    if not directory.exists():
        return {}
    by_id: dict[str, dict] = {}
    for path in sorted(directory.glob("*-intermediate.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        date_moscow = str(payload.get("date_moscow") or "")
        if not date_moscow or date_moscow >= before_date_moscow:
            continue
        checked_at = payload.get("checked_at") or UNKNOWN
        for row in payload.get("results") or []:
            population = str(row.get("population") or "")
            if population not in {"BET", "SUBSTANTIVE_PASS"}:
                continue
            decision_id = str(row.get("decision_id") or "").strip()
            selected_player = str(row.get("selection") or "").strip()
            if not decision_id or not selected_player:
                continue
            compact = {
                "decision_id": decision_id,
                "date_moscow": date_moscow,
                "population": population,
                "event_id": str(row.get("event_id") or UNKNOWN),
                "event": row.get("event") or UNKNOWN,
                "competition": row.get("competition") or UNKNOWN,
                "selected_player": selected_player,
                "captured_odds": row.get("captured_odds") if row.get("captured_odds") is not None else UNKNOWN,
                "result": row.get("result") or UNKNOWN,
                "profit_units": row.get("profit_units") if row.get("profit_units") is not None else UNKNOWN,
                "start_time": row.get("start_time") or UNKNOWN,
                "last_checked_at": checked_at,
                "source_file": path.name,
            }
            old = by_id.get(decision_id)
            if old is None or str(old.get("last_checked_at")) <= str(checked_at):
                by_id[decision_id] = compact
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for row in by_id.values():
        grouped[normalise(row["selected_player"])].append(row)
    output = {}
    terminal = {"WIN", "LOSS", "PUSH", "HALF_WIN", "HALF_LOSS", "VOID"}
    for key, rows in grouped.items():
        streams = {}
        for population in ("BET", "SUBSTANTIVE_PASS"):
            stream_rows = sorted(
                (row for row in rows if row["population"] == population),
                key=lambda row: (row["date_moscow"], row["decision_id"]),
            )
            result_counts = Counter(str(row["result"]) for row in stream_rows)
            known_profit = [
                float(row["profit_units"]) for row in stream_rows
                if isinstance(row.get("profit_units"), (int, float))
            ]
            streams[population] = {
                "decisions": len(stream_rows),
                "resolved": sum(str(row["result"]) in terminal for row in stream_rows),
                "results": dict(sorted(result_counts.items())),
                "known_price_count": sum(isinstance(row.get("captured_odds"), (int, float)) for row in stream_rows),
                "known_profit_units_total": round(sum(known_profit), 4) if known_profit else UNKNOWN,
                "records": stream_rows,
            }
        output[key] = {
            "match_method": "EXACT_NORMALIZED_SELECTED_PLAYER_NAME",
            "source_scope": "AVAILABLE_CHECK_ONLY_INTERMEDIATE_FILES_BEFORE_CARD_DATE",
            "regime_homogeneity": UNKNOWN,
            "policy": {
                "bet_and_substantive_pass_are_separate_streams": True,
                "combined_performance_is_not_computed": True,
            },
            "streams": streams,
        }
    return output


def history_fingerprint(
    player: dict, matches: list[dict], ranking: dict | None, profile: dict | None,
    prior_system_decisions: dict | None = None,
) -> str:
    stable_profile = ({
        "status": profile.get("status"),
        "source": profile.get("source"),
        "profile_url": profile.get("profile_url"),
        "fields": profile.get("fields"),
    } if profile else None)
    source = {
        "dossier_feature_schema_version": DOSSIER_FEATURE_SCHEMA_VERSION,
        "provider_player_id": player["provider_player_id"],
        "canonical_name": player["canonical_name"],
        "provider_country_code": player["provider_country_code"],
        "ranking": ranking,
        "static_profile": stable_profile,
        "prior_system_decisions": prior_system_decisions,
        "matches": [
            [row["match_id"], row["date_utc"], row["vainqueur_id"], row["score"],
             row["closing_odds_1"], row["closing_odds_2"]]
            for row in matches
        ],
    }
    raw = json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_history_record(
    player: dict,
    matches: list[dict],
    ranking: dict | None,
    global_elo: dict[str, float],
    surface_elo: dict[tuple[str, str], float],
    cutoff: datetime,
    fingerprint: str,
    profile: dict | None,
    previous_record: dict | None = None,
    prior_system_decisions: dict | None = None,
) -> dict:
    key = player.get("archive_name_key") or normalise(player["canonical_name"])
    if any(key not in {normalise(row["joueur1"]), normalise(row["joueur2"])} for row in matches):
        raise ValueError("resolved archive identity is absent from a supplied history row")
    opponent_elos = [
        value for row in matches[:20]
        if (value := opponent_pre_elo_for(row, key)) is not None
    ]
    known_durations = [
        float(row["duration_minutes"]) for row in matches[:20]
        if isinstance(row.get("duration_minutes"), (int, float))
    ]
    known_dates = [row["date_utc"] for row in matches[:20] if row.get("date_utc")]
    surface: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    retirements = 0
    score_rows = []
    score_matches = []
    price_stats: defaultdict[str, dict] = defaultdict(
        lambda: {"matches": 0, "wins": 0, "losses": 0, "profit_units_flat_stake": 0.0}
    )
    for row in matches:
        result, _ = result_for(row, key)
        if row["surface"] != UNKNOWN:
            surface[row["surface"]][0 if result == "W" else 1] += 1
        retirements += is_retirement(row["score"])
        sets = score_sets(row["score"])
        if sets:
            oriented = sets if key == normalise(row["joueur1"]) else [(b, a) for a, b in sets]
            score_rows.append(oriented)
            score_matches.append((result, oriented))
        odds = closing_odds_for(row, key)
        if odds:
            band = price_stats[price_band(odds)]
            band["matches"] += 1
            band["wins"] += result == "W"
            band["losses"] += result == "L"
            band["profit_units_flat_stake"] += odds - 1.0 if result == "W" else -1.0

    for values in price_stats.values():
        values["profit_units_flat_stake"] = round(values["profit_units_flat_stake"], 2)
        values["roi_pct_flat_stake"] = round(
            100.0 * values["profit_units_flat_stake"] / values["matches"], 1
        )
    genders = Counter(row["gender"] for row in matches if row["gender"] != UNKNOWN)
    latest = parse_stamp(matches[0]["date_utc"]) if matches else None
    tiebreak_sets = sum(sum({a, b} == {6, 7} for a, b in sets) for sets in score_rows)
    deciding = [sets for sets in score_rows if len(sets) >= 3]
    deciding_wins = sum(sets[-1][0] > sets[-1][1] for sets in deciding)
    sets_won = sum(a > b for sets in score_rows for a, b in sets)
    sets_lost = sum(a < b for sets in score_rows for a, b in sets)
    games_won = sum(a for sets in score_rows for a, _ in sets)
    games_lost = sum(b for sets in score_rows for _, b in sets)
    tiebreak_sets_won = sum(
        a > b for sets in score_rows for a, b in sets if {a, b} == {6, 7}
    )
    clean_wins = sum(result == "W" and all(a > b for a, b in sets) for result, sets in score_matches)
    clean_losses = sum(result == "L" and all(a < b for a, b in sets) for result, sets in score_matches)
    recent = matches[:20]
    strength_rows = []
    for row in recent:
        result, opponent = result_for(row, key)
        player_elo = player_pre_elo_for(row, key)
        opponent_elo = opponent_pre_elo_for(row, key)
        if player_elo is not None and opponent_elo is not None:
            strength_rows.append((result, opponent, round(opponent_elo - player_elo, 1)))
    ranking_history, ranking_movement = ranking_timeline(ranking, previous_record)
    recent_by_surface: dict[str, dict] = {}
    for surface_name in sorted({row["surface"] for row in recent if row["surface"] != UNKNOWN}):
        surface_rows = [row for row in recent if row["surface"] == surface_name]
        wins = sum(result_for(row, key)[0] == "W" for row in surface_rows)
        recent_by_surface[surface_name] = {
            "matches": len(surface_rows), "wins": wins, "losses": len(surface_rows) - wins,
            "detail": compact_matches(surface_rows, key, len(surface_rows))["detail"],
        }
    quality = {
        "historical_matches": len(matches),
        "last_20_rows": len(recent),
        "last_20_with_score": sum(bool(score_sets(row["score"])) for row in recent),
        "last_20_with_duration": len(known_durations),
        "last_20_with_opponent_archive_elo": len(opponent_elos),
        "ranking_available": ranking is not None,
        "static_profile_resolved": (profile or {}).get("status") == "RESOLVED",
        "latest_completed_match_utc": iso(latest),
        "source_freshness_at_cutoff_days": (
            (cutoff.date() - latest.date()).days if latest else UNKNOWN
        ),
        "limitations": sorted({
            *([] if ranking else ["CURRENT_RANKING_UNRESOLVED"]),
            *([] if matches else ["NO_ARCHIVE_MATCH_HISTORY"]),
            *([] if known_durations else ["NO_KNOWN_MATCH_DURATION_IN_LAST_20"]),
            *([] if (profile or {}).get("status") == "RESOLVED" else ["STATIC_PROFILE_UNRESOLVED"]),
            "SERVE_RETURN_POINT_DATA_NOT_IN_ARCHIVE",
            "CURRENT_HEALTH_REQUIRES_SOURCED_EVENT_RESEARCH",
            "TRAVEL_TIME_ZONE_NOT_COMPUTED",
        }),
    }

    return {
        **player,
        "source_fingerprint": fingerprint,
        "history_cutoff_utc": iso(cutoff),
        "identity": {
            **static_identity(profile, player, cutoff),
            "observed_gender": genders.most_common(1)[0][0] if genders else UNKNOWN,
        },
        "source_resolution": {
            "historical_name_match": player.get(
                "historical_resolution_method",
                "EXACT_NORMALIZED_NAME" if matches else "UNRESOLVED_IN_VALUEBETENNIS_ARCHIVE",
            ),
            "historical_matches_found": len(matches),
            "match_data_source": SOURCE_NAME if matches else UNKNOWN,
        },
        "baseline_history": {
            "ranking_and_movement": ({
                **ranking,
                "ranking_movement": ranking_movement,
                "source": ranking.get("source") or UNKNOWN,
            } if ranking else UNKNOWN),
            "ranking_history": ranking_history or UNKNOWN,
            "ranking_reason": (
                "EXACT_NAME_MATCH_IN_COMPLETE_ATP_WTA_SNAPSHOT; MOVEMENT_DERIVED_FROM_PERSISTED_OBSERVATIONS_WHEN_AVAILABLE"
                if ranking else player.get("ranking_resolution_reason")
            ),
            "last_5": compact_matches(matches, key, 5),
            "last_10": compact_matches(matches, key, 10),
            "last_20": compact_matches(matches, key, 20),
            "last_20_by_surface": recent_by_surface or UNKNOWN,
            "surface_record": {
                name: {"wins": values[0], "losses": values[1], "matches": sum(values)}
                for name, values in sorted(surface.items())
            } or UNKNOWN,
            "archive_strength_context": ({
                "model": "ARCHIVE_ELO_K24_START1500_FROM_2024",
                "current_archive_elo": round(global_elo.get(key, ELO_START), 1),
                "current_surface_archive_elo": {
                    name: round(surface_elo[(key, name)], 1)
                    for name in sorted(surface) if (key, name) in surface_elo
                } or UNKNOWN,
                "last_20_average_opponent_pre_match_archive_elo": (
                    round(sum(opponent_elos) / len(opponent_elos), 1) if opponent_elos else UNKNOWN
                ),
                "last_20_opponents_with_archive_elo": len(opponent_elos),
                "last_20_matches_with_both_pre_match_elos": len(strength_rows),
                "last_20_wins_over_higher_rated_opponents": sum(
                    result == "W" and difference > 0 for result, _, difference in strength_rows
                ),
                "last_20_losses_to_lower_rated_opponents": sum(
                    result == "L" and difference < 0 for result, _, difference in strength_rows
                ),
                "last_20_average_opponent_minus_player_elo": (
                    round(sum(row[2] for row in strength_rows) / len(strength_rows), 1)
                    if strength_rows else UNKNOWN
                ),
                "role": "STRENGTH_PROXY_NOT_OFFICIAL_RANKING",
            } if matches else UNKNOWN),
            "score_derived_metrics": ({
                "matches_with_score": len(score_rows),
                "tiebreak_sets_played": tiebreak_sets,
                "tiebreak_sets_won": tiebreak_sets_won,
                "deciding_sets_played": len(deciding),
                "deciding_sets_won": deciding_wins,
                "deciding_set_win_pct": round(100.0 * deciding_wins / len(deciding), 1) if deciding else UNKNOWN,
                "sets_won": sets_won,
                "sets_lost": sets_lost,
                "games_won": games_won,
                "games_lost": games_lost,
                "wins_without_losing_a_set": clean_wins,
                "losses_without_winning_a_set": clean_losses,
                "serve_points_and_hold_rate": UNKNOWN,
                "return_points_and_break_rate": UNKNOWN,
            } if score_rows else UNKNOWN),
            "retirement_walkover_evidence": {
                "flagged_results_in_archive": retirements,
                "supported_injury_information": UNKNOWN,
            },
            "workload_and_rest": {
                "calendar_windows": {
                    str(days): descriptive_window(matches, key, cutoff, days)
                    for days in (3, 7, 14, 30)
                },
                "matches_previous_7_days": descriptive_window(matches, key, cutoff, 7)["matches"],
                "matches_previous_30_days": descriptive_window(matches, key, cutoff, 30)["matches"],
                "latest_completed_match_utc": iso(latest),
                "calendar_days_rest_at_frozen_cutoff": ((cutoff.date() - latest.date()).days if latest else UNKNOWN),
                "latest_consecutive_match_days": latest_consecutive_match_days(matches),
                "last_20_known_duration_count": len(known_durations),
                "last_20_known_duration_total_minutes": (
                    round(sum(known_durations), 1) if known_durations else UNKNOWN
                ),
                "last_20_known_duration_average_minutes": (
                    round(sum(known_durations) / len(known_durations), 1)
                    if known_durations else UNKNOWN
                ),
                "latest_known_tournament": matches[0]["tournament"] if matches else UNKNOWN,
                "latest_known_surface": matches[0]["surface"] if matches else UNKNOWN,
                "last_20_tournament_sequence": list(dict.fromkeys(
                    row["tournament"] for row in matches[:20] if row["tournament"] != UNKNOWN
                )),
                "travel_and_time_zone": UNKNOWN,
            },
            "sample_stability": {
                "historical_matches_found": len(matches),
                "last_20_rows_available": min(20, len(matches)),
                "last_20_rows_with_score": sum(bool(score_sets(row["score"])) for row in matches[:20]),
                "last_20_rows_with_duration": len(known_durations),
                "last_20_rows_with_opponent_elo": len(opponent_elos),
                "last_20_date_span": ({
                    "newest": max(known_dates), "oldest": min(known_dates)
                } if known_dates else UNKNOWN),
            },
            "historical_performance_by_price_band": dict(sorted(price_stats.items())) or UNKNOWN,
            "prior_system_decisions": prior_system_decisions or UNKNOWN,
            "data_quality": quality,
        },
    }


def prematch_safe_event_context(row: dict, materialized_at: datetime) -> dict:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    stadium = extra.get("stadium_data") if isinstance(extra.get("stadium_data"), dict) else {}
    return {
        "event_id": str(row.get("id") or ""),
        "provider_current_event_id": str(row.get("provider_current_event_id") or row.get("id") or ""),
        "scheduled_start_utc": iso(datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)),
        "tournament": (row.get("league") or {}).get("name") or UNKNOWN,
        "tournament_id": str((row.get("league") or {}).get("id") or UNKNOWN),
        "surface": extra.get("ground") or UNKNOWN,
        "round": extra.get("round") or UNKNOWN,
        "format_best_of_sets": extra.get("bestofsets") or UNKNOWN,
        "venue": ({
            "name": stadium.get("name") or UNKNOWN,
            "city": stadium.get("city") or UNKNOWN,
            "country": stadium.get("country") or UNKNOWN,
        } if stadium else UNKNOWN),
        "home": {key: (row.get("home") or {}).get(key) for key in ("id", "name", "cc")},
        "away": {key: (row.get("away") or {}).get(key) for key in ("id", "name", "cc")},
        "bet365_event_id": row.get("bet365_id") or UNKNOWN,
        "identity_correction": row.get("identity_correction") or None,
        "event_view_materialized_at_utc": iso(materialized_at),
        "excluded_live_fields": [
            "time_status", "ss", "points", "playing_indicator", "stats", "events", "scores",
            "inplay_created_at", "inplay_updated_at", "confirmed_at", "o_home", "o_away",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--event-view", required=True)
    parser.add_argument("--matches", nargs="+", required=True)
    parser.add_argument("--materialized-at-utc", required=True)
    parser.add_argument("--ranking-snapshots", nargs="+", required=True)
    parser.add_argument("--profile-snapshot", required=True)
    parser.add_argument("--previous-player-history")
    parser.add_argument("--prior-system-diagnostics-root")
    parser.add_argument("--card-date-moscow")
    parser.add_argument("--history-output", required=True)
    parser.add_argument("--snapshot-output", required=True)
    parser.add_argument("--match-context-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    args = parser.parse_args()

    universe = json.loads(Path(args.universe).read_text(encoding="utf-8-sig"))
    event_view = json.loads(Path(args.event_view).read_text(encoding="utf-8-sig"))
    cutoff = parse_stamp(universe["source_captured_at"])
    materialized_at = parse_stamp(args.materialized_at_utc)
    events = universe.get("events", {}).get("TENNIS_SINGLES") or []
    expected_ids = [str(event.get("id") or "") for event in events]
    if event_view.get("stage") != "TENNIS_SINGLES_EVENT_VIEW":
        raise ValueError("Event View artifact has incompatible stage")
    if event_view.get("completed") != len(events):
        raise ValueError("Event View is incomplete for the frozen singles universe")
    event_rows = event_view.get("records") or []
    by_event = {str(row.get("id") or ""): row for row in event_rows}
    if len(by_event) != len(event_rows) or set(by_event) != set(expected_ids):
        raise ValueError("Event View does not provide one-to-one universe coverage")

    roster: dict[str, dict] = {}
    for event in events:
        for side in ("home", "away"):
            raw = event.get(side) or {}
            player_id = str(raw.get("id") or "").strip()
            name = str(raw.get("name") or "").strip()
            if player_id and name:
                roster.setdefault(player_id, {
                    "provider_player_id": player_id,
                    "canonical_name": name,
                    "provider_country_code": raw.get("cc") or UNKNOWN,
                })

    archive_rows, malformed_rows = load_archive(args.matches, cutoff)
    global_elo, surface_elo = apply_archive_elo(archive_rows)
    by_name: defaultdict[str, list[dict]] = defaultdict(list)
    for row in archive_rows:
        by_name[normalise(row["joueur1"])].append(row)
        by_name[normalise(row["joueur2"])].append(row)
    for key in by_name:
        unique = {
            row["date_utc"] + "|" + row["joueur1_id"] + "|" + row["joueur2_id"]: row
            for row in by_name[key]
        }
        by_name[key] = sorted(unique.values(), key=lambda item: item["date_utc"], reverse=True)

    rankings, ranking_sources = load_rankings(args.ranking_snapshots)
    profiles, profile_source = load_profiles(args.profile_snapshot)
    previous = load_previous_history(args.previous_player_history)
    prior_system_index = load_prior_system_decisions(
        args.prior_system_diagnostics_root, args.card_date_moscow
    )
    merged = dict(previous)
    current_records = []
    reused = rebuilt = 0
    archive_names = sorted({
        str(row[name_field])
        for row in archive_rows
        for name_field in ("joueur1", "joueur2")
        if row.get(name_field)
    })
    for player_id, player in sorted(roster.items(), key=lambda item: (normalise(item[1]["canonical_name"]), item[0])):
        archive_key, history_resolution = resolve_archive_name_key(
            player["canonical_name"], archive_names
        )
        matches = by_name.get(archive_key, []) if archive_key else []
        player["archive_name_key"] = archive_key
        player["historical_resolution_method"] = history_resolution
        ranking, ranking_reason = resolve_ranking(player, rankings)
        profile = profiles.get(player_id)
        prior_system_decisions = prior_system_index.get(normalise(player["canonical_name"]))
        player["ranking_resolution_reason"] = ranking_reason
        fingerprint = history_fingerprint(
            player, matches, ranking, profile, prior_system_decisions
        )
        old = previous.get(player_id)
        if old and old.get("source_fingerprint") == fingerprint:
            record = old
            reused += 1
        else:
            record = build_history_record(
                player, matches, ranking, global_elo, surface_elo, cutoff, fingerprint, profile,
                old, prior_system_decisions,
            )
            rebuilt += 1
        merged[player_id] = record
        current_records.append(record)

    history_registry = {
        "schema_version": 3,
        "stage": "BASELINE_PLAYER_HISTORY_REGISTRY",
        "status": "BASELINE_ONLY_NOT_FULL_MULTI_SOURCE",
        "updated_at_utc": iso(materialized_at),
        "history_cutoff_utc": iso(cutoff),
        "policy": {
            "persistent_history_is_separate_from_match_context": True,
            "unchanged_player_records_are_reused_by_source_fingerprint": True,
            "missing_optional_metrics_do_not_exclude": True,
        },
        "players": sorted(merged.values(), key=lambda row: (normalise(row["canonical_name"]), row["provider_player_id"])),
    }
    daily_snapshot = {
        "schema_version": 3,
        "stage": "BASELINE_PLAYER_HISTORY_SNAPSHOT",
        "status": "BASELINE_ONLY_NOT_FULL_MULTI_SOURCE",
        "frozen_data_cutoff_utc": iso(cutoff),
        "materialized_at_utc": iso(materialized_at),
        "sources": [{
            "source": SOURCE_NAME,
            "url": VALUEBETENNIS_URL,
            "used_result_cutoff_utc": iso(cutoff),
            "confidence": "SECONDARY_OPEN_DATA_FILTERED_TO_FROZEN_CUTOFF",
        }] + ranking_sources + [profile_source],
        "coverage": {
            "eligible_matches": len(events),
            "unique_players": len(current_records),
            "players_with_historical_match_data": sum(
                row["source_resolution"]["historical_matches_found"] > 0 for row in current_records
            ),
            "players_with_complete_provider_ranking_match": sum(
                row["baseline_history"]["ranking_and_movement"] != UNKNOWN for row in current_records
            ),
            "players_with_resolved_static_profile": sum(
                row["identity"]["profile_resolution_status"] == "RESOLVED" for row in current_records
            ),
            "players_with_date_of_birth": sum(
                row["identity"]["date_of_birth"] != UNKNOWN for row in current_records
            ),
            "players_with_age": sum(
                row["identity"]["age_at_history_cutoff"] != UNKNOWN
                or row["identity"]["source_reported_age_at_profile_retrieval"] != UNKNOWN
                for row in current_records
            ),
            "players_with_handedness": sum(
                row["identity"]["handedness"] != UNKNOWN for row in current_records
            ),
            "players_with_ranking_history": sum(
                row["baseline_history"].get("ranking_history") != UNKNOWN for row in current_records
            ),
            "players_with_comparable_opponent_strength": sum(
                isinstance(row["baseline_history"].get("archive_strength_context"), dict)
                and row["baseline_history"]["archive_strength_context"].get(
                    "last_20_matches_with_both_pre_match_elos", 0
                ) > 0
                for row in current_records
            ),
            "players_with_known_duration_in_last_20": sum(
                row["baseline_history"]["data_quality"]["last_20_with_duration"] > 0
                for row in current_records
            ),
            "players_with_prior_system_decisions": sum(
                row["baseline_history"].get("prior_system_decisions") != UNKNOWN
                for row in current_records
            ),
            "persistent_records_reused": reused,
            "persistent_records_rebuilt": rebuilt,
            "archive_matches_processed_before_cutoff": len(archive_rows),
            "malformed_source_rows_ignored": malformed_rows,
        },
        "players": current_records,
    }
    match_context = {
        "schema_version": 3,
        "stage": "MATCH_SPECIFIC_DOSSIER_CONTEXT",
        "status": "EVENT_VIEW_PREMATCH_SAFE_FIELDS_ONLY",
        "materialized_at_utc": iso(materialized_at),
        "event_view_input_singles": event_view.get("input_singles"),
        "event_view_completed": event_view.get("completed"),
        "event_view_errors": event_view.get("errors") or [],
        "events": [],
    }
    for event in events:
        event_id = str(event["id"])
        context = prematch_safe_event_context(by_event[event_id], materialized_at)
        context["player_history_refs"] = [
            str((event.get("home") or {}).get("id") or ""),
            str((event.get("away") or {}).get("id") or ""),
        ]
        match_context["events"].append(context)

    manifest = {
        "schema_version": 3,
        "stage": "BASELINE_PLAYER_DOSSIER_MANIFEST",
        "status": "READY",
        "classification": "BASELINE_DOSSIER_NOT_FULL_MULTI_SOURCE",
        "materialized_at_utc": iso(materialized_at),
        "layers": {
            "persistent_player_history": str(args.history_output),
            "immutable_card_history_snapshot": str(args.snapshot_output),
            "match_specific_event_view_context": str(args.match_context_output),
        },
        "coverage": {
            "eligible_matches": len(events),
            "match_contexts": len(match_context["events"]),
            "current_players": len(current_records),
            "ranking_provider_responses_complete": all(
                item["provider_response_complete"] for item in ranking_sources
            ),
            "ranking_full_coverage": all(
                item["full_ranking_coverage"] for item in ranking_sources
            ),
            "static_profiles_requested": profile_source["players_requested"],
            "static_profiles_resolved": profile_source["profiles_resolved"],
        },
    }

    write_json(args.history_output, history_registry)
    write_json(args.snapshot_output, daily_snapshot)
    write_json(args.match_context_output, match_context)
    write_json(args.manifest_output, manifest)
    print(json.dumps({**manifest["coverage"], "reused": reused, "rebuilt": rebuilt}, ensure_ascii=False))


if __name__ == "__main__":
    main()

