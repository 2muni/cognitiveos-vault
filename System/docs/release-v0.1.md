# CognitiveOS Release v0.1

## Release Identity

Release name: CognitiveOS read-only MVP

Package version:

```text
0.1.0
```

Git tag:

```text
v0.1.0
```

Release date target:

```text
2026-07-10
```

## Release Scope

This release establishes the first stable read-only baseline for the Obsidian PKM + Codex/MCP system.

Included:

- Markdown scanner
- Markdown/frontmatter parser
- SQLite/FTS indexer
- read-only retrieval service
- read-only MCP stdio server
- project-scoped Codex MCP config
- VS Code Codex extension setup notes
- structured source summaries
- structured context packs
- PKM-aware search reranking
- MCP argument validation
- writeback permission design

Excluded:

- writeback implementation
- vector search
- graph database
- local LLM calls
- background agents
- automatic migrations
- destructive operations

## Release Criteria

A commit may be tagged as `v0.1.0` only when all criteria pass.

Required:

- `pyproject.toml` version is `0.1.0`
- README describes the current v0.1 usage
- roadmap reflects implementation status
- MCP schema lists the enabled read-only tools
- writeback remains disabled
- writeback permission design exists
- unit tests pass
- actual vault index smoke test passes
- MCP stdio `initialize` smoke test passes
- MCP stdio `tools/list` smoke test passes
- invalid MCP tool call returns `isError = true`
- Git working tree is clean before tagging

Current verification snapshot:

| Check | Result |
| --- | --- |
| Unit tests | Pass, `16` tests |
| Actual vault index | Pass, `34` Markdown notes |
| MCP `initialize` | Pass, server name `cognitiveos` |
| MCP `tools/list` | Pass, `9` tools |
| Invalid MCP call | Pass, `isError = true`, `invalid_argument` |

Current verification command:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

Expected:

```text
Ran 16 tests
OK
```

## Version Policy

The project uses SemVer-like versioning for implementation releases.

Format:

```text
MAJOR.MINOR.PATCH
```

Rules:

- `PATCH`: bug fixes, documentation corrections, test-only changes, small deterministic ranking tweaks.
- `MINOR`: new read-only tools, new index fields, new retrieval capabilities, new optional integrations.
- `MAJOR`: writeback enabled by default, incompatible schema changes, destructive migrations, permission model changes that affect user data.

Pre-release identifiers may be used for experimental work:

```text
0.2.0-alpha.1
0.2.0-beta.1
```

## Tag Policy

Release tags use annotated Git tags.

Tag format:

```text
vX.Y.Z
```

Examples:

```text
v0.1.0
v0.1.1
v0.2.0
```

Create tag:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' tag -a v0.1.0 -m "CognitiveOS read-only MVP v0.1.0"
```

Push tag:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' push origin v0.1.0
```

Do not move a published tag unless the user explicitly approves a repair operation.

## Branch Policy

Default branch:

```text
main
```

Release tags should point to commits on `main`.

Development branches should use:

```text
codex/<short-task-name>
```

For this personal vault repository, direct commits to `main` are acceptable while the user is explicitly driving the session and tests pass.

## Release Checklist

Before creating `v0.1.0`:

- [ ] Confirm `main` is clean and aligned with `origin/main`
- [ ] Confirm `pyproject.toml` version is `0.1.0`
- [ ] Run unit tests
- [ ] Rebuild actual vault index
- [ ] Run MCP stdio handshake smoke test
- [ ] Run MCP invalid argument smoke test
- [ ] Review README
- [ ] Review roadmap
- [ ] Confirm writeback tools are not enabled
- [ ] Create annotated tag `v0.1.0`
- [ ] Push tag to origin

## Known Limitations

- Search ranking is deterministic but heuristic.
- Summaries are extractive, not abstractive.
- Context packs do not yet estimate token budget.
- No vector embeddings.
- No graph database.
- No local LLM runtime integration.
- No writeback tools.
- VS Code Codex UI-level MCP discovery requires local interactive confirmation.

## Next Version Candidates

### v0.1.1

Patch release candidates:

- README corrections
- CLI help polish
- better smoke test commands
- small ranking bug fixes
- small MCP error message improvements

### v0.2.0

Minor release candidates:

- token budget estimator for `build_context_pack`
- JSON output mode for CLI search
- richer context pack source selection
- optional embedding index design
- MCP resource URI support

### v0.3.0

Potential writeback preview release:

- proposal-only write tools
- diff preview generation
- checksum-gated apply design prototype
- no automatic apply by default

## Decision

`v0.1.0` should be the first stable tag for the current read-only MVP after the release checklist passes on `main`.
