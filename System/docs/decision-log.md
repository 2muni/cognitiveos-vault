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

### Decision: Hotfix and Version Bump Policy

The release policy now includes explicit hotfix and version bump procedures.

Decision:

- use patch bumps for hotfixes, for example `0.1.0 -> 0.1.1`
- use `codex/hotfix-vX.Y.Z-short-description` branch names for hotfix branches
- allow direct hotfix commits to `main` only when the user explicitly drives that flow and the change is narrow
- disallow new features, writeback capability, migrations, broad refactors, and private note changes in hotfixes
- require tests and relevant smoke checks before tagging a hotfix
- require version bump commits before creating release tags

Rationale:

Hotfix rules keep emergency changes small and auditable. Version bump rules prevent tags from being created without matching project metadata.

### Decision: v0.1.0 Release Notes

The `v0.1.0` GitHub release notes were drafted and stored under `System/docs`.

Decision:

- keep release notes at `System/docs/release-notes-v0.1.0.md`
- summarize included read-only capabilities
- explicitly list excluded writeback/vector/graph/local LLM work
- include verification snapshot
- include known limitations and next version candidates

Rationale:

Release notes should be reproducible from the repository itself, not only from GitHub UI text.

### Verification: Public v0.1.0 GitHub Release

The user confirmed that the `v0.1.0` GitHub Release was published on 2026-07-10.

Decision:

- treat `v0.1.0` as the published stable read-only MVP
- keep the existing annotated tag at commit `578882d`
- do not move the published tag
- keep the later release-notes commit on `main`

### Decision: Intel Mac Continuation Environment

Future work will continue on an Intel Mac.

Decision:

- add a POSIX MCP launcher for macOS
- keep the existing PowerShell launcher for Windows recovery
- add an Intel Mac bootstrap and cross-device verification script
- target the tracked project MCP configuration at macOS
- keep private note synchronization separate from Git
- use `System/docs/device-handoff-intel-mac-v0.1.md` as the canonical continuation guide
- keep writeback disabled during device migration

Rationale:

The code and governance documents are version-controlled, while personal notes and assets are intentionally ignored. Reproducing the complete working system therefore requires both Git synchronization and a separate private-vault synchronization channel.

### Decision: GPT-5.6 Terra/Sol Task Scale

The project no longer pins a model identifier in `.codex/config.toml`. The user selects the available GPT-5.6 tier in the Codex client.

Task scale:

- `Terra / light`: UI, status, small docs, routine Git
- `Sol / light`: narrow implementation and focused fixes
- `Sol / medium`: normal features, environment work, and retrieval changes
- `Sol / high`: architecture, schema, writeback, and security review
- `Sol / ultra`: high-impact migrations and authorization boundaries

Every completed task should report the next recommended task and tier.

## 2026-07-11

### Decision: Read-only Retrieval v0.2

The v0.2 implementation adds deterministic context budgeting without changing
the Markdown source-of-truth or read-only permission boundary.

Decision:

- set the package version to `0.2.0`
- return `context_version = context-pack-v0.3`
- accept a `token_budget` of `512–32768`, defaulting to `4000`
- use the dependency-free `local-heuristic-v1` estimator
- prefer note-type diversity, then fill sources by search rank
- allocate source identity first and optional evidence round-robin
- expose explicit `text|json` CLI formats
- keep the MCP surface at nine read-only tools
- defer embeddings, writeback, other-device verification, and client UI discovery

Verification:

- 22 automated tests cover token estimation, budget enforcement, deterministic
  source selection, MCP validation, and CLI formats
- actual vault verification must preserve user Markdown checksums

### Decision: Optional Embeddings Stay Derived and Opt-in

The optional semantic retrieval design is recorded in
`System/docs/embeddings-design-v0.3.md`.

Decision:

