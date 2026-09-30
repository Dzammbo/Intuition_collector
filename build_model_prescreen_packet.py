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

    if not odds_ids or not view_ids or any(not value for value in odds_ids + view_ids):
        raise SystemExit("missing event identity")
    if len(odds_ids) != len(set(odds_ids)):
        raise SystemExit("duplicate event in L1 odds")
    if len(view_ids) != len(set(view_ids)):
        raise SystemExit("duplicate event in Event View")
    if not set(view_ids).issubset(set(odds_ids)):
        missing_odds = sorted(set(view_ids) - set(odds_ids))
        raise SystemExit(f"Event View contains events missing from L1: {missing_odds}")

    l1_expected = int(odds.get("input_total") or 0)
    if l1_expected != len(odds_rows):
        raise SystemExit("L1 total accounting mismatch")
    view_expected = int(event_view.get("input_total") or 0)
    if view_expected != len(view_rows):
        raise SystemExit("Event View total accounting mismatch")
    if int(event_view.get("input_core") or 0) != int(odds.get("input_core") or 0):
        raise SystemExit("CORE accounting mismatch")
    if int(event_view.get("input_secondary") or 0) != int(odds.get("input_secondary") or 0):
        raise SystemExit("SECONDARY accounting mismatch")

    odds_map = {event_id(row): row for row in odds_rows}
    view_map = {event_id(row): row for row in view_rows}
    selected_odds_rows = [odds_map[eid] for eid in view_ids]

    cards = []
    for ordinal, row in enumerate(sorted(selected_odds_rows, key=start_key), 1):
        eid = event_id(row)
        source_tier = view_map[eid].get("source_tier") or row.get("source_tier")
        cards.append(
            {
                "ordinal": ordinal,
                "event_id": eid,
                "source_tier": source_tier,
                "sport_id": row.get("sport_id"),
                "league": row.get("league"),
                "home": row.get("home"),
                "away": row.get("away"),
                "start_time": row.get("time"),
                "raw_odds": row.get("odds") or {},
                "event_view": view_map[eid],
            }
        )

    tier_counts = {
        "CORE": sum(card.get("source_tier") == "CORE" for card in cards),
        "SECONDARY": sum(card.get("source_tier") == "SECONDARY" for card in cards),
    }
    if tier_counts["CORE"] != int(event_view.get("input_core") or 0):
        raise SystemExit("packet CORE tier mismatch")
    if tier_counts["SECONDARY"] != int(event_view.get("promoted_secondary") or 0):
        raise SystemExit("packet promoted SECONDARY tier mismatch")

    output = {
        "schema_version": 3,
        "stage": "MODEL_PRESCREEN_PACKET",
        "input": len(cards),
        "ordering": "START_TIME_ASC_EVENT_ID_ASC",
        "rule": "Lossless handoff from saved L1 odds + tier-aware Event View. No new provider calls.",
        "source_accounting": {
            "l1_records_total": len(odds_rows),
            "l1_core": int(odds.get("input_core") or 0),
            "l1_secondary": int(odds.get("input_secondary") or 0),
            "event_view_records": len(view_rows),
            "packet_core": tier_counts["CORE"],
            "packet_promoted_secondary": tier_counts["SECONDARY"],
            "secondary_not_promoted": int(event_view.get("not_promoted_secondary") or 0),
            "source_errors": 0,
        },
        "secondary_promotion_audit": event_view.get("promotion_audit") or [],
        "cards": cards,
    }
    open("model-prescreen-packet.json", "w", encoding="utf-8").write(
        json.dumps(output, ensure_ascii=False)
    )
    print(json.dumps({"cards": len(cards), "tiers": tier_counts, "ordering": output["ordering"]}))


if __name__ == "__main__":
    main()
