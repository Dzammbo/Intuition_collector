import json,os,time,urllib.parse,urllib.request
BASE="https://api.b365api.com/v1/event/view";TOKEN=os.environ["BETSAPI_TOKEN"]
d=json.load(open("classified-universe.json"));ev=d["events"]["CORE"]
rows=[];errors=[]
for i in range(0,len(ev),10):
 batch=ev[i:i+10];ids=",".join(str(x["id"]) for x in batch)
 q=urllib.parse.urlencode({"token":TOKEN,"event_id":ids})
 last=None
 for a in range(4):
  try:
   with urllib.request.urlopen(BASE+"?"+q,timeout=25) as r:x=json.load(r)
   rows.extend(x.get("results") or []);last=None;break
  except Exception as e:
   last=e
   if a<3:time.sleep(1.5*(a+1))
 if last:errors.append({"ids":ids,"error":str(last)})
 print(json.dumps({"batches":i//10+1,"of":(len(ev)+9)//10,"records":len(rows),"errors":len(errors)}),flush=True)
out={"schema_version":1,"stage":"EVENT_VIEW_DATA_LAKE","input_core":len(ev),"records":rows,"errors":errors}
open("event-view-core.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input_core":len(ev),"records":len(rows),"errors":len(errors)}))
