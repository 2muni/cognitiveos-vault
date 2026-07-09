from __future__ import annotations

import argparse
import json
from pathlib import Path

from .indexer import VaultIndex, default_index_path
from .retrieval import RetrievalService


def main_index() -> None:
    parser = argparse.ArgumentParser(description="Index a CognitiveOS Markdown vault")
    parser.add_argument("vault_root", nargs="?", default=".", help="Vault root path")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    args = parser.parse_args()
    db_path = Path(args.db) if args.db else default_index_path(args.vault_root)
    with VaultIndex(db_path) as index:
        count = index.index_vault(args.vault_root)
    print(f"Indexed {count} notes into {db_path}")


def main_search() -> None:
    parser = argparse.ArgumentParser(description="Search a CognitiveOS Markdown vault")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--vault-root", default=".", help="Vault root path")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    parser.add_argument("--type", default=None, help="Optional note type filter")
    parser.add_argument("--status", default=None, help="Optional lifecycle status filter")
    parser.add_argument("--domain", default=None, help="Optional domain filter")
    parser.add_argument("--tag", default=None, help="Optional tag filter")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    service = RetrievalService(args.vault_root, args.db)
    results = service.search_notes(
        args.query,
        note_type=args.type,
        limit=args.limit,
        status=args.status,
        domain=args.domain,
        tag=args.tag,
    )
    print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
