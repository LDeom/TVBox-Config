#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_live_playlists as live


class LivePlaylistBackupTests(unittest.TestCase):
    def test_unique_sources_deduplicates_url(self):
        rows = [
            {"name": "A", "url": "https://example.com/live.m3u"},
            {"name": "B", "url": "https://example.com/live.m3u"},
            {"name": "C", "url": "https://example.com/other.m3u"},
        ]
        result = live.unique_live_sources(rows)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "A")

    def test_fetch_one_retries_with_alternate_user_agent(self):
        calls = []
        def fake_fetch(url, default_group, fetcher):
            calls.append(url)
            if len(calls) == 1:
                return {"rows": [], "status": "无可识别频道",
                        "detail": "first UA blocked", "chain": [], "final_url": url}
            return {"rows": [{"group": "新闻", "name": "频道一",
                              "url": "https://media.example/one.m3u8"}],
                    "status": "已提取频道", "detail": "ok",
                    "chain": [url], "final_url": url}
        with patch.object(live, "fetch_live_playlist", side_effect=fake_fetch):
            result = live.fetch_one({"name": "测试直播", "url": "https://example.com/live"})
        self.assertEqual(result["status"], "直播列表已备份")
        self.assertEqual(result["channels"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["ua"], live.UA_PROFILES[1])

    def test_save_result_writes_playlist_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(live, "ROOT", root), \
                 patch.object(live, "OUTPUT", root / "out"), \
                 patch.object(live, "HISTORY", root / "history"):
                record = {
                    "name": "Demo", "url": "https://example.com/live",
                    "status": "直播列表已备份", "channels": 1,
                    "rows": [{"group": "新闻", "name": "频道一",
                              "url": "https://media.example/one.m3u8"}],
                }
                first = live.save_result(record)
                target = root / first["saved_file"]
                original = target.read_bytes()
                changed = {**record, "rows": [{"group": "新闻", "name": "频道二",
                                               "url": "https://media.example/two.m3u8"}]}
                live.save_result(changed)
                archives = list((root / "history").rglob("*.m3u"))
                self.assertEqual(len(archives), 1)
                self.assertEqual(archives[0].read_bytes(), original)
                self.assertIn("频道二", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
