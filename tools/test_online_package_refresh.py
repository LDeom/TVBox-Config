#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from refresh_online_packages import summarize


class OnlinePackageRefreshTests(unittest.TestCase):
    def test_empty_input_is_reported_without_fake_downloads(self):
        report = summarize([], [])
        self.assertEqual(report["input_count"], 0)
        self.assertEqual(report["results"], [])
        self.assertEqual(report["status_counts"], {})

    def test_status_counts_are_stable(self):
        records = [{"url": "https://example.com/a.json"}]
        results = [
            {"url": "https://example.com/a.json", "status": "在线包 JSON 已解析"},
            {"url": "https://example.com/b.json", "status": "请求失败"},
        ]
        report = summarize(records, results)
        self.assertEqual(report["status_counts"]["在线包 JSON 已解析"], 1)
        self.assertEqual(report["status_counts"]["请求失败"], 1)


if __name__ == "__main__":
    unittest.main()
