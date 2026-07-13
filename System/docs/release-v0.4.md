# CognitiveOS v0.4 Release Readiness

## Status

Feature status: complete and integrated into `main`.

Release status: stabilization; not yet a release candidate.

Current development identity: `0.4.0a1`.

Latest published stable release: `v0.3.0`.

Do not create or publish `v0.4.0` until every required release operation below
has passed against one exact commit and the user explicitly approves
publication.

## Implemented v0.4 Scope

- deterministic read-only note-contract validation and six CLI entry points
- capture and durable v0.2 templates with placeholder-safe validation
- aliases in lexical candidate generation, ranking, backlinks, and suggestion
  deduplication
- typed `frontmatter_link` and `frontmatter_source` graph edges
- conservative graph identity resolution across id, path, stem, title, and
  aliases
- outgoing/incoming graph-aware related-note ranking
- graph-connected context-pack source selection with note-type diversity
- service-local graph adjacency caching with SQLite and WAL invalidation
- valid searchable `system` identities for layer `__SPECS__.md` files
- path-derived runtime identities for versioned authoring templates
- package-version identity in both basic MCP and FastMCP stdio handshakes

## Passed Integration Gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Package and MCP development versions match | Pass | automated invariant and launcher smoke |
| MCP exposes exactly 9 read-only tools | Pass | tests and environment verification |
| Writeback tools remain absent | Pass | tool-set assertion |
| Full automated suite | Pass | 75 tests with `ResourceWarning` promoted to error |
| Actual-vault validation has no errors | Pass | 56 files, 0 errors, 10 advisory warnings |
| Lexical index cardinality | Pass | 56 notes, unique ids, unique paths, and FTS rows |
| SQLite integrity | Pass | `PRAGMA integrity_check = ok` |
| Layer specification retrieval | Pass | `system_spec_concepts` ranked first for its title query |
| Graph cache invalidation | Pass | normal rebuild, direct mutation, and WAL tests |
| Default semantic and writeback boundaries | Pass | semantic off, writeback disabled |
| Installed CLI launchers after vault move | Pass | non-editable local install; all six `--help` commands |

The 10 validator warnings are non-blocking authoring guidance. Eight come from
tracked retrieval fixtures and two describe one existing journal note. A clean
strict-mode report is not a v0.4 release condition unless the contract is
changed in a separate decision.

## Remaining Required Release Operations

- [ ] create a release-candidate branch from integrated `main`
- [ ] verify a detached clean worktree with a fresh Python 3.14 environment
- [ ] run the full suite in the supported Intel local-embedding Python 3.12
      environment
- [ ] build wheel and sdist after both local runtime directories exist
- [ ] inspect artifacts for private notes, derived indexes, model files, and
      local virtual environments
- [ ] install the wheel alone and verify all six CLI entry points
- [ ] repeat the pinned multilingual model evaluation with networking disabled
- [ ] rebuild actual-vault lexical and embedding indexes from the exact release
      commit
- [ ] confirm MCP initialize, 9 tools, invalid-call handling, required semantic
      search, writeback-disabled state, and SQLite integrity
- [ ] confirm private Markdown checksums are unchanged by release verification
- [ ] change package and MCP identity from `0.4.0a1` to `0.4.0`
- [ ] write `System/docs/release-notes-v0.4.0.md`
- [ ] cross-check README, roadmap, schemas, package metadata, and release notes
- [ ] obtain explicit user approval before the release commit, annotated tag,
      push, assets, and GitHub Release

## Explicitly Deferred and Non-blocking

- writeback implementation and authorization changes
- graph database storage
- local LLM generation
- semantic retrieval enabled by default
- automatic model downloads or background embedding
- note migrations, bulk normalization, renames, and deletes
- other-device and Codex/VS Code visual discovery checks

These require separate plans and do not belong in v0.4 merely to increase the
feature count.

## Decision Rule

The v0.4 implementation is feature-complete because its planned read-only
contract, retrieval, graph, and indexing units are integrated and passing their
tests. It becomes a release candidate only when the clean-worktree, packaging,
dual-runtime, offline-model, and actual-vault gates pass against one exact
commit. It becomes released only after identity is changed to `0.4.0`, the
exact commit is explicitly approved, and immutable publication succeeds.
