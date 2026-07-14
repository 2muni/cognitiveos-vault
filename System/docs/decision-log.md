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

### Publication: CognitiveOS v0.3.0

Result:

- fast-forward release commit `4f52367681387db474c4b79b02c3a06cfa45298a`
  to `origin/main`
- create and push annotated tag `v0.3.0` pointing to that exact commit
- publish the non-draft, non-prerelease GitHub Release on 2026-07-12
- verify public tag peeling, remote main, release URL, package identity, and
  post-release shallow clone tests

Follow-up:

- correct the release-note status text from release-candidate to published
- keep the immutable `v0.3.0` tag unchanged; this correction is a separate
  post-release documentation commit

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

### Note Contract and Read-only Validation v0.2 Design

Finding:

- the existing nine note types remain sufficient for the current vault
- all v0.1 templates require thirteen common fields, while several fields are
  stored but not consumed by search, backlink, or permission behavior
- body links are indexed as relationships, but frontmatter `links` and
  `sources` are not graph edges
- actual user-note metadata shows lifecycle ambiguity between `type: inbox`
  and `status: active`
- no read-only validator currently detects duplicate ids, enum errors,
  placeholder values, invalid field types, or unusual lifecycle combinations

Decision:

- retain the v0.1 note type vocabulary
- define separate capture and durable authoring profiles
- keep body wikilinks and Markdown links as the current canonical relationship
  representation
- design `cognitiveos-validate` as a deterministic read-only command with text
  and JSON output
- treat duplicate ids and invalid schema values as errors while introducing
  lifecycle and authoring-profile checks as warnings
- preserve v0.1 templates and add future v0.2 templates separately
- prohibit automatic note edits or migrations under this design

Documented in:

- `System/docs/note-contract-v0.2.md`

Implementation checkpoint:

- add `src/cognitiveos/validation.py` with immutable diagnostics and reports
- keep validation independent from SQLite and all writeback paths
- expose pure `validate_note_file` and `validate_vault` APIs
- cover deterministic ordering, strict exit behavior, path safety, private body
  non-disclosure, and no-write behavior
- identify eight existing user-scope noncanonical note types that the current
  parser silently treats as inbox; do not modify those notes automatically
- pass 58 total tests after the first validator unit

Second implementation checkpoint:

- add `cognitiveos-validate` with deterministic text and JSON output
- implement `--scope user|all`, `--strict`, and stable exit codes
- add nine templates under `System/templates/v0.2/` while preserving v0.1
- omit empty optional metadata arrays from v0.2 templates
- keep the first H1 as the default human-readable title
- confirm all v0.2 templates pass validation, including placeholder exemptions
- retain the immutable public v0.3.0 wheel as a five-entry-point artifact and
  describe the validator as development-tree functionality until a future
  package release
- pass 61 total tests after the CLI and template unit

Third implementation checkpoint:

- add type-specific recommended section checks for all nine note types
- aggregate all missing sections into one warning per note after the initial
  actual-vault run produced excessive repeated diagnostics
- add source locator detection for URL, DOI, locator metadata, and body text
- exempt canonical templates from authoring-completeness warnings while still
  validating their schema
- run the validator against 55 scanner-visible Markdown files without exposing
  paths or body text
- record 8 existing type errors, 18 warnings, and 3 information diagnostics
- preserve Markdown checksums and the existing lexical index modification time
- pass 62 total tests

### Alias-aware Retrieval Development

Decision:

- begin post-v0.3 development as package version `0.4.0a1`
- append normalized aliases to the derived FTS title payload while preserving
  `notes.title` as the canonical display title
- avoid a SQLite schema migration because lexical indexes are disposable and
  can be rebuilt from Markdown
- rank exact canonical titles above exact aliases
- include aliases in backlink target candidates
- suppress link suggestions when the source already links to a target alias

Safety and compatibility:

- do not edit note frontmatter or body content
- ignore malformed non-list aliases during indexing; the validator reports the
  schema error separately
- require a lexical index rebuild before existing vault aliases become
  searchable
- keep the public `v0.3.0` tag, wheel, source archive, and release unchanged

Implementation checkpoint:

- pass 63 automated tests, including English and Korean alias search, exact
  title precedence, alias backlinks, suggestion deduplication, and idempotent
  reindexing
- rebuild the actual-vault lexical index with SQLite integrity `ok`
- confirm every current alias frontmatter value is present in its derived FTS
  title payload
- preserve the scanner-visible and private Markdown aggregate checksums before
  and after the rebuild

### Frontmatter Relationship Edge Indexing

Decision:

- parse valid string-list values from `links` and `sources` into the existing
  derived `links` table without a schema migration
