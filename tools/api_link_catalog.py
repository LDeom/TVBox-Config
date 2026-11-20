#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse the repository-owned API endpoint list.

This is an independent implementation of the public list format used by the
reference project. It does not import or execute code from that project.
"""
from __future__ import annotations

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


def load_api_links(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return parse_api_links(path.read_text(encoding="utf-8-sig"))
