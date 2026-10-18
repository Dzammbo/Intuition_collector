#!/usr/bin/env python3
"""One-time, idempotent migration of immutable Scanner live-tennis evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scanner-root", default="scanner")
    parser.add_argument("--state-root", default="state")
    ns = parser.parse_args()
    source, state = Path(ns.scanner_root), Path(ns.state_root)
    target = state / "live_tennis"
    selected = json.loads((target / "registry/selected-events.json").read_text(encoding="utf-8"))
    source_selected = json.loads((source / "tennis/selected-events.json").read_text(encoding="utf-8"))
    source_ids = {str(row["event_id"]) for row in source_selected.get("selections") or []}
    target_ids = {str(row["event_id"]) for row in selected.get("selections") or []}
    if not source_ids.issubset(target_ids):
        raise SystemExit(f"selection migration mismatch: source={source_ids}, target={target_ids}")
    source_results = json.loads((source / "tennis/results.json").read_text(encoding="utf-8"))
    target_results = json.loads((target / "registry/results.json").read_text(encoding="utf-8"))
    if len(source_results.get("results") or []) != len(target_results.get("results") or []):
        raise SystemExit("result migration mismatch")
    snapshot_target = target / "snapshots/migrated-scanner"
    snapshot_target.mkdir(parents=True, exist_ok=True)
    copied = 0
    snapshot_rows = []
    for path in sorted((source / "tennis/snapshots").glob("*.json")):
        destination = snapshot_target / path.name
        if destination.exists() and digest(destination) != digest(path):
            raise SystemExit(f"immutable snapshot conflict: {path.name}")
        if not destination.exists():
            shutil.copy2(path, destination)
            copied += 1
        snapshot_rows.append({"path": f"tennis/snapshots/{path.name}", "sha256": digest(path)})
    manifest = {
        "schema_version": 1,
        "source_repository": "Dzammbo/Scaner",
        "source_commit": "4c5849e56d4ec10c1b760e8ce02249ed78f74317",
        "target_repository": "Dzammbo/jarvis-intuition",
        "deduplication_key": "event_id for primary selections; snapshot filename for snapshots",
        "selection_count": len(source_ids),
        "result_count": len(source_results.get("results") or []),
        "snapshot_count": len(snapshot_rows),
        "duplicates_removed": 0,
        "copied_this_run": copied,
        "source_files": [
            {"path": "tennis/selected-events.json", "sha256": digest(source / "tennis/selected-events.json")},
            {"path": "tennis/results.json", "sha256": digest(source / "tennis/results.json")},
            *snapshot_rows,
            {"path": "Live теннис/Live теннис.xlsx", "sha256": digest(source / "Live теннис/Live теннис.xlsx")},
        ],
        "target_workbook_sha256": digest(target / "diary/Live теннис.xlsx"),
        "workbook_change": "Summary formula ranges expanded from row 6 only to rows 6:1005; source row, values, style and calculation rules preserved.",
        "historical_prematch_handling": "No prematch opinion was present in the source selection. It remains explicitly not recorded and was not reconstructed.",
        "history_deleted_from_source": False,
    }
    destination = target / "migration/scaner-2026-10-17.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"copied": copied, "snapshots": len(snapshot_rows), "selections": len(source_ids)}))


if __name__ == "__main__":
    main()
