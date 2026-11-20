#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate reference TVBox subscriptions and import only working VOD API endpoints."""
from __future__ import annotations
import argparse, concurrent.futures, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from compare_api_source_coverage import fetch_reference_config, extract_reference_groups
from fetch_util import fetch_bytes
from source_pipeline import valid_vod_payload, strip_json_comments, unwrap_response, canonical_url
from api_link_catalog import parse_api_links

OUT=ROOT/"sources/collected/api_candidate_validation.json"
MANIFEST=ROOT/"apilinks.txt"

def is_vod_endpoint(url):
    p=urlsplit(url).path.lower()
    return "/provide/vod" in p or p.endswith("/api.php") or "/inc/api" in p or p.endswith("/apijson.php")

def with_list_action(url):
    p=urlsplit(url); q=parse_qsl(p.query,keep_blank_values=True)
    if not any(k.lower()=="ac" for k,_ in q): q.append(("ac","list"))
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),""))

def extract_sites(config):
    out=[]; seen=set()
    for s in config.get("sites",[]) if isinstance(config.get("sites"),list) else []:
        if not isinstance(s,dict): continue
        api=str(s.get("api") or "").strip(); typ=str(s.get("type",""))
        if typ not in {"0","1"} or not api.startswith(("http://","https://")): continue
        k=canonical_url(api)
        if k in seen: continue
        seen.add(k); out.append({"name":str(s.get("name") or s.get("key") or "未命名站点"),"api":api,"type":typ})
    return out

def fetch_config(url,fetcher=fetch_bytes):
    r=fetcher(url,timeout=(4,7),max_bytes=4*1024*1024,retries=0,total_timeout=12)
    if not 200<=r.status_code<300: raise ValueError(f"HTTP {r.status_code}")
    obj=json.loads(strip_json_comments(unwrap_response(r.body).decode("utf-8-sig")))
    if not isinstance(obj,dict): raise ValueError("配置根节点不是对象")
    return obj

def probe(row,fetcher=fetch_bytes):
    try:
        r=fetcher(with_list_action(row["api"]),timeout=(4,7),max_bytes=2*1024*1024,retries=0,total_timeout=12)
        if not 200<=r.status_code<300: return {**row,"status":"HTTP失败","http":r.status_code}
        obj,status,detail=valid_vod_payload(r.body)
        return {**row,"status":status,"http":r.status_code,"detail":detail,"valid":obj is not None}
    except Exception as e: return {**row,"status":"请求失败","detail":str(e)[:240],"valid":False}

def run_validation(config,fetcher=fetch_bytes,workers=5):
    groups,_=extract_reference_groups(config); candidates=[]; seen=set()
    for g in groups:
        for u in g["urls"]:
            k=canonical_url(u)
            if k not in seen: seen.add(k); candidates.append({"group":g["name"],"url":u})
    jobs=[]; config_rows=[]; config_candidates=[]
    for candidate in candidates:
        if is_vod_endpoint(candidate["url"]):
            jobs.append({"group":candidate["group"],"name":candidate["group"],"api":candidate["url"],"type":"1"})
        else:
            config_candidates.append(candidate)
    def read_one(candidate):
        try:
            sites=extract_sites(fetch_config(candidate["url"],fetcher))
            return candidate, sites, None
        except Exception as exc:
            return candidate, [], str(exc)[:240]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
        for candidate, sites, error in ex.map(read_one,config_candidates):
            if error is None:
                config_rows.append({"group":candidate["group"],"url":candidate["url"],"status":"配置有效","site_count":len(sites)})
                jobs.extend({**site,"group":candidate["group"]} for site in sites)
            else:
                config_rows.append({"group":candidate["group"],"url":candidate["url"],"status":"配置读取失败","detail":error})
    unique=[]; seen=set()
    for j in jobs:
        k=canonical_url(j["api"])
        if k not in seen: seen.add(k); unique.append(j)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
        results=list(ex.map(lambda j:probe(j,fetcher),unique))
    return candidates,config_rows,results

def append_verified(text,results):
    existing={canonical_url(x["api"]) for x in parse_api_links(text)}
    lines=[text.rstrip()] if text.strip() else []
    added=0
    for r in sorted(results,key=lambda x:(x["group"].casefold(),x["name"].casefold(),x["api"])):
        if not r.get("valid"): continue
        k=canonical_url(r["api"])
        if k in existing: continue
        name=re.sub(r"[\\r\\n,|]+"," ",f'{r["group"]} - {r["name"]}').strip()
        lines.append(f'{name}, {r["api"]}'); existing.add(k); added+=1
    return "\n".join(lines).rstrip()+"\n",added

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--workers",type=int,default=5); p.add_argument("--reference-json",type=Path); a=p.parse_args()
    cfg=json.loads(a.reference_json.read_text(encoding="utf-8-sig")) if a.reference_json else fetch_reference_config()
    candidates,configs,endpoints=run_validation(cfg,workers=a.workers)
    old=MANIFEST.read_text(encoding="utf-8-sig") if MANIFEST.exists() else ""
    new,added=append_verified(old,endpoints)
    if added: MANIFEST.write_text(new,encoding="utf-8")
    report={"generated_at":datetime.now(timezone.utc).isoformat(),"reference_repository":"lubin776/tvbox-api-backup",
      "candidate_count":len(candidates),"valid_config_count":sum(x["status"]=="配置有效" for x in configs),
      "failed_config_count":sum(x["status"]!="配置有效" for x in configs),"tested_vod_api_count":len(endpoints),
      "valid_vod_api_count":sum(bool(x.get("valid")) for x in endpoints),"new_manifest_entries":added,
      "configs":configs,"endpoints":endpoints,
      "safety":"只追加真实请求返回有效影视 JSON/XML 列表的 API；配置仅作数据解析，不执行任何代码；不复制参考配置。"}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("candidate_count","valid_config_count","failed_config_count","tested_vod_api_count","valid_vod_api_count","new_manifest_entries")},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
