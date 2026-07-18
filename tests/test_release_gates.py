from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path, PurePosixPath

from scripts.verify_release import (
    EXPECTED_TOOLS,
    artifact_violations,
    check_source_contracts,
    ensure_output_membership,
    format_text,
    normalize_archive_member,
    verify_fresh_clone_consumer,
)


class ReleaseGateTests(unittest.TestCase):
    def test_archive_member_normalization_removes_only_sdist_root(self) -> None:
        self.assertEqual(
            normalize_archive_member(
                "cognitiveos-0.5.0/src/cognitiveos/__init__.py", strip_sdist_root=True
            ),
            PurePosixPath("src/cognitiveos/__init__.py"),
        )
        self.assertEqual(
            normalize_archive_member("cognitiveos/module.py"),
            PurePosixPath("cognitiveos/module.py"),
        )

    def test_artifact_privacy_allows_placeholders_and_rejects_private_or_derived_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            safe = Path(temp_dir) / "safe.whl"
            with zipfile.ZipFile(safe, "w") as archive:
                archive.writestr("cognitiveos/__init__.py", "")
            self.assertEqual(artifact_violations(safe), [])

            safe_sdist = Path(temp_dir) / "safe.tar.gz"
            with tarfile.open(safe_sdist, "w:gz") as archive:
                for name in ("00_Inbox/.gitkeep", "Assets/.gitkeep"):
                    member = tarfile.TarInfo(f"cognitiveos-0.5.0/{name}")
                    archive.addfile(member, io.BytesIO())
            self.assertEqual(artifact_violations(safe_sdist), [])

            unsafe = Path(temp_dir) / "unsafe.whl"
            with zipfile.ZipFile(unsafe, "w") as archive:
                archive.writestr("00_Inbox/private-note.md", "secret")
                archive.writestr(".pkm-index/index.sqlite3", "database")
                archive.writestr("runtime/index.sqlite3-wal", "sidecar")
                archive.writestr("models/weights.safetensors", "model")
            violations = artifact_violations(unsafe)
            self.assertTrue(any("private vault content" in item for item in violations))
            self.assertTrue(any("runtime or derived path" in item for item in violations))
            self.assertTrue(any("database or model artifact" in item for item in violations))

    def test_artifact_privacy_rejects_nonportable_duplicate_and_link_members(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unsafe = Path(temp_dir) / "unsafe.whl"
            link = zipfile.ZipInfo("linked-note")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(unsafe, "w") as archive:
                    archive.writestr("notes\\private.md", "secret")
                    archive.writestr("duplicate.txt", "first")
                    archive.writestr("duplicate.txt", "second")
                    archive.writestr(link, "00_Inbox/private-note.md")
            violations = artifact_violations(unsafe)
            self.assertTrue(any("non-portable archive path" in item for item in violations))
            self.assertTrue(any("duplicate archive member" in item for item in violations))
            self.assertTrue(any("link or special file" in item for item in violations))

    def test_output_membership_rejects_stale_or_unexpected_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            artifact = output_dir / "cognitiveos-0.5.0-py3-none-any.whl"
            report = output_dir / "report.json"
            artifact.write_bytes(b"wheel")
            report.write_text("{}", encoding="utf-8")
            ensure_output_membership(output_dir, [artifact], report)

            (output_dir / "stale-artifact.tar.gz").write_bytes(b"stale")
            with self.assertRaisesRegex(RuntimeError, "unexpected entries"):
                ensure_output_membership(output_dir, [artifact], report)

    def test_source_contract_gate_matches_package_and_read_only_mcp_surface(self) -> None:
        details = check_source_contracts()

        self.assertEqual(details["mcp_tools"], sorted(EXPECTED_TOOLS))
        self.assertEqual(details["writeback"], "disabled")

    def test_text_report_is_stable_and_includes_gate_status(self) -> None:
        report = {
            "schema": "cognitiveos-release-gates-v0.1",
            "status": "pass",
            "version": "0.5.0",
            "python": "3.14.6",
            "gates": [{"name": "tests", "status": "pass"}],
        }

        self.assertEqual(
            format_text(report),
            "\n".join(
                (
                    "CognitiveOS release gates cognitiveos-release-gates-v0.1",
                    "status=pass version=0.5.0 python=3.14.6",
                    "tests=pass",
                )
            ),
        )

    def test_fresh_clone_consumer_is_exposed_as_a_release_gate(self) -> None:
        self.assertTrue(callable(verify_fresh_clone_consumer))


if __name__ == "__main__":
    unittest.main()
