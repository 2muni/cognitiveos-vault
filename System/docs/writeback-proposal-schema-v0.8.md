# Writeback Proposal and Exact-Change Contract v0.8

## Status and Scope

This document defines the durable, versioned contract for a future
approval-gated **single-file** write proposal. It implements no endpoint,
configuration, filesystem operation, approval UI, or write capability. The
current MCP surface remains the nine read-only tools.

It is the schema companion to [Writeback Threat Model and Permission Boundary
v0.8](writeback-threat-model-v0.8.md). If an implementation cannot satisfy
both documents exactly, it MUST remain read-only.

The contract deliberately makes a replacement representation authoritative:
the complete proposed bytes are supplied as base64. A familiar rendered diff is
useful for review, but a line-oriented patch alone is not sufficiently
unambiguous for CRLF, missing final newlines, binary bytes, Unicode
normalization, or a future parser difference. An apply implementation MUST
write only the approved replacement bytes; it MUST NOT recompute them from a
diff, template, model output, or current source text.

## Terms and Encoding

- A **proposal** is the immutable public record rendered to the owner before
  approval. Its `proposal_fingerprint` binds every authorization-relevant
  field.
- A **private proposal record** is server-controlled ephemeral state that adds
  the raw one-time approval token, monotonic expiry deadline, approval-session
  binding, and lifecycle state. It is never a client-authored record.
- A **checksum** is lower-case SHA-256 over the exact byte sequence, represented
  as `sha256:` followed by 64 hexadecimal characters. Text is never normalized
  before hashing.
- All timestamps are UTC RFC 3339 strings with a `Z` suffix and no leap-second
  spelling. They are audit/display values; the server's monotonic deadline is
  authoritative for expiry.
- IDs and fingerprints are opaque ASCII strings. A future implementation MUST
  document their generation and validate length/character bounds, without
  treating their spelling as authorization.
- `base64` means RFC 4648 standard base64 with padding. It represents the
  exact sequence of bytes, including any BOM, line ending, and final newline.

## Proposal Schema

The following JSON-shaped schema is normative. Objects reject unknown fields
unless a later schema version explicitly adds them. Field order is not
significant in JSON; the canonical fingerprint serialization defined below is.

```json
{
  "schema_version": "writeback-proposal/v0.8",
  "proposal_id": "opaque-server-generated-id",
  "proposal_fingerprint": "sha256:lowercase-hex",
  "operation": "replace_existing | create_absent",
  "scope": {
    "changed_path_count": 1,
    "changed_paths": ["vault-relative/path.md"],
    "bulk": false,
    "destructive": false
  },
  "target": {
    "vault_root_id": "configured-root-identity",
    "allowed_root_id": "configured-allowed-prefix-identity",
    "path": "vault-relative/path.md",
    "kind": "existing_regular_file | absent_final_component",
    "file_identity": "opaque-stable-identity-or-null"
  },
  "base": {
    "existence": "present | absent",
    "checksum": "sha256:lowercase-hex | null"
  },
  "change": {
    "representation": "replacement-bytes/base64-v1",
    "proposed_bytes_base64": "RFC-4648-base64",
    "proposed_byte_length": 0,
    "proposed_checksum": "sha256:lowercase-hex",
    "review": {
      "format": "unified-byte-diff-v1",
      "rendered_diff": "exact-user-visible-string",
      "rendered_diff_checksum": "sha256:lowercase-hex"
    }
  },
  "metadata": {
    "policy_version": "writeback-policy/v0.8",
    "server_instance_id": "opaque-instance-id",
    "risk_class": "single_file_non_destructive",
    "issued_at": "2026-07-18T00:00:00Z",
    "expires_at": "2026-07-18T00:10:00Z",
    "request_origin": "opaque-attribution-id"
  },
  "approval": {
    "mode": "local-owner-one-time",
    "token_binding": "server-held-token-digest-or-keyed-binding",
    "approval_session_binding": "opaque-session-binding",
    "state": "proposed"
  },
  "audit": {
    "schema_version": "writeback-audit/v0.8",
    "proposal_id_redaction": "non-secret-redacted-id",
    "journal_scope": "derived-local-only",
    "planned_changed_path_count": 1
  }
}
```

`operation` has exactly two v0.8 values. `replace_existing` requires
`base.existence` to be `present`, a non-null base checksum, and a non-null
regular-file identity. `create_absent` requires `base.existence` to be
`absent`, a null base checksum and file identity, and exclusive-create apply
semantics. It never authorizes replacing a path that appears after proposal.

The target path occurs once in `target.path` and once as the sole
`scope.changed_paths` element so independent reviewers can reject inconsistent
or broadened scope. Both values MUST be the same canonical vault-relative
Markdown path. `vault_root_id` and `allowed_root_id` identify startup-validated
server configuration; they are not client-supplied paths and do not disclose
an absolute vault location.

`request_origin` is only a non-secret attribution handle (for example, an MCP
request correlation ID). It MUST NOT contain prompt text, a local path,
credentials, note content, or an authorization claim.

## Exact-Change and Review Contract

`change.proposed_bytes_base64` is the sole authoritative change payload. The
server creates it from the candidate bytes, decodes it once to calculate
`proposed_byte_length` and `proposed_checksum`, and stores the resulting bytes
in its private record. At approval and apply time, it verifies that the bytes
still hash to the bound proposed checksum. The client cannot substitute a
different base64 payload, length, checksum, or preview.

`review.rendered_diff` is a deterministic, user-visible byte diff generated
from the exact base bytes (or an empty absent base) and exact proposed bytes.
It MUST:

