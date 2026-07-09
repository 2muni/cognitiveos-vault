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
- `type`: `inbox`
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
