# Writeback Threat Model and Permission Boundary v0.8

## Status and Decision

This is the security design gate for the v0.8 approval-gated writeback
foundation. It extends [Writeback and Permissions v0.1](writeback-permissions-v0.1.md)
with the protocol and failure rules that must be implemented and tested before
any MCP write tool is exposed.

**No write tool is enabled by this document.** The current MCP contract remains
the nine read-only tools documented in [MCP Schema v0.1](schema-mcp-v0.1.md).
There is no default writeback configuration, allowed write root, approval
token, or background write process.

The v0.8 implementation sequence remains: proposal and exact preview, explicit
approval bound to that proposal, immediate revalidation, atomic single-file
apply, and an append-only derived audit record. The normative proposal and
exact-change representation is [Writeback Proposal and Exact-Change Contract
v0.8](writeback-proposal-schema-v0.8.md). A capability may be added only after
a separate security review confirms that its implementation meets every MUST in
these documents.

## Security Objectives

The design protects the Markdown vault as the durable source of truth. A
future implementation MUST ensure that:

- an unapproved, expired, altered, replayed, out-of-policy, or conflicted
  proposal cannot change a source file;
- a successful write changes exactly one approved Markdown file and exactly
  the bytes represented by the reviewed preview;
- the service cannot follow a path, symlink, or configuration trick outside
  the configured vault and explicitly allowed directory prefixes;
- a write is attributable to a local approval event without storing note
  bodies, secrets, or the full diff in the derived audit record; and
- an inability to establish authorization, target identity, atomicity, or the
  audit result fails closed.

Availability is deliberately secondary to integrity. A user can always edit a
Markdown file directly in Obsidian or another editor; writeback refusal must
never attempt to repair, overwrite, or retry a source file automatically.

## Assets and Threats

| Asset | Security property | Principal threats |
| --- | --- | --- |
| Source Markdown, frontmatter, links, and filenames | Integrity and confidentiality | unintended mutation, overwrite, path escape, disclosure through previews or logs |
| Vault root and allowed-root policy | Integrity | path traversal, absolute paths, case/prefix confusion, symlink or junction escape, mutable configuration |
| Proposal bytes and exact preview | Integrity and confidentiality | prompt/client alteration, stale input, approval of a different diff, retention of sensitive content |
| Approval authority and token | Authenticity and single use | model self-approval, token guessing, token replay, session substitution |
| Before/after checksums and target identity | Integrity | time-of-check/time-of-use races, concurrent edits, replacement of a target with a link |
| Derived audit journal | Accountability and confidentiality | missing record, forged/rewritten history, source content leaking into logs |
| MCP server and local process account | Least privilege | a client asking for authority it does not have, environment/config injection, filesystem permissions broader than intended |

Derived indexes, embeddings, caches, prompts, and MCP responses are not an
authority to write. They may inform a proposal, but they cannot authorize it or
substitute for the current bytes read from the target file.

## Actors and Trust Boundaries

The local vault owner is the only approval authority in the initial design.
The owner approves a rendered, exact proposal in a trusted interactive client
session that is associated with the local operating-system account that owns
the vault. A model, retrieval tool, MCP client, prompt, automation, or another
agent may *generate* a proposal but is untrusted for authorization purposes.

The following boundaries are explicit:

1. **Untrusted proposal input to the server.** All operation fields, paths,
   content, timestamps, and claimed checksums supplied by an MCP client are
   input, not facts. The server canonicalizes them and computes all identity
   values itself.
2. **Server to filesystem.** The server receives only a configured canonical
   vault root and a non-empty explicit allowlist of vault-relative directory
   prefixes. Process working directory, environment variables, index paths,
   and client-provided roots never enlarge that authority.
3. **Proposal to approval.** The approval UI receives an immutable preview and
   proposal fingerprint. Free-form text such as “yes”, a model response, an MCP
   tool-approval setting, or prior approval for a similar action is not an
   approval for a write.
4. **Approval to apply.** An approved proposal is a one-time capability, not a
   general write permission. The apply path reopens and revalidates the target
   rather than trusting the earlier proposal read.
