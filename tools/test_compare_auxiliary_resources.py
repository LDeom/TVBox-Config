#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import unittest
from types import SimpleNamespace

from compare_auxiliary_resources import (
    compare_resources,
    fetch_reference_listing,
)


class AuxiliaryResourceComparisonTests(unittest.TestCase):
    def test_fetches_only_cy_json_metadata(self):
        payload = [
            {"type": "file", "name": "书源.json", "path": "cy/书源.json",
             "sha": "abc", "size": 100, "html_url": "https://github.com/example/book"},
            {"type": "file", "name": "弹幕.json", "path": "cy/弹幕.json",
             "sha": "def", "size": 200, "html_url": "https://github.com/example/danmaku"},
            {"type": "dir", "name": "sub", "path": "cy/sub"},
            {"type": "file", "name": "outside.json", "path": "other/outside.json"},
            {"type": "file", "name": "ignored.txt", "path": "cy/ignored.txt"},
        ]
        calls = []

        def fake_fetch(url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=200, body=json.dumps(payload).encode())

        rows = fetch_reference_listing(fetcher=fake_fetch)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "书源.json")
        self.assertEqual(rows[0]["category"], "book")
        self.assertEqual(rows[1]["name"], "弹幕.json")
        self.assertEqual(rows[1]["category"], "danmaku")
        self.assertEqual(calls[0][1]["max_bytes"], 1024 * 1024)

    def test_rejects_non_list_github_response(self):
        def fake_fetch(url, **kwargs):
            return SimpleNamespace(status_code=200, body=b'{"message":"bad"}')
        with self.assertRaises(Exception):
            fetch_reference_listing(fetcher=fake_fetch)

    def test_comparison_reports_candidates_without_importing(self):
        reference = [
            {"name": "书源.json", "path": "cy/书源.json", "category": "book",
             "local_candidate_categories": ["book"]},
            {"name": "模板.json", "path": "cy/模板.json", "category": "template",
             "local_candidate_categories": ["template"]},
        ]
        catalog = {
            "resources": [
                {"path": "sources/js/有声小说吧.js", "category": "book"},
                {"path": "sources/js/template.js", "category": "javascript_plugin"},
            ]
        }
        report = compare_resources(reference, catalog)
        self.assertEqual(report["comparison_scope"], "metadata_only")
        self.assertEqual(report["reference_file_count"], 2)
        self.assertEqual(report["resources"][0]["local_candidate_count"], 1)
        self.assertEqual(report["resources"][0]["coverage_status"], "存在同类候选，尚未验证功能等价")
        self.assertEqual(report["resources"][1]["local_candidate_count"], 0)
        self.assertFalse(report["resources"][0]["imported"])
        self.assertFalse(report["resources"][0]["content_downloaded"])
        self.assertIn("不下载或导入", report["safety"])


if __name__ == "__main__":
    unittest.main()
