import json,os,time,urllib.parse,urllib.request
BASE="https://api.b365api.com"
TOKEN=os.environ["BETSAPI_TOKEN"]
d=json.load(open("classified-universe.json"))
events=[dict(e,scope_status="TENNIS_SINGLES") for e in d["events"]["TENNIS_SINGLES"]]
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
  rows.append({"event_id":eid,"sport_id":e.get("sport_id"),"league":e.get("league"),
   "home":e.get("home"),"away":e.get("away"),"time":e.get("time"),
   "scope_status":"TENNIS_SINGLES","odds":x.get("results") or {}})
 except Exception as ex:
  error={"event_id":eid,"error":str(ex)};errors.append(error)
  rows.append({"event_id":eid,"sport_id":e.get("sport_id"),"league":e.get("league"),
   "home":e.get("home"),"away":e.get("away"),"time":e.get("time"),
   "scope_status":"TENNIS_SINGLES","odds":{},"technical_error":error})
 if i%25==0: print(json.dumps({"progress":i,"total":len(events),"errors":len(errors)}),flush=True)
out={"schema_version":3,"stage":"TENNIS_SINGLES_L1_MARKET_SCAN",
 "source_window_events":d["window_event_count"],"input_singles":len(events),
 "input_total":len(events),"completed":len(rows),"successful":len(rows)-len(errors),
 "errors":errors,"records":rows}
open("l1-market-raw.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input_singles":len(events),"completed":len(rows),"errors":len(errors)}))
