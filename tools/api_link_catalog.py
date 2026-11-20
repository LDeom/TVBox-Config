#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse the repository-owned API endpoint list.

This is an independent implementation of the public list format used by the
reference project. It does not import or execute code from that project.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

URL_RE = re.compile(r"https?://[^\s,;|]+", re.IGNORECASE)


def parse_api_links(text: str) -> list[dict]:
    """Parse 'name, URL1, URL2' / 'name|URL1|URL2' and bare URL lines."""
    records = []
    seen = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        match = URL_RE.search(line)
        if not match:
            continue
        name = line[:match.start()].strip(" \t,;|")
        urls = URL_RE.findall(line[match.start():])
        for url in urls:
            url = url.rstrip(").]}，；")
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            key = (name.casefold(), url.casefold())
            if key in seen:
                continue
            seen.add(key)
            fallback = Path(parsed.path).name or f"api-{line_number}"
            label = name or fallback
            records.append({
                "key": label,
                "name": label,
                "type": 0,
                "api": url,
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 1,
                "source_file": "apilinks.txt",
                "source_line": line_number,
            })
    return records


def legacy_config_records(config: dict, source_file: str) -> list[dict]:
    rows = []
    seen = set()

    def add(name, url):
        name = str(name or "").strip()
        url = str(url or "").strip()
        parsed = urlsplit(url)
        if not name or parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return
        key = (name.casefold(), url.casefold())
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "key": name, "name": name, "type": 0, "api": url,
            "searchable": 1, "quickSearch": 1, "filterable": 1,
            "source_file": source_file, "source_line": 0,
        })

    api_list = config.get("API_LIST", [])
    if isinstance(api_list, list):
        for item in api_list:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                add(item[0], item[1])
            elif isinstance(item, dict):
                add(item.get("name") or item.get("key"), item.get("api") or item.get("url"))

    mirrors = config.get("API_MIRRORS", {})
    if isinstance(mirrors, dict):
        for name, urls in mirrors.items():
            if isinstance(urls, str):
                urls = [urls]
            if isinstance(urls, list):
                for url in urls:
                    add(name, url)
    return rows


def parse_legacy_api_json(path: Path) -> list[dict]:
    """Read the old API_LIST/API_MIRRORS JSON format without executing code."""
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return []
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return legacy_config_records(config, path.name) if isinstance(config, dict) else []


def parse_legacy_api_py(path: Path) -> list[dict]:
    """Safely parse literal API_LIST/API_MIRRORS assignments; never import/execute."""
    import ast
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return []
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=path.name)
        config = {}
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                name, value = node.target.id, node.value
            else:
                return []
            try:
                literal = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                return []
            if name in {"API_LIST", "API_MIRRORS"}:
                config[name] = literal
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    return legacy_config_records(config, path.name)


def load_api_links(path: Path) -> list[dict]:
    """Prefer the current TXT manifest; use legacy JSON only as a safe fallback."""
    if path.is_file():
        records = parse_api_links(path.read_text(encoding="utf-8-sig"))
        if records:
            return records
    legacy_json = parse_legacy_api_json(path.with_name("api_list.json"))
    return legacy_json or parse_legacy_api_py(path.with_name("api_list.py"))
