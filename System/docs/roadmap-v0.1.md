# CognitiveOS Roadmap v0.1

## Current Status

Status checked on 2026-07-11.

The v0.1 read-only MVP remains the published stable baseline. The v0.2 read-only
retrieval implementation is complete on `main`; another-device and interactive
client discovery checks are deferred.

Summary:

| Area | Status |
| --- | --- |
| Schema and architecture docs | Complete |
| Markdown ingestion | Complete |
| SQLite/FTS index | Complete |
| Read-only retrieval tools | Complete |
| Basic MCP stdio server | Complete |
| MCP tool validation | Complete |
| Structured summaries | Complete |
| Structured context packs | Complete |
| Context token budget and evidence allocation | Complete |
| Explicit text/JSON CLI formats | Complete |
| Search reranking | Complete |
| VS Code Codex extension setup | Complete locally |
| Writeback implementation | Deferred |
| Writeback permission design | Complete |
| Vector search | Deferred |
| Graph database | Deferred |
| Local LLM calls | Deferred |
| Release checklist and tag policy | Complete |
| Public GitHub Release `v0.1.0` | Complete |
| Current Intel Mac environment | Complete |
| Other-device and client UI verification | Deferred by user |

## Phase 0: Schema and Docs

Status: Complete.

Delivered:

- `System/docs/cognitiveos-architecture-v0.1.md`
- `System/docs/schema-note-v0.1.md`
- `System/docs/schema-mcp-v0.1.md`
- `System/docs/schema-index-v0.1.md`
- `System/docs/roadmap-v0.1.md`
- `System/docs/templates-v0.1.md`
- `System/docs/writeback-permissions-v0.1.md`
- `System/docs/decision-log.md`

Notes:

- All discussion and design decisions are kept under `System/docs`.
- Personal notes and generated artifacts remain excluded from Git.

## Phase 1: Markdown Ingestion

Status: Complete.

Delivered:

- vault-root Markdown scanner
- operational folder skips:
  - `.git`
  - `.obsidian`
  - `.trash`
  - `.pkm-index`
  - `__pycache__`
- YAML frontmatter parsing with fallback parser
- broken YAML tolerance
- UTF-8/UTF-8-SIG/CP949 read fallback
- heading extraction
- wikilink extraction
- Markdown link extraction
- stable runtime note id from relative path
- path-inferred runtime note type for known operational folders and root operational docs

Implemented in:

- `src/cognitiveos/scanner.py`
- `src/cognitiveos/parser.py`
- `src/cognitiveos/safety.py`

## Phase 2: SQLite/FTS Index

Status: Complete.

Delivered:

- generated SQLite index under `.pkm-index/cognitiveos.sqlite3`
- tables:
  - `notes`
  - `note_frontmatter`
  - `links`
  - `headings`
  - `fts_notes`
  - `index_runs`
- full rebuild support
- path/note id upsert behavior
- duplicate row prevention on reindex
- generated index remains disposable and ignored by Git

Implemented in:

- `src/cognitiveos/indexer.py`

## Phase 3: Read-only MCP Server

Status: Complete.

Delivered tools:

- `search_notes`
- `read_note`
- `list_recent_notes`
- `get_backlinks`
- `get_related_notes`
- `suggest_links`
- `summarize_source`
- `propose_moc`
- `build_context_pack`

Delivered server behavior:

