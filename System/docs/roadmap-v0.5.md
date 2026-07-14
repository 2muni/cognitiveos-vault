# CognitiveOS v0.5 Operational Freshness Plan

## Status

Design approved on 2026-07-14. Unit 1 is implemented on the v0.5 development
branch; atomic lexical publication has not started.

The latest published stable release remains `v0.4.0`. This plan defines the
next read-only implementation boundary; it does not authorize writeback,
background indexing, note migration, or a `v0.5.0` release.

## Objective

Make derived CognitiveOS state trustworthy and inexpensive to maintain.

An operator should be able to answer, without loading a model or changing the
vault:

- whether the Markdown source is valid enough to index
- whether the lexical index represents the current Markdown set
- whether the optional embedding index is usable and compatible
- which derived state is missing, stale, incomplete, incompatible, or corrupt
- what explicit command would repair the affected derived state

The lexical builder should then update only changed source notes while
publishing a complete, validated database atomically.

## Problem Statement

`v0.4.0` provides validation, lexical and semantic retrieval, graph-aware
ranking, and separate embedding status. The remaining operational gap is that
these checks are distributed and the lexical builder always reparses and
rebuilds every note. There is no single read-only answer for whether all
derived state corresponds to the current Markdown source.

Because SQLite indexes and embeddings are disposable artifacts, freshness must
be established from source checksums rather than file timestamps alone.

## Release Boundary

v0.5 is a read-only operational reliability release.

Included:

- deterministic vault source manifest
- unified, side-effect-free vault status
- atomic full lexical rebuild
- atomic incremental lexical update
- explicit build statistics and freshness metadata
- regression and actual-vault integrity verification

Excluded:

- Markdown or frontmatter mutation
- writeback tools or approval flows
- automatic or background indexing
- model download or automatic semantic activation
- graph database or local LLM generation
- bulk migration, rename, archive, or deletion
- client UI and other-device verification as release blockers

The MCP server retains exactly nine read-only tools during the first v0.5
implementation. Unified status is introduced as a CLI and Python service
contract before any MCP surface is considered.

## Source Manifest Contract

The manifest version is `vault-manifest-v0.1`.

For every scanner-visible Markdown file, compute the existing source checksum
and vault-relative POSIX path. Sort records by path and hash this unambiguous
byte stream:

```text
UTF8(relative_path) + NUL + ASCII(source_sha256) + LF
```

The final digest is SHA-256 over the concatenated records. The manifest also
records the Markdown count and algorithm version. It must not include note
content, frontmatter values, absolute paths, file modification times, or model
state.

The same function must be used by status inspection and index publication.
Identical source sets must produce identical manifests across supported
platforms.

## Unified Status Contract

Introduce a seventh CLI entry point:

```text
cognitiveos-status [vault_root] [--db PATH] [--embedding-db PATH]
                   [--scope user|all] [--format text|json]
```

The JSON contract version is `vault-status-v0.1`. Existing CLI defaults and
entry points remain unchanged.

Required top-level fields:

- `status_version`
- `package_version`
- `overall_state`
- `vault`
- `validation`
- `lexical`
- `embedding`
- `safety`

The `vault` object contains only source count and manifest identity. Validation
contains aggregate severity counts, not note text or metadata values.

Lexical state values:

- `missing`
- `healthy`
- `stale`
- `incomplete`
- `corrupt`

Embedding state values:

- `missing`
- `healthy`
- `stale`
- `incomplete`
- `incompatible`
- `corrupt`

`overall_state` is `healthy`, `degraded`, or `unavailable`. A missing optional
embedding index does not degrade a healthy lexical-only system. Lexical
corruption or absence makes retrieval unavailable; stale or incomplete lexical
state and validation errors make it degraded. Warnings alone do not fail the
status command.

The `safety` object confirms that inspection was read-only, loaded no model,
used no network, and created no index. Status inspection must not instantiate a
builder whose constructor creates directories or databases.

Text and JSON output must be deterministic. JSON must preserve non-ASCII text,
although the normal status response should contain only counts, identities,
states, and redacted remediation commands.

## Lexical Index Publication

Extend the index CLI with an explicit mode:

