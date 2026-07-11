# Multilingual Embedding Model Evaluation v0.3

## Approved Evaluation Model

The first model approved for local CognitiveOS evaluation is:

| Field | Value |
| --- | --- |
| Provider | `sentence-transformers` |
| Model | `intfloat/multilingual-e5-small` |
| Immutable revision | `fd1525a9fd15316a2d503bf26ab031a61d056e98` |
| License | MIT |
| Embedding dimension | 384 |
| Document prefix | `passage: ` |
| Query prefix | `query: ` |
| Default device | CPU |
| Download policy | Explicit opt-in only |

Intel macOS uses a dedicated Python 3.12 environment with
`sentence-transformers>=3.4,<4` and `numpy<2`. Python 3.13/3.14 and current
PyTorch wheels do not form a supported Intel x86_64 combination. Other
platforms retain the `sentence-transformers>=5,<6` optional dependency path.

This is approval to download and evaluate the exact model revision on an
approved local device. It is not approval to publish `v0.3.0`, enable semantic
retrieval by default, transmit notes remotely, or use a mutable branch name as
the build identity.

## Selection Rationale

`multilingual-e5-small` supports the Korean-English workload while keeping the
local CPU and storage cost lower than the evaluated alternatives. Its model card
records 384-dimensional embeddings, multilingual training, MIT licensing, and
the required asymmetric retrieval prefixes. The repository stores a 471 MB
safetensors weight file at the pinned revision.

`multilingual-e5-base` was not selected because its 768-dimensional, 1.11 GB
safetensors weights increase build time, memory use, and derived index size.
`BAAI/bge-m3` was not selected for this first local baseline because its
1024-dimensional, 24-layer architecture targets a substantially heavier
retrieval profile. Either model may be reconsidered after the small-model
baseline is measured.

## Evaluation Dataset

The tracked evaluation cases are in:

```text
System/evaluation/multilingual-retrieval-v0.3.json
```

They reference the disposable fixture vault at `tests/fixtures/semantic_vault`.
No personal note text, generated embedding, or model file is committed. The six
queries cover Korean, English, and mixed Korean-English retrieval.

## Run the Harness

Install the optional runtime and explicitly acquire the approved revision once:

```bash
uv venv .venv-embeddings312 --python 3.12
uv pip install --python .venv-embeddings312/bin/python -e '.[local-embeddings]'
PYTHONPATH=src .venv-embeddings312/bin/python -m cognitiveos.evaluation \
  --vault-root tests/fixtures/semantic_vault \
  --cases System/evaluation/multilingual-retrieval-v0.3.json \
  --allow-model-download \
  --format json
```

Subsequent evaluation is cache-only by omitting `--allow-model-download`:

```bash
PYTHONPATH=src .venv-embeddings312/bin/python -m cognitiveos.evaluation \
  --vault-root tests/fixtures/semantic_vault \
  --cases System/evaluation/multilingual-retrieval-v0.3.json \
  --format json
```

The CLI defaults to the approved model and immutable revision. Supplying
`--model` or `--revision` creates a comparison run and does not change the
approved baseline.

## Report Contract and Gates

The `multilingual-retrieval-v0.1` report records:

- exact provider, model, revision, and dimension
- Python and platform identity
- model load, lexical index, embedding build, and query latency
- note count, chunk count, and embedding index bytes
- lexical and hybrid Recall@5 and MRR
- per-query lexical and hybrid note rankings
- fixed threshold and pass/fail objects

The current quality gates are:

- hybrid Recall@5 must not regress from lexical Recall@5
- hybrid Recall@5 must be at least `1.0` on the fixed fixture
- hybrid MRR must be at least `0.8` on the fixed fixture

Before `v0.3.0`, run the approved model on each supported hardware target and
record model load time, build time, query median/p95, index size, quality scores,
and source Markdown checksums. The fixture is a release regression gate, not a
claim of broad benchmark quality.

## Intel Mac Baseline Result

Verified on 2026-07-11 with macOS 15.7.7 x86_64, Python 3.12.13,
`sentence-transformers 3.4.1`, PyTorch 2.2.2, NumPy 1.26.4, and the exact model
revision above. Only the tracked three-note fixture was embedded.

| Metric | First successful run | Forced-offline repeat |
| --- | ---: | ---: |
| Model load | 9.6810 s | 8.4007 s |
| Lexical index build | 0.0165 s | 0.0336 s |
| Embedding build, 3 chunks | 0.0956 s | 0.2026 s |
| Lexical query median | 2.13 ms | 2.91 ms |
| Hybrid query median | 25.57 ms | 49.77 ms |
| Hybrid query p95 | 26.19 ms | 98.53 ms |
| Embedding index | 45,056 bytes | 45,056 bytes |
| Lexical Recall@5 | 0.8333 | 0.8333 |
| Hybrid Recall@5 | 1.0000 | 1.0000 |
| Lexical MRR | 0.8333 | 0.8333 |
| Hybrid MRR | 1.0000 | 1.0000 |

All three quality gates passed in both runs. The repeat set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, proving that evaluation uses
the pinned local cache after acquisition. These timings describe a tiny fixture
and are suitable for regression and environment validation only; a larger
approved corpus is still required for capacity planning.

The initial `sentence-transformers 5.6.0` attempt was rejected because current
Intel macOS PyTorch wheels cannot satisfy its runtime requirements on Python
3.13 or 3.14. The Python 3.12 platform-specific dependency path is therefore a
tested portability requirement, not an optimization.
