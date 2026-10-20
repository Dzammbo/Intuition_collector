#!/usr/bin/env python3
"""Deterministic final-card gate for the prospective underdog-only regime."""
from __future__ import annotations

import math
from typing import Any

REGIME_ID = "intuition-v2-2026-10-20-tennis-underdog-only"
POLICY_VERSION = "2026-10-20-underdog-only-v1"
FINAL_DECISION_CONTRACT = "2026-10-20-underdog-only-final-card-v1"
CLASSIFICATION_METHOD = "TWO_SIDED_BET365_MATCH_WINNER_COMPARISON"


def finite_odds(value: Any) -> float:
    try:
        odds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("both match-winner prices are required") from exc
    if not math.isfinite(odds) or odds <= 1:
        raise ValueError("match-winner prices must be finite and greater than 1")
    return odds


def classify(selected_side: str, home_odds: Any, away_odds: Any) -> dict[str, Any]:
    side = str(selected_side or "").upper()
    if side not in {"HOME", "AWAY"}:
        raise ValueError("selected_side must be HOME or AWAY")
    home = finite_odds(home_odds)
    away = finite_odds(away_odds)
    selected, opponent = (home, away) if side == "HOME" else (away, home)
    if math.isclose(selected, opponent, rel_tol=0.0, abs_tol=1e-12):
        market_role = "EVEN"
    elif selected > opponent:
        market_role = "UNDERDOG"
    else:
        market_role = "FAVORITE"
    return {
        "selected_side": side,
        "home_odds": home,
        "away_odds": away,
        "selected_odds": selected,
        "opponent_odds": opponent,
        "market_role": market_role,
    }


def expected_card_decision(research_decision: str, market_role: str | None) -> str:
    research = str(research_decision or "").upper()
    role = str(market_role or "UNKNOWN").upper()
    if research == "NO_DATA":
        return "NO_DATA"
    if research == "PASS":
        return "PASS"
    if research != "BET":
        raise ValueError("research_decision must be BET, PASS or NO_DATA")
    return "BET" if role == "UNDERDOG" else "PASS"


def validate_gate(gate: dict[str, Any], selected_side: str, captured_odds: Any = None) -> dict[str, Any]:
    if not isinstance(gate, dict):
        raise ValueError("underdog_gate is required")
    if gate.get("policy_version") != POLICY_VERSION:
        raise ValueError("wrong underdog gate policy version")
    if gate.get("classification_method") != CLASSIFICATION_METHOD:
        raise ValueError("wrong underdog classification method")
    if gate.get("selected_side") != str(selected_side or "").upper():
        raise ValueError("underdog gate side differs from the frozen sporting side")
    result = classify(selected_side, gate.get("home_odds"), gate.get("away_odds"))
    if gate.get("market_role") != result["market_role"]:
        raise ValueError("recorded market_role does not match the two-sided quote")
    if captured_odds not in (None, "", "UNKNOWN"):
        if not math.isclose(finite_odds(captured_odds), result["selected_odds"], rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("captured selected price differs from underdog gate")
    if not gate.get("captured_at_utc"):
        raise ValueError("underdog gate requires captured_at_utc")
    return result
