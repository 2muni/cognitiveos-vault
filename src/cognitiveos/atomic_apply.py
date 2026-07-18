"""Dormant, server-owned, atomic-create writeback boundary.

This module is intentionally absent from the MCP server.  A future trusted
local approval UI may use it only after supplying an authenticated owner
authority and a server-owned audit key.  It refuses existing-file replacement:
POSIX ``rename``/``replace`` cannot conditionally replace the exact inode that
was reviewed, and this module has no verified whole-writer coordinator.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import base64
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Any, Callable, Iterator

try:  # v0.8 deliberately remains read-only where advisory process locks lack support.
    import fcntl
except ImportError:  # pragma: no cover - exercised by platform capability checks.
    fcntl = None  # type: ignore[assignment]

from .approval import (
    MAX_APPROVAL_LIFETIME_SECONDS,
    OwnerConfirmation,
    TrustedOwnerAuthority,
    sha256_checksum,
)
from .writeback_proposal import (
    AUDIT_SCHEMA_VERSION,
    POLICY_VERSION,
    PROPOSAL_SCHEMA_VERSION,
    ProposalValidationError,
    canonical_json,
    canonical_relative_markdown_path,
    compute_proposal_fingerprint,
    render_unified_byte_diff_v1,
    validate_proposal,
)


class ApplyOutcome(str, Enum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    REFUSED = "refused"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ApplyResult:
    """A non-sensitive result for the caller that requested its proposal."""

    outcome: ApplyOutcome
    proposal_id: str


class ApplyRefused(ValueError):
    """A non-sensitive refusal that never contains an absolute path or bytes."""


@dataclass
class _PreparedProposal:
    public: dict[str, Any]
    base_bytes: bytes
    proposed_bytes: bytes
    token_digest: bytes
    raw_token: str | None
    monotonic_deadline: float
    state: str = "proposed"
    approval_at: str | None = None


class _CreateConflict(Exception):
    """The final path appeared before atomic publication."""


class _PublishedFailure(OSError):
    """A failure after the hard link made complete bytes visible at the target."""


class _AuditJournal:
    """Owner-only HMAC chained JSONL journal serialized across processes.

    The server owns ``key`` and must retain it outside this derived directory.
    The journal's directory and every opened file are checked for identity,
    ownership, restrictive mode, regular-file type, and link count.  Advisory
    locks are not authorization for source writes; they serialize the audit
    read/verify/append/fsync transaction so a concurrent process cannot fork
    or overwrite the chain.
    """

    _APPLY_FIELDS = {
        "kind",
        "schema_version",
        "policy_version",
        "journal_scope",
        "proposal_fingerprint",
        "proposal_id_redaction",
        "operation",
        "path",
        "vault_root_id",
        "allowed_root_id",
        "issued_at",
        "expires_at",
        "approval_at",
        "outcome",
        "base_checksum",
        "expected_after_checksum",
        "observed_after_checksum",
        "changed_path_count",
        "server_instance_id",
        "error_category",
    }
    _JOURNAL_FIELDS = _APPLY_FIELDS | {"journal_sequence", "previous_entry_digest", "entry_digest"}
    _FORBIDDEN_FIELDS = {
        "proposal_id",
        "proposed_bytes_base64",
        "rendered_diff",
        "token",
        "token_digest",
        "token_binding",
        "approval_session_binding",
        "request_origin",
        "owner_session_binding",
    }

    def __init__(self, directory: Path, *, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ApplyRefused("audit_unavailable")
        self._key = key
        self._directory = directory
        self._thread_lock = threading.RLock()
        self._directory_identity = self._check_directory()
        try:
            self._directory_fd = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        try:
            if self._fd_identity(self._directory_fd) != self._directory_identity:
                raise ApplyRefused("audit_unavailable")
            self._lock_fd = self._open_regular("journal.lock", os.O_RDWR | os.O_CREAT, create=True)
        except Exception:
            os.close(self._directory_fd)
            raise

    def close(self) -> None:
        for descriptor_name in ("_lock_fd", "_directory_fd"):
            descriptor = getattr(self, descriptor_name, -1)
            if descriptor >= 0:
                os.close(descriptor)
                setattr(self, descriptor_name, -1)

    def redact_proposal_id(self, proposal_id: str) -> str:
        digest = hmac.new(self._key, proposal_id.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        return f"redacted-{digest}"

    def append(self, projection: dict[str, object]) -> dict[str, object]:
        """Verify the whole chain, append one synchronized projection, and fsync."""

        with self._exclusive_lock():
            records = self._read_verified_locked()
            return self._append_locked(records, projection)

    def records(self) -> list[dict[str, object]]:
        """Return only a fully verified journal snapshot under the process lock."""

        with self._exclusive_lock():
            return self._read_verified_locked()

    def recover_pending(
        self, observer: Callable[[dict[str, object]], tuple[str, str | None]]
    ) -> list[dict[str, object]]:
        """Finalize pending entries in one locked read/verify/append transaction.

        ``observer`` is read-only.  Recovery never opens a source file for
        writing and treats an unreadable or changed target as indeterminate.
        """

        with self._exclusive_lock():
            records = self._read_verified_locked()
            finalized = {
                item["proposal_fingerprint"]
                for item in records
                if item["outcome"] != "pending"
            }
            recovered: list[dict[str, object]] = []
            for pending in list(records):
                fingerprint = pending["proposal_fingerprint"]
                if pending["outcome"] != "pending" or fingerprint in finalized:
                    continue
                outcome, observed_checksum = observer(dict(pending))
                recovery = {key: pending[key] for key in self._APPLY_FIELDS}
                recovery.update(
                    {
                        "kind": "recovery",
                        "outcome": outcome,
                        "observed_after_checksum": observed_checksum,
                        "error_category": "recovery",
                    }
                )
                entry = self._append_locked(records, recovery)
                records.append(entry)
                recovered.append(entry)
                finalized.add(fingerprint)
            return recovered

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        if fcntl is None:
            raise ApplyRefused("audit_unavailable")
        with self._thread_lock:
            self._assert_directory_identity()
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            except OSError as exc:
                raise ApplyRefused("audit_unavailable") from exc
            try:
                self._assert_directory_identity()
                self._verify_regular_fd(self._lock_fd)
                yield
            finally:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass

    def _append_locked(self, records: list[dict[str, object]], projection: dict[str, object]) -> dict[str, object]:
        self._validate_projection(projection)
        entry = dict(projection)
        entry["journal_sequence"] = len(records) + 1
        entry["previous_entry_digest"] = records[-1]["entry_digest"] if records else None
        entry["entry_digest"] = self._entry_digest(entry)
        payload = canonical_json(entry) + b"\n"
        descriptor = self._open_regular("journal.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, create=True)
        try:
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        finally:
            os.close(descriptor)
        try:
            os.fsync(self._directory_fd)
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        return entry

    def _read_verified_locked(self) -> list[dict[str, object]]:
        try:
            descriptor = self._open_regular("journal.jsonl", os.O_RDONLY, create=False)
        except FileNotFoundError:
            return []
        try:
            chunks: list[bytes] = []
            while block := os.read(descriptor, 64 * 1024):
                chunks.append(block)
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        finally:
            os.close(descriptor)
        raw = b"".join(chunks)
        if raw and not raw.endswith(b"\n"):
            raise ApplyRefused("audit_unavailable")
        try:
            records = [json.loads(line) for line in raw.splitlines() if line]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApplyRefused("audit_unavailable") from exc
        if not all(isinstance(record, dict) for record in records):
            raise ApplyRefused("audit_unavailable")
        typed_records = [dict(record) for record in records]
        self._verify_chain(typed_records)
        return typed_records

    def _verify_chain(self, records: list[dict[str, object]]) -> None:
        previous: str | None = None
        for sequence, record in enumerate(records, start=1):
            self._validate_journal_entry(record)
            digest = record["entry_digest"]
            if (
                record["journal_sequence"] != sequence
                or record["previous_entry_digest"] != previous
                or not isinstance(digest, str)
                or not hmac.compare_digest(digest, self._entry_digest(record))
            ):
                raise ApplyRefused("audit_unavailable")
            previous = digest

    def _validate_projection(self, projection: dict[str, object]) -> None:
        if set(projection) != self._APPLY_FIELDS or self._FORBIDDEN_FIELDS & set(projection):
            raise ApplyRefused("audit_unavailable")
        if projection["kind"] not in {"apply", "recovery"}:
            raise ApplyRefused("audit_unavailable")
        if projection["schema_version"] != AUDIT_SCHEMA_VERSION or projection["policy_version"] != POLICY_VERSION:
            raise ApplyRefused("audit_unavailable")
        if projection["journal_scope"] != "derived-local-only" or projection["changed_path_count"] != 1:
            raise ApplyRefused("audit_unavailable")
        for name in (
            "proposal_fingerprint",
            "proposal_id_redaction",
            "operation",
            "path",
            "vault_root_id",
            "allowed_root_id",
            "issued_at",
            "expires_at",
            "approval_at",
            "server_instance_id",
            "outcome",
        ):
            if not isinstance(projection[name], str) or not projection[name]:
                raise ApplyRefused("audit_unavailable")
        for name in ("base_checksum", "expected_after_checksum", "observed_after_checksum", "error_category"):
            if projection[name] is not None and not isinstance(projection[name], str):
                raise ApplyRefused("audit_unavailable")

    def _validate_journal_entry(self, entry: dict[str, object]) -> None:
        if set(entry) != self._JOURNAL_FIELDS or self._FORBIDDEN_FIELDS & set(entry):
            raise ApplyRefused("audit_unavailable")
        projection = {key: value for key, value in entry.items() if key in self._APPLY_FIELDS}
        self._validate_projection(projection)
        if type(entry["journal_sequence"]) is not int or entry["journal_sequence"] < 1:
            raise ApplyRefused("audit_unavailable")
        if entry["previous_entry_digest"] is not None and not isinstance(entry["previous_entry_digest"], str):
            raise ApplyRefused("audit_unavailable")

    def _entry_digest(self, entry: dict[str, object]) -> str:
        unsigned = dict(entry)
        unsigned.pop("entry_digest", None)
        return "hmac-sha256:" + hmac.new(self._key, canonical_json(unsigned), hashlib.sha256).hexdigest()

    def _check_directory(self) -> tuple[int, int]:
        try:
            info = os.lstat(self._directory)
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise ApplyRefused("audit_unavailable")
        return (info.st_dev, info.st_ino)

    def _assert_directory_identity(self) -> None:
        if self._check_directory() != self._directory_identity or self._fd_identity(self._directory_fd) != self._directory_identity:
            raise ApplyRefused("audit_unavailable")

    @staticmethod
    def _fd_identity(descriptor: int) -> tuple[int, int]:
        info = os.fstat(descriptor)
        return (info.st_dev, info.st_ino)

    def _open_regular(self, name: str, flags: int, *, create: bool) -> int:
        mode = 0o600 if create else 0o000
        try:
            descriptor = os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=self._directory_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        try:
            self._verify_regular_fd(descriptor)
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _verify_regular_fd(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise ApplyRefused("audit_unavailable")

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short audit write")
            offset += written


class AtomicSingleFileApplier:
    """Server-owned v0.8 proposal state with atomic ``create_absent`` only.

    The constructor deliberately requires both a trusted owner authority and a
    server-owned audit key.  There is no general write API, client-provided
    proposal identifier, client-provided fingerprint, or client-provided owner
    session binding.
    """

    _DENIED_TOP_LEVEL = {
        ".git",
        ".obsidian",
        ".pkm-index",
        "Assets",
        "System",
        "scripts",
        "src",
        "tests",
        "dist",
        "build",
    }

    def __init__(
        self,
        vault_root: str | Path,
        *,
        allowed_roots: tuple[str, ...],
        audit_directory: str | Path,
        owner_authority: TrustedOwnerAuthority,
        audit_key: bytes,
        server_instance_id: str | None = None,
        approval_lifetime_seconds: float = MAX_APPROVAL_LIFETIME_SECONDS,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._require_platform_primitives()
        if not 0 < approval_lifetime_seconds <= MAX_APPROVAL_LIFETIME_SECONDS:
            raise ApplyRefused("invalid_approval_lifetime")
        if not hasattr(owner_authority, "current_owner_session_binding") or not hasattr(
            owner_authority, "verify_owner_confirmation"
        ):
            raise ApplyRefused("owner_authority_required")
        requested_root = Path(vault_root)
        try:
            root_info = os.lstat(requested_root)
            root = requested_root.resolve(strict=True)
        except OSError as exc:
            raise ApplyRefused("invalid_vault_root") from exc
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise ApplyRefused("invalid_vault_root")
        try:
            self._root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ApplyRefused("invalid_vault_root") from exc
        self.root = root
        self._root_identity = self._fd_identity(self._root_fd)
        self._owner_authority = owner_authority
        self._approval_key = secrets.token_bytes(32)
        self._approval_lifetime_seconds = approval_lifetime_seconds
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._server_instance_id = server_instance_id or self._new_opaque_id("server")
        self._validate_opaque(self._server_instance_id, "server_instance_id")
        self._allowed_roots = self._prepare_allowed_roots(allowed_roots)
        self.audit = _AuditJournal(Path(audit_directory), key=audit_key)
        self._prepared: dict[str, _PreparedProposal] = {}
        self._prepared_lock = threading.Lock()

    def close(self) -> None:
        self.audit.close()
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def propose(
        self,
        *,
        operation: str,
        path: str,
        proposed_bytes: bytes,
        request_origin: str = "local-request",
    ) -> dict[str, Any]:
        """Create one immutable public proposal from untrusted candidate input.

        The server generates all identity, policy, owner-session, checksum,
        preview, token-binding, expiry, and fingerprint values.  ``replace``
        is intentionally refused before reading or writing a source file.
        """

        if operation == "replace_existing":
            raise ApplyRefused("replace_existing_unsupported")
        if operation != "create_absent":
            raise ApplyRefused("unsupported_operation")
        if not isinstance(proposed_bytes, bytes):
            raise ApplyRefused("malformed_proposal")
        try:
            canonical_path = canonical_relative_markdown_path(path)
            _, selected_root_id = self._select_allowed_root(canonical_path)
            self._validate_request_origin(request_origin)
            self._assert_root_identity()
            self._assert_absent(canonical_path)
            owner_session_binding = self._owner_authority.current_owner_session_binding()
            self._validate_opaque(owner_session_binding, "owner_session_binding")
        except (ProposalValidationError, ApplyRefused) as exc:
            raise ApplyRefused(str(exc)) from exc
        except Exception as exc:
            raise ApplyRefused("owner_session_unavailable") from exc

        issued = self._utc_now()
        issued_at = self._format_timestamp(issued)
        expires_at = self._format_timestamp(issued + timedelta(seconds=self._approval_lifetime_seconds))
        proposal_id = self._new_opaque_id("proposal")
        raw_token = secrets.token_urlsafe(48)
        rendered_diff = render_unified_byte_diff_v1(
            path=canonical_path, base_bytes=b"", proposed_bytes=proposed_bytes, absent=True
        )
        public: dict[str, Any] = {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "proposal_fingerprint": "",
            "operation": "create_absent",
            "scope": {
                "changed_path_count": 1,
                "changed_paths": [canonical_path],
                "bulk": False,
                "destructive": False,
            },
            "target": {
                "vault_root_id": self._vault_root_id(),
                "allowed_root_id": selected_root_id,
                "path": canonical_path,
                "kind": "absent_final_component",
                "file_identity": None,
            },
            "base": {"existence": "absent", "checksum": None},
            "change": {
                "representation": "replacement-bytes/base64-v1",
                "proposed_bytes_base64": base64.b64encode(proposed_bytes).decode("ascii"),
                "proposed_byte_length": len(proposed_bytes),
                "proposed_checksum": sha256_checksum(proposed_bytes),
                "review": {
                    "format": "unified-byte-diff-v1",
                    "rendered_diff": rendered_diff,
                    "rendered_diff_checksum": sha256_checksum(rendered_diff.encode("utf-8")),
                },
            },
            "metadata": {
                "policy_version": POLICY_VERSION,
                "server_instance_id": self._server_instance_id,
                "risk_class": "single_file_non_destructive",
                "issued_at": issued_at,
                "expires_at": expires_at,
                "request_origin": request_origin,
            },
            "approval": {
                "mode": "local-owner-one-time",
                "token_binding": self._public_token_binding(raw_token, proposal_id, owner_session_binding),
                "approval_session_binding": owner_session_binding,
                "state": "proposed",
            },
            "audit": {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "proposal_id_redaction": self.audit.redact_proposal_id(proposal_id),
                "journal_scope": "derived-local-only",
                "planned_changed_path_count": 1,
            },
        }
        public["proposal_fingerprint"] = compute_proposal_fingerprint(public)
        try:
            validated = validate_proposal(
                public,
                base_bytes=b"",
                expected_vault_root_id=self._vault_root_id(),
                expected_allowed_root_id=selected_root_id,
                expected_server_instance_id=self._server_instance_id,
            )
        except ProposalValidationError as exc:  # A server construction bug must fail closed.
            raise ApplyRefused("internal_integrity_failure") from exc
        record = _PreparedProposal(
            public=validated.record,
            base_bytes=b"",
            proposed_bytes=validated.proposed_bytes,
            token_digest=self._token_digest(raw_token, validated.record),
            raw_token=raw_token,
            monotonic_deadline=self._monotonic() + self._approval_lifetime_seconds,
        )
        with self._prepared_lock:
            if proposal_id in self._prepared:  # Cryptographic collision is refused, never reused.
                raise ApplyRefused("duplicate_proposal")
            self._prepared[proposal_id] = record
        return _json_clone(validated.record)

    def approve_from_trusted_owner(self, confirmation: OwnerConfirmation) -> str:
        """Return the raw one-time token only to the trusted owner channel."""

        if not isinstance(confirmation, OwnerConfirmation) or not isinstance(confirmation.proposal_id, str):
            raise ApplyRefused("owner_confirmation_required")
        with self._prepared_lock:
            record = self._prepared.get(confirmation.proposal_id)
            if record is None or record.state != "proposed" or self._expired(record):
                raise ApplyRefused("not_approved")
            self._validate_private_record(record)
            public = record.public
            try:
                verified = self._owner_authority.verify_owner_confirmation(
                    confirmation=confirmation,
                    proposal_id=public["proposal_id"],
                    proposal_fingerprint=public["proposal_fingerprint"],
                    server_instance_id=self._server_instance_id,
                    owner_session_binding=public["approval"]["approval_session_binding"],
                )
            except Exception as exc:
                raise ApplyRefused("owner_confirmation_required") from exc
            if verified is not True:
                raise ApplyRefused("owner_confirmation_required")
            if record.raw_token is None:
                raise ApplyRefused("replayed")
            token = record.raw_token
            record.raw_token = None
            record.state = "approved"
            record.approval_at = self._timestamp_now()
            return token

    def apply(self, *, proposal_id: str, token: str) -> ApplyResult:
        """Consume an owner-issued token and atomically publish only an absent file."""

        record = self._consume_for_apply(proposal_id, token)
        if record is None:
            return ApplyResult(ApplyOutcome.REFUSED, proposal_id)

        try:
            self._assert_root_identity()
            self._assert_absent(record.public["target"]["path"])
        except ApplyRefused as exc:
            outcome = ApplyOutcome.CONFLICT if str(exc) == "target_already_exists" else ApplyOutcome.REFUSED
            if not self._append_audit(record, outcome.value, observed_after=None, error_category=str(exc)):
                outcome = ApplyOutcome.FAILED
            self._terminal(record, outcome.value)
            return ApplyResult(outcome, proposal_id)

        # A durable pending record is authorization precondition, not best effort.
        if not self._append_audit(record, "pending", observed_after=None, error_category=None):
            self._terminal(record, "refused")
            return ApplyResult(ApplyOutcome.REFUSED, proposal_id)

        mutation_started = False
        try:
            self._publish_absent(record.public["target"]["path"], record.proposed_bytes)
            mutation_started = True
            final = self._read_regular(record.public["target"]["path"])
            if sha256_checksum(final) != record.public["change"]["proposed_checksum"]:
                self._terminal(record, "indeterminate")
                self._append_audit(record, "indeterminate", observed_after=final, error_category="after_checksum_mismatch")
                return ApplyResult(ApplyOutcome.INDETERMINATE, proposal_id)
            if not self._append_audit(record, "applied", observed_after=final, error_category=None):
                self._terminal(record, "indeterminate")
                return ApplyResult(ApplyOutcome.INDETERMINATE, proposal_id)
            self._terminal(record, "applied")
            return ApplyResult(ApplyOutcome.APPLIED, proposal_id)
        except _CreateConflict:
            if not self._append_audit(record, "conflict", observed_after=None, error_category="target_already_exists"):
                self._terminal(record, "failed")
                return ApplyResult(ApplyOutcome.FAILED, proposal_id)
            self._terminal(record, "conflict")
            return ApplyResult(ApplyOutcome.CONFLICT, proposal_id)
        except _PublishedFailure:
            mutation_started = True
            final = self._read_after_failure(record.public["target"]["path"])
            self._append_audit(record, "indeterminate", observed_after=final, error_category="publish_sync_failed")
            self._terminal(record, "indeterminate")
            return ApplyResult(ApplyOutcome.INDETERMINATE, proposal_id)
        except ApplyRefused as exc:
            final = self._read_after_failure(record.public["target"]["path"])
            outcome = "indeterminate" if mutation_started else "failed"
            self._append_audit(record, outcome, observed_after=final, error_category=str(exc))
            self._terminal(record, outcome)
            return ApplyResult(ApplyOutcome.INDETERMINATE if mutation_started else ApplyOutcome.REFUSED, proposal_id)
        except Exception:
            # KeyboardInterrupt and SystemExit intentionally propagate, leaving the durable
            # pending record for read-only crash recovery instead of guessing an outcome.
            final = self._read_after_failure(record.public["target"]["path"])
            outcome = "indeterminate" if mutation_started else "failed"
            self._append_audit(record, outcome, observed_after=final, error_category="apply_failed")
            self._terminal(record, outcome)
            return ApplyResult(ApplyOutcome.INDETERMINATE if mutation_started else ApplyOutcome.FAILED, proposal_id)

    def recover_incomplete_audit(self) -> list[dict[str, object]]:
        """Read-only crash recovery for pending audit records."""

        return self.audit.recover_pending(self._observe_pending)

    def _consume_for_apply(self, proposal_id: str, token: str) -> _PreparedProposal | None:
        if not isinstance(proposal_id, str) or not isinstance(token, str):
            return None
        with self._prepared_lock:
            record = self._prepared.get(proposal_id)
            if record is None or record.state != "approved" or self._expired(record):
                return None
            try:
                self._validate_private_record(record)
            except ApplyRefused:
                record.state = "refused"
                return None
            if not hmac.compare_digest(record.token_digest, self._token_digest(token, record.public)):
                return None
            # The state transition is complete before any source file is opened for writing.
            record.state = "consuming"
            return record

    def _expired(self, record: _PreparedProposal) -> bool:
        try:
            expires_at = datetime.fromisoformat(record.public["metadata"]["expires_at"].replace("Z", "+00:00"))
            wall_expired = self._utc_now() >= expires_at
        except (AttributeError, KeyError, TypeError, ValueError, ApplyRefused):
            wall_expired = True
        if wall_expired or self._monotonic() >= record.monotonic_deadline:
            record.state = "expired"
            return True
        return False

    def _terminal(self, record: _PreparedProposal, state: str) -> None:
        with self._prepared_lock:
            record.state = state

    def _validate_private_record(self, record: _PreparedProposal) -> None:
        public = record.public
        try:
            validate_proposal(
                public,
                base_bytes=record.base_bytes,
                expected_vault_root_id=self._vault_root_id(),
                expected_allowed_root_id=public["target"]["allowed_root_id"],
                expected_server_instance_id=self._server_instance_id,
            )
        except (KeyError, ProposalValidationError) as exc:
            raise ApplyRefused("tampered") from exc
        if record.proposed_bytes != base64.b64decode(
            public["change"]["proposed_bytes_base64"].encode("ascii"), validate=True
        ):
            raise ApplyRefused("tampered")

    def _append_audit(
        self,
        record: _PreparedProposal,
        outcome: str,
        *,
        observed_after: bytes | None,
        error_category: str | None,
    ) -> bool:
        public = record.public
        try:
            self.audit.append(
                {
                    "kind": "apply",
                    "schema_version": AUDIT_SCHEMA_VERSION,
                    "policy_version": POLICY_VERSION,
                    "journal_scope": "derived-local-only",
                    "proposal_fingerprint": public["proposal_fingerprint"],
                    "proposal_id_redaction": public["audit"]["proposal_id_redaction"],
                    "operation": public["operation"],
                    "path": public["target"]["path"],
                    "vault_root_id": public["target"]["vault_root_id"],
                    "allowed_root_id": public["target"]["allowed_root_id"],
                    "issued_at": public["metadata"]["issued_at"],
                    "expires_at": public["metadata"]["expires_at"],
                    "approval_at": record.approval_at,
                    "outcome": outcome,
                    "base_checksum": public["base"]["checksum"],
                    "expected_after_checksum": public["change"]["proposed_checksum"],
                    "observed_after_checksum": sha256_checksum(observed_after) if observed_after is not None else None,
                    "changed_path_count": 1,
                    "server_instance_id": self._server_instance_id,
                    "error_category": error_category,
                }
            )
            return True
        except (ApplyRefused, OSError, ProposalValidationError):
            return False

    def _observe_pending(self, pending: dict[str, object]) -> tuple[str, str | None]:
        try:
            path = pending["path"]
            expected = pending["expected_after_checksum"]
            if not isinstance(path, str) or not isinstance(expected, str):
                return ("indeterminate", None)
            observed = self._read_regular(path)
        except (ApplyRefused, OSError):
            return ("indeterminate", None)
        observed_checksum = sha256_checksum(observed)
        return ("applied_verified" if hmac.compare_digest(observed_checksum, expected) else "indeterminate", observed_checksum)

    def _publish_absent(self, relative: str, data: bytes) -> None:
        """Publish complete bytes with link-at-if-absent; never stream to target."""

        parent_fd, name = self._open_parent(relative)
        temporary = f".cognitiveos-create-{secrets.token_hex(24)}"
        descriptor = -1
        published = False
        try:
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                self._verify_regular_fd(descriptor)
                self._write_and_sync(descriptor, data)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                    descriptor = -1
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise _CreateConflict from exc
            except (NotImplementedError, TypeError) as exc:
                raise ApplyRefused("atomic_create_unsupported") from exc
            except OSError as exc:
                if exc.errno in {errno.EOPNOTSUPP, errno.ENOSYS}:
                    raise ApplyRefused("atomic_create_unsupported") from exc
                raise
            published = True
            try:
                os.fsync(parent_fd)
                os.unlink(temporary, dir_fd=parent_fd)
                temporary = ""
                os.fsync(parent_fd)
            except OSError as exc:
                raise _PublishedFailure(str(exc)) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    if published:
                        pass
            os.close(parent_fd)

    def _read_regular(self, relative: str) -> bytes:
        parent_fd, name = self._open_parent(relative)
        try:
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ApplyRefused("target_missing") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ApplyRefused("unsafe_target")
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                opened = os.fstat(descriptor)
                if (
                    (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                ):
                    raise ApplyRefused("target_changed")
                chunks: list[bytes] = []
                while block := os.read(descriptor, 64 * 1024):
                    chunks.append(block)
                return b"".join(chunks)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def _read_after_failure(self, path: str) -> bytes | None:
        try:
            return self._read_regular(path)
        except (ApplyRefused, OSError):
            return None

    def _assert_absent(self, relative: str) -> None:
        parent_fd, name = self._open_parent(relative)
        try:
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise ApplyRefused("target_already_exists")
        finally:
            os.close(parent_fd)

    def _open_parent(self, relative: str) -> tuple[int, str]:
        canonical = canonical_relative_markdown_path(relative)
        self._select_allowed_root(canonical)
        self._assert_root_identity()
        parts = canonical.split("/")
        current = os.dup(self._root_fd)
        try:
            for component in parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                child_info = os.fstat(child)
                if not stat.S_ISDIR(child_info.st_mode) or child_info.st_nlink < 2:
                    os.close(child)
                    raise ApplyRefused("unsafe_path")
                os.close(current)
                current = child
            return current, parts[-1]
        except (OSError, ProposalValidationError) as exc:
            os.close(current)
            if isinstance(exc, ApplyRefused):
                raise
            raise ApplyRefused("unsafe_path") from exc

    def _prepare_allowed_roots(self, values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        if not values:
            raise ApplyRefused("no_allowed_roots")
        prepared: list[tuple[str, str]] = []
        for value in values:
            try:
                if not isinstance(value, str) or not value:
                    raise ProposalValidationError("invalid_allowed_root")
                if value.endswith(".md"):
                    raise ProposalValidationError("invalid_allowed_root")
                candidate = value
                if "\\" in candidate or candidate.startswith("/") or ":" in candidate or "\x00" in candidate:
                    raise ProposalValidationError("invalid_allowed_root")
                components = candidate.split("/")
                if any(not part or part in {".", ".."} or part.endswith((".", " ")) for part in components):
                    raise ProposalValidationError("invalid_allowed_root")
                if components[0] in self._DENIED_TOP_LEVEL:
                    raise ProposalValidationError("invalid_allowed_root")
                canonical = "/".join(components)
            except ProposalValidationError as exc:
                raise ApplyRefused("invalid_allowed_root") from exc
            identity = "allowed-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
            prepared.append((canonical, identity))
        if len({item[0] for item in prepared}) != len(prepared):
            raise ApplyRefused("invalid_allowed_root")
        return tuple(prepared)

    def _select_allowed_root(self, path: str) -> tuple[str, str]:
        parts = tuple(path.split("/"))
        matches = [
            item
            for item in self._allowed_roots
            if parts[: len(item[0].split("/"))] == tuple(item[0].split("/"))
        ]
        if not matches:
            raise ApplyRefused("policy_denied")
        return max(matches, key=lambda item: len(item[0]))

    def _assert_root_identity(self) -> None:
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            raise ApplyRefused("invalid_vault_root") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or (info.st_dev, info.st_ino) != self._root_identity
            or self._fd_identity(self._root_fd) != self._root_identity
        ):
            raise ApplyRefused("invalid_vault_root")

    def _vault_root_id(self) -> str:
        dev, ino = self._root_identity
        material = f"{dev}:{ino}".encode("ascii")
        return "vault-" + hashlib.sha256(material).hexdigest()[:32]

    def _token_digest(self, token: str, public: dict[str, Any]) -> bytes:
        """Private token verifier bound to the final immutable fingerprint."""

        binding = "\0".join(
            (
                token,
                public["proposal_id"],
                public["proposal_fingerprint"],
                self._server_instance_id,
                public["approval"]["approval_session_binding"],
            )
        ).encode("utf-8")
        return hmac.new(self._approval_key, binding, hashlib.sha256).digest()

    def _public_token_binding(self, token: str, proposal_id: str, owner_session_binding: str) -> str:
        """Commit to the token's server, proposal, and session context.

        The final fingerprint cannot be placed inside this public commitment
        without a circular hash construction: the fingerprint covers the
        token binding itself.  The private token digest therefore binds the
        same token to that final fingerprint before approval or apply.
        """

        binding = "\0".join((token, proposal_id, self._server_instance_id, owner_session_binding)).encode("utf-8")
        return "sha256:" + hmac.new(self._approval_key, binding, hashlib.sha256).hexdigest()

    def _timestamp_now(self) -> str:
        return self._format_timestamp(self._utc_now())

    def _utc_now(self) -> datetime:
        value = self._wall_clock()
        if not isinstance(value, datetime):
            raise ApplyRefused("clock_unavailable")
        if value.tzinfo is None:
            raise ApplyRefused("clock_unavailable")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    @staticmethod
    def _validate_opaque(value: object, name: str) -> None:
        if not isinstance(value, str) or not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in value):
            raise ApplyRefused(f"invalid_{name}")

    @staticmethod
    def _validate_request_origin(value: object) -> None:
        if not isinstance(value, str) or not value or len(value) > 128 or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in value
        ):
            raise ApplyRefused("malformed_request_origin")

    @staticmethod
    def _new_opaque_id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_urlsafe(32)}"

    @staticmethod
    def _fd_identity(descriptor: int) -> tuple[int, int]:
        info = os.fstat(descriptor)
        return (info.st_dev, info.st_ino)

    @staticmethod
    def _verify_regular_fd(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ApplyRefused("unsafe_target")

    @staticmethod
    def _write_and_sync(descriptor: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short_source_write")
            offset += written
        os.fsync(descriptor)

    @staticmethod
    def _require_platform_primitives() -> None:
        required = ("O_NOFOLLOW", "O_DIRECTORY")
        if (
            os.name != "posix"
            or fcntl is None
            or any(not hasattr(os, name) for name in required)
            or os.open not in os.supports_dir_fd
            or os.stat not in os.supports_dir_fd
            or os.link not in os.supports_dir_fd
        ):
            raise ApplyRefused("unsupported_platform")


def _json_clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_json(value).decode("utf-8"))
