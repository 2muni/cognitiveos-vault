# CognitiveOS v0.4 Release Readiness

## Status

Feature status: complete and integrated into `main`.

Release status: published on 2026-07-14.

Published package identity: `0.4.0`.

Latest published stable release: `v0.4.0`.

The immutable `v0.4.0` tag points to the exact verified release source commit.

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

- [x] create a release-candidate branch from integrated `main`
- [x] verify a detached clean worktree with a fresh Python 3.14 environment
- [x] run the full suite in the supported Intel local-embedding Python 3.12
      environment
- [x] build wheel and sdist after both local runtime directories exist
- [x] inspect artifacts for private notes, derived indexes, model files, and
      local virtual environments
- [x] install the wheel alone and verify all six CLI entry points
- [x] repeat the pinned multilingual model evaluation with networking disabled
- [x] rebuild actual-vault lexical and embedding indexes from the exact release
      commit
- [x] confirm MCP initialize, 9 tools, invalid-call handling, required semantic
      search, writeback-disabled state, and SQLite integrity
- [x] confirm private Markdown checksums are unchanged by release verification
- [x] change package and MCP identity from `0.4.0a1` to `0.4.0`
- [x] write `System/docs/release-notes-v0.4.0.md`
- [x] cross-check README, roadmap, schemas, package metadata, and release notes
- [x] obtain explicit user approval before the release commit, annotated tag,
      push, assets, and GitHub Release

## Release-candidate Verification Record

The release-candidate gates passed on 2026-07-13 against exact commit
`1aea1bade6f3654237d8c8c0dccc1542496e75fc` on branch
`codex/v04-release-candidate`. The detached clean worktree was
`/tmp/cognitiveos-v04-rc-1aea1ba`; the path is operational evidence and is not
part of the release artifact.

Clean Python 3.14 verification used Python 3.14.6 and a non-editable
`.[dev,mcp]` installation. Package metadata, basic MCP, and FastMCP all reported
`0.4.0a1`. All 75 tests passed with `ResourceWarning` promoted to an error, and
all six CLI entry points completed their `--help` command. MCP exposed exactly
9 read-only tools and no writeback tool.

The supported Intel embedding verification used Python 3.12.13,
Sentence Transformers 3.4.1, PyTorch 2.2.2, and NumPy 1.26.4. All 75 tests
passed under that runtime. The pinned model evaluation ran with Hugging Face and
Transformers offline modes enabled, using
`intfloat/multilingual-e5-small` at revision
`fd1525a9fd15316a2d503bf26ab031a61d056e98` with 384 dimensions. Hybrid
Recall@5 and MRR were both `1.0`; lexical Recall@5 and MRR were both `0.8333`.
Every quality gate passed.

The candidate artifacts were built after both runtime directories existed:

| Artifact | SHA-256 |
| --- | --- |
| `cognitiveos-0.4.0a1.tar.gz` | `051ab84235578fae1fcc8997b3a32dc18a421ce92ff48b88e141ae4cb9633392` |
| `cognitiveos-0.4.0a1-py3-none-any.whl` | `ac87e8e5882854b5954356ced211534f3d0b318d07c413c6413a57ffa5fea1e2` |

The source distribution contained only tracked private-folder placeholders; it
contained no private note content, local runtime, derived index, model weight,
or previous `dist` output. The wheel contained no private vault folder or
derived artifact. A wheel-only Python 3.14 environment imported version
`0.4.0a1`, and all six installed CLI entry points passed their smoke checks.

Actual-vault verification rebuilt the lexical index to 56 notes with 56 unique
ids, 56 unique paths, and 56 FTS rows. User-scope validation reported 0 errors
and the expected 10 non-blocking warnings. The embedding index was rebuilt
offline to 56 notes and 459 chunks, all at 384 dimensions, using the exact
pinned provider identity. Both SQLite databases returned `integrity_check =
ok`.

MCP initialization reported CognitiveOS `0.4.0a1`, exposed 9 tools, returned
`invalid_argument` for an empty search query, and exposed no writeback tool. A
required-mode search completed without fallback, with `semantic_used = true`
and semantic rank 1. The 9 ignored private Markdown files had the same aggregate
SHA-256 before and after verification:
`de2ca6bafe5764506a6d2f686b0ef02aeffd7d4c84b0a6c064f02e5866c7ed1f`.

This record establishes a verified `0.4.0a1` release-candidate baseline. The
exact final `0.4.0` release commit subsequently completed the version,
release-note, cross-document, explicit-approval, and publication gates above.

## Publication Record

`v0.4.0` was published on 2026-07-14. The annotated tag object
`4bf9e3c2b8ecc7720f0a8f4fac2317c45e3ceb24` peels to exact release source
commit `24a4d3e6b559b8eb1c7044e987e84793b1008d30`. The merged `main` commit
has the same source tree. GitHub Release assets were re-downloaded and their
SHA-256 digests matched:

| Asset | SHA-256 |
| --- | --- |
| `cognitiveos-0.4.0-py3-none-any.whl` | `eeab9f871fb7399b3f8d953280f57a9f1a8cc0434b0f74d0030c512784bf3b69` |
| `cognitiveos-0.4.0.tar.gz` | `f574b76b73b33812cf8ad0c117959726f9bf6b16dd7e11c86356fc13abaedb32` |

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
tests. It became a release candidate after the clean-worktree, packaging,
dual-runtime, offline-model, and actual-vault gates passed against one exact
commit. It was released after identity changed to `0.4.0`, the exact commit was
explicitly approved, and immutable publication succeeded.
