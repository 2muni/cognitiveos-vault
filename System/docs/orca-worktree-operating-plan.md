# CognitiveOS Goal and Orca Worktree Operating Plan

## Status

Canonical operating plan adopted on 2026-07-18 after publication of
`v0.5.0`. This document is the starting point for future work performed in
Orca IDE. Historical release plans remain evidence of completed work; this
document owns the current objective, future sequence, worktree taxonomy, and
integration gates.

The primary `main` checkout is the trusted integration baseline. Except for an
explicitly approved hotfix or integration update, implementation work must be
performed in a dedicated Orca worktree created from the current
`origin/main`.

## Final Goal

CognitiveOS will be a local-first personal knowledge operating system in which:

- Markdown notes remain the durable, portable source of truth
- YAML frontmatter and internal links form an explicit machine-readable contract
- lexical, graph, embedding, summary, and agent state remain disposable and
  rebuildable
- retrieval and generated answers cite vault-relative evidence
- capture, synthesis, and maintenance workflows help knowledge compound over
  time without silently rewriting the user's meaning
- optional semantic retrieval works offline and falls back safely to lexical
  retrieval
- every write is proposed, previewed, explicitly approved, checksum-verified,
  atomically applied, and auditable
- the system remains usable across supported devices without making a cloud
  database, a model provider, or an IDE the source of truth

The finite `v1.0` completion boundary is a stable read-and-approved-write
system with reproducible setup, observable derived-state freshness, grounded
retrieval, safe authoring assistance, and a documented cross-device recovery
path. Autonomous destructive changes, background model downloads, and a graph
database are not required for `v1.0`.

## Completed Baseline

| Release | Completed boundary |
| --- | --- |
| `v0.1.0` | Markdown ingestion, SQLite/FTS, read-only MCP, retrieval safety |
| `v0.2.0` | token-budgeted context packs and deterministic text/JSON contracts |
| `v0.3.0` | optional local embeddings, hybrid retrieval, pinned model evaluation |
| `v0.4.0` | note contracts, durable templates, aliases, backlinks, typed graph edges |
| `v0.5.0` | deterministic manifests, unified status, atomic full/incremental indexes |

Current invariant:

- package and MCP version: `0.5.0`
- latest stable release: `v0.5.0`
- MCP surface: exactly nine read-only tools
- default semantic runtime: `off`
- writeback: disabled
- Markdown and frontmatter: never changed by indexing, status, or retrieval
- private note synchronization: separate from Git

## Roadmap to v1.0

### Phase A: v0.6 Worktree-native Operations

Purpose: make parallel development reproducible before adding a write surface.

Planned outcomes:

- Orca worktree setup and task taxonomy adopted by all implementation work
- continuous integration for supported default and local-embedding runtimes
- automated package, MCP-surface, privacy, and deterministic-build gates
- a single release-candidate checklist generated from executable checks
- fresh-clone and public-wheel consumer smoke tests that can run without vault
  content
- explicit policy for which local runtime and derived artifacts may be shared
  across worktrees

Exit gate: two independent clean worktrees produce the same test and package
results without sharing a SQLite index, private note, model cache path, or
Python virtual environment.

### Phase B: v0.7 Retrieval Quality and Knowledge Operations

Purpose: improve usefulness using measured, grounded behavior rather than more
storage layers.

Planned outcomes:

- larger privacy-safe Korean, English, and mixed-language evaluation fixtures
- evaluation of aliases, backlinks, typed links, recency, and graph signals
- query diagnostics that explain lexical, semantic, and reranking contributions
- stable workflows for capture, durable-note promotion, source synthesis, MOC
  maintenance, and review queues
- evidence-density and context-pack quality gates

Exit gate: retrieval and context changes demonstrate non-regression on frozen
fixtures, preserve deterministic output where promised, and never require the
optional model for the default path.

### Phase C: v0.8 Approval-gated Writeback Foundation

