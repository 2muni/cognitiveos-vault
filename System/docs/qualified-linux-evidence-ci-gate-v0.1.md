# Qualified Linux Evidence CI Gate v0.1

## Status

Issue #86 adds a separate, evidence-producing GitHub Actions job for the
qualified-Linux control-plane suite. It is deliberately not a replacement for
the default-runtime or local-embedding jobs: those generic Ubuntu regressions
cannot establish the narrow Linux qualification tuple.

The job is currently a documented stacked dependency on the unmerged qualified
control-plane suite in PR #85. Until
`tests/test_qualified_linux_control_plane.py` is present, the gate records a
durable `FAILED` result rather than silently running generic discovery. The
Issue #86 draft must be rebased onto that dependency, or the dependency merged
to `main`, before it can become a green integration candidate.

## Declared Tuple

Only a result with every value below may have `status=QUALIFIED`:

| Dimension | Required value |
| --- | --- |
| Operating system and kernel | Linux `>= 6.1` |
| Architecture | `x86_64` |
| Interpreter | CPython `3.12.x` |
| Account | Non-root effective UID |
| Fixture filesystem | A disposable `mktemp` directory on a local `/dev/*` `ext4` mount |
| Namespace | A readable `/proc/self/ns/mnt` mount namespace |
| PR-head provenance | `EXPECTED_PR_HEAD_SHA`, `GITHUB_SHA`, and `git rev-parse HEAD` are the same exact commit SHA |
| Test command | `PYTHONPATH=src <Python 3.12> -W error -m unittest discover -s tests -p 'test_qualified_linux_control_plane.py' -v` |

The job runs on `ubuntu-24.04` with the setup-python `3.12` toolchain, but it
does not infer qualification from the runner label. The gate reads the actual
kernel, architecture, UID, interpreter, mount namespace, and disposable
directory mount before it executes the suite.

The expected SHA is never inferred from the checkout. For a `pull_request`
run, the workflow supplies the event's immutable `pull_request.head.sha`. For
a direct `workflow_dispatch` run, the operator must supply the same explicit
PR-head SHA through `expected_pr_head_sha` and dispatch the workflow at that
commit. `GITHUB_SHA` and the checked-out `HEAD` must both equal that expected
value before the suite may run.

GitHub's normal pull-request execution uses a synthetic merge ref for
`GITHUB_SHA`. That execution deliberately records `BLOCKED`, even if the host
tuple and suite would otherwise pass: a merge-ref result is not PR-head
evidence. A matching direct workflow execution remains eligible to produce
evidence; missing or mismatched provenance is never repaired by falling back
to the checkout SHA.

## Evidence Artifact

Every execution uploads the `qualified-linux-evidence` artifact, even when a
tuple guard or the suite fails. It contains:

- `qualified-linux-evidence.txt`, recording the schema, expected PR-head SHA,
  `GITHUB_SHA`, checked-out SHA, `uname -a`, UID, Python identity, filesystem
  and mount, mount namespace, exact command, status, and the complete suite
  output; and
- `qualified-linux-suite-output.txt`, the unaltered focused-suite output (or
  the explicit blocked/failure message when execution was not allowed).

The artifact is durable CI evidence, not a repository artifact. It contains no
temporary fixture tree, vault note, private Markdown, generated index, SQLite
database, credentials, policy, deployment configuration, or filesystem source
content.

## Closed Failure Semantics

The script has three mutually exclusive outcomes:

| Status | Exit code | Meaning |
| --- | --- | --- |
| `QUALIFIED` | `0` | The tuple matched and the exact focused suite passed with no skips. |
| `BLOCKED` | `2` | The host did not meet a tuple guard. No suite is executed and no Linux evidence is claimed. |
| `FAILED` | `1` | The suite was absent, failed, or skipped after the tuple passed. This is not a blocked-host substitute. |

macOS, a Linux kernel older than 6.1, non-`x86_64` machines, CPython versions
other than 3.12, root accounts, unavailable mount namespaces, overlay/tmpfs/
network mounts, and non-local filesystems remain `BLOCKED`. The workflow does
not convert any of those states into a generic-test pass or a qualified claim.
An unavailable expected SHA, a PR merge ref, or any mismatch among expected,
`GITHUB_SHA`, and checked-out `HEAD` is also `BLOCKED`; the focused suite does
not run in those cases.

The focused suite remains diagnostic-only and default-off. This gate does not
add an MCP tool, a writer, a policy source, vault discovery, credentials,
deployment, generated-state access, or any writeback capability. Independent
security review is requested only after a reviewable commit has produced a
`QUALIFIED` artifact on the exact tuple.
