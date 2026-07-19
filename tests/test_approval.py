from __future__ import annotations

import unittest

from cognitiveos.approval import OwnerConfirmation, sha256_checksum


class TrustedOwnerApprovalTypesTests(unittest.TestCase):
    def test_checksum_is_exact_and_owner_confirmation_is_opaque(self) -> None:
        confirmation = OwnerConfirmation(proposal_id="proposal-test", proof=object())

        self.assertEqual("proposal-test", confirmation.proposal_id)
        self.assertEqual(
            "sha256:4f9cae90a12eb84201bc0fa456bbb44abe856734fa5b115f912d36b1fe803dc6",
            sha256_checksum(b"line one\r\n"),
        )

    def test_checksum_rejects_non_bytes(self) -> None:
        with self.assertRaises(TypeError):
            sha256_checksum("not bytes")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
