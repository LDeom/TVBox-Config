#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for export_tvbox_vod_config.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from export_tvbox_vod_config import build_tvbox_config, export_config

VALID = b'{"list":[{"vod_id":"1","vod_name":"Example"}]}'


class TVBoxVODConfigTests(unittest.TestCase):
    def _row(self, key, api, path, **extra):
        row = {
            "key": key, "name": key, "type": 1, "api": api,
            "searchable": 1, "filterable": 1, "status": "有效影视 JSON",
            "saved_file": path, "seconds": 0.5,
        }
        row.update(extra)
        return row

    def test_exports_valid_json_and_verified_manifest_entries_but_skips_custom_spiders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "cache/a.json").write_bytes(VALID)
            (root / "cache/b.xml").write_text("<root/>", encoding="utf-8")
            index = {"results": [
                self._row("json", "https://one.example/api?ac=list", "cache/a.json"),
                self._row("xml", "https://two.example/api/at/xml/", "cache/b.xml",
                          status="有效影视 XML"),
                self._row("manifest", "https://three.example/api", "cache/a.json", type=0, source_file="apilinks.txt"),
                self._row("custom", "https://custom.example/spider", "cache/a.json", type=0, source_file="sources/configs/vod/custom.json"),
                self._row("missing", "https://four.example/api", "cache/missing.json"),
            ]}
            config, included = build_tvbox_config(index, root)
            self.assertEqual(len(config["sites"]), 2)
            self.assertEqual(len(included), 2)
            self.assertEqual(config["sites"][0]["api"], "https://one.example/api")
            self.assertTrue(all(site["type"] == 1 for site in config["sites"]))

    def test_preferred_json_mirror_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "cache/a.json").write_bytes(VALID)
            (root / "cache/b.json").write_bytes(VALID)
            index = {
                "results": [
                    self._row("mirror", "https://slow.example/api", "cache/a.json", seconds=2),
                    self._row("mirror", "https://fast.example/api", "cache/b.json", seconds=0.2),
                ],
                "mirror_recommendations": {
                    "mirror": {"preferred_url": "https://slow.example/api"}
                },
            }
            _config, included = build_tvbox_config(index, root)
            self.assertEqual(included[0]["api"], "https://slow.example/api")

    def test_duplicate_api_is_included_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "cache/a.json").write_bytes(VALID)
            index = {"results": [
                self._row("first", "https://same.example/api?ac=list", "cache/a.json"),
                self._row("second", "https://same.example/api", "cache/a.json"),
            ]}
            _config, included = build_tvbox_config(index, root)
            self.assertEqual(len(included), 1)

    def test_invalid_cached_payload_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "cache/a.json").write_text('{"hello":"world"}', encoding="utf-8")
            index = {"results": [
                self._row("bad", "https://bad.example/api", "cache/a.json")
            ]}
            config, included = build_tvbox_config(index, root)
            self.assertEqual(config["sites"], [])
            self.assertEqual(included, [])

    def test_export_overwrites_stable_output_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            (root / "cache/a.json").write_bytes(VALID)
            collected = root / "sources/collected"
            collected.mkdir(parents=True)
            (collected / "api_index.json").write_text(json.dumps({
                "generated_at": "test", "results": [
                    self._row("demo", "https://demo.example/api?ac=list", "cache/a.json")
                ]
            }), encoding="utf-8")
            result = export_config(root)
            output = collected / "tvbox_vod_config.json"
            self.assertEqual(result["site_count"], 1)
            self.assertTrue(output.is_file())
            self.assertTrue((collected / "tvbox_vod_config_summary.txt").is_file())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["sites"][0]["api"],
                             "https://demo.example/api")


if __name__ == "__main__":
    unittest.main()
