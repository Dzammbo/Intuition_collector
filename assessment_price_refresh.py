#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://api.b365api.com"
TOKEN = os.environ["BETSAPI_TOKEN"]
REQUEST_PATH = os.environ.get("PRICE_REVEAL_REQUEST", "triggers/run-assessment-price-refresh.json")
HTTP_WORKERS = int(os.environ.get("BETSAPI_HTTP_WORKERS", "8"))
cfg = json.load(open(REQUEST_PATH, encoding="utf-8"))
events = cfg.get("events") or []
if not events:
    raise SystemExit("price reveal worklist contains no queryable events")
ids = [str(row["event_id"]) for row in events]
if len(ids) != len(set(ids)):
    raise SystemExit("event ids must be unique")


def now():
    return datetime.now(timezone.utc)


def iso(value=None):
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get(event_id):
    query = urllib.parse.urlencode({"token": TOKEN, "event_id": event_id, "source": "bet365"})
    url = BASE + "/v2/event/odds?" + query
    last = None
    for attempt in range(4):
        requested = iso()
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.load(response)
            return {
                "event_id": event_id,
                "requested_at": requested,
                "retrieved_at": iso(),
                "odds": payload.get("results") or {},
            }
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise last


def collect(event):
    event_id = str(event["event_id"])
    checked_at = iso()
    if now() >= parse_iso(event["scheduled_start_utc"]):
        return None, None, {
            "event_id": event_id,
            "checked_at": checked_at,
            "reason": "STARTED_BEFORE_PRICE_QUERY",
        }
    try:
        record = get(event_id)
        for key in (
            "scheduled_start_utc",
            "supported_side",
            "assessment_ref",
            "assessment_sha256",
        ):
            record[key] = event[key]
        return record, None, None
    except Exception as exc:
        return None, {
            "event_id": event_id,
            "retrieved_at": iso(),
            "error": str(exc),
        }, None


rows = []
errors = []
skipped = list(cfg.get("prefiltered_started") or [])
with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as executor:
    for index, (record, error, skip) in enumerate(executor.map(collect, events), 1):
        if record:
            rows.append(record)
        if error:
            errors.append(error)
        if skip:
            skipped.append(skip)
        if index % 25 == 0 or index == len(events):
            print(json.dumps({
                "progress": index,
                "total": len(events),
                "completed": len(rows),
                "skipped": len(skipped),
                "errors": len(errors),
                "workers": HTTP_WORKERS,
            }), flush=True)

out = {
    "schema_version": 2,
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
    "execution": {
        "mode": "BOUNDED_PARALLEL_HTTP_WITH_PER_EVENT_PREMATCH_GATE",
        "workers": HTTP_WORKERS,
        "input_order_preserved": True,
        "request_count_unchanged": True,
    },
}
open("assessment-price-refresh.json", "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps({"completed": len(rows), "skipped": len(skipped), "errors": len(errors)}))
