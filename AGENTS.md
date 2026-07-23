# CognitiveOS Vault Agent Guide

This repository is an Obsidian vault and the Markdown files are the source of truth. Treat generated indices, embeddings, graph projections, summaries, and MCP caches as derived artifacts.

## Codex Model Selection

Use only the official Codex model IDs documented in the current Codex manual. Do
not translate the project's historical `Sol`/`Terra` labels into invented model
IDs such as `gpt-5.6-sol`, and do not pass `light` as a reasoning effort. The
project default is pinned in `.codex/config.toml` for cost-efficient work; a
task may explicitly select the stronger official model when its tier requires
it.

Account-compatible model ID for Orca terminal commands in this project:

- `gpt-5.6-terra`: the currently supported Codex model for this ChatGPT account

Do not pass `gpt-5.6`, `gpt-5.3-codex-spark`, or any historical/invented model
ID in this project. The ChatGPT account rejects `gpt-5.6` with an invalid-model
400 error. If account capabilities change, verify the official Codex manual
and update the launcher allowlist before using another ID.

Supported `model_reasoning_effort` values are `none`, `minimal`, `low`,
`medium`, `high`, `xhigh`, `max`, and `ultra`, subject to account/model
availability. Use `minimal` or `low` for cost-efficient Terra tasks, and never
use the unsupported value `light`.

When launching an Orca Codex terminal, use the exact command form below and
select the model from this table—not the historical tier label:

```text
codex --model gpt-5.6-terra -c model_reasoning_effort="low"
codex --model gpt-5.6-terra -c model_reasoning_effort="high"
```

For Orca worktrees, prefer the repository launcher so an omitted or invalid
model/effort cannot silently fall back to the client default:

```text
bash scripts/run-orca-codex.sh gpt-5.6-terra low
bash scripts/run-orca-codex.sh gpt-5.6-terra high
```

The launcher requires both values, validates them against the supported IDs
and effort values above, and should be passed to
`orca terminal create --command`. After launch, verify the terminal header
shows the same model and effort before sending the task brief. Never use a
bare `codex` or `orca worktree create --agent codex` for a tier-sensitive task.

Task tier mapping:

- `gpt-5.6-terra / low`: UI checks, status checks, small documentation edits, and routine Git operations
- `gpt-5.6-terra / low`: narrow implementation, focused tests, and small bug fixes
- `gpt-5.6-terra / medium`: normal feature work, environment migration, retrieval changes, and release stabilization
- `gpt-5.6-terra / high`: architecture, schema evolution, writeback design, and security review
- `gpt-5.6-terra / xhigh` or `max`: high-impact migrations, authorization boundary changes, destructive-operation design, and incident analysis

Before every Orca handoff, record the exact model ID and reasoning value in the
task brief. If a model launch returns an invalid-model or invalid-effort error,
stop, consult this section, and retry only with an exact documented value.

At the end of every completed task, report the next recommended task and its recommended tier.

## Orca Worktree Workflow

Future implementation is worktree-native. The primary `main` checkout is the
clean integration baseline, not a general development workspace.

- Create each task in Orca from the latest `origin/main`.
- Use one objective per worktree and a `codex/<lane>-<topic>` branch.
- Use the lane, model tier, task brief, and completion gates defined in
  `System/docs/orca-worktree-operating-plan.md`.
- Never share `.venv*`, `.pkm-index`, SQLite files, build output, or private
  Markdown between worktrees.
- Use draft pull requests for review and merge only after the branch is current
  with `main` and all required gates pass.
- Do not modify `main` directly except for an explicitly approved integration
  update or emergency hotfix.
- Review `orca.yaml` before trusting its hooks. The repository setup hook may
  create a local development environment, but it must not build indexes,
  download models, synchronize notes, or enable writeback.
- Never create an implementation worktree with `--setup skip` when its agent
  will use the CognitiveOS MCP server. Before launching the agent, require the
  worktree-local `.venv` and verify that its selected Python can import
  `cognitiveos` and start `scripts/run-cognitiveos-mcp.sh` through a successful
  MCP handshake. If the preflight fails, mark the workspace blocked and repair
  or recreate its environment before submitting the task; do not leave a
  prompt queued behind repeated MCP startup retries.
- A valid model header is not evidence that a task has started. After the
  model/effort check, also verify that the agent has progressed past MCP
  initialization and produced a repository inspection or progress event.
- Treat GitHub authentication as two required host-level gates before prompt
  submission. The setup hook must verify `gh auth status --hostname github.com`
  and run `gh auth setup-git`; immediately before `exec codex`,
  `scripts/run-orca-codex.sh` must run
  `scripts/verify-github-agent-auth.sh`. The agent-runtime gate repeats those
  checks, verifies `git ls-remote origin HEAD`, and makes a read-only GitHub API
  request. Credentials remain host-level and must never be copied into a
  worktree or written to credential files. If either gate fails, stop and
  require `gh auth login --hostname github.com` before resuming.

## Vault Safety

- Prefer read-only analysis unless the user explicitly asks for file changes.
- Do not bulk rewrite notes, rename folders, or migrate frontmatter without an explicit plan and approval.
- Do not delete notes or assets unless the user explicitly asks for deletion.
- Treat `Assets/`, `.obsidian/`, and any generated index folders as sensitive operational areas.
- Preserve user-authored prose and links unless the requested change requires editing them.

## PKM Data Rules

- Markdown notes are durable records.
- YAML frontmatter is the machine-readable contract.
- Folder location is operational context, not the only source of meaning.
- Internal links express semantic relationships.
- References and personal synthesis should remain separable.

## MCP Implementation Rules

Start with read-only MCP capabilities:

- `search_notes`
- `read_note`
- `get_backlinks`
- `suggest_links`
- `summarize_source`
- `propose_moc`

Require explicit user approval for tools that write to the vault:

- `create_draft_note`
- `update_properties`
- `append_to_daily`
- any migration, rename, delete, or bulk normalization operation

MCP roots must be restricted to this vault. Reject path traversal and absolute paths outside the vault.

## Retrieval Rules

Prefer hybrid retrieval:

1. Scope by metadata and path.
2. Search with keyword or FTS.
3. Search with embeddings.
4. Rerank using title, headings, backlinks, freshness, and confidence.
5. Return note paths and evidence with generated answers.

Avoid presenting model inference as vault fact unless it is grounded in retrieved notes.

## Device Portability

- Prefer platform-neutral Python commands in documentation and tests.
- Use `scripts/run-cognitiveos-mcp.sh` on macOS and `scripts/run-cognitiveos-mcp.ps1` on Windows.
- Keep private note synchronization separate from Git repository synchronization.

### Orca MCP startup preflight

For every new worktree that will start a Codex agent, run the following checks
before submitting the task brief. These checks are read-only and must target
the child worktree, never `main`:

```text
test -x <worktree>/.venv/bin/python
<worktree>/.venv/bin/python -c 'import cognitiveos; print(cognitiveos.__version__)'
```

Then start the terminal with the fixed launcher and verify both the model header
and an MCP-ready/progress event. A missing `.venv`, a system Python fallback,
`ModuleNotFoundError`, `initialize response`/handshake closure, or a terminal
that remains in MCP startup for more than a short bounded interval is a
preflight failure. Stop the terminal, record the failure in Orca, and do not
retry the same queued prompt indefinitely. The setup hook must be rerun or the
worktree recreated with the required environment before implementation starts.
