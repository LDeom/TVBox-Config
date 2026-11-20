#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a source catalog from files already stored in this repository.

The pipeline never imports/replaces source configuration JSON from another repo.
Remote requests are limited to API and playlist URLs explicitly present in local
configuration files. Failed or invalid responses never replace a previous copy.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import gzip
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit, urlunsplit

from fetch_util import FetchError, fetch_bytes

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "sources" / "configs" / "vod"
LIVE_DIR = ROOT / "sources" / "live"
COLLECTED = ROOT / "sources" / "collected"
API_DIR = COLLECTED / "api"
LIVE_OUT = COLLECTED / "live"
HISTORY = ROOT / "output" / "history" / "api"
REPORT_DIR = ROOT / "output" / "reports"
API_INDEX = COLLECTED / "api_index.json"
MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_API_BYTES = 2 * 1024 * 1024
MAX_LIVE_BYTES = 4 * 1024 * 1024
MAX_HISTORY_FILES = 1
LIST_KEYS = {"list", "data", "vod", "videos", "items", "result"}
VOD_KEYS = {"vod_id", "vod_name", "vod_pic", "vod_play_url", "id", "title", "name"}
URL_RE = re.compile(r'https?://[^\s\t\r\n"\'<>]+', re.I)
NOW = datetime.now(timezone.utc)


def stamp() -> str:
    return NOW.strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path):
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("本地 JSON 超过 8 MiB 限制")
    text = raw.decode("utf-8-sig").strip()
    try:
        return json.loads(strip_json_comments(text))
    except Exception as first:
        # Some provider wrappers encode the complete JSON as Base64 or gzip.
        candidates = []
        try:
            decoded = base64.b64decode(text, validate=True)
            candidates.append(gzip.decompress(decoded) if decoded.startswith(b"\x1f\x8b") else decoded)
        except Exception:
            pass
        if raw.startswith(b"\x1f\x8b"):
            try:
                candidates.append(gzip.decompress(raw))
            except Exception:
                pass
        for candidate in candidates:
            try:
                return json.loads(candidate.decode("utf-8-sig"))
            except Exception:
                continue
        raise first


def strip_json_comments(text: str) -> str:
    out, i, quoted, escaped = [], 0, False, False
    while i < len(text):
        ch = text[i]
        if quoted:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            i += 1
            continue
        if ch == '"':
            quoted = True
            out.append(ch)
            i += 1
        elif ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
        elif ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and text[i:i + 2] != "*/":
                i += 1
            i = min(len(text), i + 2)
        else:
            out.append(ch)
            i += 1
    cleaned = "".join(out)
    # Remove trailing commas without touching quoted strings.
    out, i, quoted, escaped = [], 0, False, False
    while i < len(cleaned):
        ch = cleaned[i]
        if quoted:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(cleaned) and cleaned[j].isspace():
                j += 1
            if j >= len(cleaned) or cleaned[j] not in "}]":
                out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def urls_in(value):
    if isinstance(value, str):
        for match in URL_RE.findall(value):
            yield match.rstrip("),;")
    elif isinstance(value, dict):
        for child in value.values():
            yield from urls_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from urls_in(child)


