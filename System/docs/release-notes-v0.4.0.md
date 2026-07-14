# CognitiveOS v0.4.0 Release Notes

Status: Published on 2026-07-14. Tag: `v0.4.0`.

## Summary

CognitiveOS v0.4.0 improves the read-only knowledge contract and graph-aware
retrieval layer while preserving Markdown as the durable source of truth. It
adds deterministic note validation, capture and durable templates, alias-aware
search and backlinks, typed frontmatter relationship edges, and conservative
graph-aware related-note and context-pack selection.

The release does not add writeback. Semantic retrieval remains optional and
disabled by default, and all indexes remain disposable local artifacts.

## Highlights

- deterministic `cognitiveos-validate` CLI with text and JSON output
- user/all validation scopes, strict mode, stable diagnostics, and exit codes
- v0.2 capture and durable templates for all nine note types
- alias-aware lexical search, title reranking, backlink resolution, and link
  suggestion deduplication
- typed `frontmatter_link` and `frontmatter_source` edges derived from YAML
- conservative graph target resolution across ids, paths, stems, titles, and
  aliases
- outgoing-then-incoming graph-aware related-note ranking
- graph-connected context-pack source selection with note-type diversity
- service-local adjacency caching with SQLite and WAL invalidation
- valid searchable `system` identities for layer `__SPECS__.md` files
- deterministic path-derived runtime identities for versioned templates
- package-version identity in basic MCP and FastMCP handshakes
- six installed CLI entry points, including `cognitiveos-validate`

## Note Validation Contract

Validation is read-only and does not create an index. Errors identify invalid
schema or identity states. Warnings are authoring guidance and do not become
release blockers merely because existing notes predate the recommended
headings or stable-id guidance.

The canonical actual-vault release check scans 56 Markdown files with zero
errors and 10 non-blocking user-scope warnings. Note counts are device-dependent
and are not fixed acceptance criteria.

## Alias and Relationship Retrieval

Aliases are included in lexical candidate generation and receive explicit
ranking signals below the canonical title. They resolve as backlink targets and
prevent duplicate link suggestions when an existing link already uses an
alias.

Valid frontmatter `links` and `sources` lists are normalized into the derived
SQLite graph as `frontmatter_link` and `frontmatter_source` edges. Body
wikilinks and Markdown links retain their existing edge types. Ambiguous title
or alias targets remain unresolved instead of being attached to multiple notes.
No relationship is written back to Markdown.

## Graph-aware Retrieval

`get_related_notes` prioritizes direct outgoing graph neighbors, then incoming
neighbors, before lexical fallback. Context-pack selection preserves note-type
diversity while preferring graph-connected evidence within an eligible type.
Generic search does not receive a graph boost.

Resolved adjacency is cached per retrieval service. Cache invalidation uses the
main SQLite and WAL signatures together with index generation metadata and live
row counts. Mutable graph state is never shared across service instances.

## Safety and Compatibility

- Markdown and frontmatter remain the durable source of truth
- MCP exposes exactly 9 read-only tools
- writeback, migration, rename, archive, and delete tools remain absent
- default semantic mode remains `off`
- local model loading remains cache-only and requires an exact revision
- path traversal and paths outside the vault remain rejected
- derived lexical and embedding indexes may be deleted and rebuilt
- no frontmatter migration is required when upgrading from v0.3.0

## Verification Summary

- 75 automated tests pass in clean Python 3.14 and Intel embedding Python 3.12
  environments with `ResourceWarning` promoted to an error
- package, pyproject, basic MCP, and FastMCP identities agree
- wheel and source distribution build after both local runtime directories
  exist
- wheel-only installation exposes all six CLI entry points
- candidate artifacts contain no private notes, model weights, derived indexes,
  or local virtual environments
- forced-offline pinned-model evaluation passes all quality gates
- hybrid Recall@5 and MRR are both `1.0`
- actual-vault lexical and embedding rebuilds complete with SQLite integrity
  `ok`
- required semantic retrieval succeeds without lexical fallback
- private Markdown aggregate checksum remains unchanged

Detailed release-candidate evidence is recorded in
`System/docs/release-v0.4.md`.

## Upgrade Notes from v0.3.0

- rebuild the lexical index so aliases and frontmatter relationship edges are
  present in derived storage
- rebuild the optional embedding index after the lexical index is current
- existing lexical and semantic search call sites remain compatible
- adopt v0.2 templates for new notes as desired; existing notes need no bulk
  rewrite
- use `cognitiveos-validate` before indexing or release work to identify schema
  errors without modifying notes

## Excluded from v0.4.0

- writeback and authorization-boundary changes
- graph database storage
- local LLM generation
- semantic retrieval enabled by default
- automatic or background model downloads
- note migrations, bulk normalization, renames, and deletes
- other-device and Codex/VS Code visual discovery checks

## Publication Record

The exact `0.4.0` source commit `24a4d3e6b559b8eb1c7044e987e84793b1008d30`
was explicitly approved, tagged, pushed, and published on 2026-07-14. The
annotated `v0.4.0` tag is immutable and its wheel and source distribution were
downloaded again from GitHub after publication; their SHA-256 values matched the
release metadata. Historical tags must not be moved.