5. **Source files to derived audit storage.** Audit records may identify a
   target and its hashes, but must not become a second copy of private source
   prose. The audit directory is derived, local-only, and not Git-tracked.

An implementation MUST run with the least filesystem privileges available. It
MUST not elevate privileges, invoke a shell, follow user-controlled template
or hook commands, contact a network service, or use a model download as part
of proposal or apply.

## Allowed Vault Roots and Target Resolution

Write authority is default-deny. Until a future implementation has an explicit
operator configuration, the allowed-root set is empty and every write request
is rejected. The vault root itself (`.`) is never an allowed write root.

When writeback is later considered, the configuration MUST name one or more
non-empty, vault-relative directory prefixes for each enabled operation. The
server MUST use the configured values after startup validation; it MUST NOT
accept roots from an MCP request. A security review must name each proposed
root and operation together. The configuration must not grant a broad root
merely because a caller wants a convenient default.

The following locations are always denied, even if a broad configuration error
would otherwise include them: the vault control/configuration area, assets,
generated indexes and caches, version-control metadata, runtime environments,
scripts, source code, tests, build output, and all other non-note operational
files. The public system documentation is also denied by the initial write
capability; changing product policy is not a note-writing operation.

For every target, the server MUST:

- accept only a non-empty vault-relative Markdown path; reject absolute POSIX,
  drive-letter, UNC, device, and alternate-stream forms, NUL bytes, and any
  `.` or `..` component;
- normalize separators and compare path *components*, never an untrusted
  string prefix; reject an ambiguous or non-portable spelling rather than
  silently changing its meaning;
- compare denied-root names using the configured filesystem's case semantics,
  and require every existing allowed-root and parent component to use the
  filesystem entry's canonical spelling; if either guarantee is unavailable,
  that root is unsupported and writeback remains read-only;
- resolve the configured vault root and candidate parent with symlink/junction
  following disabled where the platform permits it, then verify both are below
  the canonical vault root and the selected allowed root;
- reject any target, ancestor, or destination that is a symlink, junction,
  hard link, special file, or otherwise cannot be proven to be a regular file
  (or, for creation, a non-existent final component beneath a regular
  directory); and
- keep temporary files and atomic replacement in the verified target directory
  on the same filesystem.

If the platform cannot provide the needed no-follow and atomic-replace
guarantees, that platform/tool combination is unsupported for writeback and
MUST remain read-only. Permission errors, ownership changes, ACL surprises,
or a filesystem identity change are refusals, not conditions to work around.

## Proposal Contract and Lifetime

The proposal phase has no filesystem mutation. The server creates a proposal
only after independently reading the target (or proving an approved create
target is absent), producing an exact byte-level before/after preview and a
server-generated record containing at least:

- opaque `proposal_id` and high-entropy secret approval token;
- server instance identifier, issued time, expiry time, and policy version;
- canonical operation, canonical target path, selected allowed-root identity,
  and complete ordered changed-path set (exactly one path in v0.8);
- SHA-256 of the original bytes, or an explicit `absent` sentinel for a new
  draft; SHA-256 of the proposed bytes; and SHA-256 of the rendered preview;
- an immutable fingerprint over all authorization-relevant fields; and
- a risk classification and the exact user-visible diff/preview.

The server, not the client, computes timestamps, checksums, preview, and
fingerprint. The maximum proposal lifetime is ten minutes. A proposal expires
earlier when the server restarts, its server/root/policy identity changes, the
owner ends the approval session, or the proposal is explicitly cancelled. Each
lifecycle event invalidates the private record and clears any unissued approval
token; a later apply must not merely discover the change after it has started.
Expiry uses a server-side monotonic deadline as well as its recorded wall-clock
timestamp so that client clocks and ordinary clock changes cannot prolong
authority.

Proposal records and approval tokens are stored only in server-controlled,
owner-readable local state. Tokens must be at least 256 bits from a
cryptographically secure random source, never written to logs, and never
returned after initial issuance. Loss of this state invalidates outstanding
proposals; it does not recreate them from a client request.

## Approval Authority and Replay Protection