- keep embeddings disabled by default
- store vectors in a separate Git-ignored SQLite database
- require explicit provider, model, revision, and dimension identity
- use deterministic Markdown block chunks and checksum-based incremental builds
- keep SQLite/FTS as the default and fallback retrieval path
- expose future `off | auto | required` semantic modes
- use reciprocal rank fusion instead of comparing lexical and vector scores
- perform builds only through an explicit CLI command
- prohibit automatic model downloads and background embedding jobs
- require a separate privacy review for remote embedding adapters

Rationale:

Semantic retrieval can improve recall, but it must not weaken the local-first,
Markdown-first, read-only, and evidence-grounded guarantees established in v0.2.

Implementation checkpoint:

- add the provider-neutral interface in `src/cognitiveos/embeddings.py`
- validate explicit provider, model, revision, and positive dimension identity
- validate batch inputs before provider calls
- reject wrong vector counts, dimensions, non-numeric values, non-finite values,
  and zero vectors
- wrap provider failures without including note content or provider exception text
- use a deterministic SHA-256-derived provider only inside tests
- keep storage, production adapters, CLI, and semantic retrieval deferred
- expand the automated suite to 26 passing tests

### Implementation Checkpoint: Deterministic Embedding Chunks

Decision:

- implement `markdown-blocks-v1` in `src/cognitiveos/embedding_chunks.py`
- derive chunk content only from parsed body text, title, and nearest heading
- keep YAML frontmatter text out of chunk content
- enforce a 1,600-character default hard limit and 300-character overlap
- prefer sentence boundaries, then whitespace, before hard splitting
- store body-relative line ranges and SHA-256 content hashes
- derive stable chunk ids from note id, note checksum, chunker version, and index
- emit one identity chunk for empty and heading-only notes
- keep embedding storage, production adapters, CLI, and hybrid retrieval deferred

Verification:

- tests cover frontmatter exclusion, heading context, deterministic ids and
  hashes, checksum changes, hard limits, overlap, long blocks, line ranges,
  empty notes, heading-only notes, and invalid chunk limits
- the automated suite passes 32 tests

### Implementation Checkpoint: Derived Embedding Index Builder

Decision:

- store embedding builds in `.pkm-index/cognitiveos-embeddings.sqlite3`
- keep this database separate from the lexical SQLite/FTS index
- encode vectors as little-endian float32 blobs
- require exact chunk content hash and complete provider identity for reuse
- build and validate a temporary database before atomic publication
- preserve the last valid database when provider or validation steps fail
- expose explicit full rebuild and read-only status CLI paths
- keep the provider registry empty in the core package
- inject the deterministic provider only in tests
- keep semantic retrieval and MCP embedding build tools disabled

Verification:

- tests cover vector encoding, missing/corrupt status, full build, unchanged
  reuse, changed-note re-embedding, forced rebuild, atomic failure preservation,
  and CLI JSON output
- the automated suite passes 37 tests

### Implementation Checkpoint: Opt-in Hybrid Retrieval Core

Decision:

- add `semantic_mode=off|auto|required` to search and context-pack contracts
- keep `off` as the default and preserve lexical result shape and ordering
- make `auto` fall back to unchanged lexical retrieval on every semantic failure
- make `required` return the structured `semantic_unavailable` MCP error
- apply metadata filters before vector scoring
- select each note's best cosine-scoring chunk as its semantic candidate
- combine lexical and semantic ranks with reciprocal rank fusion using `k=60`
- add optional `hybrid-v0.1` diagnostics only when semantic retrieval participates
- keep production provider registration and MCP build tools disabled

Verification:

- test missing providers and indexes, query-provider failures, stale coverage,
  incompatible identity, corrupt databases, metadata filters, context budgets,
  MCP schemas, and mode-specific errors
- add Korean, English, and mixed-language fixtures with a deterministic test
  provider; pipeline Recall@5 and MRR both equal 1.0 on three queries
- treat these fixture scores as pipeline verification, not production model quality
- the automated suite passes 41 tests

### Implementation Checkpoint: Local Sentence-Transformers Adapter

