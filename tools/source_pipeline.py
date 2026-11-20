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

from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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
MAX_LIVE_UNWRAP_DEPTH = 5
MAX_PACKAGE_BYTES = 4 * 1024 * 1024
PACKAGE_DIR = COLLECTED / "packages"
PACKAGE_HISTORY = ROOT / "output" / "history" / "packages"
RY_LINKS_FILE = ROOT / "rylinks.txt"
MAX_HISTORY_FILES = 5
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
    raw = unwrap_response(raw)
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
def parse_ry_links(text: str):
    records, seen = [], set()
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            name, url = line.split("|", 1)
        elif "," in line:
            name, url = line.split(",", 1)
        else:
            name, url = "", line
        name, url = name.strip(), url.strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        if not name:
            name = Path(urlsplit(url).path).name or f"package-{number}"
        records.append({"name": name, "url": url, "line": number})
    return records


def load_ry_links():
    if not RY_LINKS_FILE.is_file():
        return []
    return parse_ry_links(RY_LINKS_FILE.read_text(encoding="utf-8-sig"))


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


def aes128_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if len(key) != 16 or len(iv) != 16 or not ciphertext or len(ciphertext) % 16:
        raise ValueError("AES-128-CBC 密钥、IV 或密文长度无效")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = crypto_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def decode_2423(text: str) -> bytes:
    stripped = re.sub(r"\s+", " ", text).strip()
    if not stripped.startswith("2423") or "2324" not in stripped:
        raise ValueError("不是 2423 包装")
    # Hex variant used by the TVBox API downloader.
    try:
        p1, p2 = stripped.index("2423"), stripped.index("2324")
        key_raw_hex = stripped[p1 + 4:p2]
        try:
            key_raw = bytes.fromhex(key_raw_hex).decode("latin-1")
        except Exception:
            key_raw = key_raw_hex
        key = (key_raw + "0" * 16)[:16].encode("utf-8")[:16]
        data_start, data_end = p2 + 4, len(stripped) - 26
        if data_end <= data_start:
            raise ValueError("2423 hex 数据区间非法")
        data_hex = stripped[data_start:data_end]
        ts_hex = stripped[-26:]
        try:
            iv_raw = bytes.fromhex(ts_hex).decode("latin-1")
        except Exception:
            iv_raw = ts_hex
        iv = (iv_raw + "0" * 16)[:16].encode("utf-8")[:16]
        return aes128_cbc_decrypt(bytes.fromhex(data_hex), key, iv)
    except Exception as hex_error:
        # Plain variant marked with $#key#$ and a trailing 13-char IV seed.
        try:
            p2, p_dollar, p_sharp = stripped.index("2324"), stripped.index("$#"), stripped.index("#$")
            data_hex = re.sub(r"[^0-9a-fA-F]", "", stripped[p2 + 4:p_dollar])
            if len(data_hex) % 2:
                data_hex = data_hex[:-1]
            key = (stripped[p_dollar + 2:p_sharp] + "0" * 16)[:16].encode("latin-1")[:16]
            iv = (stripped[-13:] + "0" * 16)[:16].encode("latin-1")[:16]
            return aes128_cbc_decrypt(bytes.fromhex(data_hex), key, iv)
        except Exception as plain_error:
            raise ValueError(f"2423 解密失败：{hex_error}; {plain_error}") from plain_error


def unwrap_response(body: bytes, depth=0) -> bytes:
    if depth > 6:
        return body
    raw = body.strip()
    if raw.startswith(b"\x1f\x8b"):
        return unwrap_response(gzip.decompress(raw), depth + 1)
    text = raw.decode("utf-8-sig", "replace").strip()
    if text.startswith("2423") and "2324" in text:
        return unwrap_response(decode_2423(text), depth + 1)
    # Some APIs prepend a short marker followed by a Base64 payload.
    star = raw.find(b"**")
    if star >= 8:
        encoded = bytes(ch for ch in raw[star + 2:] if ch not in b" \t\r\n")
        try:
            return unwrap_response(base64.b64decode(encoded + b"=="), depth + 1)
        except Exception:
            pass
    compact = re.sub(rb"\s+", b"", raw)
    if len(compact) >= 16 and re.fullmatch(rb"[A-Za-z0-9+/]+={0,2}", compact):
        try:
            decoded = base64.b64decode(compact + b"==")
            marker = decoded.lstrip()
            if marker.startswith((b"{", b"[", b"\x1f\x8b", b"2423")) or b"**" in decoded[:32]:
                return unwrap_response(decoded, depth + 1)
        except Exception:
            pass
    return body


