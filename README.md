# cognitiveos-vault

CognitiveOS is a Markdown-first, local-first, MCP-addressable PKM system for an Obsidian vault.

The latest published stable release is the read-only semantic-retrieval release
v0.3.0. The current source tree is `0.4.0a1` development:

- scans Markdown notes
- parses frontmatter, headings, wikilinks, and Markdown links
- builds a disposable SQLite/FTS index
- exposes read-only retrieval tools through MCP
- supports structured summaries and context packs for Codex/LLM workflows

## Current Scope

Implemented:

- Python indexer
- SQLite/FTS search
- PKM-aware search reranking
- read-only MCP stdio server
- VS Code/Codex project MCP config
- MCP argument validation
- structured source summaries
- structured context packs
- deterministic token budgets and evidence allocation
- explicit text/JSON CLI output formats
- deterministic read-only note contract validation and v0.2 templates
- aliases in lexical search, ranking, backlink targets, and link suggestions
- frontmatter `links` and `sources` indexed as typed graph edges
- graph-aware related-note ranking and context-pack source selection
- service-local graph adjacency cache with index-generation invalidation
- provider-neutral embedding boundary with strict output validation
- deterministic `markdown-blocks-v1` embedding chunker and stable chunk ids
- separate embedding SQLite builder with incremental reuse and atomic publish
- read-only embedding index status CLI
- opt-in `off|auto|required` semantic modes and RRF hybrid retrieval core
- Korean, English, and mixed-language semantic evaluation fixtures
- pinned multilingual evaluation model and quality/performance harness
- writeback permission design

Deferred:

- approved-model benchmark runs on supported hardware
- graph database
- local LLM calls
- writeback tools
- migrations, renames, deletes, and bulk normalization

## Repository Layout

```text
.codex/config.toml                  Codex project config and MCP server registration
.python-version                     Preferred Python runtime for uv/pyenv (3.14.6)
scripts/run-cognitiveos-mcp.sh       macOS MCP server launcher
scripts/run-cognitiveos-mcp.ps1      Windows MCP server launcher
scripts/bootstrap-macos.sh           Intel Mac environment bootstrap
scripts/verify_environment.py        Cross-device verification
src/cognitiveos/                    Python implementation
tests/                              Unit and fixture tests
System/docs/                        Architecture, schemas, decisions, roadmap
System/templates/v0.1/              Canonical note templates
System/templates/v0.2/              Capture and durable note templates
.pkm-index/                         Generated local index, Git-ignored
```

Personal vault content folders are intentionally ignored by Git except for `.gitkeep` placeholders.

## MCP Tools

Read-only tools:

- `search_notes`
- `read_note`
- `list_recent_notes`
- `get_backlinks`
- `get_related_notes`
- `suggest_links`
- `summarize_source`
- `propose_moc`
- `build_context_pack`

No MCP tool writes to Markdown. The `0.4.0a1` development tree remains
read-only.

## Intel Mac Quick Start

CognitiveOS requires Python 3.11 or newer. This repository pins Python 3.14.6
for version managers such as `uv` and `pyenv`; the MCP launcher uses the local
`.venv` when it exists, so it does not depend on the system `python3` being the
preferred version.

After cloning the repository or opening the synchronized vault worktree:

```bash
chmod +x scripts/bootstrap-macos.sh scripts/run-cognitiveos-mcp.sh
./scripts/bootstrap-macos.sh
```

The canonical migration and continuation guide is:

```text
System/docs/device-handoff-intel-mac-v0.1.md
```

Private note folders and assets are not transferred by Git. Restore them through iCloud Drive, Obsidian Sync, or a separate encrypted transfer before rebuilding the index.

## Local Development Environment

Create the default runtime and install the current source tree with the MCP and
test extras:

```bash
uv venv --clear --python 3.14 .venv
uv pip install --python .venv/bin/python '.[dev,mcp]'
```

