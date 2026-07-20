"""Disconnected, default-off contracts for a future write control plane.

This module deliberately has no MCP registration, filesystem access, writer
dependency, configuration loader, environment lookup, or capability issuer.
It accepts only already-qualified, immutable evidence from a future trusted
bootstrap and returns structured refusals.  Even a successfully consumed owner
capability produces ``CONSUMED_DEFAULT_OFF``: it cannot authorize or perform an
operation.

The contracts are intentionally useful before an integration exists:

* configured vault-root provenance is immutable, absolute, and descriptor
  identity-bound; allowed roots are component-scoped and non-overlapping;
* a caller must provide Linux descriptor and namespace evidence, rather than a
  mutable path or process working directory; and
* trusted-owner capability consumption is delegated to a durable, atomic replay
  ledger with owner-session, server-boot, root-provenance, expiry, rotation,
  and revocation bindings.

Production bootstrap, Linux qualification, durable-ledger provisioning, owner
proof issuance, policy loading, and any operation integration are explicitly
outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Protocol
import unicodedata


CONTROL_PLANE_SCHEMA_VERSION = "canonical-root-control-plane/v1"
OWNER_CAPABILITY_SCHEMA_VERSION = "trusted-owner-capability/v1"
LINUX_DESCRIPTOR_EVIDENCE_VERSION = "linux-descriptor-evidence/v1"
MAX_CAPABILITY_LIFETIME = timedelta(minutes=10)

_OPAQUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}\Z")
_CHECKSUM_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class RootDecisionReason(str, Enum):
    """Stable outcomes for configured-root qualification and containment."""

    DEFAULT_OFF = "default_off"
    CONFIGURATION_INVALID = "configuration_invalid"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    NAMESPACE_MISMATCH = "namespace_mismatch"
    ROOT_ALIAS_REJECTED = "root_alias_rejected"
    ROOT_IDENTITY_MISMATCH = "root_identity_mismatch"
    DESCRIPTOR_RACE = "descriptor_race"
    ALLOWED_ROOT_MISMATCH = "allowed_root_mismatch"
    TARGET_OUTSIDE_ALLOWED_ROOT = "target_outside_allowed_root"
    TARGET_ALIAS_REJECTED = "target_alias_rejected"


class CapabilityDecisionReason(str, Enum):
    """Stable outcomes for one-time owner-capability consumption."""

    CONSUMED_DEFAULT_OFF = "consumed_default_off"
    CAPABILITY_INVALID = "capability_invalid"
    ROOT_PROVENANCE_MISMATCH = "root_provenance_mismatch"
    OWNER_SESSION_MISMATCH = "owner_session_mismatch"
    SERVER_INSTANCE_MISMATCH = "server_instance_mismatch"
    SERVER_RESTARTED = "server_restarted"
    ROTATED = "rotated"
    REVOKED = "revoked"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"
    PROOF_INVALID = "proof_invalid"
    PROOF_UNAVAILABLE = "proof_unavailable"
    REPLAYED = "replayed"
    REPLAY_COLLISION = "replay_collision"
    REPLAY_STATE_UNAVAILABLE = "replay_state_unavailable"


class CapabilityVerificationStatus(str, Enum):
    """Result supplied by the opaque, trusted owner proof verifier."""

    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class ReplayClaimResult(str, Enum):
    """Result of an atomic, durable replay-ledger insert attempt."""

    CONSUMED = "consumed"
    REPLAYED = "replayed"
    COLLISION = "collision"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LinuxObjectIdentity:
    """Pinned device/inode identity from a no-follow descriptor observation."""

    device: int
    inode: int


@dataclass(frozen=True)
class AllowedRoot:
    """One explicit non-root, vault-relative prefix and its pinned identity."""

    root_id: str
    components: tuple[str, ...]
    identity: LinuxObjectIdentity


@dataclass(frozen=True)
class ConfiguredVaultRootProvenance:
    """Immutable configuration evidence for one exact canonical vault root.

    ``canonical_root_path`` is an absolute, canonical POSIX spelling supplied
    by an external startup bootstrap.  This module does not resolve a path,
    infer a root from a working directory, read an environment variable, or
    load configuration.  An integration must keep this object immutable for the
    lifetime of a server boot and rebuild it after any configuration change.
    """

    schema_version: str
    configuration_id: str
    configuration_generation: int
    canonical_root_path: str
    namespace_id: str
    root_identity: LinuxObjectIdentity
    allowed_roots: tuple[AllowedRoot, ...]


@dataclass(frozen=True)
class LinuxDescriptorEvidence:
    """Read-only Linux evidence supplied by a separately qualified adapter.

    The adapter must have obtained identities through no-follow descriptor
    operations.  ``descriptor_race_detected`` is an explicit fail-closed signal
    when a path lookup and pinned descriptor no longer describe the same entry.
    The foundation never opens or resolves a filesystem path itself.
    """

    schema_version: str
    platform_supported: bool
    namespace_id: str
    requested_root_path: str
    canonical_root_path: str
    root_identity: LinuxObjectIdentity
    descriptor_race_detected: bool
    allowed_root_id: str
    allowed_root_identity: LinuxObjectIdentity
    target_components: tuple[str, ...]
    canonical_target_path: str


@dataclass(frozen=True)
class RootQualificationDecision:
    """A denial-only root decision; it never conveys filesystem authority."""

    reason: RootDecisionReason
    provenance_digest: str | None = None

    @property
    def denied(self) -> bool:
        """All results are denied because this foundation remains disconnected."""

        return True


def qualify_root_containment(
    provenance: object,
    evidence: object,
) -> RootQualificationDecision:
    """Validate canonical configured-root provenance and allowed-root scope.

    A fully matching evidence record deliberately returns ``DEFAULT_OFF``.  It
    is evidence for a future reviewed control-plane integration, not permission
    for a writer, caller, or process to open any target.
    """

    try:
        validated = _validate_provenance(provenance)
    except _ControlPlaneValidationError:
        return RootQualificationDecision(RootDecisionReason.CONFIGURATION_INVALID)

    digest = _provenance_digest(validated)
    if not isinstance(evidence, LinuxDescriptorEvidence):
        return RootQualificationDecision(RootDecisionReason.PLATFORM_UNSUPPORTED, digest)
    if evidence.schema_version != LINUX_DESCRIPTOR_EVIDENCE_VERSION or not evidence.platform_supported:
        return RootQualificationDecision(RootDecisionReason.PLATFORM_UNSUPPORTED, digest)
    if evidence.descriptor_race_detected:
        return RootQualificationDecision(RootDecisionReason.DESCRIPTOR_RACE, digest)
    if evidence.namespace_id != validated.namespace_id:
        return RootQualificationDecision(RootDecisionReason.NAMESPACE_MISMATCH, digest)
    if not _is_canonical_absolute_path(evidence.requested_root_path):
        return RootQualificationDecision(RootDecisionReason.ROOT_ALIAS_REJECTED, digest)
    if (
        evidence.requested_root_path != validated.canonical_root_path
        or evidence.canonical_root_path != validated.canonical_root_path
    ):
        return RootQualificationDecision(RootDecisionReason.ROOT_ALIAS_REJECTED, digest)
    if evidence.root_identity != validated.root_identity:
        return RootQualificationDecision(RootDecisionReason.ROOT_IDENTITY_MISMATCH, digest)

    selected = next((root for root in validated.allowed_roots if root.root_id == evidence.allowed_root_id), None)
    if selected is None or evidence.allowed_root_identity != selected.identity:
        return RootQualificationDecision(RootDecisionReason.ALLOWED_ROOT_MISMATCH, digest)
    if not _components_are_canonical(evidence.target_components):
        return RootQualificationDecision(RootDecisionReason.TARGET_ALIAS_REJECTED, digest)
    if evidence.target_components[: len(selected.components)] != selected.components:
        return RootQualificationDecision(RootDecisionReason.TARGET_OUTSIDE_ALLOWED_ROOT, digest)

    expected_target = _join_absolute_path(validated.canonical_root_path, evidence.target_components)
    if evidence.canonical_target_path != expected_target or not _is_canonical_absolute_path(evidence.canonical_target_path):
        return RootQualificationDecision(RootDecisionReason.TARGET_ALIAS_REJECTED, digest)
    return RootQualificationDecision(RootDecisionReason.DEFAULT_OFF, digest)


def provenance_digest(provenance: ConfiguredVaultRootProvenance) -> str:
    """Return the digest of validated, authorization-relevant root evidence."""

    return _provenance_digest(_validate_provenance(provenance))


@dataclass(frozen=True)
class TrustedOwnerCapability:
    """An externally issued opaque one-time capability presented for consumption.

    This type does not issue, approve, sign, rotate, or revoke anything.  The
    proof is passed only to an external verifier and is neither serialized nor
    placed in the durable replay claim.  ``proof_digest`` commits the public
    capability fingerprint to its exact verifier-owned proof representation.
    """

    schema_version: str
    capability_id: str
    authority_id: str
    owner_session_id: str
    server_instance_id: str
    server_boot_id: str
    root_provenance_digest: str
    key_epoch: int
    revocation_epoch: int
    issued_at: datetime
    expires_at: datetime
    monotonic_issued_ns: int
    monotonic_deadline_ns: int
    proof_digest: str
    proof: object


@dataclass(frozen=True)
class AuthorityRuntime:
    """Server-owned bindings used by one consumer during exactly one boot."""

    authority_id: str
    owner_session_id: str
    server_instance_id: str
    server_boot_id: str
    root_provenance_digest: str
    key_epoch: int
    revocation_epoch: int


@dataclass(frozen=True)
class ReplayClaim:
    """Non-sensitive durable evidence that a capability was consumed once."""

    capability_id: str
    capability_fingerprint: str
    authority_id: str
    server_instance_id: str
    server_boot_id: str
    root_provenance_digest: str


@dataclass(frozen=True)
class CapabilityConsumptionDecision:
    """A terminal result from consuming an owner capability.

    ``CONSUMED_DEFAULT_OFF`` proves only that the durable ledger accepted a
    bound capability.  It intentionally does not issue a token or an action.
    """

    reason: CapabilityDecisionReason
    capability_fingerprint: str | None = None

    @property
    def denied(self) -> bool:
        """All results are denied until a separately reviewed integration exists."""

        return True


class OwnerCapabilityVerifier(Protocol):
    """Verify an opaque proof without exposing issuance or key custody."""

    def verify_capability(
        self,
        *,
        capability: TrustedOwnerCapability,
        runtime: AuthorityRuntime,
    ) -> CapabilityVerificationStatus:
        """Return whether the verifier accepts this exact opaque capability."""


class DurableReplayLedger(Protocol):
    """Atomically persist one capability fingerprint or refuse it.

    A production adapter must use one owner-only durable store and a
    cross-process lock/transaction.  Before returning ``CONSUMED`` it must make
    the claim durable; after a crash or restart, the same capability ID and
    fingerprint must return ``REPLAYED``.  A reused ID with another fingerprint
    must return ``COLLISION``.  Repair, truncation, auto-retry, and state reset
    are out of scope and must fail closed as ``UNAVAILABLE``.
    """

    def consume_once(self, claim: ReplayClaim) -> ReplayClaimResult:
        """Atomically make ``claim`` durable exactly once."""


class AuthorityClock(Protocol):
    """Server-owned wall and monotonic clocks; callers never supply time."""

    def wall_now(self) -> datetime:
        """Return an aware UTC wall clock value."""

    def monotonic_ns(self) -> int:
        """Return time from the current server boot's monotonic domain."""


