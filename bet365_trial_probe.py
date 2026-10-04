import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "https://api.b365api.com"
TOKEN = os.environ["BETSAPI_TOKEN"]
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "30"))


def get(path, params, timeout=30):
    query = dict(params)
    query["token"] = TOKEN
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    last = None
    for attempt in range(1, 5):
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
            if attempt < 4:
                time.sleep(1.5 * attempt)
    raise last


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def event_candidates(payload):
    candidates = []
    seen = set()
    for node in walk(payload.get("results") or payload):
        kind = str(node.get("type") or "").upper()
        if kind not in {"EV", "EVENT"} and not any(k in node for k in ("FI", "event_id")):
            continue
        event_id = node.get("FI") or node.get("event_id") or node.get("ID") or node.get("id")
        if event_id is None:
            continue
        event_id = str(event_id)
        if event_id in seen:
            continue
        seen.add(event_id)
        candidates.append({
            "fi": event_id,
            "name": node.get("NA") or node.get("name"),
            "league": node.get("league") or node.get("competition"),
            "raw_type": kind,
        })
    return candidates


def market_summary(payload):
    nodes = list(walk(payload.get("results") or payload))
    market_names = []
    selections = []
    current_market = None
    for node in nodes:
        kind = str(node.get("type") or "").upper()
        if kind == "MG":
            current_market = str(node.get("NA") or node.get("name") or "")
            if current_market and current_market not in market_names:
                market_names.append(current_market)
        elif kind == "PA":
            name = str(node.get("NA") or node.get("name") or "")
            handicap = node.get("HA") or node.get("handicap") or node.get("line")
            odds = node.get("OD") or node.get("odds")
            if current_market and re.search(r"total games|game lines|games total|тотал", current_market, re.I):
                selections.append({
                    "market": current_market,
                    "name": name,
                    "line": handicap,
                    "odds": odds,
                    "suspended": node.get("SU"),
                })
    text = json.dumps(payload, ensure_ascii=False)
    has_itf = bool(re.search(r"\bITF\b|World Tennis|M15|M25|W15|W25|W35|W50|W75|W100", text, re.I))
    total_markets = [x for x in market_names if re.search(r"total games|game lines|games total|тотал", x, re.I)]
    handicap_markets = [x for x in market_names if re.search(r"handicap|game handicap|games handicap|фора", x, re.I)]
    set_markets = [x for x in market_names if re.search(r"set", x, re.I)]
    target_selections = []
    for selection in selections:
        try:
            line = abs(float(str(selection.get("line", "")).replace(",", ".")))
        except Exception:
            continue
        if 14.5 <= line <= 18.5:
            target_selections.append(selection)
    return {
        "has_itf_marker": has_itf,
        "market_count": len(market_names),
        "market_names": market_names,
        "total_game_markets": total_markets,
        "handicap_markets": handicap_markets,
        "set_markets": set_markets,
        "target_total_selections": target_selections,
    }


inplay, headers = get("/v1/bet365/inplay_filter", {"sport_id": 13})
events = event_candidates(inplay)
probed = []
errors = []
for event in events[:MAX_EVENTS]:
    try:
        payload, event_headers = get("/v1/bet365/event", {"FI": event["fi"], "stats": 1})
        summary = market_summary(payload)
        probed.append({**event, **summary, "rate_limit": event_headers})
    except Exception as exc:
        errors.append({"fi": event["fi"], "error": str(exc)})

result = {
    "schema_version": 1,
    "endpoint_ok": True,
    "inplay_tennis_events_found": len(events),
    "events_probed": len(probed),
    "events_with_itf_marker": sum(x["has_itf_marker"] for x in probed),
    "events_with_total_games": sum(bool(x["total_game_markets"]) for x in probed),
    "events_with_handicaps": sum(bool(x["handicap_markets"]) for x in probed),
    "events_with_set_markets": sum(bool(x["set_markets"]) for x in probed),
    "events_with_target_14_5_18_5": sum(bool(x["target_total_selections"]) for x in probed),
    "rate_limit": headers,
    "errors": errors,
    "events": probed,
}
with open("bet365-trial-probe.json", "w", encoding="utf-8") as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "events"}, ensure_ascii=False))
