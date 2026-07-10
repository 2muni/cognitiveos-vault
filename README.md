# cognitiveos-vault

CognitiveOS is a Markdown-first, local-first, MCP-addressable PKM system for an Obsidian vault.

The current implementation is a read-only v0.1 MVP:

- scans Markdown notes
- parses frontmatter, headings, wikilinks, and Markdown links
- builds a disposable SQLite/FTS index
- exposes read-only retrieval tools through MCP
- supports structured summaries and context packs for Codex/LLM workflows

## Current Scope

Implemented:

- Python indexer
- SQLite/FTS search
- PKM-aware search reranking
- read-only MCP stdio server
- VS Code/Codex project MCP config
- MCP argument validation
- structured source summaries
- structured context packs
- writeback permission design

Deferred:

- vector search
- graph database
- local LLM calls
- writeback tools
- migrations, renames, deletes, and bulk normalization

## Repository Layout

```text
.codex/config.toml                  Codex project config and MCP server registration
scripts/run-cognitiveos-mcp.sh       macOS MCP server launcher
scripts/run-cognitiveos-mcp.ps1      Windows MCP server launcher
scripts/bootstrap-macos.sh           Intel Mac environment bootstrap
scripts/verify_environment.py        Cross-device verification
src/cognitiveos/                    Python implementation
tests/                              Unit and fixture tests
System/docs/                        Architecture, schemas, decisions, roadmap
System/templates/v0.1/              Canonical note templates
.pkm-index/                         Generated local index, Git-ignored
```

Personal vault content folders are intentionally ignored by Git except for `.gitkeep` placeholders.

## MCP Tools

Read-only tools:

- `search_notes`
- `read_note`
- `list_recent_notes`
- `get_backlinks`
- `get_related_notes`
- `suggest_links`
- `summarize_source`
- `propose_moc`
- `build_context_pack`

No MCP tool writes to Markdown in v0.1.

## Intel Mac Quick Start

After cloning the repository or opening the synchronized vault worktree:

```bash
chmod +x scripts/bootstrap-macos.sh scripts/run-cognitiveos-mcp.sh
./scripts/bootstrap-macos.sh
```

The canonical migration and continuation guide is:

```text
System/docs/device-handoff-intel-mac-v0.1.md
```

Private note folders and assets are not transferred by Git. Restore them through iCloud Drive, Obsidian Sync, or a separate encrypted transfer before rebuilding the index.

## Run Tests

From the vault root:

```bash
python3 -m unittest discover -s tests -v
```

Expected current result:

```text
Ran 16 tests
OK
```

## Build the Local Index

```bash
PYTHONPATH=src python3 -c "from cognitiveos.cli import main_index; main_index()"
```

The generated database is stored under:

```text
.pkm-index/cognitiveos.sqlite3
```

This index is derived and can be rebuilt from Markdown.

## Search Example

```bash
PYTHONPATH=src python3 -c "from cognitiveos.cli import main_search; main_search()" "CognitiveOS MCP PKM"
```

## MCP Server

The project MCP server is registered in `.codex/config.toml`:

```toml
[mcp_servers.cognitiveos]
command = "/bin/bash"
args = ["scripts/run-cognitiveos-mcp.sh"]
cwd = "."
enabled = true
```

The launcher finds a usable Python executable, sets `PYTHONPATH=src`, and runs:

```bash
./scripts/run-cognitiveos-mcp.sh
```

## VS Code / Codex

Local setup status:

- VS Code installed
- Codex extension installed as `openai.chatgpt@26.707.31428`
- project MCP config exists at `.codex/config.toml`

Open the vault root in VS Code and confirm the Codex extension loads the `cognitiveos` MCP server.

## Writeback Policy

Writeback is not implemented in v0.1.

The future writeback design is documented in:

```text
System/docs/writeback-permissions-v0.1.md
```

Required principles:

- explicit approval for every write
- proposal before apply
- diff or preview before write
- checksum verification
- vault-root path enforcement
- auditable derived writeback logs

## Roadmap

The implementation-vs-roadmap status is maintained in:

```text
System/docs/roadmap-v0.1.md
```

## Release Policy

The v0.1 release checklist, version policy, and tag policy are maintained in:

```text
System/docs/release-v0.1.md
```

It also defines the hotfix flow and version bump procedure.

The v0.1.0 release notes are maintained in:

```text
System/docs/release-notes-v0.1.0.md
```

Current package version:

```text
0.1.0
```

Published stable release:

```text
v0.1.0
```
