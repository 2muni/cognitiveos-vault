"""Trusted-owner approval types for the dormant writeback boundary.

Nothing in this module is an MCP tool.  In particular, it intentionally does
not offer a client-callable ``issue`` or ``approve`` operation.  The host
application must keep the :class:`TrustedOwnerAuthority` implementation on the
trusted local-owner side of its process boundary.  Proposal generators receive
only rendered public proposals and cannot manufacture an owner confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol


MAX_APPROVAL_LIFETIME_SECONDS = 10 * 60


def sha256_checksum(value: bytes) -> str:
    """Return the v0.8 lower-case SHA-256 checksum for exact bytes."""

    if not isinstance(value, bytes):
        raise TypeError("checksum input must be bytes")
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


@dataclass(frozen=True)
class OwnerConfirmation:
    """Opaque proof emitted by a trusted, authenticated local owner UI.

    ``proof`` is deliberately opaque to the writeback core.  A concrete owner
    authority can bind it to an OS-authenticated session, a local secure UI,
    and the displayed proposal.  Untrusted proposal callers must never be
    given the authority capable of constructing or validating such a proof.
    """

    proposal_id: str
    proof: object


class TrustedOwnerAuthority(Protocol):
    """Server-owned bridge to the trusted local owner approval channel."""

    def current_owner_session_binding(self) -> str:
        """Return the current authenticated owner's opaque session binding.

        This is called by the server while issuing a proposal.  It is not an
        argument accepted from a proposal generator or MCP caller.
        """

    def verify_owner_confirmation(
        self,
        *,
        confirmation: OwnerConfirmation,
        proposal_id: str,
        proposal_fingerprint: str,
        server_instance_id: str,
        owner_session_binding: str,
    ) -> bool:
        """Verify that the owner confirmed this exact displayed proposal."""
