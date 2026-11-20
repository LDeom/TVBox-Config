#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create local TVBox config copies and localize explicitly referenced owned dependencies.

Original source JSON files are never modified. Only URLs pointing to LDeom-owned
GitHub repositories are eligible for localization/download. Existing dependency
files are immutable by default; missing files are fetched once and validated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fetch_util import FetchError, fetch_bytes
from source_pipeline import strip_json_comments

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "sources" / "configs" / "vod"
OUTPUT_DIR = ROOT / "sources" / "collected" / "configs"
DEPENDENCY_ROOT = ROOT / "sources" / "dependencies"
HISTORY_DIR = ROOT / "output" / "history" / "dependencies"
REPORT_DIR = ROOT / "output" / "reports"
REPO_RAW = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/"
OWNED_REPOS = {("LDeom", "tvbox"), ("LDeom", "TVBox-Config")}
ALLOWED_EXTENSIONS = {".js", ".jar", ".py", ".json", ".txt"}
MAX_DEPENDENCY_BYTES = 8 * 1024 * 1024
URL_RE = re.compile(r"https?://[^\s\"'<>;$]+", re.I)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def is_owned_github_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != "raw.githubusercontent.com":
            return False
        parts = [unquote(x) for x in p.path.strip("/").split("/")]
        return len(parts) >= 4 and (parts[0], parts[1]) in OWNED_REPOS
    except Exception:
        return False


def owned_path(url: str):
    p = urlsplit(url)
    parts = [unquote(x) for x in p.path.strip("/").split("/")]
    if len(parts) < 4 or (parts[0], parts[1]) not in OWNED_REPOS:
        return None
    return parts[0], parts[1], parts[2], "/".join(parts[3:])


def dependency_target(url: str) -> Path | None:
    info = owned_path(url)
    if not info:
        return None
    owner, repo, _branch, relative = info
    suffix = Path(relative).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return None
    safe_parts = [part for part in Path(relative).parts if part not in ("", ".", "..")]
    if not safe_parts:
        return None
    first = safe_parts[0].lower()
    if suffix == ".jar" or first == "jar":
        sub = safe_parts[1:] if first == "jar" else safe_parts
        base = ROOT / "sources" / "jar"
    elif suffix == ".js" or first == "js":
        sub = safe_parts[1:] if first == "js" else safe_parts
        base = ROOT / "sources" / "js"
    elif suffix == ".py" or first == "py":
        sub = safe_parts[1:] if first == "py" else safe_parts
        base = ROOT / "sources" / "py"
    else:
        sub = safe_parts
        base = DEPENDENCY_ROOT / f"{owner}-{repo}" / first if first in {"json", "lib", "xbpq", "xBPQ".lower()} else DEPENDENCY_ROOT / f"{owner}-{repo}"
        if first in {"json", "lib", "xbpq"}:
            sub = safe_parts[1:]
    if not sub:
        return None
    target = (base.joinpath(*sub)).resolve()
    try:
        target.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return target


def validate_dependency(url: str, body: bytes) -> None:
    if not body or len(body) > MAX_DEPENDENCY_BYTES:
        raise ValueError("依赖文件为空或超过大小限制")
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix == ".jar" or (suffix == ".txt" and body.startswith(b"PK\x03\x04")):
        if not body.startswith(b"PK\x03\x04"):
            raise ValueError("JAR 文件缺少 ZIP 文件头")
        with zipfile.ZipFile(BytesIO(body)) as archive:
            names = archive.namelist()
            if not names or not any(name.endswith(".class") for name in names):
                raise ValueError("JAR 包内没有 class 文件")
    elif suffix == ".json":
        json.loads(strip_json_comments(body.decode("utf-8-sig")) )
    elif suffix in {".js", ".py", ".txt"}:
        body.decode("utf-8-sig")
    else:
        raise ValueError(f"不支持的依赖类型：{suffix}")


def find_existing_owned_file(url: str) -> Path | None:
    info = owned_path(url)
    if not info:
        return None
    _owner, _repo, branch, relative = info
    # First honor the exact path represented by this repository's own raw URL.
    if _repo == "TVBox-Config":
        candidate = (ROOT / relative).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
            if candidate.is_file():
                return candidate
        except ValueError:
            pass
    target = dependency_target(url)
    if target and target.is_file():
        return target
    return None


def local_raw_url(path: Path) -> str:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    return REPO_RAW + quote(relative, safe="/")


