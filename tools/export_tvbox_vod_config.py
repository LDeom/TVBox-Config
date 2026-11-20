#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export a directly importable TVBox VOD configuration from validated JSON APIs.

Only type=1 APIs with a locally cached, structurally valid JSON VOD payload are
included. XML APIs, custom spiders, failed endpoints and missing snapshots are
excluded. The output path is stable and overwritten on every maintenance run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from source_pipeline import valid_vod_payload

ROOT = Path(__file__).resolve().parents[1]
API_INDEX = Path("sources/collected/api_index.json")
OUTPUT = Path("sources/collected/tvbox_vod_config.json")
SUMMARY = Path("sources/collected/tvbox_vod_config_summary.txt")
VALID_JSON = "有效影视 JSON"


def _safe_local_file(root: Path, relative: str) -> Path | None:
    if not relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _tvbox_api_url(value: str) -> str:
    """Remove only the list-only ac=list probe parameter; preserve other query data."""
    parts = urlsplit(str(value).strip())
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not (key.lower() == "ac" and val.lower() == "list")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _url_identity(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path.rstrip("/"), parts.query, ""))


def _is_valid_cached_json(row: dict, root: Path) -> bool:
    if str(row.get("type", "")) != "1" or row.get("status") != VALID_JSON:
        return False
    api = str(row.get("api") or "")
    if not api.startswith(("http://", "https://")):
        return False
    # XML endpoints must never be placed in the MacCMS JSON API site list.
    if "/at/xml" in urlsplit(api).path.lower() or urlsplit(api).path.lower().endswith(".xml"):
        return False
    cached = _safe_local_file(root, str(row.get("saved_file") or ""))
    if not cached:
        return False
    try:
        _obj, status, _detail = valid_vod_payload(cached.read_bytes())
    except OSError:
        return False
    return status == VALID_JSON


def build_tvbox_config(api_index: dict, root: Path = ROOT) -> tuple[dict, list[dict]]:
    """Build a minimal TVBox config and a report of the included VOD sites."""
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for row in api_index.get("results", []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("name") or "").strip()
        if key:
            grouped.setdefault(key.casefold(), []).append(row)

    recommendations = api_index.get("mirror_recommendations", {})
    if not isinstance(recommendations, dict):
        recommendations = {}

    sites: list[dict] = []
    included: list[dict] = []
    seen_urls: set[str] = set()
    used_keys: set[str] = set()

    for rows in grouped.values():
        candidates = [row for row in rows if _is_valid_cached_json(row, root)]
        if not candidates:
            continue
        first = rows[0]
        key = str(first.get("key") or first.get("name") or "vod").strip()
        recommendation = recommendations.get(key.casefold(), {})
        preferred = recommendation.get("preferred_url", "") if isinstance(recommendation, dict) else ""
        candidates.sort(key=lambda row: (
            0 if row.get("api") == preferred else 1,
            float(row.get("seconds") or 999999),
        ))
        selected = None
        selected_url = ""
        for candidate in candidates:
            api_url = _tvbox_api_url(candidate.get("api", ""))
            identity = _url_identity(api_url)
            if api_url and identity not in seen_urls:
                selected, selected_url = candidate, api_url
                break
        if not selected:
            continue

        site_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_.-") or "vod"
        base_key, suffix = site_key, 2
        while site_key.casefold() in used_keys:
            site_key = f"{base_key}_{suffix}"
            suffix += 1
        used_keys.add(site_key.casefold())
        seen_urls.add(_url_identity(selected_url))

        site = {
            "key": site_key,
            "name": str(selected.get("name") or key),
            "type": 1,
            "api": selected_url,
            "searchable": int(selected.get("searchable", 1) or 0),
            "quickSearch": int(selected.get("searchable", 1) or 0),
            "filterable": int(selected.get("filterable", 0) or 0),
        }
        if "changeable" in selected:
            site["changeable"] = int(selected.get("changeable") or 0)
        sites.append(site)
        included.append({
            "key": key,
            "name": site["name"],
            "api": selected_url,
            "snapshot": str(selected.get("saved_file") or ""),
        })

    config = {
        "sites": sites,
        "parses": [],
        "lives": [],
    }
    return config, included


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def export_config(root: Path = ROOT) -> dict:
    index_path = root / API_INDEX
    if not index_path.is_file():
        raise FileNotFoundError(f"API index not found: {index_path}")
    api_index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    config, included = build_tvbox_config(api_index, root)
    if not included:
        raise RuntimeError("No validated JSON VOD API with a valid local snapshot; existing output was not replaced.")

    generated = str(api_index.get("generated_at") or "unknown")
    config_text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    summary_lines = [
        "TVBox 可导入点播配置生成报告",
        f"API 索引时间：{generated}",
        f"纳入接口数：{len(included)}",
        "筛选条件：type=1、有效影视 JSON、存在且复验通过的本地快照",
        "排除：XML API、type=0 自定义爬虫、无效接口、缺失或无效缓存",
        "说明：影视 JSON 结构有效不等于每条视频播放地址都能播放。",
        "",
    ]
    summary_lines.extend(f"{item['name']} | {item['api']}" for item in included)
    _atomic_write(root / OUTPUT, config_text)
    _atomic_write(root / SUMMARY, "\n".join(summary_lines) + "\n")
    return {"site_count": len(included), "config_path": OUTPUT.as_posix(),
            "summary_path": SUMMARY.as_posix(), "sites": included}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = export_config(args.root.resolve())
    print(f"TVBox VOD config exported: {result['site_count']} sites -> {result['config_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
