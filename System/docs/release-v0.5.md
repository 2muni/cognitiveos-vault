# CognitiveOS v0.5 Release Readiness

## Status

Stabilization completed on 2026-07-14. The implementation is feature-complete,
but the latest published stable release remains `v0.4.0`; this document does
not authorize a `v0.5.0` version bump, tag, push, or GitHub Release.

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
- lexical index: healthy, 59 notes and 59 FTS rows
- embedding index: healthy, 59 notes, 509 chunks, dimension 384
- lexical and embedding `PRAGMA integrity_check`: `ok`
- actual-vault forced-offline required search: `semantic_used=true`, semantic
  rank 1
- MCP: package version `0.5.0a1`, nine read-only tools, invalid-call error, no
  writeback surface
- private Markdown: 9 files with the unchanged aggregate digest recorded above

Unit 4 is complete. A separate release-candidate task must still inspect the
final branch diff, decide whether to retain observation time, and explicitly
authorize any `0.5.0` version change or public release operation.

## Publication Boundary

Feature completion does not imply release publication. A later exact-commit
audit must decide whether to change `0.5.0a1` to `0.5.0`, write final release
notes, create an annotated tag, publish artifacts, or retain the development
version for more observation.