- use `unified-byte-diff-v1`, whose implementation documents how every
  non-printable byte, CR, LF, missing final newline, and non-UTF-8 sequence is
  escaped without loss;
- label only the canonical vault-relative target, never an absolute path;
- represent an absent base explicitly as `absent`, rather than as an empty
  existing file;
- be accompanied by `rendered_diff_checksum`, computed over its UTF-8 encoded
  rendered string; and
- be regenerated by the server from the bound byte sequences before display.

The preview checksum makes alteration detectable, but the diff is not an
apply payload. If the rendered form cannot faithfully represent the bytes or
is too large for the trusted approval UI, proposal creation MUST refuse rather
than show a truncated preview or a summary. A future schema may add a bounded
binary review view only with a new version and security review.

## Fingerprint and Token Binding

`proposal_fingerprint` is SHA-256 over UTF-8 canonical JSON (RFC 8785 / JCS)
of the proposal after omitting `proposal_fingerprint`, `approval.state`, and
all `audit` fields. The canonical value MUST include the exact base64 text and
every remaining field, including root identities, scope, target identity,
checksums, preview checksum, policy version, expiry, and token/session binding.
The server, not a client, computes the fingerprint.

At issuance the server generates at least 256 bits from a cryptographically
secure random source. It returns the raw approval token only through the
trusted local approval channel once, retains it only in owner-readable private
state, and stores only a digest or keyed binding in `approval.token_binding`.
The digest/binding includes the proposal ID, fingerprint, server instance ID,
and approval-session binding, so a token cannot authorize another proposal,
server, or session. Raw tokens MUST NOT appear in the public proposal, audit
record, logs, errors, URLs, or telemetry.

Approval binds the local owner session, proposal ID, fingerprint, token
binding, and not-yet-expired server instance. Applying atomically changes the
private state from `approved` to `consuming` before any write is opened. The
same token is therefore valid for one apply attempt, including a failed or
conflicted attempt; it is never restored or retried.

## Expiry, Revalidation, and Conflict Results

`expires_at` MUST be no more than ten minutes after `issued_at`. The private
record also stores a monotonic deadline calculated at issuance. A restart,
policy/root identity change, approval-session end, cancellation, missing
private record, or either deadline expiring invalidates the proposal.

Immediately before a future apply, the server re-resolves the configured root,
allowed root, parent, and target with the threat model's no-follow checks. It
then verifies all of the following against the immutable private record:

1. the policy, server instance, root identities, path, operation, scope,
   fingerprint, and approval session/token binding still match;
2. an existing target is the same verified regular file identity and its exact
   bytes hash to `base.checksum`; or an absent target is still absent; and
3. the decoded replacement bytes hash to `change.proposed_checksum` and match
   the byte length and fingerprinted base64 payload.

Failure in (1) is `refused` (`tampered`, `policy_denied`, `not_approved`,
`expired`, or `replayed` as applicable). Failure in (2) is `conflict` and
writes nothing. Failure in (3) is `refused` as an internal integrity failure.
No result triggers merge, rebasing, normalization, overwrite, rollback, or a
new proposal automatically.

## Audit Projection

The derived audit journal does not copy this proposal. Before mutation, a
future implementation creates a durable pending audit projection containing
only:

- audit and policy schema versions, journal sequence and previous-entry digest;
- `proposal_fingerprint`, `proposal_id_redaction`, operation, target path,
  root identities, issued/expiry/approval times, and outcome category;
- base, expected-after, and observed-after checksums; changed path count;
  server instance ID; and the final chained audit-entry digest.

It MUST omit `proposed_bytes_base64`, `rendered_diff`, raw approval token,
token digest/binding, approval-session binding, request-origin details, note
content, prompts, credentials, environment values, and absolute paths. Audit
persistence failure is a refusal before source mutation.

## Required Rejections

A v0.8 proposal validator MUST reject, before approval, any record that has a
wrong schema version; unknown field; malformed ID, timestamp, checksum,
base64, or byte length; unsupported operation or representation; non-Markdown,
absolute, empty, ambiguous, `.`/`..`, NUL-containing, or root-escaping path;
missing/non-matching root identity; mismatched changed path; count other than
one; `bulk: true`; `destructive: true`; more than ten minutes of lifetime;
inconsistent existing/absent fields; mismatched decoded checksum; or mismatched
regenerated preview checksum/fingerprint.

The following operations and scopes are explicitly rejected by this schema and
require a separate future contract: more than one path; directory creation,
rename, move, delete, archive, trash, restore, purge, overwrite outside the
existing-file replacement contract, migration, bulk normalization, link
rewriting, or mass frontmatter editing; changes to configuration, assets,
system documentation, generated state, Git metadata, source, scripts, tests,
environments, or permissions; and any autonomous, remote, delegated, batch,
or standing approval.

## Compatibility and Implementation Gates

`writeback-proposal/v0.8` is immutable once implemented. A new optional field,
representation, operation, approval mode, or audit field requires a new schema
version and a security review; an implementation MUST reject versions it does
not recognize. It MUST preserve this v0.8 behavior rather than silently
coercing a newer record.

Before a future write tool is exposed, focused schema tests MUST prove valid
existing and absent proposals, plus every rejection class above. They must also
prove byte-level CRLF/final-newline and non-UTF-8 handling, fingerprint and
token/session substitution rejection, expiry, duplicate apply consumption,
checksum/file-identity conflict, and absence of multi-file, bulk, and
destructive operations. Those tests belong with the eventual server-side
validator; this documentation-only issue adds no dormant write code or schema
fixture that could be mistaken for an enabled capability.
