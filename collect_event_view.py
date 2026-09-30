import json,os,time,urllib.parse,urllib.request
BASE="https://api.b365api.com/v1/event/view"
TOKEN=os.environ["BETSAPI_TOKEN"]

universe=json.load(open("classified-universe.json",encoding="utf-8"))
l1=json.load(open("l1/l1-market-raw.json",encoding="utf-8"))
core=list(universe["events"]["CORE"])
secondary=list(universe["events"]["SECONDARY"])
l1_by_id={str(r["event_id"]):r for r in l1.get("records",[])}

def normalized_quote(q):
 return {k:v for k,v in q.items() if k not in {"id","add_time","time_str","ss"}}

promotion_audit=[]
promoted=[]
for event in secondary:
 eid=str(event["id"])
 record=l1_by_id.get(eid)
 signal_markets=[]
 if record:
  markets=(((record.get("odds") or {}).get("odds")) or {})
  for market_key,quotes in markets.items():
   if not isinstance(quotes,list) or len(quotes)<2:
    continue
   unique={json.dumps(normalized_quote(q),sort_keys=True,ensure_ascii=False) for q in quotes if isinstance(q,dict)}
   if len(unique)>1:
    signal_markets.append(str(market_key))
 if signal_markets:
  promoted.append(event)
  promotion_audit.append({"event_id":eid,"source_tier":"SECONDARY","status":"PROMOTED","reason":"AUDITABLE_L1_PRICE_OR_LINE_MOVEMENT","signal_markets":sorted(signal_markets)})
 else:
  promotion_audit.append({"event_id":eid,"source_tier":"SECONDARY","status":"NOT_PROMOTED","reason":"NO_AUDITABLE_MULTI_SNAPSHOT_MOVEMENT","signal_markets":[]})

events=[dict(e,source_tier="CORE") for e in core]+[dict(e,source_tier="SECONDARY") for e in promoted]
rows=[]
errors=[]
for i in range(0,len(events),10):
 batch=events[i:i+10]
 ids=",".join(str(x["id"]) for x in batch)
 q=urllib.parse.urlencode({"token":TOKEN,"event_id":ids})
 last=None
 result_rows=[]
 for a in range(4):
  try:
   with urllib.request.urlopen(BASE+"?"+q,timeout=25) as r:
    payload=json.load(r)
   result_rows=payload.get("results") or []
   last=None
   break
  except Exception as exc:
   last=exc
   if a<3:
    time.sleep(1.5*(a+1))
 if last:
  errors.append({"ids":ids,"error":str(last)})
 else:
  expected={str(x["id"]):x.get("source_tier") for x in batch}
  returned={str(x.get("id")) for x in result_rows}
  for row in result_rows:
   row["source_tier"]=expected.get(str(row.get("id")))
   rows.append(row)
  for missing in sorted(set(expected)-returned):
   errors.append({"ids":missing,"error":"MISSING_FROM_EVENT_VIEW_RESPONSE","source_tier":expected[missing]})
 print(json.dumps({"batches":i//10+1,"of":(len(events)+9)//10,"records":len(rows),"errors":len(errors)}),flush=True)

out={
 "schema_version":2,
 "stage":"TIER_AWARE_EVENT_VIEW_DATA_LAKE",
 "input_core":len(core),
 "input_secondary":len(secondary),
 "promoted_secondary":len(promoted),
 "not_promoted_secondary":len(secondary)-len(promoted),
 "input_total":len(events),
 "records":rows,
 "errors":errors,
 "promotion_audit":promotion_audit
}
open("event-view-core.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({k:out[k] for k in ("input_core","input_secondary","promoted_secondary","not_promoted_secondary","input_total")}|{"records":len(rows),"errors":len(errors)}))
