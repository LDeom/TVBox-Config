#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create localized TVBox config copies and safely mirror referenced dependencies.

Original source configs are never modified. Owned repository files retain their
existing paths and are treated as source assets. Public third-party file
dependencies are cached below sources/dependencies/external/<host>/ and refreshed
in place after validation. No downloaded code is executed.
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
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from fetch_util import FetchError, fetch_bytes
from source_pipeline import strip_json_comments

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "sources" / "configs" / "vod"
OUTPUT_DIR = ROOT / "sources" / "collected" / "configs"
DEPENDENCY_ROOT = ROOT / "sources" / "dependencies"
EXTERNAL_DEPENDENCY_ROOT = DEPENDENCY_ROOT / "external"
REPORT_DIR = ROOT / "output" / "reports"
REPO_RAW = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/"
OWNED_REPOS = {("LDeom", "tvbox"), ("LDeom", "TVBox-Config")}
ALLOWED_EXTENSIONS = {
    ".js", ".jar", ".py", ".json", ".txt",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".zip", ".apk", ".node",
}
BLACKLIST_EXTENSIONS = {".m3u", ".m3u8", ".xml"}
MAX_DEPENDENCY_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_FILES = 20000
MAX_ARCHIVE_UNPACKED_BYTES = 128 * 1024 * 1024
URL_RE = re.compile(r"https?://[^\s\"'<>;$]+", re.I)
IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}
MACHO_SIGNATURES = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
}


def is_owned_github_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != "raw.githubusercontent.com":
            return False
        parts = [unquote(x) for x in p.path.strip("/").split("/")]
        return len(parts) >= 4 and (parts[0], parts[1]) in OWNED_REPOS
    except Exception:
        return False


def is_supported_dependency_url(url: str) -> bool:
    """Return whether a URL is a supported file dependency, not a playlist/XML."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        suffix = Path(unquote(parsed.path)).suffix.lower()
        return suffix in ALLOWED_EXTENSIONS and suffix not in BLACKLIST_EXTENSIONS
    except (TypeError, ValueError):
        return False


def owned_path(url: str):
    p = urlsplit(url)
    parts = [unquote(x) for x in p.path.strip("/").split("/")]
    if len(parts) < 4 or (parts[0], parts[1]) not in OWNED_REPOS:
        return None
    return parts[0], parts[1], parts[2], "/".join(parts[3:])


def _safe_relative_parts(raw_path: str) -> list[str] | None:
    decoded = unquote(raw_path)
    if not decoded or "\\" in decoded or "\x00" in decoded:
        return None
    path = PurePosixPath(decoded.lstrip("/"))
    parts = list(path.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if any(":" in part for part in parts):
        return None
    return parts


def dependency_target(url: str) -> Path | None:
    """Map a dependency URL to a stable, traversal-safe repository path."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    info = owned_path(url) if is_owned_github_url(url) else None
    if info:
        owner, repo, _branch, relative = info
        parts = _safe_relative_parts(relative)
        if not parts:
            return None
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS or suffix in BLACKLIST_EXTENSIONS:
            return None
        first = parts[0].lower()
        if suffix == ".jar" or first == "jar":
            sub = parts[1:] if first == "jar" else parts
            base = ROOT / "sources" / "jar"
        elif suffix == ".js" or first == "js":
            sub = parts[1:] if first == "js" else parts
            base = ROOT / "sources" / "js"
        elif suffix == ".py" or first == "py":
            sub = parts[1:] if first == "py" else parts
            base = ROOT / "sources" / "py"
        else:
            base = DEPENDENCY_ROOT / f"{owner}-{repo}"
            sub = parts[1:] if first in {"json", "lib", "xbpq"} else parts
        if not sub:
            return None
        target = (base.joinpath(*sub)).resolve()
    else:
        if not is_supported_dependency_url(url):
            return None
        parts = _safe_relative_parts(parsed.path)
        if not parts:
            return None
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS or suffix in BLACKLIST_EXTENSIONS:
            return None
        host = parsed.hostname.lower()
        if parsed.port:
            host = f"{host}-{parsed.port}"
        host = re.sub(r"[^a-z0-9.-]+", "-", host).strip(".-")
        if not host:
            return None
        target = (EXTERNAL_DEPENDENCY_ROOT / host).joinpath(*parts).resolve()

    try:
        target.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return target


