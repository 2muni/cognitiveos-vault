"""Strict v0.8 proposal construction and validation.

The proposal is a public review record, never an authorization record.  The
server retains the byte base and every lifecycle value separately, then calls
``validate_proposal`` again before owner confirmation and apply.  The validator
therefore has no coercions, defaults, or forward-compatible unknown fields.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Mapping
import unicodedata

from .approval import MAX_APPROVAL_LIFETIME_SECONDS, sha256_checksum


PROPOSAL_SCHEMA_VERSION = "writeback-proposal/v0.8"
AUDIT_SCHEMA_VERSION = "writeback-audit/v0.8"
POLICY_VERSION = "writeback-policy/v0.8"
REPLACEMENT_REPRESENTATION = "replacement-bytes/base64-v1"
REVIEW_FORMAT = "unified-byte-diff-v1"
MAX_RENDERED_DIFF_BYTES = 1_000_000

_CHECKSUM_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OPAQUE_RE = re.compile(r"[A-Za-z0-9._-]{1,200}\Z")
_REQUEST_ORIGIN_RE = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
_WINDOWS_RESERVED_RE = re.compile(r'[<>:"|?*]')


class ProposalValidationError(ValueError):
    """A malformed, altered, or unsupported v0.8 proposal."""


@dataclass(frozen=True)
class ValidatedProposal:
    """The exact validated values the server can safely retain privately."""

    record: dict[str, Any]
    proposed_bytes: bytes
    base_bytes: bytes


def canonical_json(value: object) -> bytes:
    """Canonical JSON for the restricted v0.8 value domain.

    v0.8 records contain objects, arrays, strings, booleans, null, and bounded
    integer counts only.  Rejecting floating point values avoids the only JSON
    number form for which Python's encoder would not be an RFC 8785/JCS
    implementation.  With that restriction, sorted compact UTF-8 JSON is the
    JCS serialization used for the proposal fingerprint.
    """

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
        raise ProposalValidationError("non_canonical_json") from exc


def compute_proposal_fingerprint(record: Mapping[str, object]) -> str:
    """Compute the fingerprint required by the immutable v0.8 contract."""

    copied = _json_copy(record)
    try:
        copied.pop("proposal_fingerprint")
        approval = copied["approval"]
        audit = copied.pop("audit")
    except (KeyError, TypeError) as exc:
        raise ProposalValidationError("malformed_proposal") from exc
    if not isinstance(approval, dict) or not isinstance(audit, dict):
        raise ProposalValidationError("malformed_proposal")
    approval.pop("state", None)
    return sha256_checksum(canonical_json(copied))


def render_unified_byte_diff_v1(*, path: str, base_bytes: bytes, proposed_bytes: bytes, absent: bool) -> str:
    """Render an exact, bounded byte review without line-ending coercion.

    Every byte is escaped other than printable ASCII excluding backslash.  This
    makes CR, LF, missing final newlines, NUL, and non-UTF-8 values explicit and
    reversible.  The labels contain only the canonical vault-relative path;
    the absent base is the literal ``absent`` sentinel.
    """

    path = canonical_relative_markdown_path(path)
    if not isinstance(base_bytes, bytes) or not isinstance(proposed_bytes, bytes):
        raise ProposalValidationError("malformed_bytes")
    base_label = "absent" if absent else path
    rendered = "\n".join(
        (
            f"--- {base_label}",
            f"+++ {path}",
            "@@ unified-byte-diff-v1 @@",
            f"- {_escape_bytes(base_bytes)}",
            f"+ {_escape_bytes(proposed_bytes)}",
            "",
        )
    )
    if len(rendered.encode("utf-8")) > MAX_RENDERED_DIFF_BYTES:
        raise ProposalValidationError("preview_too_large")
    return rendered


def canonical_relative_markdown_path(value: object) -> str:
    """Reject ambiguous, absolute, non-portable, and non-Markdown paths."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise ProposalValidationError("invalid_path")
    if value != unicodedata.normalize("NFC", value):
        raise ProposalValidationError("invalid_path")
    if value.startswith(("/", "\\\\", "//")) or "\\" in value or ":" in value:
        raise ProposalValidationError("invalid_path")
    components = value.split("/")
    if any(
        not component
        or component in {".", ".."}
        or component.endswith((".", " "))
        or _WINDOWS_RESERVED_RE.search(component)
        or any(ord(character) < 32 for character in component)
        for component in components
    ):
        raise ProposalValidationError("invalid_path")
    if not value.endswith(".md"):
        raise ProposalValidationError("invalid_path")
    return value


