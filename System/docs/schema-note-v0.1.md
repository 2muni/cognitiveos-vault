# Note Schema v0.1

## Common Note Object

Every Markdown file is interpreted as a `Note`.

```yaml
id: string
type: inbox | concept | source | entity | project | map | journal | system | output
title: string
aliases: string[]
status: inbox | seed | active | evergreen | archived
created_at: datetime
updated_at: datetime
tags: string[]
domains: string[]
links: string[]
sources: string[]
confidence: number
visibility: private | shared | public
```

## Runtime Defaults

If a field is missing, the indexer applies runtime defaults without editing the source file:

- `id`: stable hash derived from the relative path
- `type`: frontmatter type, path-inferred type for known operational folders, or `inbox`
- `title`: frontmatter title, first heading, or filename stem
- `status`: `seed`
- `aliases`, `tags`, `domains`, `links`, `sources`: empty list
- `confidence`: `0.5`
- `visibility`: `private`

## Initial Types

| Type | Meaning |
| --- | --- |
| `inbox` | Unprocessed capture |
| `concept` | Atomic long-term concept |
| `source` | External source, summary, citation, or research note |
| `entity` | Person, organization, product, technology, place |
| `project` | Goal-oriented workspace |
| `map` | Map of Content or navigation hub |
| `journal` | Time-based thinking record |
| `system` | Governance, schema, template, decision, prompt |
| `output` | Essay, report, design, code plan, deliverable |

## Parsed Derived Fields

The parser derives these fields for indexing:

- `path`: vault-relative file path
- `checksum`: SHA-256 of the Markdown file
- `body`: Markdown body without frontmatter
- `headings`: heading text, level, and line number
- `outgoing_links`: wikilinks and Markdown links
- `body_preview`: shortened body text for search results

Derived fields are not written back to Markdown in v0.1.

`aliases` are optional alternate names. In `0.4.0a1` development they are
included in the derived lexical title payload and backlink target resolution;
the canonical `title` remains the display identity.

## Path-inferred Types

Folder location is not the only source of meaning, but the indexer may use it as a runtime hint when frontmatter is missing.

| Path prefix | Inferred type |
| --- | --- |
| `AGENTS.md` | `system` |
| `README.md` | `system` |
| `System/` | `system` |
| `00_Inbox/` | `inbox` |
| `01_Concepts/` | `concept` |
| `02_Entities/` | `entity` |
| `03_Projects/` | `project` |
| `04_References/` | `source` |
| `05_Journal/` | `journal` |
| `06_Maps/` | `map` |

This inference is index-only and does not edit source Markdown.
