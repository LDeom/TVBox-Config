#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export stable, human-readable API snapshot files from the validated API index.

The source_pipeline remains responsible for fetching and validating API payloads.
This exporter only copies already-validated local snapshots into a named directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from source_pipeline import valid_vod_payload

ROOT = Path(__file__).resolve().parents[1]
API_INDEX = ROOT / "sources" / "collected" / "api_index.json"
OUTPUT_DIR = ROOT / "sources" / "collected" / "api_named"
INDEX_PATH = OUTPUT_DIR / "index.json"
LIST_PATH = OUTPUT_DIR / "list.txt"
SUMMARY_PATH = OUTPUT_DIR / "SUMMARY.txt"
VALID_STATUSES = {"有效影视 JSON", "有效影视 XML"}


def safe_stem(name: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name)).strip(" ._")
    value = re.sub(r"\s+", "_", value)[:72]
    return value or "unnamed"


def stable_id(key: str) -> str:
    return hashlib.sha256(key.casefold().encode("utf-8")).hexdigest()[:16]


def _safe_repo_file(root: Path, relative: str) -> Path | None:
    if not relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _group_api_results(api_index: dict) -> list[dict]:
    grouped = OrderedDict()
    for row in api_index.get("results", []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("name") or "").strip()
        if not key:
            continue
        group_key = key.casefold()
        group = grouped.setdefault(group_key, {
            "key": key,
            "name": str(row.get("name") or key).strip() or key,
            "rows": [],
        })
        group["rows"].append(row)
    return list(grouped.values())


def _choose_valid_result(group: dict, recommendations: dict) -> dict | None:
    rows = group["rows"]
    valid = [
        row for row in rows
        if row.get("status") in VALID_STATUSES and row.get("saved_file")
    ]
    if not valid:
        return None
    recommendation = recommendations.get(group["key"].casefold(), {})
    preferred = recommendation.get("preferred_url") if isinstance(recommendation, dict) else ""
    if preferred:
        for row in valid:
            if row.get("api") == preferred:
                return row
    return valid[0]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def export_named_snapshots(api_index: dict, root: Path = ROOT) -> dict:
    """Write one stable named snapshot per API key and preserve prior cache on failure."""
    output_dir = root / "sources" / "collected" / "api_named"
    index_path = output_dir / "index.json"
    old_by_id = {}
    if index_path.is_file():
        try:
            old_index = json.loads(index_path.read_text(encoding="utf-8-sig"))
            old_by_id = {
                str(item.get("id")): item
                for item in old_index.get("results", [])
                if isinstance(item, dict) and item.get("id")
            }
        except (OSError, ValueError, TypeError):
            old_by_id = {}

    recommendations = api_index.get("mirror_recommendations", {})
    if not isinstance(recommendations, dict):
        recommendations = {}
    results = []

    for group in _group_api_results(api_index):
        identifier = stable_id(group["key"])
        previous = old_by_id.get(identifier, {})
        candidate = _choose_valid_result(group, recommendations)
        if candidate:
            source = _safe_repo_file(root, str(candidate.get("saved_file") or ""))
            if source:
                try:
                    payload = source.read_bytes()
                    _obj, status, detail = valid_vod_payload(payload)
                except OSError as exc:
                    status, detail, payload = "快照读取失败", str(exc), b""
                if status in VALID_STATUSES and payload:
                    extension = source.suffix.lower()
                    if extension not in {".json", ".xml"}:
                        extension = ".json"
                    filename = f"{safe_stem(group['name'])}_{identifier}{extension}"
                    target = output_dir / filename
                    _atomic_write(target, payload)
                    results.append({
                        "id": identifier,
                        "key": group["key"],
                        "name": group["name"],
                        "status": "命名快照已更新",
                        "source_url": candidate.get("api", ""),
                        "source_file": source.relative_to(root.resolve()).as_posix(),
                        "saved_file": target.relative_to(root.resolve()).as_posix(),
                        "format": status,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "mirror_count": len(group["rows"]),
                    })
                    continue
                failure_detail = detail or f"缓存内容校验失败：{status}"
            else:
                failure_detail = "API 索引中的 saved_file 不存在或越界"
        else:
            failure_detail = "当前没有有效影视 JSON/XML 镜像"

        previous_file = _safe_repo_file(root, str(previous.get("saved_file") or ""))
        if previous_file:
            results.append({
                "id": identifier,
                "key": group["key"],
                "name": group["name"],
                "status": "更新失败，保留旧命名快照",
                "source_url": previous.get("source_url", ""),
                "source_file": previous.get("source_file", ""),
                "saved_file": previous_file.relative_to(root.resolve()).as_posix(),
                "format": previous.get("format", ""),
                "bytes": previous_file.stat().st_size,
                "sha256": hashlib.sha256(previous_file.read_bytes()).hexdigest(),
                "mirror_count": len(group["rows"]),
                "detail": failure_detail,
            })
        else:
            results.append({
                "id": identifier,
                "key": group["key"],
                "name": group["name"],
                "status": "没有可用快照",
                "source_url": "",
                "saved_file": "",
                "mirror_count": len(group["rows"]),
                "detail": failure_detail,
            })

    counts = Counter(item["status"] for item in results)
    generated = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": generated,
        "source_index": "sources/collected/api_index.json",
        "group_count": len(results),
        "success_count": counts.get("命名快照已更新", 0),
        "retained_count": counts.get("更新失败，保留旧命名快照", 0),
        "failure_count": counts.get("没有可用快照", 0),
        "status_counts": dict(counts),
        "results": results,
        "note": "只复制 source_pipeline 已验证的本地 API 快照；失败时保留旧命名文件，不生成历史副本。",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    list_lines = ["# name|saved_file|source_url|status"]
    for item in results:
        if item.get("saved_file"):
            list_lines.append("|".join((
                item["name"], item["saved_file"], item.get("source_url", ""),
                item["status"],
            )))
    LIST_PATH_FOR_ROOT = output_dir / "list.txt"
    LIST_PATH_FOR_ROOT.write_text("\n".join(list_lines) + "\n", encoding="utf-8")
    summary_lines = [
        "TVBox 点播 API 命名快照报告",
        f"生成时间：{generated}",
        f"接口组：{len(results)}",
        f"本轮更新：{report['success_count']}",
        f"保留旧快照：{report['retained_count']}",
        f"无可用快照：{report['failure_count']}",
        "",
    ]
    for item in results:
        summary_lines.append(
            f"[{item['status']}] {item['name']} | {item.get('saved_file') or '无文件'}"
        )
    (output_dir / "SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--api-index", type=Path, default=API_INDEX)
    args = parser.parse_args()
    root = args.root.resolve()
    index_path = args.api_index if args.api_index.is_absolute() else root / args.api_index
    if not index_path.is_file():
        print(f"API 索引不存在，跳过命名导出：{index_path}")
        return 0
    api_index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    report = export_named_snapshots(api_index, root=root)
    print(json.dumps({
        "group_count": report["group_count"],
        "success_count": report["success_count"],
        "retained_count": report["retained_count"],
        "failure_count": report["failure_count"],
        "output": "sources/collected/api_named/",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
