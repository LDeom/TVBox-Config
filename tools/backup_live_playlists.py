#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download and archive each live playlist declared in local TVBox configs."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fetch_util import FetchError, fetch_bytes
from source_pipeline import (
    extract_catalog, fetch_live_playlist, load_local_documents, write_m3u,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sources" / "collected" / "live_backups"
INDEX = OUTPUT / "index.json"
LIST = OUTPUT / "list.txt"
REPORT = ROOT / "output" / "reports" / "live_backup_report.json"
UA_PROFILES = (
    "okhttp/3.12.13",
    "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
    "VLC/3.0.20 LibVLC/3.0.20",
)


def safe_stem(name: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name)).strip(" ._")
    value = re.sub(r"\s+", "_", value)[:64]
    return value or "live"



def unique_live_sources(records):
    unique = {}
    for record in records:
        url = str(record.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = hashlib.sha256(url.encode()).hexdigest()
        unique.setdefault(key, {**record, "url": url})
    return list(unique.values())


def fetch_one(record, fetcher_factory=None):
    url = record["url"]
    name = str(record.get("name") or "未命名直播")
    configured_ua = record.get("ua")
    profiles = []
    if isinstance(configured_ua, str) and configured_ua.strip():
        profiles.append(configured_ua.strip())
    profiles.extend(ua for ua in UA_PROFILES if ua not in profiles)

    last = {}
    for ua in profiles:
        def ua_fetcher(target, **kwargs):
            if fetcher_factory:
                return fetcher_factory(target, ua=ua, **kwargs)
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["User-Agent"] = ua
            return fetch_bytes(target, headers=headers, **kwargs)

        result = fetch_live_playlist(
            url, default_group=name, fetcher=ua_fetcher
        )
        last = result
        if result.get("rows"):
            return {
                **record, "status": "直播列表已备份",
                "channels": len(result["rows"]), "ua": ua,
                "final_url": result.get("final_url", url),
                "unwrap_chain": result.get("chain", []),
                "unwrap_depth": max(0, len(result.get("chain", [])) - 1),
                "rows": result["rows"],
            }

    return {
        **record, "status": last.get("status", "下载失败"),
        "detail": last.get("detail", "所有 UA 均未提取到频道"),
        "channels": 0, "final_url": last.get("final_url", url),
        "unwrap_chain": last.get("chain", []),
        "unwrap_depth": max(0, len(last.get("chain", [])) - 1),
    }


def save_result(record):
    url = record["url"]
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    filename = f"{safe_stem(record.get('name') or 'live')}_{digest}.m3u"
    target = OUTPUT / filename
    if record.get("status") == "直播列表已备份":
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".m3u", delete=False) as temp:
            temp_path = Path(temp.name)
        try:
            write_m3u(temp_path, record["rows"])
            payload = temp_path.read_bytes()
        finally:
            temp_path.unlink(missing_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        record = {**record, "saved_file": target.relative_to(ROOT).as_posix(),
                  "sha256": hashlib.sha256(payload).hexdigest(),
                  "cached_previous": False}
    else:
        record = {**record, "saved_file": target.relative_to(ROOT).as_posix()
                  if target.is_file() else "",
                  "cached_previous": target.is_file()}
        if target.is_file():
            record["status"] = "下载失败，保留旧备份"
    record.pop("rows", None)
    return record


def main():
    docs = load_local_documents()
    _, live_sources, _, _ = extract_catalog(docs)
    records = unique_live_sources(live_sources)
    results = []
    for record in records:
        result = save_result(fetch_one(record))
        results.append(result)
        print(f"[{result['status']}] {result.get('name')} channels={result.get('channels', 0)}")

    generated = datetime.now(timezone.utc).isoformat()
    success = [item for item in results if item.get("status") == "直播列表已备份"]
    index = {
        "generated_at": generated,
        "source": "local TVBox config files (sites/lives)",
        "source_count": len(records),
        "success_count": len(success),
        "failure_count": len(results) - len(success),
        "channel_count": sum(item.get("channels", 0) for item in success),
        "note": "每个源独立保存；最多 5 层 URL 套壳展开；失败时保留旧备份。",
        "results": results,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# name|saved_file|channels|source_url"]
    for item in success:
        lines.append("|".join((
            str(item.get("name") or ""), item.get("saved_file", ""),
            str(item.get("channels", 0)), item.get("url", ""),
        )))
    LIST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_count": len(records), "success_count": len(success),
        "failure_count": len(results) - len(success),
        "channel_count": index["channel_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
