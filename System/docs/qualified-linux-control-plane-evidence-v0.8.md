# Qualified Linux Control-Plane Evidence v0.8

## Status: BLOCKED — no qualified Linux execution in this worktree

This is the Issue #84 remediation and execution plan for the disconnected,
default-off canonical-root control-plane evidence in PR #82. The active
worktree host is **macOS 15.7.7 (Darwin 24.6.0, x86_64)**, not Linux. The
Linux-only tests therefore skip on this host. A skip is an explicit blocked
qualification gate; it is not Linux evidence and must not be summarized as a
pass.

The Issue #84 branch starts from `origin/main` and replays the unmerged PR #82
foundation so its draft pull request is self-contained. It remains a repair
candidate, not an integration or approval of the disconnected control plane.

## Declared Qualification Tuple

Only the following tuple may turn the Linux test results into *candidate*
qualification evidence:

| Dimension | Required value |
| --- | --- |
| Kernel | Linux `>= 6.1` |
| Architecture | `x86_64` |
| Python | CPython `3.12.x` |
| Filesystem | Local `ext4` for the disposable fixture tree; not overlay, tmpfs, NFS, FUSE, or a network mount |
| Namespace | An observable `/proc/self/ns/mnt` mount namespace, recorded with the test result |
| Account | A non-root local account, with the disposable fixture root mode `0700` and test files mode `0600` |
| Fixture scope | A newly created `TemporaryDirectory` only; no vault, private Markdown, assets, generated state, SQLite, model cache, credentials, KMS/HSM, policy, deployment, or environment mutation |

The tests enforce the operating system, kernel minimum, architecture, CPython
minor version, non-root account, ext4 temporary-directory mount, owner-only
directory mode, mount-namespace availability, and `O_NOFOLLOW`/
`O_DIRECTORY` availability before executing. Any mismatch is skipped with a
reason. A future reviewer must record the exact `uname -a`, CPython version,
filesystem type and mount point for the disposable directory, mount namespace
identifier, account UID, commit SHA, and command output next to the result.

The tuple is deliberately narrow. It does not qualify other filesystems,
containers, mount policies, distributions, kernels, architectures, users, or
deployment arrangements by resemblance.

## What the Disposable Tests Prove

`tests/test_qualified_linux_control_plane.py` and its test-only support module
run exclusively below a newly created temporary directory. They never import
an MCP server, `atomic_apply`, a writer, or `ApplyOutcome`, and do not modify
the shipped package code.

| Evidence area | Disposable Linux test behavior | Required refusal behavior |
| --- | --- | --- |
| Immutable local bootstrap provenance | Builds a frozen `ConfiguredVaultRootProvenance` from descriptor observations of a temporary root and `Notes` directory; a changed generation changes the provenance digest. | No current-directory, client root, environment, policy, or real-vault source is used. |
| No-follow containment | Walks each absolute root and target component using `openat`-style descriptor-relative `O_NOFOLLOW` operations and compares `fstat` to no-follow `stat(..., dir_fd=...)`. | Root and leaf symlink aliases return the controlled `QualifiedLinuxFixtureRefusal`, never a raw no-follow error; hard-link aliases, lexical `..`, component escapes, special types, and changed descriptor/path identities also refuse. |
| Namespace and device/inode binding | Reads only the process mount-namespace handle, hashes it to an opaque test identifier, and re-observes temporary-root and allowed-root device/inode values from the opened descriptors. | A replacement root that receives the original `Notes` directory is rejected as `root_identity_mismatch`; namespace or device/inode substitutions return the existing denial-only control-plane reason. |
| Alias and descriptor race | Creates only temporary symlink aliases and performs a controlled rename/replacement after a descriptor open. | The no-follow probe raises a failure before it can construct evidence. |
| Cross-process replay | Takes the cross-process lock before deciding whether a temporary record is abandoned, starts two independent `spawn` processes over one owner-only state file, then constructs a fresh reader after both exit. | Exactly one `consumed_default_off`, one `replayed`, and a fresh-reader `replayed`; a genuine post-crash orphan still refuses as `replay_state_unavailable`, and every result remains denied. |
| Crash/torn-write and lock replacement | Supplies malformed partial JSON, a controlled replacement of the locked path, and deterministic crash-shaped interruptions immediately after temporary-file `fsync`, `rename`, and directory `fsync`; each interruption reopens a fresh fixture reader. | A post-temporary-`fsync` orphan refuses as `replay_state_unavailable`; visible post-rename and post-directory-`fsync` records reopen as `replayed`; there is no repair, replay-state creation after lock replacement, or source write. |
| Expiry, rotation, revocation, session, and boot | Uses only synthetic opaque records and a fixed test clock. | Monotonic expiry, closed-session binding, changed key/revocation epochs, and changed server boot are refused before a replay claim. |

