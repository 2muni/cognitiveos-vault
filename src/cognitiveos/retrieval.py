from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .indexer import VaultIndex, default_index_path
from .models import ContextPack, SearchResult
from .parser import parse_markdown_file
from .safety import resolve_vault_root, safe_resolve_inside


class RetrievalService:
    def __init__(self, vault_root: str | Path, db_path: str | Path | None = None):
        self.vault_root = resolve_vault_root(vault_root)
        self.db_path = Path(db_path) if db_path else default_index_path(self.vault_root)

    def ensure_index(self) -> None:
        with VaultIndex(self.db_path) as index:
            index.create_schema()

    def search_notes(
        self,
        query: str,
        note_type: str | None = None,
        limit: int = 10,
        status: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
    ) -> list[SearchResult]:
        self.ensure_index()
        limit = max(1, min(limit, 50))
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = self._search_fts(conn, query, note_type, limit, status, domain, tag)
            if not rows:
                rows = self._search_like(conn, query, note_type, limit, status, domain, tag)
            return [
                SearchResult(
                    note_id=row["note_id"],
                    path=row["path"],
                    title=row["title"],
                    note_type=row["type"],
                    score=float(row["score"]),
                    matched_excerpt=row["matched_excerpt"] or "",
                )
                for row in rows
            ]

    def read_note(self, note_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        if not note_id and not path:
            raise ValueError("note_id or path is required")
        self.ensure_index()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if note_id:
                row = conn.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            else:
                safe_path = safe_resolve_inside(self.vault_root, path or "")
                rel_path = safe_path.relative_to(self.vault_root).as_posix()
                row = conn.execute("SELECT * FROM notes WHERE path = ?", (rel_path,)).fetchone()
            if row is None:
                raise KeyError("note not found")
            parsed = parse_markdown_file(row["path"], self.vault_root)
            return {
                "note_id": parsed.note_id,
                "path": parsed.path,
                "title": parsed.title,
                "type": parsed.note_type,
                "status": parsed.status,
                "frontmatter": parsed.frontmatter,
                "body": parsed.body,
                "headings": [heading.__dict__ for heading in parsed.headings],
                "links": [link.__dict__ for link in parsed.links],
                "checksum": parsed.checksum,
            }

    def list_recent_notes(self, limit: int = 10) -> list[dict[str, Any]]:
        self.ensure_index()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT note_id, path, title, type, status, mtime FROM notes ORDER BY mtime DESC LIMIT ?",
                (max(1, min(limit, 50)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_backlinks(self, note_id: str) -> list[dict[str, Any]]:
        self.ensure_index()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            target = conn.execute("SELECT note_id, path, title FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            if target is None:
                raise KeyError("note not found")
            candidates = {target["note_id"], target["path"], target["title"], Path(target["path"]).stem}
            placeholders = ",".join("?" for _ in candidates)
            rows = conn.execute(
                f"""
                SELECT DISTINCT n.note_id, n.path, n.title, n.type, l.target
                FROM links l
                JOIN notes n ON n.note_id = l.source_note_id
                WHERE l.target IN ({placeholders})
                ORDER BY n.title
                """,
                tuple(candidates),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_related_notes(self, note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        note = self.read_note(note_id=note_id)
        query = " ".join([note["title"], *[heading["text"] for heading in note["headings"][:3]]]).strip()
        results = [result for result in self.search_notes(query, limit=limit + 1) if result.note_id != note_id]
        return [result.__dict__ for result in results[:limit]]

    def build_context_pack(self, query: str, limit: int = 5) -> ContextPack:
        results = self.search_notes(query, limit=limit)
        blocks = []
        for index, result in enumerate(results, start=1):
            blocks.append(
                f"[{index}] {result.title}\n"
                f"path: {result.path}\n"
                f"type: {result.note_type}\n"
                f"excerpt: {result.matched_excerpt}"
            )
        return ContextPack(query=query, results=results, context="\n\n".join(blocks))

    def _search_fts(
        self,
        conn: sqlite3.Connection,
        query: str,
        note_type: str | None,
        limit: int,
        status: str | None,
        domain: str | None,
        tag: str | None,
    ) -> list[sqlite3.Row]:
        filter_sql, filter_params = build_note_filters(note_type, status, domain, tag)
        params: list[Any] = [query]
        params.extend(filter_params)
        params.append(limit)
        try:
            return conn.execute(
                f"""
                SELECT n.note_id, n.path, n.title, n.type,
                       bm25(fts_notes) * -1.0 AS score,
                       snippet(fts_notes, 2, '<mark>', '</mark>', '...', 24) AS matched_excerpt
                FROM fts_notes
                JOIN notes n ON n.note_id = fts_notes.note_id
                WHERE fts_notes MATCH ? {filter_sql}
                ORDER BY bm25(fts_notes)
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _search_like(
        self,
        conn: sqlite3.Connection,
        query: str,
        note_type: str | None,
        limit: int,
        status: str | None,
        domain: str | None,
        tag: str | None,
    ) -> list[sqlite3.Row]:
        filter_sql, filter_params = build_note_filters(note_type, status, domain, tag)
        terms = search_terms(query)
        like_clauses = " OR ".join(["n.title LIKE ? OR f.body LIKE ?" for _ in terms])
        if not like_clauses:
            like_clauses = "n.title LIKE ? OR f.body LIKE ?"
            terms = [query]
        like_params: list[Any] = []
        for term in terms:
            pattern = f"%{term}%"
            like_params.extend([pattern, pattern])
        params = [*like_params, *filter_params, limit]
        return conn.execute(
            f"""
            SELECT n.note_id, n.path, n.title, n.type, 0.0 AS score,
                   n.body_preview AS matched_excerpt
            FROM notes n
            JOIN fts_notes f ON f.note_id = n.note_id
            WHERE ({like_clauses}) {filter_sql}
            ORDER BY n.mtime DESC
            LIMIT ?
            """,
            params,
        ).fetchall()


def context_pack_to_dict(pack: ContextPack) -> dict[str, Any]:
    return {
        "query": pack.query,
        "context": pack.context,
        "results": [result.__dict__ for result in pack.results],
    }


def build_note_filters(
    note_type: str | None,
    status: str | None,
    domain: str | None,
    tag: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if note_type:
        clauses.append("n.type = ?")
        params.append(note_type)
    if status:
        clauses.append("n.status = ?")
        params.append(status)
    if domain:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM note_frontmatter nf
                WHERE nf.note_id = n.note_id
                  AND nf.key IN ('domain', 'domains')
                  AND nf.value = ?
            )
            """
        )
        params.append(domain)
    if tag:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM note_frontmatter nf
                WHERE nf.note_id = n.note_id
                  AND nf.key IN ('tag', 'tags')
                  AND nf.value = ?
            )
            """
        )
        params.append(tag)
    if not clauses:
        return "", params
    return "AND " + " AND ".join(clauses), params


def search_terms(query: str) -> list[str]:
    return [term for term in re.split(r"[^0-9A-Za-z가-힣_]+", query) if term]
