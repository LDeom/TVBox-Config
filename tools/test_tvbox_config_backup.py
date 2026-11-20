#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_tvbox_configs as backup


class TVBoxConfigBackupTests(unittest.TestCase):
    def test_safe_stem_removes_path_and_control_characters(self):
        self.assertEqual(backup.safe_stem("../A:B/C?.json"), "A_B_C_.json")

    def test_absolutize_known_fields_and_preserve_code_identifiers(self):
        source = {
            "spider": "spider.jar",
            "sites": [{"name": "A", "api": "./api.php", "jar": "../libs/spider.jar",
                       "ext": {"url": "rules/demo.json", "id": "csp_Demo"}}],
            "lives": [{"url": "live/tv.m3u", "epg": "/epg.xml"}],
        }
        result = backup.absolutize_tvbox_config(source, "https://example.com/config/box.json")
        self.assertEqual(result["spider"], "https://example.com/config/spider.jar")
        self.assertEqual(result["sites"][0]["api"], "https://example.com/config/api.php")
        self.assertEqual(result["sites"][0]["jar"], "https://example.com/libs/spider.jar")
        self.assertEqual(result["sites"][0]["ext"]["url"], "https://example.com/config/rules/demo.json")
        self.assertEqual(result["sites"][0]["ext"]["id"], "csp_Demo")
        self.assertEqual(result["lives"][0]["url"], "https://example.com/config/live/tv.m3u")
        self.assertEqual(result["lives"][0]["epg"], "https://example.com/epg.xml")
        self.assertEqual(source["sites"][0]["api"], "./api.php")

    def test_grouped_records_keeps_mirrors_in_input_order(self):
        rows = [
            {"name": "Group", "api": "https://one.example/config.json"},
            {"name": "Group", "api": "https://two.example/config.json"},
            {"name": "group", "api": "https://one.example/config.json"},
        ]
        groups = backup.grouped_records(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["urls"], ["https://one.example/config.json", "https://two.example/config.json"])

    def test_build_backup_overwrites_same_path_without_history_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(backup, "ROOT", root), \
                 patch.object(backup, "RAW_DIR", root / "raw"), \
                 patch.object(backup, "PORTABLE_DIR", root / "portable"):
                group = {"name": "Demo"}
                url = "https://example.com/config/box.json"
                first = backup.build_backup(group, {
                    "name": "Demo", "status": "JSON备份成功", "source_url": url,
                    "object": {"sites": [{"api": "./api"}]},
                })
                raw_path = root / first["raw_file"]
                original = raw_path.read_bytes()
                second = backup.build_backup(group, {
                    "name": "Demo", "status": "JSON备份成功", "source_url": url,
                    "object": {"sites": [{"api": "./new-api"}]},
                })
                self.assertNotEqual(raw_path.read_bytes(), original)
                digest = hashlib.sha256(("Demo\n" + url).encode()).hexdigest()[:16]
                self.assertFalse((root / "history").exists())
                self.assertEqual(second["id"], digest)


if __name__ == "__main__":
    unittest.main()
