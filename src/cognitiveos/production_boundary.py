"""Deny-only verification for a future production write boundary.

This module is deliberately not a control plane.  It has no MCP registration,
writer reference, filesystem mutation, policy loader, environment lookup, or
credential/key material.  A caller supplies one already-loaded, signed policy
and opaque authority adapters.  Even when every verification succeeds,
``ProductionBoundaryVerifier.evaluate`` returns ``DenialReason.DENY_ONLY``.

The contracts here are intentionally narrower than a future writeback system:

* the topology policy uses one canonical JSON spelling and a detached
  signature owned by an external topology-policy authority;
* topology checks use Linux descriptor operations, pinned device/inode
  identities, exact directory contents, and no-follow opens; and
* trusted-owner evidence is verified by an opaque, read-only authority
  interface.  This module neither issues nor consumes a capability.

Only disposable synthetic directories are used by this repository's tests.
Production deployment, policy provisioning, key custody, namespace discovery,
and writer integration require separate design, evidence, and approvals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Protocol
import unicodedata


TOPOLOGY_POLICY_SCHEMA_VERSION = "production-boundary-policy/v1"
OWNER_ATTESTATION_SCHEMA_VERSION = "trusted-owner-attestation/v1"
LINUX_TOPOLOGY_PLATFORM = "linux-descriptor-v1"

_CHECKSUM_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"([0-9]+):([0-9]+)\Z")
_OPAQUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}\Z")
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


class DenialReason(str, Enum):
    """Stable, non-sensitive reasons why the deny-only gate refused evidence."""

    DENY_ONLY = "deny_only"
    POLICY_EVIDENCE_MALFORMED = "policy_evidence_malformed"
    POLICY_NOT_CANONICAL = "policy_not_canonical"
    POLICY_SCHEMA_UNSUPPORTED = "policy_schema_unsupported"
    POLICY_SIGNATURE_INVALID = "policy_signature_invalid"
    POLICY_SIGNATURE_UNAVAILABLE = "policy_signature_unavailable"
    POLICY_SIGNATURE_REVOKED = "policy_signature_revoked"
    POLICY_SIGNATURE_ROTATED = "policy_signature_rotated"
    POLICY_NOT_YET_VALID = "policy_not_yet_valid"
    POLICY_EXPIRED = "policy_expired"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    NAMESPACE_EVIDENCE_UNAVAILABLE = "namespace_evidence_unavailable"
    NAMESPACE_EVIDENCE_MISMATCH = "namespace_evidence_mismatch"
    TOPOLOGY_EVIDENCE_UNAVAILABLE = "topology_evidence_unavailable"
    TOPOLOGY_DESCRIPTOR_UNSUPPORTED = "topology_descriptor_unsupported"
    TOPOLOGY_DESCRIPTOR_RACE = "topology_descriptor_race"
    TOPOLOGY_ANCESTOR_MISMATCH = "topology_ancestor_mismatch"
    TOPOLOGY_UNEXPECTED_ENTRY = "topology_unexpected_entry"
    TOPOLOGY_ENTRY_SET_MISMATCH = "topology_entry_set_mismatch"
    TOPOLOGY_SYMLINK = "topology_symlink"
    TOPOLOGY_HARD_LINK = "topology_hard_link"
    TOPOLOGY_SPECIAL_FILE = "topology_special_file"
    TOPOLOGY_KIND_MISMATCH = "topology_kind_mismatch"
    TOPOLOGY_DEVICE_MISMATCH = "topology_device_mismatch"
    TOPOLOGY_IDENTITY_MISMATCH = "topology_identity_mismatch"
    AUTHORITY_EVIDENCE_MALFORMED = "authority_evidence_malformed"
    AUTHORITY_ID_MISMATCH = "authority_id_mismatch"
    AUTHORITY_AUDIENCE_MISMATCH = "authority_audience_mismatch"
    AUTHORITY_SCOPE_MISMATCH = "authority_scope_mismatch"
    AUTHORITY_PROPOSAL_MISMATCH = "authority_proposal_mismatch"
    AUTHORITY_POLICY_MISMATCH = "authority_policy_mismatch"
    AUTHORITY_TOPOLOGY_MISMATCH = "authority_topology_mismatch"
    AUTHORITY_KEY_EPOCH_MISMATCH = "authority_key_epoch_mismatch"
    AUTHORITY_NOT_YET_VALID = "authority_not_yet_valid"
    AUTHORITY_EXPIRED = "authority_expired"
    AUTHORITY_INVALID = "authority_invalid"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    AUTHORITY_REVOKED = "authority_revoked"
    AUTHORITY_REPLAYED = "authority_replayed"
    AUTHORITY_ROTATED = "authority_rotated"


class _BoundaryRefused(ValueError):
    """Internal exception carrying only a public denial reason."""

    def __init__(self, reason: DenialReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class PolicySignatureStatus(str, Enum):
    """Possible results from an external topology-policy signature verifier."""

    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"
    ROTATED = "rotated"


class OwnerAuthorityStatus(str, Enum):
    """Possible results from the opaque trusted-owner authority verifier."""

    VERIFIED = "verified"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"
    REPLAYED = "replayed"
    ROTATED = "rotated"


class TopologyPolicySignatureVerifier(Protocol):
    """Verify a detached policy signature without exposing key custody.

    Implementations may use an owner-managed key service, hardware device, or
    an offline verifier.  This interface deliberately accepts only bytes and
    returns a status; it cannot issue policies, rotate keys, or change state.
    """

    def verify_topology_policy_signature(
        self,
        *,
        policy_bytes: bytes,
        signature: bytes,
        signer_id: str,
        key_epoch: int,
    ) -> PolicySignatureStatus:
        """Return the policy signature verification result."""


class NamespaceEvidenceProvider(Protocol):
    """Return an opaque identity for the qualified Linux namespace tuple.

    The provider is outside this module because deriving and qualifying a
    production namespace/mount/service tuple is a platform-control-plane
    responsibility.  Failure to return evidence must make verification deny.
    """

    def current_namespace_identity(self) -> str:
        """Return the current qualified namespace identity."""


class TrustedOwnerAuthorityVerifier(Protocol):
    """Read-only verification bridge to trusted owner authority.

    The interface has no method for issuing, approving, consuming, rotating,
    or revoking an owner capability.  A future write control plane must
    separately provide atomic capability consumption.  Here, a ``REPLAYED``
    result is only a deny signal from the external authority.
    """

    def verify_owner_attestation(
        self,
        *,
        attestation: "OwnerAttestation",
        expectation: "OwnerAuthorityExpectation",
    ) -> OwnerAuthorityStatus:
        """Return whether opaque owner evidence is valid for this expectation."""


@dataclass(frozen=True)
class SignedTopologyPolicy:
    """Detached signature envelope for one exact canonical policy byte string."""

    policy_bytes: bytes
    signature: bytes
    signer_id: str
    key_epoch: int


@dataclass(frozen=True)
class TopologyRole:
    """One pinned filesystem role below the topology anchor."""

    path: str
    parent: str
    kind: str
    identity: str
    link_count: int


@dataclass(frozen=True)
class TrustedOwnerRequirement:
    """Policy-pinned binding requirements for owner attestation evidence."""

    authority_id: str
    audience: str
    scope: str
    key_epoch: int
    minimum_revocation_epoch: int


@dataclass(frozen=True)
class ParsedTopologyPolicy:
    """The strict, verified interpretation of a signed policy."""

    policy_id: str
    digest: str
    topology_digest: str
    issued_at: datetime
    expires_at: datetime
    namespace_id: str
    anchor_identity: str
    anchor_parent_identity: str
    roles: Mapping[str, TopologyRole]
    trusted_owner: TrustedOwnerRequirement


@dataclass(frozen=True)
class OwnerAttestation:
    """Opaque trusted-owner evidence presented to the deny-only verifier.

    ``proof`` remains opaque to this module.  It can be a device assertion,
    a hardware-backed signature, or another authority-specific value, but it
    is never logged, persisted, or returned in a decision.
    """

    schema_version: str
    authority_id: str
    audience: str
    scope: str
    proposal_fingerprint: str
    policy_digest: str
    topology_digest: str
    issued_at: str
    expires_at: str
    nonce: str
    key_epoch: int
    revocation_epoch: int
    proof: object


@dataclass(frozen=True)
class DenyOnlyVerificationRequest:
    """Public bindings that a trusted owner attestation must match exactly."""

    proposal_fingerprint: str
    audience: str
    scope: str


@dataclass(frozen=True)
class OwnerAuthorityExpectation:
    """Immutable input passed to the opaque trusted-owner verifier."""

    authority_id: str
    audience: str
    scope: str
    proposal_fingerprint: str
    policy_digest: str
    topology_digest: str
    key_epoch: int
    minimum_revocation_epoch: int


@dataclass(frozen=True)
class VerifiedTopology:
    """Non-sensitive success evidence produced from a pinned topology policy."""

    digest: str


@dataclass(frozen=True)
class BoundaryDecision:
    """The only outcome of this foundation: a structured refusal."""

    reason: DenialReason
    policy_digest: str | None = None
    topology_digest: str | None = None
    authority_checked: bool = False

    @property
    def denied(self) -> bool:
        """Always true; this foundation can never authorize a write."""

        return True


def canonical_policy_json(value: object) -> bytes:
    """Encode the single accepted JSON spelling for topology-policy evidence."""

    _validate_canonical_value(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED) from exc


def parse_signed_topology_policy(
    signed_policy: object,
    *,
    signature_verifier: TopologyPolicySignatureVerifier,
    now: datetime,
) -> ParsedTopologyPolicy:
    """Verify and parse one canonical detached-signed topology policy.

    The signature is checked over the exact received bytes only after canonical
    decoding has shown that those bytes express the strict policy schema.
    """

    if not isinstance(signed_policy, SignedTopologyPolicy):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    if (
        not isinstance(signed_policy.policy_bytes, bytes)
        or not signed_policy.policy_bytes
        or not isinstance(signed_policy.signature, bytes)
        or not signed_policy.signature
        or not _is_opaque(signed_policy.signer_id)
        or not _is_nonnegative_int(signed_policy.key_epoch)
    ):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    now = _require_utc_datetime(now, DenialReason.POLICY_EVIDENCE_MALFORMED)
    policy_value = _decode_canonical_policy(signed_policy.policy_bytes)
    policy = _parse_policy_value(policy_value, signed_policy.policy_bytes)
    if policy_value["issuer"]["signer_id"] != signed_policy.signer_id or policy_value["issuer"][
        "key_epoch"
    ] != signed_policy.key_epoch:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    try:
        signature_status = signature_verifier.verify_topology_policy_signature(
            policy_bytes=signed_policy.policy_bytes,
            signature=signed_policy.signature,
            signer_id=signed_policy.signer_id,
            key_epoch=signed_policy.key_epoch,
        )
    except Exception as exc:
        raise _BoundaryRefused(DenialReason.POLICY_SIGNATURE_UNAVAILABLE) from exc
    _require_signature_status(signature_status)
    if now < policy.issued_at:
        raise _BoundaryRefused(DenialReason.POLICY_NOT_YET_VALID)
    if now >= policy.expires_at:
        raise _BoundaryRefused(DenialReason.POLICY_EXPIRED)
    return policy


class ProductionBoundaryVerifier:
    """Evaluate evidence and always stop at a deny-only production boundary.

    The supplied root is read only through descriptor APIs during ``evaluate``.
    It is never created, changed, deleted, or handed to any writer.  The
    constructor intentionally has no parameter through which a writer, MCP
    server, apply operation, or permission callback can be reached.
    """

    def __init__(
        self,
        fixture_or_production_root: str | Path,
        *,
        signed_policy: SignedTopologyPolicy,
        signature_verifier: TopologyPolicySignatureVerifier,
        namespace_provider: NamespaceEvidenceProvider,
        owner_authority: TrustedOwnerAuthorityVerifier,
        wall_clock: Callable[[], datetime],
    ) -> None:
        self._root = Path(fixture_or_production_root)
        self._signed_policy = signed_policy
        self._signature_verifier = signature_verifier
        self._namespace_provider = namespace_provider
        self._owner_authority = owner_authority
        self._wall_clock = wall_clock

    def evaluate(
        self,
        *,
        request: DenyOnlyVerificationRequest,
        attestation: OwnerAttestation,
    ) -> BoundaryDecision:
        """Verify all evidence then return a final refusal in every case."""

        try:
            now = _require_utc_datetime(self._wall_clock(), DenialReason.POLICY_EVIDENCE_MALFORMED)
            policy = parse_signed_topology_policy(
                self._signed_policy,
                signature_verifier=self._signature_verifier,
                now=now,
            )
        except _BoundaryRefused as exc:
            return BoundaryDecision(exc.reason)
        except Exception:
            return BoundaryDecision(DenialReason.POLICY_EVIDENCE_MALFORMED)

        try:
            _require_linux_descriptor_platform()
            try:
                namespace_identity = self._namespace_provider.current_namespace_identity()
            except Exception as exc:
                raise _BoundaryRefused(DenialReason.NAMESPACE_EVIDENCE_UNAVAILABLE) from exc
            if not _is_opaque(namespace_identity):
                raise _BoundaryRefused(DenialReason.NAMESPACE_EVIDENCE_UNAVAILABLE)
            if namespace_identity != policy.namespace_id:
                raise _BoundaryRefused(DenialReason.NAMESPACE_EVIDENCE_MISMATCH)
            topology = verify_pinned_topology(self._root, policy=policy)
        except _BoundaryRefused as exc:
            return BoundaryDecision(exc.reason, policy_digest=policy.digest)
        except Exception:
            return BoundaryDecision(DenialReason.TOPOLOGY_EVIDENCE_UNAVAILABLE, policy_digest=policy.digest)

        authority_verifier_called = False
        try:
            expectation = _validate_owner_bindings(
                policy=policy,
                topology=topology,
                request=request,
                attestation=attestation,
                now=now,
            )
            authority_verifier_called = True
            authority_status = self._owner_authority.verify_owner_attestation(
                attestation=attestation,
                expectation=expectation,
            )
            _require_owner_authority_status(authority_status)
        except _BoundaryRefused as exc:
            return BoundaryDecision(
                exc.reason,
                policy_digest=policy.digest,
                topology_digest=topology.digest,
                authority_checked=authority_verifier_called,
            )
        except Exception:
            return BoundaryDecision(
                DenialReason.AUTHORITY_UNAVAILABLE,
                policy_digest=policy.digest,
                topology_digest=topology.digest,
                authority_checked=authority_verifier_called,
            )

        return BoundaryDecision(
            DenialReason.DENY_ONLY,
            policy_digest=policy.digest,
            topology_digest=topology.digest,
            authority_checked=True,
        )


def verify_pinned_topology(
    root: str | Path,
    *,
    policy: ParsedTopologyPolicy,
    descriptor_opener: Callable[[str, int, int], int] | None = None,
) -> VerifiedTopology:
    """Verify a closed, pinned Linux topology without mutating any entry.

    ``descriptor_opener`` exists solely to permit deterministic synthetic race
    tests.  Production callers must leave it unset so the standard no-follow
    descriptor operation is used.
    """

    _require_linux_descriptor_platform()
    root_path = Path(root)
    root_before = _lstat(root_path)
    _assert_directory(root_before)
    if _identity(root_before) != policy.anchor_identity:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_IDENTITY_MISMATCH)
    root_parent_before = _lstat(root_path.parent)
    _assert_directory(root_parent_before)
    if _identity(root_parent_before) != policy.anchor_parent_identity:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_ANCESTOR_MISMATCH)

    root_fd = -1
    parent_fd = -1
    directory_fds: dict[str, int] = {}
    try:
        parent_fd = os.open(root_path.parent, _directory_open_flags())
        parent_info = os.fstat(parent_fd)
        _assert_directory(parent_info)
        if _identity(parent_info) != policy.anchor_parent_identity:
            raise _BoundaryRefused(DenialReason.TOPOLOGY_ANCESTOR_MISMATCH)
        root_fd = os.open(root_path.name, _directory_open_flags(), dir_fd=parent_fd)
        root_info = os.fstat(root_fd)
        _assert_directory(root_info)
        root_entry = os.stat(root_path.name, dir_fd=parent_fd, follow_symlinks=False)
        if _identity(root_entry) != _identity(root_info):
            raise _BoundaryRefused(DenialReason.TOPOLOGY_ANCESTOR_MISMATCH)
        if _identity(root_info) != policy.anchor_identity:
            raise _BoundaryRefused(DenialReason.TOPOLOGY_DESCRIPTOR_RACE)

        directory_fds["anchor"] = root_fd
        _assert_closed_world(directory_fds, policy=policy)
        for role_name in _ordered_roles(policy.roles):
            role = policy.roles[role_name]
            parent_fd_for_role = directory_fds[role.parent]
            before = os.stat(role.path.rsplit("/", 1)[-1], dir_fd=parent_fd_for_role, follow_symlinks=False)
            _assert_role(before, role=role, anchor_identity=policy.anchor_identity)
            entry_name = role.path.rsplit("/", 1)[-1]
            fd = _open_descriptor(entry_name, _role_open_flags(role.kind), parent_fd_for_role, descriptor_opener)
            try:
                after = os.fstat(fd)
                if _identity(before) != _identity(after):
                    raise _BoundaryRefused(DenialReason.TOPOLOGY_DESCRIPTOR_RACE)
                _assert_role(after, role=role, anchor_identity=policy.anchor_identity)
                if role.kind == "directory":
                    directory_fds[role_name] = fd
                    fd = -1
            finally:
                if fd >= 0:
                    os.close(fd)
        _assert_closed_world(directory_fds, policy=policy)
        return VerifiedTopology(policy.topology_digest)
    except _BoundaryRefused:
        raise
    except OSError as exc:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_EVIDENCE_UNAVAILABLE) from exc
    finally:
        closed: set[int] = set()
        for fd in (*directory_fds.values(), root_fd, parent_fd):
            if fd >= 0 and fd not in closed:
                closed.add(fd)
                os.close(fd)


def _decode_canonical_policy(payload: bytes) -> dict[str, Any]:
    try:
        decoded = payload.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED) from exc
    if canonical_policy_json(value) != payload:
        raise _BoundaryRefused(DenialReason.POLICY_NOT_CANONICAL)
    if not isinstance(value, dict):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return value


def _parse_policy_value(value: dict[str, Any], policy_bytes: bytes) -> ParsedTopologyPolicy:
    policy = _exact_object(
        value,
        {
            "schema_version",
            "policy_id",
            "issuer",
            "issued_at",
            "expires_at",
            "topology",
            "trusted_owner",
        },
    )
    if policy["schema_version"] != TOPOLOGY_POLICY_SCHEMA_VERSION:
        raise _BoundaryRefused(DenialReason.POLICY_SCHEMA_UNSUPPORTED)
    policy_id = _opaque(policy["policy_id"])
    issuer = _exact_object(policy["issuer"], {"signer_id", "key_epoch"})
    _opaque(issuer["signer_id"])
    if not _is_nonnegative_int(issuer["key_epoch"]):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    issued_at = _timestamp(policy["issued_at"])
    expires_at = _timestamp(policy["expires_at"])
    if expires_at <= issued_at:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)

    topology = _exact_object(policy["topology"], {"platform", "namespace_id", "anchor", "roles"})
    if topology["platform"] != LINUX_TOPOLOGY_PLATFORM:
        raise _BoundaryRefused(DenialReason.PLATFORM_UNSUPPORTED)
    namespace_id = _opaque(topology["namespace_id"])
    anchor = _exact_object(topology["anchor"], {"path", "identity", "parent_identity"})
    if anchor["path"] != ".":
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    anchor_identity = _identity_text(anchor["identity"])
    anchor_parent_identity = _identity_text(anchor["parent_identity"])
    roles = _parse_roles(topology["roles"], anchor_identity=anchor_identity)

    owner = _exact_object(
        policy["trusted_owner"],
        {"authority_id", "audience", "scope", "key_epoch", "minimum_revocation_epoch"},
    )
    trusted_owner = TrustedOwnerRequirement(
        authority_id=_opaque(owner["authority_id"]),
        audience=_opaque(owner["audience"]),
        scope=_opaque(owner["scope"]),
        key_epoch=_nonnegative_int(owner["key_epoch"]),
        minimum_revocation_epoch=_nonnegative_int(owner["minimum_revocation_epoch"]),
    )
    return ParsedTopologyPolicy(
        policy_id=policy_id,
        digest=_sha256(policy_bytes),
        topology_digest=_sha256(canonical_policy_json(topology)),
        issued_at=issued_at,
        expires_at=expires_at,
        namespace_id=namespace_id,
        anchor_identity=anchor_identity,
        anchor_parent_identity=anchor_parent_identity,
        roles=roles,
        trusted_owner=trusted_owner,
    )


def _parse_roles(value: object, *, anchor_identity: str) -> Mapping[str, TopologyRole]:
    if not isinstance(value, dict) or not value:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    roles: dict[str, TopologyRole] = {}
    identities = {anchor_identity}
    for name, raw_role in value.items():
        if not _is_opaque(name) or name == "anchor":
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        item = _exact_object(raw_role, {"path", "parent", "kind", "identity", "link_count"})
        path = _relative_role_path(item["path"])
        parent = item["parent"]
        if parent != "anchor" and (not isinstance(parent, str) or parent not in value or parent == name):
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        if item["kind"] not in {"directory", "regular_file"}:
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        identity = _identity_text(item["identity"])
        if identity in identities:
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        identities.add(identity)
        link_count = _nonnegative_int(item["link_count"])
        if link_count < 1:
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        roles[name] = TopologyRole(
            path=path,
            parent=parent,
            kind=item["kind"],
            identity=identity,
            link_count=link_count,
        )
    for name, role in roles.items():
        if role.parent == "anchor":
            if "/" in role.path:
                raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
            continue
        parent_role = roles.get(role.parent)
        if parent_role is None or parent_role.kind != "directory":
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        expected_prefix = f"{parent_role.path}/"
        if not role.path.startswith(expected_prefix) or "/" in role.path[len(expected_prefix) :]:
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return roles


def _validate_owner_bindings(
    *,
    policy: ParsedTopologyPolicy,
    topology: VerifiedTopology,
    request: object,
    attestation: object,
    now: datetime,
) -> OwnerAuthorityExpectation:
    if not isinstance(request, DenyOnlyVerificationRequest) or not isinstance(attestation, OwnerAttestation):
        raise _BoundaryRefused(DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    if (
        attestation.schema_version != OWNER_ATTESTATION_SCHEMA_VERSION
        or not _is_opaque(attestation.authority_id)
        or not _is_opaque(attestation.audience)
        or not _is_opaque(attestation.scope)
        or not _is_digest(attestation.proposal_fingerprint)
        or not _is_digest(attestation.policy_digest)
        or not _is_digest(attestation.topology_digest)
        or not _is_opaque(attestation.nonce)
        or not _is_nonnegative_int(attestation.key_epoch)
        or not _is_nonnegative_int(attestation.revocation_epoch)
    ):
        raise _BoundaryRefused(DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    if not _is_digest(request.proposal_fingerprint) or not _is_opaque(request.audience) or not _is_opaque(request.scope):
        raise _BoundaryRefused(DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    issued_at = _timestamp(attestation.issued_at, reason=DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    expires_at = _timestamp(attestation.expires_at, reason=DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    if expires_at <= issued_at:
        raise _BoundaryRefused(DenialReason.AUTHORITY_EVIDENCE_MALFORMED)
    if now < issued_at:
        raise _BoundaryRefused(DenialReason.AUTHORITY_NOT_YET_VALID)
    if now >= expires_at:
        raise _BoundaryRefused(DenialReason.AUTHORITY_EXPIRED)
    requirement = policy.trusted_owner
    if request.audience != requirement.audience or attestation.audience != requirement.audience:
        raise _BoundaryRefused(DenialReason.AUTHORITY_AUDIENCE_MISMATCH)
    if request.scope != requirement.scope or attestation.scope != requirement.scope:
        raise _BoundaryRefused(DenialReason.AUTHORITY_SCOPE_MISMATCH)
    if attestation.authority_id != requirement.authority_id:
        raise _BoundaryRefused(DenialReason.AUTHORITY_ID_MISMATCH)
    if attestation.proposal_fingerprint != request.proposal_fingerprint:
        raise _BoundaryRefused(DenialReason.AUTHORITY_PROPOSAL_MISMATCH)
    if attestation.policy_digest != policy.digest:
        raise _BoundaryRefused(DenialReason.AUTHORITY_POLICY_MISMATCH)
    if attestation.topology_digest != topology.digest:
        raise _BoundaryRefused(DenialReason.AUTHORITY_TOPOLOGY_MISMATCH)
    if attestation.key_epoch != requirement.key_epoch:
        raise _BoundaryRefused(DenialReason.AUTHORITY_KEY_EPOCH_MISMATCH)
    if attestation.revocation_epoch < requirement.minimum_revocation_epoch:
        raise _BoundaryRefused(DenialReason.AUTHORITY_REVOKED)
    return OwnerAuthorityExpectation(
        authority_id=requirement.authority_id,
        audience=requirement.audience,
        scope=requirement.scope,
        proposal_fingerprint=request.proposal_fingerprint,
        policy_digest=policy.digest,
        topology_digest=topology.digest,
        key_epoch=requirement.key_epoch,
        minimum_revocation_epoch=requirement.minimum_revocation_epoch,
    )


def _require_signature_status(status: object) -> None:
    if status is PolicySignatureStatus.VALID:
        return
    reasons = {
        PolicySignatureStatus.INVALID: DenialReason.POLICY_SIGNATURE_INVALID,
        PolicySignatureStatus.UNAVAILABLE: DenialReason.POLICY_SIGNATURE_UNAVAILABLE,
        PolicySignatureStatus.REVOKED: DenialReason.POLICY_SIGNATURE_REVOKED,
        PolicySignatureStatus.ROTATED: DenialReason.POLICY_SIGNATURE_ROTATED,
    }
    raise _BoundaryRefused(reasons.get(status, DenialReason.POLICY_SIGNATURE_UNAVAILABLE))


def _require_owner_authority_status(status: object) -> None:
    if status is OwnerAuthorityStatus.VERIFIED:
        return
    reasons = {
        OwnerAuthorityStatus.INVALID: DenialReason.AUTHORITY_INVALID,
        OwnerAuthorityStatus.UNAVAILABLE: DenialReason.AUTHORITY_UNAVAILABLE,
        OwnerAuthorityStatus.REVOKED: DenialReason.AUTHORITY_REVOKED,
        OwnerAuthorityStatus.REPLAYED: DenialReason.AUTHORITY_REPLAYED,
        OwnerAuthorityStatus.ROTATED: DenialReason.AUTHORITY_ROTATED,
    }
    raise _BoundaryRefused(reasons.get(status, DenialReason.AUTHORITY_UNAVAILABLE))


def _require_linux_descriptor_platform() -> None:
    if not _linux_descriptor_api_supported():
        raise _BoundaryRefused(DenialReason.TOPOLOGY_DESCRIPTOR_UNSUPPORTED)


def _linux_descriptor_api_supported() -> bool:
    return (
        sys.platform.startswith("linux")
        and os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    )


def _assert_closed_world(directory_fds: Mapping[str, int], *, policy: ParsedTopologyPolicy) -> None:
    expected_children: dict[str, set[str]] = {"anchor": set()}
    expected_children.update({name: set() for name, role in policy.roles.items() if role.kind == "directory"})
    for role in policy.roles.values():
        expected_children[role.parent].add(role.path.rsplit("/", 1)[-1])
    for name, directory_fd in directory_fds.items():
        try:
            actual = set(os.listdir(directory_fd))
        except OSError as exc:
            raise _BoundaryRefused(DenialReason.TOPOLOGY_EVIDENCE_UNAVAILABLE) from exc
        expected = expected_children[name]
        if actual - expected:
            raise _BoundaryRefused(DenialReason.TOPOLOGY_UNEXPECTED_ENTRY)
        if actual != expected:
            raise _BoundaryRefused(DenialReason.TOPOLOGY_ENTRY_SET_MISMATCH)


def _ordered_roles(roles: Mapping[str, TopologyRole]) -> list[str]:
    pending = dict(roles)
    ordered: list[str] = []
    parents = {"anchor"}
    while pending:
        ready = sorted(name for name, role in pending.items() if role.parent in parents)
        if not ready:
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        for name in ready:
            ordered.append(name)
            parents.add(name)
            pending.pop(name)
    return ordered


def _assert_role(info: os.stat_result, *, role: TopologyRole, anchor_identity: str) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise _BoundaryRefused(DenialReason.TOPOLOGY_SYMLINK)
    expected_kind = stat.S_ISDIR if role.kind == "directory" else stat.S_ISREG
    if not expected_kind(info.st_mode):
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            raise _BoundaryRefused(DenialReason.TOPOLOGY_SPECIAL_FILE)
        raise _BoundaryRefused(DenialReason.TOPOLOGY_KIND_MISMATCH)
    anchor_device, _ = _identity_parts(anchor_identity)
    if info.st_dev != anchor_device:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_DEVICE_MISMATCH)
    if info.st_nlink != role.link_count:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_HARD_LINK)
    if _identity(info) != role.identity:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_IDENTITY_MISMATCH)


def _assert_directory(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise _BoundaryRefused(DenialReason.TOPOLOGY_SYMLINK)
    if not stat.S_ISDIR(info.st_mode):
        raise _BoundaryRefused(DenialReason.TOPOLOGY_KIND_MISMATCH)


def _open_descriptor(
    name: str,
    flags: int,
    parent_fd: int,
    descriptor_opener: Callable[[str, int, int], int] | None,
) -> int:
    if descriptor_opener is not None:
        return descriptor_opener(name, flags, parent_fd)
    return os.open(name, flags, dir_fd=parent_fd)


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _role_open_flags(kind: str) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    return flags | (os.O_DIRECTORY if kind == "directory" else 0)


def _lstat(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise _BoundaryRefused(DenialReason.TOPOLOGY_EVIDENCE_UNAVAILABLE) from exc


def _identity(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}"


def _identity_parts(value: str) -> tuple[int, int]:
    matched = _IDENTITY_RE.fullmatch(value)
    if matched is None:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return int(matched.group(1)), int(matched.group(2))


def _identity_text(value: object) -> str:
    if not isinstance(value, str):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    _identity_parts(value)
    return value


def _relative_role_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    if value != unicodedata.normalize("NFC", value) or value.startswith(("/", "\\", "//")) or "\\" in value or ":" in value:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    components = value.split("/")
    if any(not component or component in {".", ".."} for component in components):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return value


def _timestamp(value: object, *, reason: DenialReason = DenialReason.POLICY_EVIDENCE_MALFORMED) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise _BoundaryRefused(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _BoundaryRefused(reason) from exc
    if parsed.tzinfo != timezone.utc:
        raise _BoundaryRefused(reason)
    return parsed


def _require_utc_datetime(value: object, reason: DenialReason) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo != timezone.utc:
        raise _BoundaryRefused(reason)
    return value


def _exact_object(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return value


def _opaque(value: object) -> str:
    if not _is_opaque(value):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return value


def _is_opaque(value: object) -> bool:
    return isinstance(value, str) and value == unicodedata.normalize("NFC", value) and bool(_OPAQUE_RE.fullmatch(value))


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(_CHECKSUM_RE.fullmatch(value))


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _nonnegative_int(value: object) -> int:
    if not _is_nonnegative_int(value):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    return value


def _validate_canonical_value(value: object) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if isinstance(value, float):
        raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
        for item in value.values():
            _validate_canonical_value(item)
        return
    raise _BoundaryRefused(DenialReason.POLICY_EVIDENCE_MALFORMED)
