"""Catch undeclared package edits rather than trusting version metadata."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/voice_release/verify_sources.py"


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CHECKER.is_file(), "The source-integrity check is not implemented")
        spec = importlib.util.spec_from_file_location("verify_sources", CHECKER)
        self.checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.checker)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "pipecat"
        self.root.mkdir()
        (self.root / "core.py").write_bytes(b"CORE")
        (self.root / "extra.py").write_bytes(b"PATCH")
        self.records = {"core.py": hashlib.sha256(b"CORE").hexdigest()}
        self.overlays = {"extra.py": hashlib.sha256(b"PATCH").hexdigest()}

    def verify(self):
        return self.checker.verify_sources(self.root, self.records, self.overlays)

    def test_only_declared_exact_overlays_are_accepted(self):
        self.assertEqual(self.verify(), {
            "status": "pilot_source_integrity_verified",
            "recorded_python_files": 1, "declared_overlays": 1,
        })

    def test_changed_recorded_core_is_rejected(self):
        (self.root / "core.py").write_bytes(b"CHANGED")
        self.assertEqual(self.verify()["status"], "blocked_recorded_source_mismatch")

    def test_missing_recorded_source_is_rejected(self):
        (self.root / "core.py").unlink()
        self.assertEqual(self.verify()["status"], "blocked_missing_recorded_source")

    def test_added_python_modules_require_an_explicit_overlay(self):
        (self.root / "undeclared.py").write_bytes(b"UNDECLARED")
        self.assertEqual(self.verify()["status"], "blocked_undeclared_python_source")

    def test_wrong_overlay_contents_are_rejected(self):
        (self.root / "extra.py").write_bytes(b"OTHER")
        self.assertEqual(self.verify()["status"], "blocked_overlay_source_mismatch")

    def test_declared_overlay_can_replace_a_recorded_module(self):
        self.overlays["core.py"] = hashlib.sha256(b"REVIEWED CHANGE").hexdigest()
        (self.root / "core.py").write_bytes(b"REVIEWED CHANGE")
        self.assertEqual(self.verify()["status"], "pilot_source_integrity_verified")

    def test_paths_cannot_escape_the_package(self):
        self.overlays["../outside.py"] = hashlib.sha256(b"OUTSIDE").hexdigest()
        self.assertEqual(self.verify()["status"], "blocked_invalid_source_manifest")

    def test_symlinks_cannot_smuggle_source_from_outside_the_package(self):
        outside = Path(self.tmp.name) / "outside.py"
        outside.write_bytes(b"PATCH")
        (self.root / "extra.py").unlink()
        (self.root / "extra.py").symlink_to(outside)
        self.assertEqual(self.verify()["status"], "blocked_invalid_source_manifest")

    def test_bad_hashes_and_non_python_records_fail_closed(self):
        for name, digest in (("extra.py", "bad"), ("extra.py", True), ("../bad", "a" * 64)):
            with self.subTest(name=name, digest=digest):
                self.overlays = {name: digest}
                self.assertEqual(self.verify()["status"], "blocked_invalid_source_manifest")

    def test_missing_overlay_is_not_ignored(self):
        (self.root / "extra.py").unlink()
        self.assertEqual(self.verify()["status"], "blocked_overlay_source_mismatch")