def valid_vod_payload(body: bytes):
    body = unwrap_response(body)
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


def classify_fetch_error(exc) -> str:
    message = str(exc)
    security_markers = ("拒绝", "不允许", "非公网 IP", "本机", "局域网", "重定向次数")
    return "安全拦截" if any(marker in message for marker in security_markers) else "请求失败"


def archive_previous_cache(path: Path, digest: str) -> None:
    if not path.is_file():
        return
    backup_dir = HISTORY / digest
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{stamp()}_{path.name}"
    backup.write_bytes(path.read_bytes())
    previous = sorted(backup_dir.glob("*"), key=lambda item: item.name)
    for old in previous[:-MAX_HISTORY_FILES]:
        old.unlink(missing_ok=True)


def fetch_api(record):
    url = request_api_url(record)
    started = time.monotonic()
    digest = hashlib.sha256(record["api"].encode()).hexdigest()[:16]
    cached_files = [API_DIR / f"{digest}.json", API_DIR / f"{digest}.xml"]
    cached = next((path for path in cached_files if path.is_file()), None)

    def attach_cache(result):
        if cached and cached.is_file():
            result["saved_file"] = cached.relative_to(ROOT).as_posix()
            result["cached_previous"] = True
        return result

    try:
        result = fetch_bytes(url, timeout=(4, 8), max_bytes=MAX_API_BYTES, retries=1)
        if not 200 <= result.status_code < 300:
            return attach_cache({
                **record, "status": "HTTP失败", "http": result.status_code,
                "seconds": round(time.monotonic()-started, 2), "detail": "非 2xx"
            })
        obj, status, detail = valid_vod_payload(result.body)
        if obj is None:
            return attach_cache({
                **record, "status": status, "http": result.status_code,
                "seconds": round(time.monotonic()-started, 2), "detail": detail
            })
        ext = "xml" if isinstance(obj, str) else "json"
        target = API_DIR / f"{digest}.{ext}"
        payload = (obj.rstrip() + "\n") if isinstance(obj, str) else (
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        )
        new_bytes = payload.encode("utf-8")
        for old_path in cached_files:
            if old_path.is_file() and (old_path != target or old_path.read_bytes() != new_bytes):
                archive_previous_cache(old_path, digest)
                if old_path != target:
                    old_path.unlink(missing_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new_bytes)
        return {
            **record, "status": status, "http": result.status_code,
            "seconds": round(time.monotonic()-started, 2), "detail": detail,
            "saved_file": target.relative_to(ROOT).as_posix(),
            "final_url": result.url, "cached_previous": False
        }
    except (FetchError, ValueError, OSError, ET.ParseError) as exc:
        return attach_cache({
            **record, "status": classify_fetch_error(exc), "http": "",
            "seconds": round(time.monotonic()-started, 2), "detail": str(exc)
        })


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
def single_wrapper_url(text: str, current_url: str) -> str:
    """Return the only URL in a wrapper response, if it is not a self-reference."""
    urls = []
    for raw_url in URL_RE.findall(text):
        candidate = raw_url.rstrip("),;")
        if candidate and candidate not in urls:
            urls.append(candidate)
    if len(urls) != 1:
        return ""
    candidate = urls[0]
    if not candidate.startswith(("http://", "https://")):
        return ""
    if canonical_url(candidate) == canonical_url(current_url):
        return ""
    return candidate


