# Canonical-Root Control Plane and Consumable Owner Authority v0.8

## Status

This document records the disconnected, default-off foundation for Issue #75.
It addresses the two high findings and the Linux-evidence qualification gap
identified by the independent review of Issue #74 / PR #73.

It is not an enabled writeback design. It does not load a production policy,
discover a vault root, issue an owner capability, register an MCP tool, expose
a route, open a target, or invoke a writer. The implementation in
`cognitiveos.control_plane` has no filesystem access and has no dependency on
the existing atomic application boundary. Its two successful states are still
denials:

- root evidence is `default_off`; and
- a one-time owner capability is `consumed_default_off`.

Neither state grants write authority. Independent security review is required
before any integration is proposed.

## Review Findings Addressed

Issue #74 found that PR #73 intentionally supplied a read-only owner-attestation
verifier, not an atomic consumer. It therefore could not prove a durable
one-time replay boundary, local owner-session binding, or server-instance
binding. It also accepted a caller-supplied root without immutable configured
vault-root provenance or component-safe allowed-root containment. Finally, its
temporary POSIX tests did not prove qualification of a Linux deployment tuple
or durable replay behavior across concurrent and restarted consumers.

This foundation adds contracts and synthetic evidence only:

1. An immutable `ConfiguredVaultRootProvenance` record pins the canonical
   configured root, configuration identity/generation, Linux namespace, root
   device/inode identity, and explicit non-root allowed prefixes.
2. `LinuxDescriptorEvidence` represents only evidence obtained by a future
   qualified Linux no-follow descriptor adapter. It binds the configured root,
   selected allowed root, target components, path spelling, identities, and a
   descriptor-race signal.
3. `TrustedOwnerAuthority` consumes a pre-issued opaque capability exactly once
   through a `DurableReplayLedger` contract after validating owner session,
   server instance and boot, root-provenance digest, key epoch, revocation
   epoch, wall deadline, monotonic deadline, and opaque proof.
4. The test suite has a disposable Linux-only replay fixture which uses a
   temporary, cross-process-locked and synchronized state file. It is proof of
   the contract shape, not a production state-store implementation.

## Canonical Configured-Root Provenance

The future bootstrap, not an MCP request or process working directory, must
create the provenance record exactly once per server boot. The record contains:

| Field | Required binding |
| --- | --- |
| `configuration_id`, `configuration_generation` | A stable external bootstrap identity; changed configuration requires a new server boot and a new provenance digest. |
| `canonical_root_path` | An absolute NFC POSIX spelling. Relative paths, `.`/`..`, duplicate leading separators, backslashes, NUL, and noncanonical spellings are rejected. |
| `namespace_id` | An opaque identifier for the separately qualified Linux namespace/mount/service tuple. |
| `root_identity` | Device/inode identity observed for the canonical root through a no-follow descriptor flow. |
| `allowed_roots` | Non-empty, explicitly configured vault-relative component sequences, each with an ID and pinned identity. The vault root itself and overlapping prefixes are invalid. |

The module computes a canonical SHA-256 digest over all of these fields. A
future capability is bound to that digest, never to a mutable path string.
There is no fallback to `cwd`, an environment variable, an index path, a
client-provided root, or a policy file.

The `LinuxDescriptorEvidence` adapter contract must return the exact configured
canonical root spelling as both its requested and canonical spelling. A symlink
alias, lexical alternative, case-changing alias, or lookup that resolves to a
different spelling is refused. The evidence must contain the same namespace and
root identity and must fail closed when it observes a descriptor substitution
race.

Containment is component-based. The selected allowed-root ID must name one
pinned configured prefix, its observed identity must match, and the target
components must begin with that exact component sequence. Thus `Notes-private`
does not satisfy an allowed `Notes` prefix. The evidence's canonical target
path must equal the path mechanically derived from the configured root and
components; it may not contain aliases or parent traversal.

Even exact evidence returns `default_off`. This step neither opens the target
nor checks whether it is a Markdown file. Target resolution, links, special
files, atomic replacement, and audit sequencing remain outside this module.

## Atomically Consumable Trusted Owner Authority

The authority does not issue a capability. An external trusted owner surface
will eventually issue an opaque `TrustedOwnerCapability`; this foundation only
defines safe consumption of one. Its public fields bind:

- authority ID, exact key epoch, and exact revocation epoch;
- owner-session ID;
- server-instance ID and server-boot ID;
- configured-root provenance digest;
- issuance and expiry timestamps plus server-boot monotonic issued/deadline
  values; and
- a digest committing the record to the opaque proof without retaining the
  proof in replay state.

