import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.b365api.com/v1/event/view"
TOKEN = os.environ["BETSAPI_TOKEN"]
HTTP_WORKERS = int(os.environ.get("BETSAPI_HTTP_WORKERS", "8"))

universe = json.load(open("classified-universe.json", encoding="utf-8"))
l1 = json.load(open("l1/l1-market-raw.json", encoding="utf-8"))
events = [dict(e, scope_status="TENNIS_SINGLES") for e in universe["events"]["TENNIS_SINGLES"]]
l1_ids = {str(r["event_id"]) for r in l1.get("records", [])}
expected_ids = {str(e["id"]) for e in events}
if l1_ids != expected_ids:
    raise SystemExit("L1 and tennis-singles universe differ")


def fetch_batch(batch):
    ids = ",".join(str(row["id"]) for row in batch)
    query = urllib.parse.urlencode({"token": TOKEN, "event_id": ids})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(BASE + "?" + query, timeout=25) as response:
                payload = json.load(response)
            return batch, payload.get("results") or [], None
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    return batch, [], str(last)


batches = [events[index:index + 10] for index in range(0, len(events), 10)]
rows = []
errors = []
identity_updates = []

with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as executor:
    fetched = list(executor.map(fetch_batch, batches))

for batch_number, (batch, result_rows, batch_error) in enumerate(fetched, 1):
    ids = ",".join(str(row["id"]) for row in batch)
    if batch_error:
        errors.append({"ids": ids, "error": batch_error})
        for event in batch:
            rows.append({
                **event,
                "scope_status": "TENNIS_SINGLES",
                "technical_error": {"stage": "EVENT_VIEW", "error": batch_error},
            })
    else:
        expected = {str(row["id"]): row for row in batch}
        returned = set()
        extras = []
        for row in result_rows:
            row_id = str(row.get("id"))
            if row_id in expected:
                row["scope_status"] = "TENNIS_SINGLES"
                rows.append(row)
                returned.add(row_id)
            else:
                extras.append(row)
        for row in extras:
            league_id = str((row.get("league") or {}).get("id") or "")
            participant_ids = {
                str((row.get("home") or {}).get("id") or ""),
                str((row.get("away") or {}).get("id") or ""),
            }
            candidates = []
            for missing_id, event in expected.items():
                if missing_id in returned:
                    continue
                event_league_id = str((event.get("league") or {}).get("id") or "")
                event_participant_ids = {
                    str((event.get("home") or {}).get("id") or ""),
                    str((event.get("away") or {}).get("id") or ""),
                }
                if (
                    league_id == event_league_id
                    and participant_ids == event_participant_ids
                    and "" not in participant_ids
                ):
                    candidates.append((missing_id, event))
            if len(candidates) == 1:
                original_id, event = candidates[0]
                provider_id = str(row.get("id"))
                correction = {
                    "reason": "PROVIDER_REPLACED_EVENT_ID_FOR_SAME_LEAGUE_AND_UNORDERED_PLAYER_PAIR",
                    "universe_event_id": original_id,
                    "event_view_event_id": provider_id,
                    "universe_time": event.get("time"),
                    "event_view_time": row.get("time"),
                }
                rows.append({
                    **row,
                    "id": original_id,
                    "scope_status": "TENNIS_SINGLES",
                    "provider_current_event_id": provider_id,
                    "identity_correction": correction,
                })
                returned.add(original_id)
                identity_updates.append(correction)
            else:
                errors.append({"ids": str(row.get("id")), "error": "UNREQUESTED_EVENT_VIEW_RESPONSE"})
        for missing in sorted(set(expected) - returned):
            errors.append({"ids": missing, "error": "MISSING_FROM_EVENT_VIEW_RESPONSE"})
            event = expected[missing]
            rows.append({
                **event,
                "scope_status": "TENNIS_SINGLES",
                "technical_error": {
                    "stage": "EVENT_VIEW",
                    "error": "MISSING_FROM_EVENT_VIEW_RESPONSE",
                },
            })
    print(json.dumps({
        "batches": batch_number,
        "of": len(batches),
        "records": len(rows),
        "errors": len(errors),
        "workers": HTTP_WORKERS,
    }), flush=True)

rows.sort(key=lambda row: (int(row.get("time") or 0), str(row.get("id") or "")))
out = {
    "schema_version": 4,
    "stage": "TENNIS_SINGLES_EVENT_VIEW",
    "input_singles": len(events),
    "input_total": len(events),
    "records": rows,
    "errors": errors,
    "identity_updates": identity_updates,
    "tiering_used": False,
    "completed": len(rows),
    "successful": len(rows) - sum(bool(row.get("technical_error")) for row in rows),
    "execution": {
        "mode": "BOUNDED_PARALLEL_BATCH_HTTP",
        "workers": HTTP_WORKERS,
        "provider_batch_size": 10,
        "request_count_unchanged": True,
    },
}
open("event-view-singles.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
print(json.dumps({"input_singles": len(events), "records": len(rows), "errors": len(errors)}))
