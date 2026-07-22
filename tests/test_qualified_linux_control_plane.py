"""Qualified-Linux-only evidence tests for the disconnected control plane.

Every filesystem location here is created below ``TemporaryDirectory``. The
tests skip unless the declared Linux tuple is present; a skipped macOS result
is a blocked qualification gate, never a Linux pass.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import multiprocessing
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cognitiveos.control_plane import (
    CapabilityDecisionReason,
    LinuxObjectIdentity,
    RootDecisionReason,
    qualify_root_containment,
    provenance_digest,
)
from qualified_linux_control_plane_support import (
    DisposableLinuxDescriptorProbe,
    QualifiedLinuxFixtureRefusal,
    authority_for_fixture,
    consume_in_separate_process,
    fixture_capability,
    fixture_runtime,
    require_declared_linux_tuple,
)


@unittest.skipUnless(sys.platform == "linux", "requires the declared Linux control-plane tuple")
class QualifiedLinuxControlPlaneEvidenceTests(unittest.TestCase):
    """Tests that may provide evidence only on the documented Linux tuple."""

    def _temporary_root(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="cognitiveos-qualified-linux-")

    def _prepare_descriptor_fixture(self, temporary: str) -> tuple[Path, str]:
        root = Path(temporary) / "vault"
        root.mkdir(mode=0o700)
        (root / "Notes").mkdir(mode=0o700)
        (root / "Notes" / "review.md").write_bytes(b"synthetic Linux descriptor fixture\n")
        os.chmod(root / "Notes" / "review.md", 0o600)
        return root, require_declared_linux_tuple(self, Path(temporary))

    def test_immutable_bootstrap_provenance_and_real_nofollow_containment_remain_default_off(self) -> None:
        with self._temporary_root() as temporary:
            root, namespace_id = self._prepare_descriptor_fixture(temporary)
            probe = DisposableLinuxDescriptorProbe(root, namespace_id=namespace_id)

            provenance = probe.bootstrap_provenance()
            evidence = probe.build_target_evidence(provenance, ("Notes", "review.md"))
            decision = qualify_root_containment(provenance, evidence)

            self.assertEqual(decision.reason, RootDecisionReason.DEFAULT_OFF)
            self.assertTrue(decision.denied)
            self.assertEqual(evidence.root_identity, provenance.root_identity)
            self.assertEqual(evidence.allowed_root_identity, provenance.allowed_roots[0].identity)
            with self.assertRaises(FrozenInstanceError):
                provenance.configuration_generation = 2  # type: ignore[misc]
            self.assertNotEqual(
                provenance_digest(provenance),
                provenance_digest(replace(provenance, configuration_generation=2)),
            )

    def test_namespace_and_device_inode_bindings_refuse_substitution(self) -> None:
        with self._temporary_root() as temporary:
            root, namespace_id = self._prepare_descriptor_fixture(temporary)
            probe = DisposableLinuxDescriptorProbe(root, namespace_id=namespace_id)
            provenance = probe.bootstrap_provenance()
            evidence = probe.build_target_evidence(provenance, ("Notes", "review.md"))

            namespace_substitution = replace(evidence, namespace_id="linux-mnt-substituted-0001")
            inode_substitution = replace(
                evidence,
                root_identity=LinuxObjectIdentity(
                    device=evidence.root_identity.device,
                    inode=evidence.root_identity.inode + 1,
                ),
            )

            self.assertEqual(
                qualify_root_containment(provenance, namespace_substitution).reason,
                RootDecisionReason.NAMESPACE_MISMATCH,
            )
            self.assertEqual(
                qualify_root_containment(provenance, inode_substitution).reason,
                RootDecisionReason.ROOT_IDENTITY_MISMATCH,
            )

    def test_path_aliases_and_descriptor_replacement_fail_closed(self) -> None:
        with self._temporary_root() as temporary:
            root, namespace_id = self._prepare_descriptor_fixture(temporary)
            alias = Path(temporary) / "vault-alias"
            alias.symlink_to(root, target_is_directory=True)
            alias_probe = DisposableLinuxDescriptorProbe(alias, namespace_id=namespace_id)
            with self.assertRaises(QualifiedLinuxFixtureRefusal):
                alias_probe.bootstrap_provenance()

            probe = DisposableLinuxDescriptorProbe(root, namespace_id=namespace_id)
            provenance = probe.bootstrap_provenance()
            leaf_alias = root / "Notes" / "alias.md"
            leaf_alias.symlink_to(root / "Notes" / "review.md")
            with self.assertRaises(QualifiedLinuxFixtureRefusal):
                probe.build_target_evidence(provenance, ("Notes", "alias.md"))
            hard_alias = root / "Notes" / "hard-alias.md"
            os.link(root / "Notes" / "review.md", hard_alias)
            with self.assertRaises(QualifiedLinuxFixtureRefusal):
                probe.build_target_evidence(provenance, ("Notes", "hard-alias.md"))
            with self.assertRaises(QualifiedLinuxFixtureRefusal):
                probe.build_target_evidence(provenance, ("Notes", "..", "review.md"))

            def replace_notes_after_open() -> None:
                original = root / "Notes-before-replacement"
                (root / "Notes").rename(original)
                (root / "Notes").mkdir(mode=0o700)
                (root / "Notes" / "review.md").write_bytes(b"substituted fixture\n")
                os.chmod(root / "Notes" / "review.md", 0o600)

            with self.assertRaisesRegex(QualifiedLinuxFixtureRefusal, "identity changed"):
                probe.build_target_evidence(
                    provenance,
                    ("Notes", "review.md"),
                    after_open_component=replace_notes_after_open,
                )

    def test_owner_only_cross_process_replay_and_restart_refusal(self) -> None:
        with self._temporary_root() as temporary:
            temporary_root = Path(temporary)
            require_declared_linux_tuple(self, temporary_root)
            state_path = temporary_root / "replay-state.json"
            context = multiprocessing.get_context("spawn")
            start_event = context.Event()
            result_queue = context.Queue()
            workers = [
                context.Process(
                    target=consume_in_separate_process,
                    args=(os.fspath(state_path), start_event, result_queue),
                )
                for _ in range(2)
            ]
            for worker in workers:
                worker.start()
            start_event.set()
            for worker in workers:
                worker.join(timeout=15)
                self.assertFalse(worker.is_alive(), "cross-process replay worker did not finish")
                self.assertEqual(worker.exitcode, 0)
            results = [result_queue.get(timeout=5) for _ in workers]
            result_queue.close()
            result_queue.join_thread()

            self.assertCountEqual(
                results,
                [
                    CapabilityDecisionReason.CONSUMED_DEFAULT_OFF.value,
                    CapabilityDecisionReason.REPLAYED.value,
                ],
            )
            runtime = fixture_runtime()
            restarted_reader, _ = authority_for_fixture(state_path, runtime=runtime)
            self.assertEqual(
                restarted_reader.consume(fixture_capability(runtime)).reason,
                CapabilityDecisionReason.REPLAYED,
            )
            restarted_runtime = fixture_runtime(server_boot_id="linux-fixture-boot-0002")
            restarted_authority, _ = authority_for_fixture(state_path, runtime=restarted_runtime)
            self.assertEqual(
                restarted_authority.consume(fixture_capability(runtime)).reason,
                CapabilityDecisionReason.SERVER_RESTARTED,
            )
            self.assertEqual(stat.S_IMODE(os.stat(temporary_root).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(state_path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(state_path.with_name(state_path.name + ".lock")).st_mode), 0o600)
            self.assertEqual(os.stat(state_path).st_uid, os.geteuid())
            self.assertNotIn("proof", state_path.read_text(encoding="utf-8"))

    def test_torn_state_and_lock_replacement_refuse_without_repair(self) -> None:
        with self._temporary_root() as temporary:
            temporary_root = Path(temporary)
            require_declared_linux_tuple(self, temporary_root)
            state_path = temporary_root / "replay-state.json"
            state_path.write_bytes(b'{"schema_version":"qualified-linux-replay-fixture/v1"')
            os.chmod(state_path, 0o600)
            runtime = fixture_runtime()
            authority, _ = authority_for_fixture(state_path, runtime=runtime)
            self.assertEqual(
                authority.consume(fixture_capability(runtime)).reason,
                CapabilityDecisionReason.REPLAY_STATE_UNAVAILABLE,
            )
            self.assertEqual(
                state_path.read_bytes(),
                b'{"schema_version":"qualified-linux-replay-fixture/v1"',
            )

        with self._temporary_root() as temporary:
            temporary_root = Path(temporary)
            require_declared_linux_tuple(self, temporary_root)
            state_path = temporary_root / "replay-state.json"
            abandoned = state_path.with_name(state_path.name + ".tmp.crash")
            abandoned.write_bytes(b"interrupted temporary replay record")
            os.chmod(abandoned, 0o600)
            runtime = fixture_runtime()
            authority, _ = authority_for_fixture(state_path, runtime=runtime)
            self.assertEqual(
                authority.consume(fixture_capability(runtime)).reason,
                CapabilityDecisionReason.REPLAY_STATE_UNAVAILABLE,
            )
            self.assertTrue(abandoned.exists(), "fixture must not repair a crash artifact")

        with self._temporary_root() as temporary:
            temporary_root = Path(temporary)
            require_declared_linux_tuple(self, temporary_root)
            state_path = temporary_root / "replay-state.json"
            lock_path = state_path.with_name(state_path.name + ".lock")
            replacement = temporary_root / "replacement.lock"
            replacement.write_bytes(b"replacement")
            os.chmod(replacement, 0o600)

            def replace_lock_after_acquire() -> None:
                os.replace(replacement, lock_path)

            runtime = fixture_runtime()
            authority, _ = authority_for_fixture(
                state_path,
                runtime=runtime,
                after_lock_acquired=replace_lock_after_acquire,
            )
            self.assertEqual(
                authority.consume(fixture_capability(runtime)).reason,
                CapabilityDecisionReason.REPLAY_STATE_UNAVAILABLE,
            )
            self.assertFalse(state_path.exists(), "lock replacement must not create replay state")

    def test_monotonic_expiry_rotation_revocation_and_session_lifecycle_refuse_before_replay(self) -> None:
        with self._temporary_root() as temporary:
            temporary_root = Path(temporary)
            require_declared_linux_tuple(self, temporary_root)
            state_path = temporary_root / "replay-state.json"
            runtime = fixture_runtime()
            authority, _ = authority_for_fixture(state_path, runtime=runtime)
            stale_session = fixture_capability(
                fixture_runtime(owner_session_id="linux-fixture-session-closed")
            )
            rotated = replace(fixture_capability(runtime), key_epoch=2)
            revoked = replace(fixture_capability(runtime), revocation_epoch=2)
            expired = replace(fixture_capability(runtime), monotonic_deadline_ns=1_000)

            cases = (
                (stale_session, CapabilityDecisionReason.OWNER_SESSION_MISMATCH),
                (rotated, CapabilityDecisionReason.ROTATED),
                (revoked, CapabilityDecisionReason.REVOKED),
                (expired, CapabilityDecisionReason.EXPIRED),
            )
            for capability, expected in cases:
                with self.subTest(expected=expected):
                    self.assertEqual(authority.consume(capability).reason, expected)
            self.assertFalse(state_path.exists(), "refused lifecycle events must not claim replay state")


if __name__ == "__main__":
    unittest.main()
