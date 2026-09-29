#!/usr/bin/env python3
import json
import sys


def event_id(row):
    return str(row.get("event_id") or row.get("id") or "")


def start_key(row):
    raw = row.get("time")
    try:
        timestamp = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"invalid start time for event {event_id(row)}: {raw!r}")
    return timestamp, event_id(row)


def main():
    odds = json.load(open(sys.argv[1], encoding="utf-8"))
    event_view = json.load(open(sys.argv[2], encoding="utf-8"))

    if odds.get("errors") or event_view.get("errors"):
        raise SystemExit("source enrichment contains errors")

    odds_rows = odds.get("records") or []
    view_rows = event_view.get("records") or []
    odds_ids = [event_id(row) for row in odds_rows]
    view_ids = [event_id(row) for row in view_rows]

    if not odds_ids or any(not value for value in odds_ids + view_ids):
        raise SystemExit("missing event identity")
    if len(odds_ids) != len(set(odds_ids)):
        raise SystemExit("duplicate event in L1 odds")
    if len(view_ids) != len(set(view_ids)):
        raise SystemExit("duplicate event in Event View")
    if set(odds_ids) != set(view_ids):
        missing_view = sorted(set(odds_ids) - set(view_ids))
        missing_odds = sorted(set(view_ids) - set(odds_ids))
        raise SystemExit(
            f"L1/Event View identity mismatch: missing_view={missing_view} missing_odds={missing_odds}"
        )

    expected = int(odds.get("input_core") or 0)
    if expected != len(odds_rows) or int(event_view.get("input_core") or 0) != expected:
        raise SystemExit("CORE accounting mismatch")

    view_map = {event_id(row): row for row in view_rows}
    cards = []
    for ordinal, row in enumerate(sorted(odds_rows, key=start_key), 1):
        eid = event_id(row)
        raw_odds = row.get("odds") or {}
        cards.append(
            {
                "ordinal": ordinal,
                "event_id": eid,
                "sport_id": row.get("sport_id"),
                "league": row.get("league"),
                "home": row.get("home"),
                "away": row.get("away"),
                "start_time": row.get("time"),
                "raw_odds": raw_odds,
                "event_view": view_map[eid],
            }
        )

    output = {
        "schema_version": 2,
        "stage": "MODEL_PRESCREEN_PACKET",
        "input": len(cards),
        "ordering": "START_TIME_ASC_EVENT_ID_ASC",
        "rule": "Lossless handoff from saved L1 odds + Event View. No new provider calls.",
        "source_accounting": {
            "l1_records": len(odds_rows),
            "event_view_records": len(view_rows),
            "unique_events": len(set(odds_ids)),
            "source_errors": 0,
        },
        "cards": cards,
    }
    open("model-prescreen-packet.json", "w", encoding="utf-8").write(
        json.dumps(output, ensure_ascii=False)
    )
    print(json.dumps({"cards": len(cards), "ordering": output["ordering"]}))


if __name__ == "__main__":
    main()
