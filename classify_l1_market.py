import json,statistics,math
d=json.load(open("l1-market-raw.json"))
def nums(o):
 out=[]
 if isinstance(o,dict):
  for k,v in o.items():
   if k in ("odds","price","open","opening","close","closing") and isinstance(v,(int,float,str)):
    try:
     x=float(v)
     if 1.01<=x<=100: out.append(x)
    except: pass
   out+=nums(v)
 elif isinstance(o,list):
  for v in o: out+=nums(v)
 return out
rows=[]
for r in d["records"]:
 o=r.get("odds") or {}; xs=nums(o)
 markets=len(o) if isinstance(o,dict) else 0
 spread=(max(xs)-min(xs)) if len(xs)>=2 else 0
 status="NO_ODDS" if not xs else ("STRONG_MARKET_SIGNAL" if spread>=1.0 and len(xs)>=4 else ("MARKET_SIGNAL" if spread>=0.35 and len(xs)>=2 else "MARKET_CLEAN"))
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"time":r["time"],"classification":status,"observed_prices":len(xs),"market_groups":markets,"price_range":round(spread,4)})
from collections import Counter
c=Counter(x["classification"] for x in rows)
out={"schema_version":1,"stage":"L1_MARKET_LOCAL_CLASSIFICATION","input":len(rows),"counts":dict(c),"records":rows,"note":"Heuristic prioritization only; MARKET_CLEAN and NO_ODDS are not global PASS because other Broad Signal channels remain independent."}
open("l1-market-classified.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps(out["counts"]))