Decision:

- register `sentence-transformers` as the first optional production adapter
- keep its dependency in the `local-embeddings` extra and import it only when selected
- require exact model and revision values for every build
- use local cached model files by default; require `--allow-model-download` for acquisition
- keep `trust_remote_code=false` and use CPU unless a device is explicitly selected
- normalize embeddings during encoding and retain core vector validation
- keep search, status inspection, and the default installation free of model downloads
- hold the public `v0.3.0` release until production-model evaluation and all gates pass

Verification:

- injected backend tests cover cache-only loading, explicit download opt-in,
  remote-code rejection, device selection, normalized encoding, dimension
  discovery, and sanitized load failures
- the automated suite passes 44 tests without the optional runtime installed

### Decision: First Approved Multilingual Evaluation Model

Decision:

- approve `intfloat/multilingual-e5-small` for local evaluation only
- pin revision `fd1525a9fd15316a2d503bf26ab031a61d056e98`
- apply `query: ` to search queries and `passage: ` to indexed note chunks
- keep generic providers backward compatible through the original `embed` method
- add a fixed six-query Korean, English, and mixed-language evaluation fixture
- report lexical/hybrid Recall@5, MRR, timing, and derived index size
- require Recall@5 non-regression, hybrid Recall@5 `1.0`, and hybrid MRR `0.8`
- do not treat model selection or fixture success as authorization to release v0.3

Rationale:

- the 384-dimensional MIT-licensed model is a lower-cost first CPU baseline than
  the 768-dimensional E5 base and 1024-dimensional BGE-M3 candidates
- the exact revision makes model identity and derived indexes reproducible
- model-specific query/document roles are necessary for a valid E5 evaluation

Verification:

- role-aware embedding tests verify exact Korean query and passage prefixes
- metric and end-to-end harness tests verify the fixed report and gate contract
- the automated suite passes 48 tests without downloading a model

### Verification: Approved Model on Intel macOS

Result:

- use Python 3.12.13 because current Intel macOS PyTorch wheels do not support
  the project's Python 3.14 default or the attempted Python 3.13 runtime
- resolve `sentence-transformers 3.4.1`, PyTorch 2.2.2, and NumPy 1.26.4
- download only the approved E5 revision through explicit opt-in
- evaluate six tracked Korean, English, and mixed queries against three fixture notes
- record hybrid Recall@5 `1.0`, hybrid MRR `1.0`, and all gates passing
- repeat with Hugging Face and Transformers offline modes forced; quality results match
- record warm local hybrid query median `49.77 ms`, p95 `98.53 ms`, and a
  45,056-byte three-chunk derived index

Interpretation:

- the adapter, revision pin, prefix roles, cache-only path, and evaluation gates
  are operational on this Intel Mac
- the tiny fixture validates behavior but is not sufficient for broad model
  quality claims or production-scale latency estimates

### Implementation Checkpoint: Explicit Semantic Runtime Injection

Decision:

- keep semantic runtime `off` unless `COGNITIVEOS_SEMANTIC_RUNTIME=local`
- require provider, model, and immutable revision environment values together
- forbid model download in search and MCP runtime paths
- share one runtime loader between search CLI and basic/FastMCP servers
- preserve lexical startup and `auto` fallback when provider configuration or
  local cache loading fails; keep `required` as `semantic_unavailable`
- let launchers select a compatible interpreter through `COGNITIVEOS_PYTHON`
- automatically prefer `.venv-embeddings312` for Intel macOS local semantic mode
- do not commit an active device-specific semantic configuration

Verification:

- tests cover default-off non-loading, exact configuration, partial and invalid
  settings, sanitized load failure, lexical fallback, required failure, and
  successful provider injection
- actual offline MCP launcher required-mode search returns the expected Korean
  note first with `semantic_used=true`
- actual offline search CLI returns the same result and JSON diagnostics
- the automated suite passes 52 tests

