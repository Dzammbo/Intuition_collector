#!/usr/bin/env python3
"""Capture append-only Bet365 prematch closing snapshots for BET and substantive PASS.

This job is diagnostic only. Missing odds never changes or blocks a decision.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://api.b365api.com"
MOSCOW = timezone(timedelta(hours=3))
WINDOW_SECONDS = 20 * 60
ACTIVE_STATUSES = {"0", ""}
SIDE_FIELD = {
    "home": "home_od",
    "away": "away_od",
    "draw": "draw_od",
    "over": "over_od",
    "under": "under_od",
}


def utc(value: Any) -> datetime:
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(float(value), timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def provider_id(row: dict[str, Any]) -> str:
    value = row.get("provider_event_id") or row.get("event_id")
    return str(value or "").removeprefix("betsapi:")


def safe_key(row: dict[str, Any]) -> str:
    raw = str(row.get("decision_id") or row.get("decision_key") or "")
    if not raw:
        raw = "|".join(
            str(row.get(key) or "")
            for key in ("event_id", "market_key", "period", "line", "selection", "side")
        )
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", raw).strip("-")[:100]
    return slug or hashlib.sha256(raw.encode()).hexdigest()[:20]


def target_from_decision(row: dict[str, Any], source_ref: str) -> dict[str, Any] | None:
    status = str(row.get("decision_status") or row.get("status") or row.get("final_decision") or "").upper()
    target = row.get("evaluated_target") if isinstance(row.get("evaluated_target"), dict) else row
    if status not in {"BET", "PASS"}:
        return None
    if status == "PASS" and str(target.get("target_status") or "").upper() != "RECORDED":
        return None
    event_id = provider_id(row)
    start = row.get("start_time_utc") or row.get("scheduled_start_utc") or row.get("start_time")
    market_key = target.get("market_key") or row.get("market_key")
    side = str(target.get("side") or row.get("side") or "").lower()
    raw_market = target.get("market_type") or target.get("market") or row.get("market_type") or row.get("market")
    if not market_key and str(raw_market or "").upper().replace(" ", "_") == "MATCH_WINNER":
        market_key = "13_1"
    if not all((event_id, start, market_key, side in SIDE_FIELD)):
        return None
    entry_odds = target.get("captured_odds", target.get("decimal_odds", row.get("captured_odds")))
    return {
        "decision_key": safe_key(row),
        "decision_status": status,
        "provider_event_id": event_id,
        "scheduled_start_utc": utc(start).isoformat(),
        "market_key": str(market_key),
        "market_type": raw_market,
        "period": target.get("period") or row.get("period"),
        "line": target.get("line", row.get("line")),
        "selection": target.get("selection") or row.get("selection"),
        "side": side,
        "entry_odds": entry_odds,
        "entry_probability": row.get("estimated_probability") or row.get("jarvis_fair_probability") or (row.get("assessment") or {}).get("jarvis_fair_probability"),
        "source_ref": source_ref,
    }


def _rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("final_bets_for_freeze", "decisions", "assessments", "bets"):
        if isinstance(document.get(key), list):
            return document[key]
    return []


def load_targets(state_root: Path, now: datetime) -> list[dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    current_path = state_root / "status" / "current-run.json"
    if current_path.exists():
        current = json.loads(current_path.read_text(encoding="utf-8"))
        checkpoint_root = current.get("checkpoint_root") or (current.get("assessment") or {}).get("checkpoint_root")
        if checkpoint_root:
            root = state_root / checkpoint_root
            if root.exists():
                for path in sorted(root.rglob("*.json")):
                    candidates.append((path, json.loads(path.read_text(encoding="utf-8"))))

    for offset in range(-1, 3):
        day = (now.astimezone(MOSCOW).date() + timedelta(days=offset)).isoformat()
        status_path = state_root / "status" / f"final-portfolio-{day}.json"
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text(encoding="utf-8"))
        review_ref = status.get("final_portfolio_review")
        review_path = state_root / str(review_ref or "")
        if review_ref and review_path.exists():
            candidates.append((review_path, json.loads(review_path.read_text(encoding="utf-8"))))

    selected: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for path, document in candidates:
        ref = str(path.relative_to(state_root))
        for row in _rows(document):
            target = target_from_decision(row, ref)
            if not target:
                continue
            key = (target["provider_event_id"], target["market_key"], str(target.get("line")), target["side"])
            # Final BET manifests are read after checkpoints and therefore win ties.
            selected[key] = target
    return sorted(selected.values(), key=lambda row: (row["scheduled_start_utc"], row["provider_event_id"]))


def api_get(token: str, path: str, **params: Any) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token, **{k: v for k, v in params.items() if v is not None}})
    request = urllib.request.Request(BASE_URL + path + "?" + query, headers={"User-Agent": "jarvis-intuition-closing/1"})
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            if isinstance(payload, dict) and payload.get("success") == 0:
                raise RuntimeError(f"BetsAPI error: {payload}")
            return payload
        except Exception as exc:  # network retry is deliberately bounded
            last = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def parse_line(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        parts = [float(piece.strip()) for piece in str(value).replace("/", ",").split(",")]
        return sum(parts) / len(parts)
    except (TypeError, ValueError):
        return None


def finite_odds(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 1.0 else None


def is_prematch_quote(quote: dict[str, Any]) -> bool:
    score = str(quote.get("ss") or "").strip()
    clock = str(quote.get("time_str") or "").strip()
    return not score and not clock


def quote_matches_line(quote: dict[str, Any], target: dict[str, Any], reversed_match: bool) -> bool:
    wanted = parse_line(target.get("line"))
    if wanted is None:
        return True
    observed = parse_line(quote.get("handicap"))
    if observed is None:
        return False
    side = target.get("side")
    market = str(target.get("market_type") or "").upper()
    if "HANDICAP" in market or "SPREAD" in market:
        if reversed_match:
            observed = -observed
        if side == "away":
            observed = -observed
    return abs(wanted - observed) <= 0.02


def normalize_quote(quote: dict[str, Any], reversed_match: bool) -> dict[str, Any]:
    value = dict(quote)
    if reversed_match:
        value["home_od"], value["away_od"] = value.get("away_od"), value.get("home_od")
    return value


def fair_probability(quote: dict[str, Any], side: str) -> float | None:
    if side in {"over", "under"}:
        fields = ["over_od", "under_od"]
    else:
        fields = [name for name in ("home_od", "draw_od", "away_od") if finite_odds(quote.get(name))]
        if len(fields) not in {2, 3}:
            return None
    field = SIDE_FIELD[side]
    if field not in fields:
        return None
    inverse = [1.0 / finite_odds(quote[name]) for name in fields]
    return (1.0 / finite_odds(quote[field])) / sum(inverse)


def select_prematch_quote(payload: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    results = payload.get("results") or {}
    odds = results.get("odds") or {}
    quotes = odds.get(target["market_key"]) or []
    reversed_match = str((results.get("stats") or {}).get("matching_dir")) == "-1"
    eligible = []
    for raw in quotes:
        if not isinstance(raw, dict) or not is_prematch_quote(raw):
            continue
        quote = normalize_quote(raw, reversed_match)
        if not quote_matches_line(quote, target, reversed_match):
            continue
        selected = finite_odds(quote.get(SIDE_FIELD[target["side"]]))
        try:
            added = int(quote.get("add_time"))
        except (TypeError, ValueError):
            continue
        if selected is not None:
            eligible.append((added, quote, selected))
    if not eligible:
        return None
    added, quote, selected = max(eligible, key=lambda item: item[0])
    fair = fair_probability(quote, target["side"])
    return {
        "quote_add_time": added,
        "quote_add_time_utc": datetime.fromtimestamp(added, timezone.utc).isoformat(),
        "selected_odds": selected,
        "selected_fair_probability": round(fair, 8) if fair is not None else None,
        "opposing_odds": {
            key: finite_odds(quote.get(key)) for key in ("home_od", "draw_od", "away_od", "over_od", "under_od")
            if finite_odds(quote.get(key)) is not None
        },
        "handicap": quote.get("handicap"),
        "source": "BET365",
        "source_endpoint": "/v2/event/odds?source=bet365",
    }


def read_lifecycle(root: Path, decision_key: str) -> dict[str, Any]:
    path = root / "diagnostics" / "bet365_closing" / "lifecycle" / f"{decision_key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json_new(path: Path, document: dict[str, Any]) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def write_lifecycle(root: Path, target: dict[str, Any], patch: dict[str, Any]) -> None:
    path = root / "diagnostics" / "bet365_closing" / "lifecycle" / f"{target['decision_key']}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    document = {**old, **target, **patch, "updated_at_utc": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    state_root = Path(os.environ.get("STATE_ROOT", "state")).resolve()
    token = os.environ["BETSAPI_TOKEN"]
    now = datetime.now(timezone.utc)
    targets = load_targets(state_root, now)
    due = []
    for target in targets:
        lifecycle = read_lifecycle(state_root, target["decision_key"])
        if lifecycle.get("status") == "CLOSED":
            continue
        seconds = (utc(target["scheduled_start_utc"]) - now).total_seconds()
        if seconds <= WINDOW_SECONDS or lifecycle.get("first_snapshot_at_utc"):
            due.append(target)

    events: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    event_ids = sorted({target["provider_event_id"] for target in due})
    for offset in range(0, len(event_ids), 10):
        chunk = event_ids[offset:offset + 10]
        try:
            payload = api_get(token, "/v1/event/view", event_id=",".join(chunk))
            for event in payload.get("results") or []:
                events[str(event.get("id"))] = event
        except Exception as exc:
            errors.append({"stage": "event_view", "event_ids": chunk, "error": str(exc)})

    captured = closed = 0
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    for target in due:
        event = events.get(target["provider_event_id"]) or {}
        status = str(event.get("time_status") or "")
        event_start = event.get("time") or target["scheduled_start_utc"]
        try:
            market_id = target["market_key"].split("_", 1)[1]
            payload = api_get(token, "/v2/event/odds", event_id=target["provider_event_id"], source="bet365", odds_market=market_id)
            quote = select_prematch_quote(payload, target)
        except Exception as exc:
            errors.append({"stage": "odds", "event_id": target["provider_event_id"], "error": str(exc)})
            continue
        if quote:
            snapshot = {
                "schema_version": 1,
                "kind": "BET365_PREMATCH_CLOSING_SNAPSHOT",
                "captured_at_utc": now.isoformat(),
                "provider_event_status": status or None,
                "provider_event_start_utc": utc(event_start).isoformat(),
                "target": target,
                "quote": quote,
            }
            day = utc(event_start).astimezone(MOSCOW).date().isoformat()
            path = state_root / "closing_line_snapshots" / day / target["decision_key"] / f"{stamp}.json"
            if write_json_new(path, snapshot):
                captured += 1
            lifecycle = read_lifecycle(state_root, target["decision_key"])
            lifecycle_patch = {
                "status": "TRACKING" if status in ACTIVE_STATUSES else "CLOSED",
                "first_snapshot_at_utc": lifecycle.get("first_snapshot_at_utc") or now.isoformat(),
                "latest_snapshot": str(path.relative_to(state_root)),
                "latest_quote_add_time_utc": quote["quote_add_time_utc"],
            }
            if status not in ACTIVE_STATUSES:
                lifecycle_patch.update({
                    "closed_at_utc": now.isoformat(),
                    "closing_odds": quote["selected_odds"],
                    "closing_fair_probability": quote["selected_fair_probability"],
                    "bet365_clv_odds": round(float(target["entry_odds"]) / quote["selected_odds"] - 1, 8) if target.get("entry_odds") else None,
                    "bet365_clv_probability_pp": round((quote["selected_fair_probability"] - float(target["entry_probability"])) * 100, 6) if quote.get("selected_fair_probability") is not None and target.get("entry_probability") is not None else None,
                })
                closed += 1
            write_lifecycle(state_root, target, lifecycle_patch)
        elif status not in ACTIVE_STATUSES:
            write_lifecycle(state_root, target, {
                "status": "CLOSED_UNAVAILABLE",
                "closed_at_utc": now.isoformat(),
                "unavailable_reason": "NO_EXACT_PREMATCH_BET365_QUOTE",
            })

    summary = {
        "schema_version": 1,
        "generated_at_utc": now.isoformat(),
        "targets_discovered": len(targets),
        "targets_due": len(due),
        "snapshots_created": captured,
        "targets_closed": closed,
        "errors": errors,
        "decision_blocking": False,
    }
    path = state_root / "diagnostics" / "bet365_closing" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
