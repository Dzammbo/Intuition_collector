import json,math
from collections import Counter
d=json.load(open("market-normalized-v1.json"))
def fair_probs(odds):
 vals=[1/x for x in odds]
 s=sum(vals)
 return [v/s for v in vals] if s else []
rows=[]
for r in d["records"]:
 ms=r["markets"];tr=[]
 # Snapshot-only trigger 1: unusually high overround in any 2/3-way quoted group -> market-quality anomaly.
 for m in ms:
  os=list(m["odds"].values())
  if len(os) in (2,3):
   ov=sum(1/x for x in os)-1
   if ov>=0.12: tr.append({"type":"HIGH_OVERROUND","market":m["path"],"overround_pct":round(ov*100,2)})
 # Snapshot-only trigger 2: multiple distinct explicit lines exposed within same structural path.
 by={}
 for m in ms:
  if m["line"] not in (None,""):by.setdefault(m["path"],set()).add(str(m["line"]))
 for p,lines in by.items():
  if len(lines)>=2:tr.append({"type":"MULTIPLE_LINES_SNAPSHOT","market":p,"lines":sorted(lines)[:12]})
 # Snapshot-only trigger 3: rich market coverage suitable for deterministic cross-market deepening.
 rich=len(ms)>=3 and r["observed_prices"]>=8
 if rich:tr.append({"type":"RICH_MARKET_SNAPSHOT","market_groups":len(ms),"observed_prices":r["observed_prices"]})
 status="CANDIDATE" if tr else ("INSUFFICIENT_MARKET_DATA" if not ms else "NO_TRIGGER")
 rows.append({**{k:r[k] for k in ("event_id","sport_id","league","home","away","time")},"status":status,"triggers":tr,"market_groups":r["market_groups"],"observed_prices":r["observed_prices"]})
c=Counter(x["status"] for x in rows)
out={"schema_version":2,"stage":"REPRODUCIBLE_SNAPSHOT_PRESCREEN_V2","dataset_assumption":"Single odds snapshot per event. No line-movement or temporal-price triggers are permitted.","rules":{"HIGH_OVERROUND":"2/3-way quoted group overround >=12%; quality/anomaly trigger, not directional EV.","MULTIPLE_LINES_SNAPSHOT":"At least two explicit line values exposed under the same structural market path.","RICH_MARKET_SNAPSHOT":"At least 3 parsed market groups and 8 observed prices; promotes for cross-market analysis, not itself an EV claim.","candidate_logic":"OR across snapshot-only objective triggers. No subjective weights or intuition."},"counts":dict(c),"records":rows}
open("prescreen-v2.json","w").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out["counts"]))
