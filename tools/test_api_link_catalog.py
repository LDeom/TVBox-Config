#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from api_link_catalog import parse_api_links


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
