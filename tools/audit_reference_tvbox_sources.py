#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch reference TVBox subscription configs, test their real VOD APIs, and add only verified APIs."""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from api_link_catalog import parse_api_links
from compare_api_source_coverage import extract_reference_groups, fetch_reference_config
from fetch_util import FetchError, fetch_bytes
from source_pipeline import (
    ROOT, canonical_url, request_api_url, strip_json_comments,
    unwrap_response, valid_vod_payload,
)

OUTPUT = ROOT / "sources" / "collected" / "reference_tvbox_source_audit.json"
MANIFEST = ROOT / "apilinks.txt"
MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_ENDPOINT_BYTES = 2 * 1024 * 1024
CONFIG_TIMEOUT = 12
ENDPOINT_TIMEOUT = 10
CONFIG_WORKERS = 5
ENDPOINT_WORKERS = 5
MAX_ENDPOINTS = 1000


def parse_tvbox_config(body: bytes):
    """Decode a TVBox config without executing scripts or accepting arbitrary text."""
    try:
        decoded = unwrap_response(body)
        text = decoded.decode("utf-8-sig").strip()
        if not text:
            return None, "空响应"
        candidates = [text]
        match = re.match(r"^[\w.$]+\s*\((.*)\)\s*;?$", text, re.S)
        if match:
            candidates.append(match.group(1).strip())
        for candidate in candidates:
            try:
                obj = json.loads(strip_json_comments(candidate))
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get("sites"), list):
                return obj, "有效 TVBox 配置"
        return None, "不是包含 sites 数组的 TVBox 配置"
    except Exception as exc:
        return None, f"配置解码失败：{type(exc).__name__}: {exc}"


def extract_vod_candidates(config_name: str, config: dict, source_url: str):
    """Extract only absolute HTTP(S) sites APIs of TVBox type 0/1."""
    candidates = []
    sites = config.get("sites", [])
    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            continue
        site_type = site.get("type")
        if str(site_type) not in {"0", "1"}:
            continue
        api = str(site.get("api") or "").strip()
        if not api.startswith(("http://", "https://")):
            continue
        parsed = urlsplit(api)
        if not parsed.hostname or parsed.username or parsed.password:
            continue
        name = str(site.get("name") or site.get("key") or f"site-{index + 1}")
        key = str(site.get("key") or name)
        record = {
            "key": key,
            "name": name,
            "type": int(site_type),
            "api": api,
        }
        test_url = request_api_url(record)
        candidates.append({
            "config_name": config_name,
            "config_url": source_url,
            "site_name": name,
            "site_key": key,
            "site_type": int(site_type),
            "api": api,
            "test_url": test_url,
        })
    return candidates


def fetch_one_config(item):
    name, url = item
    try:
        response = fetch_bytes(
            url, timeout=(4, 8), max_bytes=MAX_CONFIG_BYTES, retries=0,
            total_timeout=CONFIG_TIMEOUT,
            headers={"Accept": "application/json, text/plain, */*"},
        )
        if not 200 <= response.status_code < 300:
            return {
                "name": name, "url": url, "status": "HTTP失败",
                "http": response.status_code, "detail": "",
                "config": None, "candidates": [],
            }
        config, status = parse_tvbox_config(response.body)
        if config is None:
            return {
                "name": name, "url": url, "status": status,
                "http": response.status_code, "detail": "",
                "config": None, "candidates": [],
            }
        candidates = extract_vod_candidates(name, config, url)
        return {
            "name": name, "url": url, "status": status,
            "http": response.status_code,
            "detail": f"sites={len(config.get('sites', []))}; 可测试 type 0/1 API={len(candidates)}",
            "config": None,
            "candidates": candidates,
        }
    except (FetchError, OSError, ValueError) as exc:
        return {
            "name": name, "url": url, "status": "请求失败",
            "http": "", "detail": str(exc)[:300],
            "config": None, "candidates": [],
        }


def deduplicate_candidates(rows):
    merged = OrderedDict()
    for row in rows:
        url = row["test_url"]
        key = canonical_url(url)
        if key not in merged:
            merged[key] = dict(row)
            merged[key]["sources"] = [{
                "config_name": row["config_name"],
                "config_url": row["config_url"],
                "site_name": row["site_name"],
                "site_key": row["site_key"],
                "site_type": row["site_type"],
            }]
        else:
            source = {
                "config_name": row["config_name"],
                "config_url": row["config_url"],
                "site_name": row["site_name"],
                "site_key": row["site_key"],
                "site_type": row["site_type"],
            }
            if source not in merged[key]["sources"]:
                merged[key]["sources"].append(source)
    return list(merged.values())


