"""Linux-only disposable evidence support for the disconnected control plane.

This test support is never a package adapter. It operates only on a
caller-created ``TemporaryDirectory`` and proves the shape of a future Linux
qualification without discovering a vault, loading configuration, registering
MCP, issuing an authority, or opening a source note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import re
import stat
import sys
import threading
from typing import Callable

from cognitiveos.control_plane import (
    AllowedRoot,
    AuthorityRuntime,
    CapabilityConsumptionDecision,
    CapabilityVerificationStatus,
    ConfiguredVaultRootProvenance,
    DurableReplayLedger,
    LinuxDescriptorEvidence,
    LinuxObjectIdentity,
    OWNER_CAPABILITY_SCHEMA_VERSION,
    OwnerCapabilityVerifier,
    ReplayClaim,
    ReplayClaimResult,
    TrustedOwnerAuthority,
    TrustedOwnerCapability,
    CONTROL_PLANE_SCHEMA_VERSION,
    provenance_digest,
)


DECLARED_KERNEL_MINIMUM = (6, 1)
DECLARED_MACHINE = "x86_64"
DECLARED_PYTHON = (3, 12)
DECLARED_FILESYSTEM = "ext4"
REPLAY_SCHEMA_VERSION = "qualified-linux-replay-fixture/v1"
_SAFE_COMPONENT = re.compile(r"[^/\\\x00]+\Z")


class QualifiedLinuxFixtureRefusal(RuntimeError):
    """A test-only signal that Linux evidence cannot be safely constructed."""


@dataclass(frozen=True)
class DeclaredLinuxTuple:
    """The only tuple this fixture may count as Linux execution evidence."""

    kernel_minimum: tuple[int, int] = DECLARED_KERNEL_MINIMUM
    machine: str = DECLARED_MACHINE
    python: tuple[int, int] = DECLARED_PYTHON
    filesystem: str = DECLARED_FILESYSTEM

    def require_current_host(self, temporary_root: Path) -> str:
        """Return the mount namespace only for the declared disposable tuple."""

        if sys.platform != "linux" or platform.system() != "Linux":
            raise QualifiedLinuxFixtureRefusal("host is not Linux")
        if platform.machine() != self.machine:
            raise QualifiedLinuxFixtureRefusal(f"machine is not {self.machine}")
        if sys.version_info[:2] != self.python:
            raise QualifiedLinuxFixtureRefusal(
                f"CPython is not {self.python[0]}.{self.python[1]}"
            )
        if os.geteuid() == 0:
            raise QualifiedLinuxFixtureRefusal("root account is not a qualified owner account")
        release = _kernel_release_tuple(platform.release())
        if release < self.kernel_minimum:
            raise QualifiedLinuxFixtureRefusal(
                f"kernel {platform.release()} is older than {self.kernel_minimum[0]}.{self.kernel_minimum[1]}"
            )
        if _filesystem_type_for(temporary_root) != self.filesystem:
            raise QualifiedLinuxFixtureRefusal(
                f"temporary fixture filesystem is not local {self.filesystem}"
            )
        namespace = _mount_namespace_id()
        directory_mode = stat.S_IMODE(os.stat(temporary_root, follow_symlinks=False).st_mode)
        if directory_mode & 0o077:
            raise QualifiedLinuxFixtureRefusal("temporary fixture root is not owner-only")
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise QualifiedLinuxFixtureRefusal("kernel descriptor flags are unavailable")
        return namespace


def require_declared_linux_tuple(test_case: object, temporary_root: Path) -> str:
    """Skip a test rather than inventing a result on an unqualified host."""

    try:
        return DeclaredLinuxTuple().require_current_host(temporary_root)
    except QualifiedLinuxFixtureRefusal as error:
        skip = getattr(test_case, "skipTest")
        skip(f"qualified Linux tuple unavailable: {error}")
        raise AssertionError("unreachable after unittest.skipTest")


def _kernel_release_tuple(release: str) -> tuple[int, int]:
    match = re.match(r"(\d+)\.(\d+)", release)
    if match is None:
        raise QualifiedLinuxFixtureRefusal("kernel release is not parseable")
    return int(match.group(1)), int(match.group(2))


def _mount_namespace_id() -> str:
    try:
        raw = os.readlink("/proc/self/ns/mnt")
    except OSError as error:
        raise QualifiedLinuxFixtureRefusal("mount namespace is unavailable") from error
    if not raw:
        raise QualifiedLinuxFixtureRefusal("mount namespace is empty")
    return "linux-mnt-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _unescape_mountinfo(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _filesystem_type_for(path: Path) -> str | None:
    """Read only the disposable fixture's Linux mount metadata."""

    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    requested = os.path.abspath(os.fspath(path))
    candidates: list[tuple[int, str]] = []
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        post_fields = after.split()
        if len(fields) < 5 or not post_fields:
            continue
        mount_point = _unescape_mountinfo(fields[4])
        if requested == mount_point or requested.startswith(mount_point.rstrip("/") + "/"):
            candidates.append((len(mount_point), post_fields[0]))
    return max(candidates, default=(0, None))[1]


