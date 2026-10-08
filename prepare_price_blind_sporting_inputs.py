#!/usr/bin/env python3
"""Materialize one market-redacted sporting-research input per cleared event."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_TIMING_STATUS = "CLEARED_FOR_PRICE_BLIND_SPORTING_FREEZE"
OUTPUT_STAGE = "PRICE_BLIND_SPORTING_INPUTS"
FORBIDDEN_KEY_PARTS = (
    "odds",
    "price",
    "implied_probability",
    "bookmaker",
    "favorite",
    "underdog",
)
FORBIDDEN_EXACT_KEYS = {"ev", "expected_value"}
ALLOWED_CONTROL_KEYS = {
    "market_data_redacted",
    "price_information_consulted",
    "price_reveal_forbidden",
}


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def assert_market_redacted(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized not in ALLOWED_CONTROL_KEYS and (
                normalized in FORBIDDEN_EXACT_KEYS
                or any(part in normalized for part in FORBIDDEN_KEY_PARTS)
            ):
                raise ValueError(f"forbidden market-derived key at {path}.{key}")
            assert_market_redacted(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_market_redacted(child, f"{path}[{index}]")


def forbidden_key(key: Any) -> bool:
    normalized = str(key).casefold()
    return normalized not in ALLOWED_CONTROL_KEYS and (
        normalized in FORBIDDEN_EXACT_KEYS
        or any(part in normalized for part in FORBIDDEN_KEY_PARTS)
    )


def redact_market_fields(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        removed = 0
        for key, child in value.items():
            if forbidden_key(key):
                removed += 1
                continue
            clean_child, child_removed = redact_market_fields(child)
            redacted[key] = clean_child
            removed += child_removed
        return redacted, removed
    if isinstance(value, list):
        redacted_list = []
        removed = 0
        for child in value:
            clean_child, child_removed = redact_market_fields(child)
            redacted_list.append(clean_child)
            removed += child_removed
        return redacted_list, removed
    return value, 0


def build(enrichment: dict[str, Any], timing: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    if enrichment.get("stage") != "TENNIS_PRE_DEEP_RESEARCH_ENRICHMENT":
        raise ValueError("invalid enrichment stage")
    if timing.get("stage") != "DEEP_RESEARCH_TIMING_CHECK":
        raise ValueError("invalid timing stage")

    enriched = {str(row.get("event_id") or ""): row for row in enrichment.get("events") or []}
    cleared = [
        row for row in timing.get("events") or []
        if row.get("timing_status") == ALLOWED_TIMING_STATUS
    ]
    if len(cleared) != timing.get("coverage", {}).get("cleared_for_price_blind_sporting_freeze"):
        raise ValueError("cleared-event count does not reconcile")

    output_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for ordinal, timing_row in enumerate(cleared, 1):
        event_id = str(timing_row.get("event_id") or "")
        source = enriched.get(event_id)
        if not event_id or source is None:
            raise ValueError(f"missing enriched event {event_id or 'UNKNOWN'}")
        if source.get("status") != "READY_FOR_DEEP_RESEARCH":
            raise ValueError(f"event {event_id} is not ready for deep research")
        redacted_source, removed_market_fields = redact_market_fields(source)
        payload = {
            "schema_version": 1,
            "stage": "PRICE_BLIND_SPORTING_INPUT",
            "date_moscow": timing.get("date_moscow"),
            "ordinal": ordinal,
            "event_id": event_id,
            "market_data_redacted": True,
            "price_information_consulted": False,
            "timing_gate_record": timing_row,
            "sporting_research_baseline": redacted_source,
            "market_fields_removed_count": removed_market_fields,
            "requirements": {
                "fresh_event_specific_research_required": True,
                "structured_two_player_comparison_required": True,
                "sporting_side_may_remain_unsupported": True,
                "price_reveal_forbidden": True,
            },
        }
        assert_market_redacted(payload)
        payload["content_sha256"] = fingerprint(payload)
        relative = Path("events") / f"{ordinal:03d}-{event_id}.json"
        write_json(output_dir / relative, payload)
        items.append({
            "ordinal": ordinal,
            "event_id": event_id,
            "scheduled_start_utc": timing_row.get("scheduled_start_utc"),
            "input_ref": str(relative),
            "content_sha256": payload["content_sha256"],
        })

    manifest = {
        "schema_version": 1,
        "stage": OUTPUT_STAGE,
        "status": "READY",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date_moscow": timing.get("date_moscow"),
        "source_timing_check_sha256": fingerprint(timing),
        "source_enrichment_sha256": fingerprint(enrichment),
        "coverage": {
            "timing_input_events": len(timing.get("events") or []),
            "time_gate_pass": timing.get("coverage", {}).get("time_gate_pass"),
            "sporting_inputs": len(items),
        },
        "market_data_redacted": True,
        "price_information_consulted": False,
        "ordering": "TIMING_CHECK_ORDER",
        "events": items,
        "next_action": "MANUAL_PRICE_BLIND_SPORTING_RESEARCH_AND_FREEZE",
    }
    assert_market_redacted(manifest)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enrichment", required=True)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    manifest = build(read_json(args.enrichment), read_json(args.timing), Path(args.output_dir))
    print(json.dumps(manifest["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