def test_one_endpoint(row):
    started = datetime.now(timezone.utc)
    try:
        response = fetch_bytes(
            row["test_url"], timeout=(4, 7), max_bytes=MAX_ENDPOINT_BYTES,
            retries=0, total_timeout=ENDPOINT_TIMEOUT,
            headers={"Accept": "application/json, application/xml, text/xml, */*"},
        )
        if not 200 <= response.status_code < 300:
            return {
                **row, "status": "HTTP失败", "http": response.status_code,
                "detail": "", "valid": False,
            }
        _, status, detail = valid_vod_payload(response.body)
        return {
            **row, "status": status, "http": response.status_code,
            "detail": detail[:240], "valid": status in {"有效影视 JSON", "有效影视 XML"},
        }
    except (FetchError, OSError, ValueError) as exc:
        return {
            **row, "status": "请求失败", "http": "",
            "detail": str(exc)[:300], "valid": False,
        }


def make_manifest_name(row):
    source = row["sources"][0]
    base = f"{source['config_name']} - {source['site_name']}"
    base = re.sub(r"[\r\n,|]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip(" .-_")
    base = base[:64] or "Verified API"
    suffix = hashlib.sha256(row["test_url"].encode("utf-8")).hexdigest()[:8]
    return f"{base} [{suffix}]"


def api_identity(url: str) -> str:
    """Compare API endpoints while ignoring the TVBox list-query marker ac=list."""
    parsed = urlsplit(canonical_url(url))
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() != "ac"]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def append_verified_to_manifest(existing_text: str, passed_rows: list[dict],
                                existing_api_urls=()):
    """Preserve existing lines and skip URLs already in apilinks or local API index."""
    existing = parse_api_links(existing_text)
    seen = {api_identity(item["api"]) for item in existing}
    seen.update(api_identity(url) for url in existing_api_urls if url)
    additions = []
    for row in passed_rows:
        url = row["test_url"]
        key = api_identity(url)
        if key in seen:
            continue
        seen.add(key)
        additions.append(f"{make_manifest_name(row)}, {url}")
    if not additions:
        return existing_text, []
    base = existing_text.rstrip()
    if base:
        base += "\n\n"
    base += "# 以下来源由参考 TVBox 配置逐站提取，并通过影视 JSON/XML 数据验证；每日巡检会覆盖本地缓存。\n"
    base += "\n".join(additions) + "\n"
    return base, additions


