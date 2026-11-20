#!/usr/bin/env python3
"""Mirror TVBox JS/JAR dependencies and rewrite source configs to this repository."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_URL = "https://github.com/LDeom/tvbox.git"
REPOSITORY = "LDeom/TVBox-Config"
CONFIGS = [
    "jsm.json", "js.json", "0826.json", "0827.json", "fty.json",
    "0825.json", "0821.json", "dianshi.json", "367.json", "9918.json", "99188.json",
]
AGGREGATE_CONFIGS = [
    "sources/vod/TVBox_点播总配置.json",
    "sources/vod/config.json",
    "sources/vod/tvbox-config.json",
]
EXTENSION = re.compile(r"\.(?:js|jar)$", re.I)
RELATIVE_REF = re.compile(r"""\./([^;\s"'$<>]+)""")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def raw_url(repository: str, branch: str, path: str) -> str:
    encoded = "/".join(quote(part, safe="") for part in path.split("/"))
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{encoded}"


def collect(value, config_name: str, found: dict[str, set[str]]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            collect(item, config_name, found)
    elif isinstance(value, list):
        for item in value:
            collect(item, config_name, found)
    elif isinstance(value, str):
        for match in RELATIVE_REF.finditer(value):
            token = match.group(1)
            parsed = urlsplit(token)
            path = unquote(parsed.path).replace("\\", "/")
            if path.lower().endswith((".js", ".jar")):
                found.setdefault(path, set()).add(config_name)


def destination(source_path: str) -> Path:
    if source_path.lower().endswith(".jar"):
        relative = source_path[4:] if source_path.startswith("jar/") else source_path
        return ROOT / "sources" / "jar" / relative
    relative = source_path[3:] if source_path.startswith("js/") else source_path
    return ROOT / "sources" / "js" / relative


def rewrite_relative_refs(value, local_targets: dict[str, str], stats: dict[str, int]):
    if isinstance(value, list):
        return [rewrite_relative_refs(item, local_targets, stats) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_relative_refs(item, local_targets, stats) for key, item in value.items()}
    if not isinstance(value, str) or "./" not in value:
        return value

    def replace(match: re.Match) -> str:
        token = match.group(1)
        parsed = urlsplit(token)
        source_path = unquote(parsed.path).replace("\\", "/")
        is_plugin = source_path.lower().endswith((".js", ".jar"))
        if is_plugin and source_path in local_targets:
            target = raw_url(REPOSITORY, "main", local_targets[source_path])
            stats["plugin_refs_to_local"] += 1
        else:
            target = raw_url("LDeom/tvbox", "master", source_path)
            stats["other_refs_to_upstream"] += 1
            if is_plugin:
                stats["missing_plugin_refs"] += 1
        if parsed.query:
            target += "?" + parsed.query
        if parsed.fragment:
            target += "#" + parsed.fragment
        return target

    return RELATIVE_REF.sub(replace, value)


def main() -> None:
    upstream = Path("/tmp/tvbox-upstream")
    if upstream.exists():
        shutil.rmtree(upstream)
    subprocess.run(["git", "clone", "--depth", "1", UPSTREAM_URL, str(upstream)], check=True)
    upstream_commit = git("rev-parse", "HEAD", cwd=upstream)

    references: dict[str, set[str]] = {}
    source_configs = {}
    for name in CONFIGS:
        path = upstream / name
        if not path.is_file():
            print(f"CONFIG_MISSING {name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        source_configs[name] = data
        collect(data, name, references)

    copied, missing = [], []
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

    local_targets = {item["source_path"]: item["target_path"] for item in copied}
    stats = {
        "plugin_refs_to_local": 0,
        "other_refs_to_upstream": 0,
        "missing_plugin_refs": 0,
        "configs_rewritten": 0,
        "aggregate_entries_repointed": 0,
    }

    config_output = ROOT / "sources" / "configs" / "vod"
    config_output.mkdir(parents=True, exist_ok=True)
    for name, data in source_configs.items():
        rewritten = rewrite_relative_refs(data, local_targets, stats)
        target = config_output / name
        target.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stats["configs_rewritten"] += 1

    local_config_urls = {
        name: raw_url(REPOSITORY, "main", f"sources/configs/vod/{name}")
        for name in source_configs
    }
    for relative_path in AGGREGATE_CONFIGS:
        path = ROOT / relative_path
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for item in data.get("urls", []):
            url = item.get("url", "") if isinstance(item, dict) else ""
            if "LDeom/tvbox@master/" not in url:
                continue
            name = url.split("LDeom/tvbox@master/", 1)[1].split("?", 1)[0]
            if name in local_config_urls:
                item["url"] = local_config_urls[name]
                stats["aggregate_entries_repointed"] += 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        "rewritten_configs": [f"sources/configs/vod/{name}" for name in source_configs],
        "aggregate_configs_updated": AGGREGATE_CONFIGS,
        "rewrite_stats": stats,
    }
    out = ROOT / "output" / "reports" / "plugin_dependency_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    js_count = sum(item["source_path"].lower().endswith(".js") for item in copied)
    jar_count = sum(item["source_path"].lower().endswith(".jar") for item in copied)
    print(f"UPSTREAM_COMMIT={upstream_commit}")
    print(f"REFERENCED={len(references)} COPIED={len(copied)} JS={js_count} JAR={jar_count} MISSING={len(missing)}")
    print(f"CONFIGS_REWRITTEN={stats['configs_rewritten']} LOCAL_PLUGIN_REFS={stats['plugin_refs_to_local']}")
    print(f"AGGREGATE_ENTRIES_REPOINTED={stats['aggregate_entries_repointed']}")
    for item in missing:
        print(f"MISSING {item['source_path']} (referenced by {', '.join(item['configs'])})")


if __name__ == "__main__":
    main()
