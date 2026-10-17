#!/usr/bin/env python3
"""Collect an on-demand BetsAPI Events live-tennis evidence packet."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

VERSION = "intuition-live-tennis-2026-10-17-v1"
QUOTE_MAX_AGE_SECONDS = 90
HISTORY_TTL_SECONDS = 7 * 24 * 60 * 60
REAL_EXCLUSION = re.compile(r"virtual|esport|simulated|cyber|table tennis|padel", re.I)


def utc_iso(epoch=None):
    return datetime.fromtimestamp(epoch or time.time(), timezone.utc).isoformat().replace("+00:00", "Z")


def number(value):
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


class Client:
    def __init__(self, token, timeout=12):
        if not token:
            raise ValueError("BETSAPI_TOKEN is required")
        self.token, self.timeout, self.calls = token, timeout, 0

    def fetch(self, path, **params):
        started = time.time()
        params["token"] = self.token
        self.calls += 1
        try:
            url = "https://api.b365api.com" + path + "?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data = json.load(response)
            return {"data": data, "observed_at": time.time(), "elapsed": time.time() - started}
        except Exception as exc:
            return {"error": type(exc).__name__, "observed_at": time.time(), "elapsed": time.time() - started}


def participant(event, side):
    value = event.get(side) or {}
    return value if isinstance(value, dict) else {"name": str(value)}


def match_type(event):
    names = [str(participant(event, side).get("name") or "") for side in ("home", "away")]
    doubles = any("/" in name or " & " in name or " + " in name for name in names)
    if not doubles:
        return "SINGLES"
    return "MIXED_DOUBLES" if re.search(r"mixed|микст", " ".join(names), re.I) else "DOUBLES"


def parse_prices(payload, event, now):
    if payload.get("success") != 1:
        return {"status": "UNAVAILABLE", "market": "13_1", "source": "bet365"}
    results = payload.get("results") or {}
    rows = (results.get("odds") or {}).get("13_1") or []
    if not rows:
        return {"status": "MISSING_MARKET", "market": "13_1", "source": "bet365"}
    row = max(rows, key=lambda item: number(item.get("add_time")) or 0)
    stats = results.get("stats") or {}
    checked = number((stats.get("odds_update") or {}).get("13_1"))
    quoted = number(row.get("add_time"))
    direction = str(stats.get("matching_dir"))
    out = {"status": "UNVERIFIED", "market": "13_1", "source": "bet365", "raw_latest": row,
           "checked_at_epoch": checked, "quoted_at_epoch": quoted, "matching_dir": direction}
    if direction not in {"1", "-1"}:
        return out
    home, away = number(row.get("home_od")), number(row.get("away_od"))
    if direction == "-1":
        home, away = away, home
    out.update(home=home, away=away)
    if not home or not away or min(home, away) <= 1:
        out["status"] = "SUSPENDED"
    elif not quoted or not checked or not (0 <= now - quoted <= QUOTE_MAX_AGE_SECONDS) or not (0 <= now - checked <= QUOTE_MAX_AGE_SECONDS):
        out["status"] = "STALE_OR_UNKNOWN"
    elif str(event.get("time_status")) != "1":
        out["status"] = "NOT_LIVE"
    else:
        out["status"] = "FRESH_NEEDS_SCORE_REVIEW"
    return out


def load_handoffs(root):
    rows = {}
    base = root / "live_tennis" / "prematch_handoffs"
    if not base.exists():
        return rows
    for path in sorted(base.glob("event-*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            rows[str(row["event_id"])] = {**row, "source_ref": str(path.relative_to(root))}
        except (OSError, ValueError, KeyError):
            continue
    return rows


def history_cache_path(root, event_id):
    return root / "live_tennis" / "dossiers" / "history_cache" / f"event-{event_id}.json"


def usable_cache(path, now):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        captured = number(payload.get("captured_at_epoch"))
        if captured is not None and 0 <= now - captured <= HISTORY_TTL_SECONDS:
            return payload
    except (OSError, ValueError):
        pass
    return None


def stats_availability(event):
    stats = event.get("stats") or {}
    return {"available_keys": sorted(stats) if isinstance(stats, dict) else [],
            "aces": stats.get("aces") if isinstance(stats, dict) else None,
            "double_faults": stats.get("double_faults") if isinstance(stats, dict) else None,
            "win_1st_serve": stats.get("win_1st_serve") if isinstance(stats, dict) else None,
            "break_point_conversions": stats.get("break_point_conversions") if isinstance(stats, dict) else None,
            "second_serve": stats.get("win_2nd_serve") if isinstance(stats, dict) else None,
            "return_points": stats.get("return_points_won") if isinstance(stats, dict) else None}


def dossier_summary(event, history_payload, cache_ref):
    results = ((history_payload or {}).get("data") or {}).get("results") or {}
    summaries = {}
    for side in ("home", "away"):
        matches = results.get(side) if isinstance(results, dict) else None
        summaries[side] = {"participant": participant(event, side), "match_type": match_type(event),
            "history_sample_size": len(matches) if isinstance(matches, list) else 0,
            "history": matches if isinstance(matches, list) else [],
            "surface": ((event.get("extra") or {}).get("ground") or "UNKNOWN"),
            "opponent_level": "UNKNOWN", "serve_return_history": "UNKNOWN",
            "gaps": ["Historical surface is absent unless explicitly supplied by Events",
                     "Opponent level is not inferred from tournament names",
                     "Historical serve/return statistics are unavailable in this endpoint"],
            "source_ref": cache_ref}
    summaries["h2h"] = results.get("h2h") if isinstance(results, dict) else []
    return summaries


def collect(args):
    started = time.time()
    state_root, output = Path(args.state_root), Path(args.output)
    client = Client(os.environ.get("BETSAPI_TOKEN", ""), args.timeout)
    board = client.fetch("/v3/events/inplay", sport_id=13)
    payload = board.get("data") or {}
    if payload.get("success") != 1:
        raise SystemExit("BetsAPI in-play tennis pool is unavailable")
    requested = {str(value) for value in args.event_id}
    pool = [row for row in payload.get("results") or []
            if str(row.get("time_status")) == "1"
            and not REAL_EXCLUSION.search(str((row.get("league") or {}).get("name") or ""))
            and (not requested or str(row.get("id")) in requested)]
    handoffs = load_handoffs(state_root)
    records = {str(row["id"]): {"board": row} for row in pool}
    with cf.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(client.fetch, "/v1/event/view", event_id=eid): eid for eid in records}
        for future in cf.as_completed(futures):
            records[futures[future]]["view"] = future.result()
    history_fetch, now = [], time.time()
    for event_id, record in records.items():
        viewed = ((record.get("view") or {}).get("data") or {}).get("results") or []
        record["event"] = viewed[0] if isinstance(viewed, list) and viewed else record["board"]
        cache_path = history_cache_path(state_root, event_id)
        cached = usable_cache(cache_path, now)
        if cached:
            record.update(history=cached["response"], history_source="CACHE", history_ref=str(cache_path.relative_to(state_root)))
        else:
            history_fetch.append(event_id)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for eid in records:
            futures[executor.submit(client.fetch, "/v2/event/odds", event_id=eid, source="bet365", odds_market="1")] = (eid, "odds")
        for eid in history_fetch:
            futures[executor.submit(client.fetch, "/v1/event/history", event_id=eid, qty=20)] = (eid, "history")
        for future in cf.as_completed(futures):
            eid, kind = futures[future]
            records[eid][kind] = future.result()
    dossier_updates = []
    for event_id, record in records.items():
        event = record["event"]
        if event_id in history_fetch:
            path = history_cache_path(state_root, event_id)
            ref = str(path.relative_to(state_root))
            cache = {"schema_version": 1, "event_id": event_id, "captured_at_utc": utc_iso(),
                     "captured_at_epoch": time.time(), "match_type": match_type(event),
                     "participants": {s: participant(event, s) for s in ("home", "away")},
                     "source": "BetsAPI Events /v1/event/history qty=20", "response": record.get("history")}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            record.update(history_source="FETCHED", history_ref=ref)
            dossier_updates.append(ref)
        record["match_type"] = match_type(event)
        record["live_stats"] = stats_availability(event)
        record["dossier"] = dossier_summary(event, record.get("history"), record.get("history_ref"))
        record["prematch"] = handoffs.get(event_id) or {"status": "PREMATCH_OPINION_NOT_FROZEN",
            "note": "No immutable prematch opinion exists for this event; no opinion was reconstructed after start."}
        record["winner_prices"] = parse_prices((record.get("odds") or {}).get("data") or {}, event, time.time())
        record["score_quote_consistency_requires_expert_review"] = True
    with_stats = sum(bool(row["event"].get("stats") or {}) for row in records.values())
    fresh = sum(row["winner_prices"].get("status") == "FRESH_NEEDS_SCORE_REVIEW" for row in records.values())
    snapshot = {"schema_version": 1, "version": VERSION, "mode": "EXPERT_DECISION_AFTER_COLLECTION",
        "observed_at_utc": utc_iso(started), "finished_at_utc": utc_iso(), "source": "BetsAPI Events",
        "quote_source": "bet365 via Events odds endpoint", "quote_max_age_seconds": QUOTE_MAX_AGE_SECONDS,
        "pool_count": len(records), "with_live_stats_count": with_stats, "with_fresh_price_count": fresh,
        "request_count": client.calls, "request_formula": "1 pool + N view + N odds + H stale/missing history",
        "history_fetched_count": len(history_fetch), "history_reused_count": len(records) - len(history_fetch),
        "dossier_updates": dossier_updates, "records": records,
        "selection_constraints": {"maximum_published": 10, "strict_minimum_odds": 1.30,
            "fill_to_ten": False, "sporting_case_before_price": True,
            "numeric_probability_without_calibration": "FORBIDDEN"}}
    snapshot["sha256_without_self"] = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LIVE_TENNIS_SUMMARY=" + json.dumps({"output": str(output), "pool": len(records),
        "with_stats": with_stats, "fresh_prices": fresh, "requests": client.calls,
        "history_fetched": len(history_fetch)}, ensure_ascii=False))
    return snapshot


def parser():
    out = argparse.ArgumentParser()
    out.add_argument("--state-root", default="state")
    out.add_argument("--output", default="live-tennis-snapshot.json")
    out.add_argument("--event-id", action="append", default=[])
    out.add_argument("--workers", type=int, default=12)
    out.add_argument("--timeout", type=int, default=12)
    return out


if __name__ == "__main__":
    collect(parser().parse_args())