Approval is a deliberate confirmation by the vault owner after the trusted
client shows the target, operation, risk, exact preview, proposal expiry, and
fingerprint. The confirmation binds the authenticated local approval session,
the exact proposal ID, and its fingerprint. It is valid for one apply attempt
only. A client cannot approve an arbitrary proposal ID on behalf of a user,
and a proposal generator cannot both generate and authorize the same change.

The apply state machine is:

```text
proposed -> approved -> consuming -> applied
                      \-> refused | failed | expired | conflicted
```

The transition from `approved` to `consuming` MUST atomically consume the
proposal before any target file is opened for writing. A duplicate,
simultaneous, or post-crash apply sees a non-approved state and fails. A
failure after consumption never restores the token; the user must inspect the
current file and approve a newly generated proposal. The server also verifies
that the approval session and server instance match the proposal. These rules
prevent replay, cross-session use, and “retry until it works” writes.

Approval never authorizes an operation outside the stated operation, target,
bytes, and lifetime. There is no wildcard approval, batch approval, delegated
agent approval, standing consent, or approval inherited from a prior MCP tool
call. UI-level permission prompts may permit the client to call a future
`approve` or `apply` endpoint, but do not replace this explicit binding.

## Conflict Detection, Checksums, and Atomic Apply

The preview is byte-exact. Existing-file proposals record SHA-256 of the exact
bytes read; they do not normalize line endings, YAML, Unicode, or formatting.
Immediately before applying, the server re-resolves the target under the
no-follow rules, re-reads it through the verified file handle, and compares
its SHA-256 and stable file identity to the proposal. Any difference is a
`conflict` refusal and writes nothing.

For a new draft, the server rechecks absence through the verified parent and
uses exclusive create semantics. It MUST never turn a raced create into an
overwrite. For an existing target, it writes the precomputed proposed bytes to
a secure same-directory temporary file, flushes and synchronizes it, verifies
the temporary-file checksum, and atomically replaces the verified regular
target. It then reopens the final path safely and verifies the recorded
after-checksum. A future implementation must preserve the required file mode
and ownership without widening access; inability to do so fails closed.

If the implementation cannot prove that the final bytes equal the approved
after-checksum, it reports an indeterminate failure and creates no new
proposal automatically. Recovery is a human inspection followed by a fresh
proposal. It is never a blind rollback or overwrite.

## Derived Audit Records

Every apply attempt that reaches `consuming` MUST emit an append-only derived
audit result. Audit persistence is part of authorization: if the server cannot
create and synchronize its pending audit entry before the source mutation, it
MUST refuse the write. The implementation must record a finalized outcome
after the atomic operation; a crash-recovery scan may mark an incomplete entry
as `indeterminate`, but must never claim success without verifying the final
checksum.

The audit journal belongs below a Git-ignored derived directory such as
`.pkm-index/writeback-audit/`, with owner-only permissions. It is not a source
of truth and its absence never grants permission. Entries are append-only to
the service account and include a monotonic sequence or chained previous-entry
digest so local tampering is detectable during review. Retention and export
are operator actions outside an apply request.

The journal head is additionally bound to an owner-only, HMAC-authenticated
checkpoint outside the journal directory. The checkpoint records the final
sequence, final entry digest, and immutable audit-lock identity. Every read,
append, and recovery verifies that boundary while holding that exact
cross-process lock. A missing, replaced, malformed, or mismatched checkpoint
is an audit failure; initialization or rotation is a deliberate operator setup
action and is never an apply-time repair. This prevents deleting valid final
JSONL entries from being misread as a shorter valid history.

Each entry contains only the minimum useful evidence:

- schema and policy versions, journal sequence, proposal fingerprint, and
  redacted proposal ID;
- operation, canonical relative target, selected allowed root, approval time,
  expiry, and outcome code;
- before/expected-after/observed-after checksums, changed path count, server
  instance, and error category; and
- audit-entry digest and previous-entry digest where applicable.

It MUST NOT contain approval tokens, full Markdown, full frontmatter values,
model prompts, environment variables, credentials, or an unredacted diff.
The user-visible preview remains in short-lived proposal state and is discarded
when that proposal reaches a terminal state, subject to ordinary local crash
recovery requirements.

