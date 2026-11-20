#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded, all-or-nothing pagination for standard TVBox VOD APIs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fetch_util import FetchError, fetch_bytes
from source_pipeline import valid_vod_payload

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sources" / "collected" / "api_pages"
HISTORY_DIR = ROOT / "output" / "history" / "api_pages"
MAX_PAGE_BYTES = 2 * 1024 * 1024


def _as_positive_int(value):
    try:
        number = int(value)
        return number if number > 0 else 0
    except (TypeError, ValueError):
        return 0


def pagination_info(obj):
    """Return (array_key, page_count, total_items) for recognized JSON APIs."""
    if not isinstance(obj, dict):
        return None
    list_key = next((key for key in ("list", "data", "videos", "items")
                     if isinstance(obj.get(key), list)), None)
    if not list_key:
        return None
    page_count = 0
    for key in ("pagecount", "page_count", "pageCount", "total_pages",
                "totalPage", "totalPageCount"):
        page_count = _as_positive_int(obj.get(key))
        if page_count:
            break
    total = _as_positive_int(obj.get("total"))
    limit = _as_positive_int(obj.get("limit") or obj.get("pagesize") or obj.get("pageSize"))
    if not page_count and total and limit:
        page_count = (total + limit - 1) // limit
    return {"list_key": list_key, "page_count": page_count, "total": total}


def page_url(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    page_key = "page" if any(key.lower() == "page" for key, _ in query) else "pg"
    query = [(key, value) for key, value in query
             if key.lower() not in {"pg", "page"}]
    query.append((page_key, str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def fetch_paginated_api(record, *, max_pages=10, fetcher=None):
    """Fetch all declared pages; never publish a partial aggregation."""
    fetcher = fetcher or fetch_bytes
    url = str(record.get("api") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {**record, "status": "无效 URL", "pages_fetched": 0}
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target = OUTPUT_DIR / f"{digest}.json"
    cached = target.is_file()

    def failure(status, detail="", pages=0):
        return {
            **record, "status": status, "detail": detail,
            "pages_fetched": pages, "saved_file": target.relative_to(ROOT).as_posix()
            if cached else "", "cached_previous": cached
        }

    try:
        first_response = fetcher(
            page_url(url, 1), timeout=(4, 8), max_bytes=MAX_PAGE_BYTES, retries=1,
            headers={"Accept": "application/json, text/plain, */*"}
        )
        if not 200 <= first_response.status_code < 300:
            return failure("HTTP失败", f"HTTP {first_response.status_code}")
        first_obj, status, detail = valid_vod_payload(first_response.body)
        if not isinstance(first_obj, dict):
            return failure("非分页 JSON API", detail or status)
        meta = pagination_info(first_obj)
        if not meta or not meta["page_count"]:
            return failure("未发现分页信息", "未识别 pagecount/total+limit 元数据")
        page_count = meta["page_count"]
        if page_count <= 1:
            return failure("只有一页", "API 元数据声明只有一页", 1)
        max_pages = max(1, min(int(max_pages), 20))
        if page_count > max_pages:
            return failure("超过分页上限", f"API 声明 {page_count} 页，上限 {max_pages}；未写入部分结果")

        list_key = meta["list_key"]
        merged = dict(first_obj)
        merged[list_key] = list(first_obj[list_key])
        for page in range(2, page_count + 1):
            response = fetcher(
                page_url(url, page), timeout=(4, 8), max_bytes=MAX_PAGE_BYTES, retries=1,
                headers={"Accept": "application/json, text/plain, */*"}
            )
            if not 200 <= response.status_code < 300:
                return failure("分页请求失败", f"第 {page} 页 HTTP {response.status_code}",
                               page - 1)
            page_obj, page_status, page_detail = valid_vod_payload(response.body)
            if (not isinstance(page_obj, dict)
                    or not isinstance(page_obj.get(list_key), list)):
                return failure("分页结构异常",
                               f"第 {page} 页结构无效：{page_detail or page_status}",
                               page - 1)
            merged[list_key].extend(page_obj[list_key])

        payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        old_bytes = target.read_bytes() if cached else None
        new_bytes = payload.encode("utf-8")
        if old_bytes != new_bytes and old_bytes is not None:
            backup_dir = HISTORY_DIR / digest
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            (backup_dir / f"{stamp}_{digest}.json").write_bytes(old_bytes)
            backups = sorted(backup_dir.glob("*.json"), key=lambda item: item.name)
            for old in backups[:-5]:
                old.unlink(missing_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new_bytes)
        return {
            **record, "status": "分页采集完成", "pages_fetched": page_count,
            "page_count": page_count, "item_count": len(merged[list_key]),
            "saved_file": target.relative_to(ROOT).as_posix(),
            "cached_previous": False
        }
    except (FetchError, OSError, ValueError) as exc:
        message = str(exc)
        security = any(word in message for word in
                       ("拒绝", "不允许", "非公网 IP", "本机", "局域网", "重定向"))
        return failure("安全拦截" if security else "请求失败", message)
