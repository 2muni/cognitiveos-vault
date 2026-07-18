from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cognitiveos.approval import sha256_checksum
from cognitiveos.atomic_apply import AtomicSingleFileApplier, provision_audit_boundary
from cognitiveos.writeback_proposal import (
    ProposalValidationError,
    compute_proposal_fingerprint,
    render_unified_byte_diff_v1,
    validate_proposal,
)

from writeback_support import TestOwnerAuthority


class ProposalContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name) / "vault"
        (root / "Notes").mkdir(parents=True)
        audit = Path(self.temporary.name) / "audit"
        audit.mkdir(mode=0o700)
        audit_boundary = Path(self.temporary.name) / "audit-boundary"
        provision_audit_boundary(audit, audit_key=b"v" * 32, boundary_path=audit_boundary)
        root.chmod(0o555)
        self.root = root
        self.temporary_root = Path(self.temporary.name)
        self.temporary_root.chmod(0o500)
        self.applier = AtomicSingleFileApplier(
            root,
            allowed_roots=("Notes",),
            audit_directory=audit,
            audit_boundary_path=audit_boundary,
            owner_authority=TestOwnerAuthority(),
            audit_key=b"v" * 32,
        )

    def tearDown(self) -> None:
        self.applier.close()
        self.root.chmod(0o700)
        self.temporary_root.chmod(0o700)
        self.temporary.cleanup()

    def valid_absent(self) -> dict[str, object]:
        return self.applier.propose(operation="create_absent", path="Notes/schema.md", proposed_bytes=b"after\r\n\xff")

    def validate(self, proposal: dict[str, object], *, base: bytes = b"") -> None:
        target = proposal["target"]
        metadata = proposal["metadata"]
        assert isinstance(target, dict)
        assert isinstance(metadata, dict)
        validate_proposal(
            proposal,
            base_bytes=base,
            expected_vault_root_id=target["vault_root_id"],
            expected_allowed_root_id=target["allowed_root_id"],
            expected_server_instance_id=metadata["server_instance_id"],
        )

    def test_valid_absent_and_existing_records_are_accepted(self) -> None:
        absent = self.valid_absent()
        self.validate(absent)

        base = b"before\r\n\x80"
        existing = copy.deepcopy(absent)
        target = existing["target"]
        change = existing["change"]
        assert isinstance(target, dict)
        assert isinstance(change, dict)
        existing["operation"] = "replace_existing"
        target["kind"] = "existing_regular_file"
        target["file_identity"] = "file-1"
        existing["base"] = {"existence": "present", "checksum": sha256_checksum(base)}
        review = change["review"]
        assert isinstance(review, dict)
        proposed = base64.b64decode(change["proposed_bytes_base64"])
        rendered = render_unified_byte_diff_v1(path="Notes/schema.md", base_bytes=base, proposed_bytes=proposed, absent=False)
        review["rendered_diff"] = rendered
        review["rendered_diff_checksum"] = sha256_checksum(rendered.encode("utf-8"))
        existing["proposal_fingerprint"] = compute_proposal_fingerprint(existing)

        self.validate(existing, base=base)

    def test_adversarial_contract_inputs_are_rejected_without_coercion(self) -> None:
        mutations = {
            "unknown top-level field": lambda p: p.update({"future": True}),
            "wrong schema": lambda p: p.update({"schema_version": "writeback-proposal/v0.9"}),
            "malformed id": lambda p: p.update({"proposal_id": "has space"}),
            "bad checksum": lambda p: p.update({"proposal_fingerprint": "sha256:ABC"}),
            "bad base64": lambda p: p["change"].update({"proposed_bytes_base64": "@@@"}),
            "wrong byte length": lambda p: p["change"].update({"proposed_byte_length": 999}),
            "unsupported operation": lambda p: p.update({"operation": "delete"}),
            "unsupported representation": lambda p: p["change"].update({"representation": "patch"}),
            "absolute path": lambda p: p["target"].update({"path": "/Notes/schema.md"}),
            "path traversal": lambda p: p["target"].update({"path": "Notes/../schema.md"}),
            "non markdown": lambda p: p["target"].update({"path": "Notes/schema.txt"}),
            "root identity mismatch": lambda p: p["target"].update({"vault_root_id": "vault-other"}),
            "changed path mismatch": lambda p: p["scope"].update({"changed_paths": ["Notes/other.md"]}),
            "multi file count": lambda p: p["scope"].update({"changed_path_count": 2}),
            "multi file paths": lambda p: p["scope"].update({"changed_paths": ["Notes/schema.md", "Notes/other.md"]}),
            "bulk": lambda p: p["scope"].update({"bulk": True}),
            "destructive": lambda p: p["scope"].update({"destructive": True}),
            "too long expiry": lambda p: p["metadata"].update({"expires_at": "2030-01-01T00:11:00Z"}),
            "bad timestamp": lambda p: p["metadata"].update({"issued_at": "not-a-time"}),
            "absent has checksum": lambda p: p["base"].update({"checksum": "sha256:" + "a" * 64}),
            "absent has identity": lambda p: p["target"].update({"file_identity": "file-1"}),
            "proposed checksum mismatch": lambda p: p["change"].update({"proposed_checksum": "sha256:" + "b" * 64}),
            "preview checksum mismatch": lambda p: p["change"]["review"].update({"rendered_diff_checksum": "sha256:" + "c" * 64}),
            "preview regeneration mismatch": lambda p: p["change"]["review"].update({"rendered_diff": "truncated"}),
            "fingerprint mismatch": lambda p: p.update({"proposal_fingerprint": "sha256:" + "d" * 64}),
            "unknown nested field": lambda p: p["approval"].update({"extra": "no"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                proposal = copy.deepcopy(self.valid_absent())
                mutate(proposal)
                with self.assertRaises(ProposalValidationError):
                    self.validate(proposal)

    def test_preview_is_exact_for_crlf_final_newline_and_non_utf8_bytes(self) -> None:
        proposal = self.valid_absent()
        rendered = proposal["change"]["review"]["rendered_diff"]
        self.assertIn("absent", rendered)
        self.assertIn("\\x0d\\x0a", rendered)
        self.assertIn("\\xff", rendered)
        self.assertNotIn(str(self.temporary.name), rendered)
        self.validate(proposal)

    def test_only_canonical_padded_rfc4648_base64_is_accepted(self) -> None:
        proposal = self.applier.propose(operation="create_absent", path="Notes/base64.md", proposed_bytes=b"f")
        for spelling in ("Zh==", "Zg", "Zg==\n", "-g=="):
            with self.subTest(spelling=repr(spelling)):
                altered = copy.deepcopy(proposal)
                change = altered["change"]
                assert isinstance(change, dict)
                change["proposed_bytes_base64"] = spelling
                altered["proposal_fingerprint"] = compute_proposal_fingerprint(altered)
                with self.assertRaisesRegex(ProposalValidationError, "malformed_base64"):
                    self.validate(altered)

    def test_expiry_is_limited_to_ten_minutes_from_issued_at(self) -> None:
        proposal = self.valid_absent()
        metadata = proposal["metadata"]
        assert isinstance(metadata, dict)
        issued = datetime.fromisoformat(metadata["issued_at"].replace("Z", "+00:00"))
        metadata["expires_at"] = (issued + timedelta(seconds=601)).isoformat().replace("+00:00", "Z")
        proposal["proposal_fingerprint"] = compute_proposal_fingerprint(proposal)
        with self.assertRaises(ProposalValidationError):
            self.validate(proposal)


if __name__ == "__main__":
    unittest.main()
