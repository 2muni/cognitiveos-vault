# CognitiveOS Note Contract and Validation Design v0.2

## Status

- Design status: accepted
- Implementation status: complete for the v0.4 read-only scope, including the
  CLI, v0.2 templates, aliases, relationship fields, and layer specifications
- Scope: read-only validation and user-guided templates
- Migration status: no migration is authorized by this design

## Purpose

This design reduces the cost of capturing knowledge while making durable notes
more predictable for search, linking, summarization, and context construction.
It adds a read-only validation contract and defines lighter template profiles
without changing existing Markdown automatically.

Markdown remains the durable source of truth. Validation reports, indexes,
embeddings, and caches remain disposable derived artifacts.

## Goals

- distinguish fast capture from durable knowledge maintenance
- keep note type and lifecycle status semantically separate
- validate the fields that affect retrieval before adding more metadata
- detect unsafe identity collisions and silent parser fallbacks
- make body links the current operational relationship contract
- preserve compatibility with all v0.1 notes and templates
- provide deterministic text and JSON diagnostics

## Non-goals

- editing, normalizing, or migrating existing notes
- adding writeback tools
- enforcing folder moves or naming conventions
- treating `visibility` as an access-control mechanism
- adding new note types before the current set proves insufficient
- introducing Dataview, Templater, or another plugin dependency

## Knowledge Types

The v0.1 type set remains sufficient and is retained unchanged:

| Type | Durable purpose |
| --- | --- |
| `inbox` | unprocessed capture awaiting triage |
| `concept` | reusable explanation of one concept |
| `source` | external source, citation, claims, and source-grounded notes |
| `entity` | person, organization, product, technology, or place |
| `project` | goal-oriented work with state, decisions, and next actions |
| `map` | navigation and synthesis across a knowledge area |
| `journal` | time-ordered observations, decisions, and follow-ups |
| `system` | rules, schemas, decisions, prompts, and operational guidance |
| `output` | an intended deliverable and its evidence |

Types describe what a note is. Status values describe where the note is in its
lifecycle. A status must not be used as a substitute for changing an inbox note
into its durable type.

## Lifecycle Contract

The shared status vocabulary remains:

- `inbox`: captured but not triaged
- `seed`: classified but incomplete or weakly supported
- `active`: actively used or changing
- `evergreen`: reviewed, reusable, and expected to remain useful
- `archived`: retained for history but excluded from normal attention

Recommended transitions:

| Type | Recommended lifecycle |
| --- | --- |
| `inbox` | `inbox` -> change type and move to `seed` or `active` |
| `concept` | `seed` -> `evergreen` -> `archived` |
| `source` | `seed` -> `active` or `evergreen` -> `archived` |
| `entity` | `seed` -> `active` -> `archived` |
| `project` | `active` -> `archived` |
| `map` | `active` -> `evergreen` -> `archived` |
| `journal` | `active` -> `archived` |
| `system` | `active` -> `archived` |
| `output` | `active` -> `archived` |

The first validator release reports unusual combinations as warnings rather
than errors so that existing notes remain valid. In particular,
`type: inbox` with a status other than `inbox` receives
`lifecycle_inbox_status_mismatch`.

## Authoring Profiles

### Capture Profile

The capture profile optimizes for low-friction recording. Only fields that
communicate capture state are written explicitly:

```yaml
---
type: inbox
status: inbox
created_at: YYYY-MM-DD
---
```

The first H1 heading is the title. Runtime defaults provide a path-derived id,
empty metadata lists, `confidence: 0.5`, and `visibility: private` without
writing those defaults into the note.

Recommended body:

```markdown
# Capture title

## Capture

Raw observation, question, excerpt, or thought.

## Next

- [ ] Triage this capture.
```

### Durable Profile

A note uses the durable profile after triage. The recommended common fields
are:

```yaml
---
id: concept_YYYYMMDD_slug
type: concept
status: seed
created_at: YYYY-MM-DD
updated_at: YYYY-MM-DD
visibility: private
---
```

The H1 remains the human-readable title. `title` may be supplied in
frontmatter when an integration needs it, but the validator reports a warning
if it disagrees with the first H1.

Optional fields are added only when they contain useful values:

```yaml
aliases:
  - Alternate Name
tags:
  - retrieval
domains:
  - knowledge-management
confidence: 0.8
```

### Layer Specification Profile

Files named `__SPECS__.md` are durable operational guidance for a vault layer.
They use `type: system`, `status: active`, and an explicit stable `id`. Existing
`layer`, `purpose`, and `scope` fields may describe their operational reach.

