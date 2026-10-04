#!/usr/bin/env python3
"""Create a deterministic Moscow-date singles subset for an isolated architecture test."""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

source_path, day, limit_raw, output_path = sys.argv[1:5]
limit = int(limit_raw)
source = json.load(open(source_path, encoding="utf-8"))
rows = []
for event in source.get("events", {}).get("TENNIS_SINGLES", []):
    stamp = int(event["time"])
    local_day = datetime.fromtimestamp(stamp, ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Moscow")).date().isoformat()
    if local_day == day:
        rows.append(event)
rows.sort(key=lambda e: (int(e["time"]), str(e.get("id") or "")))
selected = rows[:limit]
out = {
    "schema_version": 1,
    "stage": "TENNIS_SINGLES_ARCHITECTURE_TEST_SUBSET",
    "date_moscow": day,
    "selection_rule": "EARLIEST_START_THEN_EVENT_ID",
    "requested_limit": limit,
    "available_singles_for_day": len(rows),
    "window_event_count": len(selected),
    "raw_window_event_count": len(selected),
    "tiering_used": False,
    "counts": {
        "TENNIS_SINGLES": len(selected),
        "EXCLUDED_DOUBLES": 0,
        "EXCLUDED_NON_TENNIS": 0,
        "TECHNICAL_EXCLUSION": 0,
    },
    "events": {
        "TENNIS_SINGLES": selected,
        "EXCLUDED_DOUBLES": [],
        "EXCLUDED_NON_TENNIS": [],
        "TECHNICAL_EXCLUSION": [],
    },
}
json.dump(out, open(output_path, "w", encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"available": len(rows), "selected": len(selected), "day": day}))