def _validate_archive(body: bytes, *, require_class: bool = False,
                      require_apk_manifest: bool = False) -> None:
    with zipfile.ZipFile(BytesIO(body)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if not entries:
            raise ValueError("压缩包内没有文件")
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("压缩包文件数量超过限制")
        unpacked = sum(item.file_size for item in entries)
        if unpacked > MAX_ARCHIVE_UNPACKED_BYTES:
            raise ValueError("压缩包解压后总大小超过限制")
        if any(item.file_size > MAX_DEPENDENCY_BYTES for item in entries):
            raise ValueError("压缩包内单文件超过大小限制")
        names = {item.filename for item in entries}
        if require_class and not any(name.lower().endswith(".class") for name in names):
            raise ValueError("JAR 包内没有 class 文件")
        if require_apk_manifest and "AndroidManifest.xml" not in names:
            raise ValueError("APK 包内缺少 AndroidManifest.xml")
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"压缩包 CRC 校验失败：{bad_file}")


def validate_dependency(url: str, body: bytes) -> None:
    """Validate downloaded bytes by extension without executing downloaded code."""
    if not body or len(body) > MAX_DEPENDENCY_BYTES:
        raise ValueError("依赖文件为空或超过大小限制")
    suffix = Path(urlsplit(url).path).suffix.lower()

    if suffix == ".jar" or (suffix == ".txt" and body.startswith(b"PK\x03\x04")):
        if not body.startswith(b"PK\x03\x04"):
            raise ValueError("JAR 文件缺少 ZIP 文件头")
        _validate_archive(body, require_class=True)
    elif suffix == ".apk":
        if not body.startswith(b"PK\x03\x04"):
            raise ValueError("APK 文件缺少 ZIP 文件头")
        _validate_archive(body, require_apk_manifest=True)
    elif suffix == ".zip":
        if not body.startswith(b"PK\x03\x04"):
            raise ValueError("ZIP 文件缺少 ZIP 文件头")
        _validate_archive(body)
    elif suffix in IMAGE_SIGNATURES:
        signatures = IMAGE_SIGNATURES[suffix]
        if not any(body.startswith(signature) for signature in signatures):
            raise ValueError(f"{suffix} 图片文件签名不正确")
        if suffix == ".webp" and (len(body) < 12 or body[8:12] != b"WEBP"):
            raise ValueError("WEBP 文件头不正确")
    elif suffix == ".node":
        valid = body.startswith(b"\x7fELF") or body.startswith(b"MZ")
        valid = valid or body[:4] in MACHO_SIGNATURES
        if not valid:
            raise ValueError("NODE 原生模块不是可识别的 ELF/PE/Mach-O 文件")
    elif suffix == ".json":
        json.loads(strip_json_comments(body.decode("utf-8-sig")))
    elif suffix in {".js", ".py", ".txt"}:
        body.decode("utf-8-sig")
    else:
        raise ValueError(f"不支持的依赖类型：{suffix}")


def find_existing_owned_file(url: str) -> Path | None:
    info = owned_path(url)
    if not info:
        return None
    _owner, _repo, _branch, relative = info
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
    result = []
    seen = set()
    for url in found:
        if is_supported_dependency_url(url) and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def dependency_urls(config: dict) -> list[str]:
    """Collect file dependencies from supported TVBox fields."""
    values = []
    for field in ("spider", "wallpaper", "logo", "homeLogo", "homeBg"):
        if field in config:
            values.append(config[field])
    sites = config.get("sites")
    if isinstance(sites, list):
        for site in sites:
            if isinstance(site, dict):
                for field in ("api", "jar", "ext", "logo"):
                    if field in site:
                        values.append(site[field])
    for section in ("parses", "rules"):
        rows = config.get(section)
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict):
                    for field in ("url", "ext", "jar"):
                        if field in item:
                            values.append(item[field])
    result, seen = [], set()
    for value in values:
        for url in extract_dependency_urls(value):
            if url not in seen:
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
    return replace_urls(clone, replacements)


