# Templates v0.1

## Purpose

The canonical v0.1 Obsidian templates live under `System/templates/v0.1/`.

They align with `schema-note-v0.1.md` and are intentionally plain Markdown. They do not require Obsidian Templater, Dataview, or any plugin-specific syntax.

## Template Set

| Template | Note type |
| --- | --- |
| `inbox.md` | `inbox` |
| `concept.md` | `concept` |
| `source.md` | `source` |
| `entity.md` | `entity` |
| `project.md` | `project` |
| `map.md` | `map` |
| `journal.md` | `journal` |
| `system.md` | `system` |
| `output.md` | `output` |

## Placeholder Rules

- Replace `YYYY-MM-DD` with an ISO date.
- Replace `YYYYMMDD_slug` with a stable, readable id suffix.
- Keep `type` fixed to the template's note type.
- Keep `visibility: private` unless the note is explicitly prepared for sharing.
- Leave list fields as `[]` when no value exists.

## Canonical Field Order

Use this frontmatter order for v0.1 notes:

1. `id`
2. `type`
3. `title`
4. `aliases`
5. `status`
6. `created_at`
7. `updated_at`
8. `tags`
9. `domains`
10. `links`
11. `sources`
12. `confidence`
13. `visibility`

## Writeback Policy

These templates are for user-guided note creation. Automated creation or migration of real notes remains out of scope for v0.1.
