#!/usr/bin/env python3
"""Apply the canonical deep-research timing gate to every enriched tennis event."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUT_STAGE = "TENNIS_PRE_DEEP_RESEARCH_ENRICHMENT"
OUTPUT_STAGE = "DEEP_RESEARCH_TIMING_CHECK"
PASS_REASON = "DEEP_RESEARCH_TIME_GATE"
THRESHOLD_SECONDS = 1200


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value}")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build(source: dict[str, Any], checked_at: datetime) -> dict[str, Any]:
    if source.get("stage") != INPUT_STAGE:
        raise ValueError(f"input stage must be {INPUT_STAGE}")
    events = source.get("events")
    if not isinstance(events, list):
        raise ValueError("input events must be a list")
    checked_at = checked_at.astimezone(timezone.utc)
    checked_at_text = iso_utc(checked_at)
    rows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        context = event.get("match_context") if isinstance(event.get("match_context"), dict) else {}
        scheduled_text = str(context.get("scheduled_start_utc") or "")
        if not event_id or not scheduled_text:
            raise ValueError(f"event lacks identity or scheduled start: {event_id or 'UNKNOWN'}")
        scheduled = parse_utc(scheduled_text)
        seconds_to_start = int((scheduled - checked_at).total_seconds())
        time_gate = seconds_to_start < THRESHOLD_SECONDS
        player_refs = [
            str(player.get("player_id") or "")
            for player in (event.get("players") or [])
            if isinstance(player, dict)
        ]
        row: dict[str, Any] = {
            "event_id": event_id,
            "scheduled_start_utc": iso_utc(scheduled),
            "check_timestamp_utc": checked_at_text,
            "signed_seconds_to_start": seconds_to_start,
            "player_refs": player_refs,
            "source_enrichment_status": event.get("status"),
            "timing_status": "PASS" if time_gate else "CLEARED_FOR_PRICE_BLIND_SPORTING_FREEZE",
            "time_gate_applied": time_gate,
            "live_information_consulted": False,
        }
        if time_gate:
            row["reason"] = PASS_REASON
        rows.append(row)
    rows.sort(key=lambda row: (row["scheduled_start_utc"], row["event_id"]))
    passed = sum(row["time_gate_applied"] for row in rows)
    return {
        "schema_version": 1,
        "stage": OUTPUT_STAGE,
        "status": "SUCCESS",
        "check_timestamp_utc": checked_at_text,
        "threshold_seconds_strictly_less_than": THRESHOLD_SECONDS,
        "source_enrichment_sha256": fingerprint(source),
        "ordering": "SCHEDULED_START_ASC_EVENT_ID_ASC",
        "coverage": {
            "input_events": len(events),
            "output_events": len(rows),
            "time_gate_pass": passed,
            "cleared_for_price_blind_sporting_freeze": len(rows) - passed,
        },
        "policy": {
            "checked_only_at_deep_research_entry": True,
            "started_or_strictly_less_than_20_minutes_is_pass": True,
            "live_score_odds_or_results_used": False,
            "row_level_pass_never_stops_run": True,
        },
        "events": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checked-at-utc")
    args = parser.parse_args()
    checked_at = parse_utc(args.checked_at_utc) if args.checked_at_utc else datetime.now(timezone.utc)
    payload = build(read_json(args.input), checked_at)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
