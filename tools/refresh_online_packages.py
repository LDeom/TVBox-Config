#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh JSON online packages listed explicitly in rylinks.txt."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from source_pipeline import fetch_online_package, load_ry_links

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sources" / "collected" / "online_package_download_index.json"


def summarize(records, results):
    return {
        "source_file": "rylinks.txt",
        "input_count": len(records),
        "status_counts": dict(Counter(item.get("status", "未知") for item in results)),
        "results": results,
        "note": "仅下载显式清单中的 JSON 在线包；不执行远程代码，不导入或覆盖原始 TVBox 配置。"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    records = load_ry_links()
    if records:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(args.workers, 6))
        ) as pool:
            futures = [pool.submit(fetch_online_package, item) for item in records]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        order = {item["url"]: index for index, item in enumerate(records)}
        results.sort(key=lambda item: order.get(item.get("url"), 10**9))
    else:
        results = []

    report = summarize(records, results)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if args.debug:
        for item in results:
            print(f"[{item.get('status')}] {item.get('name')} {item.get('url')}")
    print(json.dumps({
        "input_count": report["input_count"],
        "status_counts": report["status_counts"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
