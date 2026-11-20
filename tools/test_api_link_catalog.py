#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from refresh_api_catalog import build_groups

from api_link_catalog import parse_api_links


class ApiPaginationTests(unittest.TestCase):
    def test_page_url_preserves_other_query_parameters(self):
        self.assertEqual(
            page_url("https://example.com/api?token=x&pg=1", 3),
            "https://example.com/api?token=x&pg=3"
        )

    def test_pagination_metadata(self):
        meta = pagination_info({"pagecount": "3", "list": [{"vod_id": 1}]})
        self.assertEqual(meta["page_count"], 3)
        self.assertEqual(meta["list_key"], "list")
        meta = pagination_info({"total": 45, "limit": "20", "data": []})
        self.assertEqual(meta["page_count"], 3)

    def test_fetch_all_pages_and_merge(self):
        from types import SimpleNamespace
        pages = [
            {"page": 1, "pagecount": 2, "list": [{"vod_id": 1, "vod_name": "A"}]},
            {"page": 2, "pagecount": 2, "list": [{"vod_id": 2, "vod_name": "B"}]},
        ]
        calls = []
        def fake_fetch(url, **kwargs):
            calls.append(url)
            return SimpleNamespace(status_code=200,
                body=json.dumps(pages[len(calls)-1]).encode(), url=url, headers={})
        result = fetch_paginated_api(
            {"key": "demo", "name": "Demo", "api": "https://example.com/api"},
            fetcher=fake_fetch
        )
        self.assertEqual(result["status"], "分页采集完成")
        self.assertEqual(result["item_count"], 2)
        self.assertEqual(len(calls), 2)


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
