# CognitiveOS v0.2.0 Release Notes

## Summary

CognitiveOS v0.2.0 improves the read-only retrieval layer while preserving
Markdown as the durable source of truth. It adds deterministic context budgets,
diverse source selection, evidence allocation, and explicit CLI output formats.

## Changes

- `build_context_pack` accepts `token_budget` from `512` through `32768`, with a
  default of `4000`.
- `context_version` is `context-pack-v0.3`.
- context packs include a `budget` object with requested, estimated, and
  remaining tokens, truncation state, and estimator identity.
- `local-heuristic-v1` estimates ASCII at four characters per token and
  non-ASCII at one token per character.
- context source selection prefers note-type diversity before filling by search
  rank.
- key points and evidence are added round-robin without exceeding the context
  budget.
- index and search CLI commands accept `--format text|json`.
- the MCP surface remains nine read-only tools and writeback remains disabled.

## Verification

- 22 unit and fixture tests pass.
- actual vault indexing and MCP protocol verification pass.
- MCP exposes nine read-only tools.
- invalid MCP arguments return structured tool errors.
- source Markdown remains unchanged by indexing and retrieval verification.

The indexed note count is intentionally not a fixed release criterion because
private Markdown content is synchronized outside Git and differs by device.

## Deferred

- embeddings and vector search
- graph database
- local LLM calls
- writeback implementation
- migrations, renames, and destructive operations
- other-device and interactive client UI verification
