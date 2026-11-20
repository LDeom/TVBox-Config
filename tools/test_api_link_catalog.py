#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from refresh_api_catalog import build_groups

from api_link_catalog import parse_api_links


class ApiCatalogRefreshTests(unittest.TestCase):
    def test_recommendation_prefers_valid_endpoint(self):
        records = [
            {"key": "group", "name": "Group", "api": "https://slow.example/api"},
            {"key": "group", "name": "Group", "api": "https://fast.example/api"},
        ]
        results = [
            {"api": "https://slow.example/api", "status": "有效影视 JSON", "seconds": 3.0, "http": 200},
            {"api": "https://fast.example/api", "status": "有效影视 XML", "seconds": 0.5, "http": 200},
        ]
        groups = build_groups(records, results)
        self.assertEqual(groups["group"]["preferred_url"], "https://fast.example/api")
        self.assertEqual(groups["group"]["fallback_urls"], ["https://slow.example/api"])


class ApiLinkCatalogTests(unittest.TestCase):
    def test_multiple_mirrors_and_deduplication(self):
        rows = parse_api_links(
            "# comment\n"
            "饭太硬, https://one.example/tv, https://two.example/tv\n"
            "饭太硬|https://one.example/tv\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["name"] for row in rows}, {"饭太硬"})
        self.assertEqual({row["api"] for row in rows},
                         {"https://one.example/tv", "https://two.example/tv"})

    def test_bare_url_and_invalid_line(self):
        rows = parse_api_links("not a url\nhttps://example.com/api.json\n")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["api"], "https://example.com/api.json")
        self.assertEqual(rows[0]["type"], 0)

    def test_different_names_remain_distinct(self):
        rows = parse_api_links(
            "A, https://example.com/api\nB, https://example.com/api\n"
        )
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