- use `frontmatter_link` and `frontmatter_source` edge types and `line=NULL`
- normalize full wikilinks and Markdown links to their targets while preserving
  raw ids, titles, aliases, paths, and URLs
- collapse case-insensitive duplicates within each frontmatter field
- keep body links and frontmatter relationships available together through
  `read_note`, backlinks, and link-suggestion deduplication
- return each backlink source note once when multiple edges reach the same
  target

Safety and compatibility:

- do not rewrite or migrate source Markdown
- ignore malformed non-list or non-string values during parsing; retain the
  validator's schema error
- remove `frontmatter_relationship_not_indexed` because valid relationships are
  now operational graph edges
- require a lexical index rebuild to populate existing frontmatter edges

Implementation checkpoint:

- pass 64 automated tests, including wrapper normalization, duplicate collapse,
  typed edge persistence, backlink deduplication, and suggestion suppression
- rebuild the actual-vault index with SQLite integrity `ok`
- confirm actual frontmatter edges use only `frontmatter_link` or
  `frontmatter_source` and always store `line=NULL`
- reduce actual-vault information diagnostics from 3 to 0 while preserving the
  existing 8 errors and 18 warnings
- preserve scanner-visible and private Markdown aggregate checksums before and
  after reindexing

### Graph-aware Related Notes and Context Selection

Decision:

- resolve derived graph targets against note id and path first, then filename
  stem, canonical title, and aliases using casefolded identity maps
- reject ambiguous identities rather than linking one edge to multiple notes
- rank direct outgoing neighbors ahead of incoming neighbors in
  `get_related_notes`, then fill with lexical results
- retain note-type diversity in context packs while preferring a candidate
  connected to an already selected source within the eligible type
- expose deterministic `graph-related-v0.1` and
  `type-diverse-graph-v0.1` diagnostics
- do not add graph boosts to generic `search_notes`

Rationale:

- explicit author relationships should dominate inferred textual similarity in
  a related-notes view
- context packs benefit from coherent evidence clusters without sacrificing
  source-type diversity or lexical/semantic candidate generation
- conservative ambiguity handling prevents incorrect knowledge edges

Safety and compatibility:

- use the existing disposable SQLite links projection; no graph database or
  Markdown migration is introduced
- preserve existing result fields and add retrieval/selection diagnostics only
- keep context token accounting based on rendered evidence text, not diagnostic
  metadata

Implementation checkpoint:

- pass 68 automated tests, including outgoing/incoming ordering, lexical
  fallback, graph-aware type diversity, strong-identity precedence, and
  ambiguous-alias rejection
- rebuild the actual-vault lexical index with SQLite integrity `ok`
- resolve four current graph pairs across five graph-connected notes without
  exposing note paths or contents in the audit
- complete actual-vault related-note and context-pack graph smoke checks
- preserve scanner-visible and private Markdown aggregate checksums before and
  after reindexing

### Graph Adjacency Cache

Decision:

- cache one resolved graph adjacency object per retrieval service instance
- use main SQLite and optional WAL mtime/size signatures for the fast hit path
- confirm changed signatures with latest index run id, status, indexed count,
  live note count, and link count
- rebuild once when the generation changes during construction and avoid
  caching when a second concurrent change is detected
- never share mutable adjacency objects across service instances

Rationale:

- backlink, related-note, and context-pack calls otherwise reread all notes,
  aliases, and links independently
- file signatures make the common hit path cheap, while index metadata and
  counts make invalidation auditable
- WAL awareness prevents stale graph results when SQLite writes have not yet
  checkpointed into the main database file

Implementation checkpoint:

- pass cache-hit, normal reindex, same-size direct mutation, WAL mutation, and
  service-isolation tests
- reduce actual-vault graph cache hits from about 1.78 ms to roughly
  0.03–0.05 ms per call on this device while returning the same adjacency
  object

### Layer Specification Contract and Template Runtime Identity

Decision:

- treat files named `__SPECS__.md` as durable `system` notes with explicit,
  layer-specific stable ids
- preserve their numbered, layer-specific body structure instead of requiring
  the generic system heading profile
- continue enforcing all frontmatter, status, placeholder, and duplicate-id
  diagnostics on layer specifications
- assign files under `System/templates/` deterministic path-derived runtime ids
  rather than indexing their authoring placeholder ids

Rationale:

- layer specifications are searchable operational knowledge, not validator or
  index exclusions
- `system_readme` duplicated the existing `system` semantic type and caused the
  parser to fall back to `inbox`
- v0.1 and v0.2 templates intentionally share placeholder ids, so treating
  those placeholders as runtime identity caused one version to overwrite the
  other in the derived index

Implementation checkpoint:

