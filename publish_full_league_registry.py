#!/usr/bin/env python3
"""Publish the generated exact league registry to public ops and private canon."""

import argparse
import json
from pathlib import Path


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def manifest(status, public=False):
    data = {
        "schema_version": 1,
        "policy_version": "2026-09-28-complete-provider-registry-v1",
        "status": status,
        "source": "BetsAPI /v3/league complete registry snapshot",
        "source_catalog_captured_at": "2026-09-28T15:59:12.229212Z",
        "total_provider_registry_leagues": 16187,
        "total_classified_leagues": 16187,
        "total_allowed_leagues": 13049,
        "classification_counts": {
            "CORE": 10826,
            "SECONDARY": 2223,
            "EXCLUDE": 3138,
            "UNCLASSIFIED_LEAGUE": 0,
        },
        "counts_by_sport": {
            "soccer": 1831,
            "tennis": 10310,
            "baseball": 48,
            "ice_hockey": 117,
            "basketball": 743,
        },
        "matching_key": ["sport_id", "league_id"],
        "complete_registry_file": "config/league_allowset_v1/complete_registry_classification.json",
        "unknown_league_action": "QUARANTINE_WITHOUT_BLOCKING_DAILY_RUN",
        "collection_rule": "Collect the complete sport/day RAW schedule first. Apply this exact-ID registry only after the immutable RAW snapshot and before event-level enrichment.",
        "change_rule": "Never promote a new provider ID during a daily run. Registry changes require a versioned, audited canonical update. Existing canonical decisions take precedence over build-time rules.",
    }
    if public:
        data["canonical_repository"] = "Dzammbo/jarvis-intuition"
        data["provider_catalog_file"] = "config/league_registry_v1/catalog.json"
    else:
        data["public_provider_catalog"] = "Dzammbo/Intuition_collector:config/league_registry_v1/catalog.json"
    return data


DOC = """# Complete BetsAPI League Registry v1

## Purpose

Remove daily manual league mapping from the Jarvis Intuition run while keeping
the information-quality boundary explicit and auditable.

## Sources of truth

- Private canonical exact classification:
  `config/league_allowset_v1/complete_registry_classification.json`.
- Private canonical summary: `config/league_allowset_v1/manifest.json`.
- Public provider snapshot:
  `Dzammbo/Intuition_collector/config/league_registry_v1/catalog.json`.
- Public GitHub-hosted refresh workflow: `Sync BetsAPI League Registry`.

The snapshot contains all league IDs returned by `/v3/league` for soccer,
tennis, baseball, ice hockey and basketball. The canonical mapping contains one
exact `CORE`, `SECONDARY` or `EXCLUDE` decision for every key.

## Runtime contract

1. Capture the complete RAW event schedule.
2. Classify by exact `sport_id + league_id` only.
3. Enrich `CORE`; preserve but defer `SECONDARY`; do not enrich `EXCLUDE`.
4. A new provider ID is quarantined from enrichment and the daily run continues.
5. Review new IDs outside the daily critical path. Never promote by fuzzy
   runtime matching.

Existing canonical decisions always take precedence. Build-time name and
researchability rules were used once for the remaining historical registry;
daily runtime uses only the frozen exact-ID table.

Initial coverage: 16,187 provider leagues; 10,826 CORE; 2,223 SECONDARY; 3,138
EXCLUDE; zero unclassified after the overlay. Large counts include historical
tournament IDs, especially professional tennis, and are not active-event counts.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", required=True)
    parser.add_argument("--private-root", required=True)
    args = parser.parse_args()
    public = Path(args.public_root)
    private = Path(args.private_root)

    write_json(
        public / "config/league_allowset_v1/manifest.json",
        manifest("WORKING_COPY_OF_PRIVATE_CANON", public=True),
    )
    write_json(
        private / "config/league_allowset_v1/manifest.json",
        manifest("CANONICAL", public=False),
    )
    project_path = private / "config/project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    policy = project["information_quality_universe_policy"]
    policy["registry_ref"] = "config/league_allowset_v1/complete_registry_classification.json"
    policy["rule"] = (
        "Apply the versioned exact competition registry after complete Raw Universe collection. "
        "CORE is the default daily enrichment lane; SECONDARY is preserved but deferred; EXCLUDE "
        "is not enriched. A genuinely new provider ID is quarantined and reported asynchronously "
        "but never blocks the daily run or receives automatic promotion."
    )
    write_json(project_path, project)
    doc_path = private / "docs/LEAGUE_REGISTRY_V1.md"
    doc_path.write_text(DOC, encoding="utf-8")


if __name__ == "__main__":
    main()