The runtime supplies its own owner session, server instance, boot identity,
root-provenance digest, current key epoch, revocation epoch, wall clock, and
monotonic clock. The client supplies none of these time values. A different
owner session, server instance, provenance digest, key epoch, or revocation
epoch refuses before the proof verifier or replay ledger is called. A changed
server-boot ID produces `server_restarted`, invalidating pre-restart authority.

Both deadlines are required. The wall deadline fails safely if the wall clock
moves forward; the monotonic deadline prevents a clock rollback from extending
authority. Capabilities may last no longer than ten minutes.

The opaque proof verifier can only return `valid`, `invalid`, or
`unavailable`. It has no issuance, secret retrieval, rotation, revocation, or
state-mutating method. An unavailable or invalid proof refuses before replay
state is touched.

After validation, the consumer makes one `ReplayClaim` containing only the
capability ID, public capability fingerprint, authority ID, server bindings,
and root-provenance digest. The proof is not part of a claim. The ledger must
perform the following transition atomically and durably:

```text
unseen capability ID + fingerprint -> consumed durable record
same capability ID + fingerprint   -> replayed
same capability ID + other digest  -> collision
unreadable/unlockable/unsyncable state -> unavailable
```

The durable record must exist before `consumed_default_off` is returned. A
crash, restart, malformed state, lock failure, write failure, truncation, or
repair attempt cannot recreate or retry an unconsumed capability; it must fail
closed. A production adapter must document owner-only storage permissions,
cross-process locking or equivalent transactional isolation, durable commit,
recovery behavior, and tamper-evidence. The fixture adapter is expressly not
such an implementation.

The only successful result, `consumed_default_off`, ends the method. There is
no callback, returned token, future writer handoff, or retry path. Therefore a
future integration must separately establish an authorization-to-operation
boundary after independent review; this record alone is not suitable for one.

## Synthetic Linux Evidence

Focused tests use no real vault, Markdown, Assets, generated index, database,
model cache, credential, key service, deployment, policy source, or environment
configuration. They construct synthetic descriptor evidence and use only
disposable `TemporaryDirectory` paths for the Linux-specific fixtures.

The suite covers:

- canonical root evidence that still ends at `default_off`;
- rejection of relative roots, overlapping allowed prefixes, aliases,
  noncanonical targets, component-prefix confusion, root escapes, changed
  allowed-root identity, namespace mismatch, unsupported platform, and a
  descriptor-race signal;
- one-time consumption with no proof copied into the replay claim;
- concurrent consumers receiving exactly one `consumed_default_off` and one
  `replayed` result;
- session, server, root, rotation, revocation, expiry, proof, and restart
  refusals before consumption;
- monotonic expiry despite a rolled-back wall clock; and
- on Linux only, a fresh replay-ledger reader after a durable fixture commit
  refusing the same capability, plus a new server boot refusing the old
  capability.

The Linux-only tests skip on unsupported hosts rather than treating POSIX or
macOS behavior as Linux platform qualification. They demonstrate the required
contract shape but do not qualify a real kernel, filesystem, mount, namespace,
or service-account tuple.

## Explicit Non-Go Boundaries

The following are prohibited by this change and remain absent:

- MCP tool registration, writer routes, or any application of a write result;
- integration with the existing atomic application module or writeback code;
- actual-vault, private Markdown, Assets, generated-index, SQLite, or model
  cache access;
- production policy/configuration loading, environment reads, credentials,
  KMS/HSM access, secret handling, deployment, or operator configuration;
- root discovery from client input, current working directory, or an alias;
- a production durable replay store, owner-capability issuer, key-rotation
  endpoint, revocation endpoint, or remote approval service; and
- applying, retrying, repairing, rolling back, or otherwise mutating a source
  file.

## Required Review Before Integration

An independent security review must answer all of the following before even a
disconnected control-plane deployment is considered:

1. What immutable bootstrap source establishes the configured canonical root,
   allowed prefixes, namespace/mount/service tuple, and descriptor identities?
2. Does the Linux adapter prove no-follow descriptor containment and race
   handling on every intended kernel/filesystem combination?
3. Which owner-authentication mechanism issues the opaque proof, and how does
   it authenticate a local owner session without exposing a signing secret to
   the consumer?
4. Does the production replay state implement durable atomic consumption,
   restart refusal, collision detection, locking/transaction isolation,
   integrity checks, and unrecoverable failure behavior?
5. Can configuration change, rotation, revocation, restart, process
   concurrency, and host clock changes only narrow authority?
6. Has the disconnected result remained non-actionable in every import path,
   server configuration, tool list, and test?

Until every answer is independently approved together with a narrow operation
proposal, CognitiveOS remains read-only.