- reduce actual-vault validation from 8 errors and 18 warnings to 0 errors and
  10 warnings without changing specification prose
- index all 55 scanner-visible Markdown files as 55 notes, 55 unique ids, 55
  unique paths, and 55 FTS rows with SQLite integrity `ok`
- confirm a layer specification is searchable as a `system` note
- pass 74 automated tests with `ResourceWarning` promoted to an error

### v0.4 Stabilization Boundary

Decision:

- mark the planned read-only v0.4 feature scope as implemented and integrated
  into `main`
- retain package identity `0.4.0a1` until exact release-candidate verification
  is complete
- track v0.4 release readiness separately in `System/docs/release-v0.4.md`
- treat the remaining validator warnings as advisory data-quality work rather
  than release-blocking product errors
- require clean-worktree packaging, dual-runtime regression, actual-vault
  integrity, release notes, and explicit publication approval before `v0.4.0`

Rationale:

- alias retrieval, typed frontmatter edges, graph-aware ranking, graph caching,
  note validation, layer specifications, and runtime identity are now one
  integrated read-only feature set
- feature completion and publication are different states; keeping them
  separate prevents an alpha package identity from being mistaken for a stable
  release
- validator warnings intentionally communicate authoring guidance and do not
  indicate parser, index, retrieval, or safety failures

### v0.4.0 Final Release Preparation

Decision:

- promote package and MCP identity from `0.4.0a1` to `0.4.0` only after the
  release-candidate baseline passes clean-worktree, dual-runtime, packaging,
  forced-offline model, actual-vault, MCP, and private-checksum gates
- preserve the alpha verification commit and artifact hashes as historical
  evidence rather than rewriting them to stable-version values
- prepare `System/docs/release-notes-v0.4.0.md` on a dedicated final-release
  branch
- require the exact stable-version commit to repeat every release gate before
  an annotated tag, push, asset upload, or GitHub Release
- stop before publication for explicit user approval

Rationale:

- version promotion changes package artifacts and therefore requires a fresh
  exact-commit verification even when product code is otherwise unchanged
- separating historical alpha evidence from stable artifact evidence keeps the
  release audit reproducible
- a publication pause prevents verification authority from being treated as
  authorization to mutate remote `main`, tags, or release state

### Publication: CognitiveOS v0.4.0

Decision:

- publish `v0.4.0` only after the final source commit, clean dual-runtime
  verification, package artifacts, forced-offline model evaluation, actual-vault
  integrity, and private checksum gate have all passed
- tag exact release source commit `24a4d3e6b559b8eb1c7044e987e84793b1008d30`
  with annotated tag `v0.4.0`
- publish the public GitHub Release with the verified wheel and source
  distribution, then re-download both assets and compare SHA-256 values
- retain the merge commit on `main` because it has the same verified source tree
  as the tagged release commit

Publication record:

- published 2026-07-14
- GitHub Release: `https://github.com/2muni/cognitiveos-vault/releases/tag/v0.4.0`
- wheel SHA-256:
  `eeab9f871fb7399b3f8d953280f57a9f1a8cc0434b0f74d0030c512784bf3b69`
- source distribution SHA-256:
  `f574b76b73b33812cf8ad0c117959726f9bf6b16dd7e11c86356fc13abaedb32`

### v0.5 Operational Freshness Boundary

Decision:

- define v0.5 as a read-only operational reliability phase rather than adding
  another knowledge representation or generation feature
- introduce a deterministic source manifest and one side-effect-free status
  contract spanning validation, lexical state, and optional embedding state
- add explicit atomic `full|incremental` lexical publication while retaining
  `full` as the compatibility default
- preserve the existing nine-tool MCP boundary during the first implementation
  and expose unified status through Python and a dedicated CLI first
- keep writeback, background indexing, model download, graph databases, local
  LLM generation, migration, rename, and deletion outside v0.5

Rationale:

- Markdown remains authoritative, but operators currently lack one reliable
  answer for whether every disposable index reflects the current source set
- the lexical builder reparses all notes and can be made safer and faster by
  validating a temporary database before atomic publication
- source checksums and a deterministic vault manifest provide a portable
  freshness identity without exposing note content, metadata values, absolute
  paths, or timestamps
- separating inspection from repair prevents a status command from silently
  creating an index, loading a model, using the network, or mutating Markdown

Canonical plan:

- `System/docs/roadmap-v0.5.md`

Implementation checkpoint:

- add `vault-manifest-v0.1` and `vault-status-v0.1`
- expose `cognitiveos-status` as the seventh development CLI while preserving
  the published v0.4.0 six-CLI artifact record
- classify lexical and optional embedding state without opening either DB in
  write mode
