"""Small failure-path checks for the delivery verifier; no application DB needed."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_delivery import digest, verify


class DeliveryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "payload").write_bytes(b"verified")
        self.value = {"status": "CANDIDATE_NOT_ACCEPTED", "files": {"payload": digest(self.root / "payload")}}
        self.publish()

    def publish(self):
        self.manifest = self.root / "delivery-manifest.json"
        self.manifest.write_text(json.dumps(self.value))
        self.trusted = digest(self.manifest)

    def test_valid_candidate(self):
        self.assertEqual(verify(self.root, self.trusted), 1)

    def test_tampered_payload(self):
        (self.root / "payload").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "ARTIFACT_MISMATCH"):
            verify(self.root, self.trusted)

    def test_missing_payload(self):
        (self.root / "payload").unlink()
        with self.assertRaisesRegex(ValueError, "ARTIFACT_MISMATCH"):
            verify(self.root, self.trusted)

    def test_extra_payload(self):
        (self.root / "unexpected").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "UNMANIFESTED_CONTENT"):
            verify(self.root, self.trusted)

    def test_path_traversal(self):
        self.value["files"] = {"../payload": hashlib.sha256(b"verified").hexdigest()}
        self.publish()
        with self.assertRaisesRegex(ValueError, "INVALID_MANIFEST_ENTRY"):
            verify(self.root, self.trusted)

    def test_manifest_hash_and_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError, "MANIFEST_HASH_MISMATCH"):
            verify(self.root, "0" * 64)
        self.manifest.write_text('{"status":"CANDIDATE_NOT_ACCEPTED","files":{},"files":{}}')
        with self.assertRaisesRegex(ValueError, "DUPLICATE_MANIFEST_KEY"):
            verify(self.root, digest(self.manifest))

    def test_symlink(self):
        (self.root / "alias").symlink_to(self.root / "payload")
        self.value["files"]["alias"] = digest(self.root / "payload")
        self.publish()
        with self.assertRaisesRegex(ValueError, "SYMLINK_IN_DELIVERY"):
            verify(self.root, self.trusted)


if __name__ == "__main__":
    unittest.main()
