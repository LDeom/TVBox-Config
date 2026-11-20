#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from export_named_api_snapshots import export_named_snapshots, stable_id


def vod_payload(label):
    return json.dumps({
        "list": [
            {"vod_id": f"{label}-{index}", "vod_name": f"{label} 影片 {index}"}
            for index in range(25)
        ]
    }, ensure_ascii=False).encode("utf-8")


class NamedApiSnapshotTests(unittest.TestCase):
    def test_preferred_valid_mirror_exports_stable_named_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api_dir = root / "sources" / "collected" / "api"
            api_dir.mkdir(parents=True)
            (api_dir / "a.json").write_bytes(vod_payload("A"))
            (api_dir / "b.json").write_bytes(vod_payload("B"))
            api_index = {
                "results": [
                    {"key": "demo", "name": "示例接口", "api": "https://a.example/api",
                     "status": "有效影视 JSON", "saved_file": "sources/collected/api/a.json"},
                    {"key": "demo", "name": "示例接口", "api": "https://b.example/api",
                     "status": "有效影视 JSON", "saved_file": "sources/collected/api/b.json"},
                ],
                "mirror_recommendations": {
                    "demo": {"preferred_url": "https://b.example/api"}
                },
            }
            report = export_named_snapshots(api_index, root=root)
            self.assertEqual(report["success_count"], 1)
            item = report["results"][0]
            self.assertEqual(item["source_url"], "https://b.example/api")
            self.assertEqual(item["source_file"], "sources/collected/api/b.json")
            self.assertTrue(item["saved_file"].startswith("sources/collected/api_named/示例接口_"))
            target = root / item["saved_file"]
            self.assertEqual(target.read_bytes(), vod_payload("B"))
            self.assertEqual(item["id"], stable_id("demo"))

    def test_same_api_group_overwrites_same_path_without_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api_dir = root / "sources" / "collected" / "api"
            api_dir.mkdir(parents=True)
            source = api_dir / "one.json"
            source.write_bytes(vod_payload("old"))
            api_index = {
                "results": [{
                    "key": "stable-key", "name": "固定名称", "api": "https://api.example/vod",
                    "status": "有效影视 JSON", "saved_file": "sources/collected/api/one.json",
                }],
                "mirror_recommendations": {},
            }
            first = export_named_snapshots(api_index, root=root)["results"][0]["saved_file"]
            source.write_bytes(vod_payload("new"))
            second_report = export_named_snapshots(api_index, root=root)
            second = second_report["results"][0]["saved_file"]
            self.assertEqual(first, second)
            self.assertEqual((root / second).read_bytes(), vod_payload("new"))
            files = list((root / "sources" / "collected" / "api_named").glob("固定名称_*.json"))
            self.assertEqual(len(files), 1)

    def test_failed_refresh_preserves_previous_named_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api_dir = root / "sources" / "collected" / "api"
            api_dir.mkdir(parents=True)
            source = api_dir / "one.json"
            source.write_bytes(vod_payload("old"))
            successful = {
                "results": [{
                    "key": "stable", "name": "稳定接口", "api": "https://api.example/vod",
                    "status": "有效影视 JSON", "saved_file": "sources/collected/api/one.json",
                }],
                "mirror_recommendations": {},
            }
            first = export_named_snapshots(successful, root=root)["results"][0]
            previous_content = (root / first["saved_file"]).read_bytes()
            failed = {
                "results": [{
                    "key": "stable", "name": "稳定接口", "api": "https://api.example/vod",
                    "status": "请求失败", "saved_file": "",
                }],
                "mirror_recommendations": {},
            }
            report = export_named_snapshots(failed, root=root)
            self.assertEqual(report["retained_count"], 1)
            self.assertEqual(report["results"][0]["status"], "更新失败，保留旧命名快照")
            self.assertEqual(report["results"][0]["saved_file"], first["saved_file"])
            self.assertEqual((root / first["saved_file"]).read_bytes(), previous_content)

    def test_rejects_snapshot_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = export_named_snapshots({
                "results": [{
                    "key": "unsafe", "name": "越界", "api": "https://api.example/vod",
                    "status": "有效影视 JSON", "saved_file": "../../outside.json",
                }],
                "mirror_recommendations": {},
            }, root=root)
            self.assertEqual(report["failure_count"], 1)
            self.assertEqual(report["results"][0]["status"], "没有可用快照")
            self.assertFalse((root / "outside.json").exists())


if __name__ == "__main__":
    unittest.main()
