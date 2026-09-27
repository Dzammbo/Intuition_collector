import json
from collections import Counter
d=json.load(open("l1-market-raw.json"))
PRICE_KEYS={"home_od","draw_od","away_od","over_od","under_od","od","odds","price","home","draw","away","over","under","1","2","x"}
def price(v):
 try:
  q=float(v)
  return q if 1.001<=q<=100 else None
 except:return None
def extract(o,path=""):
 out=[]
 if isinstance(o,dict):
  direct=[]
  for k,v in o.items():
   q=price(v)
   if q is not None and (k.lower() in PRICE_KEYS or k.lower().endswith("_od")): direct.append((k,q))
  if direct: out.append({"path":path,"odds":direct})
  for k,v in o.items(): out+=extract(v,f"{path}.{k}" if path else k)
 elif isinstance(o,list):
  for i,v in enumerate(o):out+=extract(v,f"{path}[{i}]")
 return out
rows=[]
for r in d["records"]:
 ms=extract(r.get("odds") or {})
 prices=[q for m in ms for _,q in m["odds"]]
 cls="NO_PRICES_IN_RESPONSE" if not prices else "MARKET_CLEAN"
 signals=[]
 # Conservative L1: presence/coverage only until market-specific normalization is validated.
 if len(prices)>=6 and len(ms)>=2:
  cls="MARKET_SIGNAL"
  signals.append("MULTI_MARKET_DATA_AVAILABLE")
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"time":r["time"],"classification":cls,"signals":signals,"market_groups":len(ms),"observed_prices":len(prices)})
c=Counter(x["classification"] for x in rows)
out={"schema_version":3,"stage":"L1_MARKET_NORMALIZED","input":len(rows),"counts":dict(c),"records":rows,"rule":"Schema-complete recursive price extraction. MULTI_MARKET_DATA_AVAILABLE is a coverage signal, not an EV claim. No event is globally passed/failed here."}
open("l1-market-classified.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps(out["counts"]))
