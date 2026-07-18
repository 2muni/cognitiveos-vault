"""Test-only trusted owner authority; never used by the MCP server."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cognitiveos.approval import OwnerConfirmation


class TestOwnerAuthority:
    """Models a separate trusted owner UI with a private confirmation key."""

    def __init__(self, session_binding: str = "trusted-owner-session") -> None:
        self.session_binding = session_binding
        self._key = secrets.token_bytes(32)

    def current_owner_session_binding(self) -> str:
        return self.session_binding

    def confirm(self, proposal: dict[str, object]) -> OwnerConfirmation:
        metadata = proposal["metadata"]
        approval = proposal["approval"]
        assert isinstance(metadata, dict)
        assert isinstance(approval, dict)
        proposal_id = proposal["proposal_id"]
        fingerprint = proposal["proposal_fingerprint"]
        assert isinstance(proposal_id, str)
        assert isinstance(fingerprint, str)
        proof = self._proof(
            proposal_id=proposal_id,
            proposal_fingerprint=fingerprint,
            server_instance_id=metadata["server_instance_id"],
            owner_session_binding=approval["approval_session_binding"],
        )
        return OwnerConfirmation(proposal_id=proposal_id, proof=proof)

    def verify_owner_confirmation(
        self,
        *,
        confirmation: OwnerConfirmation,
        proposal_id: str,
        proposal_fingerprint: str,
        server_instance_id: str,
        owner_session_binding: str,
    ) -> bool:
        if owner_session_binding != self.session_binding or confirmation.proposal_id != proposal_id:
            return False
        expected = self._proof(
            proposal_id=proposal_id,
            proposal_fingerprint=proposal_fingerprint,
            server_instance_id=server_instance_id,
            owner_session_binding=owner_session_binding,
        )
        return isinstance(confirmation.proof, bytes) and hmac.compare_digest(confirmation.proof, expected)

    def _proof(
        self,
        *,
        proposal_id: object,
        proposal_fingerprint: object,
        server_instance_id: object,
        owner_session_binding: object,
    ) -> bytes:
        value = "\0".join(
            (str(proposal_id), str(proposal_fingerprint), str(server_instance_id), str(owner_session_binding))
        ).encode("utf-8")
        return hmac.new(self._key, value, hashlib.sha256).digest()