class TrustedOwnerAuthority:
    """Consume a capability once, then deliberately stop at the deny boundary.

    The consumer first verifies immutable bindings and both clock deadlines,
    then validates the opaque proof, then asks the durable ledger to atomically
    consume the capability.  No target is opened and no route or callback is
    invoked after a successful claim.
    """

    def __init__(
        self,
        *,
        runtime: AuthorityRuntime,
        verifier: OwnerCapabilityVerifier,
        replay_ledger: DurableReplayLedger,
        clock: AuthorityClock,
    ) -> None:
        _validate_runtime(runtime)
        if not hasattr(verifier, "verify_capability") or not hasattr(replay_ledger, "consume_once"):
            raise ValueError("trusted owner authority requires verifier and durable replay ledger")
        if not hasattr(clock, "wall_now") or not hasattr(clock, "monotonic_ns"):
            raise ValueError("trusted owner authority requires a server clock")
        self._runtime = runtime
        self._verifier = verifier
        self._replay_ledger = replay_ledger
        self._clock = clock

    def consume(self, capability: object) -> CapabilityConsumptionDecision:
        """Atomically consume one valid capability and remain default-off."""

        if not isinstance(capability, TrustedOwnerCapability):
            return CapabilityConsumptionDecision(CapabilityDecisionReason.CAPABILITY_INVALID)
        try:
            fingerprint = capability_fingerprint(capability)
        except _ControlPlaneValidationError:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.CAPABILITY_INVALID)
        if capability.root_provenance_digest != self._runtime.root_provenance_digest:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.ROOT_PROVENANCE_MISMATCH, fingerprint)
        if capability.owner_session_id != self._runtime.owner_session_id:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.OWNER_SESSION_MISMATCH, fingerprint)
        if capability.server_instance_id != self._runtime.server_instance_id:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.SERVER_INSTANCE_MISMATCH, fingerprint)
        if capability.server_boot_id != self._runtime.server_boot_id:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.SERVER_RESTARTED, fingerprint)
        if capability.authority_id != self._runtime.authority_id or capability.key_epoch != self._runtime.key_epoch:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.ROTATED, fingerprint)
        if capability.revocation_epoch != self._runtime.revocation_epoch:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.REVOKED, fingerprint)
        lifetime_reason = _lifetime_reason(capability, self._clock)
        if lifetime_reason is not None:
            return CapabilityConsumptionDecision(lifetime_reason, fingerprint)
        try:
            proof_status = self._verifier.verify_capability(capability=capability, runtime=self._runtime)
        except Exception:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.PROOF_UNAVAILABLE, fingerprint)
        if proof_status == CapabilityVerificationStatus.INVALID:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.PROOF_INVALID, fingerprint)
        if proof_status != CapabilityVerificationStatus.VALID:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.PROOF_UNAVAILABLE, fingerprint)

        claim = ReplayClaim(
            capability_id=capability.capability_id,
            capability_fingerprint=fingerprint,
            authority_id=capability.authority_id,
            server_instance_id=capability.server_instance_id,
            server_boot_id=capability.server_boot_id,
            root_provenance_digest=capability.root_provenance_digest,
        )
        try:
            replay_result = self._replay_ledger.consume_once(claim)
        except Exception:
            replay_result = ReplayClaimResult.UNAVAILABLE
        if replay_result == ReplayClaimResult.CONSUMED:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.CONSUMED_DEFAULT_OFF, fingerprint)
        if replay_result == ReplayClaimResult.REPLAYED:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.REPLAYED, fingerprint)
        if replay_result == ReplayClaimResult.COLLISION:
            return CapabilityConsumptionDecision(CapabilityDecisionReason.REPLAY_COLLISION, fingerprint)
        return CapabilityConsumptionDecision(CapabilityDecisionReason.REPLAY_STATE_UNAVAILABLE, fingerprint)