- FastMCP support when the Python `mcp` SDK is installed
- dependency-free JSON-RPC stdio fallback
- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call`
- tool-level error results with `isError = true`
- structured error codes:
  - `invalid_argument`
  - `not_found`
  - `invalid_request`
  - `internal_error`
- vault-root path enforcement through retrieval/safety layer

Implemented in:

- `src/cognitiveos/mcp_server.py`
- `scripts/run-cognitiveos-mcp.ps1`
- `.codex/config.toml`

## Phase 4: Retrieval and Context Packs

Status: Complete for v0.2.

Delivered:

- SQLite FTS/LIKE candidate search
- ranking v0.2 with local PKM signals:
  - exact title match
  - partial title match
  - heading term match
  - path term match
  - excerpt term overlap
  - note type boost
  - status boost
  - small freshness boost
- type/status/domain/tag filters
- backlinks
- related notes
- link suggestions
- deterministic extractive source summary:
  - `summary_version = extractive-v0.2`
  - `summary`
  - `key_points`
  - `open_questions`
  - `headings`
  - `evidence`
  - `stats`
- structured context pack:
  - `context_version = context-pack-v0.3`
  - `context`
  - `results`
  - `sources`
  - `key_points`
  - `evidence_paths`
  - `stats`
  - `budget`
- deterministic `local-heuristic-v1` token estimation
- `512–32768` token budget with `4000` default
- note-type-diverse source selection
- round-robin key point and evidence allocation
- explicit `text|json` CLI formats

Implemented in:

- `src/cognitiveos/retrieval.py`
- `src/cognitiveos/models.py`

## Phase 5: Writeback Design Review

Status: Design complete, implementation deferred.

Delivered:

- permission model
- read/propose/write/destructive capability classes
- future write tool list
- two-phase `propose -> apply` flow
- checksum verification requirement
- diff/preview requirement
- writeback manifest design
- Git-ignored derived writeback log policy

Documented in:

- `System/docs/writeback-permissions-v0.1.md`

Deferred implementation:

- `create_draft_note`
- `update_properties`
- `append_to_daily`
- `apply_patch_to_note`
- migration tools
- rename tools
- delete/archive tools

## Verification Status

Current automated verification:

- `44` unit tests
- parser tests
- safety tests
- index tests
- retrieval tests
- schema fixture tests
- basic MCP protocol tests
- MCP argument validation tests

Current smoke verification:

- actual vault indexing succeeds; note count is device-dependent and is not a fixed pass criterion
- stdio MCP server responds to `initialize`
- stdio MCP server responds to `tools/list`
- stdio MCP server returns tool-level error for invalid calls
- VS Code Codex extension installed locally:
  - `openai.chatgpt@26.707.31428`

## Current Known Limitations

- No production embedding model adapter is enabled yet.
- No graph database yet.
- No local LLM call path yet.
- No writeback tools are enabled.
- Search ranking is deterministic and local but still heuristic.
- Source summary is extractive, not abstractive.
- Codex UI-level MCP discovery still requires user-side VS Code/Codex sign-in and visual confirmation.

## Next Recommended Phase

Phase 7: optional semantic retrieval foundation.

Status: Design, provider boundary, deterministic chunker, separate derived
storage, builder, status/build CLI, semantic modes, cosine search, RRF hybrid
retrieval core, and optional local `sentence-transformers` adapter complete.
The adapter is development work for v0.3 and is not part of v0.2.

Recommended tasks:

- optional embedding storage, chunking, provider, hybrid ranking, and fallback
  contracts are documented in `System/docs/embeddings-design-v0.3.md`
- provider-neutral identity, batch, and vector validation are implemented in
  `src/cognitiveos/embeddings.py`
- deterministic tests cover provider identity, stable output, failure wrapping,
  count, dimension, numeric, finite-value, and zero-vector validation
- `markdown-blocks-v1` implements frontmatter exclusion, heading context,
  character limits, overlap, line ranges, content hashes, and stable chunk ids
- separate SQLite storage validates build identity, counts, integrity, and vector
  encoding before atomic publish
- incremental builds reuse exact compatible chunks; `--rebuild` regenerates all
  vectors; failed builds preserve the last valid index
- `cognitiveos-embed --status --format text|json` inspects state without building
- SQLite/FTS and metadata retrieval remain the default path
- missing, stale, incompatible, and corrupt embedding indexes have explicit
  `off | auto | required` behavior
- Korean, English, and mixed-language test fixtures record Recall@5 and MRR for
  the deterministic pipeline evaluation
- revisit writeback only after the read-only retrieval boundary remains stable

Next implementation gate:

- privacy-review the first production local model adapter against an approved model
- replace the deterministic pipeline fixture with a production-model quality
  baseline while retaining it for regression tests
- measure latency, index size, Recall@5, and MRR on an approved local model
- keep semantic retrieval disabled by default
- pass the privacy, fallback, lexical non-regression, and source checksum gates
- publish `v0.3.0` only after every gate above is complete; do not publish an
  intermediate alpha GitHub Release

Release policy:

- `System/docs/release-v0.1.md`
- current development package version: `0.3.0a1`
- latest published stable tag and GitHub Release: `v0.2.0`

Recommended model:

- `Sol / medium` for Intel Mac verification and v0.2 retrieval work
- `Sol / high` for writeback, schema, authorization, or security work
- `Sol / ultra` only for high-impact migrations or permission-boundary changes
