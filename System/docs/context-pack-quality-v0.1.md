# Context-Pack Quality Gates v0.1

`build_context_pack` returns the existing structured evidence bundle plus an
additive `quality` object. The gate is deterministic, dependency-free, and
local: it uses only the pack's returned paths, source identities, extractive
evidence, and rendered context. It never opens a new vault file, writes a note,
uses embeddings, downloads a model, or exposes a local absolute path.

## Contract

```json
{
  "version": "context-pack-quality-v0.1",
  "status": "pass | fail",
  "checks": {
    "evidence_density": {"status": "pass | fail"},
    "vault_relative_paths": {"status": "pass | fail"},
    "grounded_content": {"status": "pass | fail"},
    "stability": {"status": "pass", "fingerprint": "sha256:..."}
  }
}
```

- `evidence_density` requires every included source to retain at least one
  extractive evidence block. A token-constrained pack can therefore remain a
  valid existing response while being explicitly reported as insufficient for
  evidence-first downstream use.
- `vault_relative_paths` rejects empty, absolute, backslash-separated, and
  traversal (`.` or `..`) paths across results, selected sources, and
  `evidence_paths`.
- `grounded_content` verifies that each rendered `key_point` or `evidence`
  line belongs to an included source payload, each source identity matches a
  returned search result, and `evidence_paths` is the ordered deduplication of
  included source paths.
- `stability` is a SHA-256 fingerprint of a canonical JSON representation of
  the complete pack contract. Equal deterministic builds produce the same
  fingerprint; clients can compare it without storing source text elsewhere.

The report is additive. Existing `context_version`, retrieval ordering, token
budgeting, and MCP schemas remain unchanged, and default retrieval remains
lexical-only.

## Grounded-answer workflow

Clients that generate an answer can opt into:

```python
from cognitiveos.context_quality import validate_grounded_answer

check = validate_grounded_answer(answer, citations, context_pack)
```

`citations` is a list of selected vault-relative source paths. The helper
requires valid citations with extractive evidence and at least one meaningful
lexical overlap between an answer and its cited evidence. It returns only
counts and a pass/fail status, never the answer or evidence text. This is a
mechanical workflow guard, not semantic fact verification; a passing answer
still needs normal source and human review.

No new MCP tool is introduced. The server continues to expose exactly nine
read-only tools and retains its existing path-traversal protections.
