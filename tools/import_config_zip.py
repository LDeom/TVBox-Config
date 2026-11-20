#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely validate and stage a TVBox resource ZIP without merging it into sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath

from fetch_util import fetch_bytes

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "imports" / "staging"
MANIFEST = STAGING / "manifest.json"
REPORT = ROOT / "output" / "reports" / "zip_import_report.json"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES = 200
MAX_RATIO = 100
ALLOWED_SUFFIXES = {
    ".json", ".txt", ".m3u", ".m3u8", ".xml", ".js", ".py",
    ".jar", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md",
}
BLOCKED_SUFFIXES = {
    ".apk", ".exe", ".dll", ".so", ".bat", ".cmd", ".sh", ".ps1",
    ".com", ".msi", ".deb", ".rpm",
}


class ZipImportError(ValueError):
    pass


def validate_member(info: zipfile.ZipInfo) -> str | None:
    raw = info.filename
    if not raw or "\x00" in raw or "\\" in raw:
        raise ZipImportError(f"非法 ZIP 路径：{raw!r}")
    if raw.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", raw):
        raise ZipImportError(f"不允许绝对路径：{raw}")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ZipImportError(f"路径包含非法片段：{raw}")
    if path.as_posix() == "manifest.json":
        raise ZipImportError("根目录 manifest.json 为系统保留文件名")
    if path.parts and path.parts[0].lower() in {".github", "tools", "sources", "output", ".git"}:
        raise ZipImportError(f"ZIP 不得直接写入仓库受保护目录：{raw}")
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise ZipImportError(f"拒绝符号链接：{raw}")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ZipImportError(f"拒绝特殊文件：{raw}")
    if info.is_dir():
        return None
    suffix = Path(path.name).suffix.lower()
    if suffix in BLOCKED_SUFFIXES or suffix not in ALLOWED_SUFFIXES:
        raise ZipImportError(f"不支持或禁止的文件类型：{raw}")
    if info.file_size < 0 or info.file_size > MAX_FILE_BYTES:
        raise ZipImportError(f"单文件大小超限：{raw}")
    if info.file_size and info.compress_size == 0:
        raise ZipImportError(f"压缩大小异常：{raw}")
    if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
        raise ZipImportError(f"压缩率超限：{raw}")
    if info.flag_bits & 0x1:
        raise ZipImportError(f"不接受加密 ZIP 条目：{raw}")
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ZipImportError(f"不支持的压缩算法：{raw}")
    return path.as_posix()


def validate_archive(payload: bytes) -> list[dict]:
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ZipImportError("ZIP 文件超过 20 MiB 限制")
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ZipImportError(f"不是有效 ZIP 文件：{exc}") from exc
    records, seen, total = [], set(), 0
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise ZipImportError(f"文件条目超过 {MAX_FILES} 个")
        for info in infos:
            rel = validate_member(info)
            if rel is None:
                continue
            if rel in seen:
                raise ZipImportError(f"ZIP 内存在重复路径：{rel}")
            seen.add(rel)
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ZipImportError("解压后总大小超过 40 MiB")
            try:
                content = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile) as exc:
                raise ZipImportError(f"读取条目失败：{rel}: {exc}") from exc
            if len(content) != info.file_size:
                raise ZipImportError(f"条目长度不匹配：{rel}")
            if Path(rel).suffix.lower() == ".json":
                try:
                    json.loads(content.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ZipImportError(f"JSON 校验失败：{rel}: {exc}") from exc
            records.append({
                "path": rel,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "_content": content,
            })
    if not records:
        raise ZipImportError("ZIP 中没有可导入的文件")
    return records


def import_payload(payload: bytes, root: Path = ROOT) -> dict:
    staging = root / "imports" / "staging"
    report_path = root / "output" / "reports" / "zip_import_report.json"
    try:
        records = validate_archive(payload)
        targets = [staging / item["path"] for item in records]
        if any(path.exists() for path in targets) or (staging / "manifest.json").exists():
            raise ZipImportError("暂存目录存在同名文件；为防止覆盖，已拒绝本次导入")
        manifest_records = []
        for item, target in zip(records, targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item["_content"])
            manifest_records.append({k: v for k, v in item.items() if k != "_content"})
        manifest = {
            "source": "manual_zip_import",
            "file_count": len(manifest_records),
            "total_size_bytes": sum(x["size_bytes"] for x in manifest_records),
            "files": manifest_records,
            "notes": ["文件仅解压到 imports/staging，不会合并到正式配置目录。", "不会执行 ZIP 内的 JS、Python 或 JAR。"],
        }
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report = {"status": "导入暂存成功", "file_count": len(records),
                  "total_size_bytes": manifest["total_size_bytes"],
                  "staging": "imports/staging", "files": manifest_records}
    except Exception as exc:
        report = {"status": "导入拒绝", "error": str(exc), "file_count": 0}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", type=Path, help="本地 ZIP 文件路径")
    source.add_argument("--url", help="手动指定的公开 ZIP URL")
    args = parser.parse_args()
    try:
        if args.zip:
            payload = args.zip.read_bytes()
        else:
            response = fetch_bytes(
                args.url, timeout=(5, 15), max_bytes=MAX_ARCHIVE_BYTES,
                retries=1, headers={"Accept": "application/zip, application/octet-stream"}
            )
            if not 200 <= response.status_code < 300:
                raise ZipImportError(f"ZIP 下载 HTTP 状态异常：{response.status_code}")
            payload = response.body
        result = import_payload(payload)
    except Exception as exc:
        result = {"status": "导入拒绝", "error": str(exc), "file_count": 0}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "导入暂存成功" else 1


if __name__ == "__main__":
    raise SystemExit(main())
