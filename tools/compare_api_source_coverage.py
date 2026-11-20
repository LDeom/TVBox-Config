#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit reference API source coverage without importing or activating endpoints.

The reference API list is parsed for counts and name-level coverage only.
No reference endpoint is requested and apilinks.txt is never modified.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from api_link_catalog import parse_api_links
from fetch_util import FetchError, fetch_bytes
from source_pipeline import canonical_url

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_URL = (
    "https://raw.githubusercontent.com/lubin776/tvbox-api-backup/main/api_list.json"
)
LOCAL_API_INDEX = ROOT / "sources" / "collected" / "api_index.json"
LOCAL_MANIFEST = ROOT / "apilinks.txt"
OUTPUT = ROOT / "sources" / "collected" / "api_source_coverage.json"


def extract_reference_groups(config: dict) -> tuple[list[dict], int]:
    """Read API_LIST and API_MIRRORS into named URL groups without executing code."""
    groups = OrderedDict()
    api_list = config.get("API_LIST", [])
    entry_count = 0
    if isinstance(api_list, list):
        for item in api_list:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                name, urls = item[0], item[1:]
            elif isinstance(item, dict):
                name = item.get("name") or item.get("key")
                urls = [item.get("api") or item.get("url")]
            else:
                continue
            name = str(name or "").strip()
            if not name:
                continue
            entry_count += 1
            group = groups.setdefault(name.casefold(), {"name": name, "urls": []})
            for url in urls:
                value = str(url or "").strip()
                if value.startswith(("http://", "https://")) and value not in group["urls"]:
                    group["urls"].append(value)

    mirror_groups = config.get("API_MIRRORS", {})
    mirror_group_count = 0
    if isinstance(mirror_groups, dict):
        for name, urls in mirror_groups.items():
            name = str(name or "").strip()
            if not name:
                continue
            mirror_group_count += 1
            if isinstance(urls, str):
                urls = [urls]
            if not isinstance(urls, list):
                continue
            group = groups.setdefault(name.casefold(), {"name": name, "urls": []})
            for url in urls:
                value = str(url or "").strip()
                if value.startswith(("http://", "https://")) and value not in group["urls"]:
                    group["urls"].append(value)

    return list(groups.values()), mirror_group_count


def _unique_urls(groups: list[dict]) -> set[str]:
    return {
        canonical_url(url)
        for group in groups for url in group.get("urls", [])
        if url.startswith(("http://", "https://"))
    }


def build_coverage_report(reference_config: dict, local_api_index: dict,
                          manifest_text: str) -> dict:
    reference_groups, mirror_group_count = extract_reference_groups(reference_config)
    local_index_urls = {
        canonical_url(str(row.get("api") or ""))
        for row in local_api_index.get("results", [])
        if isinstance(row, dict) and str(row.get("api") or "").startswith(("http://", "https://"))
    }
    manifest_records = parse_api_links(manifest_text)
    manifest_urls = {
        canonical_url(row["api"]) for row in manifest_records
        if row.get("api")
    }
    local_urls = local_index_urls | manifest_urls
    reference_urls = _unique_urls(reference_groups)
    covered_urls = reference_urls & local_urls

    group_rows = []
    for group in reference_groups:
        urls = {canonical_url(url) for url in group["urls"]}
        covered = urls & local_urls
        missing = urls - local_urls
        if not urls:
            status = "无有效 URL"
        elif not missing:
            status = "全部已覆盖"
        elif covered:
            status = "部分已覆盖"
        else:
            status = "尚未覆盖"
        group_rows.append({
            "name": group["name"],
            "reference_url_count": len(urls),
            "covered_url_count": len(covered),
            "uncovered_url_count": len(missing),
            "coverage_status": status,
            "imported": False,
        })

    group_rows.sort(key=lambda row: (
        row["coverage_status"] == "全部已覆盖",
        -row["uncovered_url_count"],
        row["name"].casefold(),
    ))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_repository": "lubin776/tvbox-api-backup",
        "reference_file": "api_list.json",
        "comparison_scope": "metadata_only_no_endpoint_requests",
        "reference_api_list_entry_count": sum(
            1 for item in reference_config.get("API_LIST", [])
            if isinstance(item, (list, tuple, dict))
        ),
        "reference_group_count": len(reference_groups),
        "reference_mirror_group_count": mirror_group_count,
        "reference_unique_url_count": len(reference_urls),
        "local_api_index_unique_url_count": len(local_index_urls),
        "local_explicit_manifest_unique_url_count": len(manifest_urls),
        "covered_reference_url_count": len(covered_urls),
        "uncovered_reference_url_count": len(reference_urls - local_urls),
        "candidate_group_count": sum(
            1 for row in group_rows if row["uncovered_url_count"] > 0
        ),
        "groups": group_rows,
        "safety": (
            "仅读取参考 api_list.json 的清单内容并与本地索引比较；"
            "不请求参考 API 地址、不向 apilinks.txt 写入任何来源、不覆盖原始配置。"
        ),
        "next_step": "候选来源须逐项检查可用性和许可，并经用户明确批准后才能加入 apilinks.txt。",
    }


def fetch_reference_config(fetcher=fetch_bytes) -> dict:
    response = fetcher(
        REFERENCE_URL, timeout=(5, 10), max_bytes=2 * 1024 * 1024,
        retries=2, total_timeout=15,
        headers={"Accept": "application/json, text/plain, */*"},
    )
    if not 200 <= response.status_code < 300:
        raise FetchError(f"参考 API 清单下载失败：HTTP {response.status_code}")
    try:
        config = json.loads(response.body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"参考 API 清单 JSON 无效：{exc}") from exc
    if not isinstance(config, dict):
        raise FetchError("参考 API 清单不是 JSON 对象")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--reference-json", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    index_path = root / "sources" / "collected" / "api_index.json"
    manifest_path = root / "apilinks.txt"
    output_path = root / "sources" / "collected" / "api_source_coverage.json"
    if not index_path.is_file():
        print(f"本地 API 索引不存在，保留已有报告：{index_path}")
        return 0
    local_index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    manifest_text = manifest_path.read_text(encoding="utf-8-sig") if manifest_path.is_file() else ""
    try:
        if args.reference_json:
            reference_config = json.loads(args.reference_json.read_text(encoding="utf-8-sig"))
        else:
            reference_config = fetch_reference_config()
    except (FetchError, OSError, ValueError) as exc:
        print(f"参考 API 清单暂不可用，保留已有报告：{exc}")
        return 0
    report = build_coverage_report(reference_config, local_index, manifest_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reference_unique_url_count": report["reference_unique_url_count"],
        "local_api_index_unique_url_count": report["local_api_index_unique_url_count"],
        "local_explicit_manifest_unique_url_count": report["local_explicit_manifest_unique_url_count"],
        "covered_reference_url_count": report["covered_reference_url_count"],
        "uncovered_reference_url_count": report["uncovered_reference_url_count"],
        "candidate_group_count": report["candidate_group_count"],
        "output": "sources/collected/api_source_coverage.json",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
