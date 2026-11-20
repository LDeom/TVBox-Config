#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import unittest

from audit_reference_tvbox_sources import (
    append_verified_to_manifest,
    deduplicate_candidates,
    extract_vod_candidates,
    make_manifest_name,
    parse_tvbox_config,
)


class ReferenceTvboxAuditTests(unittest.TestCase):
    def test_parses_tvbox_config_with_sites(self):
        body = json.dumps({
            "sites": [{"key": "demo", "name": "示例", "type": 1,
                       "api": "https://api.example.test/provide/vod"}]
        }, ensure_ascii=False).encode()
        config, status = parse_tvbox_config(body)
        self.assertEqual(status, "有效 TVBox 配置")
        self.assertEqual(len(config["sites"]), 1)

    def test_rejects_non_config_json(self):
        config, status = parse_tvbox_config(b'{"list":[{"vod_id":"1","vod_name":"movie"}]}')
        self.assertIsNone(config)
        self.assertEqual(status, "不是包含 sites 数组的 TVBox 配置")

    def test_extracts_only_absolute_type_zero_or_one_sites(self):
        config = {"sites": [
            {"key": "one", "name": "CMS", "type": 1, "api": "https://api.example.test/vod"},
            {"key": "two", "name": "Custom", "type": 0, "api": "http://custom.example.test/vod"},
            {"key": "three", "name": "Spider", "type": 3, "api": "csp_DouDou"},
            {"key": "four", "name": "Relative", "type": 1, "api": "/api/vod"},
        ]}
        rows = extract_vod_candidates("Demo", config, "https://config.example.test/tv.json")
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["test_url"].endswith("/vod?ac=list"))
        self.assertEqual(rows[1]["test_url"], "http://custom.example.test/vod")

    def test_deduplicates_api_url_and_keeps_source_provenance(self):
        rows = [
            {"config_name": "A", "config_url": "https://a.test/c.json",
             "site_name": "Site", "site_key": "s", "site_type": 1,
             "api": "https://api.example.test/vod", "test_url": "https://api.example.test/vod?ac=list"},
            {"config_name": "B", "config_url": "https://b.test/c.json",
             "site_name": "Site2", "site_key": "s2", "site_type": 1,
             "api": "https://api.example.test/vod", "test_url": "https://api.example.test/vod?ac=list"},
        ]
        result = deduplicate_candidates(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["sources"]), 2)

    def test_manifest_append_preserves_existing_content_and_adds_only_missing_url(self):
        row = {
            "config_name": "配置A", "site_name": "采集站", "test_url": "https://api.example.test/vod?ac=list",
            "sources": [{"config_name": "配置A", "site_name": "采集站"}],
        }
        old = "# keep this comment\nExisting, https://old.example.test/vod\n"
        updated, additions = append_verified_to_manifest(old, [row])
        self.assertTrue(updated.startswith(old))
        self.assertEqual(len(additions), 1)
        self.assertIn("https://api.example.test/vod?ac=list", updated)
        updated2, additions2 = append_verified_to_manifest(updated, [row])
        self.assertEqual(updated2, updated)
        self.assertEqual(additions2, [])

    def test_manifest_name_is_stable_and_parseable(self):
        row = {
            "test_url": "https://api.example.test/vod?ac=list",
            "sources": [{"config_name": "Config, A", "site_name": "Site|B"}],
        }
        name = make_manifest_name(row)
        self.assertNotIn(",", name)
        self.assertNotIn("|", name)
        self.assertEqual(name, make_manifest_name(row))


if __name__ == "__main__":
    unittest.main()
