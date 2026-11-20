#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import gzip
import json
import unittest
from api_link_catalog import parse_api_links
from types import SimpleNamespace
from pathlib import Path
import tempfile
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from source_pipeline import (
    aes128_cbc_decrypt, build_tvbox_live_aggregate, canonical_url, decode_2423, fetch_live_playlist, mirror_health_score, rank_mirror_candidates, single_wrapper_url, flatten_live_json, group_live_channels, parse_package_json, parse_playlist, parse_ry_links, strip_json_comments,
    valid_vod_payload,
)
from fetch_util import FetchError, validate_public_url


class ApiLinkCatalogIntegrationTests(unittest.TestCase):
    def test_repository_api_link_format(self):
        rows = parse_api_links(
            "# comment\n接口A, https://a.example/api, https://b.example/api\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "接口A")
        self.assertEqual(rows[1]["key"], "接口A")


class SourcePipelineTests(unittest.TestCase):
    def test_json_comments_and_trailing_commas(self):
        raw = '{"url":"https://example.com/a//b", // comment\n "items":[1,2,],}'
        self.assertEqual(json.loads(strip_json_comments(raw)), {
            "url": "https://example.com/a//b", "items": [1, 2]
        })

    def test_m3u_playlist(self):
        rows = parse_playlist(
            '#EXTM3U\n#EXTINF:-1 group-title="CCTV",CCTV1\nhttps://example.com/1.m3u8\n'
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["group"], "CCTV")
        self.assertEqual(rows[0]["name"], "CCTV1")

    def test_txt_playlist_two_and_three_columns(self):
        rows = parse_playlist(
            '央视频道,#genre#\nCCTV1,http://example.com/1.m3u8\n'
            '卫视频道,湖南卫视,http://example.com/2.m3u8\n'
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["group"], "央视频道")
        self.assertEqual(rows[1]["name"], "湖南卫视")

    def test_vod_json(self):
        body = json.dumps({"list": [{"vod_id": 1, "vod_name": "示例"}]}).encode()
        obj, status, _ = valid_vod_payload(body)
        self.assertEqual(status, "有效影视 JSON")
        self.assertEqual(obj["list"][0]["vod_name"], "示例")

    def test_base64_vod_json(self):
        raw = json.dumps({"list": [{"vod_id": 1, "vod_name": "示例"}]}).encode()
        obj, status, _ = valid_vod_payload(base64.b64encode(raw))
        self.assertEqual(status, "有效影视 JSON")
        self.assertIsNotNone(obj)

    def test_vod_xml(self):
        xml = b'<rss><list><video><vod_id>1</vod_id><vod_name>demo</vod_name></video></list></rss>'
        obj, status, _ = valid_vod_payload(xml)
        self.assertEqual(status, "有效影视 XML")
        self.assertIsInstance(obj, str)

    def test_jsonp_and_gzip_base64_wrappers(self):
        raw = json.dumps({"list": [{"vod_id": 2, "vod_name": "wrapped"}]}).encode()
        obj, status, _ = valid_vod_payload(b"callback(" + raw + b");")
        self.assertEqual(status, "有效影视 JSON")
        wrapped = gzip.compress(base64.b64encode(raw))
        obj, status, _ = valid_vod_payload(wrapped)
        self.assertEqual(status, "有效影视 JSON")

    def test_aes128_cbc_decrypt(self):
        key, iv = b"0123456789abcdef", b"abcdef0123456789"
        plain = b'{"list":[{"vod_id":1}]}'
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        cipher = encryptor.update(padded) + encryptor.finalize()
        self.assertEqual(aes128_cbc_decrypt(cipher, key, iv), plain)

    def test_2423_aes_wrapper(self):
        key, iv_seed = b"0123456789abcdef", b"abcdefghijklm"
        iv = iv_seed + b"000"
        plain = b'{"list":[{"vod_id":3,"vod_name":"encrypted"}]}'
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        cipher = encryptor.update(padded) + encryptor.finalize()
        wrapped = "2423" + key.hex() + "2324" + cipher.hex() + iv_seed.hex()
        self.assertEqual(decode_2423(wrapped), plain)


    def test_live_playlist_recursive_wrapper_unwrap(self):
        responses = [
            SimpleNamespace(status_code=200, body=b"https://example.com/second.txt",
                             url="https://example.com/first.txt"),
            SimpleNamespace(status_code=200,
                             body=b"News,#genre#\nCCTV1,https://stream.example/live.m3u8\n",
                             url="https://example.com/second.txt"),
        ]
        calls = []

        def fake_fetch(url, **kwargs):
            calls.append(url)
            return responses[len(calls) - 1]

        result = fetch_live_playlist(
            "https://example.com/first.txt", "Test", fetcher=fake_fetch
        )
        self.assertEqual(result["status"], "已提取频道")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["name"], "CCTV1")
        self.assertEqual(len(result["chain"]), 2)
        self.assertEqual(result["final_url"], "https://example.com/second.txt")
        self.assertEqual(len(calls), 2)

    def test_live_playlist_wrapper_cycle_is_blocked(self):
        def fake_fetch(url, **kwargs):
            next_url = (
                "https://example.com/b.txt"
                if url.endswith("/a.txt") else "https://example.com/a.txt"
            )
            return SimpleNamespace(status_code=200, body=next_url.encode(), url=url)

        result = fetch_live_playlist(
            "https://example.com/a.txt", "Test", fetcher=fake_fetch
        )
        self.assertEqual(result["status"], "递归循环")
        self.assertEqual(len(result["chain"]), 3)


    def test_mirror_ranking_prefers_valid_fast_response(self):
        urls = ["https://slow.example/api", "https://fast.example/api", "https://dead.example/api"]
        results = {
            urls[0]: {"status": "有效影视 JSON", "seconds": 4.0, "http": 200},
            urls[1]: {"status": "有效影视 XML", "seconds": 0.5, "http": 200},
            urls[2]: {"status": "请求失败", "seconds": 8.0, "http": ""},
        }
        ranked = rank_mirror_candidates(urls, results)
        self.assertEqual(ranked[0]["url"], urls[1])
        self.assertTrue(ranked[0]["preferred"])
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertFalse(ranked[-1]["valid_payload"])
        self.assertGreater(mirror_health_score(results[urls[1]]),
                           mirror_health_score(results[urls[0]]))

    def test_ry_links_parser(self):
        links = parse_ry_links(
            "# comment\n示例包,https://example.com/a.json\nhttps://example.com/b.json\n"
            "重复|https://example.com/a.json\n"
        )
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0]["name"], "示例包")
        self.assertEqual(links[1]["url"], "https://example.com/b.json")

    def test_online_package_json_decoder(self):
        raw = json.dumps({"sites": [{"key": "demo"}]}).encode()
        package = parse_package_json(gzip.compress(base64.b64encode(raw)))
        self.assertEqual(package["sites"][0]["key"], "demo")

    def test_url_normalization_keeps_query(self):
        self.assertEqual(
            canonical_url("HTTPS://Example.COM:443/api/?token=abc#frag"),
            "https://example.com/api/?token=abc"
        )

    def test_flatten_live_json(self):
        rows = flatten_live_json([{
            "name": "央视频道",
            "channel": [{"name": "CCTV1", "urls": ["https://example.com/a.m3u8"]}]
        }])
        self.assertEqual(rows[0]["group"], "央视频道")
        self.assertEqual(rows[0]["name"], "CCTV1")
        grouped = group_live_channels(rows)
        self.assertEqual(grouped[0]["name"], "央视频道")
        self.assertEqual(grouped[0]["channel"][0]["urls"][0], "https://example.com/a.m3u8")

    def test_tvbox_live_aggregate_uses_per_source_backups_and_online_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup_dir = root / "sources" / "collected" / "live_backups"
            backup_dir.mkdir(parents=True)
            first_file = backup_dir / "first.m3u"
            cached_old_file = backup_dir / "second.m3u"
            first_file.write_text("#EXTM3U\n", encoding="utf-8")
            cached_old_file.write_text("#EXTM3U\n", encoding="utf-8")
            index_path = backup_dir / "index.json"
            index_path.write_text(json.dumps({
                "channel_count": 123,
                "results": [
                    {"url": "https://live.example/one.txt",
                     "saved_file": "sources/collected/live_backups/first.m3u",
                     "status": "直播列表已备份"},
                    {"url": "https://live.example/two.txt",
                     "saved_file": "sources/collected/live_backups/second.m3u",
                     "status": "下载失败，保留旧备份"},
                ],
            }), encoding="utf-8")
            sources = [
                {"name": "源一", "url": "https://live.example/one.txt",
                 "ua": "okhttp/3.12.13", "source_file": "sources/vod/a.json"},
                {"name": "源二", "url": "https://live.example/two.txt"},
                {"name": "源三", "url": "https://live.example/three.txt"},
            ]
            result = build_tvbox_live_aggregate(
                sources, "https://raw.example/tvbox-live.m3u",
                backup_index_path=index_path, root=root,
            )
            self.assertEqual(result["source_count"], 3)
            self.assertEqual(result["local_backup_count"], 2)
            self.assertEqual(result["online_fallback_count"], 1)
            self.assertEqual(result["channel_count"], 123)
            self.assertEqual(len(result["lives"]), 4)
            self.assertIn("first.m3u", result["lives"][0]["url"])
            self.assertIn("second.m3u", result["lives"][1]["url"])
            self.assertEqual(result["lives"][2]["url"], "https://live.example/three.txt")
            self.assertEqual(result["lives"][0]["ua"], "okhttp/3.12.13")
            self.assertEqual(result["lives"][-1]["name"], "TVBox-Config 本地聚合直播")

    def test_private_hosts_are_rejected(self):
        with self.assertRaises(FetchError):
            validate_public_url("http://127.0.0.1:9978/proxy")


if __name__ == "__main__":
    unittest.main()