The replay fixture writes only capability IDs, public fingerprints, a schema
label, and an unkeyed integrity digest. It intentionally stores no proof,
source bytes, Markdown, token, credential, secret, or policy. Its state and
lock files are test-only; the fixture has no provisioning, discovery,
repair/recovery, rotation, revocation, authentication, or deployment path.

## Exact Linux Execution Procedure

Run from a clean disposable worktree at the reviewed commit, on the declared
tuple and non-root account:

```text
PYTHONPATH=src ./.venv/bin/python -W error -m unittest discover -s tests -p 'test_qualified_linux_control_plane.py' -v
PYTHONPATH=src ./.venv/bin/python -W error -m unittest discover -s tests -v
git diff --check
```

Before attaching the output to Issue #84, confirm that the focused suite did
not skip because of the tuple guard. Record the required host facts listed in
the tuple section. Do not use a macOS/POSIX result, a Docker overlay result,
or a root-account result as a substitute. Do not persist the temporary test
directory or copy any result into a vault or generated directory.

`PYTHONPATH=src` is process-local source selection for this non-editable
development environment; it neither writes nor changes an operator's persisted
environment. Do not install, rebuild, or activate an environment as part of
this evidence task.

## Current macOS Evidence

The current worktree can provide only this exact platform statement:

```text
ProductName: macOS
ProductVersion: 15.7.7
BuildVersion: 24G720
Darwin 24.6.0, x86_64
```

### 2026-07-22 diagnostic execution record

- Model record: `gpt-5.6-terra / xhigh`.
- Reviewed code commit: `ce69986484b8a79dadd34128e2f5ac34079f1c6c`.
- `uname -srm`: `Darwin 24.6.0 x86_64`; effective UID: `501`.
- Interpreter: CPython `3.14.6`, which does not meet the required CPython 3.12 tuple.
- The qualified-Linux command ran eight tests and skipped all eight with
  `requires the declared Linux control-plane tuple`.
- The warning-strict complete suite ran `193` tests successfully with `24`
  platform/capability skips; `git diff --check` succeeded.

The required local-ext4 mount evidence and `/proc/self/ns/mnt` namespace ID
do not exist on this macOS host and were not fabricated or inferred. This
diagnostic record is **BLOCKED** and contributes no Linux qualification.

No Linux descriptor, filesystem, mount namespace, process-lock, crash-safety,
or authenticated-session result was executed or inferred from this platform.
The qualification gate is therefore **BLOCKED**.

## Boundaries and Residual Risks

This evidence does not register MCP, expose a route, load a policy, issue or
authenticate a real owner capability, call a writer, integrate with
`atomic_apply`, return `ApplyOutcome.APPLIED`, access a vault/private/generated
path/SQLite database, use credentials/KMS/HSM/secrets, deploy anything, or
change the environment. The control-plane result remains either `default_off`
or `consumed_default_off`, and both are denials.

The test verifier is intentionally synthetic and cannot authenticate an owner
session. The fixture ledger demonstrates process and crash refusal behavior
only on the declared temporary ext4 tuple; it is not a production durable
replay store, does not provide tamper evidence, and cannot establish a real
session-ending or unique-boot lifecycle. A qualified Linux pass would narrow
the Issue #84 qualification gap but would still require a fresh independent security review
before any control-plane, replay-store, MCP, or writer integration.

## Gate Decision

**NO-GO for integration.** Keep all control-plane behavior disconnected and
default-off. The next action is to run the declared tuple in a dedicated Linux
worktree, attach exact output and platform facts to Issue #84, then request an
independent security review of the resulting evidence and residual risks.
