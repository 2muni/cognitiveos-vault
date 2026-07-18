from __future__ import annotations

import unittest

from cognitiveos.approval import ApprovalOutcome, ApprovalTokenStore, sha256_checksum


class ApprovalTokenStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.store = ApprovalTokenStore("server-1", monotonic=lambda: self.now)
        self.values = {
            "proposal_id": "proposal-1",
            "proposal_fingerprint": "sha256:" + "a" * 64,
            "owner_session_binding": "owner-session-1",
        }

    def issue(self, base: bytes = b"before", **overrides: object) -> str:
        return self.store.issue(**self.values, base_bytes=base, **overrides)

    def approve(self, token: str, **overrides: str) -> ApprovalOutcome:
        return self.store.approve(**(self.values | overrides), token=token).outcome

    def consume(self, token: str, observed: bytes = b"before", **overrides: str) -> ApprovalOutcome:
        return self.store.consume_for_revalidation(
            **(self.values | overrides), token=token, observed_base_bytes=observed
        ).outcome

    def test_valid_approval_consumes_once_after_exact_byte_revalidation(self) -> None:
        token = self.issue(b"line one\r\n")

        self.assertEqual(ApprovalOutcome.READY, self.approve(token))
        self.assertEqual(ApprovalOutcome.READY, self.consume(token, b"line one\r\n"))
        self.assertEqual("sha256:4f9cae90a12eb84201bc0fa456bbb44abe856734fa5b115f912d36b1fe803dc6", sha256_checksum(b"line one\r\n"))

    def test_expired_token_is_refused_before_approval(self) -> None:
        token = self.issue(lifetime_seconds=1)
        self.now += 1

        self.assertEqual(ApprovalOutcome.EXPIRED, self.approve(token))

    def test_replayed_token_is_refused_after_consumption(self) -> None:
        token = self.issue()
        self.assertEqual(ApprovalOutcome.READY, self.approve(token))
        self.assertEqual(ApprovalOutcome.READY, self.consume(token))

        self.assertEqual(ApprovalOutcome.REPLAYED, self.consume(token))

    def test_mismatched_token_or_proposal_identity_is_refused(self) -> None:
        token = self.issue()

        self.assertEqual(ApprovalOutcome.TAMPERED, self.approve("not-the-issued-token"))
        self.assertEqual(
            ApprovalOutcome.TAMPERED,
            self.approve(token, proposal_fingerprint="sha256:" + "b" * 64),
        )
        self.assertEqual(ApprovalOutcome.READY, self.approve(token))

    def test_checksum_conflict_consumes_the_approval(self) -> None:
        token = self.issue(b"before\n")
        self.assertEqual(ApprovalOutcome.READY, self.approve(token))

        self.assertEqual(ApprovalOutcome.CONFLICT, self.consume(token, b"before\r\n"))
        self.assertEqual(ApprovalOutcome.REPLAYED, self.consume(token, b"before\n"))


if __name__ == "__main__":
    unittest.main()
