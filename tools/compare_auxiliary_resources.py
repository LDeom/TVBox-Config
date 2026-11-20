#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare reference cy/ resource metadata with this repo's local inventory.

Only the GitHub directory listing is fetched. Reference JSON file contents are
never downloaded or imported; this tool creates a metadata-only gap report.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fetch_util import FetchError, fetch_bytes

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_API = (
    "https://api.github.com/repos/lubin776/tvbox-api-backup/"
    "contents/cy?ref=main"
)
CATALOG_PATH = ROOT / "sources" / "collected" / "resource_catalog.json"
OUTPUT_PATH = ROOT / "sources" / "collected" / "auxiliary_resource_comparison.json"

RESOURCE_TYPES = {
    "书源.json": ("book", ("book",)),
    "弹幕.json": ("danmaku", ("danmaku",)),
    "本站APP.json": ("app_catalog", ("json_config_or_resource", "javascript_plugin")),
    "模板.json": ("template", ("template",)),
    "漫画源.json": ("comic", ("comic",)),
    "社群推荐.json": ("community_recommendation", ("json_config_or_resource",)),
    "站点1.json": ("site_collection", ("vod", "json_config_or_resource")),
    "站点2.json": ("site_collection", ("vod", "json_config_or_resource")),
    "站点3.json": ("site_collection", ("vod", "json_config_or_resource")),
    "站点域名分组.json": ("domain_group", ("json_config_or_resource",)),
    "站长推荐.json": ("owner_recommendation", ("json_config_or_resource",)),
    "自定义点播混排.json": ("mixed_vod", ("vod", "json_config_or_resource")),
    "音源.json": ("audio", ("audio",)),
}


def fetch_reference_listing(fetcher=fetch_bytes) -> list[dict]:
    result = fetcher(
        REFERENCE_API, timeout=(5, 15), max_bytes=1024 * 1024,
        retries=2, headers={"Accept": "application/vnd.github+json"},
    )
    if not 200 <= result.status_code < 300:
        raise FetchError(f"GitHub cy 目录读取失败：HTTP {result.status_code}")
    try:
        payload = json.loads(result.body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"GitHub cy 目录响应不是有效 JSON：{exc}") from exc
    if not isinstance(payload, list):
        raise FetchError("GitHub cy 目录响应结构不是文件列表")
    rows = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = str(item.get("name") or "")
        if not name.lower().endswith(".json"):
            continue
        if not str(item.get("path") or "").startswith("cy/"):
            continue
        if name not in RESOURCE_TYPES:
            category = "unclassified"
            local_categories = ()
        else:
            category, local_categories = RESOURCE_TYPES[name]
        rows.append({
            "name": name,
            "path": item.get("path", ""),
            "sha": item.get("sha", ""),
            "size_bytes": int(item.get("size") or 0),
            "html_url": item.get("html_url", ""),
            "category": category,
            "local_candidate_categories": list(local_categories),
        })
    return sorted(rows, key=lambda item: item["name"])


def compare_resources(reference_rows: list[dict], local_catalog: dict) -> dict:
    resources = local_catalog.get("resources", [])
    category_counts = Counter(item.get("category", "other") for item in resources)
    results = []
    for source in reference_rows:
        categories = source.get("local_candidate_categories", [])
        candidate_count = sum(category_counts.get(category, 0) for category in categories)
        candidates = [
            item for item in resources
            if item.get("category") in categories
        ]
        results.append({
            **source,
            "local_candidate_count": candidate_count,
            "local_candidate_paths": [item.get("path", "") for item in candidates[:12]],
            "coverage_status": (
                "存在同类候选，尚未验证功能等价"
                if candidate_count else "本地未发现同类候选"
            ),
            "imported": False,
            "content_downloaded": False,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_repository": "lubin776/tvbox-api-backup",
        "source_directory": "cy/",
        "comparison_scope": "metadata_only",
        "reference_file_count": len(results),
        "category_counts": dict(sorted(Counter(
            item["category"] for item in results
        ).items())),
        "local_category_counts": dict(sorted(category_counts.items())),
        "resources": results,
        "safety": (
            "只读取 GitHub cy/ 目录清单元数据；不下载或导入参考仓库 JSON 内容，"
            "不执行任何远程代码，不覆盖本仓库原始配置。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    root = args.root.resolve()
    catalog_path = args.catalog if args.catalog.is_absolute() else root / args.catalog
    output_path = args.output if args.output.is_absolute() else root / args.output
    if not catalog_path.is_file():
        raise SystemExit(f"本地资源索引不存在：{catalog_path}")
    local_catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    try:
        reference_rows = fetch_reference_listing()
    except FetchError as exc:
        print(f"参考仓库元数据暂不可用，保留现有报告：{exc}")
        return 0
    report = compare_resources(reference_rows, local_catalog)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "reference_file_count": report["reference_file_count"],
        "category_counts": report["category_counts"],
        "output": output_path.as_posix(),
        "scope": report["comparison_scope"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