def extract_dependency_urls(value) -> list[str]:
    found = []
    if isinstance(value, str):
        found.extend(URL_RE.findall(value))
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(extract_dependency_urls(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(extract_dependency_urls(child))
    return found


def dependency_urls(config: dict) -> list[str]:
    values = []
    spider = config.get("spider")
    if isinstance(spider, str):
        values.append(spider)
    sites = config.get("sites")
    if isinstance(sites, list):
        for site in sites:
            if not isinstance(site, dict):
                continue
            for field in ("api", "jar", "ext"):
                if field in site:
                    values.append(site[field])
    parses = config.get("parses")
    if isinstance(parses, list):
        for item in parses:
            if isinstance(item, dict):
                for field in ("url", "ext"):
                    if field in item:
                        values.append(item[field])
    rules = config.get("rules")
    if isinstance(rules, list):
        for item in rules:
            if isinstance(item, dict):
                for field in ("url", "ext", "jar"):
                    if field in item:
                        values.append(item[field])
    result = []
    seen = set()
    for value in values:
        for url in extract_dependency_urls(value):
            if url not in seen and Path(urlsplit(url).path).suffix.lower() in ALLOWED_EXTENSIONS:
                seen.add(url)
                result.append(url)
    return result


def replace_urls(value, replacements: dict[str, str]):
    if isinstance(value, str):
        return URL_RE.sub(lambda match: replacements.get(match.group(0), match.group(0)), value)
    if isinstance(value, list):
        return [replace_urls(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace_urls(item, replacements) for key, item in value.items()}
    return value


def localize_config(config: dict, replacements: dict[str, str]) -> dict:
    clone = json.loads(json.dumps(config, ensure_ascii=False))
    if isinstance(clone.get("spider"), str):
        clone["spider"] = replace_urls(clone["spider"], replacements)
    for field in ("sites", "parses", "rules"):
        rows = clone.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            fields = ("api", "jar", "ext") if field == "sites" else ("url", "ext", "jar")
            for key in fields:
                if key in row:
                    row[key] = replace_urls(row[key], replacements)
    return clone


def fetch_missing_dependency(url: str, target: Path) -> tuple[str, str]:
    if not is_owned_github_url(url):
        return "外部依赖保留", "来源不是 LDeom 名下的 raw.githubusercontent.com 地址"
    try:
        result = fetch_bytes(url, timeout=(5, 15), max_bytes=MAX_DEPENDENCY_BYTES,
                             retries=1, headers={"Accept": "application/octet-stream, */*"})
        if not 200 <= result.status_code < 300:
            return "下载失败", f"HTTP {result.status_code}"
        validate_dependency(url, result.body)
        if target.exists():
            return "目标文件已存在未覆盖", "保留仓库已有文件"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.body)
        return "新依赖已下载", f"{len(result.body)} bytes"
    except (FetchError, ValueError, OSError, zipfile.BadZipFile) as exc:
        return "下载失败", str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3, help="保留参数兼容；依赖按序下载以便稳定审计")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    configs = sorted(CONFIG_DIR.glob("*.json"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": "LDeom/TVBox-Config",
        "source_policy": "仅读取本仓库 sources/configs/vod；不下载外部完整配置、不修改原始 JSON、不覆盖已有依赖",
        "config_count": len(configs),
        "dependency_url_count": 0,
        "status_counts": {},
        "dependencies": [],
        "generated_configs": [],
    }
    replacements = {}
    dependency_rows = []
    for config_path in configs:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            dependency_rows.append({"source_config": config_path.name, "status": "配置解析失败", "detail": str(exc)})
            continue
        if not isinstance(config, dict):
            dependency_rows.append({"source_config": config_path.name, "status": "配置结构不支持"})
            continue
        for url in dependency_urls(config):
            if url in replacements:
                continue
            if not is_owned_github_url(url):
                dependency_rows.append({"source_config": config_path.name, "url": url,
                                        "status": "外部依赖保留", "detail": "仅自动本地化 LDeom 自有 GitHub 原始文件"})
                continue
            existing = find_existing_owned_file(url)
            if existing:
                replacements[url] = local_raw_url(existing)
                dependency_rows.append({"source_config": config_path.name, "url": url,
                                        "local_path": existing.relative_to(ROOT).as_posix(),
                                        "local_url": replacements[url], "status": "仓库已有依赖"})
                continue
            target = dependency_target(url)
            if target is None:
                dependency_rows.append({"source_config": config_path.name, "url": url,
                                        "status": "路径或文件类型不支持"})
                continue
            status, detail = fetch_missing_dependency(url, target)
            if status == "新依赖已下载":
                replacements[url] = local_raw_url(target)
                dependency_rows.append({"source_config": config_path.name, "url": url,
                                        "local_path": target.relative_to(ROOT).as_posix(),
                                        "local_url": replacements[url], "status": status, "detail": detail})
            else:
                dependency_rows.append({"source_config": config_path.name, "url": url,
                                        "status": status, "detail": detail})

    generated = []
    for config_path in configs:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                continue
            localized = localize_config(config, replacements)
            target = OUTPUT_DIR / config_path.name
            payload = json.dumps(localized, ensure_ascii=False, indent=2) + "
"
            # Validate the generated document before writing it.
            json.loads(payload)
            target.write_text(payload, encoding="utf-8")
            generated.append({"source": config_path.relative_to(ROOT).as_posix(),
                              "output": target.relative_to(ROOT).as_posix(),
                              "localized_dependency_count": sum(1 for u in dependency_urls(config) if u in replacements)})
        except Exception as exc:
            generated.append({"source": config_path.relative_to(ROOT).as_posix(), "status": "生成失败", "detail": str(exc)})

    report["dependency_url_count"] = len({row.get("url") for row in dependency_rows if row.get("url")})
    report["status_counts"] = dict(Counter(row.get("status", "未知") for row in dependency_rows))
    report["dependencies"] = dependency_rows
    report["generated_configs"] = generated
    report_path = REPORT_DIR / "config_localization_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "
", encoding="utf-8")
    print(json.dumps({
        "config_count": len(configs),
        "generated_config_count": sum(1 for row in generated if "output" in row),
        "dependency_url_count": report["dependency_url_count"],
        "status_counts": report["status_counts"],
        "report": report_path.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