Purpose: introduce the smallest useful write capability without weakening the
Markdown source-of-truth boundary.

Required sequence:

1. threat model and permission review
2. proposal schema and exact diff preview
3. explicit approval token bound to one proposal
4. checksum revalidation immediately before apply
5. atomic single-file apply and append-only derived audit record
6. recovery, conflict, and stale-proposal tests
7. one write tool at a time, beginning with the least destructive candidate

Initial candidates remain `create_draft_note`, `update_properties`,
`append_to_daily`, and `apply_patch_to_note`. Multi-file migrations, bulk
normalization, rename, archive, and delete remain outside this phase.

Exit gate: an expired, altered, unapproved, out-of-vault, or checksum-mismatched
proposal cannot write; an approved valid proposal produces exactly the
previewed change and an auditable result.

### Phase D: v0.9 Portability and Recovery

Purpose: prove that CognitiveOS is an operating system for knowledge rather
than a configuration tied to one machine.

Planned outcomes:

- macOS and Windows bootstrap verification on supported Python combinations
- private-note sync and Git sync recovery runbook
- rebuild-from-Markdown disaster recovery
- client/MCP discovery diagnostics separated from server health
- upgrade and rollback checks across stable releases

Exit gate: a fresh supported device can restore private Markdown separately,
install a released package, rebuild disposable state, and verify the same
read/write safety contracts.

### Phase E: v1.0 Stabilization

Purpose: freeze the public contracts that define the useful, safe system.

Release gates:

- all v0.6-v0.9 exit gates complete
- no autonomous destructive operation
- read-only operation remains fully functional with semantic runtime disabled
- approved writeback is opt-in and auditable
- package, source archive, MCP schemas, note contracts, and operator docs agree
- actual-vault validation preserves private Markdown checksums
- clean-worktree and public-asset consumer verification pass

## Orca Worktree Taxonomy

Create each task from the latest `origin/main`. Use one worktree, one branch,
and one primary objective per task.

| Lane | Branch pattern | Typical work | Model tier |
| --- | --- | --- | --- |
| Documentation | `codex/docs-<topic>` | guides, examples, status records | `gpt-5.6-terra / low` |
| Maintenance | `codex/fix-<topic>` | narrow defects, packaging, compatibility | `gpt-5.6-terra / low` |
| Feature | `codex/feature-<topic>` | normal service or CLI capability | `gpt-5.6-terra / medium` |
| Retrieval | `codex/retrieval-<topic>` | indexing, ranking, context, evaluation | `gpt-5.6-terra / medium` |
| Schema | `codex/schema-<topic>` | note/index/MCP contract evolution | `gpt-5.6-terra / high` |
| Security | `codex/security-<topic>` | permission and writeback boundaries | `gpt-5.6-terra / high`, `xhigh`, or `max` |
| Release | `codex/release-<version>` | stabilization, packaging, publication | `gpt-5.6-terra / medium` |

Task names should describe the outcome, not the agent or session. Examples:

- `codex/feature-ci-release-gates`
- `codex/retrieval-context-evaluation`
- `codex/security-writeback-proposals`
- `codex/release-v0.6.0`

## Worktree Lifecycle in Orca

1. Refresh the primary checkout and confirm `main == origin/main` and clean.
2. Create a new Orca worktree from `origin/main` with a name matching the lane.
3. Review and trust `orca.yaml` only when its diff is understood.
4. Let the setup hook create the worktree-local `.venv` and install
   `.[dev,mcp]`.
5. Run the agent/MCP startup preflight below before submitting the task brief.
   A worktree created with `--setup skip` is not eligible for an MCP-backed
   implementation task until its environment is installed and import-verified.
6. Require the setup hook to verify host-level GitHub authentication with
   `gh auth status --hostname github.com` and initialize the Git credential
   helper with `gh auth setup-git`. Then require the agent-runtime preflight
   invoked by `scripts/run-orca-codex.sh` to pass before the terminal can
   accept the task prompt. Do not copy tokens into the worktree.
