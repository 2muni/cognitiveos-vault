"""Disposable-fixture topology and owner-authority test support.

This module is deliberately located under ``tests``.  It is not packaged, has
no MCP entry point, cannot invoke the production writer, and is useful only
for negative validation against disposable synthetic directories.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable, Iterable, Mapping

from cognitiveos.approval import OwnerConfirmation


TOPOLOGY_SCHEMA_VERSION = "fixture-only-topology/v1"
_ROLE_NAMES = ("root", "audit", "lock", "boundary")
_ROLE_SHAPES = {
    "root": ("vault", "anchor", "directory", None),
    "audit": ("audit", "anchor", "directory", None),
    "lock": ("audit/journal.lock", "audit", "regular_file", 1),
    "boundary": ("audit-boundary", "anchor", "regular_file", 1),
}
_EXPECTED_ROOT_ENTRIES = frozenset({"vault", "audit", "audit-boundary"})
_EXPECTED_AUDIT_ENTRIES = frozenset({"journal.lock"})
_IDENTITY_RE = re.compile(r"[0-9]+:[0-9]+\Z")
_OPAQUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
FIXTURE_AUDIENCE = "fixture-server-audience"
FIXTURE_POLICY_DIGEST = "sha256:" + hashlib.sha256(b"fixture-only-policy/v1").hexdigest()


class FixtureTopologyRefused(ValueError):
    """A synthetic topology did not match its immutable fixture manifest."""


class FixtureAuthorityRefused(ValueError):
    """A fake owner-authority request was malformed before handle issuance."""


def _canonical_json(value: object) -> bytes:
    """Encode the one permitted JSON spelling for this fixture contract."""

    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise FixtureTopologyRefused("manifest_not_json") from exc


def _sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _identity(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}"


def _lstat(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise FixtureTopologyRefused("topology_entry_unavailable") from exc


def _assert_kind_and_links(info: os.stat_result, *, kind: str, link_count: int | None) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise FixtureTopologyRefused("topology_symlink")
    expected_kind = stat.S_ISDIR if kind == "directory" else stat.S_ISREG
    if not expected_kind(info.st_mode):
        raise FixtureTopologyRefused("topology_kind_mismatch")
    if link_count is not None and info.st_nlink != link_count:
        raise FixtureTopologyRefused("topology_link_count_mismatch")


def _assert_closed_world_entries(entries: Iterable[str], *, expected: frozenset[str]) -> None:
    """Require the fixture directory to contain exactly its canonical entries."""

    actual = frozenset(entries)
    if actual - expected:
        raise FixtureTopologyRefused("topology_unexpected_entry")
    if actual != expected:
        raise FixtureTopologyRefused("topology_entry_set_mismatch")


def _descriptor_api_supported() -> bool:
    """Return whether the required POSIX descriptor operations are available."""

    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    )


@dataclass(frozen=True)
class TopologyRole:
    """An exact role record from a canonical fixture topology manifest."""

    path: str
    parent: str
    kind: str
    identity: str
    link_count: int


@dataclass(frozen=True)
class FixtureTopologyManifest:
    """Parsed strict manifest for one disposable fixture topology."""

    anchor_identity: str
    roles: Mapping[str, TopologyRole]

    @property
    def digest(self) -> str:
        return _sha256_digest(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "anchor": {"identity": self.anchor_identity, "path": "."},
                "roles": {
                    name: {
                        "identity": role.identity,
                        "kind": role.kind,
                        "link_count": role.link_count,
                        "parent": role.parent,
                        "path": role.path,
                    }
                    for name, role in self.roles.items()
                },
                "schema_version": TOPOLOGY_SCHEMA_VERSION,
            }
        )


def capture_canonical_manifest(fixture_root: str | Path) -> bytes:
    """Capture a known-good synthetic topology without creating or changing it."""

    root = Path(fixture_root)
    anchor_info = _lstat(root)
    _assert_kind_and_links(anchor_info, kind="directory", link_count=anchor_info.st_nlink)
    try:
        _assert_closed_world_entries((entry.name for entry in root.iterdir()), expected=_EXPECTED_ROOT_ENTRIES)
        _assert_closed_world_entries(
            (entry.name for entry in (root / "audit").iterdir()),
            expected=_EXPECTED_AUDIT_ENTRIES,
        )
    except OSError as exc:
        raise FixtureTopologyRefused("topology_entry_unavailable") from exc
    roles: dict[str, dict[str, object]] = {}
    for name, (relative_path, parent, kind, link_count) in _ROLE_SHAPES.items():
        entry = root / relative_path
        info = _lstat(entry)
        _assert_kind_and_links(info, kind=kind, link_count=link_count)
        parent_path = root if parent == "anchor" else root / _ROLE_SHAPES[parent][0]
        parent_info = _lstat(parent_path)
        _assert_kind_and_links(
            parent_info,
            kind="directory",
            link_count=_ROLE_SHAPES[parent][3] if parent != "anchor" else parent_info.st_nlink,
        )
        roles[name] = {
            "path": relative_path,
            "parent": parent,
            "kind": kind,
            "identity": _identity(info),
            "link_count": info.st_nlink if link_count is None else link_count,
        }
    return _canonical_json(
        {
            "anchor": {"identity": _identity(anchor_info), "path": "."},
            "roles": roles,
            "schema_version": TOPOLOGY_SCHEMA_VERSION,
        }
    )


def parse_canonical_manifest(payload: object) -> FixtureTopologyManifest:
    """Parse only canonical JSON with the complete v1 role schema."""

    if not isinstance(payload, bytes):
        raise FixtureTopologyRefused("manifest_bytes_required")
    try:
        decoded = payload.decode("ascii")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureTopologyRefused("manifest_not_json") from exc
    if _canonical_json(value) != payload:
        raise FixtureTopologyRefused("manifest_not_canonical")
    if not isinstance(value, dict) or set(value) != {"schema_version", "anchor", "roles"}:
        raise FixtureTopologyRefused("manifest_fields_invalid")
    if value["schema_version"] != TOPOLOGY_SCHEMA_VERSION:
        raise FixtureTopologyRefused("manifest_schema_invalid")
    anchor = value["anchor"]
    if not isinstance(anchor, dict) or set(anchor) != {"path", "identity"}:
        raise FixtureTopologyRefused("manifest_anchor_invalid")
    if anchor["path"] != "." or not isinstance(anchor["identity"], str) or not _IDENTITY_RE.fullmatch(anchor["identity"]):
        raise FixtureTopologyRefused("manifest_anchor_invalid")
    role_values = value["roles"]
    if not isinstance(role_values, dict) or set(role_values) != set(_ROLE_NAMES):
        raise FixtureTopologyRefused("manifest_roles_invalid")
    roles: dict[str, TopologyRole] = {}
    identities = {anchor["identity"]}
    for name in _ROLE_NAMES:
        role = role_values[name]
        expected_path, expected_parent, expected_kind, expected_links = _ROLE_SHAPES[name]
        if not isinstance(role, dict) or set(role) != {"path", "parent", "kind", "identity", "link_count"}:
            raise FixtureTopologyRefused("manifest_role_fields_invalid")
        if (
            role["path"] != expected_path
            or role["parent"] != expected_parent
            or role["kind"] != expected_kind
            or type(role["link_count"]) is not int
            or role["link_count"] < 1
            or (expected_links is not None and role["link_count"] != expected_links)
            or not isinstance(role["identity"], str)
            or not _IDENTITY_RE.fullmatch(role["identity"])
        ):
            raise FixtureTopologyRefused("manifest_role_invalid")
        if role["identity"] in identities:
            raise FixtureTopologyRefused("manifest_identity_alias")
        identities.add(role["identity"])
        roles[name] = TopologyRole(
            path=role["path"],
            parent=role["parent"],
            kind=role["kind"],
            identity=role["identity"],
            link_count=role["link_count"],
        )
    return FixtureTopologyManifest(anchor_identity=anchor["identity"], roles=roles)


DescriptorOpener = Callable[[str, int, int], int]


def _open_readonly(name: str, flags: int, parent_fd: int) -> int:
    if parent_fd < 0:
        return os.open(name, flags)
    return os.open(name, flags, dir_fd=parent_fd)


class FixtureTopologyVerifier:
    """Read-only, descriptor-bound verifier for the four synthetic roles."""

    def __init__(self, fixture_root: str | Path) -> None:
        self._fixture_root = Path(fixture_root)

    def verify(
        self,
        payload: object,
        *,
        descriptor_opener: DescriptorOpener = _open_readonly,
    ) -> FixtureTopologyManifest:
        """Reject topology changes before any hypothetical writer can run."""

        if not _descriptor_api_supported():
            raise FixtureTopologyRefused("topology_descriptor_api_unsupported")
        manifest = parse_canonical_manifest(payload)
        anchor_info = _lstat(self._fixture_root)
        _assert_kind_and_links(anchor_info, kind="directory", link_count=anchor_info.st_nlink)
        if _identity(anchor_info) != manifest.anchor_identity:
            raise FixtureTopologyRefused("anchor_identity_mismatch")
        anchor_fd = -1
        audit_fd = -1
        opened: list[int] = []
        try:
            anchor_fd = self._open_and_verify(
                name=str(self._fixture_root),
                parent_fd=-1,
                role=TopologyRole(
                    path=".", parent="", kind="directory", identity=manifest.anchor_identity, link_count=anchor_info.st_nlink
                ),
                descriptor_opener=descriptor_opener,
            )
            _assert_closed_world_entries(os.listdir(anchor_fd), expected=_EXPECTED_ROOT_ENTRIES)
            root_role = manifest.roles["root"]
            root_fd = self._open_and_verify(
                name=root_role.path,
                parent_fd=anchor_fd,
                role=root_role,
                descriptor_opener=descriptor_opener,
            )
            opened.append(root_fd)
            audit_role = manifest.roles["audit"]
            audit_fd = self._open_and_verify(
                name=audit_role.path,
                parent_fd=anchor_fd,
                role=audit_role,
                descriptor_opener=descriptor_opener,
            )
            _assert_closed_world_entries(os.listdir(audit_fd), expected=_EXPECTED_AUDIT_ENTRIES)
            lock_role = manifest.roles["lock"]
            lock_fd = self._open_and_verify(
                name=lock_role.path.rsplit("/", 1)[1],
                parent_fd=audit_fd,
                role=lock_role,
                descriptor_opener=descriptor_opener,
            )
            opened.append(lock_fd)
            boundary_role = manifest.roles["boundary"]
            boundary_fd = self._open_and_verify(
                name=boundary_role.path,
                parent_fd=anchor_fd,
                role=boundary_role,
                descriptor_opener=descriptor_opener,
            )
            opened.append(boundary_fd)
            actual_identities = {
                _identity(os.fstat(anchor_fd)),
                _identity(os.fstat(root_fd)),
                _identity(os.fstat(audit_fd)),
                _identity(os.fstat(lock_fd)),
                _identity(os.fstat(boundary_fd)),
            }
            if len(actual_identities) != 5:
                raise FixtureTopologyRefused("topology_identity_alias")
            return manifest
        finally:
            for descriptor in opened:
                os.close(descriptor)
            if audit_fd >= 0:
                os.close(audit_fd)
            if anchor_fd >= 0:
                os.close(anchor_fd)

    def _open_and_verify(
        self,
        *,
        name: str,
        parent_fd: int,
        role: TopologyRole,
        descriptor_opener: DescriptorOpener,
    ) -> int:
        try:
            if parent_fd >= 0:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            else:
                before = os.lstat(name)
        except OSError as exc:
            raise FixtureTopologyRefused("topology_entry_unavailable") from exc
        _assert_kind_and_links(before, kind=role.kind, link_count=role.link_count)
        if _identity(before) != role.identity:
            raise FixtureTopologyRefused("topology_identity_mismatch")
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if role.kind == "directory":
            flags |= os.O_DIRECTORY
        try:
            descriptor = descriptor_opener(name, flags, parent_fd)
        except OSError as exc:
            raise FixtureTopologyRefused("topology_descriptor_unavailable") from exc
        try:
            after = os.fstat(descriptor)
            _assert_kind_and_links(after, kind=role.kind, link_count=role.link_count)
            if _identity(after) != role.identity:
                raise FixtureTopologyRefused("topology_descriptor_race")
            return descriptor
        except Exception:
            os.close(descriptor)
            raise


@dataclass(frozen=True)
class FixtureAuthorityBinding:
    """Every authorization-relevant field bound to one fake opaque handle."""

    proposal_fingerprint: str
    audience: str
    operation: str
    topology_digest: str
    policy_digest: str
    preflight_digest: str
    expires_at: str
    nonce: str
    revocation_epoch: int


class _FixtureOpaqueHandle:
    """Uninspectable object identity used only by the in-memory fake authority."""

    __slots__ = ()


@dataclass
class _FixtureGrant:
    proposal_id: str
    binding: FixtureAuthorityBinding
    owner_session_binding: str
    consumed: bool = False


class FakeOpaqueHandleTrustedOwnerAuthority:
    """Test-only TrustedOwnerAuthority adapter with no production key material.

    Handles are private object identities retained solely in this instance.  A
    caller cannot serialize, forge, or interpret them, and every verifier
    failure returns ``False`` without permitting a hypothetical writer.
    """

    def __init__(
        self,
        *,
        owner_session_binding: str = "fixture-owner-session",
        audience: str = FIXTURE_AUDIENCE,
        policy_digest: str = FIXTURE_POLICY_DIGEST,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _is_opaque(owner_session_binding) or not _is_opaque(audience) or not _is_digest(policy_digest):
            raise FixtureAuthorityRefused("authority_configuration_invalid")
        self._owner_session_binding = owner_session_binding
        self._audience = audience
        self._policy_digest = policy_digest
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._grants: dict[_FixtureOpaqueHandle, _FixtureGrant] = {}
        self._seen_nonces: set[str] = set()
        self._revocation_epoch = 0

    @property
    def revocation_epoch(self) -> int:
        return self._revocation_epoch

    def current_owner_session_binding(self) -> str:
        return self._owner_session_binding

    def revoke_all(self) -> int:
        """Advance the fixture revocation epoch; old handles fail closed."""

        self._revocation_epoch += 1
        return self._revocation_epoch

    def issue_confirmation(
        self,
        *,
        proposal_id: str,
        binding: FixtureAuthorityBinding,
    ) -> OwnerConfirmation:
        """Issue a one-time opaque proof after strict fixture-only checks."""

        self._assert_issue_request(proposal_id=proposal_id, binding=binding)
        handle = _FixtureOpaqueHandle()
        self._seen_nonces.add(binding.nonce)
        self._grants[handle] = _FixtureGrant(
            proposal_id=proposal_id,
            binding=binding,
            owner_session_binding=self._owner_session_binding,
        )
        return OwnerConfirmation(proposal_id=proposal_id, proof=handle)

    def verify_fixture_confirmation(
        self,
        *,
        confirmation: object,
        proposal_id: object,
        binding: object,
        owner_session_binding: object,
    ) -> bool:
        """Verify every explicit fixture binding and consume a valid handle once."""

        if not isinstance(confirmation, OwnerConfirmation) or not isinstance(confirmation.proof, _FixtureOpaqueHandle):
            return False
        if not isinstance(proposal_id, str) or not isinstance(binding, FixtureAuthorityBinding):
            return False
        if owner_session_binding != self._owner_session_binding or not self._binding_is_valid(binding):
            return False
        grant = self._grants.get(confirmation.proof)
        if grant is None or grant.consumed:
            return False
        if (
            confirmation.proposal_id != proposal_id
            or grant.proposal_id != proposal_id
            or grant.binding != binding
            or grant.owner_session_binding != owner_session_binding
            or binding.revocation_epoch != self._revocation_epoch
            or self._is_expired(binding.expires_at)
        ):
            return False
        grant.consumed = True
        return True

    def verify_owner_confirmation(
        self,
        *,
        confirmation: OwnerConfirmation,
        proposal_id: str,
        proposal_fingerprint: str,
        server_instance_id: str,
        owner_session_binding: str,
    ) -> bool:
        """Implement the production protocol without accepting any secret proof."""

        if not isinstance(confirmation, OwnerConfirmation) or not isinstance(confirmation.proof, _FixtureOpaqueHandle):
            return False
        if not all(
            isinstance(value, str)
            for value in (proposal_id, proposal_fingerprint, server_instance_id, owner_session_binding)
        ):
            return False
        grant = self._grants.get(confirmation.proof)
        if grant is None:
            return False
        binding = grant.binding
        if binding.proposal_fingerprint != proposal_fingerprint or binding.audience != server_instance_id:
            return False
        return self.verify_fixture_confirmation(
            confirmation=confirmation,
            proposal_id=proposal_id,
            binding=binding,
            owner_session_binding=owner_session_binding,
        )

    def _assert_issue_request(self, *, proposal_id: object, binding: object) -> None:
        if not isinstance(proposal_id, str) or not _is_opaque(proposal_id):
            raise FixtureAuthorityRefused("proposal_id_invalid")
        if not isinstance(binding, FixtureAuthorityBinding) or not self._binding_is_valid(binding):
            raise FixtureAuthorityRefused("binding_invalid")
        if binding.revocation_epoch != self._revocation_epoch:
            raise FixtureAuthorityRefused("revocation_epoch_invalid")
        if binding.nonce in self._seen_nonces:
            raise FixtureAuthorityRefused("nonce_replayed")
        if self._is_expired(binding.expires_at):
            raise FixtureAuthorityRefused("binding_expired")

    def _binding_is_valid(self, binding: FixtureAuthorityBinding) -> bool:
        return (
            _is_digest(binding.proposal_fingerprint)
            and binding.audience == self._audience
            and binding.operation == "create_absent"
            and _is_digest(binding.topology_digest)
            and binding.policy_digest == self._policy_digest
            and _is_digest(binding.preflight_digest)
            and _is_utc_timestamp(binding.expires_at)
            and _is_opaque(binding.nonce)
            and type(binding.revocation_epoch) is int
            and binding.revocation_epoch >= 0
            and binding.preflight_digest
            == compute_fixture_preflight_digest(
                operation=binding.operation,
                topology_digest=binding.topology_digest,
                policy_digest=binding.policy_digest,
            )
        )

    def _is_expired(self, value: str) -> bool:
        try:
            expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            now = self._clock()
            if now.tzinfo is None:
                return True
            return now.astimezone(timezone.utc) >= expires_at
        except (AttributeError, TypeError, ValueError):
            return True


def compute_fixture_preflight_digest(*, operation: str, topology_digest: str, policy_digest: str) -> str:
    """Return the canonical test-only digest that binds topology and policy."""

    return _sha256_digest(
        _canonical_json(
            {
                "operation": operation,
                "policy_digest": policy_digest,
                "topology_digest": topology_digest,
            }
        )
    )


@dataclass(frozen=True)
class FixtureDenyDecision:
    """A validation result that deliberately cannot represent an apply outcome."""

    reason: str
    write_sink_calls: int


class FixtureOnlyDenyGate:
    """Test-only coordinator that always denies before any write-sink invocation."""

    def __init__(
        self,
        *,
        topology_verifier: FixtureTopologyVerifier,
        authority: FakeOpaqueHandleTrustedOwnerAuthority,
        write_sink: object,
    ) -> None:
        self._topology_verifier = topology_verifier
        self._authority = authority
        self._write_sink = write_sink

    def evaluate(
        self,
        *,
        manifest: object,
        confirmation: object,
        proposal_id: object,
        binding: object,
    ) -> FixtureDenyDecision:
        """Validate synthetic inputs and unconditionally stop at the deny boundary."""

        try:
            verified_topology = self._topology_verifier.verify(manifest)
        except FixtureTopologyRefused:
            return FixtureDenyDecision("topology_refused", 0)
        if not isinstance(binding, FixtureAuthorityBinding) or binding.topology_digest != verified_topology.digest:
            return FixtureDenyDecision("topology_binding_refused", 0)
        verified = self._authority.verify_fixture_confirmation(
            confirmation=confirmation,
            proposal_id=proposal_id,
            binding=binding,
            owner_session_binding=self._authority.current_owner_session_binding(),
        )
        if not verified:
            return FixtureDenyDecision("authority_refused", 0)
        return FixtureDenyDecision("fixture_only_denied", 0)


def _is_opaque(value: object) -> bool:
    return isinstance(value, str) and bool(_OPAQUE_RE.fullmatch(value))


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.fullmatch(value))


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo == timezone.utc
