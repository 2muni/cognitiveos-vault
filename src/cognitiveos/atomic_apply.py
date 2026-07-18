"""Opt-in, approval-gated single-file apply boundary; deliberately not an MCP tool.

The caller configures one vault root and one or more narrow, relative allowlist
prefixes.  Proposals are prepared and retained by this process; callers cannot
replace their path or bytes after approval.  The module has no MCP registration
and is intended only for a future trusted local approval UI.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import threading
from typing import Callable

from .approval import ApprovalOutcome, ApprovalTokenStore, sha256_checksum


AUDIT_SCHEMA_VERSION = "writeback-audit/v0.8"
POLICY_VERSION = "writeback-policy/v0.8"


class ApplyOutcome(str, Enum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    REFUSED = "refused"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class AtomicApplyProposal:
    """The private, server-prepared subset required for one apply attempt."""

    proposal_id: str
    proposal_fingerprint: str
    owner_session_binding: str
    operation: str
    path: str
    proposed_bytes: bytes
    base_bytes: bytes | None
    file_identity: tuple[int, int] | None
    changed_paths: tuple[str, ...]
    bulk: bool = False
    destructive: bool = False


@dataclass(frozen=True)
class ApplyResult:
    outcome: ApplyOutcome
    proposal_id: str


class ApplyRefused(ValueError):
    """A non-sensitive policy failure; messages never include absolute paths."""


class _AuditJournal:
    """Owner-only, append-only JSONL journal with a digest chain."""

    def __init__(self, directory: Path) -> None:
        try:
            info = os.lstat(directory)
        except OSError as exc:
            raise ApplyRefused("audit_unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ApplyRefused("audit_unavailable")
        self._directory = directory
        self._directory_fd = os.open(
            directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        self._lock = threading.Lock()

    def append(self, record: dict[str, object]) -> dict[str, object]:
        with self._lock:
            previous = self.records()
            self._verify_chain(previous)
            entry = dict(record)
            entry["journal_sequence"] = len(previous) + 1
            entry["previous_entry_digest"] = previous[-1]["entry_digest"] if previous else None
            entry["entry_digest"] = self._digest(entry)
            payload = self._canonical(entry) + b"\n"
            fd = os.open(
                "journal.jsonl",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._directory_fd,
            )
            try:
                if os.write(fd, payload) != len(payload):
                    raise OSError("short audit write")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(self._directory_fd)
            return entry

    def records(self) -> list[dict[str, object]]:
        try:
            fd = os.open("journal.jsonl", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._directory_fd)
        except FileNotFoundError:
            return []
        try:
            chunks: list[bytes] = []
            while block := os.read(fd, 64 * 1024):
                chunks.append(block)
        finally:
            os.close(fd)
        try:
            return [json.loads(line) for line in b"".join(chunks).splitlines() if line]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApplyRefused("audit_unavailable") from exc

    def _verify_chain(self, records: list[dict[str, object]]) -> None:
        previous: str | None = None
        for sequence, record in enumerate(records, start=1):
            digest = record.get("entry_digest")
            if (
                record.get("journal_sequence") != sequence
                or record.get("previous_entry_digest") != previous
                or not isinstance(digest, str)
                or digest != self._digest(record)
            ):
                raise ApplyRefused("audit_unavailable")
            previous = digest

    @staticmethod
    def _canonical(record: dict[str, object]) -> bytes:
        return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    def _digest(self, record: dict[str, object]) -> str:
        unsigned = dict(record)
        unsigned.pop("entry_digest", None)
        return sha256_checksum(self._canonical(unsigned))


class AtomicSingleFileApplier:
    """Atomically apply only a prepared create or replacement in an allowlist."""

    def __init__(self, vault_root: str | Path, *, allowed_roots: tuple[str, ...], audit_directory: str | Path) -> None:
        requested_root = Path(vault_root)
        try:
            root_info = os.lstat(requested_root)
            root = requested_root.resolve(strict=True)
        except OSError as exc:
            raise ApplyRefused("invalid_vault_root") from exc
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise ApplyRefused("invalid_vault_root")
        self.root = root
        self._root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        self.allowed_roots = tuple(self._normal_path(item) for item in allowed_roots)
        if not self.allowed_roots:
            raise ApplyRefused("no_allowed_roots")
        self.audit = _AuditJournal(Path(audit_directory))
        self._prepared: dict[str, AtomicApplyProposal] = {}
        self._prepared_lock = threading.Lock()

    def prepare(
        self,
        *,
        proposal_id: str,
        proposal_fingerprint: str,
        owner_session_binding: str,
        operation: str,
        path: str,
        proposed_bytes: bytes,
        changed_paths: tuple[str, ...] | None = None,
        bulk: bool = False,
        destructive: bool = False,
    ) -> AtomicApplyProposal:
        path = self._validate_target(path)
        if operation not in {"replace_existing", "create_absent"}:
            raise ApplyRefused("unsupported_operation")
        if not all(isinstance(value, str) and value for value in (proposal_id, proposal_fingerprint, owner_session_binding)):
            raise ApplyRefused("malformed_proposal")
        if not isinstance(proposed_bytes, bytes):
            raise ApplyRefused("malformed_proposal")
        proposal = AtomicApplyProposal(
            proposal_id,
            proposal_fingerprint,
            owner_session_binding,
            operation,
            path,
            proposed_bytes,
            None,
            None,
            changed_paths if changed_paths is not None else (path,),
            bulk,
            destructive,
        )
        self._validate_scope(proposal, require_captured_base=False)
        if operation == "replace_existing":
            data, identity = self._read_regular(path)
            proposal = replace(proposal, base_bytes=data, file_identity=identity)
        else:
            self._assert_absent(path)
        with self._prepared_lock:
            if proposal_id in self._prepared:
                raise ApplyRefused("duplicate_proposal")
            self._prepared[proposal_id] = proposal
        return proposal

    def apply(
        self,
        proposal: AtomicApplyProposal,
        *,
        token: str,
        approvals: ApprovalTokenStore,
        before_replace: Callable[[], None] | None = None,
        after_replace: Callable[[], None] | None = None,
    ) -> ApplyResult:
        """Consume one approval and apply once; recovery never changes source bytes."""

        try:
            self._assert_prepared(proposal)
            self._validate_scope(proposal)
            if proposal.operation == "replace_existing":
                observed, identity = self._read_regular(proposal.path)
                if identity != proposal.file_identity:
                    return self._consume_conflict(proposal, token, approvals, observed)
            else:
                self._assert_absent(proposal.path)
                observed = b""
            attempt = approvals.consume_for_revalidation(
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.proposal_fingerprint,
                owner_session_binding=proposal.owner_session_binding,
                token=token,
                observed_base_bytes=observed,
            )
            if attempt.outcome is ApprovalOutcome.CONFLICT:
                self._audit(proposal, "conflict", observed_after=None)
                return ApplyResult(ApplyOutcome.CONFLICT, proposal.proposal_id)
            if attempt.outcome is not ApprovalOutcome.READY:
                return ApplyResult(ApplyOutcome.REFUSED, proposal.proposal_id)
            self._audit(proposal, "pending", observed_after=None)
        except ApplyRefused:
            return ApplyResult(ApplyOutcome.REFUSED, proposal.proposal_id)
        except OSError:
            return ApplyResult(ApplyOutcome.FAILED, proposal.proposal_id)

        mutation_started = False
        try:
            if before_replace:
                before_replace()
            if proposal.operation == "replace_existing":
                current, identity = self._read_regular(proposal.path)
                if current != proposal.base_bytes or identity != proposal.file_identity:
                    self._audit(proposal, "conflict", observed_after=None)
                    return ApplyResult(ApplyOutcome.CONFLICT, proposal.proposal_id)
            else:
                self._assert_absent(proposal.path)
            mutation_started = True
            self._atomic_write(proposal.path, proposal.proposed_bytes, exclusive=proposal.operation == "create_absent")
            if after_replace:
                after_replace()
            final, _ = self._read_regular(proposal.path)
            if sha256_checksum(final) != sha256_checksum(proposal.proposed_bytes):
                self._audit(proposal, "indeterminate", observed_after=final)
                return ApplyResult(ApplyOutcome.INDETERMINATE, proposal.proposal_id)
            self._audit(proposal, "applied", observed_after=final)
            return ApplyResult(ApplyOutcome.APPLIED, proposal.proposal_id)
        except Exception:
            final = self._read_after_failure(proposal.path)
            outcome = "indeterminate" if mutation_started else "failed"
            try:
                self._audit(proposal, outcome, observed_after=final)
            except (ApplyRefused, OSError):
                pass
            return ApplyResult(ApplyOutcome.INDETERMINATE if mutation_started else ApplyOutcome.FAILED, proposal.proposal_id)

    def recover_incomplete_audit(self) -> list[dict[str, object]]:
        """Append recovery evidence for pending entries without writing source files."""

        records = self.audit.records()
        finalized = {str(item.get("proposal_id")) for item in records if item.get("outcome") != "pending"}
        recovered: list[dict[str, object]] = []
        for item in records:
            proposal_id = str(item.get("proposal_id"))
            if item.get("outcome") != "pending" or proposal_id in finalized:
                continue
            observed = self._read_after_failure(str(item.get("path", "")))
            outcome = "indeterminate"
            if observed is not None and sha256_checksum(observed) == item.get("expected_after_checksum"):
                outcome = "applied_verified"
            recovery = self.audit.append(
                {
                    "kind": "recovery",
                    "schema_version": AUDIT_SCHEMA_VERSION,
                    "policy_version": POLICY_VERSION,
                    "proposal_id": proposal_id,
                    "proposal_id_redaction": item.get("proposal_id_redaction"),
                    "outcome": outcome,
                    "observed_after_checksum": sha256_checksum(observed) if observed is not None else None,
                }
            )
            recovered.append(recovery)
            finalized.add(proposal_id)
        return recovered

    def _assert_prepared(self, proposal: AtomicApplyProposal) -> None:
        with self._prepared_lock:
            if self._prepared.get(proposal.proposal_id) != proposal:
                raise ApplyRefused("unknown_or_altered_proposal")

    def _consume_conflict(
        self, proposal: AtomicApplyProposal, token: str, approvals: ApprovalTokenStore, observed: bytes
    ) -> ApplyResult:
        attempt = approvals.consume_for_revalidation(
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.proposal_fingerprint,
            owner_session_binding=proposal.owner_session_binding,
            token=token,
            observed_base_bytes=observed,
        )
        if attempt.outcome is ApprovalOutcome.CONFLICT:
            self._audit(proposal, "conflict", observed_after=None)
            return ApplyResult(ApplyOutcome.CONFLICT, proposal.proposal_id)
        return ApplyResult(ApplyOutcome.REFUSED, proposal.proposal_id)

    def _audit(self, proposal: AtomicApplyProposal, outcome: str, observed_after: bytes | None) -> None:
        self.audit.append(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "policy_version": POLICY_VERSION,
                "proposal_id": proposal.proposal_id,
                "proposal_id_redaction": hashlib.sha256(proposal.proposal_id.encode("utf-8")).hexdigest()[:16],
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "operation": proposal.operation,
                "path": proposal.path,
                "changed_path_count": 1,
                "outcome": outcome,
                "base_checksum": sha256_checksum(proposal.base_bytes) if proposal.base_bytes is not None else None,
                "expected_after_checksum": sha256_checksum(proposal.proposed_bytes),
                "observed_after_checksum": sha256_checksum(observed_after) if observed_after is not None else None,
            }
        )

    def _validate_scope(self, proposal: AtomicApplyProposal, *, require_captured_base: bool = True) -> None:
        if proposal.operation not in {"replace_existing", "create_absent"} or proposal.bulk or proposal.destructive:
            raise ApplyRefused("unsupported_operation")
        if proposal.changed_paths != (proposal.path,) or not proposal.path.endswith(".md"):
            raise ApplyRefused("single_file_scope_required")
        self._validate_target(proposal.path)
        if require_captured_base and proposal.operation == "replace_existing" and (
            proposal.base_bytes is None or proposal.file_identity is None
        ):
            raise ApplyRefused("malformed_proposal")
        if require_captured_base and proposal.operation == "create_absent" and (
            proposal.base_bytes is not None or proposal.file_identity is not None
        ):
            raise ApplyRefused("malformed_proposal")

    def _normal_path(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ApplyRefused("invalid_path")
        if "\x00" in value or "\\" in value or value.startswith("/") or ":" in value:
            raise ApplyRefused("invalid_path")
        components = value.split("/")
        if any(not component or component in {".", ".."} for component in components):
            raise ApplyRefused("invalid_path")
        return "/".join(components)

    def _validate_target(self, value: str) -> str:
        path = self._normal_path(value)
        if not path.endswith(".md") or not any(path.startswith(root + "/") for root in self.allowed_roots):
            raise ApplyRefused("policy_denied")
        return path

    def _open_parent(self, relative: str) -> tuple[int, str]:
        parts = relative.split("/")
        current = os.dup(self._root_fd)
        try:
            for component in parts[:-1]:
                child = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=current,
                )
                os.close(current)
                current = child
            return current, parts[-1]
        except OSError as exc:
            os.close(current)
            raise ApplyRefused("unsafe_path") from exc

    def _read_regular(self, relative: str) -> tuple[bytes, tuple[int, int]]:
        parent_fd, name = self._open_parent(self._validate_target(relative))
        try:
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ApplyRefused("target_missing") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ApplyRefused("unsafe_target")
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(opened.st_mode):
                    raise ApplyRefused("target_changed")
                chunks: list[bytes] = []
                while block := os.read(fd, 64 * 1024):
                    chunks.append(block)
                return b"".join(chunks), (opened.st_dev, opened.st_ino)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

    def _assert_absent(self, relative: str) -> None:
        parent_fd, name = self._open_parent(self._validate_target(relative))
        try:
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise ApplyRefused("target_already_exists")
        finally:
            os.close(parent_fd)

    def _atomic_write(self, relative: str, data: bytes, *, exclusive: bool) -> None:
        parent_fd, name = self._open_parent(self._validate_target(relative))
        try:
            if exclusive:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    self._write_and_sync(fd, data)
                finally:
                    os.close(fd)
                os.fsync(parent_fd)
                return
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise ApplyRefused("unsafe_target")
            temporary = f".cognitiveos-{secrets.token_hex(16)}"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
            try:
                os.fchmod(descriptor, stat.S_IMODE(existing.st_mode))
                self._write_and_sync(descriptor, data)
                os.close(descriptor)
                descriptor = -1
                os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                temporary = ""
                os.fsync(parent_fd)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                if temporary:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(parent_fd)

    @staticmethod
    def _write_and_sync(fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("short source write")
            offset += written
        os.fsync(fd)

    def _read_after_failure(self, path: str) -> bytes | None:
        try:
            return self._read_regular(path)[0]
        except (ApplyRefused, OSError):
            return None
