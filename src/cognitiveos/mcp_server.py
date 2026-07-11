from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .embedding_index import SemanticUnavailableError
from .retrieval import RetrievalService, context_pack_to_dict, search_result_to_dict

PROTOCOL_VERSION = "2025-11-25"


class ToolInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_service() -> RetrievalService:
    vault_root = os.environ.get("COGNITIVEOS_VAULT_ROOT", ".")
    db_path = os.environ.get("COGNITIVEOS_DB_PATH")
    return RetrievalService(vault_root, db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CognitiveOS read-only MCP server")
    parser.add_argument("--vault-root", default=os.environ.get("COGNITIVEOS_VAULT_ROOT", "."))
    parser.add_argument("--db", default=os.environ.get("COGNITIVEOS_DB_PATH"))
    args = parser.parse_args()
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        if os.environ.get("COGNITIVEOS_REQUIRE_MCP_SDK") == "1":
            raise SystemExit("Install the MCP extra first: pip install -e .[mcp]") from exc
        run_basic_stdio_server(RetrievalService(args.vault_root, args.db))
        return

    service = RetrievalService(args.vault_root, args.db)
    mcp = FastMCP("cognitiveos")

    @mcp.tool()
    def search_notes(
        query: str,
        type: str | None = None,
        limit: int = 10,
        status: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        semantic_mode: str = "off",
    ) -> list[dict[str, Any]]:
        """Search indexed Markdown notes."""
        query = require_text("query", query)
        return [
            search_result_to_dict(result)
            for result in service.search_notes(
                query,
                note_type=type,
                limit=normalize_limit(limit, default=10, maximum=50),
                status=status,
                domain=domain,
                tag=tag,
                semantic_mode=normalize_semantic_mode(semantic_mode),
            )
        ]

    @mcp.tool()
    def read_note(note_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        """Read one indexed Markdown note by note id or vault-relative path."""
        note_id, path = normalize_note_reference(note_id=note_id, path=path)
        return service.read_note(note_id=note_id, path=path)

    @mcp.tool()
    def list_recent_notes(limit: int = 10) -> list[dict[str, Any]]:
        """List recently modified indexed notes."""
        return service.list_recent_notes(normalize_limit(limit, default=10, maximum=50))

    @mcp.tool()
    def get_backlinks(note_id: str) -> list[dict[str, Any]]:
        """Return notes that link to the selected note."""
        note_id = require_text("note_id", note_id)
        return service.get_backlinks(note_id)

    @mcp.tool()
    def get_related_notes(note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return notes related by title, headings, and explicit links."""
        note_id = require_text("note_id", note_id)
        return service.get_related_notes(note_id, normalize_limit(limit, default=10, maximum=50))

    @mcp.tool()
    def suggest_links(note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Suggest candidate internal links for a note. Read-only."""
        note_id = require_text("note_id", note_id)
        return service.suggest_links(note_id, normalize_limit(limit, default=10, maximum=50))

    @mcp.tool()
    def summarize_source(note_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        """Return an extractive source summary with evidence. Read-only."""
        note_id, path = normalize_note_reference(note_id=note_id, path=path)
        return service.summarize_source(note_id=note_id, path=path)

    @mcp.tool()
    def propose_moc(query: str, limit: int = 10) -> dict[str, Any]:
        """Propose a map-of-content outline from retrieved notes. Read-only."""
        query = require_text("query", query)
        return service.propose_moc(query, normalize_limit(limit, default=10, maximum=50))

    @mcp.tool()
    def build_context_pack(
        query: str,
        limit: int = 5,
        token_budget: int = 4000,
        semantic_mode: str = "off",
    ) -> dict[str, Any]:
        """Build a compact evidence pack for a query."""
        query = require_text("query", query)
        return context_pack_to_dict(
            service.build_context_pack(
                query,
                normalize_limit(limit, default=5, maximum=20),
                normalize_token_budget(token_budget),
                normalize_semantic_mode(semantic_mode),
            )
        )

    mcp.run()


def run_basic_stdio_server(service: RetrievalService) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_message(service, message)
        except Exception as exc:  # Keep stderr for logs; stdout must stay protocol-only.
            request_id = None
            try:
                request_id = json.loads(line).get("id")
            except Exception:
                pass
            response = error_response(request_id, -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def handle_message(service: RetrievalService, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion") or PROTOCOL_VERSION
        return result_response(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "cognitiveos",
                    "title": "CognitiveOS Read-only PKM",
                    "version": "0.3.0a1",
                    "description": "Read-only search and retrieval tools for a local Obsidian Markdown vault.",
                },
                "instructions": "Read-only vault tools. This server never writes to source Markdown files.",
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return result_response(request_id, {})
    if method == "tools/list":
        return result_response(request_id, {"tools": tool_definitions()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return error_response(request_id, -32602, "tool arguments must be an object")
        return call_tool(service, request_id, name, arguments)
    return error_response(request_id, -32601, f"unknown method: {method}")


def call_tool(
    service: RetrievalService,
    request_id: Any,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    try:
        if name == "search_notes":
            query = require_text("query", arguments.get("query"))
            result = [
                search_result_to_dict(item)
                for item in service.search_notes(
                    query=query,
                    note_type=optional_text(arguments.get("type")),
                    limit=normalize_limit(arguments.get("limit"), default=10, maximum=50),
                    status=optional_text(arguments.get("status")),
                    domain=optional_text(arguments.get("domain")),
                    tag=optional_text(arguments.get("tag")),
                    semantic_mode=normalize_semantic_mode(arguments.get("semantic_mode")),
                )
            ]
        elif name == "read_note":
            note_id, path = normalize_note_reference(note_id=arguments.get("note_id"), path=arguments.get("path"))
            result = service.read_note(note_id=note_id, path=path)
        elif name == "list_recent_notes":
            result = service.list_recent_notes(limit=normalize_limit(arguments.get("limit"), default=10, maximum=50))
        elif name == "get_backlinks":
            result = service.get_backlinks(note_id=require_text("note_id", arguments.get("note_id")))
        elif name == "get_related_notes":
            result = service.get_related_notes(
                note_id=require_text("note_id", arguments.get("note_id")),
                limit=normalize_limit(arguments.get("limit"), default=10, maximum=50),
            )
        elif name == "suggest_links":
            result = service.suggest_links(
                note_id=require_text("note_id", arguments.get("note_id")),
                limit=normalize_limit(arguments.get("limit"), default=10, maximum=50),
            )
        elif name == "summarize_source":
            note_id, path = normalize_note_reference(note_id=arguments.get("note_id"), path=arguments.get("path"))
            result = service.summarize_source(note_id=note_id, path=path)
        elif name == "propose_moc":
            result = service.propose_moc(
                query=require_text("query", arguments.get("query")),
                limit=normalize_limit(arguments.get("limit"), default=10, maximum=50),
            )
        elif name == "build_context_pack":
            result = context_pack_to_dict(
                service.build_context_pack(
                    query=require_text("query", arguments.get("query")),
                    limit=normalize_limit(arguments.get("limit"), default=5, maximum=20),
                    token_budget=normalize_token_budget(arguments.get("token_budget")),
                    semantic_mode=normalize_semantic_mode(arguments.get("semantic_mode")),
                )
            )
        else:
            return error_response(request_id, -32602, f"unknown tool: {name}")
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        return result_response(
            request_id,
            {
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"result": result},
                "isError": False,
            },
        )
    except ToolInputError as exc:
        return tool_error_response(request_id, exc.code, str(exc))
    except SemanticUnavailableError as exc:
        return tool_error_response(request_id, "semantic_unavailable", str(exc))
    except KeyError as exc:
        return tool_error_response(request_id, "not_found", str(exc))
    except ValueError as exc:
        return tool_error_response(request_id, "invalid_request", str(exc))
    except Exception as exc:
        return tool_error_response(request_id, "internal_error", str(exc))


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_notes",
            "title": "Search notes",
            "description": "Search indexed Markdown notes. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "domain": {"type": "string"},
                    "tag": {"type": "string"},
                    "semantic_mode": {"type": "string", "enum": ["off", "auto", "required"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "read_note",
            "title": "Read note",
            "description": "Read one indexed Markdown note by note id or vault-relative path. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "list_recent_notes",
            "title": "List recent notes",
            "description": "List recently modified indexed notes. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_backlinks",
            "title": "Get backlinks",
            "description": "Return notes that link to the selected note. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_related_notes",
            "title": "Get related notes",
            "description": "Return related notes based on indexed titles, headings, and links. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["note_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "suggest_links",
            "title": "Suggest links",
            "description": "Suggest candidate internal links for a note. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["note_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "summarize_source",
            "title": "Summarize source",
            "description": "Return an extractive source summary with evidence. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "propose_moc",
            "title": "Propose MOC",
            "description": "Propose a map-of-content outline from retrieved notes. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "build_context_pack",
            "title": "Build context pack",
            "description": "Build a compact evidence bundle for a query. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "token_budget": {"type": "integer", "minimum": 512, "maximum": 32768},
                    "semantic_mode": {"type": "string", "enum": ["off", "auto", "required"]},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    ]


def require_text(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ToolInputError("invalid_argument", f"{name} must be a non-empty string")
    value = value.strip()
    if not value:
        raise ToolInputError("invalid_argument", f"{name} must be a non-empty string")
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolInputError("invalid_argument", "optional text argument must be a string")
    value = value.strip()
    return value or None


def normalize_limit(value: Any, default: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolInputError("invalid_argument", "limit must be an integer") from exc
    if limit < 1:
        raise ToolInputError("invalid_argument", "limit must be at least 1")
    return min(limit, maximum)


def normalize_token_budget(value: Any) -> int:
    if value is None:
        return 4000
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError("invalid_argument", "token_budget must be an integer")
    if not 512 <= value <= 32768:
        raise ToolInputError("invalid_argument", "token_budget must be between 512 and 32768")
    return value


def normalize_semantic_mode(value: Any) -> str:
    if value is None:
        return "off"
    if not isinstance(value, str) or value not in {"off", "auto", "required"}:
        raise ToolInputError("invalid_argument", "semantic_mode must be off, auto, or required")
    return value


def normalize_note_reference(note_id: Any = None, path: Any = None) -> tuple[str | None, str | None]:
    normalized_note_id = optional_text(note_id)
    normalized_path = optional_text(path)
    if bool(normalized_note_id) == bool(normalized_path):
        raise ToolInputError("invalid_argument", "provide exactly one of note_id or path")
    return normalized_note_id, normalized_path


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def tool_error_response(request_id: Any, code: str, message: str) -> dict[str, Any]:
    return result_response(
        request_id,
        {
            "content": [{"type": "text", "text": message}],
            "structuredContent": {"error": {"code": code, "message": message}},
            "isError": True,
        },
    )


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
