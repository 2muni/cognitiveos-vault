from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .retrieval import RetrievalService, context_pack_to_dict

PROTOCOL_VERSION = "2025-11-25"


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
    ) -> list[dict[str, Any]]:
        """Search indexed Markdown notes."""
        return [
            result.__dict__
            for result in service.search_notes(
                query,
                note_type=type,
                limit=limit,
                status=status,
                domain=domain,
                tag=tag,
            )
        ]

    @mcp.tool()
    def read_note(note_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        """Read one indexed Markdown note by note id or vault-relative path."""
        return service.read_note(note_id=note_id, path=path)

    @mcp.tool()
    def list_recent_notes(limit: int = 10) -> list[dict[str, Any]]:
        """List recently modified indexed notes."""
        return service.list_recent_notes(limit)

    @mcp.tool()
    def get_backlinks(note_id: str) -> list[dict[str, Any]]:
        """Return notes that link to the selected note."""
        return service.get_backlinks(note_id)

    @mcp.tool()
    def get_related_notes(note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return notes related by title, headings, and explicit links."""
        return service.get_related_notes(note_id, limit)

    @mcp.tool()
    def build_context_pack(query: str, limit: int = 5) -> dict[str, Any]:
        """Build a compact evidence pack for a query."""
        return context_pack_to_dict(service.build_context_pack(query, limit))

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
                    "version": "0.1.0",
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
            result = [
                item.__dict__
                for item in service.search_notes(
                    query=str(arguments.get("query") or ""),
                    note_type=arguments.get("type"),
                    limit=int(arguments.get("limit") or 10),
                    status=arguments.get("status"),
                    domain=arguments.get("domain"),
                    tag=arguments.get("tag"),
                )
            ]
        elif name == "read_note":
            result = service.read_note(note_id=arguments.get("note_id"), path=arguments.get("path"))
        elif name == "list_recent_notes":
            result = service.list_recent_notes(limit=int(arguments.get("limit") or 10))
        elif name == "get_backlinks":
            result = service.get_backlinks(note_id=str(arguments.get("note_id") or ""))
        elif name == "get_related_notes":
            result = service.get_related_notes(
                note_id=str(arguments.get("note_id") or ""),
                limit=int(arguments.get("limit") or 10),
            )
        elif name == "build_context_pack":
            result = context_pack_to_dict(
                service.build_context_pack(
                    query=str(arguments.get("query") or ""),
                    limit=int(arguments.get("limit") or 5),
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
    except Exception as exc:
        return result_response(
            request_id,
            {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        )


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
            "name": "build_context_pack",
            "title": "Build context pack",
            "description": "Build a compact evidence bundle for a query. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    ]


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
