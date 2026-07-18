import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from cognitiveos.approval import ApprovalOutcome, ApprovalTokenStore
from cognitiveos.atomic_apply import ApplyOutcome, ApplyRefused, AtomicSingleFileApplier


class AtomicSingleFileApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "vault"
        self.notes = self.root / "Notes"
        self.notes.mkdir(parents=True)
        self.audit = Path(self.temporary.name) / "audit"
        self.audit.mkdir(mode=0o700)
        self.applier = AtomicSingleFileApplier(
            self.root, allowed_roots=("Notes",), audit_directory=self.audit
        )
        self.approvals = ApprovalTokenStore("test-server")
        self.counter = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepare(self, *, operation: str = "replace_existing", **overrides: object):
        self.counter += 1
        defaults: dict[str, object] = {
            "proposal_id": f"proposal-{self.counter}",
            "proposal_fingerprint": f"sha256:{self.counter:064x}",
            "owner_session_binding": "local-owner",
            "operation": operation,
            "path": "Notes/note.md",
            "proposed_bytes": b"after\n",
        }
        return self.applier.prepare(**(defaults | overrides))

    def approve(self, proposal) -> str:
        token = self.approvals.issue(
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.proposal_fingerprint,
            owner_session_binding=proposal.owner_session_binding,
            base_bytes=proposal.base_bytes or b"",
        )
        self.assertEqual(
            ApprovalOutcome.READY,
            self.approvals.approve(
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.proposal_fingerprint,
                owner_session_binding=proposal.owner_session_binding,
                token=token,
            ).outcome,
        )
        return token

    def test_successfully_replaces_exact_prepared_bytes_and_audits(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\r\n")
        proposal = self.prepare(proposed_bytes=b"after\x00\n")
        token = self.approve(proposal)

        result = self.applier.apply(proposal, token=token, approvals=self.approvals)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(b"after\x00\n", target.read_bytes())
        records = self.applier.audit.records()
        self.assertEqual(["pending", "applied"], [record["outcome"] for record in records])
        self.assertEqual([1, 2], [record["journal_sequence"] for record in records])
        self.assertEqual(records[0]["entry_digest"], records[1]["previous_entry_digest"])

    def test_pending_audit_is_durable_before_source_mutation(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\n")
        proposal = self.prepare()
        token = self.approve(proposal)

        def before_replace() -> None:
            self.assertEqual(b"before\n", target.read_bytes())
            self.assertEqual(["pending"], [record["outcome"] for record in self.applier.audit.records()])

        result = self.applier.apply(
            proposal, token=token, approvals=self.approvals, before_replace=before_replace
        )

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)

    def test_create_absent_uses_the_approved_bytes(self) -> None:
        proposal = self.prepare(operation="create_absent", proposed_bytes=b"new note\n")
        token = self.approve(proposal)

        result = self.applier.apply(proposal, token=token, approvals=self.approvals)

        self.assertEqual(ApplyOutcome.APPLIED, result.outcome)
        self.assertEqual(b"new note\n", (self.notes / "note.md").read_bytes())

    def test_failure_after_replace_is_indeterminate_and_audited(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\n")
        proposal = self.prepare()
        token = self.approve(proposal)

        result = self.applier.apply(
            proposal,
            token=token,
            approvals=self.approvals,
            after_replace=lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )

        self.assertEqual(ApplyOutcome.INDETERMINATE, result.outcome)
        self.assertEqual(b"after\n", target.read_bytes())
        self.assertEqual(
            ["pending", "indeterminate"],
            [record["outcome"] for record in self.applier.audit.records()],
        )

    def test_interrupted_pending_entry_recovers_without_source_mutation(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\n")
        proposal = self.prepare()
        token = self.approve(proposal)

        with self.assertRaises(KeyboardInterrupt):
            self.applier.apply(
                proposal,
                token=token,
                approvals=self.approvals,
                after_replace=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            )

        self.assertEqual(["pending"], [record["outcome"] for record in self.applier.audit.records()])
        recovered = self.applier.recover_incomplete_audit()
        self.assertEqual("applied_verified", recovered[0]["outcome"])
        self.assertEqual(b"after\n", target.read_bytes())
        self.assertEqual("recovery", self.applier.audit.records()[-1]["kind"])

    def test_path_escape_and_symlink_targets_are_refused(self) -> None:
        with self.assertRaises(ApplyRefused):
            self.prepare(path="Notes/../outside.md")

        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        os.symlink(outside, self.notes / "linked")
        with self.assertRaises(ApplyRefused):
            self.prepare(path="Notes/linked/note.md")

        os.unlink(self.notes / "linked")
        os.symlink(outside / "note.md", self.notes / "note.md")
        with self.assertRaises(ApplyRefused):
            self.prepare()

    def test_checksum_conflict_consumes_token_and_preserves_changed_source(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\n")
        proposal = self.prepare()
        token = self.approve(proposal)
        target.write_bytes(b"concurrent change\n")

        result = self.applier.apply(proposal, token=token, approvals=self.approvals)

        self.assertEqual(ApplyOutcome.CONFLICT, result.outcome)
        self.assertEqual(b"concurrent change\n", target.read_bytes())
        self.assertEqual("conflict", self.applier.audit.records()[-1]["outcome"])
        self.assertEqual(
            ApprovalOutcome.REPLAYED,
            self.approvals.consume_for_revalidation(
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.proposal_fingerprint,
                owner_session_binding=proposal.owner_session_binding,
                token=token,
                observed_base_bytes=b"before\n",
            ).outcome,
        )

    def test_destructive_multi_file_and_unsupported_operations_are_refused(self) -> None:
        (self.notes / "note.md").write_bytes(b"before\n")
        for overrides in (
            {"operation": "delete"},
            {"operation": "rename"},
            {"bulk": True},
            {"destructive": True},
            {"changed_paths": ("Notes/note.md", "Notes/other.md")},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ApplyRefused):
                self.prepare(**overrides)

    def test_altered_prepared_proposal_is_refused_without_mutation(self) -> None:
        target = self.notes / "note.md"
        target.write_bytes(b"before\n")
        proposal = self.prepare()
        token = self.approve(proposal)

        result = self.applier.apply(
            replace(proposal, proposed_bytes=b"substituted\n"), token=token, approvals=self.approvals
        )

        self.assertEqual(ApplyOutcome.REFUSED, result.outcome)
        self.assertEqual(b"before\n", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
