#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from build_resource_catalog import build_catalog


class ResourceCatalogTests(unittest.TestCase):
    def test_indexes_local_files_and_classifies_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources/js").mkdir(parents=True)
            (root / "sources/jar").mkdir(parents=True)
            (root / "sources/live").mkdir(parents=True)
            (root / "sources/js/有声听书.js").write_text("// local", encoding="utf-8")
            (root / "sources/jar/spider.jar").write_bytes(b"jar")
            (root / "sources/live/channels.m3u").write_text("#EXTM3U\n", encoding="utf-8")
            result = build_catalog(root)
            self.assertEqual(result["total_files"], 3)
            categories = {item["path"]: item["category"] for item in result["resources"]}
            self.assertEqual(categories["sources/live/channels.m3u"], "live")
            self.assertEqual(categories["sources/jar/spider.jar"], "jar_dependency")
            self.assertEqual(categories["sources/js/有声听书.js"], "audio")

    def test_empty_repository_returns_empty_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_catalog(Path(tmp))
            self.assertEqual(result["total_files"], 0)
            self.assertEqual(result["resources"], [])


if __name__ == "__main__":
    unittest.main()
