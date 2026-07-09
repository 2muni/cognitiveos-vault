# CognitiveOS Architecture v0.1

## Definition

CognitiveOS is a Markdown-first, local-first, MCP-addressable personal knowledge system.

Obsidian Markdown files are the source of truth. Indexes, embeddings, graph projections, summaries, and MCP caches are derived artifacts that can be deleted and rebuilt from the vault.

## Design Principles

- Markdown is the durable record.
- YAML frontmatter is the machine-readable contract.
- Folder location is operational context, not the semantic source of truth.
- Retrieval quality comes before autonomous reasoning.
- The first MCP surface is read-only.
- Any future writeback tool requires explicit approval and a separate design pass.

## Layers

1. Storage Layer: Markdown, YAML frontmatter, attachments.
2. Semantic Structure Layer: note types, lifecycle status, links, sources, entities, projects.
3. Index Layer: SQLite metadata, full-text search, links, headings.
4. Retrieval Layer: keyword/FTS search, metadata filters, evidence snippets.
5. Context Layer: search results compressed into a context pack.
6. Model Layer: local LLM, cloud LLM, Codex, embeddings, rerankers.
7. MCP Interface Layer: resources and tools exposed to Codex or other clients.
8. Agent Workflow Layer: review, synthesis, source distillation, project planning.

## MVP Scope

The v0.1 implementation is a read-only knowledge interface:

- scan Markdown files under a vault root
- parse frontmatter, headings, wikilinks, and Markdown links
- index metadata and body text in SQLite/FTS
- search notes with evidence snippets
- read notes by id or path
- expose read-only MCP tools when the MCP runtime is installed

## Out of Scope

- automatic edits to Markdown notes
- frontmatter migration
- vector DB, graph DB, embeddings
- autonomous agents
- remote MCP exposure
- destructive tools

## Data Flow

```text
Vault Markdown
  -> scanner
  -> parser
  -> SQLite/FTS index
  -> retrieval API
  -> context pack
  -> MCP tools/resources
  -> Codex or local client
```

## Permission Boundary

The vault root is the maximum read boundary. All path access must resolve inside the configured vault root. The implementation must reject absolute paths or traversal attempts that escape the vault.