Layer specifications retain their numbered, layer-specific section structure,
so the validator does not require the generic system headings `Purpose`,
`Specification`, `Rationale`, and `Change Log`. All other frontmatter, identity,
placeholder, status, and duplicate checks continue to apply. Layer
specifications remain scanner-visible and searchable; they are not validator or
index exclusions.

Empty optional arrays should not be required in v0.2 templates.
Template placeholder IDs are authoring instructions rather than durable note
identities. At index time, files under `System/templates/` therefore receive a
deterministic path-derived runtime ID. This keeps versioned templates with the
same placeholder ID independently searchable without changing template source.

### Type-specific Body Contracts

The validator treats these headings as guidance in its first release. Missing
headings are warnings, not errors.

| Type | Recommended headings |
| --- | --- |
| `inbox` | `Capture`, `Next` |
| `concept` | `Definition`, `Distinction`, `Examples`, `Related`, `Sources`, `Open Questions` |
| `source` | `Citation`, `Summary`, `Key Claims`, `Extracted Concepts`, `Personal Notes` |
| `entity` | `Type`, `Description`, `Relations`, `Sources` |
| `project` | `Goal`, `Current State`, `Decisions`, `Next Actions`, `Related Notes` |
| `map` | `Purpose`, `Core Notes`, `Clusters`, `Open Questions` |
| `journal` | `Log`, `Observations`, `Decisions`, `Follow-ups` |
| `system` | `Purpose`, `Specification`, `Rationale`, `Change Log` |
| `output` | `Brief`, `Draft`, `Evidence`, `Revision Notes` |

## Identity Contract

- capture notes may use the runtime path-derived id
- durable notes should have an explicit, stable `id`
- ids must be unique across scanner-visible Markdown
- ids should not change when a note is renamed or moved
- duplicate ids are validation errors because the current index upsert contract
  may otherwise replace one indexed path with another
- placeholder ids such as `concept_YYYYMMDD_slug` are validation errors outside
  the canonical template directory

The validator reports missing explicit ids on durable notes as warnings in the
first release. A future strict profile may promote them to errors only after a
separate migration plan is approved.

## Relationship and Source Contract

### Canonical relationship representation

Body wikilinks and Markdown links remain the preferred human-readable
relationship representation:

```markdown
## Related

- [[Hybrid Retrieval]]
- [[Context Pack]]

## Sources

- [[CognitiveOS Architecture v0.1]]
```

Frontmatter `links` and `sources` are also indexed as typed graph edges in
`0.4.0a1` development. Each field must be a list of strings. Values may be raw
note ids, titles, aliases, vault-relative paths, wikilinks, Markdown links, or
external URLs. Wikilink display text and Markdown link labels are removed from
the derived target. Duplicate values within one field are collapsed
case-insensitively. Because frontmatter values do not have a body line number,
their derived edge stores `line=NULL`.

`links` produces `frontmatter_link` edges and `sources` produces
`frontmatter_source` edges. Body links retain their existing `wikilink` and
`markdown` types. Backlinks resolve all internal edge types; external URLs stay
indexed as outgoing source evidence but do not resolve to a note unless they
match a note identity explicitly. No relationship is written back to Markdown.

Graph identity resolution gives note id and path precedence over filename stem,
canonical title, and aliases. Ambiguous title or alias targets are left
unresolved rather than being attached to every matching note. Resolved edges
guide related-note ranking and context-pack source selection; generic search
ranking remains lexical/semantic and does not receive a graph boost.

### Source metadata

The source template retains its human-readable citation section in the first
v0.2 template release. Structured fields such as `author`, `published_at`,
`accessed_at`, `source_kind`, and `url` should be added only together with
search, deduplication, or citation features that consume them.

Source summaries must continue to separate source-grounded claims from
personal synthesis.

## Metadata Semantics

### Tags and domains

- `domains` are stable top-level knowledge areas
- `tags` are narrower topics or operating contexts
- values should be lowercase kebab-case where practical
- filters are currently exact-match, so spelling and case must be consistent
- the first validator release diagnoses type errors but does not enforce a
  controlled vocabulary

### Aliases

Aliases remain optional. In `0.4.0a1` development they are included in lexical
FTS candidate generation, receive explicit alias ranking signals, and resolve
as backlink targets. Link suggestions also recognize an existing alias link so
they do not propose the canonical note again. The canonical title remains the
display title and receives a stronger exact-match score than an alias.

### Confidence

`confidence` is optional for durable notes and absent from capture templates.
When present, it means the author's confidence in the note's central claims
after reviewing the cited evidence. It must be a number from `0.0` through
`1.0`. It does not represent source prestige, note completeness, or access
permission.

