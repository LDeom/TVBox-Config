#!/usr/bin/env python3
"""Mirror locally referenced JS/JAR dependencies from LDeom/tvbox."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_URL = "https://github.com/LDeom/tvbox.git"
CONFIGS = [
    "jsm.json", "js.json", "0826.json", "0827.json", "fty.json",
    "0825.json", "0821.json", "dianshi.json", "367.json", "9918.json", "99188.json",
]
REF_SPLIT = re.compile(r"(?:\$\$\$|;|\n)")
EXTENSION = re.compile(r"\.(?:js|jar)$", re.I)


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def collect(value, config_name: str, found: dict[str, set[str]]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            collect(item, config_name, found)
    elif isinstance(value, list):
        for item in value:
            collect(item, config_name, found)
    elif isinstance(value, str):
        for part in REF_SPLIT.split(value):
            part = part.strip().strip('"').strip("'")
            if not part.startswith("./"):
                continue
            path = unquote(urlsplit(part[2:]).path).replace("\\", "/")
            if EXTENSION.search(path):
                found.setdefault(path, set()).add(config_name)


def destination(source_path: str) -> Path:
    if source_path.lower().endswith(".jar"):
        relative = source_path[4:] if source_path.startswith("jar/") else source_path
        return ROOT / "sources" / "jar" / relative
    relative = source_path[3:] if source_path.startswith("js/") else source_path
    return ROOT / "sources" / "js" / relative


def main() -> None:
    upstream = Path("/tmp/tvbox-upstream")
    if upstream.exists():
        shutil.rmtree(upstream)
    subprocess.run(["git", "clone", "--depth", "1", UPSTREAM_URL, str(upstream)], check=True)
    upstream_commit = git("rev-parse", "HEAD", cwd=upstream)

    references: dict[str, set[str]] = {}
    for name in CONFIGS:
        path = upstream / name
        if not path.is_file():
            print(f"CONFIG_MISSING {name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        collect(data, name, references)

    copied, missing, errors = [], [], []
    for source_path, configs in sorted(references.items()):
        source = upstream / source_path
        if not source.is_file():
            missing.append({"source_path": source_path, "configs": sorted(configs)})
            continue
        target = destination(source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        content = target.read_bytes()
        copied.append({
            "source_path": source_path,
            "target_path": target.relative_to(ROOT).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "configs": sorted(configs),
        })

    manifest = {
        "upstream_repository": "https://github.com/LDeom/tvbox",
        "upstream_branch": "master",
        "upstream_commit": upstream_commit,
        "configs_checked": CONFIGS,
        "dependency_count": len(references),
        "copied_count": len(copied),
        "missing_count": len(missing),
        "copied": copied,
        "missing": missing,
    }
    out = ROOT / "output" / "reports" / "plugin_dependency_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    js_count = sum(x["source_path"].lower().endswith(".js") for x in copied)
    jar_count = sum(x["source_path"].lower().endswith(".jar") for x in copied)
    print(f"UPSTREAM_COMMIT={upstream_commit}")
    print(f"REFERENCED={len(references)} COPIED={len(copied)} JS={js_count} JAR={jar_count} MISSING={len(missing)}")
    for item in missing:
        print(f"MISSING {item['source_path']} (referenced by {', '.join(item['configs'])})")


if __name__ == "__main__":
    main()
