import json,os,time,urllib.parse,urllib.request
BASE="https://api.b365api.com/v1/event/view"
TOKEN=os.environ["BETSAPI_TOKEN"]
universe=json.load(open("classified-universe.json",encoding="utf-8"))
l1=json.load(open("l1/l1-market-raw.json",encoding="utf-8"))
events=[dict(e,scope_status="TENNIS_SINGLES") for e in universe["events"]["TENNIS_SINGLES"]]
l1_ids={str(r["event_id"]) for r in l1.get("records",[])}
expected_ids={str(e["id"]) for e in events}
if l1_ids!=expected_ids:
 raise SystemExit("L1 and tennis-singles universe differ")
rows=[];errors=[]
for i in range(0,len(events),10):
 batch=events[i:i+10]
 ids=",".join(str(x["id"]) for x in batch)
 q=urllib.parse.urlencode({"token":TOKEN,"event_id":ids})
 last=None;result_rows=[]
 for a in range(4):
  try:
   with urllib.request.urlopen(BASE+"?"+q,timeout=25) as r: payload=json.load(r)
   result_rows=payload.get("results") or [];last=None;break
  except Exception as exc:
   last=exc
   if a<3: time.sleep(1.5*(a+1))
 if last:
  errors.append({"ids":ids,"error":str(last)})
 else:
  returned={str(x.get("id")) for x in result_rows}
  for row in result_rows:
   row["scope_status"]="TENNIS_SINGLES";rows.append(row)
  for missing in sorted({str(x["id"]) for x in batch}-returned):
   errors.append({"ids":missing,"error":"MISSING_FROM_EVENT_VIEW_RESPONSE"})
 print(json.dumps({"batches":i//10+1,"of":(len(events)+9)//10,"records":len(rows),"errors":len(errors)}),flush=True)
out={"schema_version":3,"stage":"TENNIS_SINGLES_EVENT_VIEW","input_singles":len(events),
 "input_total":len(events),"records":rows,"errors":errors,"tiering_used":False}
open("event-view-singles.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input_singles":len(events),"records":len(rows),"errors":len(errors)}))
