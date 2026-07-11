# Optional Embeddings Design v0.3

## Purpose

This document defines the implementation contract for optional semantic
retrieval after the v0.2 read-only baseline. Embeddings improve candidate recall
but never replace Markdown, frontmatter, links, SQLite/FTS, or evidence paths as
the source of truth.

Design status: complete. Implementation status: provider boundary and
deterministic chunking, separate SQLite storage, incremental/full builder, and
status/build CLI complete; production adapters and hybrid retrieval deferred.

## Invariants

- Embeddings are disabled by default.
- Markdown remains the durable record.
- The existing SQLite/FTS search remains available and is the default path.
- Embedding data is derived, Git-ignored, deletable, and fully rebuildable.
- Retrieval never writes to Markdown or frontmatter.
- No model download, network call, or note-content transmission occurs without
  explicit configuration and an explicit build or query command.
- Results must retain vault-relative evidence paths and readable excerpts.
- Vectors created by different provider, model, revision, or dimension values
  are never compared or merged.

## Storage Boundary

Use a separate database:

```text
.pkm-index/cognitiveos-embeddings.sqlite3
```

Do not add vectors to `.pkm-index/cognitiveos.sqlite3`. A separate database
keeps the lexical index operational when the embedding database is absent,
stale, incompatible, or corrupt.

Required metadata:

```sql
embedding_builds (
  build_id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_revision TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  chunker_version TEXT NOT NULL,
  note_count INTEGER NOT NULL DEFAULT 0,
  chunk_count INTEGER NOT NULL DEFAULT 0
)

embedding_chunks (
  chunk_id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL,
  path TEXT NOT NULL,
  note_checksum TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  heading TEXT,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_revision TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  vector BLOB NOT NULL
)
```

Vectors use little-endian IEEE-754 float32 values. `chunk_id` is a stable SHA-256
digest of note id, note checksum, chunker version, and chunk index. Indexes are
required on `note_id`, `path`, `note_checksum`, and `content_hash`.

## Chunking Contract

Chunking is deterministic and tokenizer-independent.

1. Parse the note with the existing Markdown parser.
2. Split the body into heading, paragraph, and list blocks while preserving line
   numbers.
3. Prefix each chunk with the note title and nearest heading.
4. Combine consecutive blocks up to 1,600 Unicode characters.
5. When a block is longer than 1,600 characters, split it at the nearest
   sentence or whitespace boundary; hard-split only when no boundary exists.
6. Carry the final complete block into the next chunk as overlap, capped at 300
   characters.
7. Never embed YAML frontmatter verbatim. Title, type, status, domain, and tags
   may be added as normalized labels.

Chunker identity is `markdown-blocks-v1`. Any change to these rules requires a
new chunker version and a full embedding rebuild.

The chunk model and `markdown-blocks-v1` implementation live in
`src/cognitiveos/embedding_chunks.py`. The implementation emits title and nearest
heading context, body-relative line ranges, SHA-256 content hashes, and stable
chunk ids derived from note id, note checksum, chunker version, and chunk index.
Empty and heading-only notes still emit one identity chunk. Long title/heading
prefixes are deterministically shortened only when required to preserve the
configured hard character limit.

## Provider Boundary

The future implementation exposes one provider-neutral interface:

