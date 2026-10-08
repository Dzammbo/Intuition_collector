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


def compact_player(player: dict[str, Any]) -> dict[str, Any]:
    surface = player.get("surface_form") if isinstance(player.get("surface_form"), dict) else {}
    quality = player.get("opponent_quality") if isinstance(player.get("opponent_quality"), dict) else {}
    workload = player.get("workload_qualification_and_duration") if isinstance(player.get("workload_qualification_and_duration"), dict) else {}
    sample = player.get("age_experience_and_sample") if isinstance(player.get("age_experience_and_sample"), dict) else {}
    readiness = player.get("retirement_health_and_readiness") if isinstance(player.get("retirement_health_and_readiness"), dict) else {}
    recent = quality.get("historical_matches_ordered_by_similarity_to_current_opponent")
    recent = recent if isinstance(recent, list) else []
    return {
        "side": player.get("side"),
        "player_id": player.get("player_id"),
        "canonical_name": player.get("canonical_name"),
        "current_archive_elo": quality.get("player_current_archive_elo"),
        "surface_record": surface.get("record"),
        "surface_archive_elo": surface.get("archive_surface_elo"),
        "surface_status": surface.get("status"),
        "highest_published_singles_rank": sample.get("highest_published_singles_rank"),
        "date_of_birth": sample.get("date_of_birth"),
        "age_at_frozen_cutoff": sample.get("age_at_frozen_cutoff"),
        "handedness": sample.get("handedness"),
        "historical_matches_found": sample.get("historical_matches_found"),
        "matches_previous_7_days": workload.get("matches_previous_7_days"),
        "matches_previous_30_days": workload.get("matches_previous_30_days"),
        "calendar_days_rest_at_frozen_cutoff": workload.get("calendar_days_rest_at_frozen_cutoff"),
        "latest_known_tournament": workload.get("latest_known_tournament"),
        "latest_known_match_surface": workload.get("latest_known_match_surface"),
        "score_derived_sample": sample.get("score_derived_sample"),
        "recent_archive_matches": recent[:10],
        "retirement_health_and_readiness": readiness,
        "research_gaps": player.get("research_gaps"),
    }


def compact_event(payload: dict[str, Any]) -> dict[str, Any]:
    baseline = payload["sporting_research_baseline"]
    return {
        "ordinal": payload["ordinal"],
        "event_id": payload["event_id"],
        "scheduled_start_utc": payload["timing_gate_record"].get("scheduled_start_utc"),
        "match_context": baseline.get("match_context"),
        "players": [compact_player(row) for row in baseline.get("players") or []],
        "input_content_sha256": payload["content_sha256"],
    }


def build(
    enrichment: dict[str, Any], timing: dict[str, Any], output_dir: Path,
    date_moscow: str | None = None,
) -> dict[str, Any]:
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
    compact_events = []
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
            "date_moscow": date_moscow or timing.get("date_moscow"),
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
        compact_events.append(compact_event(payload))
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
        "date_moscow": date_moscow or timing.get("date_moscow"),
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
        "compact_index_ref": "compact-research-index.json",
        "compact_batch_root": "compact-batches",
    }
    assert_market_redacted(manifest)
    compact_index = {
        "schema_version": 1,
        "stage": "PRICE_BLIND_SPORTING_COMPACT_RESEARCH_INDEX",
        "date_moscow": date_moscow or timing.get("date_moscow"),
        "market_data_redacted": True,
        "price_information_consulted": False,
        "coverage": {"events": len(compact_events)},
        "events": compact_events,
    }
    assert_market_redacted(compact_index)
    write_json(output_dir / "compact-research-index.json", compact_index)
    compact_batch_root = output_dir / "compact-batches"
    for start in range(0, len(compact_events), 25):
        batch_events = compact_events[start:start + 25]
        batch_number = start // 25 + 1
        write_json(
            compact_batch_root / f"batch-{batch_number:03d}.json",
            {
                "schema_version": 1,
                "stage": "PRICE_BLIND_SPORTING_COMPACT_RESEARCH_BATCH",
                "date_moscow": date_moscow or timing.get("date_moscow"),
                "batch_number": batch_number,
                "ordinal_start": batch_events[0]["ordinal"],
                "ordinal_end": batch_events[-1]["ordinal"],
                "market_data_redacted": True,
                "price_information_consulted": False,
                "coverage": {"events": len(batch_events)},
                "events": batch_events,
            },
        )
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enrichment", required=True)
    parser.add_argument("--timing", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--date-moscow", required=True)
    args = parser.parse_args()
    manifest = build(
        read_json(args.enrichment), read_json(args.timing), Path(args.output_dir),
        date_moscow=args.date_moscow,
    )
    print(json.dumps(manifest["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