def validate_proposal(
    value: object,
    *,
    base_bytes: bytes,
    expected_vault_root_id: str | None = None,
    expected_allowed_root_id: str | None = None,
    expected_server_instance_id: str | None = None,
) -> ValidatedProposal:
    """Strictly validate one public ``writeback-proposal/v0.8`` record.

    Existing-file review regeneration deliberately requires server-retained
    ``base_bytes``.  A public proposal includes the base checksum, not a second
    copy of source content, so a caller cannot make the server trust a client
    supplied base merely to validate a preview.
    """

    if not isinstance(base_bytes, bytes):
        raise ProposalValidationError("base_bytes_unavailable")
    record = _exact_object(
        value,
        "proposal",
        {
            "schema_version",
            "proposal_id",
            "proposal_fingerprint",
            "operation",
            "scope",
            "target",
            "base",
            "change",
            "metadata",
            "approval",
            "audit",
        },
    )
    if record["schema_version"] != PROPOSAL_SCHEMA_VERSION:
        raise ProposalValidationError("unsupported_schema")
    _opaque(record["proposal_id"], "proposal_id")
    _checksum(record["proposal_fingerprint"], "proposal_fingerprint")

    operation = record["operation"]
    if operation not in {"replace_existing", "create_absent"}:
        raise ProposalValidationError("unsupported_operation")

    scope = _exact_object(record["scope"], "scope", {"changed_path_count", "changed_paths", "bulk", "destructive"})
    if type(scope["changed_path_count"]) is not int or scope["changed_path_count"] != 1:
        raise ProposalValidationError("single_file_scope_required")
    if type(scope["bulk"]) is not bool or scope["bulk"]:
        raise ProposalValidationError("single_file_scope_required")
    if type(scope["destructive"]) is not bool or scope["destructive"]:
        raise ProposalValidationError("single_file_scope_required")
    if not isinstance(scope["changed_paths"], list) or len(scope["changed_paths"]) != 1:
        raise ProposalValidationError("single_file_scope_required")

    target = _exact_object(
        record["target"],
        "target",
        {"vault_root_id", "allowed_root_id", "path", "kind", "file_identity"},
    )
    vault_root_id = _opaque(target["vault_root_id"], "vault_root_id")
    allowed_root_id = _opaque(target["allowed_root_id"], "allowed_root_id")
    if expected_vault_root_id is not None and vault_root_id != expected_vault_root_id:
        raise ProposalValidationError("root_identity_mismatch")
    if expected_allowed_root_id is not None and allowed_root_id != expected_allowed_root_id:
        raise ProposalValidationError("root_identity_mismatch")
    path = canonical_relative_markdown_path(target["path"])
    if scope["changed_paths"][0] != path:
        raise ProposalValidationError("single_file_scope_required")

    base = _exact_object(record["base"], "base", {"existence", "checksum"})
    if base["existence"] not in {"present", "absent"}:
        raise ProposalValidationError("malformed_base")

    change = _exact_object(
        record["change"],
        "change",
        {"representation", "proposed_bytes_base64", "proposed_byte_length", "proposed_checksum", "review"},
    )
    if change["representation"] != REPLACEMENT_REPRESENTATION:
        raise ProposalValidationError("unsupported_representation")
    proposed_bytes = _strict_base64(change["proposed_bytes_base64"])
    if type(change["proposed_byte_length"]) is not int or change["proposed_byte_length"] < 0:
        raise ProposalValidationError("malformed_change")
    if change["proposed_byte_length"] != len(proposed_bytes):
        raise ProposalValidationError("malformed_change")
    _checksum(change["proposed_checksum"], "proposed_checksum")
    if sha256_checksum(proposed_bytes) != change["proposed_checksum"]:
        raise ProposalValidationError("proposed_checksum_mismatch")
    review = _exact_object(record["change"]["review"], "review", {"format", "rendered_diff", "rendered_diff_checksum"})
    if review["format"] != REVIEW_FORMAT or not isinstance(review["rendered_diff"], str):
        raise ProposalValidationError("malformed_review")
    _checksum(review["rendered_diff_checksum"], "rendered_diff_checksum")
    if sha256_checksum(review["rendered_diff"].encode("utf-8")) != review["rendered_diff_checksum"]:
        raise ProposalValidationError("preview_checksum_mismatch")

    if operation == "replace_existing":
        if target["kind"] != "existing_regular_file" or not isinstance(target["file_identity"], str):
            raise ProposalValidationError("malformed_existing_target")
        _opaque(target["file_identity"], "file_identity")
        if base["existence"] != "present" or not isinstance(base["checksum"], str):
            raise ProposalValidationError("malformed_base")
        _checksum(base["checksum"], "base_checksum")
        if sha256_checksum(base_bytes) != base["checksum"]:
            raise ProposalValidationError("base_checksum_mismatch")
        expected_review = render_unified_byte_diff_v1(
            path=path, base_bytes=base_bytes, proposed_bytes=proposed_bytes, absent=False
        )
    else:
        if target["kind"] != "absent_final_component" or target["file_identity"] is not None:
            raise ProposalValidationError("malformed_absent_target")
        if base["existence"] != "absent" or base["checksum"] is not None or base_bytes != b"":
            raise ProposalValidationError("malformed_base")
        expected_review = render_unified_byte_diff_v1(
            path=path, base_bytes=b"", proposed_bytes=proposed_bytes, absent=True
        )
    if review["rendered_diff"] != expected_review:
        raise ProposalValidationError("preview_mismatch")

    metadata = _exact_object(
        record["metadata"],
        "metadata",
        {"policy_version", "server_instance_id", "risk_class", "issued_at", "expires_at", "request_origin"},
    )
    if metadata["policy_version"] != POLICY_VERSION:
        raise ProposalValidationError("policy_mismatch")
    server_instance_id = _opaque(metadata["server_instance_id"], "server_instance_id")
    if expected_server_instance_id is not None and server_instance_id != expected_server_instance_id:
        raise ProposalValidationError("server_identity_mismatch")
    if metadata["risk_class"] != "single_file_non_destructive":
        raise ProposalValidationError("unsupported_risk_class")
    _request_origin(metadata["request_origin"])
    issued = _timestamp(metadata["issued_at"], "issued_at")
    expires = _timestamp(metadata["expires_at"], "expires_at")
    if not timedelta(0) < expires - issued <= timedelta(seconds=MAX_APPROVAL_LIFETIME_SECONDS):
        raise ProposalValidationError("invalid_expiry")

    approval = _exact_object(
        record["approval"],
        "approval",
        {"mode", "token_binding", "approval_session_binding", "state"},
    )
    if approval["mode"] != "local-owner-one-time" or approval["state"] != "proposed":
        raise ProposalValidationError("unsupported_approval")
    _checksum(approval["token_binding"], "token_binding")
    _opaque(approval["approval_session_binding"], "approval_session_binding")

    audit = _exact_object(
        record["audit"],
        "audit",
        {"schema_version", "proposal_id_redaction", "journal_scope", "planned_changed_path_count"},
    )
    if audit["schema_version"] != AUDIT_SCHEMA_VERSION or audit["journal_scope"] != "derived-local-only":
        raise ProposalValidationError("malformed_audit")
    _opaque(audit["proposal_id_redaction"], "proposal_id_redaction")
    if type(audit["planned_changed_path_count"]) is not int or audit["planned_changed_path_count"] != 1:
        raise ProposalValidationError("malformed_audit")

    if compute_proposal_fingerprint(record) != record["proposal_fingerprint"]:
        raise ProposalValidationError("fingerprint_mismatch")
    return ValidatedProposal(_json_copy(record), proposed_bytes, base_bytes)


