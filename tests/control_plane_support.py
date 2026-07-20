"""Synthetic, disposable support for canonical-root control-plane tests only.

Nothing here is imported by the package.  The durable ledger uses a temporary
directory supplied by each Linux test and stores only capability IDs and public
fingerprints; it never receives vault content, paths, proof objects, or keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any

from cognitiveos.control_plane import (
    AuthorityRuntime,
    CapabilityVerificationStatus,
    ConfiguredVaultRootProvenance,
    DurableReplayLedger,
    LinuxObjectIdentity,
    OwnerCapabilityVerifier,
    ReplayClaim,
    ReplayClaimResult,
    TrustedOwnerCapability,
    AllowedRoot,
    CONTROL_PLANE_SCHEMA_VERSION,
    OWNER_CAPABILITY_SCHEMA_VERSION,
    provenance_digest,
)


FIXTURE_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
FIXTURE_PROOF = object()


class FixtureClock:
    """Mutable server-owned clock used to prove monotonic expiry behavior."""

    def __init__(self, *, wall_now: datetime = FIXTURE_NOW, monotonic_now: int = 1_000) -> None:
        self.wall_value = wall_now
        self.monotonic_value = monotonic_now

    def wall_now(self) -> datetime:
        return self.wall_value

    def monotonic_ns(self) -> int:
        return self.monotonic_value


class FixtureVerifier(OwnerCapabilityVerifier):
    """Opaque proof verifier with no issuer, signer, or key material."""

    def __init__(self, status: CapabilityVerificationStatus = CapabilityVerificationStatus.VALID) -> None:
        self.status = status
        self.calls = 0

    def verify_capability(
        self,
        *,
        capability: TrustedOwnerCapability,
        runtime: AuthorityRuntime,
    ) -> CapabilityVerificationStatus:
        self.calls += 1
        if capability.proof is not FIXTURE_PROOF:
            return CapabilityVerificationStatus.INVALID
        return self.status


class RecordingReplayLedger(DurableReplayLedger):
    """Thread-safe synthetic ledger for pure contract tests, never durable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claims: dict[str, str] = {}
        self.claims: list[ReplayClaim] = []

    def consume_once(self, claim: ReplayClaim) -> ReplayClaimResult:
        with self._lock:
            previous = self._claims.get(claim.capability_id)
            if previous is None:
                self._claims[claim.capability_id] = claim.capability_fingerprint
                self.claims.append(claim)
                return ReplayClaimResult.CONSUMED
            if previous == claim.capability_fingerprint:
                return ReplayClaimResult.REPLAYED
            return ReplayClaimResult.COLLISION


class DisposableLinuxReplayLedger(DurableReplayLedger):
    """A cross-process locked, fsynced replay fixture for Linux-only tests.

    The path is always supplied from a test ``TemporaryDirectory``.  It is
    deliberately test support rather than a production durable-state adapter.
    """

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock_path = state_path.with_name(state_path.name + ".lock")

    def consume_once(self, claim: ReplayClaim) -> ReplayClaimResult:
        if os.name != "posix":
            return ReplayClaimResult.UNAVAILABLE
        try:
            import fcntl

            lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                state = self._read_state()
                previous = state.get(claim.capability_id)
                if previous is not None:
                    return (
                        ReplayClaimResult.REPLAYED
                        if previous == claim.capability_fingerprint
                        else ReplayClaimResult.COLLISION
                    )
                state[claim.capability_id] = claim.capability_fingerprint
                self._write_state(state)
                return ReplayClaimResult.CONSUMED
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        except Exception:
            return ReplayClaimResult.UNAVAILABLE

    def _read_state(self) -> dict[str, str]:
        if not self._state_path.exists():
            return {}
        value = json.loads(self._state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
            raise ValueError("synthetic replay state is malformed")
        return value

    def _write_state(self, state: dict[str, str]) -> None:
        payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = self._state_path.with_name(self._state_path.name + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, self._state_path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(self._state_path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def fixture_provenance() -> ConfiguredVaultRootProvenance:
    """Return detached canonical-root evidence for a synthetic Linux fixture."""

    return ConfiguredVaultRootProvenance(
        schema_version=CONTROL_PLANE_SCHEMA_VERSION,
        configuration_id="fixture-config-0001",
        configuration_generation=7,
        canonical_root_path="/synthetic/vault",
        namespace_id="fixture-namespace-0001",
        root_identity=LinuxObjectIdentity(device=101, inode=201),
        allowed_roots=(
            AllowedRoot(
                root_id="fixture-notes-root",
                components=("Notes",),
                identity=LinuxObjectIdentity(device=101, inode=202),
            ),
            AllowedRoot(
                root_id="fixture-drafts-root",
                components=("Drafts",),
                identity=LinuxObjectIdentity(device=101, inode=203),
            ),
        ),
    )


def fixture_runtime(
    *,
    provenance: ConfiguredVaultRootProvenance | None = None,
    owner_session_id: str = "fixture-session-0001",
    server_instance_id: str = "fixture-server-0001",
    server_boot_id: str = "fixture-boot-0001",
    key_epoch: int = 4,
    revocation_epoch: int = 8,
) -> AuthorityRuntime:
    root = provenance or fixture_provenance()
    return AuthorityRuntime(
        authority_id="fixture-authority-0001",
        owner_session_id=owner_session_id,
        server_instance_id=server_instance_id,
        server_boot_id=server_boot_id,
        root_provenance_digest=provenance_digest(root),
        key_epoch=key_epoch,
        revocation_epoch=revocation_epoch,
    )


def fixture_capability(
    *,
    runtime: AuthorityRuntime,
    capability_id: str = "fixture-capability-0001",
    expires_at: datetime | None = None,
    monotonic_deadline_ns: int = 2_000,
    **changes: Any,
) -> TrustedOwnerCapability:
    """Construct a test-only externally-issued capability record."""

    values: dict[str, Any] = {
        "schema_version": OWNER_CAPABILITY_SCHEMA_VERSION,
        "capability_id": capability_id,
        "authority_id": runtime.authority_id,
        "owner_session_id": runtime.owner_session_id,
        "server_instance_id": runtime.server_instance_id,
        "server_boot_id": runtime.server_boot_id,
        "root_provenance_digest": runtime.root_provenance_digest,
        "key_epoch": runtime.key_epoch,
        "revocation_epoch": runtime.revocation_epoch,
        "issued_at": FIXTURE_NOW,
        "expires_at": expires_at or datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc),
        "monotonic_issued_ns": 1_000,
        "monotonic_deadline_ns": monotonic_deadline_ns,
        "proof_digest": "sha256:" + "1" * 64,
        "proof": FIXTURE_PROOF,
    }
    values.update(changes)
    return TrustedOwnerCapability(**values)
