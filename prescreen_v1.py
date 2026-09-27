import json,math
d=json.load(open("market-normalized-v1.json"))
rows=[]
for r in d["records"]:
 triggers=[]
 ms=r["markets"]
 # Trigger A: market history has same path with materially changed quoted price.
 by={}
 for m in ms:by.setdefault(m["path"],[]).append(m)
 for p,xs in by.items():
  if len(xs)<2:continue
  keys=set.intersection(*(set(x["odds"]) for x in xs))
  for k in keys:
   vals=[x["odds"][k] for x in xs]
   probs=[1/v for v in vals]
   if max(probs)-min(probs)>=0.05:
    triggers.append({"type":"PRICE_PROB_MOVE_5PP","market":p,"selection":k,"delta_pp":round((max(probs)-min(probs))*100,2)})
 # Trigger B: explicit line value changed inside same normalized market path.
 for p,xs in by.items():
  lines=[str(x["line"]) for x in xs if x["line"] not in (None,"")]
  if len(set(lines))>=2:triggers.append({"type":"LINE_MOVE","market":p,"lines":list(dict.fromkeys(lines))[:8]})
 status="CANDIDATE" if triggers else ("INSUFFICIENT_MARKET_DATA" if not ms else "NO_TRIGGER")
 rows.append({**{k:r[k] for k in ("event_id","sport_id","league","home","away","time")},"status":status,"triggers":triggers,"market_groups":r["market_groups"],"observed_prices":r["observed_prices"]})
from collections import Counter
c=Counter(x["status"] for x in rows)
out={"schema_version":1,"stage":"REPRODUCIBLE_PRESCREEN_V1","rules":{"PRICE_PROB_MOVE_5PP":"Within the same normalized market path/selection, implied probability range >=5 percentage points.","LINE_MOVE":"At least two distinct explicit line values observed within the same normalized market path.","candidate_logic":"OR across objective triggers. No subjective weights or intuition."},"counts":dict(c),"records":rows}
open("prescreen-v1.json","w").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out["counts"]))