### Visibility

`visibility` remains `private | shared | public`, defaulting to `private`.
It is classification metadata only. CognitiveOS v0.3 does not use it as an
authorization boundary, and the validator must state this in text help and JSON
metadata.

### Dates and freshness

`created_at` and `updated_at` use ISO `YYYY-MM-DD` or an ISO 8601 datetime.
The current retrieval implementation ranks freshness using filesystem mtime.
The validator reports malformed dates, while using `updated_at` for retrieval
freshness remains a separate implementation decision.

## Read-only Validator

The validation core is available in `src/cognitiveos/validation.py`. It provides
deterministic report and diagnostic data structures plus pure read-only
validation functions. `cognitiveos-validate` exposes text and JSON output,
scope selection, strict warning handling, and stable exit codes. Type-specific
heading guidance is aggregated into one warning per note, and source notes are
checked for a URL, DOI, or another locator without exposing its value.

### Command

Proposed entry point:

```text
cognitiveos-validate [VAULT_ROOT] [--scope all|user] [--format text|json]
                     [--strict]
```

Defaults:

- `VAULT_ROOT`: current directory
- `--scope user`: exclude `System/`, `README.md`, and `AGENTS.md` from authoring
  profile warnings while still checking them for identity and parse errors
- `--format text`
- strict mode disabled

The command is read-only. It must not create an index, edit Markdown, normalize
frontmatter, rename files, or write a report inside the vault.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | no validation errors; warnings may exist |
| `1` | one or more validation errors, or warnings under `--strict` |
| `2` | invalid command arguments or validator execution failure |

### Diagnostic shape

JSON output uses a stable top-level contract:

```json
{
  "validation_version": "note-contract-v0.2",
  "scope": "user",
  "strict": false,
  "summary": {
    "files_scanned": 0,
    "errors": 0,
    "warnings": 0,
    "info": 0
  },
  "diagnostics": []
}
```

Each diagnostic contains:

```json
{
  "code": "duplicate_id",
  "severity": "error",
  "path": "vault-relative/path.md",
  "line": 2,
  "field": "id",
  "message": "note id is also used by another scanner-visible note",
  "related_paths": ["other/path.md"]
}
```

Absolute paths and note body excerpts must not appear in diagnostics.
Diagnostic ordering is deterministic by severity, path, line, and code.

### Initial diagnostics

Errors:

- `duplicate_id`
- `invalid_type`
- `invalid_status`
- `invalid_field_type`
- `invalid_date`
- `confidence_out_of_range`
- `template_placeholder_present`
- `frontmatter_parse_failed`

Warnings:

- `durable_id_missing`
- `title_heading_mismatch`
- `lifecycle_inbox_status_mismatch`
- `recommended_heading_missing`
- `source_locator_missing`
- `duplicate_title`
- `tag_domain_noncanonical`

Information:

- `visibility_is_not_access_control`
- `runtime_default_applied`

Unknown frontmatter keys are allowed. Existing operational metadata such as
`layer`, `purpose`, and `scope` must not generate warnings merely because it is
outside the common schema.

## Compatibility and Rollout

1. [Complete] Add validator data structures and pure validation functions with
   fixture tests.
2. [Complete] Add deterministic text and JSON output plus
   `cognitiveos-validate`.
3. [Complete] Add `System/templates/v0.2/` without modifying `v0.1` templates.
4. [Complete] Run the validator against the actual vault and record aggregate
   diagnostics only; do not expose private note content.
5. [Complete] Tune initial warning volume based on observed false positives.
6. Document an opt-in user-guided cleanup workflow.
7. Consider migrations only under a separate explicit plan and approval.

## Test Contract

The implementation is complete when tests cover:

- duplicate explicit ids across different paths
- invalid and missing type/status values
- invalid list, number, visibility, and date field types
- placeholder detection outside template directories
- capture and durable profiles
- all lifecycle warnings
- heading recommendations by type
- frontmatter relationship edge parsing and validation
- custom frontmatter keys without warnings
- deterministic diagnostic ordering
- text and parseable JSON output
- exit codes with and without strict mode
- no index, report, or Markdown mutation
- scanner exclusions and vault-root path safety
- private note body text absent from diagnostic output
- all existing CognitiveOS tests remain passing

## Deferred Implementation Decisions

- using `updated_at` rather than mtime for freshness
- structured citation fields and source deduplication
- controlled vocabularies for tags and domains
- automatic note migration or repair
- writeback of validator suggestions

These items require separate implementation units so that the validator remains
read-only and the v0.1 note contract remains backward compatible.
