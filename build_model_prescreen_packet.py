#!/usr/bin/env python3
"""Build a lossless assessment packet for every eligible tennis singles event."""
import json,sys

def event_id(row): return str(row.get("event_id") or row.get("id") or "")
def start_key(row):
 try:return int(row.get("time")),event_id(row)
 except (TypeError,ValueError):raise SystemExit(f"invalid start time for event {event_id(row)}")

def main():
 odds=json.load(open(sys.argv[1],encoding="utf-8"))
 view=json.load(open(sys.argv[2],encoding="utf-8"))
 if odds.get("errors") or view.get("errors"):raise SystemExit("source enrichment contains errors")
 odds_rows=odds.get("records") or [];view_rows=view.get("records") or []
 odds_ids=[event_id(x) for x in odds_rows];view_ids=[event_id(x) for x in view_rows]
 if not odds_ids or odds_ids!=view_ids:
  if set(odds_ids)!=set(view_ids):raise SystemExit("L1 and Event View identities differ")
 if len(odds_ids)!=len(set(odds_ids)) or len(view_ids)!=len(set(view_ids)):
  raise SystemExit("duplicate event identity")
 expected=int(odds.get("input_singles") or 0)
 if expected!=len(odds_rows) or expected!=len(view_rows):raise SystemExit("singles accounting mismatch")
 odds_map={event_id(x):x for x in odds_rows};view_map={event_id(x):x for x in view_rows}
 cards=[]
 for ordinal,row in enumerate(sorted(odds_rows,key=start_key),1):
  eid=event_id(row);v=view_map[eid]
  cards.append({"ordinal":ordinal,"event_id":eid,"scope_status":"TENNIS_SINGLES",
   "sport_id":13,"league":row.get("league"),"home":row.get("home"),"away":row.get("away"),
   "start_time":row.get("time"),"raw_odds":row.get("odds") or {},"event_view":v,
   "player_refs":[str((row.get("home") or {}).get("id") or ""),str((row.get("away") or {}).get("id") or "")]})
 output={"schema_version":4,"stage":"TENNIS_SINGLES_RESEARCH_PACKET",
  "handoff_status":"READY_FOR_ASSESSMENT","substantive_prescreen_required":False,
  "tiering_used":False,"input":len(cards),"ordering":"START_TIME_ASC_EVENT_ID_ASC",
  "rule":"Every technically eligible real tennis singles event advances to player-dossier research.",
  "source_accounting":{"eligible_singles":len(cards),"l1_records":len(odds_rows),
   "event_view_records":len(view_rows),"technical_errors":0},"cards":cards}
 open("model-prescreen-packet.json","w",encoding="utf-8").write(json.dumps(output,ensure_ascii=False))
 print(json.dumps({"cards":len(cards),"scope":"TENNIS_SINGLES","ordering":output["ordering"]}))

if __name__=="__main__":main()
