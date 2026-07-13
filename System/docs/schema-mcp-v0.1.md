# MCP Schema v0.1

## MCP Principle

The v0.1 MCP surface is read-only. It lets Codex and other MCP clients inspect the vault, search notes, and build evidence packs without modifying Markdown files.

The project MCP server is configured in `.codex/config.toml` as `mcp_servers.cognitiveos`.
It runs over stdio and exposes only the read-only tools listed below.

If the Python `mcp` SDK is installed, the server uses FastMCP. Otherwise it falls back to a minimal JSON-RPC stdio implementation for the v0.1 tool surface.

Codex documentation currently describes MCP server support for the CLI and IDE extension. Codex App tool discovery should not be treated as the primary verification path until App support for project MCP servers is explicitly confirmed.

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
  "semantic_mode": "off | auto | required",
  "limit": 10
}
```

Output: ranked list of search results containing `note_id`, `path`, `title`, `type`, `score`, and `matched_excerpt`.

Ranking v0.2 uses SQLite FTS/LIKE candidates and then reranks with local PKM signals:

- exact or partial title match
- heading term match
- path term match
- matched excerpt term overlap
- note type boost
- status boost
- small freshness boost

`semantic_mode` defaults to `off`. `auto` uses RRF hybrid retrieval when a
compatible provider and embedding index are available and otherwise returns the
unchanged lexical results. `required` returns `semantic_unavailable` instead of
falling back. Hybrid results add a `retrieval` diagnostic with lexical rank,
semantic rank, fusion score, mode, and `hybrid-v0.1` version.

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

Output: notes related by resolved explicit graph edges followed by lexical
matches. Graph-ranked items include a `retrieval` object:

```json
{
  "version": "graph-related-v0.1",
  "graph_used": true,
  "directions": ["outgoing"],
  "edge_types": ["frontmatter_link"],
  "graph_score": 3.1,
  "lexical_rank": null
}
```

Outgoing edges rank before incoming edges. Ambiguous identities are not
resolved automatically.

### `suggest_links`

Input:

```json
{
  "note_id": "string",
  "limit": 10
}
```

Output: candidate internal links for the selected note, including `note_id`, `path`, `title`, `type`, `reason`, and `score`. This is read-only and does not modify Markdown.

### `summarize_source`

Input:

```json
{
  "note_id": "optional string",
  "path": "optional vault-relative path"
}
```

Output: deterministic extractive summary for one note.

Returned fields:

- `summary_version`: currently `extractive-v0.2`
- `summary`: compact text assembled from the title and selected key points
- `key_points`: selected heading, paragraph, or list-item statements
- `open_questions`: question-like lines extracted from the note
- `headings`: parsed Markdown headings
- `evidence`: source Markdown blocks used for the summary
- `stats`: heading, link, evidence, and word counts

This is grounded in the note body and does not call an LLM in v0.1.

### `propose_moc`

Input:

```json
{
  "query": "string",
  "limit": 10
}
```

Output: proposed map-of-content structure grouped by note type. This returns an outline only and sets `writeback` to `false`.

### `build_context_pack`

Input:

```json
{
  "query": "string",
  "limit": 5,
  "token_budget": 4000,
  "semantic_mode": "off | auto | required"
}
```

`token_budget` defaults to `4000` and must be an integer from `512` through
`32768`.

Output: structured evidence bundle for LLM/Codex context construction.

Returned fields:

- `context_version`: currently `context-pack-v0.3`
- `context`: compact text block for prompt insertion
- `results`: raw search results
- `sources`: ranked source objects with summary, key points, evidence, score, and stats
- `key_points`: deduplicated key points across selected sources
- `evidence_paths`: vault-relative source paths used in the pack
- `stats`: source count, evidence path count, key point count, source word
  count, selection version, graph edge count, and graph-connected source count
- `budget`: requested, estimated, and remaining tokens plus truncation state and estimator identity

Each source includes `selection.version = type-diverse-graph-v0.1`,
`graph_connected_to`, and `graph_edge_types`.

The `local-heuristic-v1` estimator counts ASCII text at four characters per
token, rounded up, and non-ASCII text at one token per character. Context source
selection starts from the highest-ranked result, preserves note-type diversity,
and prefers a directly connected candidate within the eligible type before
falling back to search rank. Source identity and excerpts are
allocated before key points and evidence; optional evidence is added round-robin
without exceeding the requested context budget.

## Deferred Write Tools

The following are intentionally excluded from v0.1:

- `create_note`
- `update_frontmatter`
- `append_to_note`
- `create_project_brief`
- `create_map`
- `archive_note`

They require a separate approval and safety design.

## Tool Error Semantics

The basic stdio server returns MCP-style tool results for tool execution failures.

For invalid tool arguments, missing notes, rejected paths, or internal failures, the response shape is:

```json
{
  "content": [
    {
      "type": "text",
      "text": "error message"
    }
  ],
  "structuredContent": {
    "error": {
      "code": "invalid_argument | not_found | semantic_unavailable | invalid_request | internal_error",
      "message": "error message"
    }
  },
  "isError": true
}
```

Validation rules:

- required string arguments must be non-empty after trimming
- `read_note` and `summarize_source` require exactly one of `note_id` or `path`
- `limit` must be an integer greater than or equal to `1`
- tool-specific maximum limits are enforced server-side
- paths remain restricted to the vault root

## Codex Config

```toml
[mcp_servers.cognitiveos]
command = "powershell"
args = ["-ExecutionPolicy", "Bypass", "-File", "scripts/run-cognitiveos-mcp.ps1"]
cwd = "."
startup_timeout_sec = 20
tool_timeout_sec = 60
enabled = true
enabled_tools = [
  "search_notes",
  "read_note",
  "list_recent_notes",
  "get_backlinks",
  "get_related_notes",
  "suggest_links",
  "summarize_source",
  "propose_moc",
  "build_context_pack",
]
default_tools_approval_mode = "prompt"
```

## Verification Surface

Use these verification levels in order:

1. TOML parse check for `.codex/config.toml`.
2. Local stdio JSON-RPC handshake against `scripts/run-cognitiveos-mcp.ps1`.
3. `tools/list` and `tools/call` against the stdio server.
4. Codex CLI or IDE extension `/mcp` discovery.

Codex App discovery is currently informational only for this project because the official Codex MCP page documents CLI and IDE extension support.
