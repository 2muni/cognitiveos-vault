# CognitiveOS v0.3 Release Readiness

## Status

Feature status: complete.

Release status: release commit preparation; not yet published.

Current release-candidate identity: `0.3.0`.

Latest published stable release: `v0.2.0`.

Do not create `v0.3.0`, move an existing tag, or publish a GitHub Release until
the remaining release operations in this document are complete and explicitly
approved by the user.

## Implemented v0.3 Scope

- provider-neutral embedding identity and validation
- deterministic `markdown-blocks-v1` chunks and stable chunk ids
- separate derived SQLite embedding index
- atomic full and incremental rebuilds
- exact provider/model/revision/dimension compatibility checks
- cosine candidate retrieval and RRF hybrid ranking
- `off | auto | required` semantic modes
- lexical fallback and structured `semantic_unavailable` behavior
- optional cache-only local `sentence-transformers` adapter
- model-specific E5 query and passage prefixes
- approved multilingual model and immutable revision
- Korean, English, and mixed-language evaluation harness
- Recall@5, MRR, latency, index-size, and gate reports
- explicit cache-only CLI and MCP runtime injection
- Intel macOS compatibility path and actual-vault baseline

## Passed Gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Package and MCP development versions match | Pass | automated invariant test |
| MCP exposes exactly 9 read-only tools | Pass | test and actual launcher smoke |
| Writeback tools absent | Pass | automated tool-set assertion |
| Default semantic mode is `off` | Pass | runtime tests |
| Default runtime does not load a provider | Pass | provider-factory mock assertion |
| Search/MCP runtime cannot download a model | Pass | cache-only adapter contract |
| Missing or broken semantic runtime preserves lexical search | Pass | fallback tests |
| `required` reports semantic unavailability | Pass | service and MCP tests |
| Fixed multilingual hybrid Recall@5 | Pass, `1.0` | actual pinned model evaluation |
| Fixed multilingual hybrid MRR | Pass, `1.0` | actual pinned model evaluation |
| Lexical Recall@5 non-regression | Pass | evaluation gate |
| Forced-offline repeat | Pass | Hugging Face and Transformers offline |
| Actual vault embedding build | Pass | 42-note baseline, 327 initial chunks |
| SQLite integrity and dimension validation | Pass | `ok`, 384 dimensions |
| Private Markdown checksum unchanged | Pass | 9 private Markdown aggregate |
| Basic and model runtimes pass tests | Pass | 53 tests after stabilization |
| Writeback remains disabled | Pass | environment verification |
| Clean detached worktree install | Pass | commit `9cc89f8` |
| Wheel and sdist build | Pass | `cognitiveos-0.3.0a1` artifacts |
| Wheel-only import and four CLI entry points | Pass | fresh Python 3.14 environment |
| Clean-worktree pinned-model evaluation | Pass | forced offline, all quality gates |

Other-device and Codex/VS Code visual discovery checks remain explicitly
deferred and are not v0.3 release blockers under the approved scope.

## Remaining Release Operations

These are release operations, not missing v0.3 features:

- [x] integrate the stacked `codex/*` semantic branches into local `main`
- [x] collect the stacked work as `codex/v03-release-candidate`
- [x] verify the release-candidate history and working tree are clean
- [x] run install and tests from a detached clean worktree
- [x] run both default Python and supported local-embedding runtime tests
- [x] build wheel and sdist, install the wheel alone, and verify all CLI entries
- [x] confirm the integrated local `main` history and working tree are clean
- [ ] rebuild lexical and embedding indexes from the release commit
- [ ] repeat MCP initialize, 9-tool list, invalid call, required semantic query,
      writeback-disabled, SQLite integrity, and private checksum checks
- [x] update package and MCP identity from `0.3.0a1` to `0.3.0`
- [x] draft `System/docs/release-notes-v0.3.0.md`
- [ ] verify README, roadmap, schemas, release notes, and package metadata agree
- [ ] obtain explicit user approval for the final commit, annotated tag, push,
      and GitHub Release

## Release Decision Rule

The implementation may be called feature-complete now. It may be called a
release candidate only after branch integration and fresh-checkout verification.
It may be called released only after the exact `0.3.0` commit is approved,
tagged, pushed, and published without moving historical tags.

## Clean Worktree Verification Record

On 2026-07-12, detached commit `9cc89f8` was checked out at
`/tmp/cognitiveos-v03-rc` with no access to the vault's private notes or derived
indexes.

- Python 3.14.6 fresh environment installed `.[dev,mcp]`
- pytest passed 53 tests and 26 subtests
- environment verification exposed 9 tools and writeback remained disabled
- package, installed package, and MCP versions all reported `0.3.0a1`
- `cognitiveos-index`, `cognitiveos-search`, `cognitiveos-embed`, and
  `cognitiveos-evaluate-embeddings` entry points loaded successfully
- wheel and sdist built successfully
- the wheel installed alone in a second clean environment and imported as
  `0.3.0a1`
- Python 3.12.13 fresh Intel environment resolved Sentence Transformers 3.4.1,
  PyTorch 2.2.2, and NumPy 1.26.4
- 53 tests passed in the local-embedding environment
- pinned-model evaluation ran with network access disabled and returned hybrid
  Recall@5 `1.0`, hybrid MRR `1.0`, and all gates passing

The first evaluation attempt reused a path from an interrupted parallel run and
encountered a SQLite disk I/O error. Repeating in a new unique temporary
directory passed, confirming an isolated artifact-path collision rather than a
release-candidate defect.

Writeback, graph storage, local LLM generation, background model downloads, and
semantic-by-default behavior remain outside v0.3. They require separate plans
and do not delay this read-only semantic release.
