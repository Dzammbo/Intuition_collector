import json,math
d=json.load(open("l1-market-raw.json"))
def f(v):
 try:
  x=float(v);return x if 1.001<=x<=100 else None
 except:return None
def walk(o,path="",out=None):
 out=[] if out is None else out
 if isinstance(o,dict):
  odds={}
  for k,v in o.items():
   q=f(v)
   if q is not None and (k.lower().endswith("_od") or k.lower() in {"home","draw","away","over","under","od","odds","price","1","2","x"}):odds[k]=q
  if odds:out.append({"path":path,"line":o.get("handicap") or o.get("ss") or o.get("name"),"timestamp":o.get("time") or o.get("updated_at") or o.get("add_time"),"odds":odds})
  for k,v in o.items():walk(v,f"{path}.{k}" if path else k,out)
 elif isinstance(o,list):
  for i,v in enumerate(o):walk(v,f"{path}[{i}]",out)
 return out
rows=[]
for r in d["records"]:
 ms=walk(r.get("odds") or {})
 rows.append({"event_id":r["event_id"],"sport_id":r["sport_id"],"league":r["league"],"home":r["home"],"away":r["away"],"time":r["time"],"markets":ms,"market_groups":len(ms),"observed_prices":sum(len(x["odds"]) for x in ms)})
out={"schema_version":1,"stage":"MARKET_NORMALIZER_V1","input":len(rows),"records":rows}
open("market-normalized-v1.json","w").write(json.dumps(out,ensure_ascii=False))
print(json.dumps({"input":len(rows),"with_markets":sum(bool(x["markets"]) for x in rows),"without_markets":sum(not x["markets"] for x in rows)}))
