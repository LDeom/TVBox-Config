#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox 点播 API 巡检。仅验证 HTTP 响应与影视数据结构，不代表真实可播放。"""
import argparse, csv, json, time, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from fetch_util import FetchError, fetch_bytes

HEADERS = {"User-Agent": "okhttp/3.12.13", "Accept": "application/json, application/xml, text/xml, */*"}
TIMEOUT = (5, 10)
MAX_BYTES = 2 * 1024 * 1024
LIST_KEYS = {"list", "data", "vod", "videos", "items", "result"}
VOD_KEYS = {"vod_id", "vod_name", "vod_pic", "vod_play_url", "id", "title", "name"}

def load_records(path):
    raw = open(path, encoding="utf-8-sig").read()
    records, seen = [], set()
    try:
        obj = json.loads(raw)
        def walk(x):
            if isinstance(x, dict):
                api = x.get("api")
                if isinstance(api, str) and api.startswith(("http://", "https://")):
                    name = str(x.get("name") or x.get("key") or "")
                    if api not in seen:
                        seen.add(api); records.append({"line": "", "key": name, "name": name, "api": api})
                for v in x.values(): walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
        walk(obj)
        if records: return records
    except json.JSONDecodeError:
        pass
    for n, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = line.split("|")
        api = next((p.split(":", 1)[1].strip() for p in parts if p.strip().lower().startswith("api:")), "")
        if not api:
            api = next((p.strip() for p in parts if p.strip().startswith(("http://", "https://"))), "")
        if api and api not in seen:
            seen.add(api); records.append({"line": n, "key": parts[0].strip(), "name": parts[1].strip() if len(parts)>1 else "", "api": api})
    return records

def probe_url(url):
    p = urlsplit(url); q = parse_qsl(p.query, keep_blank_values=True)
    if not any(k.lower()=="ac" for k,_ in q): q.append(("ac","list"))
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),""))

def inspect(body):
    s = body.decode("utf-8-sig", "replace").strip()
    if not s: return "空响应", "响应体为空"
    try:
        obj = json.loads(s); lists=0; fields=set()
        def walk(x, depth=0):
            nonlocal lists
            if depth>8: return
            if isinstance(x,dict):
                for k,v in x.items():
                    if str(k).lower() in VOD_KEYS: fields.add(str(k).lower())
                    if str(k).lower() in LIST_KEYS and isinstance(v,list):
                        lists += len(v)
                        for y in v[:8]: walk(y,depth+1)
                    elif isinstance(v,(dict,list)): walk(v,depth+1)
            elif isinstance(x,list):
                for y in x[:20]: walk(y,depth+1)
        walk(obj)
        if lists and fields: return "有效影视数据结构", f"列表项目数≥{lists}；字段：{','.join(sorted(fields))}"
        if lists: return "有列表但影视字段不明确", f"列表项目数≥{lists}"
        if fields: return "有影视字段但列表为空/缺失", ",".join(sorted(fields))
        return "合法 JSON 但无影视特征", "未发现影视列表字段"
    except Exception: pass
    try:
        root=ET.fromstring(s); tags={e.tag.lower().split("}")[-1] for e in root.iter()}
        count=sum(1 for e in root.iter() if e.tag.lower().split("}")[-1] in {"video","vod","item"})
        fields=sorted(tags & VOD_KEYS)
        if count and fields: return "有效影视 XML 结构", f"项目节点数：{count}；字段：{','.join(fields)}"
        if count: return "XML 有项目节点但字段不明确", f"项目节点数：{count}"
        return "合法 XML 但无影视特征", root.tag
    except Exception: return "格式异常/非 JSON/XML", s[:160].replace("\\n"," ")

def check(item):
    start = time.monotonic()
    try:
        result = fetch_bytes(
            probe_url(item["api"]), timeout=TIMEOUT, max_bytes=MAX_BYTES,
            retries=2, headers=HEADERS,
        )
        status, detail = (
            ("HTTP 失败", f"HTTP {result.status_code}")
            if not 200 <= result.status_code < 300 else inspect(result.body)
        )
        return {
            **item, "status": status, "http": result.status_code,
            "seconds": round(time.monotonic() - start, 2),
            "final_url": result.url, "detail": detail,
        }
    except FetchError as exc:
        message = str(exc)
        status = "超时" if "Timeout" in message else "请求失败/安全拦截"
        return {
            **item, "status": status, "http": "",
            "seconds": round(time.monotonic() - start, 2),
            "final_url": "", "detail": message,
        }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True,help="cjlist.txt 或 TVBox JSON 配置文件")
    p.add_argument("--csv",default="api_check_report.csv")
    p.add_argument("--json",default="api_check_report.json")
    p.add_argument("--workers",type=int,default=6)
    a=p.parse_args(); items=load_records(a.input)
    print(f"发现 {len(items)} 个唯一 API")
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,min(a.workers,12))) as pool:
        fs=[pool.submit(check,x) for x in items]
        for i,f in enumerate(as_completed(fs),1):
            r=f.result(); results.append(r)
            print(f"[{i}/{len(items)}] {r['status']} | HTTP {r['http']} | {r['api']}")
    results.sort(key=lambda x: str(x["line"]))
    fields=["line","key","name","api","status","http","seconds","final_url","detail"]
    with open(a.csv,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(results)
    with open(a.json,"w",encoding="utf-8") as f: json.dump(results,f,ensure_ascii=False,indent=2)
    from collections import Counter
    print("汇总：",dict(Counter(x["status"] for x in results)))
    print("提示：结构检测通过不代表播放地址实际可播放。")

if __name__=="__main__": main()
