#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import json
import unittest
import zipfile
from pathlib import Path

from localize_tvbox_configs import (
    dependency_target,
    extract_dependency_urls,
    is_owned_github_url,
    local_raw_url,
    localize_config,
    replace_urls,
    validate_dependency,
)


class ConfigLocalizerTests(unittest.TestCase):
    def test_only_l_deom_raw_github_is_owned(self):
        self.assertTrue(is_owned_github_url(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/js/demo.js"
        ))
        self.assertTrue(is_owned_github_url(
            "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/js/demo.js"
        ))
        self.assertFalse(is_owned_github_url(
            "https://raw.githubusercontent.com/other/repo/main/demo.js"
        ))
        self.assertFalse(is_owned_github_url("https://example.com/demo.js"))

    def test_dependency_target_keeps_expected_type_directory(self):
        self.assertTrue(str(dependency_target(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/js/demo.js"
        )).endswith("sources/js/demo.js"))
        self.assertTrue(str(dependency_target(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/demo.jar"
        )).endswith("sources/jar/demo.jar"))
        self.assertTrue(str(dependency_target(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/json/demo.json"
        )).endswith("sources/dependencies/LDeom-tvbox/json/demo.json"))

    def test_extracts_urls_from_multi_ext(self):
        value = "https://raw.githubusercontent.com/LDeom/tvbox/master/lib/token.json$$$https://example.com/site$$$https://raw.githubusercontent.com/LDeom/tvbox/master/js/a.js"
        self.assertEqual(extract_dependency_urls(value), [
            "https://raw.githubusercontent.com/LDeom/tvbox/master/lib/token.json",
            "https://example.com/site",
            "https://raw.githubusercontent.com/LDeom/tvbox/master/js/a.js",
        ])

    def test_replaces_only_exact_dependency_urls(self):
        original = "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/fan.txt;md5;abcd"
        replacement = "https://raw.githubusercontent.com/LDeom/TVBox-Config/main/sources/jar/fan.txt"
        self.assertEqual(replace_urls(original, {
            "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/fan.txt": replacement
        }), replacement + ";md5;abcd")

    def test_localize_config_does_not_mutate_original(self):
        original = {
            "spider": "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/a.jar",
            "sites": [{"api": "csp_Test", "ext": {"json": "https://raw.githubusercontent.com/LDeom/tvbox/master/json/a.json"}}],
        }
        cloned = localize_config(original, {
            "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/a.jar": "https://local/a.jar",
            "https://raw.githubusercontent.com/LDeom/tvbox/master/json/a.json": "https://local/a.json",
        })
        self.assertEqual(original["spider"], "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/a.jar")
        self.assertEqual(cloned["spider"], "https://local/a.jar")
        self.assertEqual(cloned["sites"][0]["ext"]["json"], "https://local/a.json")
        self.assertEqual(json.loads(json.dumps(cloned))["sites"][0]["api"], "csp_Test")

    def test_validate_json_dependency(self):
        validate_dependency(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/json/a.json",
            b'{"sites":[]}'
        )
        with self.assertRaises(Exception):
            validate_dependency(
                "https://raw.githubusercontent.com/LDeom/tvbox/master/json/a.json",
                b"not-json"
            )


    def test_validate_json_with_comments_and_trailing_comma(self):
        validate_dependency(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/json/a.json",
            b'{\n  // comment\n  "sites": [],\n}'
        )

    def test_txt_extension_can_contain_valid_jar(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("demo/Example.class", b"class-bytes")
        validate_dependency(
            "https://raw.githubusercontent.com/LDeom/tvbox/master/jar/fan.txt",
            stream.getvalue()
        )

    def test_rejects_empty_dependency(self):
        with self.assertRaises(ValueError):
            validate_dependency(
                "https://raw.githubusercontent.com/LDeom/tvbox/master/js/a.js",
                b""
            )


if __name__ == "__main__":
    unittest.main()
