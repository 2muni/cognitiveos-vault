# Retrieval Evaluation Fixtures v0.7

## Purpose

`System/evaluation/retrieval-quality-v0.7.json` and
`tests/fixtures/retrieval_quality_vault/` provide a frozen, public, synthetic
regression corpus for Phase B retrieval-quality work. They contain no personal
notes, actual-vault paths, generated index data, model cache paths, or model
weights.

The fixture is additive. `System/evaluation/multilingual-retrieval-v0.3.json`
remains the approved three-note multilingual model-evaluation baseline.

## Contract

The fixture version is `retrieval-quality-v0.7`. Every case has:

- a unique non-empty `id`;
- a non-empty Korean (`ko`), English (`en`), or mixed-language (`mixed`)
  query;
- one or more known `signals`: `aliases`, `backlinks`, `graph_evidence`,
  `headings`, `recency`, `title`, or `typed_links`;
- one or more relevant durable note IDs; and
- one or more matching vault-relative POSIX Markdown paths in `relevant_paths`.

Absolute paths, traversal, backslashes, Windows drive paths, duplicate IDs,
empty relevance, missing signals, and unknown signals are invalid. Fixture paths
identify only files in the tracked synthetic fixture corpus.

The evaluation report adds sorted, timing-free `breakdowns.language` and
`breakdowns.signal` objects. Each entry contains case count plus lexical and
hybrid Recall@k and MRR. A case with multiple signals participates in every
declared signal breakdown.

## Safety and execution

The default retrieval path remains `semantic_mode="off"`. The normal automated
suite uses the deterministic in-repo test embedding provider; it neither loads
nor downloads a production model. The fixture does not add an MCP tool or alter
the existing nine read-only MCP tools.

For deterministic regression checks, compare report fields other than runtime
timings. No evaluation command should target a private vault or retain a derived
index inside this repository.

## Coverage

The initial frozen corpus includes Korean, English, and mixed-language cases
for aliases, titles, headings, backlinks, typed links, graph evidence, and
recency. It provides a non-regression baseline for later diagnostic or ranking
work; it does not itself change a retrieval algorithm or claim benchmark-scale
model quality.
