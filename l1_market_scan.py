import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.b365api.com"
TOKEN = os.environ["BETSAPI_TOKEN"]
HTTP_WORKERS = int(os.environ.get("BETSAPI_HTTP_WORKERS", "8"))

d = json.load(open("classified-universe.json", encoding="utf-8"))
events = [dict(e, scope_status="TENNIS_SINGLES") for e in d["events"]["TENNIS_SINGLES"]]


def get(event_id):
    query = urllib.parse.urlencode({"token": TOKEN, "event_id": event_id})
    url = BASE + "/v2/event/odds?" + query
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise last


def collect(event):
    event_id = str(event.get("id"))
    base = {
        "event_id": event_id,
        "sport_id": event.get("sport_id"),
        "league": event.get("league"),
        "home": event.get("home"),
        "away": event.get("away"),
        "time": event.get("time"),
        "scope_status": "TENNIS_SINGLES",
    }
    try:
        payload = get(event_id)
        return {**base, "odds": payload.get("results") or {}}, None
    except Exception as exc:
        error = {"event_id": event_id, "error": str(exc)}
        return {**base, "odds": {}, "technical_error": error}, error


rows = []
errors = []
with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as executor:
    for index, (row, error) in enumerate(executor.map(collect, events), 1):
        rows.append(row)
        if error:
            errors.append(error)
        if index % 25 == 0 or index == len(events):
            print(json.dumps({
                "progress": index,
                "total": len(events),
                "errors": len(errors),
                "workers": HTTP_WORKERS,
            }), flush=True)

out = {
    "schema_version": 4,
    "stage": "TENNIS_SINGLES_L1_MARKET_SCAN",
    "source_window_events": d["window_event_count"],
    "input_singles": len(events),
    "input_total": len(events),
    "completed": len(rows),
    "successful": len(rows) - len(errors),
    "errors": errors,
    "records": rows,
    "execution": {
        "mode": "BOUNDED_PARALLEL_HTTP",
        "workers": HTTP_WORKERS,
        "input_order_preserved": True,
        "request_count_unchanged": True,
    },
}
open("l1-market-raw.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
print(json.dumps({"input_singles": len(events), "completed": len(rows), "errors": len(errors)}))
