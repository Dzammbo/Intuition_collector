#!/usr/bin/env python3
"""Create immutable live handoffs from already-frozen prematch assessments."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def first(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", default="state")
    root = Path(parser.parse_args().state_root)
    out_dir = root / "live_tennis" / "prematch_handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    built = skipped = 0
    for source in sorted((root / "price_blind_assessments").glob("*/*event-*.json")):
        try:
            row = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        event_id = str(row.get("event_id") or "")
        if not event_id:
            skipped += 1
            continue
        frozen_at = first(row, "frozen_at_utc", "created_at_utc", "assessed_at_utc")
        handoff = {"schema_version": 1, "event_id": event_id, "status": "FROZEN_PREMATCH_OPINION",
            "frozen_at_utc": frozen_at, "decision": first(row, "research_decision", "decision", "sporting_verdict") or "UNKNOWN",
            "selected_side": first(row, "selected_side", "supported_side", "lean") or "UNKNOWN",
            "qualitative_confidence": first(row, "qualitative_confidence", "confidence") or "UNKNOWN",
            "thesis": first(row, "thesis", "sporting_thesis", "primary_thesis") or "UNKNOWN",
            "principal_counterargument": first(row, "principal_counterargument", "counterargument", "main_risk") or "UNKNOWN",
            "victory_scenarios": first(row, "victory_scenarios", "win_scenarios") or [],
            "live_confirmation_indicators": first(row, "live_confirmation_indicators") or [],
            "live_refutation_indicators": first(row, "live_refutation_indicators") or [],
            "player_refs": row.get("player_refs") or [], "prematch_price": first(row, "captured_price", "entry_odds"),
            "prematch_price_time": first(row, "price_captured_at_utc", "entry_odds_time_utc"),
            "gaps": first(row, "research_gaps", "gaps") or [], "source_ref": str(source.relative_to(root)),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "historical_record_rewritten": False}
        destination = out_dir / f"event-{event_id}.json"
        if destination.exists():
            existing = json.loads(destination.read_text(encoding="utf-8"))
            if existing.get("source_sha256") == handoff["source_sha256"]:
                continue
            if existing.get("frozen_at_utc") and frozen_at and existing["frozen_at_utc"] > frozen_at:
                continue
        destination.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        built += 1
    receipt = {"schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "built_or_updated": built, "skipped_unreadable": skipped, "source": "immutable price_blind_assessments"}
    (out_dir / "manifest.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
