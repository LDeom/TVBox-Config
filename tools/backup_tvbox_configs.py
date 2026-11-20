#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Back up explicit TVBox JSON configuration URLs from apilinks.txt.

This complements the VOD API health checker: it accepts complete TVBox config
JSON (sites/lives/parses/spider, etc.), preserves a decoded source snapshot,
and emits a second copy with known relative resource URLs made absolute.
Remote Python/JavaScript/JAR files are never executed or downloaded here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from api_link_catalog import load_api_links
from fetch_util import FetchError, fetch_bytes
from source_pipeline import parse_package_json

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "apilinks.txt"
OUT = ROOT / "sources" / "collected" / "api_backups"
RAW_DIR = OUT / "raw"
PORTABLE_DIR = OUT / "portable"
HISTORY = ROOT / "output" / "history" / "api_backups"
REPORT = ROOT / "output" / "reports" / "api_backup_report.json"
INDEX = OUT / "index.json"
LIST = OUT / "list.txt"
MAX_BYTES = 4 * 1024 * 1024
MAX_HISTORY = 5
USER_AGENTS = (
    "okhttp/3.12.13",
    "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
)
TOP_URL_FIELDS = {
    "spider", "wallpaper", "homeLogo", "homeBg", "homeSite",
    "livePlayHeaders", "logo", "homeSearch", "homeRec", "md5",
}
RESOURCE_FIELDS = {"jar", "playUrl", "logo", "url", "epg"}
CODE_PREFIXES = ("csp_", "json_", "nodejs_", "py_", "js_", "http_")


def safe_stem(name: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name)).strip(" ._")
    value = re.sub(r"\s+", "_", value)[:72]
    return value or "unnamed"


def should_resolve(value) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value or value.isdigit():
        return False
    if value.startswith(("http://", "https://", "//", "data:", "file:")):
        return False
    if value.startswith(CODE_PREFIXES):
        return False
    return (value.startswith(("/", "./", "../")) or "/" in value or
            ("." in value and not value.startswith(".")))


def absolutize_tvbox_config(obj, source_url: str):
    """Return a deep-copied TVBox config with known relative resource URLs fixed."""
    cloned = json.loads(json.dumps(obj, ensure_ascii=False))
    if not isinstance(cloned, dict):
        return cloned

    def resolve(value):
        return urljoin(source_url, value.strip()) if should_resolve(value) else value

    def resolve_ext(value):
        if isinstance(value, str):
            return resolve(value)
        if isinstance(value, list):
            return [resolve_ext(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve_ext(item) for key, item in value.items()}
        return value

    for field in TOP_URL_FIELDS:
        if field in cloned and isinstance(cloned[field], str):
            cloned[field] = resolve(cloned[field])

    for collection, fields in (
        ("sites", RESOURCE_FIELDS | {"api"}),
        ("lives", RESOURCE_FIELDS),
        ("parses", {"url", "logo"}),
        ("rules", {"url"}),
    ):
        rows = cloned.get(collection)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field in fields:
                value = row.get(field)
                if isinstance(value, str):
                    # Site API values can be identifiers or executable spider names.
                    if field != "api" or should_resolve(value):
                        row[field] = resolve(value)
            if "ext" in row:
                row["ext"] = resolve_ext(row["ext"])
    return cloned


def json_bytes(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def archive_if_changed(path: Path, digest: str, new_bytes: bytes) -> None:
    if not path.is_file():
        return
    old_bytes = path.read_bytes()
    if old_bytes == new_bytes:
        return
    folder = HISTORY / digest
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (folder / f"{stamp}_{path.name}").write_bytes(old_bytes)
    versions = sorted(folder.glob("*.json"), key=lambda item: item.name)
    for old in versions[:-MAX_HISTORY]:
        old.unlink(missing_ok=True)


def grouped_records(records):
    groups = OrderedDict()
    for record in records:
        name = str(record.get("name") or record.get("key") or "unnamed").strip()
        groups.setdefault(name.casefold(), {"name": name, "urls": []})
        if record["api"] not in groups[name.casefold()]["urls"]:
            groups[name.casefold()]["urls"].append(record["api"])
    return list(groups.values())


def fetch_config(group):
    name = group["name"]
    failures = []
    for url in group["urls"]:
        for ua in USER_AGENTS:
            try:
                response = fetch_bytes(
                    url, timeout=(5, 12), max_bytes=MAX_BYTES, retries=1,
                    headers={"User-Agent": ua, "Accept": "application/json, text/plain, */*"},
                )
                if not 200 <= response.status_code < 300:
                    failures.append(f"{url}: HTTP {response.status_code}")
                    continue
                obj = parse_package_json(response.body)
                # Keep any non-empty JSON object/list as a backup. This includes
                # complete TVBox configs and valid VOD API response snapshots.
                return {
                    "name": name, "status": "JSON备份成功", "source_url": url,
                    "final_url": response.url, "http": response.status_code,
                    "bytes": len(response.body), "user_agent": ua, "object": obj,
                }
            except (FetchError, ValueError, OSError) as exc:
                failures.append(f"{url} [{ua[:18]}]: {exc}")
    return {"name": name, "status": "全部线路失败", "source_url": "",
            "bytes": 0, "detail": "；".join(failures[-8:])}


def build_backup(group, result):
    source_url = result["source_url"]
    digest = hashlib.sha256((group["name"] + "\n" + source_url).encode()).hexdigest()[:16]
    filename = f"{safe_stem(group['name'])}_{digest}.json"
    raw_path = RAW_DIR / filename
    portable_path = PORTABLE_DIR / filename

    raw_bytes = json_bytes(result["object"])
    portable_obj = absolutize_tvbox_config(result["object"], source_url)
    portable_bytes = json_bytes(portable_obj)

    # Archive the previous cache before writing its replacement.
    archive_if_changed(raw_path, digest, raw_bytes)
    archive_if_changed(portable_path, digest + "_portable", portable_bytes)
    write_bytes(raw_path, raw_bytes)
    write_bytes(portable_path, portable_bytes)

    result.pop("object", None)
    result.update({
        "id": digest,
        "raw_file": raw_path.relative_to(ROOT).as_posix(),
        "portable_file": portable_path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "portable_sha256": hashlib.sha256(portable_bytes).hexdigest(),
        "relative_url_copy": raw_bytes != portable_bytes,
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    records = load_api_links(INPUT)
    groups = grouped_records(records)

    results = []
    for group in groups:
        result = fetch_config(group)
        if result.get("status") == "JSON备份成功":
            result = build_backup(group, result)
            print(f"[OK] {group['name']}: {result['portable_file']}")
        else:
            print(f"[FAIL] {group['name']}: {result.get('detail', '')}")
        results.append(result)

    generated = datetime.now(timezone.utc).isoformat()
    success = [item for item in results if item.get("status") == "JSON备份成功"]
    index = {
        "generated_at": generated,
        "source_file": "apilinks.txt",
        "input_endpoint_count": len(records),
        "group_count": len(groups),
        "success_count": len(success),
        "failure_count": len(results) - len(success),
        "note": "只备份 apilinks.txt 明确列出的 JSON；不执行远程代码，不覆盖原始配置。",
        "results": results,
    }
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    list_lines = ["# name|portable_file|source_url"]
    for item in success:
        list_lines.append("|".join((item["name"], item["portable_file"], item["source_url"])))
    LIST.write_text("\n".join(list_lines) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "endpoint_count": len(records), "group_count": len(groups),
        "success_count": len(success), "failure_count": len(results) - len(success),
    }, ensure_ascii=False))
    # Empty input is a valid no-op; actual failures remain visible in the report.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
