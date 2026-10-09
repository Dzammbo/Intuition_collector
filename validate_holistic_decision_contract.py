#!/usr/bin/env python3
"""Reject post-2026-10-09 decisions whose status depends on price or EV."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "2026-10-09-holistic-deep-research-v1"
EFFECTIVE_AT = datetime(2026, 10, 9, 11, 34, tzinfo=timezone.utc)
DECISIONS = {"BET", "PASS", "NO_DATA"}
SIDES = {"HOME", "AWAY"}
FORBIDDEN_REASON_TOKENS = {"PRICE", "ODDS", "EV", "IMPLIED", "MARKET"}


def utc(value: Any, label: str) -> datetime:
    if not value:
        raise ValueError(f"{label} is required")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} requires timezone")
    return parsed.astimezone(timezone.utc)


def nonempty_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    return value


def iter_rows(document: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(document, dict):
        return
    rows = document.get("decisions")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                yield row


def validate_row(row: dict[str, Any]) -> None:
    status = str(row.get("status") or row.get("decision_status") or "").upper()
    if status not in DECISIONS:
        return
    if str(row.get("reason_code") or "") == "DEEP_RESEARCH_TIME_GATE":
        return
    decided = utc(
        row.get("decision_frozen_at_utc")
        or row.get("decision_recorded_at_utc")
        or row.get("decision_recorded_at"),
        "decision freeze time",
    )
    if decided < EFFECTIVE_AT:
        return
    if row.get("decision_method_contract") != CONTRACT:
        raise ValueError("new decision lacks the holistic deep-research contract")
    if row.get("decision_frozen_before_price") is not True:
        raise ValueError("decision must be frozen before price reveal")

    judgment = row.get("deep_research_judgment")
    if not isinstance(judgment, dict):
        raise ValueError("deep_research_judgment is required")
    if str(judgment.get("research_decision") or "").upper() != status:
        raise ValueError("final status differs from frozen research decision")
    nonempty_list(judgment.get("source_refs"), "source_refs")
    nonempty_list(judgment.get("uncertainties"), "uncertainties")
    if not str(judgment.get("evidence_weighing") or "").strip():
        raise ValueError("evidence_weighing is required")

    if status in {"BET", "PASS"}:
        if str(judgment.get("selected_side") or "").upper() not in SIDES:
            raise ValueError("BET/PASS requires an exact price-blind selected side")
        nonempty_list(judgment.get("supporting_facts"), "supporting_facts")
        if not isinstance(judgment.get("counterevidence"), list):
            raise ValueError("counterevidence must be a list")
    if status == "PASS":
        nonempty_list(judgment.get("reasons_for_pass"), "reasons_for_pass")
    if status == "NO_DATA":
        nonempty_list(judgment.get("sporting_data_gaps"), "sporting_data_gaps")

    reason = str(row.get("reason_code") or "").upper()
    if any(token in reason for token in FORBIDDEN_REASON_TOKENS):
        raise ValueError(f"price/EV-dependent reason_code is forbidden: {reason}")

    reveal = row.get("price_reveal")
    if isinstance(reveal, dict) and reveal.get("captured_at_utc"):
        if utc(reveal["captured_at_utc"], "price capture time") < decided:
            raise ValueError("price was captured before the frozen research decision")
    if row.get("expected_value") is not None:
        if row.get("expected_value_decision_role") != "POST_DECISION_DIAGNOSTIC_ONLY":
            raise ValueError("EV may be stored only as a post-decision diagnostic")


def validate_root(root: Path) -> int:
    checked = 0
    for path in sorted((root / "final_decisions").glob("**/*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for row in iter_rows(document):
            validate_row(row)
            checked += 1
    return checked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    checked = validate_root(Path(args.root))
    print(json.dumps({"status": "PASS", "rows_checked": checked}))


if __name__ == "__main__":
    main()
