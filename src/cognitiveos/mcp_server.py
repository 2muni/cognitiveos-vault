from __future__ import annotations

import argparse
import os
from typing import Any

from .retrieval import RetrievalService, context_pack_to_dict


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
        raise SystemExit("Install the MCP extra first: pip install -e .[mcp]") from exc

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


if __name__ == "__main__":
    main()