The install is intentionally non-editable. The current Python 3.14 runtime
skips hidden `.pth` files, while the current `uv` editable flow names its source
path file `_editable_impl_cognitiveos.pth`. A standard local install keeps all
six CLI launchers functional. Reinstall after source changes when validating
the installed CLI surface; source-based tests continue to read `src/`
directly.

## Install v0.3.0 Release Assets

The GitHub Release provides a universal Python wheel and source distribution:

```text
https://github.com/2muni/cognitiveos-vault/releases/tag/v0.3.0
```

Download either asset, verify its SHA-256 digest, then install the wheel with
Python 3.11 or newer:

```bash
shasum -a 256 cognitiveos-0.3.0-py3-none-any.whl
python -m pip install cognitiveos-0.3.0-py3-none-any.whl
```

Expected release-asset digests:

```text
7360c7b8ef26bfa9d57029402244a224453cce021ef34add6ca141422ff28cbe  cognitiveos-0.3.0-py3-none-any.whl
7d84e96276373fef5128b82b905b83b9183f393927a35d633f28432c4656e624  cognitiveos-0.3.0.tar.gz
```

The wheel exposes `cognitiveos-index`, `cognitiveos-search`,
`cognitiveos-mcp`, `cognitiveos-embed`, and `cognitiveos-evaluate-embeddings`.
For local development or the optional semantic runtime, clone the repository
and use the environment setup described below instead.

## Run Tests

From the vault root:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Expected current result:

```text
Ran 75 tests
OK
```

## Validate Notes

The development tree provides a read-only note contract validator:

```bash
PYTHONPATH=src ./.venv/bin/python -c "from cognitiveos.cli import main_validate; raise SystemExit(main_validate())" . --format text
```

JSON and strict validation are explicit:

```bash
PYTHONPATH=src ./.venv/bin/python -c "from cognitiveos.cli import main_validate; raise SystemExit(main_validate())" . --scope user --strict --format json
```

The validator does not create an index or modify Markdown. The public v0.3.0
wheel predates this development command; `cognitiveos-validate` is available
from the current source tree and future packages that include the new entry
point.

## Build the Local Index

```bash
PYTHONPATH=src ./.venv/bin/python -c "from cognitiveos.cli import main_index; main_index()" --format text
```

The generated database is stored under:

```text
.pkm-index/cognitiveos.sqlite3
```

This index is derived and can be rebuilt from Markdown.

## Search Example

```bash
PYTHONPATH=src ./.venv/bin/python -c "from cognitiveos.cli import main_search; main_search()" "CognitiveOS MCP PKM" --format json
```

Both commands accept `--format text|json`. Indexing defaults to `text`; search
defaults to `json` for backward compatibility. Search also accepts
`--semantic-mode off|auto|required`; `off` is the default, `auto` falls back to
lexical retrieval, and `required` errors when compatible semantic retrieval is
unavailable.

## MCP Server

The project MCP server is registered in `.codex/config.toml`:

```toml
[mcp_servers.cognitiveos]
command = "/bin/bash"
args = ["scripts/run-cognitiveos-mcp.sh"]
cwd = "."
enabled = true
```

The launcher finds a usable Python executable, sets `PYTHONPATH=src`, and runs:

```bash
./scripts/run-cognitiveos-mcp.sh
```

## VS Code / Codex

Local setup status:

- VS Code installed
- Codex extension installed as `openai.chatgpt@26.707.31428`
- project MCP config exists at `.codex/config.toml`

Open the vault root in VS Code and confirm the Codex extension loads the `cognitiveos` MCP server.

## Writeback Policy

Writeback is not implemented in v0.3.0.

The future writeback design is documented in:

```text
System/docs/writeback-permissions-v0.1.md
```

Required principles:

- explicit approval for every write
- proposal before apply
- diff or preview before write
- checksum verification
- vault-root path enforcement
- auditable derived writeback logs

## Roadmap

The implementation-vs-roadmap status is maintained in:

```text
System/docs/roadmap-v0.1.md
```

The approved design for future opt-in semantic retrieval is maintained in:

```text
System/docs/embeddings-design-v0.3.md
```

The provider-neutral interface, deterministic chunker, derived SQLite builder,
hybrid retrieval core, and optional local `sentence-transformers` adapter are
implemented. The adapter dependency and model files are not installed by
default, and `off` remains the retrieval default.

Inspect local embedding status without creating an index or calling a provider:

```bash
PYTHONPATH=src ./.venv/bin/python -c "from cognitiveos.cli import main_embed; main_embed()" --status --format json
```

Install the optional local runtime only on a device approved for model storage.
On Intel macOS, use the supported Python 3.12 evaluation environment:

```bash
uv venv .venv-embeddings312 --python 3.12
uv pip install --python .venv-embeddings312/bin/python -e '.[local-embeddings]'
```

Other supported platforms may install the same extra into their normal project
environment. See `System/docs/model-evaluation-v0.3.md` for the tested matrix.

Building requires an exact model id and immutable revision. The command is
cache-only by default and does not download model files:

```bash
cognitiveos-embed --vault-root . --provider sentence-transformers \
  --model MODEL_ID --revision COMMIT_SHA
```

Add `--allow-model-download` only for an explicit, reviewed model acquisition.
The adapter always disables remote model code. Search never initiates a build or
download.

The approved local evaluation baseline is
`intfloat/multilingual-e5-small@fd1525a9fd15316a2d503bf26ab031a61d056e98`.
Its selection rationale, fixed multilingual cases, evaluation CLI, metrics, and
release gates are documented in `System/docs/model-evaluation-v0.3.md`.

### Enable Local Semantic Runtime

The search CLI and MCP server remain lexical-only unless the local runtime is
explicitly enabled. After building a compatible embedding index, set:

```bash
export COGNITIVEOS_SEMANTIC_RUNTIME=local
export COGNITIVEOS_EMBEDDING_PROVIDER=sentence-transformers
export COGNITIVEOS_EMBEDDING_MODEL=intfloat/multilingual-e5-small
export COGNITIVEOS_EMBEDDING_REVISION=fd1525a9fd15316a2d503bf26ab031a61d056e98
export COGNITIVEOS_EMBEDDING_DEVICE=cpu
```

`scripts/run-cognitiveos-mcp.sh` then selects `.venv-embeddings312` on Intel
macOS. `COGNITIVEOS_PYTHON` may explicitly select another compatible runtime.
No runtime setting permits model download: acquisition remains confined to the
explicit build/evaluation commands. If configuration or cache loading fails,
MCP still starts, `auto` returns lexical results, and `required` returns
`semantic_unavailable`. Do not commit active device-specific environment values.

## Release Policy

The v0.1 release checklist, version policy, and tag policy are maintained in:

```text
System/docs/release-v0.1.md
```

The v0.3 release readiness and publication record are maintained in:

```text
System/docs/release-v0.3.md
```

It also defines the hotfix flow and version bump procedure.

The draft v0.2 note authoring and read-only validation contract is maintained
in:

```text
System/docs/note-contract-v0.2.md
```

It defines capture and durable authoring profiles plus the proposed
`cognitiveos-validate` diagnostic contract. It does not authorize note
migration or writeback.

The v0.1.0 release notes are maintained in:

```text
System/docs/release-notes-v0.1.0.md
```

The v0.2.0 release notes are maintained in:

```text
System/docs/release-notes-v0.2.0.md
```

The published v0.3.0 release notes are maintained in:

```text
System/docs/release-notes-v0.3.0.md
```

The current v0.4 implementation and release gates are maintained in:

```text
System/docs/release-v0.4.md
```

Current package version:

```text
0.4.0a1
```

Published stable release:

```text
v0.3.0
```

`v0.3.0` was published on 2026-07-12 after the planned semantic retrieval,
model evaluation, privacy, packaging, and release gates completed.
