# CognitiveOS v0.3.0 Release Notes

Status: Published on 2026-07-12. Tag: `v0.3.0`.

## Summary

CognitiveOS v0.3.0 adds optional, local, read-only multilingual semantic
retrieval while preserving Markdown as the durable source of truth and
SQLite/FTS as the default search path.

Semantic retrieval is disabled by default. Enabling it requires an explicit
local runtime configuration, an exact model revision, and a separately built
derived embedding index. Search and MCP runtime paths never download models or
write to Markdown.

## Highlights

- provider-neutral embedding identity and strict vector validation
- deterministic Markdown chunks with stable ids and source line ranges
- separate, Git-ignored SQLite embedding index
- atomic full and incremental builds with compatible-vector reuse
- opt-in `off | auto | required` semantic modes
- cosine candidates combined with lexical candidates through RRF
- optional cache-only local Sentence Transformers adapter
- exact multilingual E5 model and immutable revision pin
- model-required `query: ` and `passage: ` role prefixes
- Korean, English, and mixed-language evaluation harness
- Recall@5, MRR, latency, index-size, and per-query reports
- explicit cache-only search CLI and MCP runtime injection
- Intel macOS compatibility path and actual-vault baseline

## Approved Local Model

```text
provider: sentence-transformers
model: intfloat/multilingual-e5-small
revision: fd1525a9fd15316a2d503bf26ab031a61d056e98
dimension: 384
license: MIT
```

CognitiveOS does not redistribute model weights. Model acquisition remains an
explicit user action.

## Retrieval Modes

- `off`: lexical SQLite/FTS retrieval only; this remains the default
- `auto`: use compatible semantic retrieval and otherwise return lexical results
- `required`: require a healthy compatible semantic path or return
  `semantic_unavailable`

Existing result fields remain compatible. Hybrid results add a `retrieval`
object with semantic mode, lexical rank, semantic rank, fusion score, and the
`hybrid-v0.1` diagnostic version.

## Local Runtime Safety

The runtime is activated only with explicit provider, model, immutable revision,
and device environment values. Default startup does not load a model backend.
Runtime loading is cache-only, remote model code is disabled, invalid local
configuration preserves lexical MCP startup, and source Markdown is never
modified. Writeback remains disabled.

## Intel macOS Runtime

Current Intel x86_64 PyTorch wheels require a separate Python 3.12 environment:

```bash
uv venv .venv-embeddings312 --python 3.12
uv pip install --python .venv-embeddings312/bin/python -e '.[local-embeddings]'
```

The tested stack is Python 3.12.13, Sentence Transformers 3.4.1, PyTorch 2.2.2,
and NumPy 1.26.4. The normal runtime supports Python 3.11 or newer and is
verified on Python 3.14.6.

## Verification Summary

- 53 automated tests and 26 subtests pass
- package, pyproject, and MCP development versions agree
- MCP exposes exactly 9 read-only tools; writeback tool names are absent
- forced-offline pinned-model evaluation passes all quality gates
- hybrid Recall@5 and MRR: `1.0`; lexical Recall@5 non-regression: pass
- actual vault full rebuild baseline: 42 notes, 327 initial chunks, 45.99 seconds
- actual vault warm required-mode median: 71.84 ms across six smoke queries
- SQLite integrity: `ok`; private Markdown aggregate checksum: unchanged
- clean detached worktree installs and tests both supported runtimes
- wheel and sdist build; wheel-only installation exposes all five CLI entries

Note counts are device-dependent and are not fixed release criteria.

## Upgrade Notes from v0.2.0

- existing lexical search remains the default and needs no call-site changes
- embedding storage is separate and may be deleted or rebuilt independently
- semantic retrieval requires the optional dependency, model cache, embedding
  build, and explicit runtime configuration
- no frontmatter migration or note rewrite is required

## Excluded from v0.3.0

- writeback, migration, rename, archive, and delete operations
- graph database storage and local LLM generation
- background model downloads or embedding jobs
- remote embedding providers and semantic-by-default behavior
- other-device and client-UI validation

## Publication Record

The `0.3.0` release commit was explicitly approved, tagged, pushed, and
published on 2026-07-12. The GitHub Release provides a wheel and source
distribution whose SHA-256 values are listed in the README. Historical tags
must not be moved.
