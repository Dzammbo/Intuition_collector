import json
from datetime import datetime,timezone
u=json.load(open("universe.json"))
cutoff=datetime.fromisoformat(u["captured_at"]).timestamp()+1200
eligible=[];excluded=[]
seen=set()
for e in u["window_events"]:
 eid=str(e.get("id") or "")
 t=e.get("time")
 reason=None
 if not eid or not str(t or "").isdigit(): reason="CORRUPT_DATA"
 elif eid in seen: reason="DUPLICATE"
 elif int(t)<cutoff: reason="INSUFFICIENT_FREEZE_TIME"
 if reason: excluded.append({"id":eid,"reason":reason})
 else: eligible.append(e)
 seen.add(eid)
out={"schema_version":1,"source_run_id":36308695060,"captured_at":u["captured_at"],"raw_universe":len(u["window_events"]),"technically_eligible":len(eligible),"excluded":len(excluded),"excluded_records":excluded,"events":eligible}
open("technically-eligible.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"raw":len(u["window_events"]),"eligible":len(eligible),"excluded":len(excluded)}))
