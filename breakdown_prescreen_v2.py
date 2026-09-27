import json
from collections import Counter
d=json.load(open("prescreen-v2.json"))
combo=Counter();types=Counter();rows=[]
for r in d["records"]:
 if r["status"]!="CANDIDATE":continue
 ts=sorted(set(x["type"] for x in r["triggers"]))
 for t in ts:types[t]+=1
 combo[" + ".join(ts)]+=1
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"trigger_types":ts,"triggers":r["triggers"]})
out={"candidate_count":len(rows),"trigger_counts":dict(types),"combination_counts":dict(combo),"records":rows}
open("prescreen-v2-trigger-breakdown.json","w").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({"candidate_count":len(rows),"trigger_counts":dict(types),"combination_counts":dict(combo)}))