def run_audit(reference_config=None, root: Path = ROOT, fetcher=fetch_bytes):
    """Run the full candidate-config and extracted-API audit."""
    if reference_config is None:
        reference_config = fetch_reference_config(fetcher=fetcher)
    groups, mirror_count = extract_reference_groups(reference_config)
    source_rows = []
    seen_configs = set()
    for group in groups:
        for url in group["urls"]:
            key = canonical_url(url)
            if key not in seen_configs:
                seen_configs.add(key)
                source_rows.append((group["name"], url))

    config_results = []
    with ThreadPoolExecutor(max_workers=CONFIG_WORKERS) as pool:
        futures = [pool.submit(fetch_one_config, item) for item in source_rows]
        for future in as_completed(futures):
            config_results.append(future.result())
    config_results.sort(key=lambda row: (row["name"].casefold(), row["url"]))

    all_candidates = [
        candidate for result in config_results for candidate in result["candidates"]
    ]
    unique_candidates = deduplicate_candidates(all_candidates)
    truncated = len(unique_candidates) > MAX_ENDPOINTS
    to_test = unique_candidates[:MAX_ENDPOINTS]

    endpoint_results = []
    with ThreadPoolExecutor(max_workers=ENDPOINT_WORKERS) as pool:
        futures = [pool.submit(test_one_endpoint, row) for row in to_test]
        for future in as_completed(futures):
            endpoint_results.append(future.result())
    endpoint_results.sort(key=lambda row: (not row["valid"], row["config_name"].casefold(), row["test_url"]))

    passed = [row for row in endpoint_results if row["valid"]]
    manifest_path = root / "apilinks.txt"
    old_text = manifest_path.read_text(encoding="utf-8-sig") if manifest_path.is_file() else ""
    local_index_path = root / "sources" / "collected" / "api_index.json"
    try:
        local_index = json.loads(local_index_path.read_text(encoding="utf-8-sig"))
        local_api_urls = [
            row.get("api") for row in local_index.get("results", [])
            if isinstance(row, dict) and row.get("api")
        ]
    except (OSError, ValueError, TypeError):
        local_api_urls = []
    new_text, additions = append_verified_to_manifest(
        old_text, passed, existing_api_urls=local_api_urls
    )
    if additions:
        manifest_path.write_text(new_text, encoding="utf-8")

    old_manifest_identities = {
        api_identity(row["api"]) for row in parse_api_links(old_text)
    }
    local_index_identities = {api_identity(url) for url in local_api_urls}
    added_identities = {
        api_identity(match.group(0))
        for line in additions
        if (match := re.search(r"https?://[^\s,;|]+", line))
    }

    counts = {}
    for row in config_results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    endpoint_counts = {}
    for row in endpoint_results:
        endpoint_counts[row["status"]] = endpoint_counts.get(row["status"], 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_repository": "lubin776/tvbox-api-backup",
        "reference_config_entry_count": sum(
            1 for row in reference_config.get("API_LIST", [])
            if isinstance(row, (list, tuple, dict))
        ),
        "reference_mirror_group_count": mirror_count,
        "unique_reference_config_url_count": len(source_rows),
        "config_fetch_status_counts": counts,
        "valid_tvbox_config_count": sum(1 for row in config_results if row["status"] == "有效 TVBox 配置"),
        "extracted_type_0_1_site_count": len(all_candidates),
        "unique_extracted_api_count": len(unique_candidates),
        "tested_api_count": len(endpoint_results),
        "api_test_status_counts": endpoint_counts,
        "verified_api_count": len(passed),
        "local_api_index_unique_url_count": len(local_index_identities),
        "already_in_local_api_index_count": sum(
            1 for row in passed if api_identity(row["test_url"]) in local_index_identities
        ),
        "already_in_manifest_count": sum(
            1 for row in passed if api_identity(row["test_url"]) in old_manifest_identities
        ),
        "new_manifest_entry_count": len(additions),
        "endpoint_test_truncated": truncated,
        "max_endpoint_limit": MAX_ENDPOINTS,
        "config_results": [
            {k: row[k] for k in ("name", "url", "status", "http", "detail")}
            for row in config_results
        ],
        "verified_apis": [
            {
                "name": make_manifest_name(row),
                "url": row["test_url"],
                "status": row["status"],
                "http": row["http"],
                "detail": row["detail"],
                "sources": row["sources"],
                "added_to_apilinks": api_identity(row["test_url"]) in added_identities,
            }
            for row in passed
        ],
        "failed_api_samples": [
            {
                "url": row["test_url"], "status": row["status"],
                "http": row["http"], "detail": row["detail"],
                "config_name": row["config_name"], "site_name": row["site_name"],
            }
            for row in endpoint_results if not row["valid"]
        ][:200],
        "safety": (
            "只请求参考仓库清单中的 TVBox 配置 URL，再提取其中 type 0/1 的绝对 HTTP(S) sites.api；"
            "只把通过影视 JSON/XML 数据校验的真实 VOD API 写入本仓库 apilinks.txt。"
            "所有请求均执行公网 IP、重定向、响应体大小、主机熔断和单 URL 时间预算校验；"
            "不执行远程脚本，不覆盖或删除原始配置。"
        ),
    }
    output = root / "sources" / "collected" / "reference_tvbox_source_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    report = run_audit()
    print(json.dumps({
        "reference_config_urls": report["unique_reference_config_url_count"],
        "config_fetch_status_counts": report["config_fetch_status_counts"],
        "valid_tvbox_configs": report["valid_tvbox_config_count"],
        "extracted_api_candidates": report["unique_extracted_api_count"],
        "tested_api_count": report["tested_api_count"],
        "api_test_status_counts": report["api_test_status_counts"],
        "verified_api_count": report["verified_api_count"],
        "new_manifest_entries": report["new_manifest_entry_count"],
        "report": "sources/collected/reference_tvbox_source_audit.json",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
