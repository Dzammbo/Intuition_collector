import json
from collections import Counter,defaultdict
d=json.load(open("l1-market-raw.json"))
def has_recognized(o):
 if isinstance(o,dict):
  for k,v in o.items():
   if k in ("home_od","draw_od","away_od","over_od","under_od","od","odds","price"):
    try:
     q=float(v)
     if 1.001<=q<=100:return True
    except: pass
   if has_recognized(v):return True
 elif isinstance(o,list):
  return any(has_recognized(x) for x in o)
 return False
rows=[]
for r in d["records"]:
 o=r.get("odds")
 if has_recognized(o): continue
 if o is None: cls="NULL_RESULTS"
 elif o=={} or o==[]: cls="EMPTY_RESULTS"
 elif isinstance(o,dict):
  cls="NONEMPTY_UNPARSED"
 else: cls="OTHER_SCHEMA"
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"class":cls,"top_type":type(o).__name__,"top_keys":list(o.keys())[:30] if isinstance(o,dict) else [],"sample":o if isinstance(o,(dict,list)) else str(o)})
c=Counter(x["class"] for x in rows);sp=defaultdict(Counter)
for x in rows:sp[str(x["sport_id"])][x["class"]]+=1
out={"input_no_odds":len(rows),"counts":dict(c),"by_sport":{k:dict(v) for k,v in sp.items()},"records":rows}
open("no-odds-diagnostic.json","w").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({"input_no_odds":len(rows),"counts":dict(c),"by_sport":out["by_sport"]}))
