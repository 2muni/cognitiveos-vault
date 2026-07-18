# CognitiveOS v0.5 Release Readiness

## Status

Stabilization completed on 2026-07-14. The release-candidate audit passed on
2026-07-18 against integrated `main` commit `3cd12ef`, and final publication was
explicitly authorized on 2026-07-18. Package identity is `0.5.0`; the verified
final source is published as the immutable `v0.5.0` release.

The v0.5 implementation is read-only. Markdown and frontmatter remain the
durable source of truth, the default semantic runtime remains `off`, MCP retains
exactly nine read-only tools, and writeback remains disabled.

## Implemented Scope

- deterministic `vault-manifest-v0.1`
- side-effect-free `vault-status-v0.1`
- atomic full lexical publication
- explicit atomic incremental lexical publication
- added, updated, removed, reused, and publication statistics
- no-op incremental runs that preserve database bytes and generation
- full/incremental observable-equivalence and failure-preservation tests

## Stabilization Gates

- actual-vault full, changed incremental, and no-op timing
- complete and private Markdown checksum preservation
- lexical and embedding SQLite integrity
- default and local-embedding runtime test suites
- MCP initialize, nine-tool surface, invalid-call behavior, and writeback absence
- forced-offline pinned-model required-mode retrieval
- clean-worktree wheel and source-distribution builds
- wheel-only installation and all seven development CLI entry points
- source artifacts exclude private notes, models, runtimes, and derived indexes

## Actual-vault Publication Measurements

Measured on the current Intel macOS device with Python 3.14.6. These are local
operational measurements, not cross-device performance guarantees.

| Build | Source state | Result | Wall time |
| --- | --- | --- | ---: |
| full | 58 notes | 58 added | 1.21 s |
| incremental changed | one tracked System document added | 1 added, 58 reused | 0.96 s |
| incremental no-op | unchanged 59-note manifest | 59 reused, `published=false` | 0.42 s |

The no-op run preserved generation
`980649b8a05948d38b713ec25d555dae`, database SHA-256
`6d2cf7bf7829679650b857c64aee8651b2612b0a9968715e522d715faf007683`,
file size, and modification time. No Markdown was parsed or written.

## Runtime Verification

- Python 3.14 default runtime: 92 tests pass with `ResourceWarning` promoted to
  an error
- Python 3.12 local-embedding runtime: 92 tests pass under the same warning
  policy
- private Markdown baseline: 9 files, aggregate digest
  `4f6886919d89d27024b71b966c3e74fcd43bffc45c24087978d8747c6ccb0435`

## Clean-worktree Verification

Detached checkpoint `d148e06` was installed into new runtime environments with
no dependency on the original vault environments.

- Python 3.14.6: 92 tests pass with `ResourceWarning` promoted to an error
- installed package identity: `0.5.0a1`
- all seven development CLI entry points return help successfully
- Python 3.12.13 local-embedding runtime: 92 tests pass
- pinned model forced-offline evaluation: Recall@5 `1.0`, MRR `1.0`, all gates
  pass
- clean environment verification: 50 tracked Markdown notes indexed, MCP
  initializes, exactly nine tools are exposed, invalid calls return errors, and
  writeback is disabled
- wheel-only installation succeeds and exposes all seven CLI entry points
- wheel and source distribution build twice with byte-identical output
- a second build performed after `.venv*` and `.pkm-index` creation excludes
  every runtime and derived index
- no private note, model weight, or local database is present in either
  artifact; the tracked `Assets/.gitkeep` placeholder remains intentional

## Final Local State

- validation errors: 0
- lexical index: healthy, 60 notes and 60 FTS rows
- embedding index: healthy, 60 notes, 521 chunks, dimension 384
- lexical and embedding `PRAGMA integrity_check`: `ok`
- actual-vault forced-offline required search: `semantic_used=true`, semantic
  rank 1
- MCP: package version `0.5.0`, nine read-only tools, invalid-call error, no
  writeback surface
- private Markdown: 9 files with the unchanged aggregate digest recorded above

## Release-Candidate Audit

The 2026-07-18 audit used integrated `main` commit `3cd12ef` as its immutable
code baseline. No code or package identity changed during the audit.

- no open issue, pull request, remote `v0.5.0` tag, or `v0.5.0` GitHub Release
  conflicts with final preparation
- fresh Python 3.14.6 and Python 3.12.13 environments each pass all 92 tests
  with `ResourceWarning` promoted to an error
- package and MCP identities both report `0.5.0a1`; exactly nine read-only MCP
  tools are exposed and writeback remains disabled
- forced-offline pinned-model evaluation passes Recall@5 `1.0`, MRR `1.0`, and
  every quality gate
- wheel and source distribution builds are byte-identical across two runs after
  local runtimes and derived indexes exist
- source artifacts contain no local runtime, derived database, model weight, or
  private Markdown
- wheel-only installation reports `0.5.0a1` and exposes all seven CLI entry
  points
- actual-vault lexical and embedding indexes are healthy, both SQLite integrity
  checks return `ok`, and required semantic retrieval reports
  `semantic_used=true` with semantic rank 1
- the canonical private Markdown digest remains
  `4f6886919d89d27024b71b966c3e74fcd43bffc45c24087978d8747c6ccb0435`

The audit approved a dedicated final-release branch to change `0.5.0a1` to
`0.5.0`, write final release notes, and repeat exact-commit gates. The user then
explicitly authorized publication through the verified tag and GitHub Release.

## Publication Boundary

The `v0.5.0` tag must point to the exact merged commit that passes the final
dual-runtime, packaging, MCP, actual-vault, offline-model, and checksum gates.
Historical tags must not be moved. Release assets must be built from that exact
tree and verified again after download from GitHub.