## Failure Behavior

| Condition | Required result |
| --- | --- |
| Missing, malformed, expired, cancelled, or unapproved proposal | Refuse; no source mutation |
| Replayed or concurrent approval token | Refuse as consumed; no retry from stored proposal |
| Path traversal, path ambiguity, path/root policy failure, or link/special file | Refuse and record only non-sensitive error metadata if an apply was consuming |
| Target absent/present contrary to proposal, checksum mismatch, or changed file identity | Return `conflict`; do not write |
| Preview/fingerprint/operation/path does not match approved record | Refuse as tampered |
| Audit pending record cannot be made durable | Refuse before mutation |
| Atomic write, final checksum verification, or audit finalization fails | Return failed or indeterminate; consume proposal; require human inspection and a fresh proposal |
| Server restart, session loss/cancellation, or server/root/policy identity reload | Invalidate outstanding proposals; no automatic resume |
| Client disconnect or timeout | Do not continue an unconfirmed apply; terminal state is recorded if consumption already occurred |

Errors returned to an MCP client should be structured and avoid leaking
absolute paths, note contents, tokens, or raw internal exceptions. The server
may report a vault-relative target and a stable category such as `expired`,
`not_approved`, `replayed`, `policy_denied`, `conflict`, or `audit_unavailable`.

## Explicitly Out of Scope

This design does not authorize any write operation today. The following remain
out of scope for v0.8 and require a separate design, review, and approval:

- delete, trash, archive, purge, restore, rename, move, or overwrite of a
  source note;
- multi-file changes, migrations, bulk normalization, mass frontmatter edits,
  link rewriting, or directory creation/renames;
- modifications to vault configuration, plugins, assets, system documents,
  generated state, Git metadata, source code, scripts, environments, or file
  permissions;
- automatic writeback from retrieval, summaries, context packs, agents,
  automations, scheduled jobs, hooks, model output, or index maintenance;
- repair of malformed YAML, conflict auto-resolution, blind retry, rollback,
  or recovery that changes source Markdown; and
- remote approval, shared/delegated approval authority, cross-vault writes,
  network synchronization, credential handling, or model download.

Creating one new draft is not permission to overwrite an existing path: it
must use the explicit absent-target contract above. Future candidates such as
frontmatter updates, daily-note appends, and constrained patches must each
define their own operation-specific schema and tests before they can be
enabled.

## Required Implementation Evidence

Before a write tool is enabled, security-focused tests must cover at least:

- default deny and no write-tool exposure in the MCP tool list;
- every rejected path form, allowed-root escape, symlink/junction traversal,
  special-file target, denied-root case variant, and case/prefix ambiguity
  supported by the platform;
- unapproved, expired, cancelled, altered, cross-session, concurrent, and
  replayed proposals;
- exact preview/fingerprint binding, byte-level checksum conflict, absent-target
  create race, and final after-checksum verification;
- failure before source mutation when audit persistence is unavailable;
- cross-process recovery ownership/lock replacement, and retained-entry or
  final-tail truncation against the anchored audit boundary; and
- simulated interruption at each state transition, with no automatic retry or
  source-changing recovery.

The v0.8 exit gate in the worktree operating plan is satisfied only when these
tests demonstrate that an expired, altered, unapproved, out-of-vault, or
checksum-mismatched proposal cannot write, while an approved valid proposal
changes exactly the previewed bytes and leaves an auditable result.

## Review Checklist

Security review for a future implementation must answer all of the following
before enabling a tool:

1. Which single operation and exact allowed-root prefixes are requested, and
   why are broader roots unnecessary?
2. Does the target-resolution implementation reject links and prove containment
   after canonicalization on every supported platform?
3. Can an untrusted model or client obtain, alter, extend, or replay approval?
4. Does every apply revalidate the exact target bytes immediately before an
   atomic, same-filesystem change?
5. Does audit failure occur before mutation, and can audit review detect an
   interrupted or rewritten record without retaining note content?
6. Have all out-of-scope destructive and multi-file operations remained absent
   from MCP configuration, schemas, implementation, and tests?

Until all answers are affirmative and separately approved, CognitiveOS remains
read-only.
