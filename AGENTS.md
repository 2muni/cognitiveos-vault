# CognitiveOS Vault Agent Guide

This repository is an Obsidian vault and the Markdown files are the source of truth. Treat generated indices, embeddings, graph projections, summaries, and MCP caches as derived artifacts.

## Default Codex Profile

Use the local Codex defaults in `.codex/config.toml`:

- Model: `gpt-5.5`
- Reasoning effort: `medium`
- Reasoning summary: `concise`
- Verbosity: `medium`
- Approval policy: `on-request`

Use higher reasoning only for architecture, migration, writeback, security, or MCP permission-boundary work.

## Vault Safety

- Prefer read-only analysis unless the user explicitly asks for file changes.
- Do not bulk rewrite notes, rename folders, or migrate frontmatter without an explicit plan and approval.
- Do not delete notes or assets unless the user explicitly asks for deletion.
- Treat `Assets/`, `.obsidian/`, and any generated index folders as sensitive operational areas.
- Preserve user-authored prose and links unless the requested change requires editing them.

## PKM Data Rules

- Markdown notes are durable records.
- YAML frontmatter is the machine-readable contract.
- Folder location is operational context, not the only source of meaning.
- Internal links express semantic relationships.
- References and personal synthesis should remain separable.

## MCP Implementation Rules

Start with read-only MCP capabilities:

- `search_notes`
- `read_note`
- `get_backlinks`
- `suggest_links`
- `summarize_source`
- `propose_moc`

Require explicit user approval for tools that write to the vault:

- `create_draft_note`
- `update_properties`
- `append_to_daily`
- any migration, rename, delete, or bulk normalization operation

MCP roots must be restricted to this vault. Reject path traversal and absolute paths outside the vault.

## Retrieval Rules

Prefer hybrid retrieval:

1. Scope by metadata and path.
2. Search with keyword or FTS.
3. Search with embeddings.
4. Rerank using title, headings, backlinks, freshness, and confidence.
5. Return note paths and evidence with generated answers.

Avoid presenting model inference as vault fact unless it is grounded in retrieved notes.

## Recommended Reasoning Levels

- Architecture and schema design: `high`
- MVP implementation and tests: `medium`
- Small templates or documentation edits: `low`
- Vault writeback, migrations, authorization, and security review: `high` or `xhigh`
