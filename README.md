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
scripts/run-cognitiveos-mcp.ps1      Windows MCP server launcher
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

## Run Tests

From the vault root:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

Expected current result:

```text
Ran 16 tests
OK
```

## Build the Local Index

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "import sys; sys.path.insert(0, 'src'); from cognitiveos.indexer import VaultIndex, default_index_path; db=default_index_path('.'); index=VaultIndex(db); count=index.index_vault('.'); index.close(); print(f'Indexed {count} notes into {db}')"
```

The generated database is stored under:

```text
.pkm-index/cognitiveos.sqlite3
```

This index is derived and can be rebuilt from Markdown.

## Search Example

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "import sys,json; sys.path.insert(0,'src'); from cognitiveos.retrieval import RetrievalService; s=RetrievalService('.'); print(json.dumps([r.__dict__ for r in s.search_notes('CognitiveOS MCP PKM', limit=5)], ensure_ascii=False, indent=2))"
```

## MCP Server

The project MCP server is registered in `.codex/config.toml`:

```toml
[mcp_servers.cognitiveos]
command = "powershell"
args = ["-ExecutionPolicy", "Bypass", "-File", "scripts/run-cognitiveos-mcp.ps1"]
cwd = "."
enabled = true
```

The launcher finds a usable Python executable, sets `PYTHONPATH=src`, and runs:

```powershell
python -m cognitiveos.mcp_server --vault-root <vault-root>
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

Current package version:

```text
0.1.0
```

First stable tag target:

```text
v0.1.0
```
