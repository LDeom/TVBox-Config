#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import gzip
import json
import unittest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from source_pipeline import (
    aes128_cbc_decrypt, canonical_url, flatten_live_json, group_live_channels, parse_playlist, strip_json_comments,
    valid_vod_payload,
)
from fetch_util import FetchError, validate_public_url


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
        self.assertEqual(grouped[0]["channel"][0]["urls"][0], "https://example.com/1.m3u8")

    def test_private_hosts_are_rejected(self):
        with self.assertRaises(FetchError):
            validate_public_url("http://127.0.0.1:9978/proxy")


if __name__ == "__main__":
    unittest.main()
