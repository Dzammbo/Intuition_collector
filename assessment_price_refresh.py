#!/usr/bin/env python3
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE="https://api.b365api.com"
TOKEN=os.environ["BETSAPI_TOKEN"]
TRIGGER="triggers/run-assessment-price-refresh.json"
cfg=json.load(open(TRIGGER,encoding="utf-8"))
ids=[str(x) for x in cfg.get("event_ids") or []]
if not ids or len(ids)>50 or len(ids)!=len(set(ids)):
 raise SystemExit("event_ids must contain 1-50 unique ids")

def iso():
 return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

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

rows=[];errors=[]
for i,eid in enumerate(ids,1):
 try: rows.append(get(eid))
 except Exception as exc: errors.append({"event_id":eid,"retrieved_at":iso(),"error":str(exc)})
 print(json.dumps({"progress":i,"total":len(ids),"errors":len(errors)}),flush=True)
out={"schema_version":1,"stage":"ASSESSMENT_CURRENT_PRICE_REFRESH","date_moscow":cfg["date_moscow"],"batch":cfg["batch"],"trigger_requested_at":cfg.get("requested_at"),"generated_at":iso(),"input_count":len(ids),"completed":len(rows),"errors":errors,"records":rows}
open("assessment-price-refresh.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"completed":len(rows),"errors":len(errors)}))
