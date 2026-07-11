# CognitiveOS Release v0.1

## Release Identity

Release name: CognitiveOS read-only MVP

Release notes:

```text
System/docs/release-notes-v0.1.0.md
```

Package version:

```text
0.1.0
```

Git tag:

```text
v0.1.0
```

Release date:

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
| Unit tests | Pass, `26` tests |
| Actual vault index | Pass; note count is device-dependent |
| MCP `initialize` | Pass, server name `cognitiveos` |
| MCP `tools/list` | Pass, `9` tools |
| Invalid MCP call | Pass, `isError = true`, `invalid_argument` |

Current verification command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Expected:

```text
Ran 26 tests
OK
```

Current development package version: `0.2.0`. The published `v0.1.0` tag and
its historical release identity remain unchanged.

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

## Version Bump Procedure

Version changes must be explicit and should be committed before tagging.

Files to check:

- `pyproject.toml`
- `README.md`
- `System/docs/roadmap-v0.1.md`
- `System/docs/release-v0.1.md`
- `System/docs/decision-log.md`

Patch bump example:

```text
0.1.0 -> 0.1.1
```

Use for:

- bug fixes
- typo or documentation corrections
- test-only improvements
- deterministic ranking tweaks that do not change contracts
- MCP error message improvements that do not change schemas

Minor bump example:

```text
0.1.0 -> 0.2.0
```

Use for:

- new read-only MCP tool
- new retrieval output field
- optional embedding index design or implementation
- new CLI mode
- new MCP resource URI support

Major bump example:

```text
0.1.0 -> 1.0.0
```

Use for:

- writeback tools enabled by default
- incompatible note schema changes
- destructive migrations
- permission boundary changes that can affect user-authored Markdown
- default behavior changes that can modify source files

Required bump checklist:

- [ ] decide bump class: patch, minor, or major
- [ ] update `pyproject.toml`
- [ ] update release notes or release document
- [ ] update README if user-facing behavior changed
- [ ] update roadmap if scope changed
- [ ] run tests
- [ ] commit version bump
- [ ] create annotated tag after verification

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

## Hotfix Policy

A hotfix is a minimal patch release made after a stable tag when the current release has a defect that should be corrected without waiting for the next planned minor version.

Hotfix version:

```text
v0.1.0 -> v0.1.1
```

Hotfix branch format:

```text
codex/hotfix-v0.1.1-short-description
```

For this personal vault repository, direct hotfix commits to `main` are acceptable only when:

- the user explicitly asks to proceed directly on `main`
- the fix is narrow
- no private note content is staged
- tests pass

Hotfix allowed changes:

- critical bug fix
- broken test fix
- incorrect release/documentation instruction
- MCP error handling fix
- path safety fix
- packaging or launch script fix

Hotfix disallowed changes:

- new features
- new writeback capability
- schema migrations
- broad refactors
- unrelated documentation rewrites
- private note changes

Hotfix process:

1. Confirm the target base tag or current release branch.
2. Create a narrow hotfix branch when not working directly on `main`.
3. Make the smallest safe change.
4. Add or update tests when behavior changes.
5. Run unit tests.
6. Run relevant smoke tests.
7. Bump patch version.
8. Commit with a clear message.
9. Merge or fast-forward to `main`.
10. Create annotated patch tag.
11. Push branch/main and tag.

Hotfix tag example:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' tag -a v0.1.1 -m "CognitiveOS hotfix v0.1.1"
& 'C:\Program Files\Git\cmd\git.exe' push origin v0.1.1
```

Hotfix verification:

- unit tests pass
- relevant smoke test passes
- `git status --short --branch` is clean before tagging
- `git tag --list vX.Y.Z` confirms the tag does not already exist

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

Completed for `v0.1.0`:

- [x] Confirm `main` is clean and aligned with `origin/main`
- [x] Confirm `pyproject.toml` version is `0.1.0`
- [x] Run unit tests
- [x] Rebuild actual vault index
- [x] Run MCP stdio handshake smoke test
- [x] Run MCP invalid argument smoke test
- [x] Review README
- [x] Review roadmap
- [x] Confirm writeback tools are not enabled
- [x] Create annotated tag `v0.1.0`
- [x] Push tag to origin
- [x] Publish the GitHub Release

## Known Limitations

- Search ranking is deterministic but heuristic.
- Summaries are extractive, not abstractive.
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

- completed on `main`: token-budgeted `build_context_pack`
- completed on `main`: explicit text/JSON CLI output
- completed on `main`: note-type-diverse context source selection
- optional embedding index design
- MCP resource URI support

### v0.3.0

Potential writeback preview release:

- proposal-only write tools
- diff preview generation
- checksum-gated apply design prototype
- no automatic apply by default

## Decision

`v0.1.0` is the published stable tag and GitHub Release for the current read-only MVP. The published tag must not be moved.
