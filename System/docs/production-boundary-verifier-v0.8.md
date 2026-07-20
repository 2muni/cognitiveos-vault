# Deny-Only Production-Boundary Verifier Foundation v0.8

## Status

This document records the implementation contract introduced for Issue #72.
It is verification evidence only. It is not a production topology policy, a
key-custody configuration, an approval, a deployment plan, or permission to
enable writeback.

The implementation lives in `cognitiveos.production_boundary`. It is not
registered with MCP and has no dependency on `atomic_apply`, a writer, or a
write route. Its only public outcome is a structured denial. Even a complete
verification returns `deny_only` rather than an approval token, an apply
capability, or a filesystem action.

This keeps the implementation within the NO-GO decision in the Issue #71
authorization-boundary report and the no-write requirements in the
[Writeback Threat Model and Permission Boundary v0.8](writeback-threat-model-v0.8.md).

## Canonical Signed Topology Policy

The verifier accepts a detached `SignedTopologyPolicy` envelope containing
exact policy bytes, a signature, signer identity, and key epoch. The policy
bytes must be canonical JSON: UTF-8, sorted keys, compact separators, no
floating-point values, and no alternate serialization. The strict schema is
`production-boundary-policy/v1` and includes:

- signer identity and key epoch, which must equal the detached envelope;
- issued and expiry timestamps;
- an opaque, qualified Linux namespace identity;
- a topology anchor and its immediate parent, both pinned by device/inode;
- exact role paths, ancestry, kinds, device/inode identities, and link counts;
- a Trusted Owner Authority identity, audience, scope, key epoch, and minimum
  revocation epoch.

Signature verification is intentionally an opaque external interface. The
foundation has no signing key, key-service client, credential, rotation API, or
policy-provisioning path. Invalid, unavailable, revoked, rotated, malformed,
non-canonical, not-yet-valid, and expired policy evidence all deny.

## Disposable Linux-Style Topology Verification

For a supported Linux descriptor environment, the verifier reads only the
specified synthetic root using no-follow descriptor operations. It verifies:

- the anchor and immediate parent device/inode identities;
- exact closed-world directory entries derived from policy roles;
- role ancestry through pinned parent descriptors;
- regular-file/directory kinds, device identity, inode identity, and link
  count;
- rejection of symlinks, hard links, special files, unexpected entries, and
  descriptor substitution races.

The namespace identity arrives through another opaque read-only interface. A
missing, malformed, or mismatched value is a denial. Platform capability is
also default-deny: absent Linux no-follow/descriptor support denies rather
than falling back to path-based checks.

## Trusted Owner Authority Verification

`TrustedOwnerAuthorityVerifier` verifies an opaque `OwnerAttestation` after
the foundation independently binds it to the signed policy and topology. The
attestation must match the policy's authority ID, audience, scope, key epoch,
policy digest, topology digest, and the supplied proposal fingerprint. It is
also subject to strict timestamps and a minimum revocation epoch.

The external authority returns only one of the following verification states:
`verified`, `invalid`, `unavailable`, `revoked`, `replayed`, or `rotated`.
Every non-`verified` state is mapped to a stable denial reason. The interface
cannot issue an attestation, release a secret, consume a capability, rotate a
key, or alter revocation state. Replay recognition is therefore evidence for
future control-plane work, not a write authorization mechanism.

## Test Evidence

`tests/test_production_boundary_verifier.py` uses only an in-memory HMAC test
adapter and disposable temporary POSIX directories shaped like a minimal Linux
fixture. It covers:

- a fully verified fixture ending at `deny_only`;
- canonicality, signature, signer-envelope, expiry, and rotation/revocation
  denials for policy evidence;
- unsupported or unavailable namespace/platform evidence;
- unexpected entries, symlinks, hard links, special files, anchor replacement,
  and descriptor substitution;
- authority ID, audience, scope, proposal, policy, topology, key epoch,
  revocation epoch, timestamp, replay, rotation, outage, and proof failures;
- source-level absence of MCP, atomic-applier, outcome, and write-sink
  dependencies.

The fixtures never use a real vault, private note, asset, generated index,
SQLite database, model cache, credential, KMS/HSM, deployment, policy source,
or environment configuration.

## Residual Risks and Required Gates

This is not production enablement. The following remain required before any
control-plane or writer integration is considered:

1. Owner-approved production topology policy with managed key custody and
   independently qualified Linux mount/namespace/service tuple evidence.
2. A production Trusted Owner Authority that supplies authenticated proof,
   revocation, rotation, replay handling, durable availability behavior, and
   atomically consumable capability semantics outside this module.
3. A separately deployed default-off control plane, immutable policy loading,
   audit/monitoring/recovery controls, kill switch, and platform qualification.
4. Independent security review of the policy, authority, platform evidence,
   and complete v0.8 writeback matrix before a first narrow operation is even
   proposed for enablement.

Until those gates are approved, CognitiveOS remains read-only.
