import json,sys
od=json.load(open(sys.argv[1])); ev=json.load(open(sys.argv[2]))
evmap={str(x.get("id") or x.get("event_id")):x for x in ev.get("records",[])}
cards=[]
for i,r in enumerate(od.get("records",[]),1):
 eid=str(r.get("event_id"))
 raw=r.get("odds") or {}
 cards.append({"ordinal":i,"event_id":eid,"sport_id":r.get("sport_id"),"league":r.get("league"),"home":r.get("home"),"away":r.get("away"),"start_time":r.get("time"),"raw_odds":raw,"event_view":evmap.get(eid,{})})
out={"schema_version":1,"stage":"MODEL_PRESCREEN_PACKET","input":len(cards),"rule":"Lossless compact handoff from saved L1 odds + Event View. No new provider calls.","cards":cards}
open("model-prescreen-packet.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"cards":len(cards)}))
