import json,os,time,urllib.parse,urllib.request,math
BASE="https://api.b365api.com"
TOKEN=os.environ["BETSAPI_TOKEN"]
d=json.load(open("classified-universe.json"))
core_events=d["events"]["CORE"]
secondary_events=d["events"]["SECONDARY"]
events=[dict(e,source_tier="CORE") for e in core_events]+[dict(e,source_tier="SECONDARY") for e in secondary_events]
def get(event_id):
 q=urllib.parse.urlencode({"token":TOKEN,"event_id":event_id})
 url=BASE+"/v2/event/odds?"+q
 last=None
 for a in range(4):
  try:
   with urllib.request.urlopen(url,timeout=20) as r:return json.load(r)
  except Exception as e:
   last=e
   if a<3: time.sleep(1.5*(a+1))
 raise last
rows=[];errors=[]
for i,e in enumerate(events,1):
 eid=str(e.get("id"))
 try:
  x=get(eid)
  results=x.get("results") or {}
  rows.append({"event_id":eid,"sport_id":e.get("sport_id"),"league":e.get("league"),"home":e.get("home"),"away":e.get("away"),"time":e.get("time"),"source_tier":e.get("source_tier"),"odds":results})
 except Exception as ex:
  errors.append({"event_id":eid,"error":str(ex)})
 if i%25==0: print(json.dumps({"progress":i,"total":len(events),"errors":len(errors)}),flush=True)
out={"schema_version":2,"stage":"L1_MARKET_SCAN_RAW","source_window_events":d["window_event_count"],"input_core":len(core_events),"input_secondary":len(secondary_events),"input_total":len(events),"completed":len(rows),"errors":errors,"records":rows}
open("l1-market-raw.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input_core":len(core_events),"input_secondary":len(secondary_events),"input_total":len(events),"completed":len(rows),"errors":len(errors)}))
