#!/usr/bin/env python3
"""Classify the saved 24-hour universe with audited dynamic-ID fallback."""

import glob
import json
import re
import unicodedata
from collections import defaultdict


TIERS = {"CORE", "SECONDARY", "EXCLUDE"}
TENNIS_PRO_PREFIX = re.compile(r"^(?:atp|wta|challenger|m\d{2,3}|w\d{2,3})\b", re.I)
TENNIS_BLOCKED = re.compile(
    r"\b(?:utr|junior|juniors|youth|u[- ]?\d{1,2}|wheelchair|"
    r"table tennis|padel|beach|exhibition|battle of)\b",
    re.I,
)
DRAW_SUFFIX = re.compile(r"\s+(?:md|wd|qual|qualification|qualifying)$", re.I)


def normalized_family(sport_id, name):
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    if sport_id == 13:
        text = re.sub(r"^itf\s+", "", text)
        while DRAW_SUFFIX.search(text):
            text = DRAW_SUFFIX.sub("", text).strip()
    return text


def load_registry():
    exact = {}
    families = defaultdict(list)
    for path in glob.glob("config/league_allowset_v1/*.json"):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = data.get("allowed_leagues", []) + data.get("leagues", [])
        for row in rows:
            tier = row.get("tier")
            if tier not in TIERS:
                continue
            sport_id = int(row["sport_id"])
            league_id = int(row["league_id"])
            name = row.get("league_name") or ""
            exact[(sport_id, league_id)] = (tier, row.get("tier_reason"))
            family = normalized_family(sport_id, name)
            if family:
                families[(sport_id, family)].append(
                    {"league_id": league_id, "league_name": name, "tier": tier}
                )
    return exact, families


def resolve_dynamic(sport_id, league_name, families):
    """Resolve only deterministic cases; ambiguous names remain quarantined."""
    family = normalized_family(sport_id, league_name)
    siblings = families.get((sport_id, family), [])
    sibling_tiers = {row["tier"] for row in siblings}
    if len(sibling_tiers) == 1:
        return sibling_tiers.pop(), "NORMALIZED_FAMILY", siblings

    if sport_id == 13 and not TENNIS_BLOCKED.search(league_name or ""):
        if TENNIS_PRO_PREFIX.search(family):
            return "CORE", "TENNIS_PRO_PREFIX", []

    return None, None, siblings


def main():
    universe = json.load(open("universe.json", encoding="utf-8"))
    exact, families = load_registry()
    buckets = {"CORE": [], "SECONDARY": [], "EXCLUDE": [], "UNCLASSIFIED_LEAGUE": []}
    audit = {"EXACT_ID": 0, "NORMALIZED_FAMILY": 0, "TENNIS_PRO_PREFIX": 0, "UNCLASSIFIED": 0}
    inferred = {}

    for event in universe["window_events"]:
        sport_id = int(event.get("sport_id") or 0)
        league = event.get("league") or {}
        try:
            league_id = int(league.get("id"))
        except (TypeError, ValueError):
            league_id = 0
        league_name = league.get("name") or ""
        record = exact.get((sport_id, league_id))
        if record:
            tier = record[0]
            method = "EXACT_ID"
            siblings = []
        else:
            tier, method, siblings = resolve_dynamic(sport_id, league_name, families)
            if tier is None:
                tier = "UNCLASSIFIED_LEAGUE"
                method = "UNCLASSIFIED"
            else:
                key = f"{sport_id}:{league_id}"
                inferred[key] = {
                    "sport_id": sport_id,
                    "league_id": league_id,
                    "league_name": league_name,
                    "tier": tier,
                    "method": method,
                    "matched_league_ids": sorted({row["league_id"] for row in siblings}),
                }
        audit[method] += 1
        buckets[tier].append(event)

    output = {
        "schema_version": 2,
        "source_captured_at": universe["captured_at"],
        "window_event_count": len(universe["window_events"]),
        "counts": {key: len(value) for key, value in buckets.items()},
        "classification_audit": audit,
        "inferred_leagues": sorted(inferred.values(), key=lambda row: (row["sport_id"], row["league_id"])),
        "events": buckets,
    }
    open("classified-universe.json", "w", encoding="utf-8").write(
        json.dumps(output, ensure_ascii=False)
    )
    print(json.dumps({"counts": output["counts"], "classification_audit": audit}))


if __name__ == "__main__":
    main()