def capability_fingerprint(capability: TrustedOwnerCapability) -> str:
    """Hash all authorization-relevant public capability fields, never its proof."""

    _validate_capability(capability)
    public = {
        "authority_id": capability.authority_id,
        "capability_id": capability.capability_id,
        "expires_at": _utc_timestamp(capability.expires_at),
        "issued_at": _utc_timestamp(capability.issued_at),
        "key_epoch": capability.key_epoch,
        "monotonic_deadline_ns": capability.monotonic_deadline_ns,
        "monotonic_issued_ns": capability.monotonic_issued_ns,
        "owner_session_id": capability.owner_session_id,
        "proof_digest": capability.proof_digest,
        "revocation_epoch": capability.revocation_epoch,
        "root_provenance_digest": capability.root_provenance_digest,
        "schema_version": capability.schema_version,
        "server_boot_id": capability.server_boot_id,
        "server_instance_id": capability.server_instance_id,
    }
    return _checksum(_canonical_json(public))


class _ControlPlaneValidationError(ValueError):
    """Internal validation failure kept out of public decisions."""


def _validate_provenance(value: object) -> ConfiguredVaultRootProvenance:
    if not isinstance(value, ConfiguredVaultRootProvenance):
        raise _ControlPlaneValidationError()
    if (
        value.schema_version != CONTROL_PLANE_SCHEMA_VERSION
        or not _is_opaque(value.configuration_id)
        or not _is_nonnegative_int(value.configuration_generation)
        or not _is_opaque(value.namespace_id)
        or not _is_canonical_absolute_path(value.canonical_root_path)
        or not _valid_identity(value.root_identity)
        or not isinstance(value.allowed_roots, tuple)
        or not value.allowed_roots
    ):
        raise _ControlPlaneValidationError()
    root_ids: set[str] = set()
    component_sets: list[tuple[str, ...]] = []
    for root in value.allowed_roots:
        if (
            not isinstance(root, AllowedRoot)
            or not _is_opaque(root.root_id)
            or root.root_id in root_ids
            or not _components_are_canonical(root.components)
            or not _valid_identity(root.identity)
        ):
            raise _ControlPlaneValidationError()
        root_ids.add(root.root_id)
        component_sets.append(root.components)
    for left_index, left in enumerate(component_sets):
        for right in component_sets[left_index + 1 :]:
            if left[: len(right)] == right or right[: len(left)] == left:
                raise _ControlPlaneValidationError()
    return value


