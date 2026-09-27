import json,os,time,urllib.parse,urllib.request
# Input is an immutable Technical Eligibility snapshot supplied from the canonical run.
# This stage must never recollect schedule/universe.
inp=os.environ.get("ELIGIBLE_FILE","technically-eligible.json")
d=json.load(open(inp))
events=d["events"]
out=[]
for e in events:
    signals=[]
    # Provider-native context only; no hand-authored score/weight and no direction lock.
    comp=e.get("league") or {}
    if comp.get("id") or comp.get("name"):
        signals.append({"family":"MATCHUP_CONTEXT","provenance":"BETSAPI_EVENT_METADATA"})
    # Retain events for downstream research only when at least one auditable non-trivial signal exists.
    # Additional price/model/line signals are appended by dedicated enrichers, not fabricated here.
    if signals:
        out.append({"event_id":str(e.get("id")),"sport_id":e.get("sport_id"),"time":e.get("time"),
                    "home":e.get("home"),"away":e.get("away"),"league":comp,"signals":signals,
                    "direction_locked":False})
result={"schema_version":1,"stage":"BROAD_SIGNAL_SCAN","source_run_id":d.get("source_run_id"),
        "input_events":len(events),"broad_candidates":len(out),"candidates":out,
        "rule":"No scores or weights; candidate requires auditable non-trivial signal provenance."}
open("broad-candidates.json","w").write(json.dumps(result,ensure_ascii=False))
print(json.dumps({"input":len(events),"broad_candidates":len(out)}))
