from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest import mock

from cognitiveos.approval import OwnerConfirmation
from cognitiveos.atomic_apply import ApplyOutcome, ApplyRefused, AtomicSingleFileApplier

from writeback_support import TestOwnerAuthority


AUDIT_KEY = b"a" * 32


def _concurrent_create_worker(
    root: str,
    audit: str,
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
        owner_authority=authority,
        audit_key=AUDIT_KEY,
    )
    proposal = applier.propose(operation="create_absent", path=path, proposed_bytes=path.encode("utf-8"))
    token = applier.approve_from_trusted_owner(authority.confirm(proposal))
    barrier.wait(timeout=10)  # type: ignore[union-attr]
    queue.put(applier.apply(proposal_id=proposal["proposal_id"], token=token).outcome.value)  # type: ignore[union-attr]
    applier.close()


class AtomicSingleFileApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "vault"
        self.notes = self.root / "Notes"
        self.notes.mkdir(parents=True)
        self.audit_directory = Path(self.temporary.name) / "audit"
        self.audit_directory.mkdir(mode=0o700)
        self.owner = TestOwnerAuthority()
        self.applier = AtomicSingleFileApplier(
            self.root,
            allowed_roots=("Notes",),
            audit_directory=self.audit_directory,
            owner_authority=self.owner,
            audit_key=AUDIT_KEY,
        )

    def tearDown(self) -> None:
        self.applier.close()
        self.temporary.cleanup()

    def propose(self, *, path: str = "Notes/note.md", data: bytes = b"new note\n") -> dict[str, object]:
        return self.applier.propose(operation="create_absent", path=path, proposed_bytes=data)

    def approve(self, proposal: dict[str, object]) -> str:
        return self.applier.approve_from_trusted_owner(self.owner.confirm(proposal))

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

    def test_create_absent_publishes_only_after_the_temporary_file_is_complete(self) -> None:
        target = self.notes / "note.md"
        data = b"complete\x00\r\nbytes"
        proposal = self.propose(data=data)
        token = self.approve(proposal)
        original_link = os.link

        def checked_link(source: str, destination: str, **kwargs: object) -> None:
            self.assertFalse(target.exists(), "the final name must not expose partial bytes")
            self.assertEqual(data, (self.notes / source).read_bytes())
            original_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=checked_link):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(data, target.read_bytes())
        self.assertEqual(["pending", "applied"], [record["outcome"] for record in self.applier.audit.records()])

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

    def test_unsupported_atomic_create_refuses_without_creating_a_target(self) -> None:
        proposal = self.propose()
        token = self.approve(proposal)

        with mock.patch("cognitiveos.atomic_apply.os.link", side_effect=NotImplementedError):
            result = self.applier.apply(proposal_id=proposal["proposal_id"], token=token)

        self.assertEqual(ApplyOutcome.REFUSED, result.outcome)
        self.assertFalse((self.notes / "note.md").exists())

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

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "requires POSIX fork")
    def test_cross_process_audit_chain_is_serialized_and_verified(self) -> None:
        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_create_worker,
                args=(str(self.root), str(self.audit_directory), f"Notes/concurrent-{index}.md", barrier, queue),
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

    def test_path_escape_symlink_and_replay_are_refused(self) -> None:
        for path in ("Notes/../outside.md", "/Notes/note.md", "Notes\\note.md", "Notes/note.txt"):
            with self.subTest(path=path), self.assertRaises(ApplyRefused):
                self.propose(path=path)

        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
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
