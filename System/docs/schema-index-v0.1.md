# Index Schema v0.1

## Storage

The MVP index is a SQLite database under `.pkm-index/cognitiveos.sqlite3`.

The index is derived from Markdown and can be deleted and rebuilt at any time.

## Tables

### `notes`

Stores one row per Markdown note.

```sql
note_id TEXT PRIMARY KEY
path TEXT UNIQUE NOT NULL
title TEXT NOT NULL
type TEXT NOT NULL
status TEXT NOT NULL
created_at TEXT
updated_at TEXT
mtime REAL NOT NULL
checksum TEXT NOT NULL
body_preview TEXT
frontmatter_json TEXT NOT NULL
```

### `note_frontmatter`

Stores searchable frontmatter key-value pairs.

```sql
note_id TEXT NOT NULL
key TEXT NOT NULL
value TEXT NOT NULL
PRIMARY KEY (note_id, key, value)
```

### `links`

Stores outgoing links parsed from the Markdown body and relationship
frontmatter.

```sql
source_note_id TEXT NOT NULL
target TEXT NOT NULL
link_type TEXT NOT NULL
line INTEGER
```

`link_type` values:

- `wikilink`: body wikilink
- `markdown`: body Markdown link
- `frontmatter_link`: normalized value from frontmatter `links`
- `frontmatter_source`: normalized value from frontmatter `sources`

Frontmatter wikilink display text and Markdown link labels are removed before
storage. Raw ids, titles, aliases, paths, and URLs are preserved as targets.
Frontmatter edges use `line=NULL`; duplicate targets are collapsed within each
frontmatter field. A rebuild replaces all derived edge rows.

### `headings`

Stores headings for navigation and context packing.

```sql
note_id TEXT NOT NULL
level INTEGER NOT NULL
text TEXT NOT NULL
line INTEGER NOT NULL
```

### `fts_notes`

SQLite FTS5 table for title, aliases, body, headings, and path search. Aliases
are appended to the derived FTS title payload; the canonical title stored in
`notes.title` remains unchanged.

The derived alias payload requires no Markdown or SQLite schema migration. A
full lexical index rebuild refreshes existing rows after an alias changes.

### `index_runs`

Records index rebuild metadata: run id, started time, completed time, note count, and status.

## Reindex Rule

Reindexing the same file must update the existing row and replace derived links/headings/FTS rows. It must not create duplicate notes.

## Alias Resolution

- exact canonical title matches rank above exact alias matches
- exact and partial aliases contribute explicit lexical ranking signals
- aliases are accepted as backlink targets alongside note id, path, title, and
  filename stem
- link suggestion deduplication treats canonical title and aliases as the same
  target note
- backlinks return each source note once even if it reaches the target through
  multiple canonical, alias, body, or frontmatter edges