```python
class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    model_revision: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Provider and exact model revision are mandatory configuration. There is no
implicit default provider or model. The first implementation may supply a local
adapter and a deterministic test provider, but the core package must not gain a
mandatory embedding dependency.

The provider protocol, identity validation, batch input validation, and vector
count, dimension, finite-value, numeric-value, and zero-vector validation are
implemented in `src/cognitiveos/embeddings.py`. Tests use a deterministic
SHA-256-derived provider; it is not a production model adapter.

Remote providers are allowed only as a later opt-in adapter. Enabling one must
display that note content leaves the device, require an explicit provider
configuration, and read credentials from environment or an OS credential store.
Credentials must never appear in Markdown, tracked config, SQLite rows, logs, or
MCP results.

## Build and Rebuild Flow

Embedding construction is explicit; it is never triggered by ordinary search.

Planned CLI:

```text
cognitiveos-embed --vault-root PATH --provider ID --model ID --revision REV
cognitiveos-embed --vault-root PATH --provider ID --model ID --revision REV --rebuild
cognitiveos-embed --vault-root PATH --status --format text|json
```

Incremental build rules:

- reuse chunks only when note checksum, content hash, chunker version, provider,
  model, revision, and dimension all match
- embed new or changed chunks
- remove chunks for deleted notes only inside the derived embedding database
- validate vector count, dimensions, finite numeric values, and build metadata
  before publishing the new database
- build into a temporary database and atomically replace the active database
  only after validation succeeds
- leave the last valid database untouched when a build fails

`--rebuild` discards reuse eligibility and regenerates all vectors. Neither mode
modifies source Markdown.

The storage and builder implementation lives in
`src/cognitiveos/embedding_index.py`; the CLI entry point is
`cognitiveos.cli:main_embed`. Builds embed into a temporary database, validate
SQLite integrity, build metadata, provider identity, note/chunk counts, vector
dimensions, finite values, and nonzero vectors, then publish with an atomic
replace. Incremental reuse requires matching chunk id, content hash, provider,
model, immutable revision, dimension, and chunker version. A provider failure
leaves the last valid database byte-for-byte unchanged.

The core provider registry is empty. Tests inject the deterministic provider;
ordinary installations cannot build embeddings until a production adapter is
implemented and explicitly registered.

## Retrieval Modes

Future `search_notes` and `build_context_pack` inputs may add:

```json
{
  "semantic_mode": "off | auto | required"
}
```

Default: `off`.

- `off`: current SQLite/FTS and deterministic reranking only.
- `auto`: use hybrid retrieval when a compatible, healthy embedding index and
  provider are available; otherwise return the unchanged lexical result.
- `required`: require compatible semantic retrieval and return a structured
  `semantic_unavailable` error instead of falling back.

Metadata and path filters are applied before vector scoring. Hybrid retrieval
uses the current lexical candidate list plus semantic candidates and combines
their ranks with reciprocal rank fusion using `k = 60`. Existing PKM title,
heading, type, status, link, and freshness signals rerank the fused candidates.
No raw cosine score is compared directly with an FTS score.

When semantic retrieval participates, results add an optional diagnostic object:

```json
{
  "retrieval": {
    "version": "hybrid-v0.1",
    "semantic_mode": "auto",
    "semantic_used": true,
    "lexical_rank": 1,
    "semantic_rank": 3,
    "fusion_score": 0.0323
  }
}
```

Existing result fields remain unchanged. Context packs continue to enforce the
v0.2 token budget after hybrid candidate selection.

## Failure and Fallback Matrix

| Condition | `off` | `auto` | `required` |
| --- | --- | --- | --- |
| Embedding DB missing | lexical | lexical | error |
| Provider unavailable | lexical | lexical | error |
| Provider/model/revision mismatch | lexical | lexical | error |
| Vector dimension mismatch | lexical | lexical | error |
| Database open or integrity failure | lexical | lexical | error |
| Query embedding failure | lexical | lexical | error |
| Stale note checksum | lexical | exclude stale chunks and continue | error |
| Partial healthy coverage | lexical | hybrid for healthy notes plus lexical fallback | error |

Read paths do not rename, delete, repair, or rebuild a broken embedding database.
They report diagnostics and follow the selected mode. Repair occurs only through
an explicit build command.

## Privacy, Safety, and Observability

- Embedding status output may report provider/model identifiers, dimensions,
  coverage, timestamps, and error classes, but not note bodies or credentials.
- Logs use vault-relative paths and content hashes; raw chunk content is omitted.
- MCP remains read-only and does not expose a build or repair tool initially.
- An embedding adapter must enforce the same vault-root path boundary as the
  lexical indexer.
- Remote adapters require a separate privacy review before implementation.

## Verification and Release Gates

Implementation is complete only when all gates pass:

- current lexical tests pass unchanged with embeddings disabled
- missing, stale, incompatible, and corrupt embedding indexes fall back exactly
  as specified
- repeated builds produce identical chunks and stable chunk ids
- incremental and full rebuilds return equivalent active vectors
- count, dimension, non-numeric, non-finite, and zero-vector validation reject
  invalid provider output
- Korean, English, and mixed-language fixtures exercise semantic retrieval
- a fixed evaluation set records lexical and hybrid Recall@5 and MRR
- hybrid mode must not reduce lexical Recall@5 on the fixed evaluation set
- context token budgets and evidence paths remain valid after hybrid retrieval
- checksum comparison proves source Markdown is unchanged
- no network request occurs in default configuration or `semantic_mode=off`

Initial implementation should be released as an opt-in pre-release before any
stable version enables `auto` by default. Changing the default from `off` requires
a separate decision and release review.

## Explicit Non-goals

- replacing SQLite/FTS
- treating vectors as durable knowledge
- automatic model downloads
- background embedding jobs
- graph database implementation
- local LLM generation
- writeback, migration, rename, archive, or delete operations
