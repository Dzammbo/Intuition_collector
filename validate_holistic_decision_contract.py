#!/usr/bin/env python3
"""Reject post-2026-10-09 decisions whose status depends on price or EV."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from underdog_gate import FINAL_DECISION_CONTRACT, REGIME_ID as UNDERDOG_REGIME, expected_card_decision, validate_gate

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
    method = row.get("decision_method_contract")
    underdog_mode = method == FINAL_DECISION_CONTRACT
    if method not in {CONTRACT, FINAL_DECISION_CONTRACT}:
        raise ValueError("new decision lacks a supported holistic contract")
    if underdog_mode and row.get("regime_id") != UNDERDOG_REGIME:
        raise ValueError("underdog-only final decision has wrong regime_id")
    if row.get("decision_frozen_before_price") is not True:
        raise ValueError("decision must be frozen before price reveal")

    judgment = row.get("deep_research_judgment")
    if not isinstance(judgment, dict):
        raise ValueError("deep_research_judgment is required")
    if str(judgment.get("research_decision") or "").upper() != status:
        raise ValueError("research status differs from frozen sporting decision")
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

    if underdog_mode:
        card_decision = str(row.get("card_decision") or "").upper()
        if card_decision not in DECISIONS:
            raise ValueError("underdog-only record requires card_decision")
        if status == "NO_DATA":
            expected = "NO_DATA"
        elif status == "PASS":
            expected = "PASS"
        else:
            gate = row.get("underdog_gate")
            if isinstance(gate, dict):
                target = row.get("evaluated_target") or {}
                selected_side = judgment.get("selected_side")
                gate_result = validate_gate(gate, selected_side, target.get("captured_odds"))
                expected = expected_card_decision(status, gate_result["market_role"])
            else:
                price_status = str((row.get("price_reveal") or {}).get("price_status") or "").upper()
                if price_status == "PRICE_CAPTURED":
                    raise ValueError("captured two-sided price requires underdog_gate")
                expected = "PASS"
        if card_decision != expected:
            raise ValueError("card_decision does not match research decision and underdog gate")
        if card_decision == "BET" and (row.get("underdog_gate") or {}).get("market_role") != "UNDERDOG":
            raise ValueError("final BET is not a verified underdog")
        if status == "BET" and card_decision == "PASS":
            target = row.get("evaluated_target") or {}
            if str(target.get("target_status") or "").upper() != "RECORDED":
                raise ValueError("demoted sporting BET must remain an exact PASS control")
        if not str(row.get("card_reason_code") or "").strip():
            raise ValueError("underdog-only record requires card_reason_code")

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