def fetch_live_playlist(url: str, default_group="采集直播", chain=None, fetcher=None):
    """Fetch a playlist and safely unwrap URL-only wrapper responses."""
    chain = list(chain or [])
    fetcher = fetcher or fetch_bytes
    current_key = canonical_url(url)
    if current_key in chain:
        return {"status": "递归循环", "detail": "直播列表 URL 出现循环引用",
                "rows": [], "final_url": url, "chain": chain}
    if len(chain) >= MAX_LIVE_UNWRAP_DEPTH:
        return {"status": "递归层数超限", "detail": f"超过 {MAX_LIVE_UNWRAP_DEPTH} 层穿透限制",
                "rows": [], "final_url": url, "chain": chain}
    try:
        result = fetcher(
            url, timeout=(4, 8), max_bytes=MAX_LIVE_BYTES, retries=1,
            headers={"Accept": "application/vnd.apple.mpegurl, text/plain, */*"}
        )
    except (FetchError, OSError) as exc:
        return {"status": classify_fetch_error(exc), "detail": str(exc),
                "rows": [], "final_url": url, "chain": chain}
    if not 200 <= result.status_code < 300:
        return {"status": "HTTP失败", "detail": f"HTTP {result.status_code}",
                "rows": [], "final_url": result.url, "http": result.status_code,
                "chain": chain + [current_key]}

    next_chain = chain + [current_key]
    text = result.body.decode("utf-8-sig", "replace")
    rows = parse_playlist(text, default_group)
    if rows:
        return {"status": "已提取频道", "detail": "M3U/TXT 已解析",
                "rows": rows, "final_url": result.url, "http": result.status_code,
                "chain": next_chain}
    wrapper_url = single_wrapper_url(text, url)
    if wrapper_url:
        if canonical_url(wrapper_url) in next_chain:
            return {"status": "递归循环", "detail": "直播列表 URL 出现循环引用",
                    "rows": [], "final_url": result.url, "http": result.status_code,
                    "chain": next_chain + [canonical_url(wrapper_url)]}
        return fetch_live_playlist(wrapper_url, default_group, next_chain, fetcher)
    return {"status": "无可识别频道", "detail": "响应不是可识别的 M3U/TXT 列表或单 URL 套壳",
            "rows": [], "final_url": result.url, "http": result.status_code,
            "chain": next_chain}


def fetch_live(record):
    started = time.monotonic()
    url = record.get("url", "")
    try:
        result = fetch_live_playlist(url, str(record.get("name") or "采集直播"))
        rows = result["rows"]
        if not rows:
            return {
                **record, "status": result["status"], "detail": result["detail"],
                "channels": 0, "final_url": result.get("final_url", url),
                "unwrap_chain": result.get("chain", []),
                "unwrap_depth": max(0, len(result.get("chain", [])) - 1),
                "seconds": round(time.monotonic() - started, 2)
            }
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        out = LIVE_OUT / f"{digest}.m3u"
        write_m3u(out, rows)
        return {
            **record, "status": "已提取频道", "detail": result["detail"],
            "channels": len(rows), "saved_file": out.relative_to(ROOT).as_posix(),
            "final_url": result.get("final_url", url),
            "unwrap_chain": result.get("chain", []),
            "unwrap_depth": max(0, len(result.get("chain", [])) - 1),
            "seconds": round(time.monotonic() - started, 2), "rows": rows
        }
    except (FetchError, OSError) as exc:
        return {**record, "status": classify_fetch_error(exc), "detail": str(exc), "channels": 0}


def parse_package_json(body: bytes):
    raw = unwrap_response(body)
    text = raw.decode("utf-8-sig", "replace").strip()
    if not text:
        raise ValueError("在线包响应为空")
    try:
        obj = json.loads(strip_json_comments(text))
    except Exception:
        obj = None
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                candidate, _ = decoder.raw_decode(text[index:])
                if isinstance(candidate, (dict, list)) and candidate:
                    obj = candidate
                    break
            except Exception:
                continue
        if obj is None:
            raise ValueError("响应中没有可解析的 JSON 配置")
    if not isinstance(obj, (dict, list)) or not obj:
        raise ValueError("在线包 JSON 为空或顶层结构不受支持")
    return obj


