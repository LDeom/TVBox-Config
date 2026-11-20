#!/usr/bin/env python3
"""Audit and safely normalize JSON files already inside this repository.

No upstream repositories are contacted. Only encoding BOMs and trailing commas
outside JSON strings are normalized. Invalid files are reported, never deleted.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "output" / "reports" / "local_json_maintenance.json"
SKIP_PARTS = {".git", ".github", "__pycache__", ".venv", "venv"}
TRAILING_COMMA = re.compile(r",(?=\s*[}\]])")
RAW_PREFIX = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/"


def strip_trailing_commas(text: str) -> str:
    out = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
                out.append(ch)
            elif ch == ",":
                j = i + 1
                while j < len(text) and text[j].isspace():
                    j += 1
                if j < len(text) and text[j] in "}]":
                    pass
                else:
                    out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def main() -> None:
    files = sorted(
        p for p in ROOT.rglob("*.json")
        if not any(part in SKIP_PARTS for part in p.relative_to(ROOT).parts)
        and p != REPORT
    )
    valid, repaired, invalid, local_missing = [], [], [], []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        original = path.read_text(encoding="utf-8-sig")
        normalized = strip_trailing_commas(original)
        try:
            data = json.loads(normalized)
        except Exception as exc:
            invalid.append({"path": rel, "error": str(exc)})
            continue
        if normalized != original or path.read_bytes().startswith(b"\xef\xbb\xbf"):
            path.write_text(normalized.rstrip() + "\n", encoding="utf-8")
            repaired.append(rel)
        else:
            valid.append(rel)

        # Check references to files hosted by this repository.
        def walk(value):
            if isinstance(value, dict):
                for v in value.values():
                    yield from walk(v)
            elif isinstance(value, list):
                for v in value:
                    yield from walk(v)
            elif isinstance(value, str) and RAW_PREFIX in value:
                for match in re.findall(re.escape(RAW_PREFIX) + r"([^ \t\r\n\\"'<>]+)", value):
                    target = unquote(urlsplit(match.strip("'\\\"")).path)
                    if target and not (ROOT / target).is_file():
                        yield target
        for target in walk(data):
            local_missing.append({"source": rel, "target": target})

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "LDeom/TVBox-Config",
        "source": "this repository only; no upstream sync",
        "total_json": len(files),
        "valid_count": len(valid) + len(repaired),
        "repaired_count": len(repaired),
        "invalid_count": len(invalid),
        "missing_local_reference_count": len(local_missing),
        "repaired": repaired,
        "invalid": invalid,
        "missing_local_references": local_missing,
        "note": "Invalid JSON and missing references are reported but not deleted or guessed at."
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "total_json", "valid_count", "repaired_count",
        "invalid_count", "missing_local_reference_count"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