7. Put the objective, scope, excluded work, completion gates, and model tier in
   the worktree task description before implementation.
8. Inspect the current contracts and tests before editing.
9. Implement the smallest independently reviewable unit.
10. Run focused checks, then the lane's required regression gates.
11. Review the Orca diff and checkpoint the verified state.
12. Commit intentionally, push the task branch, and open a draft pull request.
13. Resolve review and CI in the same worktree.
14. Merge only when the branch is current with `main` and all gates pass.
15. Close the worktree only after verifying there are no uncommitted or
    untracked files. Stop any live terminals, then remove completed disposable
    worktrees with `orca worktree rm --worktree id:<repoId>::<path> --force
    --json`; archive a worktree instead when its review, recovery, or audit
    context must remain available. Keep the remote branch only when repository
    policy requires it.
16. Confirm the cleanup with `orca worktree list --json` and `git worktree
    list --porcelain`. The completed worktree must no longer be registered,
    while the primary `main` worktree remains present and clean.

Before removal, record any required durable decision or release evidence in
the pull request or `System/docs`; terminal scrollback and a disposable
worktree are not durable records. Never use cleanup to discard uncommitted
work: commit it, preserve it in an archived worktree, or obtain explicit
approval to delete it.

For competing implementations, create separate disposable worktrees and select
one winner. Do not merge two alternatives merely because both exist.

## Isolation and Concurrency Rules

- Never edit implementation directly in the primary `main` checkout.
- Never share `.venv`, `.venv-*`, `.pkm-index`, SQLite sidecars, test output,
  or build directories between worktrees.
- Never copy private Markdown into a temporary or remote worktree.
- Model caches may be read from the host only after the task explicitly permits
  local-model evaluation; do not commit or expose their paths.
- Only one active worktree may perform actual-vault embedding rebuilds or final
  release publication at a time.
- Only one active worktree may own a given schema or canonical roadmap file.
- Parallel worktrees must have disjoint primary files or an explicit dependency
  order.
- A dependent task starts from the merged predecessor, not from an unpublished
  sibling branch, unless a temporary stacked branch is explicitly documented.
- Worktree setup must not build indexes, download models, contact model APIs,
  synchronize notes, or enable writeback.

## Agent and MCP Startup Preflight

The worktree setup hook and the MCP server have separate responsibilities. The
hook prepares the child environment; the MCP server starts only after that
environment is proven usable. A model header alone does not prove that the
agent is executing the task.

For each child worktree that will run a Codex agent:

1. Use the setup hook, or an explicitly approved equivalent, to create the
   local `.venv` and install `.[dev,mcp]`. Do not use `--setup skip` for an
   MCP-backed implementation task.
2. Verify `<worktree>/.venv/bin/python` exists and can import `cognitiveos`.
3. When the GitHub-authenticated security launcher is required, execute
   `scripts/run-orca-codex.sh gpt-5.6-terra high` directly (never through a
   bare `bash`). It accepts only that reviewed combination; its required
   agent-runtime GitHub preflight must pass before `exec codex`. For other
   controls, retain the documented task-tier selection; then verify the
   header.
4. Verify that the terminal progresses beyond MCP initialization and emits a
   repository inspection or progress event.
5. Treat `ModuleNotFoundError`, fallback to system Python, MCP handshake
   closure, `initialize response` failure, or a repeated startup loop as a
   preflight failure. Stop the terminal and repair or recreate the environment;
   never leave the task prompt queued while retrying the same failed startup.

The observed failure mode was a worktree created with `--setup skip`: it had
neither `.venv` nor `.venv-embeddings312`, fell back to system Python 3.9.6,
could not import `cognitiveos`, and repeatedly failed the MCP handshake before
the implementation prompt was processed. Record such failures in the Orca
workspace comment and resume only after the preflight passes.

