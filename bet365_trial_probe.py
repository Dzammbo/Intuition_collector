import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "https://api.b365api.com"
TOKEN = os.environ["BETSAPI_TOKEN"]
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "20"))
SPORTS = {1: "football", 13: "tennis", 16: "baseball", 17: "ice_hockey", 18: "basketball"}

def get(path, params, timeout=30):
    query = dict(params)
    query["token"] = TOKEN
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    last = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                headers = {
                    "limit": response.headers.get("X-RateLimit-Limit"),
                    "remaining": response.headers.get("X-RateLimit-Remaining"),
                    "reset": response.headers.get("X-RateLimit-Reset"),
                }
                return json.load(response), headers
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(attempt)
    raise last

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def label(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("NA") or value.get("id")
    return value

def response_shape(payload):
    results = payload.get("results") if isinstance(payload, dict) else None
    sample = results[0] if isinstance(results, list) and results else results
    if isinstance(sample, dict):
        sample = {k: label(v) for k, v in list(sample.items())[:20]}
    return {
        "top_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        "success": payload.get("success") if isinstance(payload, dict) else None,
        "error": payload.get("error") if isinstance(payload, dict) else None,
        "error_detail": payload.get("error_detail") if isinstance(payload, dict) else None,
        "results_type": type(results).__name__,
        "results_count": len(results) if isinstance(results, list) else None,
        "first_result": sample,
    }

def event_candidates(payload):
    candidates, seen = [], set()
    for node in walk(payload.get("results") if isinstance(payload, dict) else payload):
        event_id = node.get("FI") or node.get("event_id") or node.get("id") or node.get("our_event_id")
        event_like = (
            ("home" in node and "away" in node)
            or "sport_id" in node
            or "time_status" in node
            or str(node.get("type") or "").upper() in {"EV", "EVENT"}
        )
        if event_id is None or not event_like:
            continue
        event_id = str(event_id)
        if event_id in seen:
            continue
        seen.add(event_id)
        home, away = label(node.get("home")), label(node.get("away"))
        name = node.get("NA") or node.get("name")
        if not name and (home or away):
            name = f"{home or '?'} vs {away or '?'}"
        candidates.append({
            "fi": event_id,
            "name": name,
            "league": label(node.get("league") or node.get("competition")),
            "sport_id": node.get("sport_id"),
            "r_id": node.get("r_id"),
            "ev_id": node.get("ev_id"),
            "our_event_id": node.get("our_event_id"),
            "raw_keys": list(node.keys())[:30],
        })
    return candidates

def market_summary(payload):
    nodes = list(walk(payload.get("results") if isinstance(payload, dict) else payload))
    market_names, target_lines = [], []
    for node in nodes:
        if str(node.get("type") or "").upper() == "MG":
            name = str(node.get("NA") or node.get("name") or "")
            if name and name not in market_names:
                market_names.append(name)
        if str(node.get("type") or "").upper() == "PA":
            line = node.get("HA") or node.get("handicap") or node.get("line")
            try:
                numeric = abs(float(str(line).replace(",", ".")))
            except Exception:
                continue
            if 14.5 <= numeric <= 24.5:
                target_lines.append({"name": node.get("NA"), "line": line, "odds": node.get("OD")})
    text = json.dumps(payload, ensure_ascii=False)
    return {
        "has_itf_marker": bool(re.search(r"\\bITF\\b|World Tennis|M15|M25|W15|W25|W35|W50|W75|W100", text, re.I)),
        "market_count": len(market_names),
        "market_names": market_names,
        "has_total_market": any(re.search(r"total|games|goals|points|runs", x, re.I) for x in market_names),
        "has_handicap_market": any(re.search(r"handicap|spread", x, re.I) for x in market_names),
        "has_set_or_period_market": any(re.search(r"set|period|quarter|inning", x, re.I) for x in market_names),
        "target_lines": target_lines[:20],
    }

result = {"schema_version": 2, "endpoint_ok": True, "sports": {}, "events": [], "errors": []}
last_headers = {}
all_events = []
for sport_id, sport_name in SPORTS.items():
    try:
        payload, headers = get("/v1/bet365/inplay_filter", {"sport_id": sport_id})
        last_headers = headers
        events = event_candidates(payload)
        result["sports"][sport_name] = {
            "sport_id": sport_id,
            "events_found": len(events),
            "response_shape": response_shape(payload),
        }
        for event in events:
            event["sport"] = sport_name
        all_events.extend(events[:10 if sport_id == 13 else 3])
    except Exception as exc:
        result["sports"][sport_name] = {"sport_id": sport_id, "error": str(exc)}
        result["errors"].append({"sport": sport_name, "stage": "inplay_filter", "error": str(exc)})

result["id_diagnostics"] = []
first_tennis = next((x for x in all_events if x.get("sport") == "tennis"), None)
if first_tennis:
    for field in ("fi", "r_id", "ev_id", "our_event_id"):
        value = first_tennis.get(field)
        if not value:
            continue
        try:
            payload, headers = get("/v1/bet365/event", {"FI": value, "stats": 1})
            result["id_diagnostics"].append({"field": field, "value": value, "shape": response_shape(payload)})
            last_headers = headers
        except Exception as exc:
            result["id_diagnostics"].append({"field": field, "value": value, "exception": str(exc)})
result["raw_inplay"] = {"skipped": "fast identifier test"}

for event in []:
    try:
        payload, headers = get("/v1/bet365/event", {"FI": event["fi"], "stats": 1})
        result["events"].append({**event, **market_summary(payload), "response_shape": response_shape(payload)})
        last_headers = headers
    except Exception as exc:
        result["errors"].append({"sport": event["sport"], "fi": event["fi"], "stage": "event", "error": str(exc)})

result["events_probed"] = len(result["events"])
result["events_with_itf_marker"] = sum(x["has_itf_marker"] for x in result["events"])
result["events_with_total_market"] = sum(x["has_total_market"] for x in result["events"])
result["events_with_handicap_market"] = sum(x["has_handicap_market"] for x in result["events"])
result["events_with_set_or_period_market"] = sum(x["has_set_or_period_market"] for x in result["events"])
result["events_with_target_lines"] = sum(bool(x["target_lines"]) for x in result["events"])
result["rate_limit"] = last_headers
with open("bet365-trial-probe.json", "w", encoding="utf-8") as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "events"}, ensure_ascii=False))
