import json,os,time,urllib.parse,urllib.request
from datetime import datetime,timezone,timedelta
SPORTS={"13":"tennis","16":"baseball","17":"ice_hockey","18":"basketball"}
EXCLUDED_SPORTS={"1":"soccer"}
BASE="https://api.b365api.com"
def get(path,params,timeout=20):
 p=dict(params);p["token"]=os.environ["BETSAPI_TOKEN"]
 url=BASE+path+"?"+urllib.parse.urlencode(p)
 last=None
 for attempt in range(1,5):
  try:
   with urllib.request.urlopen(url,timeout=timeout) as r:return json.load(r)
  except Exception as e:
   last=e
   if attempt<4:
    time.sleep(1.5*attempt)
 raise last
def collect_feed(sid,day):
 events=[];page=1;reported=None
 while True:
  d=get("/v3/events/upcoming",{"sport_id":sid,"day":day,"page":page,"skip_esports":1})
  rows=d.get("results") or []
  if reported is None:
   try: reported=int(d.get("pager",{}).get("total") or d.get("total") or 0)
   except: reported=None
  events.extend(rows)
  pager=d.get("pager") or {}
  total_pages=pager.get("total_pages") or pager.get("last_page")
  if total_pages is not None:
   try:
    if page>=int(total_pages):
     if reported is None or len(events)>=reported: break
   except: pass
  if not rows: break
  if reported is not None and len(events)>=reported: break
  if len(rows)<50 and reported is None: break
  page+=1
  if page>100: raise RuntimeError("pagination_guard")
 return {"sport_id":int(sid),"sport":SPORTS[sid],"day_utc":day,"pages":page,"reported_total":reported,"rows":len(events),"events":events}
now=datetime.now(timezone.utc);days=[now.strftime("%Y%m%d"),(now+timedelta(days=1)).strftime("%Y%m%d")]
feeds=[];errors=[]
for sid in SPORTS:
 for day in days:
  try:
   x=collect_feed(sid,day);feeds.append(x);print(json.dumps({"feed":"complete","sport":SPORTS[sid],"day":day,"rows":x["rows"],"pages":x["pages"],"reported_total":x["reported_total"]}),flush=True)
  except Exception as e:
   errors.append({"sport_id":sid,"day":day,"error":str(e)});print(json.dumps({"feed":"error","sport":SPORTS[sid],"day":day,"error":str(e)}),flush=True)
start=int(now.timestamp());end=int((now+timedelta(hours=24)).timestamp())
all_events={str(e.get("id")):e for f in feeds for e in f["events"] if e.get("id") is not None}
window=[e for e in all_events.values() if str(e.get("time","")).isdigit() and start<=int(e["time"])<end]
out={"captured_at":now.isoformat(),"window_start":start,"window_end":end,"active_sports":list(SPORTS.values()),"excluded_sports":list(EXCLUDED_SPORTS.values()),"expected_feeds":8,"feeds":feeds,"errors":errors,"raw_unique_events":len(all_events),"window_events":window,"window_event_count":len(window)}
open("universe.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"feeds_complete":len(feeds),"errors":len(errors),"raw_unique_events":len(all_events),"window_events":len(window)}))
if errors: raise SystemExit(2)