### GitHub authentication preflight

GitHub authentication is host-level state, not worktree state. Both gates below
must pass before a task prompt is submitted; setup success alone is not enough
because credentials or remote access can change before the terminal starts.

The setup hook verifies the initial host state:

```text
gh auth status --hostname github.com
gh auth setup-git
```

Immediately before `exec codex`, `scripts/run-orca-codex.sh` runs
`scripts/verify-github-agent-auth.sh`. The agent-runtime gate must repeat the
authentication and credential-helper checks, verify `git ls-remote origin HEAD`,
and make a read-only GitHub API request. On failure it exits nonzero before
Codex starts and emits an actionable category plus safe context limited to
hostname, account, and status; it must never print a token.

The security launcher uses fixed `/bin/bash -p` and `/usr/bin/env` paths, so a
worktree-controlled `PATH`, Bash startup file, or imported function cannot
select its outer shell or alter path resolution before preflight. It resolves
its sibling preflight from the canonical launcher path, clears only Bash
startup and imported-function variables for the preflight child process, and
preserves the host GitHub and Git credential environment. The gate resolves
`gh`, `git`, and Codex with PATH-only lookup from fixed host-managed locations,
then verifies their physical paths remain under a trusted host root. It does
not honor executable override environment variables or the worktree's `PATH`;
tests use an in-process shell-function seam that the executed launcher cannot
access.

If either gate fails, stop and instruct the operator to run
`gh auth login --hostname github.com` once on the host. Neither gate may copy
tokens or create credential files inside the worktree. This prevents a
sub-workspace from discovering expired or missing GitHub authorization only
when it attempts to push, create a PR, or post a review report.

## Required Task Brief

Every Orca task should begin with this compact contract:

```text
Objective:
In scope:
Out of scope:
Source contracts to preserve:
Files expected to change:
Tests and completion gates:
Privacy/writeback impact:
Dependencies:
Recommended model tier:
```

If the objective or safety boundary changes materially, update the brief before
continuing. Record important intermediate decisions as worktree checkpoints;
durable architecture and release decisions belong in `System/docs`.

## Lane-specific Completion Gates

### Documentation

- links, versions, tool counts, and commands match current implementation
- `git diff --check` passes
- no private path, note content, credential, or mutable local count is used as
  a universal requirement

### Code and Retrieval

- focused tests and the complete automated suite pass
- deterministic contracts are repeated with identical input
- path traversal and out-of-vault access remain rejected
- default lexical-only behavior remains available
- source Markdown checksums are unchanged

### Schema and Security

- design and compatibility notes precede implementation
- malformed, stale, replayed, and adversarial inputs have explicit tests
- no new write capability is enabled by default
- a separate security review approves the final boundary

### Release

- exact commit verified in a detached clean worktree
- supported runtimes pass with warnings promoted to errors
- wheel and source distribution contain no private or derived artifacts
- MCP version and tool surface match documentation
- actual-vault checks preserve private Markdown digests
- immutable tag and public assets are verified after download

## Orca Project Configuration

The repository `orca.yaml` contains only reviewed, local project defaults:

- a setup hook that creates a worktree-local default development environment
- terminal tabs for tests, read-only status, and Git status
- no archive hook
- no cloud environment recipe
- no credential, token, private path, model download, index build, or writeback

The setup hook is intentionally safe to rerun. It installs only the default
development and MCP extras. The optional local-embedding runtime remains an
explicit task action because it has platform-specific dependencies and may use
a large local model cache.

## Decision Authority

- `AGENTS.md`: mandatory agent and safety behavior
- this document: current goal, sequencing, worktree operation, and v1.0 gates
- versioned roadmaps and release notes: historical implementation evidence
- architecture and schema documents: durable public contracts
- worktree task briefs and checkpoints: temporary execution state

When these disagree, stop implementation and reconcile the durable documents
in a dedicated documentation or schema worktree before proceeding.
