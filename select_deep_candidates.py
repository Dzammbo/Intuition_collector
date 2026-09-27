import json,hashlib,math
p=json.load(open("prescreen-v2.json"))
# Reproducible diversified selection. No intuition, no random state.
# Rank within sport by: usable market data first, normal market quality before high-overround warnings,
# richer coverage, then stable event_id tie-break.
targets={1:65,13:38,16:15,17:27,18:35} # 180 max; shortfalls are not backfilled with another sport.
by={}
for r in p["records"]:by.setdefault(int(r["sport_id"]),[]).append(r)
def key(r):
 ts={x["type"] for x in r["triggers"]}
 usable=0 if r["status"]=="INSUFFICIENT_MARKET_DATA" else 1
 normal=0 if "HIGH_OVERROUND" in ts else 1
 rich=1 if "RICH_MARKET_SNAPSHOT" in ts else 0
 return (-usable,-normal,-rich,-r["market_groups"],-r["observed_prices"],str(r["event_id"]))
sel=[];summary={}
for sid,n in targets.items():
 xs=sorted(by.get(sid,[]),key=key);take=xs[:min(n,len(xs))]
 for rank,r in enumerate(take,1):
  sel.append({"sport_id":sid,"rank_within_sport":rank,"event_id":r["event_id"],"league":r["league"],"home":r["home"],"away":r["away"],"time":r["time"],"market_status":r["status"],"triggers":r["triggers"],"market_groups":r["market_groups"],"observed_prices":r["observed_prices"],"selection_reason":"REPRODUCIBLE_DIVERSIFIED_PRESCREEN"})
 summary[str(sid)]={"available":len(xs),"selected":len(take),"target":n}
out={"schema_version":1,"stage":"DEEP_RESEARCH_CANDIDATE_SELECTION","method":"deterministic diversified ranking from saved CORE market snapshot; no intuition/randomness","target_total":sum(targets.values()),"selected_total":len(sel),"by_sport":summary,"candidates":sel}
open("deep-research-candidates.json","w").write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({"selected_total":len(sel),"by_sport":summary}))
