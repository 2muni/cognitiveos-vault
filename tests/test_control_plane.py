"""Focused evidence for the disconnected canonical-root control plane."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import ast
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from cognitiveos import control_plane
from cognitiveos.control_plane import (
    CapabilityDecisionReason,
    CapabilityVerificationStatus,
    ConfiguredVaultRootProvenance,
    LinuxDescriptorEvidence,
    LinuxObjectIdentity,
    RootDecisionReason,
    TrustedOwnerAuthority,
    qualify_root_containment,
)
from control_plane_support import (
    DisposableLinuxReplayLedger,
    FixtureClock,
    FixtureVerifier,
    RecordingReplayLedger,
    fixture_capability,
    fixture_provenance,
    fixture_runtime,
)


def valid_evidence(*, provenance: ConfiguredVaultRootProvenance | None = None, **changes: object) -> LinuxDescriptorEvidence:
    """Return synthetic descriptor evidence for the ``Notes`` allowed root."""

    root = provenance or fixture_provenance()
    notes = root.allowed_roots[0]
    values: dict[str, object] = {
        "schema_version": "linux-descriptor-evidence/v1",
        "platform_supported": True,
        "namespace_id": root.namespace_id,
        "requested_root_path": root.canonical_root_path,
        "canonical_root_path": root.canonical_root_path,
        "root_identity": root.root_identity,
        "descriptor_race_detected": False,
        "allowed_root_id": notes.root_id,
        "allowed_root_identity": notes.identity,
        "target_components": ("Notes", "review.md"),
        "canonical_target_path": root.canonical_root_path + "/Notes/review.md",
    }
    values.update(changes)
    return LinuxDescriptorEvidence(**values)


class CanonicalRootControlPlaneTests(unittest.TestCase):
    def test_exact_configured_root_and_allowed_scope_remain_default_off(self) -> None:
        decision = qualify_root_containment(fixture_provenance(), valid_evidence())

        self.assertEqual(decision.reason, RootDecisionReason.DEFAULT_OFF)
        self.assertTrue(decision.denied)
        self.assertRegex(decision.provenance_digest or "", r"sha256:[0-9a-f]{64}")

    def test_relative_or_overlapping_root_configuration_is_rejected(self) -> None:
        root = fixture_provenance()
        relative = replace(root, canonical_root_path=".")
        self.assertEqual(
            qualify_root_containment(relative, valid_evidence(provenance=root)).reason,
            RootDecisionReason.CONFIGURATION_INVALID,
        )
        overlapping = replace(
            root,
            allowed_roots=(
                root.allowed_roots[0],
                replace(root.allowed_roots[1], components=("Notes", "Nested")),
            ),
        )
        self.assertEqual(
            qualify_root_containment(overlapping, valid_evidence(provenance=root)).reason,
            RootDecisionReason.CONFIGURATION_INVALID,
        )

    def test_alias_and_noncanonical_target_spellings_are_refused(self) -> None:
        root = fixture_provenance()
        alias = valid_evidence(requested_root_path="/synthetic/vault-alias")
        self.assertEqual(qualify_root_containment(root, alias).reason, RootDecisionReason.ROOT_ALIAS_REJECTED)
        lexical_alias = valid_evidence(canonical_target_path="/synthetic/vault/Notes/../Drafts/review.md")
        self.assertEqual(qualify_root_containment(root, lexical_alias).reason, RootDecisionReason.TARGET_ALIAS_REJECTED)

    def test_component_containment_rejects_string_prefix_and_root_escape(self) -> None:
        root = fixture_provenance()
        prefix_confusion = valid_evidence(
            target_components=("Notes-private", "review.md"),
            canonical_target_path="/synthetic/vault/Notes-private/review.md",
        )
        self.assertEqual(
            qualify_root_containment(root, prefix_confusion).reason,
            RootDecisionReason.TARGET_OUTSIDE_ALLOWED_ROOT,
        )
        escape = valid_evidence(
            target_components=("Drafts", "review.md"),
            canonical_target_path="/synthetic/vault/Drafts/review.md",
        )
        self.assertEqual(qualify_root_containment(root, escape).reason, RootDecisionReason.TARGET_OUTSIDE_ALLOWED_ROOT)

    def test_descriptor_race_namespace_platform_and_identity_fail_closed(self) -> None:
        root = fixture_provenance()
        cases = (
            (valid_evidence(descriptor_race_detected=True), RootDecisionReason.DESCRIPTOR_RACE),
            (valid_evidence(namespace_id="fixture-namespace-other"), RootDecisionReason.NAMESPACE_MISMATCH),
            (valid_evidence(platform_supported=False), RootDecisionReason.PLATFORM_UNSUPPORTED),
            (valid_evidence(root_identity=LinuxObjectIdentity(device=101, inode=999)), RootDecisionReason.ROOT_IDENTITY_MISMATCH),
            (valid_evidence(allowed_root_identity=LinuxObjectIdentity(device=101, inode=999)), RootDecisionReason.ALLOWED_ROOT_MISMATCH),
        )
        for evidence, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(qualify_root_containment(root, evidence).reason, expected)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only disposable alias fixture")
    def test_disposable_linux_alias_is_represented_as_noncanonical_evidence(self) -> None:
        """Create an alias only in a disposable fixture; the module never opens it."""

        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary) / "vault"
            fixture_root.mkdir()
            alias = Path(temporary) / "vault-alias"
            alias.symlink_to(fixture_root, target_is_directory=True)
            self.assertTrue(alias.is_symlink())

            root = replace(fixture_provenance(), canonical_root_path=str(fixture_root))
            evidence = valid_evidence(
                provenance=root,
                requested_root_path=str(alias),
                canonical_root_path=str(fixture_root),
            )
            self.assertEqual(qualify_root_containment(root, evidence).reason, RootDecisionReason.ROOT_ALIAS_REJECTED)


class TrustedOwnerAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = fixture_runtime()
        self.clock = FixtureClock()
        self.ledger = RecordingReplayLedger()
        self.verifier = FixtureVerifier()
        self.authority = TrustedOwnerAuthority(
            runtime=self.runtime,
            verifier=self.verifier,
            replay_ledger=self.ledger,
            clock=self.clock,
        )

    def test_consumption_is_one_time_and_success_still_default_off(self) -> None:
        capability = fixture_capability(runtime=self.runtime)

        first = self.authority.consume(capability)
        second = self.authority.consume(capability)

        self.assertEqual(first.reason, CapabilityDecisionReason.CONSUMED_DEFAULT_OFF)
        self.assertTrue(first.denied)
        self.assertEqual(second.reason, CapabilityDecisionReason.REPLAYED)
        self.assertEqual(len(self.ledger.claims), 1)
        claim = self.ledger.claims[0]
        self.assertEqual(claim.capability_id, capability.capability_id)
        self.assertFalse(hasattr(claim, "proof"))
        self.assertNotIn("proof", claim.__dict__)

    def test_concurrent_consumption_allows_only_one_durable_claim(self) -> None:
        capability = fixture_capability(runtime=self.runtime)
        start = threading.Barrier(3)
        decisions: list[CapabilityDecisionReason] = []
        decisions_lock = threading.Lock()

        def consume() -> None:
            start.wait()
            decision = self.authority.consume(capability)
            with decisions_lock:
                decisions.append(decision.reason)

        workers = [threading.Thread(target=consume) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join()

        self.assertCountEqual(
            decisions,
            [CapabilityDecisionReason.CONSUMED_DEFAULT_OFF, CapabilityDecisionReason.REPLAYED],
        )
        self.assertEqual(len(self.ledger.claims), 1)

    def test_session_server_root_rotation_and_revocation_mismatches_do_not_claim(self) -> None:
        cases = (
            (fixture_capability(runtime=self.runtime, owner_session_id="fixture-session-other"), CapabilityDecisionReason.OWNER_SESSION_MISMATCH),
            (fixture_capability(runtime=self.runtime, server_instance_id="fixture-server-other"), CapabilityDecisionReason.SERVER_INSTANCE_MISMATCH),
            (fixture_capability(runtime=self.runtime, root_provenance_digest="sha256:" + "2" * 64), CapabilityDecisionReason.ROOT_PROVENANCE_MISMATCH),
            (fixture_capability(runtime=self.runtime, key_epoch=5), CapabilityDecisionReason.ROTATED),
            (fixture_capability(runtime=self.runtime, revocation_epoch=7), CapabilityDecisionReason.REVOKED),
            (fixture_capability(runtime=self.runtime, revocation_epoch=9), CapabilityDecisionReason.REVOKED),
        )
        for capability, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.authority.consume(capability).reason, expected)
        self.assertEqual(self.ledger.claims, [])
        self.assertEqual(self.verifier.calls, 0)

    def test_monotonic_expiry_cannot_be_extended_by_wall_clock_rollback(self) -> None:
        capability = fixture_capability(runtime=self.runtime, monotonic_deadline_ns=1_001)
        self.clock.wall_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.clock.monotonic_value = 1_001

        decision = self.authority.consume(capability)

        self.assertEqual(decision.reason, CapabilityDecisionReason.EXPIRED)
        self.assertEqual(self.ledger.claims, [])

    def test_capability_cannot_be_consumed_before_either_server_clock_issuance_point(self) -> None:
        capability = fixture_capability(runtime=self.runtime)
        self.clock.wall_value = datetime(2026, 7, 20, 11, 59, tzinfo=timezone.utc)
        self.clock.monotonic_value = 999

        decision = self.authority.consume(capability)

        self.assertEqual(decision.reason, CapabilityDecisionReason.NOT_YET_VALID)
        self.assertEqual(self.ledger.claims, [])

    def test_reused_capability_id_with_a_different_bound_record_is_a_collision(self) -> None:
        original = fixture_capability(runtime=self.runtime)
        altered = fixture_capability(runtime=self.runtime, proof_digest="sha256:" + "3" * 64)

        self.assertEqual(self.authority.consume(original).reason, CapabilityDecisionReason.CONSUMED_DEFAULT_OFF)
        self.assertEqual(self.authority.consume(altered).reason, CapabilityDecisionReason.REPLAY_COLLISION)
        self.assertEqual(len(self.ledger.claims), 1)

    def test_proof_failure_is_refused_before_replay_state(self) -> None:
        unavailable = TrustedOwnerAuthority(
            runtime=self.runtime,
            verifier=FixtureVerifier(CapabilityVerificationStatus.UNAVAILABLE),
            replay_ledger=self.ledger,
            clock=self.clock,
        )
        invalid = TrustedOwnerAuthority(
            runtime=self.runtime,
            verifier=FixtureVerifier(CapabilityVerificationStatus.INVALID),
            replay_ledger=self.ledger,
            clock=self.clock,
        )
        capability = fixture_capability(runtime=self.runtime)

        self.assertEqual(unavailable.consume(capability).reason, CapabilityDecisionReason.PROOF_UNAVAILABLE)
        self.assertEqual(invalid.consume(capability).reason, CapabilityDecisionReason.PROOF_INVALID)
        self.assertEqual(self.ledger.claims, [])

    def test_restart_rejects_old_server_boot_before_consumption(self) -> None:
        restarted_runtime = fixture_runtime(server_boot_id="fixture-boot-0002")
        restarted = TrustedOwnerAuthority(
            runtime=restarted_runtime,
            verifier=self.verifier,
            replay_ledger=self.ledger,
            clock=self.clock,
        )

        decision = restarted.consume(fixture_capability(runtime=self.runtime))

        self.assertEqual(decision.reason, CapabilityDecisionReason.SERVER_RESTARTED)
        self.assertEqual(self.ledger.claims, [])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only durable replay fixture")
    def test_disposable_linux_ledger_refuses_concurrent_and_restarted_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "synthetic-replay-state.json"
            capability = fixture_capability(runtime=self.runtime)
            barrier = threading.Barrier(3)
            decisions: list[CapabilityDecisionReason] = []
            decisions_lock = threading.Lock()

            def consume_once() -> None:
                consumer = TrustedOwnerAuthority(
                    runtime=self.runtime,
                    verifier=self.verifier,
                    replay_ledger=DisposableLinuxReplayLedger(state_path),
                    clock=self.clock,
                )
                barrier.wait()
                decision = consumer.consume(capability)
                with decisions_lock:
                    decisions.append(decision.reason)

            workers = [threading.Thread(target=consume_once) for _ in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait()
            for worker in workers:
                worker.join()
            self.assertCountEqual(
                decisions,
                [CapabilityDecisionReason.CONSUMED_DEFAULT_OFF, CapabilityDecisionReason.REPLAYED],
            )

            restarted_reader = TrustedOwnerAuthority(
                runtime=self.runtime,
                verifier=self.verifier,
                replay_ledger=DisposableLinuxReplayLedger(state_path),
                clock=self.clock,
            )

            self.assertEqual(restarted_reader.consume(capability).reason, CapabilityDecisionReason.REPLAYED)
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(set(stored), {capability.capability_id})
            self.assertNotIn("proof", state_path.read_text(encoding="utf-8"))

            restarted_runtime = fixture_runtime(server_boot_id="fixture-boot-0002")
            restarted = TrustedOwnerAuthority(
                runtime=restarted_runtime,
                verifier=self.verifier,
                replay_ledger=DisposableLinuxReplayLedger(state_path),
                clock=self.clock,
            )
            self.assertEqual(restarted.consume(capability).reason, CapabilityDecisionReason.SERVER_RESTARTED)


class DisconnectedSurfaceTests(unittest.TestCase):
    def test_control_plane_has_no_integration_imports_or_apply_outcome_reference(self) -> None:
        source = inspect.getsource(control_plane)
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )

        self.assertFalse(any("mcp" in name or "atomic_apply" in name or "writer" in name for name in imported))
        self.assertNotIn("ApplyOutcome", source)
        self.assertNotIn("os.", source)
        self.assertNotIn("pathlib", source)


if __name__ == "__main__":
    unittest.main()
