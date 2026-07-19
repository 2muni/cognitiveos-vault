from __future__ import annotations

import functools
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest import mock

from cognitiveos.approval import OwnerConfirmation
from cognitiveos.atomic_apply import (
    ApplyOutcome,
    ApplyRefused,
    AtomicSingleFileApplier,
    provision_audit_boundary,
)
from cognitiveos.safety import SKIPPED_DIRS, WRITEBACK_DENIED_DIRS, WRITEBACK_DENIED_DIR_PREFIXES

from writeback_support import TestOwnerAuthority


AUDIT_KEY = b"a" * 32


def _requires_descriptor_bound_publication(test: object) -> object:
    """Run publication assertions only on a filesystem with the safe primitive."""

    @functools.wraps(test)
    def wrapped(self: "AtomicSingleFileApplyTests", *args: object, **kwargs: object) -> object:
        self.require_descriptor_bound_publication()
        return test(self, *args, **kwargs)  # type: ignore[operator]

    return wrapped


def _atomic_test_temporary_directory() -> tempfile.TemporaryDirectory[str]:
    """Prefer a Linux tmpfs when its anonymous-file primitive is available.

    Hosted Linux workspaces can be overlay filesystems that correctly reject
    ``O_TMPFILE``.  ``/dev/shm`` is a disposable tmpfs on the CI images, so it
    lets the descriptor-bound regression execute where the kernel/filesystem
    pair supports the required primitive.  Other hosts retain the ordinary
    ``TemporaryDirectory`` path and exercise the fail-closed behavior.
    """

    shared_memory = Path("/dev/shm")
    if AtomicSingleFileApplier._descriptor_bound_atomic_create_supported() and shared_memory.is_dir():
        temporary = tempfile.TemporaryDirectory(dir=shared_memory)
        descriptor = -1
        try:
            descriptor = os.open(temporary.name, os.O_WRONLY | os.O_TMPFILE, 0o600)
            AtomicSingleFileApplier._verify_unlinked_temporary_fd(descriptor)
            os.write(descriptor, b"probe")
            os.fsync(descriptor)
            AtomicSingleFileApplier._verify_unlinked_temporary_fd(descriptor)
            return temporary
        except (ApplyRefused, OSError):
            temporary.cleanup()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return tempfile.TemporaryDirectory()


def _concurrent_create_worker(
    root: str,
    audit: str,
    boundary: str,
    path: str,
    barrier: object,
    queue: object,
) -> None:
    """Child server process used only to prove the audit transaction lock."""

    authority = TestOwnerAuthority()
    applier = AtomicSingleFileApplier(
        root,
        allowed_roots=("Notes",),
        audit_directory=audit,
        audit_boundary_path=boundary,
        owner_authority=authority,
        audit_key=AUDIT_KEY,
    )
    proposal = applier.propose(operation="create_absent", path=path, proposed_bytes=path.encode("utf-8"))
    token = applier.approve_from_trusted_owner(authority.confirm(proposal))
    barrier.wait(timeout=10)  # type: ignore[union-attr]
    queue.put(applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome.value)  # type: ignore[union-attr]
    applier.close()


def _concurrent_recovery_worker(
    root: str,
    audit: str,
    boundary: str,
    barrier: object,
    queue: object,
) -> None:
    """Independent server processes race only on read-only audit recovery."""

    applier = AtomicSingleFileApplier(
        root,
        allowed_roots=("Notes",),
        audit_directory=audit,
        audit_boundary_path=boundary,
        owner_authority=TestOwnerAuthority(),
        audit_key=AUDIT_KEY,
    )
    barrier.wait(timeout=10)  # type: ignore[union-attr]
    queue.put(len(applier.recover_incomplete_audit()))  # type: ignore[union-attr]
    applier.close()


class AtomicSingleFileApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = _atomic_test_temporary_directory()
        self.temporary_root = Path(self.temporary.name)
        self.root = Path(self.temporary.name) / "vault"
        self.notes = self.root / "Notes"
        self.notes.mkdir(parents=True)
        self.audit_directory = Path(self.temporary.name) / "audit"
        self.audit_directory.mkdir(mode=0o700)
        self.audit_boundary = Path(self.temporary.name) / "audit-boundary"
        self.outside_notes = Path(self.temporary.name) / "outside" / "Notes"
        self.outside_notes.mkdir(parents=True)
        provision_audit_boundary(
            self.audit_directory,
            audit_key=AUDIT_KEY,
            boundary_path=self.audit_boundary,
        )
        # The v0.8 boundary is intentionally unsupported when a namespace
        # parent can rename an allowed directory.  Notes itself is writable;
        # its vault parent is not, so a final create can proceed but Notes
        # cannot move outside the verified vault after its descriptor opens.
        self.root.chmod(0o555)
        self.temporary_root.chmod(0o500)
        self.owner = TestOwnerAuthority()
        self.applier = AtomicSingleFileApplier(
            self.root,
            allowed_roots=("Notes",),
            audit_directory=self.audit_directory,
            audit_boundary_path=self.audit_boundary,
            owner_authority=self.owner,
            audit_key=AUDIT_KEY,
        )

    def tearDown(self) -> None:
        self.applier.close()
        self.root.chmod(0o700)
        self.temporary_root.chmod(0o700)
        self.temporary.cleanup()

    def propose(self, *, path: str = "Notes/note.md", data: bytes = b"new note\n") -> dict[str, object]:
        return self.applier.propose(operation="create_absent", path=path, proposed_bytes=data)

    def approve(self, proposal: dict[str, object]) -> str:
        return self.applier.approve_from_trusted_owner(self.owner.confirm(proposal))

    def descriptor_bound_publication_available(self) -> bool:
        """Probe the entire safe publication sequence without exposing target bytes."""

        if not AtomicSingleFileApplier._descriptor_bound_atomic_create_supported():
            return False
        parent_fd = os.open(self.notes, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = -1
        probe_name = ".cognitiveos-descriptor-probe"
        linked = False
        try:
            descriptor = os.open(".", os.O_WRONLY | os.O_TMPFILE, 0o600, dir_fd=parent_fd)
            AtomicSingleFileApplier._verify_unlinked_temporary_fd(descriptor)
            os.write(descriptor, b"probe")
            os.fsync(descriptor)
            AtomicSingleFileApplier._verify_unlinked_temporary_fd(descriptor)
            os.link(
                f"/proc/self/fd/{descriptor}",
                probe_name,
                dst_dir_fd=parent_fd,
                follow_symlinks=True,
            )
            linked = True
            os.fsync(parent_fd)
            os.unlink(probe_name, dir_fd=parent_fd)
            linked = False
            return True
        except (ApplyRefused, OSError):
            return False
        finally:
            if linked:
                try:
                    os.unlink(probe_name, dir_fd=parent_fd)
                except OSError:
                    pass
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent_fd)

    def require_descriptor_bound_publication(self) -> None:
        """Run APPLIED assertions only after the whole safe primitive succeeds."""

        if not self.descriptor_bound_publication_available():
            self.skipTest("descriptor-bound atomic publication is unavailable on this filesystem")

    @_requires_descriptor_bound_publication
    def test_only_trusted_owner_can_issue_the_one_time_apply_token(self) -> None:
        proposal = self.propose()

        with self.assertRaises(ApplyRefused):
            self.applier.approve_from_trusted_owner(OwnerConfirmation(proposal["proposal_id"], b"forged"))
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=proposal["proposal_id"], token="client-invented").outcome,
        )
        self.assertFalse((self.notes / "note.md").exists())

        token = self.approve(proposal)
        self.assertEqual(ApplyOutcome.APPLIED, self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)
        self.assertEqual(b"new note\n", (self.notes / "note.md").read_bytes())

    @_requires_descriptor_bound_publication
    def test_proposal_caller_cannot_choose_identity_fingerprint_or_owner_session(self) -> None:
        with self.assertRaises(TypeError):
            self.applier.propose(  # type: ignore[call-arg]
                operation="create_absent",
                path="Notes/note.md",
                proposed_bytes=b"safe\n",
                proposal_id="caller-id",
            )

        proposal = self.propose(data=b"server-owned\n")
        altered_view = json.loads(json.dumps(proposal))
        altered_view["change"]["proposed_bytes_base64"] = "Y2xpZW50LXN1YnN0aXR1dGVkCg=="
        token = self.approve(proposal)
        self.assertEqual(ApplyOutcome.APPLIED, self.applier.apply(proposal_id=altered_view["proposal_id"], token=token).outcome)
        self.assertEqual(b"server-owned\n", (self.notes / "note.md").read_bytes())

    @_requires_descriptor_bound_publication
    def test_token_and_owner_session_substitution_are_refused(self) -> None:
        first = self.propose(path="Notes/first.md", data=b"first\n")
        second = self.propose(path="Notes/second.md", data=b"second\n")
        first_token = self.approve(first)
        second_token = self.approve(second)

        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=second["proposal_id"], token=first_token).outcome,
        )
        self.assertFalse((self.notes / "second.md").exists())
        self.assertEqual(
            ApplyOutcome.APPLIED,
            self.applier.apply(proposal_id=second["proposal_id"], token=second_token).outcome,
        )

        third = self.propose(path="Notes/third.md", data=b"third\n")
        self.owner.session_binding = "different-owner-session"
        with self.assertRaises(ApplyRefused):
            self.applier.approve_from_trusted_owner(self.owner.confirm(third))
        self.assertFalse((self.notes / "third.md").exists())

    def test_replace_existing_is_refused_without_a_check_then_replace_claim(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"reviewed bytes\n")

        with self.assertRaisesRegex(ApplyRefused, "replace_existing_unsupported"):
            self.applier.propose(operation="replace_existing", path="Notes/note.md", proposed_bytes=b"replacement\n")

        self.assertEqual(b"reviewed bytes\n", target.read_bytes())
        self.assertEqual([], self.applier.audit.records())

    @_requires_descriptor_bound_publication
    def test_create_absent_publishes_only_after_the_temporary_file_is_complete(self) -> None:
        target = self.notes / "note.md"
        data = b"complete\x00\r\nbytes"
        proposal = self.propose(data=data)
        token = self.approve(proposal)
        original_link = os.link

        def checked_link(source: str, destination: str, **kwargs: object) -> None:
            self.assertFalse(target.exists(), "the final name must not expose partial bytes")
            self.assertTrue(source.startswith("/proc/self/fd/"))
            self.assertEqual(data, Path(source).read_bytes())
            original_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=checked_link):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(data, target.read_bytes())
        self.assertEqual(["pending", "applied"], [record["outcome"] for record in self.applier.audit.records()])

    @_requires_descriptor_bound_publication
    def test_temporary_name_hard_link_substitution_cannot_publish_unapproved_bytes(self) -> None:
        """A substituted legacy-style temporary name cannot affect the fd source."""

        target = self.notes / "note.md"
        approved = b"approved bytes\n"
        reviewed_temporary = self.notes / ".cognitiveos-reviewed-temporary"
        reviewed_temporary.write_bytes(approved)
        unapproved = self.notes / "unapproved.md"
        unapproved.write_bytes(b"unapproved bytes\n")
        proposal = self.propose(data=approved)
        token = self.approve(proposal)
        original_link = os.link

        def substitute_temporary_name(source: str, destination: str, **kwargs: object) -> None:
            self.assertTrue(source.startswith("/proc/self/fd/"))
            parent_fd = kwargs["dst_dir_fd"]
            self.assertIsInstance(parent_fd, int)
            temporary = ".cognitiveos-create-substitution"

            # Reproduce the Issue #48 attack: a legacy temporary name first
            # references reviewed bytes, then an attacker replaces it with a
            # hard link to unreviewed bytes before final publication.  Keep
            # this legacy inode separate from the active O_TMPFILE descriptor:
            # linking and unlinking that descriptor would change the kernel
            # object whose one publication call the test needs to verify.
            original_link(str(reviewed_temporary), temporary, dst_dir_fd=parent_fd, follow_symlinks=True)
            os.unlink(temporary, dir_fd=parent_fd)
            original_link(str(unapproved), temporary, dst_dir_fd=parent_fd, follow_symlinks=True)
            self.assertEqual(approved, reviewed_temporary.read_bytes())
            self.assertEqual(b"unapproved bytes\n", (self.notes / temporary).read_bytes())
            self.assertEqual(os.stat(unapproved).st_ino, os.stat(self.notes / temporary).st_ino)

            # Publication still uses the verified descriptor.  The replaced
            # temporary name is deliberately not an input to this call.
            original_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=substitute_temporary_name):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(approved, target.read_bytes())
        self.assertEqual(b"unapproved bytes\n", (self.notes / ".cognitiveos-create-substitution").read_bytes())

    @_requires_descriptor_bound_publication
    def test_create_race_is_a_conflict_never_an_overwrite(self) -> None:
        target = self.notes / "note.md"
        proposal = self.propose(data=b"approved\n")
        token = self.approve(proposal)
        original_link = os.link

        def racing_link(source: str, destination: str, **kwargs: object) -> None:
            target.write_bytes(b"concurrent creator\n")
            original_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=racing_link):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.CONFLICT, result.outcome)
        self.assertEqual(b"concurrent creator\n", target.read_bytes())
        self.assertEqual(["pending", "conflict"], [record["outcome"] for record in self.applier.audit.records()])

    @_requires_descriptor_bound_publication
    def test_after_open_parent_rename_cannot_publish_outside_the_vault(self) -> None:
        proposal = self.propose(path="Notes/renamed-parent.md", data=b"approved\n")
        token = self.approve(proposal)
        target = self.notes / "renamed-parent.md"
        outside_target = self.outside_notes / "renamed-parent.md"
        original_link = os.link
        rename_attempted = False

        def rename_parent_after_open(source: str, destination: str, **kwargs: object) -> None:
            nonlocal rename_attempted
            rename_attempted = True
            # _publish_absent has already opened Notes when it reaches link.
            # The protected vault parent is the namespace/permission primitive
            # that makes this adversarial rename fail rather than redirect the
            # retained directory descriptor outside the vault.
            with self.assertRaises(PermissionError):
                os.rename(self.notes, self.outside_notes)
            original_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=rename_parent_after_open):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertTrue(rename_attempted)
        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(b"approved\n", target.read_bytes())
        self.assertFalse(outside_target.exists())

    def test_writable_allowed_parent_namespace_is_refused_before_a_proposal(self) -> None:
        self.root.chmod(0o755)
        try:
            with self.assertRaisesRegex(ApplyRefused, "invalid_allowed_root"):
                AtomicSingleFileApplier(
                    self.root,
                    allowed_roots=("Notes",),
                    audit_directory=self.audit_directory,
                    audit_boundary_path=self.audit_boundary,
                    owner_authority=TestOwnerAuthority(),
                    audit_key=AUDIT_KEY,
                )
        finally:
            self.root.chmod(0o555)

    def test_writable_vault_parent_namespace_is_refused_before_a_proposal(self) -> None:
        self.temporary_root.chmod(0o700)
        try:
            with self.assertRaisesRegex(ApplyRefused, "unsafe_namespace"):
                AtomicSingleFileApplier(
                    self.root,
                    allowed_roots=("Notes",),
                    audit_directory=self.audit_directory,
                    audit_boundary_path=self.audit_boundary,
                    owner_authority=TestOwnerAuthority(),
                    audit_key=AUDIT_KEY,
                )
        finally:
            self.temporary_root.chmod(0o500)

    def test_unsupported_atomic_create_refuses_without_creating_a_target(self) -> None:
        proposal = self.propose()
        token = self.approve(proposal)

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=NotImplementedError):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.REFUSED, result.outcome)
        self.assertFalse((self.notes / "note.md").exists())

    def test_unavailable_descriptor_primitive_refuses_without_creating_a_target(self) -> None:
        if self.descriptor_bound_publication_available():
            self.skipTest("requires an unavailable descriptor-bound publication primitive")

        proposal = self.propose()
        token = self.approve(proposal)
        result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.REFUSED, result.outcome)
        self.assertFalse((self.notes / "note.md").exists())

    @_requires_descriptor_bound_publication
    def test_pending_audit_is_durable_before_atomic_publication(self) -> None:
        proposal = self.propose()
        token = self.approve(proposal)
        original_publish = self.applier._publish_absent

        def checked_publish(path: str, data: bytes) -> None:
            self.assertFalse((self.notes / "note.md").exists())
            self.assertEqual(["pending"], [item["outcome"] for item in self.applier.audit.records()])
            original_publish(path, data)

        with mock.patch.object(self.applier, "_publish_absent", side_effect=checked_publish):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)

    @_requires_descriptor_bound_publication
    def test_audit_uses_redaction_and_rejects_tampered_chain(self) -> None:
        proposal = self.propose(data=b"private source text must not reach audit\n")
        token = self.approve(proposal)
        self.assertEqual(ApplyOutcome.APPLIED, self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)

        journal = self.audit_directory / "journal.jsonl"
        serialized = journal.read_text(encoding="utf-8")
        self.assertNotIn(proposal["proposal_id"], serialized)
        self.assertNotIn("private source text", serialized)
        records = self.applier.audit.records()
        self.assertTrue(all("proposal_id" not in record for record in records))
        self.assertTrue(all(record["entry_digest"].startswith("hmac-sha256:") for record in records))

        journal.write_text(serialized.replace('"outcome":"applied"', '"outcome":"forged"'), encoding="utf-8")
        with self.assertRaises(ApplyRefused):
            self.applier.audit.records()

    @_requires_descriptor_bound_publication
    def test_audit_tail_truncation_is_detected_by_the_external_boundary(self) -> None:
        proposal = self.propose(data=b"auditable\n")
        token = self.approve(proposal)
        self.assertEqual(ApplyOutcome.APPLIED, self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)

        journal = self.audit_directory / "journal.jsonl"
        retained = journal.read_bytes().splitlines(keepends=True)
        self.assertEqual(2, len(retained))
        journal.write_bytes(b"".join(retained[:-1]))

        with self.assertRaisesRegex(ApplyRefused, "audit_unavailable"):
            self.applier.audit.records()
        blocked = self.propose(path="Notes/blocked-after-truncation.md")
        blocked_token = self.approve(blocked)
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=blocked["proposal_id"], token=blocked_token).outcome,
        )
        self.assertFalse((self.notes / "blocked-after-truncation.md").exists())

    @_requires_descriptor_bound_publication
    def test_recovery_serializes_read_verify_append_and_never_writes_source(self) -> None:
        proposal = self.propose(data=b"published before interruption\n")
        token = self.approve(proposal)
        original_publish = self.applier._publish_absent

        def interrupt_after_publish(path: str, data: bytes) -> None:
            original_publish(path, data)
            raise KeyboardInterrupt

        with mock.patch.object(self.applier, "_publish_absent", side_effect=interrupt_after_publish):
            with self.assertRaises(KeyboardInterrupt):
                self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        target = self.notes / "note.md"
        before_recovery = target.read_bytes()
        self.assertEqual(["pending"], [record["outcome"] for record in self.applier.audit.records()])
        recovered = self.applier.recover_incomplete_audit()
        self.assertEqual("applied_verified", recovered[0]["outcome"])
        self.assertEqual(before_recovery, target.read_bytes())
        self.assertEqual("recovery", recovered[0]["kind"])

    @_requires_descriptor_bound_publication
    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "requires POSIX fork")
    def test_cross_process_recovery_claims_pending_evidence_once(self) -> None:
        proposal = self.propose(data=b"published before concurrent recovery\n")
        token = self.approve(proposal)
        original_publish = self.applier._publish_absent

        def interrupt_after_publish(path: str, data: bytes) -> None:
            original_publish(path, data)
            raise KeyboardInterrupt

        with mock.patch.object(self.applier, "_publish_absent", side_effect=interrupt_after_publish):
            with self.assertRaises(KeyboardInterrupt):
                self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_recovery_worker,
                args=(str(self.root), str(self.audit_directory), str(self.audit_boundary), barrier, queue),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
            self.assertEqual(0, process.exitcode)
        self.assertEqual([0, 1], sorted(queue.get(timeout=2) for _ in processes))

        records = self.applier.audit.records()
        self.assertEqual(["pending", "applied_verified"], [record["outcome"] for record in records])
        self.assertEqual([1, 2], [record["journal_sequence"] for record in records])

    def test_replaced_journal_lock_is_refused_before_source_mutation(self) -> None:
        proposal = self.propose(path="Notes/no-lock-split.md")
        token = self.approve(proposal)
        lock = self.audit_directory / "journal.lock"
        lock.unlink()
        lock.write_bytes(b"replacement")
        lock.chmod(0o600)

        with self.assertRaisesRegex(ApplyRefused, "audit_unavailable"):
            self.applier.audit.records()
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome,
        )
        self.assertFalse((self.notes / "no-lock-split.md").exists())

    @_requires_descriptor_bound_publication
    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "requires POSIX fork")
    def test_cross_process_audit_chain_is_serialized_and_verified(self) -> None:
        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_create_worker,
                args=(
                    str(self.root),
                    str(self.audit_directory),
                    str(self.audit_boundary),
                    f"Notes/concurrent-{index}.md",
                    barrier,
                    queue,
                ),
            )
            for index in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
            self.assertEqual(0, process.exitcode)
        self.assertEqual(["applied", "applied"], sorted(queue.get(timeout=2) for _ in processes))

        records = self.applier.audit.records()
        self.assertEqual([1, 2, 3, 4], [record["journal_sequence"] for record in records])
        self.assertEqual(records[0]["entry_digest"], records[1]["previous_entry_digest"])
        self.assertEqual(records[1]["entry_digest"], records[2]["previous_entry_digest"])
        self.assertEqual(records[2]["entry_digest"], records[3]["previous_entry_digest"])

    def test_case_variant_denied_roots_and_allowlist_aliases_are_refused(self) -> None:
        cases: list[tuple[Path, Path, str]] = []
        self.temporary_root.chmod(0o700)
        try:
            for index, allowed_root in enumerate(("assets", "notes")):
                audit = Path(self.temporary.name) / f"case-audit-{index}"
                audit.mkdir(mode=0o700)
                boundary = Path(self.temporary.name) / f"case-boundary-{index}"
                provision_audit_boundary(audit, audit_key=AUDIT_KEY, boundary_path=boundary)
                cases.append((audit, boundary, allowed_root))
        finally:
            self.temporary_root.chmod(0o500)
        for audit, boundary, allowed_root in cases:
            with self.subTest(allowed_root=allowed_root):
                with self.assertRaisesRegex(ApplyRefused, "invalid_allowed_root"):
                    AtomicSingleFileApplier(
                        self.root,
                        allowed_roots=(allowed_root,),
                        audit_directory=audit,
                        audit_boundary_path=boundary,
                        owner_authority=TestOwnerAuthority(),
                        audit_key=AUDIT_KEY,
                    )

    def test_canonical_operational_directories_are_denied_in_nested_trees(self) -> None:
        # Iterate over the policy rather than a test-local duplicate: new
        # scanner-owned operational directories must automatically be denied
        # by atomic apply as well.
        for component in sorted(WRITEBACK_DENIED_DIRS):
            with self.subTest(component=component):
                with self.assertRaisesRegex(ApplyRefused, "policy_denied"):
                    self.propose(path=f"Notes/projects/review/{component}/archive/policy-bypass.md")
                self.assertFalse((self.notes / "projects" / "review" / component).exists())

    def test_trash_paths_and_case_variants_are_denied_at_every_depth(self) -> None:
        self.assertIn(".trash", SKIPPED_DIRS)
        denied_paths = (
            "Notes/.trash/accepted.md",
            "Notes/.TrAsH/accepted.md",
            "Notes/projects/.trash/archive/accepted.md",
            "Notes/projects/.TrAsH/archive/accepted.md",
        )
        for path in denied_paths:
            with self.subTest(path=path), self.assertRaisesRegex(ApplyRefused, "policy_denied"):
                self.propose(path=path)

    def test_trash_paths_and_case_variants_are_invalid_allowed_roots(self) -> None:
        for allowed_root in ("Notes/.trash", "Notes/.TrAsH", "Notes/projects/.trash"):
            with self.subTest(allowed_root=allowed_root), self.assertRaisesRegex(ApplyRefused, "invalid_allowed_root"):
                AtomicSingleFileApplier(
                    self.root,
                    allowed_roots=(allowed_root,),
                    audit_directory=self.audit_directory,
                    audit_boundary_path=self.audit_boundary,
                    owner_authority=TestOwnerAuthority(),
                    audit_key=AUDIT_KEY,
                )

    def test_canonical_operational_directory_patterns_are_case_aware(self) -> None:
        for prefix in WRITEBACK_DENIED_DIR_PREFIXES:
            for component in (f"{prefix}fixture", f"{prefix.swapcase()}fixture"):
                with self.subTest(component=component), self.assertRaisesRegex(ApplyRefused, "policy_denied"):
                    self.propose(path=f"Notes/projects/{component}/policy-bypass.md")

    def test_session_end_and_cancellation_invalidate_approved_tokens(self) -> None:
        session_ended = self.propose(path="Notes/session-ended.md")
        session_token = self.approve(session_ended)
        self.assertEqual(1, self.applier.end_owner_session("trusted-owner-session"))
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=session_ended["proposal_id"], token=session_token).outcome,
        )

        cancelled = self.propose(path="Notes/cancelled.md")
        cancelled_token = self.approve(cancelled)
        self.assertTrue(self.applier.cancel(cancelled["proposal_id"]))
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=cancelled["proposal_id"], token=cancelled_token).outcome,
        )
        self.assertFalse((self.notes / "session-ended.md").exists())
        self.assertFalse((self.notes / "cancelled.md").exists())

    def test_restart_and_server_root_or_policy_identity_change_invalidate_tokens(self) -> None:
        server_changed = self.propose(path="Notes/server-changed.md")
        server_token = self.approve(server_changed)
        self.applier._server_instance_id = "server-restarted"  # Simulate trusted host identity rotation.
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=server_changed["proposal_id"], token=server_token).outcome,
        )
        self.applier._server_instance_id = server_changed["metadata"]["server_instance_id"]

        policy_changed = self.propose(path="Notes/policy-changed.md")
        policy_token = self.approve(policy_changed)
        self.applier._policy_identity = "policy-reloaded"
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=policy_changed["proposal_id"], token=policy_token).outcome,
        )
        self.applier._policy_identity = "writeback-policy/v0.8"

        root_changed = self.propose(path="Notes/root-changed.md")
        root_token = self.approve(root_changed)
        self.applier._root_identity = (-1, -1)  # Simulate a root replacement detected before write.
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=root_changed["proposal_id"], token=root_token).outcome,
        )
        self.assertFalse((self.notes / "server-changed.md").exists())
        self.assertFalse((self.notes / "policy-changed.md").exists())
        self.assertFalse((self.notes / "root-changed.md").exists())

    def test_close_invalidates_private_state_so_a_restart_cannot_resume_it(self) -> None:
        proposal = self.propose(path="Notes/restart.md")
        token = self.approve(proposal)
        self.applier.close()
        self.assertEqual(
            ApplyOutcome.REFUSED,
            self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome,
        )
        self.assertFalse((self.notes / "restart.md").exists())

    @_requires_descriptor_bound_publication
    def test_path_escape_symlink_and_replay_are_refused(self) -> None:
        for path in ("Notes/../outside.md", "/Notes/note.md", "Notes\\note.md", "Notes/note.txt"):
            with self.subTest(path=path), self.assertRaises(ApplyRefused):
                self.propose(path=path)

        outside = self.outside_notes.parent
        os.symlink(outside, self.notes / "linked")
        with self.assertRaises(ApplyRefused):
            self.propose(path="Notes/linked/note.md")
        os.unlink(self.notes / "linked")

        proposal = self.propose()
        token = self.approve(proposal)
        self.assertEqual(ApplyOutcome.APPLIED, self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)
        self.assertEqual(ApplyOutcome.REFUSED, self.applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)

    def test_wall_clock_or_monotonic_expiry_refuses_before_source_mutation(self) -> None:
        now = [datetime(2026, 7, 18, tzinfo=timezone.utc)]
        monotonic = [100.0]
        authority = TestOwnerAuthority()
        applier = AtomicSingleFileApplier(
            self.root,
            allowed_roots=("Notes",),
            audit_directory=self.audit_directory,
            audit_boundary_path=self.audit_boundary,
            owner_authority=authority,
            audit_key=AUDIT_KEY,
            wall_clock=lambda: now[0],
            monotonic=lambda: monotonic[0],
        )
        try:
            proposal = applier.propose(operation="create_absent", path="Notes/expired.md", proposed_bytes=b"expired\n")
            token = applier.approve_from_trusted_owner(authority.confirm(proposal))
            now[0] += timedelta(seconds=601)
            self.assertEqual(ApplyOutcome.REFUSED, applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome)
            self.assertFalse((self.notes / "expired.md").exists())
        finally:
            applier.close()


if __name__ == "__main__":
    unittest.main()