def fetch_online_package(record):
    started = time.monotonic()
    digest = hashlib.sha256(record["url"].encode()).hexdigest()[:16]
    target = PACKAGE_DIR / f"{digest}.json"
    try:
        result = fetch_bytes(
            record["url"], timeout=(4, 8), max_bytes=MAX_PACKAGE_BYTES, retries=1,
            headers={"Accept": "application/json, text/plain, */*"}
        )
        if not 200 <= result.status_code < 300:
            return {**record, "status": "HTTP失败", "http": result.status_code,
                    "seconds": round(time.monotonic()-started, 2)}
        obj = parse_package_json(result.body)
        payload = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if target.is_file() and target.read_bytes() != payload:
            backup_dir = PACKAGE_HISTORY / digest
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{stamp()}.json").write_bytes(target.read_bytes())
            previous = sorted(backup_dir.glob("*.json"), key=lambda item: item.name)
            for old in previous[:-MAX_HISTORY_FILES]:
                old.unlink(missing_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return {
            **record, "status": "在线包 JSON 已解析", "http": result.status_code,
            "seconds": round(time.monotonic()-started, 2),
            "saved_file": target.relative_to(ROOT).as_posix(),
            "top_level_keys": list(obj.keys())[:30] if isinstance(obj, dict) else [],
            "embedded_urls": len(set(urls_in(obj)))
        }
    except (FetchError, ValueError, OSError) as exc:
        cached = target.relative_to(ROOT).as_posix() if target.is_file() else ""
        return {
            **record, "status": classify_fetch_error(exc), "http": "",
            "seconds": round(time.monotonic()-started, 2), "detail": str(exc),
            "saved_file": cached, "cached_previous": bool(cached)
        }


def group_live_channels(rows):
    groups = {}
    for row in rows:
        group = str(row.get("group") or "未分组")
        groups.setdefault(group, []).append({
            "name": str(row.get("name") or "未命名频道"),
            "urls": [str(row.get("url") or "")]
        })
    return [{"name": name, "channel": channels} for name, channels in groups.items()]

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
    write_json(COLLECTED / "海量采集聚合接口.json", {"sites": sites, "count": len(sites), "generated_at": NOW.isoformat()})

    py_lines = ["# name|python_url"]
    for site in py_sites:
        py_lines.append(f'{str(site.get("name") or site.get("key") or "未命名").replace("|","/")}|{site["api"]}')
    (COLLECTED / "pylist.txt").write_text("\n".join(py_lines) + "\n", encoding="utf-8")
    write_json(COLLECTED / "Py站聚合.json", {"sites": py_sites, "count": len(py_sites), "generated_at": NOW.isoformat()})
    write_json(COLLECTED / "海量py聚合接口.json", {"sites": py_sites, "count": len(py_sites), "generated_at": NOW.isoformat()})

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

    ry_links = load_ry_links()
    if not args.offline and ry_links:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            package_futures = [pool.submit(fetch_online_package, item) for item in ry_links]
            package_results = [future.result() for future in concurrent.futures.as_completed(package_futures)]
    else:
        package_results = [
            {**item, "status": "离线跳过" if args.offline else "无待处理链接"}
            for item in ry_links
        ]
    write_json(COLLECTED / "online_package_download_index.json", {
        "source_file": "rylinks.txt",
        "input_count": len(ry_links),
        "results": package_results,
        "note": "只解析显式清单中的 JSON 在线包；不执行远程代码，也不覆盖点播/直播源配置。"
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
    txt = [
        f'{str(r["group"]).replace(",", "，")},{str(r["name"]).replace(",", "，")},{r["url"]}'
        for r in all_live
    ]
    (COLLECTED / "livelist.txt").write_text("\n".join(txt) + ("\n" if txt else ""), encoding="utf-8")
    write_json(COLLECTED / "live.json", group_live_channels(all_live))
    write_json(COLLECTED / "直播源聚合.json", {
        "lives": [{
            "name": "TVBox-Config 本地聚合直播",
            "type": 0,
            "url": "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/collected/tvbox-live.m3u",
            "playerType": 1
        }],
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

    result_by_url = {item.get("api"): item for item in api_results}
    mirror_health = {
        key: [
            {
                "url": url,
                "status": result_by_url.get(url, {}).get("status", "未检测"),
                "http": result_by_url.get(url, {}).get("http", "")
            }
            for url in urls
        ]
        for key, urls in mirror_groups.items()
    }

    api_index = {
        "generated_at": NOW.isoformat(), "source": "local repository config files only",
        "total_unique_apis": len(sites), "mirror_group_count": len(mirror_groups), "mirror_groups": mirror_groups, "mirror_health": mirror_health, "results": api_results
    }
    write_json(API_INDEX, api_index)

    counts = Counter(r["status"] for r in api_results)
    live_counts = Counter(r["status"] for r in live_fetch_results)
    report = {
        "generated_at": NOW.isoformat(),
        "repository": "LDeom/TVBox-Config",
        "input_config_count": len(docs),
        "unique_site_api_count": len(sites), "mirror_group_count": len(mirror_groups), "mirror_health": mirror_health,
        "unique_live_playlist_count": len(live_sources),
        "unique_py_site_count": len(py_sites),
        "online_package_reference_count": len(packages),
        "ry_package_link_count": len(ry_links),
        "ry_package_status_counts": dict(Counter(r.get("status", "") for r in package_results)),
        "ry_package_results": package_results,
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
        "live_channels": len(all_live), "packages_indexed": len(packages), "ry_package_links": len(ry_links),
        "api_status": dict(counts), "live_status": dict(live_counts)
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
