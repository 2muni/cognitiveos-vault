# CognitiveOS Intel Mac Handoff v0.1

## Purpose

This is the canonical continuation guide for moving CognitiveOS development from the original Windows workspace to an Intel Mac without losing project context.

## Handoff State

Prepared on 2026-07-10 from `main` after the public `v0.1.0` GitHub Release was published.

Repository:

```text
https://github.com/2muni/cognitiveos-vault.git
```

Stable release:

```text
v0.1.0
```

The release tag points to commit `578882d`. Release notes were added later on `main`, beginning with commit `bfffc11`. Do not move the published tag.

Current implementation boundary:

- read-only Markdown ingestion is complete
- SQLite/FTS indexing is complete
- nine read-only MCP tools are complete
- deterministic source summaries and context packs are complete
- writeback permission design is complete
- writeback implementation remains disabled
- vector search, graph storage, and local LLM calls remain deferred

## Two Separate Sync Channels

Git and private vault content have intentionally different responsibilities.

Git carries:

- source code
- tests and fixtures
- architecture and decision documents
- canonical templates
- Codex and MCP project configuration
- release and roadmap documents

Git does not carry:

- personal notes under `00_Inbox` through `06_Maps`
- files under `Assets`
- `.obsidian` local state
- generated `.pkm-index` data

To continue with the same knowledge base, synchronize private notes and assets separately with iCloud Drive, Obsidian Sync, or an encrypted manual transfer. A Git clone alone recreates the software project but not the private knowledge content.

Do not create a second clone on top of a partially synchronized iCloud vault. Either open the existing synchronized vault and attach its Git worktree, or clone into an empty directory and then restore the ignored private folders.

## Intel Mac Prerequisites

Required:

- macOS on an Intel Mac
- Git
- Python 3.11 or newer
- Obsidian
- Codex app or VS Code with the Codex extension

Install Apple command line tools when Git is missing:

```bash
xcode-select --install
```

If Python 3.11 or newer is missing and Homebrew is already installed:

```bash
brew install python@3.13
```

On Intel Macs, Homebrew normally uses `/usr/local`. Ensure `/usr/local/bin` is on `PATH` before opening Codex or VS Code from a shell.

## Restore Procedure

1. Finish private vault synchronization before indexing.
2. Open Terminal and enter the intended vault parent directory.
3. Clone the repository only if the synchronized vault is not already a Git worktree:

```bash
git clone https://github.com/2muni/cognitiveos-vault.git
cd cognitiveos-vault
```

4. Confirm repository identity and release state:

```bash
git remote -v
git status --short --branch
git log -1 --oneline --decorate
git show --no-patch --oneline v0.1.0
```

5. Run the macOS bootstrap:

```bash
chmod +x scripts/bootstrap-macos.sh scripts/run-cognitiveos-mcp.sh
./scripts/bootstrap-macos.sh
```

The bootstrap creates `.venv`, runs all tests, rebuilds the disposable local index, and verifies the MCP handshake and tool list. It does not modify source Markdown.

6. Open the same vault root in Obsidian and Codex or VS Code.
7. Trust the project when prompted so `.codex/config.toml` can load.
8. Select the GPT-5.6 task tier in the Codex client.
9. Confirm the `cognitiveos` MCP server exposes nine read-only tools.
10. Test `list_recent_notes`, then `search_notes` with a known local query.

## Codex Model Policy

The repository does not pin a model identifier in `.codex/config.toml`. Model access and Terra/Sol selection are client-side and account-dependent.

Use this task scale:

| Tier | Intended work |
| --- | --- |
| `Terra / light` | UI checks, status, small docs, routine Git |
| `Sol / light` | narrow implementation and focused fixes |
| `Sol / medium` | normal features, environment work, retrieval changes |
| `Sol / high` | architecture, schema, writeback, security review |
| `Sol / ultra` | high-impact migrations and authorization boundaries |

Every completed task must end with the next recommended task and tier.

## Verification Contract

Run at any time from the vault root:

```bash
./.venv/bin/python scripts/verify_environment.py
```

Expected invariants:

- Python is 3.11 or newer
- all unit tests pass
- the vault index rebuild succeeds
- MCP server name is `cognitiveos`
- MCP exposes nine tools
- an invalid tool call returns `isError = true`
- writeback remains disabled

The indexed note count can differ between devices because private Markdown is synchronized outside Git. A different count is not automatically a failure.

## Current Roadmap

The next development phase is v0.2 read-only retrieval improvement.

Recommended order:

1. Complete the Intel Mac client-level MCP discovery check.
2. Add token budget estimation to `build_context_pack`.
3. Add explicit structured JSON output options to CLI commands.
4. Improve context pack source selection and evidence budgeting.
5. Design optional embeddings without making them a source of truth.
6. Revisit writeback only after the read-only v0.2 boundary is stable.

Do not enable writeback, migrations, renames, or deletion as part of environment restoration.

## First Prompt on the Intel Mac

Use this prompt after opening the repository in Codex:

```text
Read AGENTS.md and System/docs/device-handoff-intel-mac-v0.1.md first.
Verify the Intel Mac environment with scripts/verify_environment.py, confirm the
cognitiveos MCP server exposes nine read-only tools, and compare the result with
System/docs/roadmap-v0.1.md. Do not modify private notes or enable writeback.
After the task, report the next task and the recommended GPT-5.6 Terra/Sol tier.
```

## Source Documents

- `System/docs/roadmap-v0.1.md`
- `System/docs/decision-log.md`
- `System/docs/release-v0.1.md`
- `System/docs/release-notes-v0.1.0.md`
- `System/docs/writeback-permissions-v0.1.md`
- `System/docs/codex-client-setup-v0.1.md`