def _provenance_digest(provenance: ConfiguredVaultRootProvenance) -> str:
    public = {
        "allowed_roots": [
            {
                "components": list(root.components),
                "identity": {"device": root.identity.device, "inode": root.identity.inode},
                "root_id": root.root_id,
            }
            for root in provenance.allowed_roots
        ],
        "canonical_root_path": provenance.canonical_root_path,
        "configuration_generation": provenance.configuration_generation,
        "configuration_id": provenance.configuration_id,
        "namespace_id": provenance.namespace_id,
        "root_identity": {
            "device": provenance.root_identity.device,
            "inode": provenance.root_identity.inode,
        },
        "schema_version": provenance.schema_version,
    }
    return _checksum(_canonical_json(public))


def _validate_runtime(runtime: object) -> None:
    if not isinstance(runtime, AuthorityRuntime):
        raise _ControlPlaneValidationError()
    if not all(
        _is_opaque(value)
        for value in (
            runtime.authority_id,
            runtime.owner_session_id,
            runtime.server_instance_id,
            runtime.server_boot_id,
        )
    ):
        raise _ControlPlaneValidationError()
    if not _is_checksum(runtime.root_provenance_digest):
        raise _ControlPlaneValidationError()
    if not _is_nonnegative_int(runtime.key_epoch) or not _is_nonnegative_int(runtime.revocation_epoch):
        raise _ControlPlaneValidationError()


