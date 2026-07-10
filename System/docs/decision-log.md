# CognitiveOS Decision Log

This document records design decisions and discussion outcomes for the Obsidian-based PKM, local LLM/Codex, and MCP system.

## 2026-07-08

### Decision: Store Project Decisions in `System/docs`

Future discussion outcomes, architecture decisions, and implementation agreements should be preserved under `System/docs`.

Rationale:

- Keep system governance separate from private knowledge content.
- Make design history available to Codex and future local agents.
- Preserve project decisions in Markdown so they remain portable and version-controllable.

### Decision: Restart Architecture From a Blank Slate

Existing vault folders, files, and prior documents should not constrain the next architecture pass unless explicitly reintroduced.

The current design process should proceed from abstract system design toward concrete schema, MCP resources, MCP tools, index design, and implementation plan.

### Decision: Current Abstract Direction

CognitiveOS is defined as a Markdown-first, local-first, MCP-addressable PKM system.

Initial implementation target:

- read-only knowledge interface
- Markdown/frontmatter parsing
- metadata and full-text indexing
- evidence-returning retrieval
- MCP resources and tools for read/search operations
- writeback only after explicit approval and later design

### Decision: Implement Plan v0.1

The accepted implementation plan covers architecture documentation, note/MCP/index schemas, a roadmap, and a Python MVP.

Implementation defaults:

- Python core package under `src/cognitiveos`
- SQLite/FTS index under `.pkm-index`
- read-only ingestion, retrieval, and MCP tools
- no vector DB, graph DB, embeddings, or writeback in v0.1
- tests use fixture vaults and must not mutate private notes

### Verification: Actual Vault Read-only Index

The Python MVP was run against the current vault in read-only mode.

Result:

- indexed 27 Markdown notes
- created derived SQLite index at `.pkm-index/cognitiveos.sqlite3`
- verified search for `CognitiveOS`
- verified recent-note listing
- verified `read_note` by vault-relative path
- verified `build_context_pack`
- verified path traversal rejection for `../outside.md`
- unit test suite passed: 8 tests

No source Markdown files were modified by indexing or retrieval.

### Decision: Add Schema Fixture Verification

The MVP should not rely only on legacy or pre-schema Markdown files for validation.

Additional verification uses a dedicated test fixture vault with current Note Schema frontmatter:

- concept note
- source note
- project note

Search now supports read-only filters for `type`, `status`, `domain`, and `tag`.

### Decision: Delete Legacy System Artifacts

The pre-v0.1 files `System/__SPECS__.md` and `System/templates/` were deleted locally and remain excluded from the repository baseline.

Rationale:

- They were not part of the current blank-slate v0.1 design process.
- `System/__SPECS__.md` appears to contain mojibake/encoding-corrupted legacy governance text.
- The existing templates predate the current Note Schema and should not be treated as canonical.

Future schema-aligned templates should be created explicitly under a new v0.1 template plan.

### Decision: Create Canonical Templates v0.1

Canonical templates are stored under `System/templates/v0.1/`.

Rules:

- templates align with `schema-note-v0.1.md`
- templates use plain Markdown and YAML frontmatter only
- no Obsidian plugin-specific syntax is required
- templates cover all initial note types: `inbox`, `concept`, `source`, `entity`, `project`, `map`, `journal`, `system`, `output`
- automated note creation and migration remain out of scope

### Decision: Configure Read-only Codex MCP Server

The project-scoped `.codex/config.toml` includes `mcp_servers.cognitiveos`.

Rules:

- run as a stdio MCP server through `scripts/run-cognitiveos-mcp.ps1`
- expose only read-only tools
- use `default_tools_approval_mode = "prompt"`
- keep writeback tools out of scope
- support the Python MCP SDK when installed, with a dependency-free JSON-RPC stdio fallback for v0.1

### Verification: MCP Server Runtime

The project MCP server was verified at the stdio protocol level.

Result:

- `.codex/config.toml` parses successfully
- `mcp_servers.cognitiveos.enabled` is `true`
- enabled tools are `search_notes`, `read_note`, `list_recent_notes`, `get_backlinks`, `get_related_notes`, `build_context_pack`
- `scripts/run-cognitiveos-mcp.ps1` starts the server using an executable Python candidate
- JSON-RPC `initialize` succeeds
- JSON-RPC `tools/list` returns the read-only tool set
- JSON-RPC `tools/call` with `search_notes` succeeds

Codex CLI `codex mcp list` could not be verified in this environment because `codex.exe` fails with WindowsApps access denied. The current running Codex session also does not dynamically expose the newly configured MCP tools; a new session or app restart is expected to load the project MCP configuration.

### Verification: Codex Tool Discovery Follow-up

A new local Codex thread was created for MCP discovery verification.

Result:

- the new thread also did not expose `cognitiveos` MCP tools through dynamic tool discovery
- the visible discovery surface showed `node_repl`, not the expected `search_notes`, `read_note`, `list_recent_notes`, `get_backlinks`, `get_related_notes`, or `build_context_pack`
- local search through the implementation path still works
- stdio JSON-RPC server verification remains the strongest confirmed signal that the server implementation is healthy

Conclusion:

The v0.1 MCP server is implemented and operational at the stdio protocol level, but Codex app/client registration is not yet confirmed. This should be treated as a client configuration/loading issue rather than a server implementation failure until proven otherwise.

### Decision: Treat CLI and IDE Extension as Primary MCP Clients

Official Codex MCP documentation states that Codex supports MCP servers in the CLI and IDE extension. It also says MCP configuration is stored in `config.toml`, including project-scoped `.codex/config.toml` for trusted projects.

Decision:

- keep the project-scoped `.codex/config.toml` MCP server definition
- treat CLI or IDE extension `/mcp` discovery as the primary client-level verification path
- treat Codex App discovery as non-authoritative for this v0.1 MCP setup
- continue using local stdio JSON-RPC tests as the implementation-level verification path

Rationale:

The server passed TOML parsing, stdio initialization, `tools/list`, and `tools/call`. The remaining gap is client-surface loading, and the official support statement points to CLI/IDE rather than App.

### Verification: Local CLI and IDE Client Availability

Local client availability was checked for MCP discovery.

Result:

- VS Code CLI is installed and reports version `1.128.0`
- no installed VS Code extension matching `codex` or `openai` was found
- the only `codex` executable on PATH is the WindowsApps packaged app resource
- direct execution of the WindowsApps `codex.exe` fails with `Access is denied`
- `codex mcp list` cannot be used from this shell until an executable CLI path is available

Conclusion:

Client-level `/mcp` verification is blocked by local client availability, not by the CognitiveOS MCP server. The next verification path is either installing/enabling the Codex IDE extension in VS Code or installing a standalone Codex CLI that can run outside the WindowsApps package boundary.

### Decision: Expand Read-only MCP Tool Surface

The read-only MCP surface was aligned with `AGENTS.md`.

Decision:

- add `suggest_links`
- add `summarize_source`
- add `propose_moc`
- keep all three tools read-only
- keep writeback and automatic Markdown mutation out of v0.1

Rationale:

These tools support PKM workflows without changing source Markdown. `suggest_links` proposes internal links from indexed evidence, `summarize_source` returns an extractive summary grounded in one note, and `propose_moc` returns a map-of-content outline with `writeback = false`.

### Verification: Actual Vault Read-only Helper Tools

The actual vault was reindexed after expanding the read-only MCP surface.

Result:

- indexed 32 Markdown notes
- `System/docs/decision-log.md` is inferred as `system` without editing source Markdown
- `suggest_links` returned relevant system documents for the decision log
- `propose_moc("CognitiveOS MCP PKM")` grouped matching system documents under a `system` section
- all helper outputs remained read-only and produced no Markdown writeback

Decision:

- keep path-inferred runtime note types for known operational folders
- keep `suggest_links` keyword-overlap reranking as the v0.1 heuristic
- keep `propose_moc` grouped by note type with `writeback = false`

### Decision: Structured Extractive Source Summary v0.2

`summarize_source` was upgraded from a plain paragraph concatenation to a deterministic structured summary.

