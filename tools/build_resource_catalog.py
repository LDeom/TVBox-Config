#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a stable-path inventory of auxiliary TVBox resources already in this repo.

This tool inventories local files only. It never imports resources from another
repository, downloads remote files, or executes JS/Python/JAR content.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("sources/collected/resource_catalog.json")
SCAN_DIRS = (
    "sources/dependencies",
    "sources/js",
    "sources/jar",
    "sources/py",
    "sources/live",
    "sources/vod",
    "sources/configs/vod",
    "sources/pending",
)
CATEGORY_HINTS = {
    "audio": ("听书", "音源", "音乐", "电台", "评书", "相声", "dj"),
    "comic": ("漫画", "动漫"),
    "danmaku": ("弹幕", "danmu"),
    "template": ("模板", "template"),
    "live": ("直播", "live", "m3u"),
    "vod": ("点播", "影视", "影院", "vod", "config"),
    "book": ("书源", "小说", "阅读", "book"),
}


def classify(path: Path, rel: str) -> str:
    low = (rel + "/" + path.name).lower()
    if "/sources/live/" in ("/" + rel + "/") or path.suffix.lower() in {".m3u", ".m3u8"}:
        return "live"
    for category, hints in CATEGORY_HINTS.items():
        if any(h.lower() in low for h in hints):
            return category
    if path.suffix.lower() == ".jar":
        return "jar_dependency"
    if path.suffix.lower() == ".py":
        return "python_site_or_tool"
    if path.suffix.lower() == ".js":
        return "javascript_plugin"
    if path.suffix.lower() == ".json":
        return "json_config_or_resource"
    if path.suffix.lower() in {".txt", ".xml"}:
        return "text_resource"
    return "other"


def build_catalog(root: Path) -> dict:
    entries = []
    for directory in SCAN_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            rel = path.relative_to(root).as_posix()
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entries.append({
                "path": rel,
                "category": classify(path, rel),
                "extension": path.suffix.lower(),
                "size_bytes": size,
            })
    counts = Counter(item["category"] for item in entries)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "local_repository_only",
        "total_files": len(entries),
        "category_counts": dict(sorted(counts.items())),
        "resources": entries,
        "notes": [
            "仅登记本仓库已有文件，不代表资源可用或可播放。",
            "不从其他仓库导入资源，不下载远程文件，不执行 JS/Python/JAR。",
            "每日运行覆盖本文件，路径和文件名保持不变，不生成日期副本。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    catalog = build_catalog(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"资源文件: {catalog['total_files']}")
    print(f"分类: {json.dumps(catalog['category_counts'], ensure_ascii=False)}")
    print(f"输出: {output.relative_to(root) if output.is_relative_to(root) else output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
