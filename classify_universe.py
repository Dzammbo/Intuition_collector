import json,glob
u=json.load(open("universe.json"))
tiers={}
for p in glob.glob("config/league_allowset_v1/*.json"):
 try:
  d=json.load(open(p))
  rows=d.get("allowed_leagues",[]) + d.get("leagues",[])
  for x in rows:
   tier=x.get("tier")
   if tier in ("CORE","SECONDARY","EXCLUDE"):
    tiers[(int(x["sport_id"]),int(x["league_id"]))]=(tier,x.get("tier_reason"))
 except Exception:
  pass
b={"CORE":[],"SECONDARY":[],"EXCLUDE":[],"UNCLASSIFIED_LEAGUE":[]}
for e in u["window_events"]:
 sid=int(e.get("sport_id") or 0); league=e.get("league") or {}
 try: lid=int(league.get("id"))
 except: lid=0
 rec=tiers.get((sid,lid))
 tier=rec[0] if rec else "UNCLASSIFIED_LEAGUE"
 b[tier].append(e)
out={"schema_version":1,"source_captured_at":u["captured_at"],"window_event_count":len(u["window_events"]),"counts":{k:len(v) for k,v in b.items()},"events":b}
open("classified-universe.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps(out["counts"]))