Decision:

- keep the tool read-only
- do not call an LLM in v0.1
- return `summary_version = extractive-v0.2`
- return `summary`, `key_points`, `open_questions`, `headings`, `evidence`, and `stats`
- keep evidence blocks grounded in source Markdown

Rationale:

Structured output is easier for Codex and future agents to consume than a single summary string. The v0.2 structure improves downstream context packing while preserving deterministic, auditable behavior.

### Decision: Structured Context Pack v0.2

`build_context_pack` was upgraded from a compact excerpt list to a structured evidence bundle.

Decision:

- keep the tool read-only
- return `context_version = context-pack-v0.2`
- preserve the compact `context` string for prompt insertion
- add ranked `sources` with summaries, key points, evidence, scores, and stats
- add deduplicated `key_points`
- add `evidence_paths`
- add pack-level `stats`

Rationale:

Future local LLM and Codex workflows need more than raw excerpts. A structured context pack gives the model prompt-ready text while also preserving source paths and evidence for auditability.

### Decision: Search Ranking v0.2

`search_notes` now reranks SQLite FTS/LIKE candidates with local PKM signals.

Decision:

- keep SQLite FTS/LIKE as the candidate generator
- fetch more candidates than the requested limit
- rerank candidates in Python
- prioritize exact and partial title matches
- add heading, path, excerpt, note type, status, and small freshness boosts
- keep vector search deferred beyond v0.1

Rationale:

FTS ranking alone is too generic for a PKM vault. Title, headings, lifecycle status, and note type encode useful human intent while remaining deterministic and local-first.

Verification:

- unit tests cover title and heading reranking
- actual vault search for `CognitiveOS MCP PKM` returned relevant system documents
- `AGENTS.md` and `README.md` are now inferred as `system` when frontmatter is missing

### Decision: MCP Argument Validation and Tool Error Semantics

The basic stdio MCP server now validates tool arguments before calling retrieval services.

Decision:

- reject empty required strings
- reject missing or ambiguous note references
- reject invalid `limit` values
- clamp valid limits to tool-specific maximums
- return tool-level errors with `isError = true`
- include structured error codes in `structuredContent.error`

Rationale:

Retrieval tools should fail predictably at the MCP boundary instead of passing empty or ambiguous values into lower layers.

### Decision: Writeback Permission Boundary v0.1

Writeback remains outside the current implementation and is documented as a future two-phase proposal/apply system.

Decision:

- keep v0.1 MCP tools read-only
- document future write tools separately in `System/docs/writeback-permissions-v0.1.md`
- require explicit approval for every write operation
- require previews or diffs before writes
- require checksum verification before applying patches
- keep writeback logs as derived Git-ignored artifacts

Rationale:

Markdown files are durable records. Writeback must be auditable, approval-gated, and vault-root constrained before any MCP write tools are enabled.

### Decision: Reconcile Roadmap With Implementation

The roadmap was updated from an initial phase list into an implementation status document.

Decision:

- mark schema/docs, ingestion, index, read-only MCP, retrieval, structured summaries, structured context packs, search reranking, MCP validation, and writeback design as complete for v0.1
- keep writeback implementation, vector search, graph DB, and local LLM calls deferred
- document current test count, smoke verification, and known limitations
- expand `README.md` into a practical v0.1 usage guide

Rationale:

The implemented system has moved beyond the original roadmap outline. A release-facing status document makes the current boundary clearer and prevents deferred features from being confused with implemented capabilities.

### Decision: Release and Version Policy v0.1

The project now has an explicit release checklist, version policy, and tag policy.

Decision:

- keep package version as `0.1.0`
- use `v0.1.0` as the first stable release tag target
- use annotated Git tags for releases
- do not move published tags without explicit user approval
- use SemVer-like versioning for implementation releases
- treat writeback enablement or incompatible schema changes as major-version events
- keep release criteria in `System/docs/release-v0.1.md`

Rationale:

The read-only MVP is stable enough to define a release boundary. Explicit version and tag rules reduce ambiguity before creating the first release tag.
