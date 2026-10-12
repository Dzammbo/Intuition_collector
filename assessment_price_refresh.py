#!/usr/bin/env python3
"""Capture post-decision Bet365 prices with a guarded Bet365-FI fallback.

The sporting decision is already frozen. This module only resolves a price.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

BASE = "https://api.b365api.com"
REQUEST_PATH = os.environ.get("PRICE_REVEAL_REQUEST", "triggers/run-assessment-price-refresh.json")
STATE_ROOT = Path(os.environ.get("STATE_ROOT", "state"))
HTTP_WORKERS = int(os.environ.get("BETSAPI_HTTP_WORKERS", "8"))
MATCH_WINNER_NAMES = re.compile(r"^(match winner|money line|moneyline|to win match|game betting)$", re.I)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def api_get(token: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token, **params})
    request = urllib.request.Request(
        BASE + path + "?" + query,
        headers={"User-Agent": "jarvis-intuition-price-refresh/2"},
    )
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.load(response)
            if isinstance(payload, dict) and payload.get("success") == 0:
                raise RuntimeError(f"BetsAPI error: {payload}")
            return payload
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def name_score(left: Any, right: Any) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    at, bt = a.split(), b.split()
    surname_equal = at[-1] == bt[-1]
    first_compatible = at[0][0] == bt[0][0]
    if surname_equal and first_compatible:
        return max(0.9, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def label(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("NA") or value.get("id")
    return str(value).strip() if value not in (None, "") else None


def split_event_name(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "")
    parts = re.split(r"\s+(?:v|vs|versus)\.?\s+|\s+-\s+", text, maxsplit=1, flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, None)


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_candidate_time(node: dict[str, Any]) -> datetime | None:
    for key in ("time", "TU", "start_time", "start", "kickoff"):
        value = node.get(key)
        if value in (None, ""):
            continue
        try:
            if isinstance(value, (int, float)) or str(value).isdigit():
                number = float(value)
                if number > 10_000_000_000:
                    number /= 1000
                return datetime.fromtimestamp(number, timezone.utc)
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def bet365_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for node in walk(payload.get("results") if isinstance(payload, dict) else payload):
        fi = node.get("FI") or node.get("bet365_id") or node.get("bet365_event_id")
        if fi in (None, ""):
            continue
        home, away = label(node.get("home")), label(node.get("away"))
        if not home or not away:
            home, away = split_event_name(node.get("NA") or node.get("name"))
        if not home or not away:
            continue
        found[str(fi)] = {
            "fi": str(fi),
            "home": home,
            "away": away,
            "start": parse_candidate_time(node),
            "league": label(node.get("league") or node.get("competition")),
        }
    return list(found.values())


def choose_candidate(
    candidates: list[dict[str, Any]], home: str, away: str, scheduled_start: datetime
) -> dict[str, Any] | None:
    ranked = []
    for candidate in candidates:
        normal = min(name_score(home, candidate["home"]), name_score(away, candidate["away"]))
        reverse = min(name_score(home, candidate["away"]), name_score(away, candidate["home"]))
        score, reversed_match = (reverse, True) if reverse > normal else (normal, False)
        start = candidate.get("start")
        delta = abs((start - scheduled_start).total_seconds()) if start else None
        if score < 0.86 or (delta is not None and delta > 6 * 3600):
            continue
        ranked.append((score, -(delta or 0), reversed_match, candidate))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    if not ranked:
        return None
    if len(ranked) > 1 and ranked[0][0] < 0.98 and ranked[0][0] - ranked[1][0] < 0.05:
        return None
    score, neg_delta, reversed_match, candidate = ranked[0]
    return {**candidate, "match_score": round(score, 6), "reversed": reversed_match, "time_delta_seconds": -neg_delta}


def _market_participants(value: Any, inherited_market: str = ""):
    if isinstance(value, list):
        current = inherited_market
        for item in value:
            if isinstance(item, dict) and str(item.get("type") or "").upper() in {"MA", "MG"}:
                current = str(item.get("NA") or item.get("name") or current)
                yield from _market_participants(item, current)
            else:
                yield from _market_participants(item, current)
    elif isinstance(value, dict):
        kind = str(value.get("type") or "").upper()
        current = inherited_market
        if kind in {"MA", "MG"}:
            current = str(value.get("NA") or value.get("name") or current)
        if kind == "PA":
            yield current, value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from _market_participants(child, current)


def finite_odds(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 1 else None


def extract_match_winner(
    payload: dict[str, Any], home: str, away: str, reversed_match: bool, captured_at: datetime
) -> dict[str, Any] | None:
    priced = []
    for market, node in _market_participants(payload.get("results") or payload):
        if not MATCH_WINNER_NAMES.match(str(market).strip()):
            continue
        odds = finite_odds(node.get("OD") or node.get("odds"))
        selection = node.get("NA") or node.get("name")
        if odds and selection:
            priced.append((str(selection), odds, node))
    best_home = max(priced, key=lambda row: name_score(home, row[0]), default=None)
    best_away = max(priced, key=lambda row: name_score(away, row[0]), default=None)
    if not best_home or not best_away or best_home[2] is best_away[2]:
        return None
    if name_score(home, best_home[0]) < 0.78 or name_score(away, best_away[0]) < 0.78:
        return None
    # The selections were matched to the canonical home/away names above.
    # Candidate order is useful audit metadata only and must not swap prices.
    home_od, away_od = best_home[1], best_away[1]
    return {
        "stats": {"matching_dir": 1, "resolution": "BET365_FI_NAME_TIME_MATCH"},
        "odds": {"13_1": [{
            "home_od": home_od,
            "away_od": away_od,
            "add_time": str(int(captured_at.timestamp())),
            "id": str(best_home[2].get("ID") or best_home[2].get("id") or ""),
        }]},
    }


def has_match_winner_price(results: Any) -> bool:
    if not isinstance(results, dict):
        return False
    quotes = ((results.get("odds") or {}).get("13_1") or [])
    return any(
        isinstance(row, dict)
        and finite_odds(row.get("home_od"))
        and finite_odds(row.get("away_od"))
        for row in quotes
    )


def load_match_metadata(event: dict[str, Any]) -> dict[str, Any] | None:
    path = STATE_ROOT / str(event.get("assessment_ref") or "")
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    comparison = document.get("structured_two_player_comparison") or {}
    matchup = comparison.get("matchup") or {}
    home = (comparison.get("home") or {}).get("canonical_name")
    away = (comparison.get("away") or {}).get("canonical_name")
    if not home or not away:
        return None
    return {"home": home, "away": away, "league": matchup.get("tournament")}


class PriceResolver:
    def __init__(self, token: str):
        self.token = token
        self._candidates: list[dict[str, Any]] | None = None
        self._candidate_error: str | None = None
        self._candidate_shape: dict[str, Any] | None = None
        self._candidate_lock = threading.Lock()

    def direct(self, event_id: str) -> dict[str, Any]:
        payload = api_get(self.token, "/v2/event/odds", {"event_id": event_id, "source": "bet365", "odds_market": 1})
        return payload.get("results") or {}

    def candidates(self) -> list[dict[str, Any]]:
        if self._candidates is None:
            with self._candidate_lock:
                if self._candidates is None:
                    try:
                        payload = api_get(self.token, "/v1/bet365/upcoming", {"sport_id": 13})
                        results = payload.get("results") if isinstance(payload, dict) else None
                        self._candidate_shape = {
                            "top_keys": sorted(payload.keys())[:20] if isinstance(payload, dict) else [],
                            "results_type": type(results).__name__,
                            "results_count": len(results) if isinstance(results, (list, dict)) else None,
                        }
                        self._candidates = bet365_candidates(payload)
                    except Exception as exc:
                        self._candidate_error = str(exc)
                        self._candidates = []
        return self._candidates

    def resolve(self, event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        event_id = str(event["event_id"])
        direct = self.direct(event_id)
        if has_match_winner_price(direct):
            return direct, {"method": "DIRECT_EVENT_ID", "event_id": event_id}
        metadata = load_match_metadata(event)
        if not metadata:
            return direct, {"method": "NO_PRICE", "reason": "MATCH_METADATA_UNAVAILABLE"}
        match = choose_candidate(self.candidates(), metadata["home"], metadata["away"], parse_iso(event["scheduled_start_utc"]))
        if not match:
            return direct, {
                "method": "NO_PRICE",
                "reason": "NO_UNIQUE_BET365_FI_MATCH",
                "bet365_candidate_count": len(self._candidates or []),
                "candidate_endpoint_error": self._candidate_error,
                "candidate_response_shape": self._candidate_shape,
            }
        payload = api_get(self.token, "/v1/bet365/event", {"FI": match["fi"]})
        fallback = extract_match_winner(payload, metadata["home"], metadata["away"], match["reversed"], now())
        if not fallback:
            return direct, {"method": "NO_PRICE", "reason": "BET365_FI_MATCH_WITHOUT_MATCH_WINNER", "matched": match}
        fallback["stats"].update({"matched_bet365_fi": match["fi"], "match_score": match["match_score"]})
        return fallback, {"method": "BET365_FI_NAME_TIME_MATCH", "original_event_id": event_id, "matched": match}


def collect(event: dict[str, Any], resolver: PriceResolver):
    event_id = str(event["event_id"])
    checked_at = iso()
    if now() >= parse_iso(event["scheduled_start_utc"]):
        return None, None, {"event_id": event_id, "checked_at": checked_at, "reason": "STARTED_BEFORE_PRICE_QUERY"}
    requested = iso()
    try:
        odds, resolution = resolver.resolve(event)
        record = {"event_id": event_id, "requested_at": requested, "retrieved_at": iso(), "odds": odds, "resolution": resolution}
        for key in ("scheduled_start_utc", "supported_side", "assessment_ref", "assessment_sha256"):
            record[key] = event[key]
        return record, None, None
    except Exception as exc:
        return None, {"event_id": event_id, "retrieved_at": iso(), "error": str(exc)}, None


def run(cfg: dict[str, Any], token: str) -> dict[str, Any]:
    events = cfg.get("events") or []
    if not events:
        raise SystemExit("price reveal worklist contains no queryable events")
    ids = [str(row["event_id"]) for row in events]
    if len(ids) != len(set(ids)):
        raise SystemExit("event ids must be unique")
    resolver = PriceResolver(token)
    rows, errors = [], []
    skipped = list(cfg.get("prefiltered_started") or [])
    with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as executor:
        for index, (record, error, skip) in enumerate(executor.map(lambda event: collect(event, resolver), events), 1):
            if record:
                rows.append(record)
            if error:
                errors.append(error)
            if skip:
                skipped.append(skip)
            if index % 25 == 0 or index == len(events):
                print(json.dumps({"progress": index, "total": len(events), "completed": len(rows), "skipped": len(skipped), "errors": len(errors), "workers": HTTP_WORKERS}), flush=True)
    return {
        "schema_version": 3,
        "stage": "PRICE_REVEAL_RAW_CAPTURE",
        "date_moscow": cfg["date_moscow"],
        "card_key": cfg.get("card_key") or cfg["date_moscow"],
        "batch": cfg.get("batch", 1),
        "trigger_requested_at": cfg.get("requested_at"),
        "worklist_built_at": cfg.get("worklist_built_at"),
        "generated_at": iso(),
        "input_count": len(ids),
        "completed": len(rows),
        "skipped_started": skipped,
        "errors": errors,
        "records": rows,
        "execution": {"mode": "DIRECT_EVENT_ID_THEN_GUARDED_BET365_FI_FALLBACK", "workers": HTTP_WORKERS, "input_order_preserved": True},
    }


def main() -> None:
    token = os.environ["BETSAPI_TOKEN"]
    cfg = json.loads(Path(REQUEST_PATH).read_text(encoding="utf-8"))
    output = run(cfg, token)
    Path("assessment-price-refresh.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"completed": output["completed"], "skipped": len(output["skipped_started"]), "errors": len(output["errors"])}))


if __name__ == "__main__":
    main()
