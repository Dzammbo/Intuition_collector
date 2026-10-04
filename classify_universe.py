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


def participant_name(event, side):
    value = event.get(side) or {}
    return str(value.get("name") or "").strip()


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


def main():
    universe = json.load(open("universe.json", encoding="utf-8"))
    buckets = {
        "TENNIS_SINGLES": [],
        "EXCLUDED_DOUBLES": [],
        "EXCLUDED_NON_TENNIS": [],
        "TECHNICAL_EXCLUSION": [],
    }
    reasons = {}
    for event in universe.get("window_events") or []:
        status, reason = classify(event)
        row = dict(event)
        row["scope_status"] = status
        row["scope_reason"] = reason
        buckets[status].append(row)
        reasons[reason] = reasons.get(reason, 0) + 1

    output = {
        "schema_version": 3,
        "stage": "TENNIS_SINGLES_SCOPE_CLASSIFICATION",
        "source_captured_at": universe["captured_at"],
        "raw_window_event_count": len(universe.get("window_events") or []),
        "window_event_count": sum(len(value) for value in buckets.values()),
        "counts": {key: len(value) for key, value in buckets.items()},
        "classification_audit": reasons,
        "tiering_used": False,
        "events": buckets,
    }
    open("classified-universe.json", "w", encoding="utf-8").write(
        json.dumps(output, ensure_ascii=False)
    )
    print(json.dumps({"counts": output["counts"], "classification_audit": reasons}))


if __name__ == "__main__":
    main()