def _identity_from_stat(value: os.stat_result) -> LinuxObjectIdentity:
    return LinuxObjectIdentity(device=value.st_dev, inode=value.st_ino)


def _validate_component(component: str) -> None:
    if component in {"", ".", ".."} or not _SAFE_COMPONENT.fullmatch(component):
        raise QualifiedLinuxFixtureRefusal("noncanonical path component")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _same_named_entry(directory_fd: int, name: str, descriptor_fd: int, *, directory: bool) -> None:
    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    opened = os.fstat(descriptor_fd)
    if named.st_dev != opened.st_dev or named.st_ino != opened.st_ino:
        raise QualifiedLinuxFixtureRefusal("descriptor path identity changed")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(opened.st_mode):
        raise QualifiedLinuxFixtureRefusal("descriptor is not the required regular type")
    if not directory and opened.st_nlink != 1:
        raise QualifiedLinuxFixtureRefusal("target descriptor has an aliasing hard link")


def _open_absolute_directory_nofollow(path: Path) -> int:
    """Walk every absolute component from ``/`` using no-follow descriptors."""

    rendered = os.fspath(path)
    if not rendered.startswith("/") or rendered.startswith("//"):
        raise QualifiedLinuxFixtureRefusal("root is not a canonical absolute path")
    current_fd = os.open("/", _directory_flags())
    try:
        for component in rendered.split("/")[1:]:
            _validate_component(component)
            next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            try:
                _same_named_entry(current_fd, component, next_fd, directory=True)
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


