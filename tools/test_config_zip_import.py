#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from import_config_zip import import_payload, validate_archive


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


class ConfigZipImportTests(unittest.TestCase):
    def test_valid_archive_is_staged_without_touching_sources(self):
        payload = make_zip([
            ("bundle/config.json", json.dumps({"sites": []})),
            ("bundle/readme.txt", "说明"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = import_payload(payload, root)
            self.assertEqual(report["status"], "导入暂存成功")
            self.assertTrue((root / "imports/staging/bundle/config.json").is_file())
            self.assertFalse((root / "sources").exists())
            manifest = json.loads((root / "imports/staging/manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["file_count"], 2)

    def test_rejects_path_traversal(self):
        payload = make_zip([("../outside.txt", "bad")])
        with self.assertRaises(ValueError):
            validate_archive(payload)

    def test_rejects_reserved_manifest_filename(self):
        payload = make_zip([("manifest.json", "{}")])
        with self.assertRaises(ValueError):
            validate_archive(payload)

    def test_rejects_invalid_json_before_extracting(self):
        payload = make_zip([("bad.json", "{invalid")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = import_payload(payload, root)
            self.assertEqual(report["status"], "导入拒绝")
            self.assertFalse((root / "imports/staging").exists())

    def test_rejects_collision_instead_of_overwriting(self):
        payload = make_zip([("config.json", "{}")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = import_payload(payload, root)
            second = import_payload(payload, root)
            self.assertEqual(first["status"], "导入暂存成功")
            self.assertEqual(second["status"], "导入拒绝")
            self.assertEqual((root / "imports/staging/config.json").read_text("utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
