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

- `71` unit tests
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

## Current Implementation Phase

Phase 7: optional semantic retrieval foundation.

Status: Design, provider boundary, deterministic chunker, separate derived
storage, builder, status/build CLI, semantic modes, cosine search, RRF hybrid
retrieval core, optional local `sentence-transformers` adapter, approved
multilingual model pin, quality/performance evaluation harness, and explicit
cache-only CLI/MCP runtime injection complete.
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

Completed implementation gates:

- Intel macOS baseline complete with the pinned model; retain the deterministic
  pipeline fixture for regression tests
- recorded Intel latency, index size, Recall@5, MRR, and forced-offline repeat
- actual MCP launcher and search CLI required-mode offline smoke tests complete
- actual 42-note vault baseline complete: 327 chunks, 1.3 MB index, 45.99-second
  full rebuild, 71.84 ms warm query median, and private Markdown checksum gate
- run the same pinned-model harness on remaining supported hardware later
- keep semantic retrieval disabled by default
- pass the privacy, fallback, lexical non-regression, and source checksum gates

The completed v0.3 release operations and immutable publication record are
tracked separately in `System/docs/release-v0.3.md`.

Release policy:

- `System/docs/release-v0.1.md`
- current development package version: `0.4.0a1`
- latest published stable tag and GitHub Release: `v0.3.0`

## Next Read-only Quality Phase

Phase 8: note contract validation and lower-friction authoring.

Status: Design, validator core, CLI, v0.2 templates, type-specific heading
guidance, source locator checks, and aggregate actual-vault audit complete.

Planned scope:

- deterministic, read-only `cognitiveos-validate`
- duplicate id and invalid frontmatter diagnostics
- lifecycle consistency warnings
- separate capture and durable authoring profiles
- new `System/templates/v0.2/` templates without changing v0.1 templates
- aggregate actual-vault validation without exposing private note content

The contract, diagnostic schema, compatibility boundary, and rollout order are
defined in `System/docs/note-contract-v0.2.md`.

Completed first implementation unit:

- immutable diagnostic and report data structures
- deterministic validation ordering and strict-mode exit semantics
- duplicate id, enum, field type, date, confidence, and placeholder errors
- lifecycle, title, durable-id, and tag/domain warnings
- relationship and visibility information diagnostics
- user/all scope behavior and vault-root safety
- no index creation or Markdown mutation

Completed second implementation unit:

- `cognitiveos-validate` package entry point
- deterministic `text|json` output
- `--scope user|all` and `--strict`
- stable exit codes for clean, validation, and invocation outcomes
- nine validator-compatible templates under `System/templates/v0.2/`
- capture and durable profiles without empty optional metadata arrays
- explicit documentation that the public v0.3.0 wheel predates the validator
  entry point

Completed third implementation unit:

- type-specific recommended heading diagnostics
- one aggregated missing-heading warning per note to limit diagnostic noise
- source URL, DOI, locator metadata, and body locator recognition
- source locator warnings without returning locator values or note content
- canonical template exemption from authoring-completeness diagnostics
- aggregate actual-vault audit: 8 errors, 18 warnings, and 3 information items

## Alias-aware Retrieval Development

Status: Implemented on the `0.4.0a1` feature branch; integration pending.

Delivered:

- aliases included in derived FTS candidate text without changing the SQLite
  schema or canonical title
- exact and partial alias ranking signals below exact canonical-title ranking
- alias-aware backlink target resolution
- alias-aware existing-link suppression in `suggest_links`
- English, Korean, reindex, backlink, and ranking regression coverage

Completed follow-up indexing unit:

- frontmatter `links` and `sources` normalized into typed derived graph edges
- raw ids, titles, aliases, paths, wikilinks, Markdown links, and URLs accepted
- frontmatter edge line numbers represented as `NULL`
- backlink source-note deduplication across multiple target spellings and edge
  types
- frontmatter edges included in `read_note` and existing-link suppression
- validator information warning removed now that the fields are operational
- aggregate actual-vault diagnostics now remain at 8 errors and 18 warnings
  with relationship information diagnostics reduced from 3 to 0

Completed graph retrieval unit:

- one deterministic identity resolver for backlinks, related notes, and
  context-pack graph signals
- exact note id and path precedence over colliding aliases or titles
- ambiguous aliases and titles rejected instead of expanding to multiple notes
- outgoing graph neighbors ranked before incoming neighbors in
  `get_related_notes`, with lexical fallback preserved
- note-type-diverse context selection prefers graph-connected candidates within
  the eligible type
- source-level and aggregate graph selection diagnostics
- generic lexical and hybrid `search_notes` ranking left unchanged

Completed graph cache unit:

- service-local adjacency reuse across backlink, related-note, and context-pack
  calls
- fast cache-hit signature check without opening SQLite
- generation confirmation using index run, status, note, and link state
- main SQLite and WAL mutation invalidation
- one retry for concurrent generation changes and no-cache fallback if the
  generation remains unstable
- actual-vault cache-hit benchmark reduced from about 1.78 ms to roughly
  0.03–0.05 ms per call on this device

Recommended model:

- `Sol / medium` for alias-aware retrieval integration and regression review
- `Sol / high` for writeback, schema, authorization, or security work
- `Sol / ultra` only for high-impact migrations or permission-boundary changes