class DisposableLinuxDescriptorProbe:
    """Construct actual descriptor evidence below one disposable directory."""

    def __init__(self, root_path: Path, *, namespace_id: str) -> None:
        self._root_path = Path(os.fspath(root_path))
        self._namespace_id = namespace_id

    def bootstrap_provenance(self) -> ConfiguredVaultRootProvenance:
        root_fd = _open_absolute_directory_nofollow(self._root_path)
        try:
            root_identity = _identity_from_stat(os.fstat(root_fd))
            notes_fd = os.open("Notes", _directory_flags(), dir_fd=root_fd)
            try:
                _same_named_entry(root_fd, "Notes", notes_fd, directory=True)
                notes_identity = _identity_from_stat(os.fstat(notes_fd))
            finally:
                os.close(notes_fd)
        finally:
            os.close(root_fd)
        return ConfiguredVaultRootProvenance(
            schema_version=CONTROL_PLANE_SCHEMA_VERSION,
            configuration_id="linux-fixture-bootstrap-0001",
            configuration_generation=1,
            canonical_root_path=os.fspath(self._root_path),
            namespace_id=self._namespace_id,
            root_identity=root_identity,
            allowed_roots=(
                AllowedRoot(
                    root_id="linux-fixture-notes-0001",
                    components=("Notes",),
                    identity=notes_identity,
                ),
            ),
        )

    def build_target_evidence(
        self,
        provenance: ConfiguredVaultRootProvenance,
        target_components: tuple[str, ...],
        *,
        after_open_component: Callable[[], None] | None = None,
    ) -> LinuxDescriptorEvidence:
        if not target_components or target_components[:1] != ("Notes",):
            raise QualifiedLinuxFixtureRefusal("fixture target escapes the Notes prefix")
        for component in target_components:
            _validate_component(component)

        root_fd = _open_absolute_directory_nofollow(self._root_path)
        current_fd = root_fd
        allowed_identity: LinuxObjectIdentity | None = None
        try:
            for index, component in enumerate(target_components):
                is_directory = index < len(target_components) - 1
                flags = _directory_flags() if is_directory else _file_flags()
                next_fd = os.open(component, flags, dir_fd=current_fd)
                try:
                    if index == 0 and after_open_component is not None:
                        after_open_component()
                    _same_named_entry(current_fd, component, next_fd, directory=is_directory)
                    if index == 0:
                        allowed_identity = _identity_from_stat(os.fstat(next_fd))
                except Exception:
                    os.close(next_fd)
                    raise
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
            if allowed_identity is None:
                raise QualifiedLinuxFixtureRefusal("allowed-root descriptor was not observed")
            return LinuxDescriptorEvidence(
                schema_version="linux-descriptor-evidence/v1",
                platform_supported=True,
                namespace_id=self._namespace_id,
                requested_root_path=os.fspath(self._root_path),
                canonical_root_path=os.fspath(self._root_path),
                root_identity=provenance.root_identity,
                descriptor_race_detected=False,
                allowed_root_id="linux-fixture-notes-0001",
                allowed_root_identity=allowed_identity,
                target_components=target_components,
                canonical_target_path=os.fspath(self._root_path) + "/" + "/".join(target_components),
            )
        finally:
            os.close(current_fd)
            if current_fd != root_fd:
                os.close(root_fd)


