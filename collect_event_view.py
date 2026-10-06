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
rows=[];errors=[];identity_updates=[]
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
  for event in batch:
   rows.append({**event,"scope_status":"TENNIS_SINGLES",
    "technical_error":{"stage":"EVENT_VIEW","error":str(last)}})
 else:
  expected={str(x["id"]):x for x in batch}
  returned=set()
  extras=[]
  for row in result_rows:
   row_id=str(row.get("id"))
   if row_id in expected:
    row["scope_status"]="TENNIS_SINGLES";rows.append(row);returned.add(row_id)
   else:
    extras.append(row)
  for row in extras:
   league_id=str((row.get("league") or {}).get("id") or "")
   participant_ids={
    str((row.get("home") or {}).get("id") or ""),
    str((row.get("away") or {}).get("id") or ""),
   }
   candidates=[]
   for missing_id,event in expected.items():
    if missing_id in returned: continue
    event_league_id=str((event.get("league") or {}).get("id") or "")
    event_participant_ids={
     str((event.get("home") or {}).get("id") or ""),
     str((event.get("away") or {}).get("id") or ""),
    }
    if league_id==event_league_id and participant_ids==event_participant_ids and "" not in participant_ids:
     candidates.append((missing_id,event))
   if len(candidates)==1:
    original_id,event=candidates[0]
    provider_id=str(row.get("id"))
    provider_time=row.get("time")
    normalized={**row,"id":original_id,"scope_status":"TENNIS_SINGLES",
     "provider_current_event_id":provider_id,
     "identity_correction":{
      "reason":"PROVIDER_REPLACED_EVENT_ID_FOR_SAME_LEAGUE_AND_UNORDERED_PLAYER_PAIR",
      "universe_event_id":original_id,
      "event_view_event_id":provider_id,
      "universe_time":event.get("time"),
      "event_view_time":provider_time,
     }}
    rows.append(normalized);returned.add(original_id)
    identity_updates.append(normalized["identity_correction"])
   else:
    errors.append({"ids":str(row.get("id")),"error":"UNREQUESTED_EVENT_VIEW_RESPONSE"})
  for missing in sorted(set(expected)-returned):
   errors.append({"ids":missing,"error":"MISSING_FROM_EVENT_VIEW_RESPONSE"})
   event=expected[missing]
   rows.append({**event,"scope_status":"TENNIS_SINGLES",
    "technical_error":{"stage":"EVENT_VIEW","error":"MISSING_FROM_EVENT_VIEW_RESPONSE"}})
 print(json.dumps({"batches":i//10+1,"of":(len(events)+9)//10,"records":len(rows),"errors":len(errors)}),flush=True)
rows.sort(key=lambda x:(int(x.get("time") or 0),str(x.get("id") or "")))
out={"schema_version":3,"stage":"TENNIS_SINGLES_EVENT_VIEW","input_singles":len(events),
 "input_total":len(events),"records":rows,"errors":errors,"identity_updates":identity_updates,"tiering_used":False,
 "completed":len(rows),"successful":len(rows)-sum(bool(x.get("technical_error")) for x in rows)}
open("event-view-singles.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input_singles":len(events),"records":len(rows),"errors":len(errors)}))
