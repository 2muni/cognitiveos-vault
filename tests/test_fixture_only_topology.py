from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from cognitiveos.approval import OwnerConfirmation
from cognitiveos.atomic_apply import AtomicSingleFileApplier

from fixture_only_topology import (
    FakeOpaqueHandleTrustedOwnerAuthority,
    FixtureAuthorityBinding,
    FixtureAuthorityRefused,
    FixtureOnlyDenyGate,
    FixtureTopologyRefused,
    FixtureTopologyVerifier,
    FIXTURE_AUDIENCE,
    FIXTURE_POLICY_DIGEST,
    capture_canonical_manifest,
    compute_fixture_preflight_digest,
    parse_canonical_manifest,
)


class RecordingWriteSink:
    """A writer-shaped test double that must remain untouched by the deny gate."""

    def __init__(self) -> None:
        self.calls = 0

    def write(self, *_: object, **__: object) -> None:
        self.calls += 1
        raise AssertionError("fixture-only gate must never call a write sink")


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FixtureOnlyTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temporary_root = Path(self.temporary.name)
        self.fixture_root = self.temporary_root / "fixture"
        self.fixture_root.mkdir()
        (self.fixture_root / "vault").mkdir()
        audit = self.fixture_root / "audit"
        audit.mkdir()
        (audit / "journal.lock").write_bytes(b"fixture lock\n")
        (self.fixture_root / "audit-boundary").write_bytes(b"fixture boundary\n")
        self.outside = self.temporary_root / "outside-sentinel"
        self.outside.write_bytes(b"outside fixture bytes\n")
        self.outside_snapshot = self._outside_snapshot()
        self.manifest = capture_canonical_manifest(self.fixture_root)
        self.topology_digest = parse_canonical_manifest(self.manifest).digest
        self.clock = MutableClock(datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
        self.authority = FakeOpaqueHandleTrustedOwnerAuthority(clock=self.clock)

    def tearDown(self) -> None:
        self.assertEqual(0, self._out_of_fixture_mutation_count())
        self.temporary.cleanup()

    def _outside_snapshot(self) -> tuple[bytes, int, int, int, int, int]:
        info = os.lstat(self.outside)
        return (
            self.outside.read_bytes(),
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_mtime_ns,
            info.st_nlink,
        )

    def _out_of_fixture_mutation_count(self) -> int:
        return int(self._outside_snapshot() != self.outside_snapshot)

    def binding(self, *, nonce: str = "fixture-nonce-0001") -> FixtureAuthorityBinding:
        policy_digest = FIXTURE_POLICY_DIGEST
        return FixtureAuthorityBinding(
            proposal_fingerprint="sha256:" + ("b" * 64),
            audience=FIXTURE_AUDIENCE,
            operation="create_absent",
            topology_digest=self.topology_digest,
            policy_digest=policy_digest,
            preflight_digest=compute_fixture_preflight_digest(
                operation="create_absent",
                topology_digest=self.topology_digest,
                policy_digest=policy_digest,
            ),
            expires_at="2026-07-19T12:05:00Z",
            nonce=nonce,
            revocation_epoch=self.authority.revocation_epoch,
        )

    def issue(self, binding: FixtureAuthorityBinding | None = None) -> tuple[FixtureAuthorityBinding, OwnerConfirmation]:
        issued_binding = binding or self.binding()
        return issued_binding, self.authority.issue_confirmation(
            proposal_id="fixture-proposal-0001",
            binding=issued_binding,
        )

    def test_canonical_manifest_parses_and_descriptor_verifier_accepts_the_synthetic_topology(self) -> None:
        parsed = parse_canonical_manifest(self.manifest)

        verified = FixtureTopologyVerifier(self.fixture_root).verify(self.manifest)

        self.assertEqual(parsed, verified)
        self.assertEqual(self.topology_digest, verified.digest)

    def test_manifest_rejects_noncanonical_and_non_strict_variants(self) -> None:
        decoded = json.loads(self.manifest)
        variants: list[object] = [
            self.manifest + b"\n",
            b"{not-json}",
            "not bytes",
            {**decoded, "schema_version": "fixture-only-topology/v0"},
            {**decoded, "roles": {key: value for key, value in decoded["roles"].items() if key != "lock"}},
        ]
        extra_field = json.loads(self.manifest)
        extra_field["roles"]["root"]["unexpected"] = True
        variants.append(json.dumps(extra_field, separators=(",", ":"), sort_keys=True).encode("ascii"))
        traversal = json.loads(self.manifest)
        traversal["roles"]["boundary"]["path"] = "../audit-boundary"
        variants.append(json.dumps(traversal, separators=(",", ":"), sort_keys=True).encode("ascii"))
        wrong_ancestry = json.loads(self.manifest)
        wrong_ancestry["roles"]["lock"]["parent"] = "anchor"
        variants.append(json.dumps(wrong_ancestry, separators=(",", ":"), sort_keys=True).encode("ascii"))
        alias = json.loads(self.manifest)
        alias["roles"]["boundary"]["identity"] = alias["roles"]["lock"]["identity"]
        variants.append(json.dumps(alias, separators=(",", ":"), sort_keys=True).encode("ascii"))

        for payload in variants:
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(FixtureTopologyRefused):
                    parse_canonical_manifest(payload)

    def test_identity_and_ancestry_changes_are_refused_before_any_sink_call(self) -> None:
        verifier = FixtureTopologyVerifier(self.fixture_root)
        sink = RecordingWriteSink()
        binding, confirmation = self.issue()
        gate = FixtureOnlyDenyGate(topology_verifier=verifier, authority=self.authority, write_sink=sink)
        replacement = self.fixture_root / "audit-replacement"
        replacement.mkdir()
        (replacement / "journal.lock").write_bytes(b"replacement lock\n")
        shutil.rmtree(self.fixture_root / "audit")
        os.rename(replacement, self.fixture_root / "audit")

        decision = gate.evaluate(
            manifest=self.manifest,
            confirmation=confirmation,
            proposal_id="fixture-proposal-0001",
            binding=binding,
        )

        self.assertEqual("topology_refused", decision.reason)
        self.assertEqual(0, decision.write_sink_calls)
        self.assertEqual(0, sink.calls)

    def test_symlink_and_hard_link_topology_attacks_are_refused(self) -> None:
        verifier = FixtureTopologyVerifier(self.fixture_root)
        hard_link = self.fixture_root / "lock-alias"
        os.link(self.fixture_root / "audit" / "journal.lock", hard_link)
        with self.assertRaises(FixtureTopologyRefused):
            verifier.verify(self.manifest)

        hard_link.unlink()
        boundary = self.fixture_root / "audit-boundary"
        boundary.unlink()
        os.link(self.fixture_root / "audit" / "journal.lock", boundary)
        with self.assertRaises(FixtureTopologyRefused):
            verifier.verify(self.manifest)

        boundary.unlink()
        boundary.write_bytes(b"fixture boundary\n")
        root = self.fixture_root / "vault"
        root.rmdir()
        os.symlink(self.outside, root)
        with self.assertRaises(FixtureTopologyRefused):
            verifier.verify(self.manifest)

    def test_descriptor_substitution_race_is_refused(self) -> None:
        verifier = FixtureTopologyVerifier(self.fixture_root)
        boundary = self.fixture_root / "audit-boundary"
        replacement = self.fixture_root / "boundary-replacement"
        replacement.write_bytes(b"raced boundary\n")
        raced = False

        def race_opener(name: str, flags: int, parent_fd: int) -> int:
            nonlocal raced
            if name == "audit-boundary" and not raced:
                raced = True
                os.replace(replacement, boundary)
            return os.open(name, flags, dir_fd=parent_fd if parent_fd >= 0 else None)

        with self.assertRaisesRegex(FixtureTopologyRefused, "topology_descriptor_race"):
            verifier.verify(self.manifest, descriptor_opener=race_opener)
        self.assertTrue(raced)

    def test_fake_authority_binds_every_field_and_uses_a_one_time_opaque_handle(self) -> None:
        binding, confirmation = self.issue()

        self.assertTrue(
            self.authority.verify_fixture_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                binding=binding,
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )
        self.assertFalse(
            self.authority.verify_fixture_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                binding=binding,
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )
        self.assertFalse(
            self.authority.verify_fixture_confirmation(
                confirmation=OwnerConfirmation(proposal_id="fixture-proposal-0001", proof=object()),
                proposal_id="fixture-proposal-0001",
                binding=binding,
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )

    def test_fake_authority_rejects_each_tampered_binding_field(self) -> None:
        replacements = {
            "proposal_fingerprint": "sha256:" + ("c" * 64),
            "audience": "other-fixture-audience",
            "operation": "replace_existing",
            "topology_digest": "sha256:" + ("d" * 64),
            "policy_digest": "sha256:" + ("e" * 64),
            "preflight_digest": "sha256:" + ("f" * 64),
            "expires_at": "2026-07-19T12:10:00Z",
            "nonce": "fixture-nonce-tampered",
            "revocation_epoch": 1,
        }
        for index, (field, replacement) in enumerate(replacements.items()):
            with self.subTest(field=field):
                authority = FakeOpaqueHandleTrustedOwnerAuthority(clock=self.clock)
                binding = self.binding(nonce=f"fixture-nonce-{index:04d}")
                binding = FixtureAuthorityBinding(**{**binding.__dict__, "revocation_epoch": authority.revocation_epoch})
                confirmation = authority.issue_confirmation(proposal_id="fixture-proposal-0001", binding=binding)
                tampered = FixtureAuthorityBinding(**{**binding.__dict__, field: replacement})
                self.assertFalse(
                    authority.verify_fixture_confirmation(
                        confirmation=confirmation,
                        proposal_id="fixture-proposal-0001",
                        binding=tampered,
                        owner_session_binding=authority.current_owner_session_binding(),
                    )
                )

    def test_fake_authority_refuses_malformed_bindings_at_issue_time(self) -> None:
        invalid_replacements = {
            "proposal_fingerprint": "not-a-digest",
            "audience": "other-fixture-audience",
            "operation": "replace_existing",
            "topology_digest": "not-a-digest",
            "policy_digest": "sha256:" + ("c" * 64),
            "preflight_digest": "not-a-digest",
            "expires_at": "not-a-timestamp",
            "nonce": "short",
            "revocation_epoch": -1,
        }
        for index, (field, replacement) in enumerate(invalid_replacements.items()):
            with self.subTest(field=field):
                binding = self.binding(nonce=f"fixture-nonce-invalid-{index:04d}")
                invalid = FixtureAuthorityBinding(**{**binding.__dict__, field: replacement})
                with self.assertRaises(FixtureAuthorityRefused):
                    self.authority.issue_confirmation(proposal_id="fixture-proposal-invalid", binding=invalid)

    def test_fake_authority_rejects_expiry_nonce_replay_and_revocation(self) -> None:
        expired = self.binding(nonce="fixture-nonce-expired")
        expired = FixtureAuthorityBinding(**{**expired.__dict__, "expires_at": "2026-07-19T11:59:59Z"})
        with self.assertRaises(FixtureAuthorityRefused):
            self.authority.issue_confirmation(proposal_id="fixture-proposal-expired", binding=expired)

        binding, confirmation = self.issue(self.binding(nonce="fixture-nonce-revoke"))
        self.assertEqual(1, self.authority.revoke_all())
        self.assertFalse(
            self.authority.verify_fixture_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                binding=binding,
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )
        replacement = FixtureAuthorityBinding(**{**binding.__dict__, "revocation_epoch": self.authority.revocation_epoch})
        with self.assertRaises(FixtureAuthorityRefused):
            self.authority.issue_confirmation(proposal_id="fixture-proposal-replay", binding=replacement)

    def test_protocol_adapter_rejects_wrong_audience_and_session(self) -> None:
        binding, confirmation = self.issue()

        self.assertFalse(
            self.authority.verify_owner_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                proposal_fingerprint=binding.proposal_fingerprint,
                server_instance_id="other-fixture-audience",
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )
        self.assertFalse(
            self.authority.verify_owner_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                proposal_fingerprint=binding.proposal_fingerprint,
                server_instance_id=binding.audience,
                owner_session_binding="other-fixture-session",
            )
        )
        self.assertTrue(
            self.authority.verify_owner_confirmation(
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                proposal_fingerprint=binding.proposal_fingerprint,
                server_instance_id=binding.audience,
                owner_session_binding=self.authority.current_owner_session_binding(),
            )
        )

    def test_valid_fixture_confirmation_still_ends_at_deny_with_zero_mutations(self) -> None:
        binding, confirmation = self.issue()
        sink = RecordingWriteSink()
        gate = FixtureOnlyDenyGate(
            topology_verifier=FixtureTopologyVerifier(self.fixture_root),
            authority=self.authority,
            write_sink=sink,
        )
        with mock.patch.object(AtomicSingleFileApplier, "apply", autospec=True) as production_apply:
            decision = gate.evaluate(
                manifest=self.manifest,
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                binding=binding,
            )

        self.assertEqual("fixture_only_denied", decision.reason)
        self.assertEqual(0, decision.write_sink_calls)
        self.assertEqual(0, sink.calls)
        production_apply.assert_not_called()
        self.assertEqual(0, self._out_of_fixture_mutation_count())

    def test_mismatched_topology_digest_is_denied_before_authority_or_sink_use(self) -> None:
        binding, confirmation = self.issue()
        mismatched = FixtureAuthorityBinding(
            **{**binding.__dict__, "topology_digest": "sha256:" + ("c" * 64)}
        )
        sink = RecordingWriteSink()
        gate = FixtureOnlyDenyGate(
            topology_verifier=FixtureTopologyVerifier(self.fixture_root),
            authority=self.authority,
            write_sink=sink,
        )

        with mock.patch.object(
            self.authority,
            "verify_fixture_confirmation",
            wraps=self.authority.verify_fixture_confirmation,
        ) as verify_confirmation:
            decision = gate.evaluate(
                manifest=self.manifest,
                confirmation=confirmation,
                proposal_id="fixture-proposal-0001",
                binding=mismatched,
            )

        self.assertEqual("topology_binding_refused", decision.reason)
        self.assertEqual(0, decision.write_sink_calls)
        self.assertEqual(0, sink.calls)
        verify_confirmation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