def _state_digest(claims: dict[str, str]) -> str:
    public = {"claims": claims, "schema_version": REPLAY_SCHEMA_VERSION}
    payload = json.dumps(public, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class DisposableOwnerOnlyReplayLedger(DurableReplayLedger):
    """Cross-process replay fixture with owner-only files and fail-closed I/O.

    It is limited to a supplied temporary directory. It has no secrets, no
    repair path, no retained proof, no source-file access, and no production
    configuration. The fixture is evidence for the protocol only.
    """

    def __init__(
        self,
        state_path: Path,
        *,
        after_lock_acquired: Callable[[], None] | None = None,
    ) -> None:
        self._state_path = Path(os.fspath(state_path))
        self._directory = self._state_path.parent
        self._state_name = self._state_path.name
        self._lock_name = self._state_name + ".lock"
        self._temporary_prefix = self._state_name + ".tmp."
        self._after_lock_acquired = after_lock_acquired

    @property
    def lock_path(self) -> Path:
        """Expose the disposable lock path solely for controlled race tests."""

        return self._directory / self._lock_name

    def consume_once(self, claim: ReplayClaim) -> ReplayClaimResult:
        if sys.platform != "linux":
            return ReplayClaimResult.UNAVAILABLE
        directory_fd: int | None = None
        lock_fd: int | None = None
        try:
            directory_fd = self._open_owner_directory()
            if self._has_abandoned_temporary(directory_fd):
                return ReplayClaimResult.UNAVAILABLE
            lock_fd = self._open_locked_file(directory_fd)
            import fcntl

            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self._after_lock_acquired is not None:
                self._after_lock_acquired()
            if not _same_path_entry(directory_fd, self._lock_name, lock_fd):
                return ReplayClaimResult.UNAVAILABLE
            claims = self._read_claims(directory_fd)
            previous = claims.get(claim.capability_id)
            if previous is not None:
                return (
                    ReplayClaimResult.REPLAYED
                    if previous == claim.capability_fingerprint
                    else ReplayClaimResult.COLLISION
                )
            claims[claim.capability_id] = claim.capability_fingerprint
            self._write_claims(directory_fd, claims, lock_fd)
            return ReplayClaimResult.CONSUMED
        except (OSError, ValueError, TypeError, json.JSONDecodeError, QualifiedLinuxFixtureRefusal):
            return ReplayClaimResult.UNAVAILABLE
        finally:
            if lock_fd is not None:
                try:
                    import fcntl

                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(lock_fd)
            if directory_fd is not None:
                os.close(directory_fd)

    def _open_owner_directory(self) -> int:
        fd = _open_absolute_directory_nofollow(self._directory)
        details = os.fstat(fd)
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o077:
            os.close(fd)
            raise QualifiedLinuxFixtureRefusal("replay directory is not owner-only")
        return fd

    def _open_locked_file(self, directory_fd: int) -> int:
        try:
            fd = os.open(
                self._lock_name,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(fd, 0o600)
        except FileExistsError:
            fd = os.open(
                self._lock_name,
                os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
        try:
            _require_owner_regular(fd)
            if not _same_path_entry(directory_fd, self._lock_name, fd):
                raise QualifiedLinuxFixtureRefusal("lock path changed before acquisition")
            return fd
        except Exception:
            os.close(fd)
            raise

    def _has_abandoned_temporary(self, directory_fd: int) -> bool:
        return any(name.startswith(self._temporary_prefix) for name in os.listdir(directory_fd))

    def _read_claims(self, directory_fd: int) -> dict[str, str]:
        try:
            fd = os.open(self._state_name, _file_flags(), dir_fd=directory_fd)
        except FileNotFoundError:
            return {}
        try:
            _require_owner_regular(fd)
            if not _same_path_entry(directory_fd, self._state_name, fd):
                raise QualifiedLinuxFixtureRefusal("state path changed while opening")
            chunks: list[bytes] = []
            while chunk := os.read(fd, 65_536):
                chunks.append(chunk)
            document = json.loads(b"".join(chunks).decode("utf-8"))
        finally:
            os.close(fd)
        if not isinstance(document, dict) or set(document) != {"schema_version", "claims", "digest"}:
            raise QualifiedLinuxFixtureRefusal("replay state schema is malformed")
        claims = document["claims"]
        if (
            document["schema_version"] != REPLAY_SCHEMA_VERSION
            or not isinstance(claims, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in claims.items())
            or document["digest"] != _state_digest(claims)
        ):
            raise QualifiedLinuxFixtureRefusal("replay state integrity is invalid")
        return claims

    def _write_claims(self, directory_fd: int, claims: dict[str, str], lock_fd: int) -> None:
        payload = json.dumps(
            {
                "schema_version": REPLAY_SCHEMA_VERSION,
                "claims": claims,
                "digest": _state_digest(claims),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        temporary_name = f"{self._temporary_prefix}{os.getpid()}.{threading.get_ident()}"
        temporary_fd = os.open(
            temporary_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.fchmod(temporary_fd, 0o600)
            written = 0
            while written < len(payload):
                written += os.write(temporary_fd, payload[written:])
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)
        if not _same_path_entry(directory_fd, self._lock_name, lock_fd):
            raise QualifiedLinuxFixtureRefusal("lock path changed before commit")
        os.replace(temporary_name, self._state_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)


def _require_owner_regular(fd: int) -> None:
    details = os.fstat(fd)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
        or details.st_nlink != 1
    ):
        raise QualifiedLinuxFixtureRefusal("replay file is not an owner-only regular file")


def _same_path_entry(directory_fd: int, name: str, fd: int) -> bool:
    try:
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        return False
    opened = os.fstat(fd)
    return named.st_dev == opened.st_dev and named.st_ino == opened.st_ino


class _StaticClock:
    def wall_now(self) -> datetime:
        return datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

    def monotonic_ns(self) -> int:
        return 1_000


class _FixtureVerifier(OwnerCapabilityVerifier):
    """Synthetic verifier only; it is not an owner authentication mechanism."""

    def verify_capability(
        self,
        *,
        capability: TrustedOwnerCapability,
        runtime: AuthorityRuntime,
    ) -> CapabilityVerificationStatus:
        return CapabilityVerificationStatus.VALID


def fixture_runtime(
    *,
    server_boot_id: str = "linux-fixture-boot-0001",
    owner_session_id: str = "linux-fixture-session-0001",
) -> AuthorityRuntime:
    """Create fixed, non-secret fields for isolated authority tests."""

    provenance = ConfiguredVaultRootProvenance(
        schema_version=CONTROL_PLANE_SCHEMA_VERSION,
        configuration_id="linux-replay-fixture-0001",
        configuration_generation=1,
        canonical_root_path="/synthetic/linux-replay",
        namespace_id="linux-fixture-namespace-0001",
        root_identity=LinuxObjectIdentity(device=1, inode=2),
        allowed_roots=(
            AllowedRoot(
                root_id="linux-fixture-replay-root-0001",
                components=("Notes",),
                identity=LinuxObjectIdentity(device=1, inode=3),
            ),
        ),
    )
    return AuthorityRuntime(
        authority_id="linux-fixture-authority-0001",
        owner_session_id=owner_session_id,
        server_instance_id="linux-fixture-server-0001",
        server_boot_id=server_boot_id,
        root_provenance_digest=provenance_digest(provenance),
        key_epoch=1,
        revocation_epoch=1,
    )


def fixture_capability(runtime: AuthorityRuntime) -> TrustedOwnerCapability:
    """Create a fixed, opaque synthetic capability with no credential material."""

    return TrustedOwnerCapability(
        schema_version=OWNER_CAPABILITY_SCHEMA_VERSION,
        capability_id="linux-fixture-capability-0001",
        authority_id=runtime.authority_id,
        owner_session_id=runtime.owner_session_id,
        server_instance_id=runtime.server_instance_id,
        server_boot_id=runtime.server_boot_id,
        root_provenance_digest=runtime.root_provenance_digest,
        key_epoch=runtime.key_epoch,
        revocation_epoch=runtime.revocation_epoch,
        issued_at=datetime(2026, 7, 22, 11, 59, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 22, 12, 5, tzinfo=timezone.utc),
        monotonic_issued_ns=999,
        monotonic_deadline_ns=2_000,
        proof_digest="sha256:" + "4" * 64,
        proof=object(),
    )


def authority_for_fixture(
    state_path: Path,
    *,
    runtime: AuthorityRuntime | None = None,
    after_lock_acquired: Callable[[], None] | None = None,
) -> tuple[TrustedOwnerAuthority, AuthorityRuntime]:
    """Build a disconnected authority over the temporary replay fixture."""

    selected_runtime = runtime or fixture_runtime()
    return (
        TrustedOwnerAuthority(
            runtime=selected_runtime,
            verifier=_FixtureVerifier(),
            replay_ledger=DisposableOwnerOnlyReplayLedger(
                state_path,
                after_lock_acquired=after_lock_acquired,
            ),
            clock=_StaticClock(),
        ),
        selected_runtime,
    )


def consume_in_separate_process(
    state_path: str,
    start_event: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue[str],
) -> None:
    """Spawn-safe worker proving process rather than thread replay semantics."""

    try:
        if not start_event.wait(timeout=10):
            result_queue.put("worker_start_timeout")
            return
        authority, runtime = authority_for_fixture(Path(state_path))
        result_queue.put(authority.consume(fixture_capability(runtime)).reason.value)
    except BaseException as error:  # pragma: no cover - returned to parent assertion
        result_queue.put(f"worker_error:{type(error).__name__}")