def _validate_capability(capability: TrustedOwnerCapability) -> None:
    if capability.schema_version != OWNER_CAPABILITY_SCHEMA_VERSION:
        raise _ControlPlaneValidationError()
    if not all(
        _is_opaque(value)
        for value in (
            capability.capability_id,
            capability.authority_id,
            capability.owner_session_id,
            capability.server_instance_id,
            capability.server_boot_id,
        )
    ):
        raise _ControlPlaneValidationError()
    if not _is_checksum(capability.root_provenance_digest) or not _is_checksum(capability.proof_digest):
        raise _ControlPlaneValidationError()
    if not _is_nonnegative_int(capability.key_epoch) or not _is_nonnegative_int(capability.revocation_epoch):
        raise _ControlPlaneValidationError()
    issued = _require_utc(capability.issued_at)
    expires = _require_utc(capability.expires_at)
    if expires <= issued or expires - issued > MAX_CAPABILITY_LIFETIME:
        raise _ControlPlaneValidationError()
    if (
        not _is_nonnegative_int(capability.monotonic_issued_ns)
        or not _is_nonnegative_int(capability.monotonic_deadline_ns)
        or capability.monotonic_deadline_ns <= capability.monotonic_issued_ns
        or capability.monotonic_deadline_ns - capability.monotonic_issued_ns > int(MAX_CAPABILITY_LIFETIME.total_seconds() * 1_000_000_000)
    ):
        raise _ControlPlaneValidationError()


def _lifetime_reason(
    capability: TrustedOwnerCapability,
    clock: AuthorityClock,
) -> CapabilityDecisionReason | None:
    try:
        wall_now = _require_utc(clock.wall_now())
        monotonic_now = clock.monotonic_ns()
    except Exception:
        return CapabilityDecisionReason.EXPIRED
    if not _is_nonnegative_int(monotonic_now):
        return CapabilityDecisionReason.EXPIRED
    if wall_now >= capability.expires_at or monotonic_now >= capability.monotonic_deadline_ns:
        return CapabilityDecisionReason.EXPIRED
    if wall_now < capability.issued_at or monotonic_now < capability.monotonic_issued_ns:
        return CapabilityDecisionReason.NOT_YET_VALID
    return None


def _valid_identity(value: object) -> bool:
    return isinstance(value, LinuxObjectIdentity) and _is_nonnegative_int(value.device) and _is_nonnegative_int(value.inode)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_opaque(value: object) -> bool:
    return isinstance(value, str) and bool(_OPAQUE_RE.fullmatch(value))


def _is_checksum(value: object) -> bool:
    return isinstance(value, str) and bool(_CHECKSUM_RE.fullmatch(value))


def _components_are_canonical(value: object) -> bool:
    if not isinstance(value, tuple) or not value:
        return False
    for component in value:
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
            or unicodedata.normalize("NFC", component) != component
        ):
            return False
    return True


def _is_canonical_absolute_path(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or "\\" in value or "\x00" in value:
        return False
    if unicodedata.normalize("NFC", value) != value:
        return False
    if value == "/":
        return True
    pieces = value.split("/")
    return pieces[0] == "" and all(piece and piece not in {".", ".."} for piece in pieces[1:])


def _join_absolute_path(root: str, components: tuple[str, ...]) -> str:
    return root.rstrip("/") + "/" + "/".join(components)


def _require_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise _ControlPlaneValidationError()
    return value


def _utc_timestamp(value: datetime) -> str:
    return _require_utc(value).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _checksum(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
