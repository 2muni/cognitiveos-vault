"""In-memory approval capability handling for a future writeback service.

This module deliberately does not open, resolve, or mutate files.  A future
write path supplies bytes obtained through its verified file-handle flow and
uses ``consume_for_revalidation`` immediately before any mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import secrets
import threading
import time
from typing import Callable


MAX_APPROVAL_LIFETIME_SECONDS = 10 * 60


class ApprovalOutcome(str, Enum):
    """Deterministic outcomes for an attempted approval-boundary transition."""

    READY = "ready"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    NOT_APPROVED = "not_approved"
    REPLAYED = "replayed"
    TAMPERED = "tampered"


@dataclass(frozen=True)
class ApprovalAttempt:
    """The result of consuming a capability before a future write attempt."""

    outcome: ApprovalOutcome
    proposal_id: str


@dataclass
class _ApprovalRecord:
    proposal_id: str
    proposal_fingerprint: str
    server_instance_id: str
    owner_session_binding: str
    expected_base_checksum: str
    token_digest: bytes
    expires_at_monotonic: float
    state: str = "proposed"


def sha256_checksum(value: bytes) -> str:
    """Return the schema's lower-case SHA-256 checksum for exact bytes."""

    if not isinstance(value, bytes):
        raise TypeError("checksum input must be bytes")
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class ApprovalTokenStore:
    """Server-owned, one-time approval state for immutable proposals.

    ``approve`` represents a trusted local-owner confirmation.  It is kept
    separate from issuance so a proposal generator cannot self-authorize.
    State is process-local by design: restarting the server loses the records
    and therefore invalidates every outstanding capability.
    """

    def __init__(
        self, server_instance_id: str, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        if not server_instance_id:
            raise ValueError("server_instance_id is required")
        self._server_instance_id = server_instance_id
        self._monotonic = monotonic
        self._records: dict[str, _ApprovalRecord] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        proposal_id: str,
        proposal_fingerprint: str,
        owner_session_binding: str,
        base_bytes: bytes,
        lifetime_seconds: float = MAX_APPROVAL_LIFETIME_SECONDS,
    ) -> str:
        """Create a proposed capability and return its raw token exactly once."""

        if not proposal_id or not proposal_fingerprint or not owner_session_binding:
            raise ValueError("proposal ID, fingerprint, and owner session are required")
        if not 0 < lifetime_seconds <= MAX_APPROVAL_LIFETIME_SECONDS:
            raise ValueError("approval lifetime must be greater than zero and at most ten minutes")
        expected_base_checksum = sha256_checksum(base_bytes)
        token = secrets.token_urlsafe(32)
        token_digest = self._token_digest(
            token, proposal_id, proposal_fingerprint, owner_session_binding
        )
        record = _ApprovalRecord(
            proposal_id=proposal_id,
            proposal_fingerprint=proposal_fingerprint,
            server_instance_id=self._server_instance_id,
            owner_session_binding=owner_session_binding,
            expected_base_checksum=expected_base_checksum,
            token_digest=token_digest,
            expires_at_monotonic=self._monotonic() + lifetime_seconds,
        )
        with self._lock:
            if proposal_id in self._records:
                raise ValueError("proposal ID already exists")
            self._records[proposal_id] = record
        return token

    def approve(
        self,
        *,
        proposal_id: str,
        proposal_fingerprint: str,
        owner_session_binding: str,
        token: str,
    ) -> ApprovalAttempt:
        """Bind a trusted-owner confirmation to the one immutable proposal."""

        with self._lock:
            record = self._records.get(proposal_id)
            outcome = self._verify(record, proposal_fingerprint, owner_session_binding, token)
            if outcome is not None:
                return ApprovalAttempt(outcome, proposal_id)
            if record.state != "proposed":
                return ApprovalAttempt(ApprovalOutcome.REPLAYED, proposal_id)
            record.state = "approved"
            return ApprovalAttempt(ApprovalOutcome.READY, proposal_id)

    def consume_for_revalidation(
        self,
        *,
        proposal_id: str,
        proposal_fingerprint: str,
        owner_session_binding: str,
        token: str,
        observed_base_bytes: bytes,
    ) -> ApprovalAttempt:
        """Atomically consume approval, then compare a freshly read byte sequence.

        A conflict consumes the token too.  This makes every apply attempt
        replay-resistant and prevents a later retry from skipping revalidation.
        """

        with self._lock:
            record = self._records.get(proposal_id)
            outcome = self._verify(record, proposal_fingerprint, owner_session_binding, token)
            if outcome is not None:
                return ApprovalAttempt(outcome, proposal_id)
            if record.state != "approved":
                return ApprovalAttempt(ApprovalOutcome.REPLAYED, proposal_id)
            record.state = "consuming"
            if sha256_checksum(observed_base_bytes) != record.expected_base_checksum:
                record.state = "conflicted"
                return ApprovalAttempt(ApprovalOutcome.CONFLICT, proposal_id)
            return ApprovalAttempt(ApprovalOutcome.READY, proposal_id)

    def _verify(
        self,
        record: _ApprovalRecord | None,
        proposal_fingerprint: str,
        owner_session_binding: str,
        token: str,
    ) -> ApprovalOutcome | None:
        if record is None:
            return ApprovalOutcome.TAMPERED
        if record.server_instance_id != self._server_instance_id:
            return ApprovalOutcome.TAMPERED
        if record.state in {"consuming", "conflicted", "applied", "failed", "refused"}:
            return ApprovalOutcome.REPLAYED
        if self._monotonic() >= record.expires_at_monotonic:
            record.state = "expired"
            return ApprovalOutcome.EXPIRED
        if (
            record.proposal_fingerprint != proposal_fingerprint
            or record.owner_session_binding != owner_session_binding
            or not hmac.compare_digest(
                record.token_digest,
                self._token_digest(
                    token,
                    record.proposal_id,
                    proposal_fingerprint,
                    owner_session_binding,
                ),
            )
        ):
            return ApprovalOutcome.TAMPERED
        return None

    def _token_digest(
        self, token: str, proposal_id: str, proposal_fingerprint: str, owner_session_binding: str
    ) -> bytes:
        binding = "\0".join(
            (token, proposal_id, proposal_fingerprint, self._server_instance_id, owner_session_binding)
        ).encode("utf-8")
        return hashlib.sha256(binding).digest()
