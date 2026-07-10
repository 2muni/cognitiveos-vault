# CognitiveOS v0.1.0 Release Notes

Tag:

```text
v0.1.0
```

Target commit:

```text
578882d
```

Release type:

```text
First stable read-only MVP
```

## Summary

CognitiveOS v0.1.0 establishes the first stable read-only baseline for an Obsidian-based, Markdown-first, local-first, MCP-addressable PKM system.

This release can scan a local vault, derive a disposable SQLite/FTS index, expose read-only MCP tools, and build structured evidence packs for Codex or future local LLM workflows.

## Highlights

- Markdown-first vault indexing
- SQLite/FTS search
- PKM-aware search reranking
- read-only MCP stdio server
- project-scoped Codex MCP configuration
- structured extractive source summaries
- structured context packs for LLM/Codex use
- MCP argument validation and structured tool errors
- writeback permission design, with implementation intentionally deferred

## Included

### Markdown Ingestion

- vault-root Markdown scanner
- operational folder skips for `.git`, `.obsidian`, `.trash`, `.pkm-index`, and `__pycache__`
- YAML frontmatter parsing with fallback parser
- broken YAML tolerance
- UTF-8, UTF-8-SIG, and CP949 read fallback
- heading extraction
- wikilink extraction
- Markdown link extraction
- stable runtime note IDs
- path-inferred note types for known operational folders and root operational docs

### SQLite/FTS Index

- generated index at `.pkm-index/cognitiveos.sqlite3`
- index tables:
  - `notes`
  - `note_frontmatter`
  - `links`
  - `headings`
  - `fts_notes`
  - `index_runs`
- full rebuild support
- path/note id upsert behavior
- duplicate row prevention on reindex

### Read-only MCP Tools

The v0.1.0 MCP surface exposes 9 read-only tools:

- `search_notes`
- `read_note`
- `list_recent_notes`
- `get_backlinks`
- `get_related_notes`
- `suggest_links`
- `summarize_source`
- `propose_moc`
- `build_context_pack`

No MCP tool writes to Markdown in this release.

### Retrieval

`search_notes` uses SQLite FTS/LIKE as the candidate generator and reranks results with local PKM signals:

- exact title match
- partial title match
- heading term match
- path term match
- matched excerpt overlap
- note type boost
- status boost
- small freshness boost

### Structured Summaries

`summarize_source` returns:

- `summary_version = extractive-v0.2`
- `summary`
- `key_points`
- `open_questions`
- `headings`
- `evidence`
- `stats`

The summary is deterministic and extractive. It does not call an LLM.

### Structured Context Packs

`build_context_pack` returns:

- `context_version = context-pack-v0.2`
- `context`
- `results`
- `sources`
- `key_points`
- `evidence_paths`
- `stats`

This is designed as a prompt-ready evidence bundle while preserving source paths for auditability.

### MCP Validation

The basic stdio MCP server now validates:

- required non-empty string arguments
- exact one-of `note_id` or `path` for note reads/summaries
- valid integer limits
- tool-specific maximum limits

Tool failures return `isError = true` with structured error codes.

## Verification

Current verification snapshot:

| Check | Result |
| --- | --- |
| Unit tests | Pass, `16` tests |
| Actual vault index | Pass, `34` Markdown notes |
| MCP `initialize` | Pass, server name `cognitiveos` |
| MCP `tools/list` | Pass, `9` tools |
| Invalid MCP call | Pass, `isError = true`, `invalid_argument` |

Test command:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

Expected result:

```text
Ran 16 tests
OK
```

## Excluded From v0.1.0

The following are intentionally not implemented:

- writeback tools
- vector search
- graph database
- local LLM calls
- background agents
- automatic migrations
- destructive operations

## Writeback Policy

Writeback remains disabled in v0.1.0.

The future writeback model is documented in:

```text
System/docs/writeback-permissions-v0.1.md
```

The future design requires:

- explicit approval for every write
- proposal before apply
- diff or preview before write
- checksum verification
- vault-root path enforcement
- auditable derived writeback logs

## Known Limitations

- Search ranking is deterministic but heuristic.
- Summaries are extractive, not abstractive.
- Context packs do not yet estimate token budget.
- No vector embeddings.
- No graph database.
- No local LLM runtime integration.
- No writeback tools.
- VS Code Codex UI-level MCP discovery requires local interactive confirmation.

## Upgrade Notes

This is the first stable release tag.

Generated artifacts such as `.pkm-index/` remain disposable and can be rebuilt from Markdown.

No migration is required.

## Next Candidates

Patch release candidates for `v0.1.1`:

- README corrections
- CLI help polish
- better smoke test commands
- small ranking bug fixes
- small MCP error message improvements

Minor release candidates for `v0.2.0`:

- token budget estimator for `build_context_pack`
- JSON output mode for CLI search
- richer context pack source selection
- optional embedding index design
- MCP resource URI support

