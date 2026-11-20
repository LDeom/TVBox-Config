#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative HTTP/HLS reachability checks for local TVBox live playlists."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from fetch_util import FetchError, fetch_bytes
from source_pipeline import flatten_live_json, parse_playlist, read_json

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "sources" / "live"
COLLECTED = ROOT / "sources" / "collected"
REPORT_DIR = ROOT / "output" / "reports"
MAX_MANIFEST_BYTES = 512 * 1024
MAX_SEGMENT_BYTES = 256 * 1024


def collect_live_candidates(limit: int = 300):
    rows = []
    paths = sorted(list(LIVE_DIR.glob("*.m3u")) + list(LIVE_DIR.glob("*.txt")))
    for path in paths:
        try:
            parsed = parse_playlist(path.read_text(encoding="utf-8-sig", errors="replace"),
                                    path.stem)
            rows.extend({**item, "source_file": path.relative_to(ROOT).as_posix()}
                        for item in parsed)
        except OSError as exc:
            print(f"[WARN] {path}: {exc}")
    for path in sorted(LIVE_DIR.glob("*.json")):
        try:
            parsed = flatten_live_json(read_json(path))
            rows.extend({**item, "source_file": path.relative_to(ROOT).as_posix()}
                        for item in parsed)
        except Exception as exc:
            print(f"[WARN] {path}: {exc}")

    unique = {}
    for row in rows:
        url = str(row.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            unique.setdefault(url, row)
    values = list(unique.values())
    return values[:max(1, min(int(limit), 2000))]


def probe_stream(url: str, fetcher=None):
    fetcher = fetcher or fetch_bytes
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"url": url, "status": "不支持的协议", "level": "unsupported"}

    try:
        response = fetcher(
            url, timeout=(3, 6), max_bytes=MAX_MANIFEST_BYTES, retries=0,
            headers={"Range": "bytes=0-524287",
                     "Accept": "application/vnd.apple.mpegurl, video/*, */*"}
        )
        if not 200 <= response.status_code < 300:
            return {"url": url, "status": "HTTP失败", "http": response.status_code,
                    "level": "http_failed"}

        body = response.body or b""
        text = body.decode("utf-8-sig", "replace")
        is_hls = text.lstrip().startswith("#EXTM3U") and (
            "#EXT-X-" in text or ".m3u8" in url.lower()
        )
        if is_hls:
            segment = next((
                line.strip() for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ), "")
            if not segment:
                return {"url": url, "status": "HLS 清单可访问但没有媒体分片",
                        "http": response.status_code, "level": "manifest_only"}
            segment_url = urljoin(getattr(response, "url", url) or url, segment)
            segment_response = fetcher(
                segment_url, timeout=(3, 6), max_bytes=MAX_SEGMENT_BYTES, retries=0,
                headers={"Range": "bytes=0-262143", "Accept": "video/*, */*"}
            )
            if 200 <= segment_response.status_code < 300 and segment_response.body:
                return {
                    "url": url, "status": "HLS 清单与首个分片均可访问",
                    "http": response.status_code, "segment_http": segment_response.status_code,
                    "segment_url": segment_url, "level": "hls_segment"
                }
            return {
                "url": url, "status": "HLS 清单可访问但首个分片失败",
                "http": response.status_code, "segment_http": segment_response.status_code,
                "segment_url": segment_url, "level": "manifest_only"
            }

        content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
        if "text/html" in content_type:
            return {"url": url, "status": "HTTP 可访问但疑似网页响应",
                    "http": response.status_code, "level": "http_only"}
        if not body:
            return {"url": url, "status": "HTTP 可访问但响应体为空",
                    "http": response.status_code, "level": "http_only"}
        return {
            "url": url, "status": "媒体直链 HTTP 可访问（未验证解码）",
            "http": response.status_code, "content_type": content_type,
            "level": "http_only"
        }
    except (FetchError, OSError, ValueError) as exc:
        message = str(exc)
        security = any(word in message for word in
                       ("拒绝", "不允许", "非公网 IP", "本机", "局域网", "重定向"))
        return {"url": url, "status": "安全拦截" if security else "请求失败",
                "detail": message, "level": "blocked" if security else "unreachable"}


def run_checks(rows, workers=5):
    if not rows:
        return []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {
            pool.submit(probe_stream, row["url"]): row for row in rows
        }
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"url": row["url"], "status": "检测异常",
                          "detail": str(exc), "level": "error"}
            results.append({**row, **result})
    order = {row["url"]: index for index, row in enumerate(rows)}
    results.sort(key=lambda item: order.get(item.get("url"), 10**9))
    return results


def write_report(results, candidate_count):
    counts = Counter(item.get("level", "unknown") for item in results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": candidate_count,
        "checked_count": len(results),
        "level_counts": dict(counts),
        "results": results,
        "verification_note": (
            "HLS 首分片可访问不等于设备端一定能播放；HTTP 直链仅验证连接和有限响应，"
            "未验证 DRM、解码、音视频同步或电视盒子兼容性。"
        )
    }
    for path in (COLLECTED / "live_health_report.json",
                 REPORT_DIR / "live_health_report.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    rows = collect_live_candidates(args.limit)
    results = run_checks(rows, args.workers)
    report = write_report(results, len(rows))
    print(json.dumps({
        "candidate_count": report["candidate_count"],
        "checked_count": report["checked_count"],
        "level_counts": report["level_counts"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