def canonical_url(url: str) -> str:
    """Conservative URL normalization; preserve query order and tokens."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if not host:
        return url.strip()
    port = p.port
    netloc = f"[{host}]" if ":" in host else host
    if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)):
        netloc += f":{port}"
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


def add_record(target: dict, record: dict, url_field="api") -> None:
    url = str(record.get(url_field) or "").strip()
    if not url.startswith(("http://", "https://")):
        return
    key = canonical_url(url)
    if key not in target:
        item = dict(record)
        item[url_field] = url
        item["sources"] = [record.get("source_file", "")]
        target[key] = item
    else:
        sources = target[key].setdefault("sources", [])
        src = record.get("source_file", "")
        if src and src not in sources:
            sources.append(src)


def load_local_documents():
    docs = []
    paths = (sorted(CONFIG_DIR.glob("*.json")) + sorted(LIVE_DIR.glob("*.json"))
             + sorted((ROOT / "sources" / "vod").glob("*.json")))
    for path in paths:
        try:
            docs.append((path, read_json(path)))
        except Exception as exc:
            print(f"[WARN] 本地 JSON 读取失败 {path.relative_to(ROOT)}: {exc}")
    return docs
def extract_catalog(docs):
    sites, lives, py_sites, external_packages = {}, {}, {}, {}
    for path, obj in docs:
        source_file = path.relative_to(ROOT).as_posix()
        if not isinstance(obj, dict):
            continue
        for site in obj.get("sites", []) if isinstance(obj.get("sites"), list) else []:
            if not isinstance(site, dict):
                continue
            rec = {**site, "source_file": source_file}
            api = str(site.get("api") or "")
            if re.search(r"\.py(?:$|[?#])", api, re.I):
                add_record(py_sites, rec)
            if str(site.get("type", "")) in {"0", "1"}:
                add_record(sites, rec)
        for live in obj.get("lives", []) if isinstance(obj.get("lives"), list) else []:
            if not isinstance(live, dict):
                continue
            rec = {**live, "source_file": source_file}
            url = str(live.get("url") or "")
            if url.startswith(("http://", "https://")):
                add_record(lives, rec, "url")
        # Online package references are indexed, not imported as configuration.
        for entry in obj.get("urls", []) if isinstance(obj.get("urls"), list) else []:
            if isinstance(entry, dict):
                url = str(entry.get("url") or "")
                if url.startswith(("http://", "https://")):
                    add_record(external_packages, {**entry, "source_file": source_file}, "url")
    return list(sites.values()), list(lives.values()), list(py_sites.values()), list(external_packages.values())


def valid_vod_payload(body: bytes):
    raw = body.lstrip()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig", "replace").strip()
    if not text:
        return None, "空响应", "响应体为空"

    candidates = [text]
    # JSONP-style wrapper: callback({...});
    match = re.match(r"^[\w.$]+\s*\((.*)\)\s*;?$", text, re.S)
    if match:
        candidates.append(match.group(1).strip())
    # Plain Base64-wrapped JSON/XML, including Base64(gzip(JSON)).
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 32 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        try:
            decoded = base64.b64decode(compact, validate=True)
            if decoded.startswith(b"\x1f\x8b"):
                decoded = gzip.decompress(decoded)
            candidates.append(decoded.decode("utf-8-sig", "replace").strip())
        except Exception:
            pass

    last_json_error = None
    for candidate in candidates:
        try:
            obj = json.loads(strip_json_comments(candidate))
            count, fields = 0, set()
            def walk(node, depth=0):
                nonlocal count
                if depth > 10:
                    return
                if isinstance(node, dict):
                    for key, val in node.items():
                        lk = str(key).lower()
                        if lk in VOD_KEYS:
                            fields.add(lk)
                        if lk in LIST_KEYS and isinstance(val, list):
                            count += len(val)
                            for child in val[:12]:
                                walk(child, depth + 1)
                        elif isinstance(val, (dict, list)):
                            walk(val, depth + 1)
                elif isinstance(node, list):
                    for child in node[:30]:
                        walk(child, depth + 1)
            walk(obj)
            if count and fields:
                return obj, "有效影视 JSON", f"列表项目数≥{count}; 字段={','.join(sorted(fields))}"
            last_json_error = f"列表项目数≥{count}; 字段={','.join(sorted(fields)) or '无'}"
        except Exception as exc:
            last_json_error = str(exc)

    for candidate in candidates:
        try:
            root = ET.fromstring(candidate)
            tags = {e.tag.lower().split("}")[-1] for e in root.iter()}
            count = sum(1 for e in root.iter() if e.tag.lower().split("}")[-1] in {"video", "vod", "item"})
            fields = tags & VOD_KEYS
            if count and fields:
                return candidate, "有效影视 XML", f"项目节点={count}; 字段={','.join(sorted(fields))}"
            return None, "XML 无影视数据", f"项目节点={count}"
        except Exception:
            continue
    if last_json_error and "字段=" in last_json_error:
        return None, "JSON 无影视数据", last_json_error
    return None, "格式异常", text[:160].replace("\n", " ")

def request_api_url(record):
    url = record["api"]
    if str(record.get("type")) == "1":
        p = urlsplit(url)
        q = parse_qsl(p.query, keep_blank_values=True)
        if not any(k.lower() == "ac" for k, _ in q):
            q.append(("ac", "list"))
            url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))
    return url


def fetch_api(record):
    url = request_api_url(record)
    started = time.monotonic()
    try:
        result = fetch_bytes(url, timeout=(4, 8), max_bytes=MAX_API_BYTES, retries=1)
        if not 200 <= result.status_code < 300:
            return {**record, "status": "HTTP失败", "http": result.status_code,
                    "seconds": round(time.monotonic()-started, 2), "detail": "非 2xx"}
        obj, status, detail = valid_vod_payload(result.body)
        if obj is None:
            return {**record, "status": status, "http": result.status_code,
                    "seconds": round(time.monotonic()-started, 2), "detail": detail}
        digest = hashlib.sha256(record["api"].encode()).hexdigest()[:16]
        ext = "xml" if isinstance(obj, str) else "json"
        target = API_DIR / f"{digest}.{ext}"
        if target.exists() and target.read_bytes() != (obj.encode("utf-8") if isinstance(obj, str) else (json.dumps(obj, ensure_ascii=False, indent=2)+"\n").encode()):
            backup = HISTORY / f"{digest}.{ext}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(target.read_bytes())
        if isinstance(obj, str):
            payload = obj.rstrip() + "\n"
        else:
            payload = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        return {**record, "status": status, "http": result.status_code,
                "seconds": round(time.monotonic()-started, 2), "detail": detail,
                "saved_file": target.relative_to(ROOT).as_posix(), "final_url": result.url}
    except (FetchError, ValueError, OSError, ET.ParseError) as exc:
        return {**record, "status": "请求失败/安全拦截", "http": "",
                "seconds": round(time.monotonic()-started, 2), "detail": str(exc)}


def flatten_live_json(obj, group=""):
    rows = []
    if isinstance(obj, dict):
        if isinstance(obj.get("channel"), list):
            group_name = str(obj.get("name") or group or "未分组")
            for channel in obj["channel"]:
                if not isinstance(channel, dict):
                    continue
                urls = channel.get("urls") or channel.get("url") or []
                if isinstance(urls, str):
                    urls = [urls]
                for url in urls if isinstance(urls, list) else []:
                    if isinstance(url, str) and url.startswith(("http://", "https://")):
                        rows.append({"group": group_name, "name": str(channel.get("name") or "频道"), "url": url})
        else:
            for key, value in obj.items():
                rows.extend(flatten_live_json(value, str(key)))
    elif isinstance(obj, list):
        for item in obj:
            rows.extend(flatten_live_json(item, group))
    return rows


def parse_playlist(text: str, default_group="采集直播"):
    rows, group, name = [], default_group, None
    lines = [line.strip() for line in text.replace("\ufeff", "").splitlines() if line.strip()]
    if any(line.startswith("#EXTM3U") for line in lines):
        for line in lines:
            if line.startswith("#EXTINF"):
                m = re.search(r'group-title="([^"]*)"', line)
                if m:
                    group = m.group(1) or default_group
                name = line.rsplit(",", 1)[-1].strip() if "," in line else "未命名频道"
            elif line.startswith(("http://", "https://")) and name:
                rows.append({"group": group, "name": name, "url": line})
                name = None
        return rows
    for line in lines:
        if line.startswith("#"):
            if line.lower().endswith(",#genre#"):
                group = line.rsplit(",", 1)[0].strip() or default_group
            continue
        parts = re.split(r"[,|]", line, maxsplit=2)
        if len(parts) == 2 and parts[1].strip().lower() == "#genre#":
            group = parts[0].strip() or default_group
            continue
        if len(parts) == 2 and parts[1].strip().startswith(("http://", "https://")):
            rows.append({"group": group, "name": parts[0].strip() or "未命名频道",
                         "url": parts[1].strip()})
        elif len(parts) == 3 and parts[2].strip().startswith(("http://", "https://")):
            rows.append({"group": parts[0].strip() or default_group,
                         "name": parts[1].strip() or "未命名频道", "url": parts[2].strip()})
    return rows
def fetch_live(record):
    started = time.monotonic()
    url = record.get("url", "")
    try:
        result = fetch_bytes(url, timeout=(4, 8), max_bytes=MAX_LIVE_BYTES, retries=1,
                             headers={"Accept": "application/vnd.apple.mpegurl, text/plain, */*"})
        if not 200 <= result.status_code < 300:
            return {**record, "status": "HTTP失败", "detail": f"HTTP {result.status_code}", "channels": 0}
        text = result.body.decode("utf-8-sig", "replace")
        rows = parse_playlist(text, str(record.get("name") or "采集直播"))
        if not rows:
            return {**record, "status": "无可识别频道", "detail": "响应不是可识别的 M3U/TXT 列表", "channels": 0}
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        out = LIVE_OUT / f"{digest}.m3u"
        write_m3u(out, rows)
        return {**record, "status": "已提取频道", "detail": "M3U/TXT 已解析", "channels": len(rows),
                "saved_file": out.relative_to(ROOT).as_posix(), "rows": rows}
    except (FetchError, OSError) as exc:
        return {**record, "status": "请求失败/安全拦截", "detail": str(exc), "channels": 0}


def write_m3u(path: Path, rows) -> None:
    lines = ["#EXTM3U"]
    for row in rows:
        group = str(row.get("group") or "未分组").replace('"', "'")
        name = str(row.get("name") or "未命名频道").replace("\n", " ").replace(",", "，")
        url = str(row.get("url") or "")
        lines.extend([f'#EXTINF:-1 group-title="{group}",{name}', url])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="只扫描本地配置，不请求外部 URL")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    docs = load_local_documents()
    sites, live_sources, py_sites, packages = extract_catalog(docs)

    # Include existing local M3U/TXT and JSON playlists already stored in this repository.
    live_rows = []
    for path in sorted(list(LIVE_DIR.glob("*.m3u")) + list(LIVE_DIR.glob("*.txt"))):
        try:
            live_rows.extend(parse_playlist(path.read_text(encoding="utf-8-sig", errors="replace"),
                                             path.stem))
        except OSError as exc:
            print(f"[WARN] 本地直播列表读取失败 {path.name}: {exc}")

    # Include existing local live JSON channel definitions in the aggregate.
    for path in sorted(LIVE_DIR.glob("*.json")):
        try:
            live_rows.extend(flatten_live_json(read_json(path)))
        except Exception as exc:
            print(f"[WARN] 直播 JSON 解析失败 {path.name}: {exc}")
    # Deduplicate channels by normalized URL, retaining first label/group.
    local_channels = {}
    for row in live_rows:
        local_channels.setdefault(canonical_url(row["url"]), row)
    live_rows = list(local_channels.values())

    API_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_OUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    COLLECTED.mkdir(parents=True, exist_ok=True)

    # Stable, deduplicated source lists for consumers.
    site_lines = ["# name|api"]
    for site in sites:
        site_lines.append(f'{str(site.get("name") or site.get("key") or "未命名").replace("|","/")}|{site["api"]}')
    (COLLECTED / "cjlist.txt").write_text("\n".join(site_lines) + "\n", encoding="utf-8")
    write_json(COLLECTED / "采集站聚合.json", {"sites": sites, "count": len(sites), "generated_at": NOW.isoformat()})

    py_lines = ["# name|python_url"]
    for site in py_sites:
        py_lines.append(f'{str(site.get("name") or site.get("key") or "未命名").replace("|","/")}|{site["api"]}')
    (COLLECTED / "pylist.txt").write_text("\n".join(py_lines) + "\n", encoding="utf-8")
    write_json(COLLECTED / "Py站聚合.json", {"sites": py_sites, "count": len(py_sites), "generated_at": NOW.isoformat()})

    package_rows = []
    for p in packages:
        url = p.get("url", "")
        status = "external"
        local_path = ""
        parsed = urlsplit(url)
        prefix = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/"
        if url.startswith(prefix):
            relative = "/".join(parsed.path.lstrip("/").split("/")[3:])
            candidate = (ROOT / unquote(relative)).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
                if candidate.is_file():
                    status = "local-file-present"
                    local_path = candidate.relative_to(ROOT).as_posix()
                else:
                    status = "local-file-missing"
            except ValueError:
                status = "unsafe-local-path"
        package_rows.append({
            "name": p.get("name"), "url": url, "source_file": p.get("source_file"),
            "resolution": status, "local_path": local_path
        })
    write_json(COLLECTED / "在线配置包索引.json", {
        "source": "local repository JSON only",
        "note": "仅索引本仓库配置中声明的远程入口；不下载或覆盖外部配置文件。",
        "packages": package_rows, "count": len(package_rows), "generated_at": NOW.isoformat()
    })

    # Local channels plus remotely declared playlist URLs.
    live_fetch_results = []
    if not args.offline:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = [pool.submit(fetch_live, r) for r in live_sources]
            for future in concurrent.futures.as_completed(futures):
                live_fetch_results.append(future.result())
                live_rows.extend(future.result().get("rows", []))
    unique_rows = {}
    for row in live_rows:
        unique_rows.setdefault(canonical_url(row["url"]), row)
    all_live = list(unique_rows.values())
    write_m3u(COLLECTED / "tvbox-live.m3u", all_live)
    txt = [f'{r["group"]},{r["name"]},{r["url"]}' for r in all_live]
    (COLLECTED / "livelist.txt").write_text("\n".join(txt) + ("\n" if txt else ""), encoding="utf-8")
    write_json(COLLECTED / "直播源聚合.json", {
        "lives": [{"name": "本仓库聚合直播", "type": 0, "channels": all_live}],
        "source_count": len(live_sources), "channel_count": len(all_live),
        "generated_at": NOW.isoformat()
    })

    api_results = []
    if not args.offline:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = [pool.submit(fetch_api, r) for r in sites]
            for future in concurrent.futures.as_completed(futures):
                api_results.append(future.result())
    else:
        api_results = [{**r, "status": "离线跳过", "http": "", "detail": "offline"} for r in sites]

    mirror_groups = {}
    for item in sites:
        mirror_key = str(item.get("key") or item.get("name") or "").strip().lower()
        if mirror_key:
            mirror_groups.setdefault(mirror_key, []).append(item["api"])
    mirror_groups = {
        key: sorted(set(urls)) for key, urls in mirror_groups.items()
        if len(set(urls)) > 1
    }

    api_index = {
        "generated_at": NOW.isoformat(), "source": "local repository config files only",
        "total_unique_apis": len(sites), "mirror_group_count": len(mirror_groups), "mirror_groups": mirror_groups, "results": api_results
    }
    write_json(API_INDEX, api_index)

    counts = Counter(r["status"] for r in api_results)
    live_counts = Counter(r["status"] for r in live_fetch_results)
    report = {
        "generated_at": NOW.isoformat(),
        "repository": "LDeom/TVBox-Config",
        "input_config_count": len(docs),
        "unique_site_api_count": len(sites), "mirror_group_count": len(mirror_groups),
        "unique_live_playlist_count": len(live_sources),
        "unique_py_site_count": len(py_sites),
        "online_package_reference_count": len(packages),
        "local_live_channel_count": len(local_channels),
        "aggregated_live_channel_count": len(all_live),
        "api_status_counts": dict(counts),
        "live_status_counts": dict(live_counts),
        "api_results": api_results,
        "live_results": [{k:v for k,v in r.items() if k != "rows"} for r in live_fetch_results],
        "safety": "private/local IP targets and unsafe redirects are blocked; failed fetches do not overwrite valid cached API files",
        "scope": "All source definitions originate from this repository; external URLs are fetched only when explicitly referenced by local configs."
    }
    write_json(REPORT_DIR / "source_pipeline_report.json", report)
    print(json.dumps({
        "input_configs": len(docs), "unique_apis": len(sites),
        "py_sites": len(py_sites), "live_playlists": len(live_sources),
        "live_channels": len(all_live), "packages_indexed": len(packages),
        "api_status": dict(counts), "live_status": dict(live_counts)
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
