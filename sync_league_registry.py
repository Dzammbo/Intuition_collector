#!/usr/bin/env python3
"""Download the complete BetsAPI league registry for supported sports.

The League API is paginated by ``max_id`` (descending provider ID). The
result is joined with our exact canonical tier mapping. Unknown IDs stay
explicit and never acquire a tier through fuzzy name matching.
"""

import glob
import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


BASE = "https://api.b365api.com"
SPORTS = {
    13: "tennis",
    16: "baseball",
    17: "ice_hockey",
    18: "basketball",
}
OUTPUT_DIR = Path("config/league_registry_v1")
HISTORICAL_EXCLUDED_SPORTS = {1: "soccer"}


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def api_get(path, params, timeout=30):
    query = dict(params)
    query["token"] = os.environ["BETSAPI_TOKEN"]
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    last = None
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or payload.get("success") == 0:
                raise RuntimeError(f"BetsAPI error: {payload}")
            return payload
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(2 * attempt)
    raise last


def load_canonical_tiers():
    tiers = {}
    for filename in glob.glob("config/league_allowset_v1/*.json"):
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in data.get("allowed_leagues", []) + data.get("leagues", []):
            tier = row.get("tier")
            if tier not in {"CORE", "SECONDARY", "EXCLUDE"}:
                continue
            key = (int(row["sport_id"]), int(row["league_id"]))
            previous = tiers.get(key)
            if previous and previous["tier"] != tier:
                raise RuntimeError(f"conflicting canonical tier for {key}")
            tiers[key] = {
                "tier": tier,
                "tier_reason": row.get("tier_reason") or row.get("reason"),
            }
    return tiers


def normalize_league(row, sport_id, sport_name, tiers):
    league_id = int(row["id"])
    known = tiers.get((sport_id, league_id))
    return {
        "sport_id": sport_id,
        "sport": sport_name,
        "league_id": league_id,
        "league_name": row.get("name") or str(league_id),
        "country_code": row.get("cc"),
        "has_league_table": bool(int(row.get("has_leaguetable") or 0)),
        "has_toplist": bool(int(row.get("has_toplist") or 0)),
        "tier": known["tier"] if known else "UNCLASSIFIED_LEAGUE",
        "tier_reason": known["tier_reason"] if known else None,
    }


def collect_sport(sport_id, sport_name, tiers):
    rows_by_id = {}
    max_id = None
    calls = 0
    seen_cursors = set()
    while True:
        params = {"sport_id": sport_id}
        if max_id is not None:
            params["max_id"] = max_id
        payload = api_get("/v3/league", params)
        calls += 1
        rows = payload.get("results") or []
        if not rows:
            break
        for row in rows:
            if row.get("id") is not None:
                normalized = normalize_league(row, sport_id, sport_name, tiers)
                rows_by_id[normalized["league_id"]] = normalized
        pager = payload.get("pager") or {}
        cursor = pager.get("min_id")
        if cursor is None:
            cursor = min(int(row["id"]) for row in rows if row.get("id") is not None)
        cursor = int(cursor)
        if cursor <= 0:
            break
        if cursor in seen_cursors or (max_id is not None and cursor >= max_id):
            raise RuntimeError(f"pagination stalled for sport {sport_id} at {cursor}")
        seen_cursors.add(cursor)
        max_id = cursor
    leagues = sorted(rows_by_id.values(), key=lambda x: x["league_id"])
    print(json.dumps({"sport": sport_name, "leagues": len(leagues), "api_calls": calls}), flush=True)
    return leagues, calls


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main():
    if not os.environ.get("BETSAPI_TOKEN"):
        raise SystemExit("BETSAPI_TOKEN is required")
    captured_at = utcnow_iso()
    tiers = load_canonical_tiers()
    existing_catalog = OUTPUT_DIR / "catalog.json"
    historical_rows = []
    if existing_catalog.exists():
        saved = json.loads(existing_catalog.read_text(encoding="utf-8"))
        historical_rows = [
            row for row in saved.get("leagues", [])
            if int(row.get("sport_id") or 0) in HISTORICAL_EXCLUDED_SPORTS
        ]
    leagues = list(historical_rows)
    calls_by_sport = {}
    for sport_id, sport_name in SPORTS.items():
        sport_rows, calls = collect_sport(sport_id, sport_name, tiers)
        leagues.extend(sport_rows)
        calls_by_sport[sport_name] = calls

    present_keys = {(row["sport_id"], row["league_id"]) for row in leagues}
    missing_canonical = sorted(
        key for key in tiers if key[0] in SPORTS and key not in present_keys
    )
    tier_counts = Counter(row["tier"] for row in leagues)
    sport_counts = Counter(row["sport"] for row in leagues)
    unclassified = [row for row in leagues if row["tier"] == "UNCLASSIFIED_LEAGUE"]

    catalog = {
        "schema_version": 1,
        "source": "BetsAPI /v3/league",
        "captured_at": captured_at,
        "matching_key": ["sport_id", "league_id"],
        "leagues": leagues,
    }
    pending = {
        "schema_version": 1,
        "captured_at": captured_at,
        "rule": "Explicit review only; no fuzzy or automatic tier promotion.",
        "leagues": unclassified,
    }
    manifest = {
        "schema_version": 1,
        "captured_at": captured_at,
        "supported_sports": SPORTS,
        "historical_excluded_sports_retained_without_api_calls": HISTORICAL_EXCLUDED_SPORTS,
        "total_leagues": len(leagues),
        "counts_by_sport": dict(sorted(sport_counts.items())),
        "counts_by_tier": dict(sorted(tier_counts.items())),
        "api_calls_by_sport": calls_by_sport,
        "football_api_calls": 0,
        "canonical_tier_records_loaded": len(tiers),
        "canonical_ids_absent_from_provider_snapshot": [
            {"sport_id": sport_id, "league_id": league_id}
            for sport_id, league_id in missing_canonical
        ],
        "unknown_runtime_action": "QUARANTINE_WITHOUT_BLOCKING_DAILY_RUN",
    }
    write_json(OUTPUT_DIR / "catalog.json", catalog)
    write_json(OUTPUT_DIR / "unclassified.json", pending)
    write_json(OUTPUT_DIR / "manifest.json", manifest)
    print(json.dumps({"total": len(leagues), "tiers": tier_counts}, default=dict))


if __name__ == "__main__":
    main()
