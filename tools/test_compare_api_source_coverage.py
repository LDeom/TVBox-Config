#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import unittest
from types import SimpleNamespace

from compare_api_source_coverage import (
    build_coverage_report,
    extract_reference_groups,
    fetch_reference_config,
)


class ApiSourceCoverageTests(unittest.TestCase):
    def test_extracts_and_deduplicates_api_list_and_mirror_groups(self):
        config = {
            "API_LIST": [
                ["接口甲", "https://a.example/vod", "https://b.example/vod"],
                ["接口乙", "https://c.example/vod"],
            ],
            "API_MIRRORS": {
                "接口甲": ["https://b.example/vod", "https://d.example/vod"],
            },
        }
        groups, mirror_count = extract_reference_groups(config)
        self.assertEqual(len(groups), 2)
        self.assertEqual(mirror_count, 1)
        self.assertEqual(groups[0]["urls"], [
            "https://a.example/vod", "https://b.example/vod", "https://d.example/vod"
        ])

    def test_builds_coverage_without_copying_endpoint_urls(self):
        reference = {
            "API_LIST": [
                ["接口甲", "https://a.example/vod", "https://b.example/vod"],
                ["接口乙", "https://c.example/vod"],
            ],
            "API_MIRRORS": {"接口甲": ["https://b.example/vod", "https://d.example/vod"]},
        }
        local_index = {
            "results": [
                {"api": "https://a.example/vod"},
                {"api": "https://c.example/vod"},
            ]
        }
        manifest = "# explicit\n手动源, https://d.example/vod\n"
        report = build_coverage_report(reference, local_index, manifest)
        self.assertEqual(report["reference_unique_url_count"], 4)
        self.assertEqual(report["local_api_index_unique_url_count"], 2)
        self.assertEqual(report["local_explicit_manifest_unique_url_count"], 1)
        self.assertEqual(report["covered_reference_url_count"], 3)
        self.assertEqual(report["uncovered_reference_url_count"], 1)
        self.assertFalse(any(row["imported"] for row in report["groups"]))
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("https://a.example/vod", serialized)
        self.assertNotIn("https://b.example/vod", serialized)
        self.assertIn("不向 apilinks.txt 写入", report["safety"])

    def test_fetch_reference_config_parses_json(self):
        payload = {"API_LIST": [["接口", "https://api.example/vod"]]}
        def fake_fetch(url, **kwargs):
            return SimpleNamespace(status_code=200, body=json.dumps(payload).encode())
        self.assertEqual(fetch_reference_config(fetcher=fake_fetch), payload)

    def test_fetch_reference_config_rejects_http_error(self):
        def fake_fetch(url, **kwargs):
            return SimpleNamespace(status_code=503, body=b"")
        with self.assertRaises(Exception):
            fetch_reference_config(fetcher=fake_fetch)


if __name__ == "__main__":
    unittest.main()
