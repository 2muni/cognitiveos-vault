# CognitiveOS v0.5.0 Release Notes

Status: Published on 2026-07-18. Tag: `v0.5.0`.

## Summary

CognitiveOS v0.5.0 makes disposable derived state easier to trust and cheaper
to maintain while preserving Markdown and frontmatter as the durable source of
truth. It adds a deterministic vault manifest, unified side-effect-free status,
atomic lexical publication, and explicit incremental indexing that parses only
new or checksum-changed notes.

The release remains read-only. Semantic retrieval is optional and disabled by
default, model loading remains cache-only, and writeback is not exposed.

## Highlights

- deterministic `vault-manifest-v0.1` over vault-relative paths and source
  checksums
- `vault-status-v0.1` and the new `cognitiveos-status` CLI
- validation, lexical, embedding, and safety state in deterministic text or JSON
- explicit `missing`, `healthy`, `stale`, `incomplete`, `incompatible`, and
  `corrupt` derived-state classifications
- atomic full lexical publication through a validated sibling SQLite database
- explicit incremental publication for added, updated, removed, and reused
  notes
- true no-op incremental runs that parse no Markdown and preserve database
  bytes, modification time, generation, and graph caches
- source-race, WAL, rollback-journal, parser, validation, and replacement
  failures preserve the last valid active database
- seven installed CLI entry points, including `cognitiveos-status`

## Operational Workflow

Inspect the vault without creating an index, loading a model, or using the
network:

```bash
cognitiveos-status . --format json
```

Create the first compatible v0.5 lexical baseline:

```bash
cognitiveos-index . --mode full --format json
```

Apply later source changes explicitly:

```bash
cognitiveos-index . --mode incremental --format json
```

An incremental run never silently falls back to full mode. Missing,
incompatible, stale, or corrupt baselines return explicit remediation instead.

## Safety and Compatibility

- Markdown and frontmatter remain the durable source of truth
- status inspection is read-only, loads no model, uses no network, and creates
  no index
- MCP exposes exactly nine read-only tools
- writeback, migration, rename, archive, and delete tools remain absent
- default semantic mode remains `off`
- local model loading remains cache-only and requires an exact revision
- existing retrieval response fields and ranking contracts remain compatible
- lexical and embedding indexes remain disposable local artifacts
- no frontmatter migration is required when upgrading from v0.4.0

## Verification Summary

- 92 automated tests pass in clean Python 3.14 and Intel embedding Python 3.12
  environments with `ResourceWarning` promoted to an error
- package, pyproject, basic MCP, and FastMCP identities agree
- wheel and source distribution build reproducibly after local runtime and
  derived-index directories exist
- wheel-only installation exposes all seven CLI entry points
- source artifacts contain no private notes, model weights, derived indexes, or
  local virtual environments
- forced-offline pinned-model evaluation passes Recall@5 and MRR at `1.0`
- actual-vault lexical and embedding indexes are healthy with SQLite integrity
  `ok`
- required semantic retrieval succeeds without network access
- private Markdown aggregate checksum remains unchanged

Detailed release evidence is recorded in `System/docs/release-v0.5.md`.

## Upgrade Notes from v0.4.0

- reinstall the package to receive the new `cognitiveos-status` entry point
- run one explicit full lexical build to establish v0.5 manifest and build-run
  metadata
- use explicit incremental mode for later changes
- rebuild the optional embedding index only when status reports it stale,
  incomplete, incompatible, or corrupt
- automation should use JSON output and inspect `overall_state`, component
  states, manifest identity, and `published`
- existing notes and frontmatter require no bulk rewrite

## Excluded from v0.5.0

- writeback and authorization-boundary changes
- automatic or background indexing
- automatic model downloads or semantic activation
- graph database storage
- local LLM generation
- note migrations, bulk normalization, renames, archive, and deletes
- other-device and client UI discovery as release blockers

## Publication Record

The annotated `v0.5.0` tag points to exact source commit
`bb53f508bd16e66a26a23e0c852cbcb5349b4a05`, which passed the final
dual-runtime, packaging, actual-vault, MCP, offline-model, and private Markdown
checksum gates. The public GitHub Release is:

```text
https://github.com/2muni/cognitiveos-vault/releases/tag/v0.5.0
```

Published assets were downloaded again and matched the exact build outputs:

```text
77eafcf89cd1af3a6878187fd7cef2f2b106c35ff1baa4e3bdc7452d8ce59ace  cognitiveos-0.5.0-py3-none-any.whl
8cc5b89a65db467e7ad4e23629a5fe3381ef88d8c47557e581552d158ea556ec  cognitiveos-0.5.0.tar.gz
```

Historical tags must not be moved.