### Verification: Actual Vault Embedding Baseline

Result:

- build the derived embedding index offline from 42 Markdown notes and 327 chunks
- verify SQLite integrity, exact model revision, 384 dimensions, and full coverage
- record a 45.99-second full rebuild and 10.44-second all-reused incremental run
- record a 1.3 MB derived index and six-query required-mode median of 71.84 ms
- verify the real MCP launcher exposes 9 tools and returns semantic diagnostics
- reproduce the full Markdown checksum immediately before and after model build
- establish a separate checksum for 9 Git-ignored private Markdown files so
  tracked evaluation documentation can change without weakening the no-write gate

Decision:

- retain the derived index locally under `.pkm-index`; never commit it
- use the private-note aggregate checksum as the source-safety release gate
- defer other-device baselines as previously scoped

### v0.3 Stabilization Audit

Finding:

- all planned read-only semantic features are implemented
- MCP duplicated the package development version as a literal string
- the embeddings document still described implemented modes and model
  evaluation as future or deferred
- the historical v0.1 release document did not clearly separate v0.3 feature
  completion from final release operations

Decision:

- source MCP server identity from the package `__version__`
- assert pyproject, package, and MCP versions match
- assert exactly 9 MCP tools and no approved writeback tool names
- mark the v0.3 implementation feature-complete
- create `System/docs/release-v0.3.md` as the canonical readiness checklist
- keep `0.3.0a1` until stacked branches are integrated and a fresh checkout passes
- require explicit approval before version bump, tag, push, or GitHub Release

Verification:

- the stabilization suite passes 53 tests in the default environment
- release blockers are operational integration and publication steps, not
  missing semantic feature implementation

### Verification: Clean v0.3 Release-Candidate Worktree

Result:

- collect the complete linear semantic history as `codex/v03-release-candidate`
- check out detached commit `9cc89f8` in a clean `/tmp` worktree
- install default development and MCP dependencies into a new Python 3.14 environment
- pass 53 tests, 26 subtests, 9-tool discovery, and writeback-disabled checks
- build `0.3.0a1` wheel and sdist and install the wheel in another clean environment
- verify all four command-line entry points from the installed package
- install the Intel local-embedding extra in a new Python 3.12 environment
- pass 53 tests and the forced-offline pinned-model quality evaluation

Decision:

- mark clean-worktree, packaging, wheel-install, and dual-runtime gates complete
- keep main integration, final version bump, release notes, release-commit smoke,
  tag, push, and GitHub Release pending

### v0.3 Local Main Integration and Release-Note Draft

Decision:

- fast-forward local `main` from `0f86272` to verified release-candidate commit
  `c710d5d` without creating a merge commit
- retain `0.3.0a1` after integration
- create `codex/v03-release-prep` for subsequent release preparation
- draft `System/docs/release-notes-v0.3.0.md` without publishing it
- keep remote push, final version bump, tag, and GitHub Release pending explicit approval

Result:

- the complete semantic history is integrated into local `main`
- release scope, model identity, safety, verification, upgrade notes, and
  exclusions are captured in the release-note draft

### v0.3.0 Final Release Branch

Decision:

- create `codex/v03-final-release` from integrated local `main`
- change package and MCP identity from `0.3.0a1` to `0.3.0`
- promote release notes from draft to release-candidate status
- preserve historical alpha verification records as historical evidence
- rerun every release gate against the exact release commit
- stop before tag, push, and GitHub Release for explicit publication approval

### v0.3 Final Packaging Fix

Finding:

- the exact release worktree built successfully before the Intel embedding
  environment existed
- after `.venv-embeddings312` was created, Hatch attempted to include that
  environment in the sdist and rejected its external absolute Python symlink

Decision:

- ignore `.venv-*` directories as repository-local runtime artifacts
- exclude `.venv*`, `.pkm-index`, and `dist` from every Hatch build target
- require the final sdist build to pass while both default and embedding virtual
  environments are present
