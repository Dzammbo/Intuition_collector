import json
from collections import Counter
d=json.load(open("l1-market-raw.json"))
def collect_markets(o,path=""):
 out=[]
 if isinstance(o,dict):
  for k,v in o.items():
   p=f"{path}.{k}" if path else k
   if isinstance(v,list) and v and all(isinstance(z,dict) for z in v):
    for z in v:
     odds=[]
     for kk,vv in z.items():
      if kk in ("home_od","draw_od","away_od","over_od","under_od","od","odds","price"):
       try:
        q=float(vv)
        if 1.001<=q<=100: odds.append((kk,q))
       except: pass
     if odds: out.append({"path":p,"line":z.get("handicap") or z.get("ss") or z.get("name"),"odds":odds})
   out+=collect_markets(v,p)
 elif isinstance(o,list):
  for i,v in enumerate(o): out+=collect_markets(v,f"{path}[{i}]")
 return out
rows=[]
for r in d["records"]:
 ms=collect_markets(r.get("odds") or {})
 prices=[q for m in ms for _,q in m["odds"]]
 cls="NO_ODDS"
 sig=[]
 if prices:
  cls="MARKET_CLEAN"
  if len(ms)>=2:
   ranges=[max(q for _,q in m["odds"])-min(q for _,q in m["odds"]) for m in ms if len(m["odds"])>=2]
   if ranges and max(ranges)>=0.5: sig.append("MARKET_SHAPE_ANOMALY")
  if sig: cls="MARKET_SIGNAL"
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"time":r["time"],"classification":cls,"signals":sig,"market_groups":len(ms),"observed_prices":len(prices)})
c=Counter(x["classification"] for x in rows)
out={"schema_version":2,"stage":"L1_MARKET_LOCAL_CLASSIFICATION","input":len(rows),"counts":dict(c),"records":rows,"rule":"Market classification only; CLEAN/NO_ODDS are not global PASS."}
open("l1-market-classified.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps(out["counts"]))
