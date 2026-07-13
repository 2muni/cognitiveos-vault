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

## Graph Identity and Ranking

The SQLite links table is a derived graph projection, not a separate graph
database. Edge targets first resolve case-insensitively against the strong
identities note id and vault-relative path. If neither matches, filename stem,
canonical title, and aliases are considered. A named identity that resolves to
more than one note is ambiguous and is not converted into a graph connection.

`get_related_notes` ranks resolved outgoing neighbors before incoming
neighbors, then fills remaining result slots with lexical matches. A
bidirectional neighbor receives both signals. Context-pack selection keeps the
existing note-type-diversity rule, but within an eligible type prefers a
candidate directly connected to a source already selected. Generic
`search_notes` ranking is unchanged.

## Graph Projection Cache

Each retrieval service caches one resolved adjacency projection. A cache hit
first compares the main SQLite file and optional WAL file signatures, avoiding
SQL and full graph reconstruction. When either signature changes, the service
confirms the latest index run, run status, indexed-note count, live note count,
and link count before publishing a replacement cache.

If the generation changes while adjacency is being built, the service rebuilds
once. If it changes again during that retry, the result is returned for the
current call but is not cached. Caches are instance-local and contain only
derived index data; they are never serialized or written to Markdown.
