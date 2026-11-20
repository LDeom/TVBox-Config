#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh only the explicitly maintained API catalog and mirror health report."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from api_link_catalog import load_api_links
from api_pagination import fetch_paginated_api
from source_pipeline import (extract_catalog, fetch_api, load_local_documents, rank_mirror_candidates)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "output" / "reports"
COLLECTED = ROOT / "sources" / "collected"


def build_groups(records, results):
    by_url = {item.get("api"): item for item in results}
    grouped = {}
    for record in records:
        name = str(record.get("key") or record.get("name") or "").strip()
        if name:
            grouped.setdefault(name.casefold(), {"name": name, "urls": []})
            grouped[name.casefold()]["urls"].append(record["api"])
    recommendations = {}
    for key, group in grouped.items():
        urls = list(dict.fromkeys(group["urls"]))
        ranked = rank_mirror_candidates(urls, by_url)
        valid = [item["url"] for item in ranked if item.get("valid_payload")]
        recommendations[key] = {
            "name": group["name"],
            "preferred_url": valid[0] if valid else "",
            "fallback_urls": valid[1:],
            "candidates": ranked,
            "note": "按有效影视 JSON/XML 和响应耗时排序；只生成建议，不改写原始 TVBox 配置。"
        }
    return recommendations


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--paginate", action="store_true", help="对识别出分页元数据的有效 API 抓取完整分页")
    parser.add_argument("--max-pages", type=int, default=10)
    args = parser.parse_args()

    local_sites, _, _, _ = extract_catalog(load_local_documents())
    records_by_url = {
        str(item.get("api") or ""): item for item in local_sites
        if str(item.get("api") or "").startswith(("http://", "https://"))
    }
    for item in load_api_links(ROOT / "apilinks.txt"):
        records_by_url.setdefault(item["api"], item)
    records = list(records_by_url.values())
    if not records:
        raise SystemExit("本仓库配置和 apilinks.txt 中均没有有效 API 地址；未改动旧缓存。")

    results = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(args.workers, 8))
    ) as pool:
        futures = [pool.submit(fetch_api, record) for record in records]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            if args.debug:
                print(f"[{result.get('status')}] {result.get('name')} {result.get('api')}")

    # Keep deterministic output independent of thread completion order.
    order = {record["api"]: index for index, record in enumerate(records)}
    results.sort(key=lambda item: order.get(item.get("api"), 10**9))
    recommendations = build_groups(records, results)
    sites = []
    for group in recommendations.values():
        preferred = group.get("preferred_url")
        if preferred:
            sites.append({
                "key": group["name"], "name": group["name"], "type": 0,
                "api": preferred, "searchable": 1, "quickSearch": 1, "filterable": 1
            })
    write_json(COLLECTED / "api_mirror_config.json", {
        "name": "TVBox-Config API 镜像推荐片段",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sites": sites,
        "fallbacks": {key: value.get("fallback_urls", [])
                      for key, value in recommendations.items()}
    })
    pagination_results = []
    if args.paginate:
        valid_urls = {item.get("api") for item in results
                      if item.get("status") == "有效影视 JSON"}
        selected = [record for record in records if record.get("api") in valid_urls]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(args.workers, 6))
        ) as pool:
            futures = [pool.submit(fetch_paginated_api, record,
                                   max_pages=args.max_pages) for record in selected]
            pagination_results = [future.result() for future in concurrent.futures.as_completed(futures)]
        write_json(COLLECTED / "api_pages_index.json", {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "repository-owned local JSON configs + apilinks.txt",
            "enabled": True, "max_pages": args.max_pages,
            "results": pagination_results
        })
    counts = Counter(item.get("status", "未知") for item in results)
    generated_at = datetime.now(timezone.utc).isoformat()

    write_json(COLLECTED / "api_links_mirror_recommendations.json", {
        "generated_at": generated_at,
        "source": "repository-owned apilinks.txt",
        "groups": recommendations
    })
    write_json(REPORT_DIR / "api_links_report.json", {
        "generated_at": generated_at,
        "source": "repository-owned apilinks.txt",
        "endpoint_count": len(records),
        "mirror_group_count": len(recommendations),
        "pagination_enabled": args.paginate,
        "pagination_status_counts": dict(Counter(item.get("status", "未知") for item in pagination_results)),
        "status_counts": dict(counts),
        "results": results,
        "safety": "SSRF/unsafe redirects blocked; invalid or failed responses do not replace valid cached data."
    })
    print(json.dumps({
        "endpoint_count": len(records),
        "mirror_group_count": len(recommendations),
        "status_counts": dict(counts)
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