def _escape_bytes(value: bytes) -> str:
    return "".join(chr(byte) if 0x20 <= byte <= 0x7E and byte != 0x5C else f"\\x{byte:02x}" for byte in value)


def _validate_canonical_value(value: object) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if isinstance(value, float):
        raise ProposalValidationError("non_canonical_json")
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProposalValidationError("non_canonical_json")
            _validate_canonical_value(item)
        return
    raise ProposalValidationError("non_canonical_json")


def _exact_object(value: object, name: str, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ProposalValidationError(f"malformed_{name}")
    return value


def _strict_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise ProposalValidationError("malformed_base64")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProposalValidationError("malformed_base64") from exc


def _checksum(value: object, name: str) -> str:
    if not isinstance(value, str) or not _CHECKSUM_RE.fullmatch(value):
        raise ProposalValidationError(f"malformed_{name}")
    return value


def _opaque(value: object, name: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_RE.fullmatch(value):
        raise ProposalValidationError(f"malformed_{name}")
    return value


def _request_origin(value: object) -> str:
    if not isinstance(value, str) or not _REQUEST_ORIGIN_RE.fullmatch(value):
        raise ProposalValidationError("malformed_request_origin")
    return value


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ProposalValidationError(f"malformed_{name}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProposalValidationError(f"malformed_{name}") from exc
    if parsed.tzinfo != timezone.utc:
        raise ProposalValidationError(f"malformed_{name}")
    return parsed


def _json_copy(value: Mapping[str, object] | object) -> dict[str, Any]:
    try:
        copied = json.loads(canonical_json(value).decode("utf-8"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProposalValidationError("malformed_proposal") from exc
    if not isinstance(copied, dict):
        raise ProposalValidationError("malformed_proposal")
    return copied
