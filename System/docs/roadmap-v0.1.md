# CognitiveOS Roadmap v0.1

## Phase 0: Schema and Docs

- Architecture document
- Note schema
- MCP schema
- Index schema
- Roadmap

## Phase 1: Markdown Ingestion

- scan Markdown files under a vault root
- skip operational folders such as `.git`, `.obsidian`, `.trash`, `.pkm-index`
- parse frontmatter without editing source files
- derive title, note id, headings, body, and outgoing links

## Phase 2: SQLite/FTS Index

- create SQLite schema
- index notes, frontmatter, headings, links
- support rebuild and incremental upsert
- keep index under `.pkm-index/`

## Phase 3: Read-only MCP Server

- expose search and read tools
- enforce vault root path boundary
- return evidence paths and excerpts

## Phase 4: Retrieval and Context Packs

- implement FTS search with type filter
- build compact context packs for LLM use
- preserve evidence paths in every answerable result

## Phase 5: Writeback Design Review

- design approval flow
- define write tools separately
- audit migration and destructive-operation risks before implementation