def _atomic_write(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(body)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def fetch_dependency(url: str, target: Path, *, refresh: bool) -> tuple[str, str]:
    """Fetch and validate a dependency; atomically replace only its cache file."""
    if not is_supported_dependency_url(url):
        return "路径或文件类型不支持", "URL 后缀不在白名单或属于黑名单"
    try:
        result = fetch_bytes(
            url, timeout=(5, 15), max_bytes=MAX_DEPENDENCY_BYTES,
            retries=2, headers={"Accept": "application/octet-stream, */*"},
        )
        if not 200 <= result.status_code < 300:
            raise FetchError(f"HTTP {result.status_code}")
        validate_dependency(url, result.body)
        if target.exists() and not refresh:
            return "目标文件已存在未覆盖", "按保守模式保留现有文件"
        _atomic_write(target, result.body)
        return "依赖已下载并覆盖" if refresh else "新依赖已下载", f"{len(result.body)} bytes"
    except (FetchError, ValueError, OSError, zipfile.BadZipFile) as exc:
        return "下载失败", str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3,
                        help="保留参数兼容；按序处理以保证稳定审计和路径覆盖")
    parser.add_argument("--no-refresh", action="store_true",
                        help="不刷新已经存在的外部依赖缓存")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    configs = sorted(CONFIG_DIR.glob("*.json"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": "LDeom/TVBox-Config",
        "source_policy": (
            "仅读取 sources/configs/vod；原始配置不修改。LDeom 自有仓库依赖沿用原路径；"
            "公开第三方文件依赖缓存到 sources/dependencies/external/<host>/，"
            "每日校验后覆盖同一路径；不执行 JS/PY/JAR/NODE。"
        ),
        "config_count": len(configs),
        "dependency_url_count": 0,
        "status_counts": {},
        "dependencies": [],
        "generated_configs": [],
    }
    replacements: dict[str, str] = {}
    processed_urls: set[str] = set()
    dependency_rows = []

    for config_path in configs:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            dependency_rows.append({
                "source_config": config_path.name, "status": "配置解析失败",
                "detail": str(exc),
            })
            continue
        if not isinstance(config, dict):
            dependency_rows.append({
                "source_config": config_path.name, "status": "配置结构不支持",
            })
            continue

        for url in dependency_urls(config):
            if url in processed_urls:
                continue
            processed_urls.add(url)
            owned = is_owned_github_url(url)
            target = dependency_target(url)
            if target is None:
                dependency_rows.append({
                    "source_config": config_path.name, "url": url,
                    "status": "路径或文件类型不支持",
                })
                continue

            if owned:
                existing = find_existing_owned_file(url)
                if existing:
                    replacements[url] = local_raw_url(existing)
                    dependency_rows.append({
                        "source_config": config_path.name, "url": url,
                        "local_path": existing.relative_to(ROOT).as_posix(),
                        "local_url": replacements[url], "status": "仓库已有依赖",
                    })
                    continue
                status, detail = fetch_dependency(url, target, refresh=False)
            else:
                # Third-party dependencies are mirrored only when the URL is a
                # public HTTP(S) file URL on the explicit extension allowlist.
                status, detail = fetch_dependency(
                    url, target, refresh=not args.no_refresh
                )
                if status == "下载失败" and target.is_file():
                    replacements[url] = local_raw_url(target)
                    dependency_rows.append({
                        "source_config": config_path.name, "url": url,
                        "local_path": target.relative_to(ROOT).as_posix(),
                        "local_url": replacements[url], "status": "更新失败保留旧缓存",
                        "detail": detail,
                    })
                    continue

            if status in {"新依赖已下载", "依赖已下载并覆盖"}:
                replacements[url] = local_raw_url(target)
                dependency_rows.append({
                    "source_config": config_path.name, "url": url,
                    "local_path": target.relative_to(ROOT).as_posix(),
                    "local_url": replacements[url], "status": status,
                    "detail": detail,
                })
            else:
                dependency_rows.append({
                    "source_config": config_path.name, "url": url,
                    "status": status, "detail": detail,
                })

    generated = []
    for config_path in configs:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                continue
            localized = localize_config(config, replacements)
            target = OUTPUT_DIR / config_path.name
            payload = json.dumps(localized, ensure_ascii=False, indent=2) + "\n"
            json.loads(payload)
            target.write_text(payload, encoding="utf-8")
            generated.append({
                "source": config_path.relative_to(ROOT).as_posix(),
                "output": target.relative_to(ROOT).as_posix(),
                "localized_dependency_count": sum(
                    1 for url in dependency_urls(config) if url in replacements
                ),
            })
        except Exception as exc:
            generated.append({
                "source": config_path.relative_to(ROOT).as_posix(),
                "status": "生成失败", "detail": str(exc),
            })

    report["dependency_url_count"] = len({
        row.get("url") for row in dependency_rows if row.get("url")
    })
    report["status_counts"] = dict(Counter(
        row.get("status", "未知") for row in dependency_rows
    ))
    report["dependencies"] = dependency_rows
    report["generated_configs"] = generated
    report_path = REPORT_DIR / "config_localization_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "config_count": len(configs),
        "generated_config_count": sum(1 for row in generated if "output" in row),
        "dependency_url_count": report["dependency_url_count"],
        "status_counts": report["status_counts"],
        "external_dependency_root": EXTERNAL_DEPENDENCY_ROOT.relative_to(ROOT).as_posix(),
        "report": report_path.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
