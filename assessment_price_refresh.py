#!/usr/bin/env python3
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE="https://api.b365api.com"
TOKEN=os.environ["BETSAPI_TOKEN"]
TRIGGER="triggers/run-assessment-price-refresh.json"
cfg=json.load(open(TRIGGER,encoding="utf-8"))
events=cfg.get("events") or []
if not events or len(events)>50:
 raise SystemExit("events must contain 1-50 rows")
ids=[str(x["event_id"]) for x in events]
if len(ids)!=len(set(ids)):
 raise SystemExit("event ids must be unique")

def now():
 return datetime.now(timezone.utc)

def iso(dt=None):
 return (dt or now()).isoformat().replace("+00:00","Z")

def parse_iso(value):
 return datetime.fromisoformat(value.replace("Z","+00:00"))

def get(eid):
 q=urllib.parse.urlencode({"token":TOKEN,"event_id":eid,"source":"bet365"})
 url=BASE+"/v2/event/odds?"+q
 last=None
 for attempt in range(4):
  requested=iso()
  try:
   with urllib.request.urlopen(url,timeout=20) as r:
    payload=json.load(r)
   return {"event_id":eid,"requested_at":requested,"retrieved_at":iso(),"odds":payload.get("results") or {}}
  except Exception as exc:
   last=exc
   if attempt<3: time.sleep(1.5*(attempt+1))
 raise last

rows=[]; errors=[]; skipped=[]
for i,event in enumerate(events,1):
 eid=str(event["event_id"])
 if now() >= parse_iso(event["scheduled_start_utc"]):
  skipped.append({"event_id":eid,"checked_at":iso(),"reason":"STARTED_BEFORE_PRICE_QUERY"})
 else:
  try:
   record=get(eid)
   record["scheduled_start_utc"]=event["scheduled_start_utc"]
   record["supported_side"]=event["supported_side"]
   record["assessment_ref"]=event["assessment_ref"]
   record["assessment_sha256"]=event["assessment_sha256"]
   rows.append(record)
  except Exception as exc:
   errors.append({"event_id":eid,"retrieved_at":iso(),"error":str(exc)})
 print(json.dumps({"progress":i,"total":len(ids),"completed":len(rows),"skipped":len(skipped),"errors":len(errors)}),flush=True)
out={"schema_version":1,"stage":"PRICE_REVEAL_RAW_CAPTURE","date_moscow":cfg["date_moscow"],"batch":cfg["batch"],"trigger_requested_at":cfg.get("requested_at"),"generated_at":iso(),"input_count":len(ids),"completed":len(rows),"skipped_started":skipped,"errors":errors,"records":rows}
open("assessment-price-refresh.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"completed":len(rows),"skipped":len(skipped),"errors":len(errors)}))
