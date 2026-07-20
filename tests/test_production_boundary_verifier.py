"""Synthetic Linux-style tests for the deny-only production boundary foundation.

Every filesystem object here lives below a ``TemporaryDirectory``.  The test
adapters hold only ephemeral fixture keys; they do not contact a key service,
read local configuration, or reach the dormant writeback implementation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cognitiveos.production_boundary import (
    OWNER_ATTESTATION_SCHEMA_VERSION,
    DenialReason,
    DenyOnlyVerificationRequest,
    OwnerAttestation,
    OwnerAuthorityStatus,
    PolicySignatureStatus,
    ProductionBoundaryVerifier,
    SignedTopologyPolicy,
    canonical_policy_json,
    parse_signed_topology_policy,
    verify_pinned_topology,
)


FIXTURE_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_PROPOSAL_FINGERPRINT = "sha256:" + ("a" * 64)


def _identity(path: Path) -> str:
    info = os.lstat(path)
    return f"{info.st_dev}:{info.st_ino}"


def _fixture_proof(attestation: OwnerAttestation) -> bytes:
    value = "\0".join(
        (
            attestation.authority_id,
            attestation.audience,
            attestation.scope,
            attestation.proposal_fingerprint,
            attestation.policy_digest,
            attestation.topology_digest,
            attestation.issued_at,
            attestation.expires_at,
            attestation.nonce,
            str(attestation.key_epoch),
            str(attestation.revocation_epoch),
        )
    ).encode("ascii")
    return hmac.new(b"fixture-owner-authority-only", value, hashlib.sha256).digest()


class FixturePolicySignatureVerifier:
    """Ephemeral HMAC adapter standing in for external signer verification."""

    def __init__(self) -> None:
        self.status = PolicySignatureStatus.VALID
        self.calls = 0

    def sign(self, policy: dict[str, object]) -> SignedTopologyPolicy:
        policy_bytes = canonical_policy_json(policy)
        return SignedTopologyPolicy(
            policy_bytes=policy_bytes,
            signature=hmac.new(b"fixture-topology-policy-only", policy_bytes, hashlib.sha256).digest(),
            signer_id="fixture-policy-signer",
            key_epoch=7,
        )

    def verify_topology_policy_signature(
        self,
        *,
        policy_bytes: bytes,
        signature: bytes,
        signer_id: str,
        key_epoch: int,
    ) -> PolicySignatureStatus:
        self.calls += 1
        if self.status is not PolicySignatureStatus.VALID:
            return self.status
        expected = hmac.new(b"fixture-topology-policy-only", policy_bytes, hashlib.sha256).digest()
        if signer_id != "fixture-policy-signer" or key_epoch != 7 or not hmac.compare_digest(signature, expected):
            return PolicySignatureStatus.INVALID
        return PolicySignatureStatus.VALID


class FixtureNamespaceProvider:
    def __init__(self, value: str = "fixture-linux-namespace") -> None:
        self.value = value
        self.unavailable = False

    def current_namespace_identity(self) -> str:
        if self.unavailable:
            raise RuntimeError("fixture namespace unavailable")
        return self.value


class FixtureTrustedOwnerAuthority:
    """Read-only fixture authority with no issuing or consumption method."""

    def __init__(self) -> None:
        self.status = OwnerAuthorityStatus.VERIFIED
        self.calls = 0

    def verify_owner_attestation(self, *, attestation: OwnerAttestation, expectation: object) -> OwnerAuthorityStatus:
        self.calls += 1
        if self.status is not OwnerAuthorityStatus.VERIFIED:
            return self.status
        if not isinstance(attestation.proof, bytes) or not hmac.compare_digest(attestation.proof, _fixture_proof(attestation)):
            return OwnerAuthorityStatus.INVALID
        return OwnerAuthorityStatus.VERIFIED


class ProductionBoundaryVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temporary_root = Path(self.temporary.name)
        self.root = self.temporary_root / "linux-fixture"
        self.root.mkdir()
        (self.root / "vault").mkdir()
        audit = self.root / "audit"
        audit.mkdir()
        (audit / "journal.lock").write_bytes(b"fixture lock\n")
        (self.root / "audit-boundary").write_bytes(b"fixture boundary\n")
        self.outside = self.temporary_root / "outside-sentinel"
        self.outside.write_bytes(b"outside fixture bytes\n")
        self.outside_snapshot = self._snapshot(self.outside)
        self.signer = FixturePolicySignatureVerifier()
        self.namespace = FixtureNamespaceProvider()
        self.authority = FixtureTrustedOwnerAuthority()
        self.signed_policy = self.signer.sign(self._policy_value())
        self.parsed_policy = parse_signed_topology_policy(
            self.signed_policy,
            signature_verifier=self.signer,
            now=FIXTURE_NOW,
        )
        self.request = DenyOnlyVerificationRequest(
            proposal_fingerprint=_PROPOSAL_FINGERPRINT,
            audience="fixture-control-audience",
            scope="fixture-preflight-scope",
        )
        self.attestation = self._attestation()

    def tearDown(self) -> None:
        self.assertEqual(self.outside_snapshot, self._snapshot(self.outside))
        self.temporary.cleanup()

    def _snapshot(self, path: Path) -> tuple[bytes, int, int, int, int]:
        info = os.lstat(path)
        return (path.read_bytes(), info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns)

    def _policy_value(self) -> dict[str, object]:
        def role(path: str, parent: str, kind: str) -> dict[str, object]:
            info = os.lstat(self.root / path)
            return {
                "path": path,
                "parent": parent,
                "kind": kind,
                "identity": f"{info.st_dev}:{info.st_ino}",
                "link_count": info.st_nlink,
            }

        return {
            "schema_version": "production-boundary-policy/v1",
            "policy_id": "fixture-boundary-policy",
            "issuer": {"signer_id": "fixture-policy-signer", "key_epoch": 7},
            "issued_at": "2026-07-20T11:00:00Z",
            "expires_at": "2026-07-20T13:00:00Z",
            "topology": {
                "platform": "linux-descriptor-v1",
                "namespace_id": "fixture-linux-namespace",
                "anchor": {
                    "path": ".",
                    "identity": _identity(self.root),
                    "parent_identity": _identity(self.root.parent),
                },
                "roles": {
                    "vault-role": role("vault", "anchor", "directory"),
                    "audit-role": role("audit", "anchor", "directory"),
                    "lock-role": role("audit/journal.lock", "audit-role", "regular_file"),
                    "boundary-role": role("audit-boundary", "anchor", "regular_file"),
                },
            },
            "trusted_owner": {
                "authority_id": "fixture-owner-authority",
                "audience": "fixture-control-audience",
                "scope": "fixture-preflight-scope",
                "key_epoch": 3,
                "minimum_revocation_epoch": 2,
            },
        }

    def _attestation(self) -> OwnerAttestation:
        unsigned = OwnerAttestation(
            schema_version=OWNER_ATTESTATION_SCHEMA_VERSION,
            authority_id="fixture-owner-authority",
            audience="fixture-control-audience",
            scope="fixture-preflight-scope",
            proposal_fingerprint=_PROPOSAL_FINGERPRINT,
            policy_digest=self.parsed_policy.digest,
            topology_digest=self.parsed_policy.topology_digest,
            issued_at="2026-07-20T11:30:00Z",
            expires_at="2026-07-20T12:30:00Z",
            nonce="fixture-owner-nonce-001",
            key_epoch=3,
            revocation_epoch=2,
            proof=b"",
        )
        return replace(unsigned, proof=_fixture_proof(unsigned))

    def _verifier(self, *, signed_policy: SignedTopologyPolicy | None = None) -> ProductionBoundaryVerifier:
        return ProductionBoundaryVerifier(
            self.root,
            signed_policy=signed_policy or self.signed_policy,
            signature_verifier=self.signer,
            namespace_provider=self.namespace,
            owner_authority=self.authority,
            wall_clock=lambda: FIXTURE_NOW,
        )

    def _evaluate(self, *, verifier: ProductionBoundaryVerifier | None = None, attestation: OwnerAttestation | None = None):
        with mock.patch("cognitiveos.production_boundary._linux_descriptor_api_supported", return_value=True):
            return (verifier or self._verifier()).evaluate(request=self.request, attestation=attestation or self.attestation)

    def test_valid_disposable_evidence_still_ends_at_deny_only(self) -> None:
        decision = self._evaluate()

        self.assertEqual(DenialReason.DENY_ONLY, decision.reason)
        self.assertTrue(decision.denied)
        self.assertEqual(self.parsed_policy.digest, decision.policy_digest)
        self.assertEqual(self.parsed_policy.topology_digest, decision.topology_digest)
        self.assertTrue(decision.authority_checked)
        self.assertEqual(1, self.authority.calls)

    def test_source_has_no_writer_or_mcp_dependency(self) -> None:
        source = inspect.getsource(ProductionBoundaryVerifier)

        self.assertNotIn("AtomicSingleFileApplier", source)
        self.assertNotIn("ApplyOutcome", source)
        self.assertNotIn("mcp_server", source)
        self.assertNotIn("write_sink", source)

    def test_policy_requires_canonical_signed_current_evidence(self) -> None:
        cases: list[tuple[str, SignedTopologyPolicy, DenialReason]] = []
        cases.append(
            (
                "noncanonical",
                replace(self.signed_policy, policy_bytes=self.signed_policy.policy_bytes + b"\n"),
                DenialReason.POLICY_NOT_CANONICAL,
            )
        )
        expired = self._policy_value()
        expired["expires_at"] = "2026-07-20T11:59:59Z"
        cases.append(("expired", self.signer.sign(expired), DenialReason.POLICY_EXPIRED))
        not_yet = self._policy_value()
        not_yet["issued_at"] = "2026-07-20T12:00:01Z"
        cases.append(("not_yet_valid", self.signer.sign(not_yet), DenialReason.POLICY_NOT_YET_VALID))
        cases.append(
            (
                "envelope_issuer_mismatch",
                replace(self.signed_policy, signer_id="other-policy-signer"),
                DenialReason.POLICY_EVIDENCE_MALFORMED,
            )
        )
        for label, signed_policy, reason in cases:
            with self.subTest(label=label):
                decision = self._evaluate(verifier=self._verifier(signed_policy=signed_policy))
                self.assertEqual(reason, decision.reason)
                self.assertFalse(decision.authority_checked)

    def test_policy_signature_statuses_fail_closed(self) -> None:
        expected = {
            PolicySignatureStatus.INVALID: DenialReason.POLICY_SIGNATURE_INVALID,
            PolicySignatureStatus.UNAVAILABLE: DenialReason.POLICY_SIGNATURE_UNAVAILABLE,
            PolicySignatureStatus.REVOKED: DenialReason.POLICY_SIGNATURE_REVOKED,
            PolicySignatureStatus.ROTATED: DenialReason.POLICY_SIGNATURE_ROTATED,
        }
        for status, reason in expected.items():
            with self.subTest(status=status):
                self.signer.status = status
                decision = self._evaluate()
                self.assertEqual(reason, decision.reason)
                self.assertFalse(decision.authority_checked)
        self.signer.status = PolicySignatureStatus.VALID

    def test_namespace_platform_and_topology_unavailability_fail_closed(self) -> None:
        self.namespace.unavailable = True
        self.assertEqual(DenialReason.NAMESPACE_EVIDENCE_UNAVAILABLE, self._evaluate().reason)
        self.namespace.unavailable = False
        self.namespace.value = "other-linux-namespace"
        self.assertEqual(DenialReason.NAMESPACE_EVIDENCE_MISMATCH, self._evaluate().reason)
        self.namespace.value = "fixture-linux-namespace"
        with mock.patch("cognitiveos.production_boundary._linux_descriptor_api_supported", return_value=False):
            decision = self._verifier().evaluate(request=self.request, attestation=self.attestation)
        self.assertEqual(DenialReason.TOPOLOGY_DESCRIPTOR_UNSUPPORTED, decision.reason)

    def test_unexpected_topology_entry_and_anchor_replacement_are_denied(self) -> None:
        extra = self.root / "unexpected-entry"
        extra.write_bytes(b"fixture unexpected\n")
        self.assertEqual(DenialReason.TOPOLOGY_UNEXPECTED_ENTRY, self._evaluate().reason)
        extra.unlink()

        replacement = self.temporary_root / "replacement-root"
        replacement.mkdir()
        self.root.rename(self.temporary_root / "original-root")
        replacement.rename(self.root)
        self.assertEqual(DenialReason.TOPOLOGY_IDENTITY_MISMATCH, self._evaluate().reason)

    def test_symlink_hard_link_and_special_file_topology_entries_are_denied(self) -> None:
        vault = self.root / "vault"
        vault.rmdir()
        os.symlink(self.outside, vault)
        self.assertEqual(DenialReason.TOPOLOGY_SYMLINK, self._evaluate().reason)

        vault.unlink()
        vault.mkdir()
        boundary = self.root / "audit-boundary"
        boundary.unlink()
        os.link(self.root / "audit" / "journal.lock", boundary)
        self.assertEqual(DenialReason.TOPOLOGY_HARD_LINK, self._evaluate().reason)

        boundary.unlink()
        os.mkfifo(boundary)
        self.assertEqual(DenialReason.TOPOLOGY_SPECIAL_FILE, self._evaluate().reason)

    def test_descriptor_substitution_race_is_denied(self) -> None:
        replacement = self.temporary_root / "replacement-boundary"
        replacement.write_bytes(b"replacement fixture boundary\n")
        raced = False

        def descriptor_opener(name: str, flags: int, parent_fd: int) -> int:
            nonlocal raced
            if name == "audit-boundary" and not raced:
                raced = True
                os.replace(replacement, self.root / "audit-boundary")
            return os.open(name, flags, dir_fd=parent_fd)

        with mock.patch("cognitiveos.production_boundary._linux_descriptor_api_supported", return_value=True):
            with self.assertRaisesRegex(ValueError, DenialReason.TOPOLOGY_DESCRIPTOR_RACE.value):
                verify_pinned_topology(self.root, policy=self.parsed_policy, descriptor_opener=descriptor_opener)
        self.assertTrue(raced)

    def test_authority_bindings_fail_before_the_external_authority_is_called(self) -> None:
        replacements = {
            "authority_id": ("other-owner-authority", DenialReason.AUTHORITY_ID_MISMATCH),
            "audience": ("other-control-audience", DenialReason.AUTHORITY_AUDIENCE_MISMATCH),
            "scope": ("other-preflight-scope", DenialReason.AUTHORITY_SCOPE_MISMATCH),
            "proposal_fingerprint": ("sha256:" + ("b" * 64), DenialReason.AUTHORITY_PROPOSAL_MISMATCH),
            "policy_digest": ("sha256:" + ("c" * 64), DenialReason.AUTHORITY_POLICY_MISMATCH),
            "topology_digest": ("sha256:" + ("d" * 64), DenialReason.AUTHORITY_TOPOLOGY_MISMATCH),
            "key_epoch": (4, DenialReason.AUTHORITY_KEY_EPOCH_MISMATCH),
            "revocation_epoch": (1, DenialReason.AUTHORITY_REVOKED),
        }
        for field, (value, reason) in replacements.items():
            with self.subTest(field=field):
                self.authority.calls = 0
                decision = self._evaluate(attestation=replace(self.attestation, **{field: value}))
                self.assertEqual(reason, decision.reason)
                self.assertFalse(decision.authority_checked)
                self.assertEqual(0, self.authority.calls)

    def test_authority_expiry_malformed_and_status_denials_fail_closed(self) -> None:
        expired = replace(self.attestation, expires_at="2026-07-20T11:59:59Z")
        self.assertEqual(DenialReason.AUTHORITY_EXPIRED, self._evaluate(attestation=expired).reason)
        not_yet = replace(self.attestation, issued_at="2026-07-20T12:00:01Z")
        self.assertEqual(DenialReason.AUTHORITY_NOT_YET_VALID, self._evaluate(attestation=not_yet).reason)
        malformed = replace(self.attestation, nonce="short")
        self.assertEqual(DenialReason.AUTHORITY_EVIDENCE_MALFORMED, self._evaluate(attestation=malformed).reason)

        expected = {
            OwnerAuthorityStatus.INVALID: DenialReason.AUTHORITY_INVALID,
            OwnerAuthorityStatus.UNAVAILABLE: DenialReason.AUTHORITY_UNAVAILABLE,
            OwnerAuthorityStatus.REVOKED: DenialReason.AUTHORITY_REVOKED,
            OwnerAuthorityStatus.REPLAYED: DenialReason.AUTHORITY_REPLAYED,
            OwnerAuthorityStatus.ROTATED: DenialReason.AUTHORITY_ROTATED,
        }
        for status, reason in expected.items():
            with self.subTest(status=status):
                self.authority.status = status
                decision = self._evaluate()
                self.assertEqual(reason, decision.reason)
                self.assertTrue(decision.authority_checked)
        self.authority.status = OwnerAuthorityStatus.VERIFIED

    def test_invalid_opaque_proof_is_denied_by_the_external_authority(self) -> None:
        altered = replace(self.attestation, proof=b"not-the-fixture-proof")

        decision = self._evaluate(attestation=altered)

        self.assertEqual(DenialReason.AUTHORITY_INVALID, decision.reason)
        self.assertTrue(decision.authority_checked)


if __name__ == "__main__":
    unittest.main()
