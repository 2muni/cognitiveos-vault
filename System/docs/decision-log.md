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
