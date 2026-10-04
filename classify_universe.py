#!/usr/bin/env python3
"""Classify every real tennis event by singles eligibility, without league tiers."""

import json
import re

NON_TENNIS = re.compile(
    r"\b(?:padel|table tennis|beach tennis|virtual|esports?|e-tennis|simulated|battle of)\b",
    re.I,
)
DOUBLES_LEAGUE = re.compile(
    r"(?:\b(?:doubles?|mixed doubles?)\b|\s(?:md|wd|xd)\s*$)",
    re.I,
)
PAIR_NAME = re.compile(r"(?:\s[/&+]\s|/|\s(?:and|и)\s)", re.I)
DUPLICATE_TIME_TOLERANCE_SECONDS = 8 * 60 * 60


def participant_name(event, side):
    value = event.get(side) or {}
    return str(value.get("name") or "").strip()


def participant_key(event, side):
    value = event.get(side) or {}
    pid = str(value.get("id") or "").strip()
    name = participant_name(event, side).casefold()
    return "id:" + pid if pid else "name:" + name


def classify(event):
    league = str((event.get("league") or {}).get("name") or "").strip()
    home = participant_name(event, "home")
    away = participant_name(event, "away")
    if int(event.get("sport_id") or 0) != 13 or NON_TENNIS.search(league):
        return "EXCLUDED_NON_TENNIS", "NOT_REAL_RACKET_TENNIS"
    if not home or not away or home.casefold() == away.casefold():
        return "TECHNICAL_EXCLUSION", "MISSING_OR_INVALID_PARTICIPANTS"
    if DOUBLES_LEAGUE.search(league) or PAIR_NAME.search(home) or PAIR_NAME.search(away):
        return "EXCLUDED_DOUBLES", "DOUBLES_IDENTITY"
    return "TENNIS_SINGLES", "ALL_REAL_SINGLES_INCLUDED"


def duplicate_group_key(event):
    league = event.get("league") or {}
    league_key = str(league.get("id") or league.get("name") or "").strip().casefold()
    pair = tuple(sorted((participant_key(event, "home"), participant_key(event, "away"))))
    return league_key, pair


def canonical_score(event):
    return (
        1 if event.get("bet365_id") else 0,
        1 if (event.get("home") or {}).get("id") and (event.get("away") or {}).get("id") else 0,
        1 if event.get("round") not in (None, "") else 0,
        int(event.get("id") or 0),
    )


def remove_duplicate_listings(buckets):
    singles = buckets["TENNIS_SINGLES"]
    groups = {}
    for event in singles:
        groups.setdefault(duplicate_group_key(event), []).append(event)

    keep = []
    duplicates = []
    for group in groups.values():
        ordered = sorted(group, key=lambda event: int(event.get("time") or 0))
        clusters = []
        for event in ordered:
            stamp = int(event.get("time") or 0)
            if not clusters or stamp - int(clusters[-1][-1].get("time") or 0) > DUPLICATE_TIME_TOLERANCE_SECONDS:
                clusters.append([event])
            else:
                clusters[-1].append(event)
        for cluster in clusters:
            canonical = max(cluster, key=canonical_score)
            keep.append(canonical)
            for event in cluster:
                if event is canonical:
                    continue
                row = dict(event)
                row["scope_status"] = "TECHNICAL_EXCLUSION"
                row["scope_reason"] = "DUPLICATE_SINGLES_LISTING"
                row["canonical_event_id"] = str(canonical.get("id"))
                duplicates.append(row)

    buckets["TENNIS_SINGLES"] = sorted(keep, key=lambda e: (int(e.get("time") or 0), str(e.get("id") or "")))
    buckets["TECHNICAL_EXCLUSION"].extend(duplicates)


def main():
    universe = json.load(open("universe.json", encoding="utf-8"))
    buckets = {
        "TENNIS_SINGLES": [],
        "EXCLUDED_DOUBLES": [],
        "EXCLUDED_NON_TENNIS": [],
        "TECHNICAL_EXCLUSION": [],
    }
    for event in universe.get("window_events") or []:
        status, reason = classify(event)
        row = dict(event)
        row["scope_status"] = status
        row["scope_reason"] = reason
        buckets[status].append(row)

    remove_duplicate_listings(buckets)
    reasons = {}
    for values in buckets.values():
        for event in values:
            reason = event["scope_reason"]
            reasons[reason] = reasons.get(reason, 0) + 1

    output = {
        "schema_version": 4,
        "stage": "TENNIS_SINGLES_SCOPE_CLASSIFICATION",
        "source_captured_at": universe["captured_at"],
        "raw_window_event_count": len(universe.get("window_events") or []),
        "window_event_count": sum(len(value) for value in buckets.values()),
        "counts": {key: len(value) for key, value in buckets.items()},
        "classification_audit": reasons,
        "tiering_used": False,
        "duplicate_policy": {
            "identity": "LEAGUE_AND_UNORDERED_PLAYER_PAIR",
            "time_tolerance_seconds": DUPLICATE_TIME_TOLERANCE_SECONDS,
            "canonical_preference": "BET365_ID_THEN_COMPLETE_IDS_THEN_ROUND_THEN_EVENT_ID",
        },
        "events": buckets,
    }
    open("classified-universe.json", "w", encoding="utf-8").write(
        json.dumps(output, ensure_ascii=False)
    )
    print(json.dumps({"counts": output["counts"], "classification_audit": reasons}))


if __name__ == "__main__":
    main()
