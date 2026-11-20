#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from localize_tvbox_configs import (
    dependency_target, dependency_urls, extract_dependency_urls,
    fetch_dependency, is_owned_github_url, is_supported_dependency_url,
    localize_config, replace_urls, validate_dependency,
)


def make_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return stream.getvalue()


class ConfigLocalizerTests(unittest.TestCase):
    def test_owned_github_detection(self):
        self.assertTrue(is_owned_github_url("https://raw.githubusercontent.com/LDeom/tvbox/master/js/demo.js"))
        self.assertFalse(is_owned_github_url("https://raw.githubusercontent.com/other/repo/main/demo.js"))
        self.assertFalse(is_owned_github_url("https://example.com/demo.js"))

    def test_extension_allowlist_and_blacklist(self):
        for ext in (".js", ".jar", ".py", ".json", ".txt", ".png", ".jpg",
                    ".jpeg", ".gif", ".webp", ".zip", ".apk", ".node"):
            self.assertTrue(is_supported_dependency_url(f"https://cdn.example.test/assets/file{ext}"), ext)
        for ext in (".m3u", ".m3u8", ".xml", ".mp4", ".php"):
            self.assertFalse(is_supported_dependency_url(f"https://cdn.example.test/assets/file{ext}"), ext)
        self.assertFalse(is_supported_dependency_url("file:///tmp/a.js"))

    def test_owned_dependency_target_keeps_existing_layout(self):
        self.assertTrue(str(dependency_target("https://raw.githubusercontent.com/LDeom/tvbox/master/js/demo.js")).endswith("sources/js/demo.js"))
        self.assertTrue(str(dependency_target("https://raw.githubusercontent.com/LDeom/tvbox/master/jar/demo.jar")).endswith("sources/jar/demo.jar"))
        self.assertTrue(str(dependency_target("https://raw.githubusercontent.com/LDeom/tvbox/master/json/demo.json")).endswith("sources/dependencies/LDeom-tvbox/demo.json"))

    def test_external_dependency_path_is_stable_and_host_scoped(self):
        first = dependency_target("https://cdn.example.test/plugins/demo%20file.js?token=one")
        second = dependency_target("https://cdn.example.test/plugins/demo%20file.js?token=two")
        other = dependency_target("https://other.example.test/plugins/demo%20file.js")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(str(first).endswith("sources/dependencies/external/cdn.example.test/plugins/demo file.js"))

    def test_rejects_path_traversal(self):
        self.assertIsNone(dependency_target("https://cdn.example.test/%2e%2e/%2e%2e/escape.js"))
        self.assertIsNone(dependency_target("https://raw.githubusercontent.com/LDeom/tvbox/master/js/%2e%2e/escape.js"))

    def test_extracts_supported_urls_and_blacklists_playlists(self):
        value = ("https://cdn.example.test/a.js$$$https://cdn.example.test/logo.webp"
                 "$$$https://cdn.example.test/list.m3u$$$https://cdn.example.test/config.xml"
                 "$$$https://cdn.example.test/file.node")
        self.assertEqual(extract_dependency_urls(value), [
            "https://cdn.example.test/a.js",
            "https://cdn.example.test/logo.webp",
            "https://cdn.example.test/file.node",
        ])

    def test_dependency_urls_includes_common_assets_and_site_fields(self):
        config = {
            "spider": "https://cdn.example.test/spider.jar",
            "wallpaper": "https://cdn.example.test/bg.webp",
            "logo": "https://cdn.example.test/logo.png",
            "sites": [{"api": "https://cdn.example.test/site.json",
                       "ext": {"file": "https://cdn.example.test/ext.zip"}}],
            "lives": [{"url": "https://cdn.example.test/live.m3u"}],
        }
        urls = dependency_urls(config)
        self.assertEqual(len(urls), 5)
        self.assertNotIn("https://cdn.example.test/live.m3u", urls)

    def test_replaces_exact_urls_and_preserves_suffix(self):
        original = "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/fan.txt;md5;abcd"
        replacement = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/jar/fan.txt"
        self.assertEqual(replace_urls(original, {
            "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/fan.txt": replacement
        }), replacement + ";md5;abcd")

    def test_localize_config_does_not_mutate_original_and_recurses(self):
        original = {"spider": "https://cdn.example.test/spider.jar",
                    "wallpaper": "https://cdn.example.test/bg.webp",
                    "sites": [{"api": "csp_Test", "ext": {"json": "https://cdn.example.test/ext.json"}}]}
        localized = localize_config(original, {
            "https://cdn.example.test/spider.jar": "https://local/spider.jar",
            "https://cdn.example.test/bg.webp": "https://local/bg.webp",
            "https://cdn.example.test/ext.json": "https://local/ext.json",
        })
        self.assertEqual(original["spider"], "https://cdn.example.test/spider.jar")
        self.assertEqual(localized["spider"], "https://local/spider.jar")
        self.assertEqual(localized["wallpaper"], "https://local/bg.webp")
        self.assertEqual(localized["sites"][0]["ext"]["json"], "https://local/ext.json")
        self.assertEqual(localized["sites"][0]["api"], "csp_Test")

    def test_validate_json_comments_and_invalid_json(self):
        validate_dependency("https://cdn.example.test/config.json", b'{"sites":[]}')
        validate_dependency("https://cdn.example.test/config.json", b'{\n // comment\n "sites": [],\n}')
        with self.assertRaises(Exception):
            validate_dependency("https://cdn.example.test/config.json", b"not-json")

    def test_validate_text_and_invalid_utf8(self):
        validate_dependency("https://cdn.example.test/plugin.js", b"const a = 1;")
        with self.assertRaises(UnicodeDecodeError):
            validate_dependency("https://cdn.example.test/plugin.py", b"\xff\xfe")

    def test_validate_jar_and_txt_wrapped_jar(self):
        jar = make_zip({"demo/Example.class": b"class-bytes"})
        validate_dependency("https://cdn.example.test/demo.jar", jar)
        validate_dependency("https://cdn.example.test/demo.txt", jar)
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/empty.jar", make_zip({"readme.txt": b"x"}))

    def test_validate_zip_and_apk(self):
        validate_dependency("https://cdn.example.test/archive.zip", make_zip({"readme.txt": b"ok"}))
        apk = make_zip({"AndroidManifest.xml": b"manifest", "classes.dex": b"dex"})
        validate_dependency("https://cdn.example.test/app.apk", apk)
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/not-apk.apk", make_zip({"readme.txt": b"x"}))

    def test_validate_image_signatures(self):
        validate_dependency("https://cdn.example.test/a.png", b"\x89PNG\r\n\x1a\nrest")
        validate_dependency("https://cdn.example.test/a.jpg", b"\xff\xd8\xffrest")
        validate_dependency("https://cdn.example.test/a.gif", b"GIF89arest")
        validate_dependency("https://cdn.example.test/a.webp", b"RIFFxxxxWEBPrest")
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/a.png", b"not-image")

    def test_validate_node_binary_signature(self):
        validate_dependency("https://cdn.example.test/addon.node", b"\x7fELF" + b"\x00" * 20)
        validate_dependency("https://cdn.example.test/addon.node", b"MZ" + b"\x00" * 20)
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/addon.node", b"not-native")

    def test_rejects_empty_and_oversized_dependency(self):
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/a.js", b"")
        with self.assertRaises(ValueError):
            validate_dependency("https://cdn.example.test/a.js", b"x" * (32 * 1024 * 1024 + 1))

    def test_external_refresh_overwrites_same_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "same" / "asset.js"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old")
            fake = SimpleNamespace(status_code=200, body=b"const updated = true;")
            with patch("localize_tvbox_configs.fetch_bytes", return_value=fake):
                status, _ = fetch_dependency("https://cdn.example.test/asset.js", target, refresh=True)
            self.assertEqual(status, "依赖已下载并覆盖")
            self.assertEqual(target.read_bytes(), b"const updated = true;")
            self.assertFalse(target.with_name(target.name + ".tmp").exists())

    def test_failed_refresh_preserves_existing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.js"
            target.write_bytes(b"old")
            with patch("localize_tvbox_configs.fetch_bytes", side_effect=OSError("network")):
                status, _ = fetch_dependency("https://cdn.example.test/asset.js", target, refresh=True)
            self.assertEqual(status, "下载失败")
            self.assertEqual(target.read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