```text
cognitiveos-index [vault_root] [--db PATH] [--mode full|incremental]
                  [--format text|json]
```

The default remains `full` in v0.5 to preserve existing scripts. Incremental
mode is an explicit optimization, not an autonomous background behavior.

Both modes publish atomically:

1. create a temporary database beside the target
2. for incremental mode, copy the last compatible healthy database
3. scan the current Markdown source and compute its manifest
4. parse and upsert only new or checksum-changed notes
5. remove notes whose paths no longer exist
6. validate schema, counts, unique identities, FTS coverage, manifest, and
   `PRAGMA integrity_check`
7. commit build metadata in the temporary database
8. replace the active database atomically

If parsing, validation, or publication fails, the last valid active database
must remain unchanged. Temporary files must be removable on the next run and
must not be treated as an active index.

The completed run records:

- build mode
- source manifest version and digest
- scanned note count
- added note count
- updated note count
- removed note count
- reused note count
- final note and FTS counts
- success status and completion time

Derived graph cache generation must change after any successful publication and
remain stable after a no-op incremental run.

## Compatibility

- Markdown and frontmatter contracts do not change.
- Existing SQLite databases remain disposable and may be rebuilt.
- Existing retrieval response fields and ranking behavior do not change.
- `semantic_mode=off|auto|required` behavior does not change.
- Embedding identity, chunking, and model pin do not change.
- The default semantic runtime remains `off`.
- No new MCP tool is added in the initial v0.5 scope.

## Implementation Units

### Unit 1: Manifest and Read-only Status

Status: Complete.

- implement one source-manifest function
- implement status data models and state precedence
- inspect validation, lexical, and embedding state without side effects
- add deterministic text and JSON CLI output
- add missing, healthy, stale, incompatible, incomplete, and corrupt fixtures

Implementation checkpoint:

- `vault-manifest-v0.1` hashes sorted vault-relative paths and source checksums
- `vault-status-v0.1` combines validation, lexical, and embedding state
- `cognitiveos-status` provides deterministic `text|json` output
- status responses expose only counts, identities, digests, states, and safe
  remediation commands
- inspection creates no index, loads no model, uses no network, and returns no
  absolute path or note content
- legacy v0.4 lexical databases are checked by deriving their manifest from
  stored path and checksum rows
- five new tests cover deterministic manifests, side effects, healthy/stale/
  incomplete coverage, corruption, incompatibility, and CLI output
- all 80 automated tests pass

### Unit 2: Atomic Full Publication

- move full lexical rebuilding to a temporary database
- validate before atomic replacement
- preserve the active database on injected parser, SQLite, and publication
  failures
- persist source manifest and run statistics

### Unit 3: Incremental Lexical Publication

- classify added, changed, removed, and unchanged notes by path and checksum
- reuse unchanged note, frontmatter, heading, edge, and FTS rows
- prove equivalence with a clean full rebuild
- invalidate graph caches only after a changed publication

### Unit 4: Stabilization

- run both modes against the actual vault
- record full, changed, and no-op timings without exposing note paths or content
- verify Markdown checksums before and after every build
- verify lexical and embedding integrity plus required semantic search
- repeat clean-worktree, packaging, MCP, and release gates

## Completion Gates

- all existing 75 tests pass before adding new coverage; the current suite has
  80 tests after Unit 1
- manifest output is identical across repeated runs and path separator variants
- status inspection creates and modifies no files
- status never imports or loads the optional model runtime
- status correctly distinguishes every documented state
- successful full and incremental builds produce equivalent observable index
  content
- a no-op incremental run reparses zero notes
- changed notes update their FTS, headings, metadata, aliases, and graph edges
- removed notes leave no orphaned derived rows
- injected failure preserves the previous active database byte-for-byte
- graph cache behavior remains deterministic across changed and no-op runs
- MCP still exposes exactly nine read-only tools with writeback disabled
- actual-vault Markdown and private-note checksums remain unchanged
- package, schema, roadmap, README, and release documentation agree

## Release Decision

Feature completion does not imply publication. After all four units pass, a
separate release-candidate audit must decide whether the package becomes
`0.5.0` and whether GitHub artifacts are published. Until then, `v0.4.0`
remains the stable release.
