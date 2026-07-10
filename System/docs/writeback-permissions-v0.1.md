# Writeback and Permissions v0.1

## Purpose

This document defines the permission boundary for future CognitiveOS writeback features.

The current MCP server remains read-only. Writeback is a later capability and must not be enabled implicitly by adding retrieval, summary, context, or planning tools.

## Permission Principles

- Markdown files are the durable source of truth.
- Generated indices and caches are derived artifacts.
- Read tools may inspect Markdown and derived indices.
- Write tools must never run without explicit user approval.
- Bulk write tools require a separate plan, preview, and approval.
- A write tool must only access paths inside the vault root.
- A write tool must refuse path traversal and absolute paths outside the vault.
- A write tool must preserve user prose unless the approved operation explicitly edits it.
- A write tool must produce an auditable diff or patch preview before modifying files.

## Capability Classes

| Class | Examples | Default |
| --- | --- | --- |
| Read | `search_notes`, `read_note`, `build_context_pack` | allowed |
| Propose | `suggest_links`, `propose_moc`, future draft generators | allowed, no writeback |
| Single-file write | `create_draft_note`, `append_to_daily`, `update_properties` | approval required |
| Multi-file write | migrations, renames, bulk frontmatter normalization | plan and approval required |
| Destructive | delete, archive, overwrite, mass rename | explicit approval required |

## Proposed Write Tools

Future write tools should start as disabled by default.

### `create_draft_note`

Creates a new Markdown file from an approved draft.

Required safeguards:

- vault-relative path only
- refuse overwrite unless explicitly approved
- require frontmatter validation
- return created path and checksum

### `update_properties`

Updates frontmatter only.

Required safeguards:

- read current file
- parse frontmatter
- generate before/after preview
- preserve body byte-for-byte where possible
- refuse malformed YAML unless explicitly repaired by a separate approved operation

### `append_to_daily`

Appends text to a daily note.

Required safeguards:

- date must be explicit
- append section must be explicit
- return preview before write
- create note only if approved

### `apply_patch_to_note`

Applies a constrained patch to one note.

Required safeguards:

- require exact current checksum
- reject stale patches
- preview diff
- write atomically

## Approval Flow

Writeback should use a two-phase flow.

Phase 1: propose

- tool returns intended path
- tool returns normalized frontmatter
- tool returns Markdown preview or diff
- tool returns risk class
- tool returns required approval scope
- no file is modified

Phase 2: apply

- user approves the exact proposal
- tool verifies the target checksum still matches
- tool writes atomically
- tool returns final checksum and changed paths

## Writeback Manifest

Every approved write should create a small manifest entry in a derived log folder, not in the note itself.

Suggested path:

```text
.pkm-index/writeback-log/YYYYMMDD-HHMMSS.json
```

Suggested fields:

```json
{
  "operation": "update_properties",
  "approved_at": "ISO-8601 datetime",
  "target_path": "vault-relative path",
  "before_checksum": "sha256",
  "after_checksum": "sha256",
  "changed_paths": ["vault-relative path"],
  "proposal": {},
  "result": {}
}
```

The writeback log is a derived artifact and remains Git-ignored by default.

## MCP Configuration Boundary

Read-only tools may remain enabled in `.codex/config.toml`.

Future write tools must be placed behind a separate config section or profile and should not be listed in `enabled_tools` by default.

Recommended future shape:

```toml
[mcp_servers.cognitiveos]
enabled_tools = [
  "search_notes",
  "read_note",
  "list_recent_notes",
  "get_backlinks",
  "get_related_notes",
  "suggest_links",
  "summarize_source",
  "propose_moc",
  "build_context_pack",
]
```

Select `Sol / high` for ordinary writeback review and `Sol / ultra` for high-impact migration or authorization-boundary work. Keep approval policy `on-request` or stricter.

## Non-goals for v0.1

- no automatic note creation
- no automatic frontmatter migration
- no writeback from retrieval tools
- no bulk rename
- no delete/archive operation
- no background write operation

## Decision

The v0.1 implementation remains read-only. Writeback is designed as a future two-phase proposal/apply system with explicit approval, checksum verification, vault-root path enforcement, and auditable derived logs.
