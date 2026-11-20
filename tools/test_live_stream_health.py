#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from live_stream_health import probe_stream


class LiveStreamHealthTests(unittest.TestCase):
    def test_hls_manifest_and_segment_are_both_checked(self):
        responses = [
            SimpleNamespace(status_code=200,
                             body=b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg001.ts\n",
                             url="https://media.example/live/index.m3u8", headers={"Content-Type":"application/vnd.apple.mpegurl"}),
            SimpleNamespace(status_code=206, body=b"\x47" * 64,
                             url="https://media.example/live/seg001.ts", headers={"Content-Type":"video/mp2t"})
        ]
        calls = []
        def fake_fetch(url, **kwargs):
            calls.append(url)
            return responses[len(calls)-1]
        result = probe_stream("https://media.example/live/index.m3u8", fake_fetch)
        self.assertEqual(result["level"], "hls_segment")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].endswith("seg001.ts"))

    def test_hls_master_playlist_checks_variant_media_segment(self):
        responses = [
            SimpleNamespace(status_code=200,
                body=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000\nvariant.m3u8\n",
                url="https://media.example/master.m3u8", headers={}),
            SimpleNamespace(status_code=200,
                body=b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg.ts\n",
                url="https://media.example/variant.m3u8", headers={}),
            SimpleNamespace(status_code=206, body=b"\x47" * 64,
                url="https://media.example/seg.ts", headers={})
        ]
        calls = []
        def fake_fetch(url, **kwargs):
            calls.append(url)
            return responses[len(calls)-1]
        result = probe_stream("https://media.example/master.m3u8", fake_fetch)
        self.assertEqual(result["level"], "hls_segment")
        self.assertTrue(calls[-1].endswith("seg.ts"))
        self.assertEqual(len(calls), 3)

    def test_direct_http_does_not_claim_playback_success(self):
        response = SimpleNamespace(status_code=200, body=b"stream bytes",
                                   url="https://media.example/live.ts",
                                   headers={"Content-Type":"video/mp2t"})
        result = probe_stream("https://media.example/live.ts",
                              lambda url, **kwargs: response)
        self.assertEqual(result["level"], "http_only")
        self.assertIn("未验证解码", result["status"])

    def test_http_failure_is_classified(self):
        response = SimpleNamespace(status_code=503, body=b"", url="https://media.example/a",
                                   headers={})
        result = probe_stream("https://media.example/a",
                              lambda url, **kwargs: response)
        self.assertEqual(result["level"], "http_failed")


if __name__ == "__main__":
    unittest.main()