- keep a missing embedding index compatible with a healthy lexical-only system
- return safe explicit rebuild commands for unhealthy derived state without
  exposing absolute paths or private note metadata
- retain exactly nine read-only MCP tools and leave writeback disabled
- pass 80 automated tests after adding five status and manifest tests

### v0.5 Atomic Full Lexical Publication

Decision:

- stop deleting rows from the active lexical database during a full rebuild
- build a complete sibling SQLite database and publish only after source,
  schema, count, FTS, foreign-key, and integrity validation succeeds
- open `VaultIndex` lazily so construction and failed first builds do not create
  an active database
- persist one build generation, `vault-manifest-v0.1`, and explicit full-build
  statistics in `index_runs`
- retain `index_vault() -> int` for compatibility while exposing structured
  full-build results to the CLI and future incremental implementation

Rationale:

- a disposable index should be replaceable without making a valid previous
  generation unavailable during parsing or validation
- checking the source manifest before parsing and immediately before publish
  detects notes added, removed, or changed during the build
- a temporary database permits strong failure injection tests without touching
  Markdown or requiring rollback logic against the active index

Implementation checkpoint:

- parser, validation, source-race, and `os.replace` failures preserve the prior
  active database byte-for-byte
- a failed first build leaves no active database
- temporary SQLite files are removed after both success and failure
- publication is rejected instead of replacing an index with an active,
  non-empty WAL sidecar
- all 85 automated tests pass with `ResourceWarning` promoted to an error

### v0.5 Incremental Lexical Publication

Decision:

- require an internally healthy, completed v0.5 lexical database before an
  explicit incremental build; missing or incompatible baselines require full
  rebuild rather than an implicit mode change
- classify source paths by checksum and parse only added or updated notes while
  reusing unchanged rows and deleting removed paths from all derived tables
- copy the active database to a temporary sibling, validate the complete
  manifest and FTS coverage, then atomically publish a new generation
- treat an unchanged manifest as a true no-op: no parser calls, no run row, no
  file publication, and no graph-cache invalidation
- expose `published` in `LexicalBuildResult` so automation can distinguish a
  changed incremental publication from a no-op

Rationale:

- explicit baseline compatibility prevents silently trusting legacy or corrupt
  derived state
- path/checksum classification is deterministic and keeps Markdown as the only
  authority while avoiding unnecessary parser work
- preserving the active database byte-for-byte on parser, validation, source
  race, SQLite sidecar, or replacement failure retains the Unit 2 safety model
- not touching the database on a no-op keeps service-local graph caches stable

Implementation checkpoint:

- added, updated, removed, and reused counts are persisted for changed builds
- full and incremental final databases are observably equivalent outside build
  history metadata
- no-op incremental runs reparse zero notes and preserve generation and bytes
- changed incremental runs invalidate graph adjacency caches after publication
- active WAL and rollback-journal sidecars block publication
- all 92 automated tests pass with `ResourceWarning` promoted to an error

### v0.5 Stabilization Baseline

Decision:

- integrate Units 1 through 3 through reviewed PRs #9 and #10 before starting
  release-candidate stabilization
- measure full, changed incremental, and no-op publication on the actual vault
  without altering private Markdown
- keep `0.5.0a1` and published stable `v0.4.0` unchanged until clean-worktree,
  packaging, forced-offline semantic, and exact-commit gates complete

Measured checkpoint:

- full publication: 58 notes in 1.21 seconds
- changed incremental publication: one added tracked System document and 58
  reused notes in 0.96 seconds
- no-op incremental publication: 59 reused notes in 0.42 seconds
- no-op database SHA-256, size, modification time, and generation are unchanged
- default Python 3.14 and local-embedding Python 3.12 each pass all 92 tests
- private Markdown baseline contains 9 files with aggregate digest
  `4f6886919d89d27024b71b966c3e74fcd43bffc45c24087978d8747c6ccb0435`

Completion checkpoint:

- detached clean-worktree checkpoint `d148e06` passes all 92 tests in new
  Python 3.14 and Python 3.12 local-embedding environments
- a wheel-only install reports `0.5.0a1` and exposes all seven CLI entry points
- pinned `multilingual-e5-small` forced-offline evaluation passes Recall@5 and
  MRR at `1.0`
- environment verification indexes 50 tracked notes and confirms MCP
  initialize, nine read-only tools, invalid-call errors, and writeback disabled
- wheel and source distribution output is byte-identical before and after
  creating local runtimes and `.pkm-index`; excluded state does not leak into
  artifacts
- actual-vault lexical and embedding states are healthy at 59 notes, with 509
  embedding chunks and both SQLite integrity checks returning `ok`
- Unit 4 is complete without changing package version `0.5.0a1`, stable tag
  `v0.4.0`, or any private Markdown
