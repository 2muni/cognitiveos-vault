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

Stores outgoing links parsed from Markdown.

```sql
source_note_id TEXT NOT NULL
target TEXT NOT NULL
link_type TEXT NOT NULL
line INTEGER
```

### `headings`

Stores headings for navigation and context packing.

```sql
note_id TEXT NOT NULL
level INTEGER NOT NULL
text TEXT NOT NULL
line INTEGER NOT NULL
```

### `fts_notes`

SQLite FTS5 table for title, body, headings, and path search.

### `index_runs`

Records index rebuild metadata: run id, started time, completed time, note count, and status.

## Reindex Rule

Reindexing the same file must update the existing row and replace derived links/headings/FTS rows. It must not create duplicate notes.
