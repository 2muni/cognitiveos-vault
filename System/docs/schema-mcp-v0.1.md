# MCP Schema v0.1

## MCP Principle

The v0.1 MCP surface is read-only. It lets Codex and other MCP clients inspect the vault, search notes, and build evidence packs without modifying Markdown files.

## Resources

```text
vault://notes/{id}
vault://search?q={query}
vault://concepts/{id}
vault://sources/{id}
vault://projects/{id}
```

## Tools

### `search_notes`

Input:

```json
{
  "query": "string",
  "type": "optional note type",
  "status": "optional lifecycle status",
  "domain": "optional domain value",
  "tag": "optional tag value",
  "limit": 10
}
```

Output: list of search results containing `note_id`, `path`, `title`, `type`, `score`, and `matched_excerpt`.

### `read_note`

Input:

```json
{
  "note_id": "optional string",
  "path": "optional vault-relative path"
}
```

Output: frontmatter, body, headings, links, and metadata for one note.

### `list_recent_notes`

Input:

```json
{
  "limit": 10
}
```

Output: recently modified indexed notes.

### `get_backlinks`

Input:

```json
{
  "note_id": "string"
}
```

Output: notes whose outgoing links mention the selected note title, path, or id.

### `get_related_notes`

Input:

```json
{
  "note_id": "string",
  "limit": 10
}
```

Output: notes related by explicit links or matching metadata.

### `build_context_pack`

Input:

```json
{
  "query": "string",
  "limit": 5
}
```

Output: compact evidence bundle for LLM context construction.

## Deferred Write Tools

The following are intentionally excluded from v0.1:

- `create_note`
- `update_frontmatter`
- `append_to_note`
- `create_project_brief`
- `create_map`
- `archive_note`

They require a separate approval and safety design.
