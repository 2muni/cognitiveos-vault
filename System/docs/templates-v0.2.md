# CognitiveOS Templates v0.2

## Purpose

The canonical v0.2 templates live under `System/templates/v0.2/`. They reduce
capture friction and align durable notes with the read-only validation contract
in `System/docs/note-contract-v0.2.md`.

The v0.1 templates remain unchanged for compatibility. No existing note is
migrated by adding this template set.

## Profiles

### Capture

`inbox.md` contains only explicit capture-state metadata:

- `type: inbox`
- `status: inbox`
- `created_at`

The runtime derives the title from the first H1 and supplies other defaults
without writing them into the note.

### Durable

The other eight templates contain:

- stable explicit `id`
- `type`
- lifecycle `status`
- `created_at` and `updated_at`
- explicit `visibility: private`

Optional metadata is omitted until it has a useful value. Add `aliases`,
`tags`, `domains`, or `confidence` only when they improve retrieval or record a
real decision. Empty optional arrays are not part of the v0.2 templates.

## Relationship Rule

Prefer body wikilinks or Markdown links under the appropriate section when the
relationship should be visible in the note. Frontmatter `links` and `sources`
may also record structured relationships; they are indexed as typed derived
graph edges. Do not duplicate the same relationship in both places without a
specific human-readable reason.

## Placeholder Rules

- replace `YYYY-MM-DD` with an ISO date
- replace `YYYYMMDD_slug` with a stable readable suffix
- replace the first H1 placeholder
- keep the template's note type fixed
- do not reuse a durable id

The read-only validator exempts canonical template files from placeholder
errors but reports placeholders when copied notes retain them.

## Template Set

| Template | Profile | Type |
| --- | --- | --- |
| `inbox.md` | capture | `inbox` |
| `concept.md` | durable | `concept` |
| `source.md` | durable | `source` |
| `entity.md` | durable | `entity` |
| `project.md` | durable | `project` |
| `map.md` | durable | `map` |
| `journal.md` | durable | `journal` |
| `system.md` | durable | `system` |
| `output.md` | durable | `output` |

## Safety Boundary

Templates are copied and completed by the user. CognitiveOS does not create,
edit, migrate, move, rename, or delete real notes under this contract.
