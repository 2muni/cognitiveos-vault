from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .embedding_index import (
    SemanticCandidate,
    SemanticUnavailableError,
    default_embedding_index_path,
    search_embedding_index,
)
from .embeddings import EmbeddingError, EmbeddingProvider, embed_query, provider_identity
from .indexer import VaultIndex, default_index_path
from .models import ContextPack, SearchResult
from .parser import parse_markdown_file
from .safety import resolve_vault_root, safe_resolve_inside


class RetrievalService:
    def __init__(
        self,
        vault_root: str | Path,
        db_path: str | Path | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_db_path: str | Path | None = None,
    ):
        self.vault_root = resolve_vault_root(vault_root)
        self.db_path = Path(db_path) if db_path else default_index_path(self.vault_root)
        self.embedding_provider = embedding_provider
        self.embedding_db_path = (
            Path(embedding_db_path)
            if embedding_db_path
            else default_embedding_index_path(self.vault_root)
        )

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
        semantic_mode: str = "off",
    ) -> list[SearchResult]:
        if semantic_mode not in {"off", "auto", "required"}:
            raise ValueError("semantic_mode must be off, auto, or required")
        requested_limit = max(1, min(limit, 50))
        if semantic_mode == "off":
            return self._search_lexical(query, note_type, requested_limit, status, domain, tag)

        candidate_limit = min(max(requested_limit * 4, 25), 50)
        lexical = self._search_lexical(query, note_type, candidate_limit, status, domain, tag)
        try:
            semantic = self._search_semantic(
                query,
                note_type,
                candidate_limit,
                status,
                domain,
                tag,
                require_complete=semantic_mode == "required",
            )
        except (EmbeddingError, SemanticUnavailableError, ValueError) as exc:
            if semantic_mode == "required":
                if isinstance(exc, SemanticUnavailableError):
                    raise
                raise SemanticUnavailableError("semantic retrieval is unavailable") from exc
            return lexical[:requested_limit]
        return self._fuse_search_results(lexical, semantic, semantic_mode, requested_limit)

    def _search_lexical(
        self,
        query: str,
        note_type: str | None,
        limit: int,
        status: str | None,
        domain: str | None,
        tag: str | None,
    ) -> list[SearchResult]:
        self.ensure_index()
        limit = max(1, min(limit, 50))
        candidate_limit = min(max(limit * 4, 25), 200)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = self._search_fts(conn, query, note_type, candidate_limit, status, domain, tag)
            if not rows:
                rows = self._search_like(conn, query, note_type, candidate_limit, status, domain, tag)
            results = [
                SearchResult(
                    note_id=row["note_id"],
                    path=row["path"],
                    title=row["title"],
                    note_type=row["type"],
                    score=search_relevance_score(query, row),
                    matched_excerpt=row["matched_excerpt"] or "",
                )
                for row in rows
            ]
            results.sort(key=lambda result: (-result.score, result.title, result.path))
            return results[:limit]

    def _search_semantic(
        self,
        query: str,
        note_type: str | None,
        limit: int,
        status: str | None,
        domain: str | None,
        tag: str | None,
        *,
        require_complete: bool,
    ) -> list[SemanticCandidate]:
        if self.embedding_provider is None:
            raise SemanticUnavailableError("embedding provider is unavailable")
        identity = provider_identity(self.embedding_provider)
        query_vector = embed_query(self.embedding_provider, query)
        current_checksums = self._eligible_note_checksums(note_type, status, domain, tag)
        return search_embedding_index(
            self.embedding_db_path,
            identity,
            query_vector,
            current_checksums,
            limit=limit,
            require_complete=require_complete,
        )

    def _eligible_note_checksums(
        self,
        note_type: str | None,
        status: str | None,
        domain: str | None,
        tag: str | None,
    ) -> dict[str, str]:
        self.ensure_index()
        filter_sql, params = build_note_filters(note_type, status, domain, tag)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT n.note_id, n.checksum FROM notes n WHERE 1 = 1 {filter_sql}",
                params,
            ).fetchall()
            return {row["note_id"]: row["checksum"] for row in rows}

    def _fuse_search_results(
        self,
        lexical: list[SearchResult],
        semantic: list[SemanticCandidate],
        semantic_mode: str,
        limit: int,
    ) -> list[SearchResult]:
        lexical_by_id = {result.note_id: result for result in lexical}
        semantic_by_id = {result.note_id: result for result in semantic}
        lexical_ranks = {result.note_id: rank for rank, result in enumerate(lexical, start=1)}
        semantic_ranks = {result.note_id: rank for rank, result in enumerate(semantic, start=1)}
        note_ids = set(lexical_by_id) | set(semantic_by_id)
        metadata = self._note_metadata(note_ids - set(lexical_by_id))
        fused: list[SearchResult] = []
        for note_id in note_ids:
            lexical_result = lexical_by_id.get(note_id)
            semantic_result = semantic_by_id.get(note_id)
            lexical_rank = lexical_ranks.get(note_id)
            semantic_rank = semantic_ranks.get(note_id)
            fusion_score = 0.0
            if lexical_rank is not None:
                fusion_score += 1.0 / (60 + lexical_rank)
            if semantic_rank is not None:
                fusion_score += 1.0 / (60 + semantic_rank)
            if lexical_result is not None:
                path = lexical_result.path
                title = lexical_result.title
                note_type = lexical_result.note_type
                excerpt = lexical_result.matched_excerpt
            else:
                row = metadata[note_id]
                path = row["path"]
                title = row["title"]
                note_type = row["type"]
                excerpt = semantic_result.excerpt if semantic_result else ""
            fused.append(
                SearchResult(
                    note_id=note_id,
                    path=path,
                    title=title,
                    note_type=note_type,
                    score=round(fusion_score, 8),
                    matched_excerpt=excerpt,
                    retrieval={
                        "version": "hybrid-v0.1",
                        "semantic_mode": semantic_mode,
                        "semantic_used": True,
                        "lexical_rank": lexical_rank,
                        "semantic_rank": semantic_rank,
                        "fusion_score": round(fusion_score, 8),
                    },
                )
            )
        fused.sort(key=lambda result: (-result.score, result.title, result.path))
        return fused[:limit]

    def _note_metadata(self, note_ids: set[str]) -> dict[str, sqlite3.Row]:
        if not note_ids:
            return {}
        placeholders = ",".join("?" for _ in note_ids)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT note_id, path, title, type FROM notes WHERE note_id IN ({placeholders})",
                tuple(sorted(note_ids)),
            ).fetchall()
            return {row["note_id"]: row for row in rows}

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
        return [search_result_to_dict(result) for result in results[:limit]]

    def suggest_links(self, note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        note = self.read_note(note_id=note_id)
        existing_targets = {link["target"] for link in note["links"]}
        existing_targets.update({link["display"] for link in note["links"] if link.get("display")})
        query = " ".join(
            [note["title"], *[heading["text"] for heading in note["headings"][:5]], note["body"][:500]]
        ).strip()
        if not query:
            query = note["body"][:200]
        source_terms = keyword_set(query)
        candidates = self.search_notes(query, limit=max(limit * 4, 20))
        suggestions: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.note_id == note_id:
                continue
            target_names = {candidate.note_id, candidate.path, candidate.title, Path(candidate.path).stem}
            if existing_targets.intersection(target_names):
                continue
            candidate_note = self.read_note(note_id=candidate.note_id)
            candidate_text = " ".join(
                [
                    candidate_note["title"],
                    *[heading["text"] for heading in candidate_note["headings"][:5]],
                    candidate_note["body"][:800],
                ]
            )
            overlap = sorted(source_terms.intersection(keyword_set(candidate_text)))
            overlap_score = float(len(overlap))
            suggestions.append(
                {
                    "note_id": candidate.note_id,
                    "path": candidate.path,
                    "title": candidate.title,
                    "type": candidate.note_type,
                    "reason": link_reason(candidate.matched_excerpt, overlap),
                    "score": candidate.score + overlap_score,
                }
            )
        suggestions.sort(key=lambda item: (-float(item["score"]), item["title"]))
        return suggestions[: max(1, min(limit, 50))]

    def summarize_source(self, note_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        note = self.read_note(note_id=note_id, path=path)
        body = note["body"].strip()
        blocks = content_blocks(body)
        evidence = select_evidence_blocks(blocks, max_blocks=5)
        key_points = key_points_from_blocks(evidence, max_points=5)
        open_questions = questions_from_blocks(blocks, max_questions=5)
        summary_parts = [note["title"], *key_points[:3]]
        summary = " ".join(part for part in summary_parts if part)
        if len(summary) > 800:
            summary = summary[:797].rstrip() + "..."
        return {
            "note_id": note["note_id"],
            "path": note["path"],
            "title": note["title"],
            "type": note["type"],
            "summary_version": "extractive-v0.2",
            "summary": summary,
            "key_points": key_points,
            "open_questions": open_questions,
            "headings": note["headings"][:10],
            "evidence": evidence,
            "stats": {
                "heading_count": len(note["headings"]),
                "link_count": len(note["links"]),
                "evidence_count": len(evidence),
                "word_count": len(search_terms(strip_markdown(body))),
            },
        }

    def propose_moc(self, query: str, limit: int = 10) -> dict[str, Any]:
        results = self.search_notes(query, limit=limit)
        sections: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            sections.setdefault(result.note_type, []).append(
                {
                    "note_id": result.note_id,
                    "path": result.path,
                    "title": result.title,
                    "excerpt": result.matched_excerpt,
                }
            )
        ordered_sections = [
            {"type": section_type, "notes": notes}
            for section_type, notes in sorted(sections.items(), key=lambda item: note_type_rank(item[0]))
        ]
        return {
            "query": query,
            "title": f"MOC: {query}",
            "sections": ordered_sections,
            "note_count": len(results),
            "writeback": False,
        }

    def build_context_pack(
        self,
        query: str,
        limit: int = 5,
        token_budget: int = 4000,
        semantic_mode: str = "off",
    ) -> ContextPack:
        limit = max(1, min(limit, 20))
        token_budget = validate_token_budget(token_budget)
        candidate_limit = min(max(limit * 4, 20), 50)
        candidates = self.search_notes(query, limit=candidate_limit, semantic_mode=semantic_mode)
        selected_results = select_diverse_results(candidates, limit)
        included_results: list[SearchResult] = []
        source_lines: list[list[str]] = []
        sources: list[dict[str, Any]] = []
        key_points: list[str] = []
        evidence_paths: list[str] = []
        total_word_count = 0
        truncated = False

        for result in selected_results:
            rank = len(included_results) + 1
            base_lines = [
                f"[{rank}] {result.title}",
                f"path: {result.path}",
                f"type: {result.note_type}",
                f"excerpt: {result.matched_excerpt}",
            ]
            proposed_lines = [*source_lines, base_lines]
            if estimate_tokens(render_context(proposed_lines)) > token_budget:
                truncated = True
                continue
            summary = self.summarize_source(note_id=result.note_id)
            total_word_count += int(summary.get("stats", {}).get("word_count") or 0)
            included_results.append(result)
            source_lines.append(base_lines)
            if result.path not in evidence_paths:
                evidence_paths.append(result.path)
            sources.append(
                {
                    "rank": rank,
                    "note_id": result.note_id,
                    "path": result.path,
                    "title": result.title,
                    "type": result.note_type,
                    "score": result.score,
                    "matched_excerpt": result.matched_excerpt,
                    "summary": summary.get("summary", ""),
                    "key_points": [],
                    "evidence": [],
                    "stats": summary.get("stats", {}),
                    "_pending_key_points": summary.get("key_points", [])[:3],
                    "_pending_evidence": summary.get("evidence", [])[:3],
                }
            )

        pending_items: list[list[tuple[str, str]]] = []
        for source in sources:
            items: list[tuple[str, str]] = []
            source_key_points = source.pop("_pending_key_points")
            source_evidence = source.pop("_pending_evidence")
            for index in range(max(len(source_key_points), len(source_evidence))):
                if index < len(source_key_points):
                    items.append(("key_point", source_key_points[index]))
                if index < len(source_evidence):
                    items.append(("evidence", source_evidence[index]))
            pending_items.append(items)

        while any(pending_items):
            made_progress = False
            for source_index, items in enumerate(pending_items):
                if not items:
                    continue
                kind, value = items.pop(0)
                line = f"{kind}: {strip_markdown(value)}"
                source_lines[source_index].append(line)
                if estimate_tokens(render_context(source_lines)) > token_budget:
                    source_lines[source_index].pop()
                    truncated = True
                    continue
                made_progress = True
                if kind == "key_point":
                    sources[source_index]["key_points"].append(value)
                    if value not in key_points:
                        key_points.append(value)
                else:
                    sources[source_index]["evidence"].append(value)
            if not made_progress and any(pending_items):
                truncated = True

        context = render_context(source_lines)
        estimated_tokens = estimate_tokens(context)
        return ContextPack(
            query=query,
            results=included_results,
            context=context,
            context_version="context-pack-v0.3",
            sources=sources,
            key_points=key_points[:12],
            evidence_paths=evidence_paths,
            stats={
                "source_count": len(sources),
                "candidate_count": len(candidates),
                "selected_source_count": len(selected_results),
                "omitted_source_count": len(selected_results) - len(sources),
                "evidence_path_count": len(evidence_paths),
                "key_point_count": len(key_points[:12]),
                "source_word_count": total_word_count,
            },
            budget={
                "requested_tokens": token_budget,
                "estimated_tokens": estimated_tokens,
                "remaining_tokens": token_budget - estimated_tokens,
                "truncated": truncated,
                "estimator": "local-heuristic-v1",
            },
        )

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
                SELECT n.note_id, n.path, n.title, n.type, n.status, n.mtime,
                       bm25(fts_notes) * -1.0 AS score,
                       COALESCE((
                           SELECT group_concat(h.text, ' ')
                           FROM headings h
                           WHERE h.note_id = n.note_id
                       ), '') AS heading_text,
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
            SELECT n.note_id, n.path, n.title, n.type, n.status, n.mtime, 0.0 AS score,
                   COALESCE((
                       SELECT group_concat(h.text, ' ')
                       FROM headings h
                       WHERE h.note_id = n.note_id
                   ), '') AS heading_text,
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
        "context_version": pack.context_version,
        "context": pack.context,
        "results": [search_result_to_dict(result) for result in pack.results],
        "sources": pack.sources,
        "key_points": pack.key_points,
        "evidence_paths": pack.evidence_paths,
        "stats": pack.stats,
        "budget": pack.budget,
    }


def search_result_to_dict(result: SearchResult) -> dict[str, Any]:
    payload = {
        "note_id": result.note_id,
        "path": result.path,
        "title": result.title,
        "note_type": result.note_type,
        "score": result.score,
        "matched_excerpt": result.matched_excerpt,
    }
    if result.retrieval is not None:
        payload["retrieval"] = result.retrieval
    return payload


def validate_token_budget(token_budget: Any) -> int:
    if isinstance(token_budget, bool) or not isinstance(token_budget, int):
        raise ValueError("token_budget must be an integer")
    if not 512 <= token_budget <= 32768:
        raise ValueError("token_budget must be between 512 and 32768")
    return token_budget


def estimate_tokens(text: str) -> int:
    ascii_characters = sum(1 for character in text if character.isascii())
    non_ascii_characters = len(text) - ascii_characters
    return math.ceil(ascii_characters / 4) + non_ascii_characters


def select_diverse_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
    selected: list[SearchResult] = []
    selected_ids: set[str] = set()
    selected_types: set[str] = set()
    for result in results:
        if result.note_type in selected_types:
            continue
        selected.append(result)
        selected_ids.add(result.note_id)
        selected_types.add(result.note_type)
        if len(selected) >= limit:
            return selected
    for result in results:
        if result.note_id in selected_ids:
            continue
        selected.append(result)
        selected_ids.add(result.note_id)
        if len(selected) >= limit:
            break
    return selected


def render_context(source_lines: list[list[str]]) -> str:
    return "\n\n".join("\n".join(lines) for lines in source_lines)


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


def search_relevance_score(query: str, row: sqlite3.Row) -> float:
    terms = {term.lower() for term in search_terms(query)}
    title = str(row["title"] or "")
    heading_text = str(row["heading_text"] or "")
    path = str(row["path"] or "")
    note_type = str(row["type"] or "")
    status = str(row["status"] or "")
    excerpt = str(row["matched_excerpt"] or "")
    title_terms = keyword_set(title)
    heading_terms = keyword_set(heading_text)
    path_terms = keyword_set(path.replace("/", " ").replace("-", " ").replace("_", " "))
    excerpt_terms = keyword_set(excerpt)
    score = float(row["score"] or 0.0)
    title_lower = title.lower()
    query_lower = strip_markdown(query).lower().strip()
    if query_lower and query_lower == title_lower:
        score += 12.0
    elif query_lower and query_lower in title_lower:
        score += 8.0
    score += 4.0 * len(terms.intersection(title_terms))
    score += 2.5 * len(terms.intersection(heading_terms))
    score += 1.5 * len(terms.intersection(path_terms))
    score += 0.5 * len(terms.intersection(excerpt_terms))
    score += note_type_search_boost(note_type)
    score += status_search_boost(status)
    score += freshness_boost(row["mtime"])
    return round(score, 6)


def note_type_search_boost(note_type: str) -> float:
    boosts = {
        "map": 1.2,
        "project": 1.0,
        "concept": 0.9,
        "source": 0.6,
        "system": 0.4,
        "entity": 0.3,
        "output": 0.2,
        "journal": 0.1,
        "inbox": 0.0,
    }
    return boosts.get(note_type, 0.0)


def status_search_boost(status: str) -> float:
    boosts = {
        "evergreen": 1.0,
        "active": 0.8,
        "seed": 0.2,
        "inbox": 0.0,
        "archived": -1.0,
    }
    return boosts.get(status, 0.0)


def freshness_boost(mtime: Any) -> float:
    try:
        value = float(mtime)
    except (TypeError, ValueError):
        return 0.0
    # Small stable nudge; relevance signals should dominate.
    return min(max(value / 10_000_000_000, 0.0), 0.2)


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"[*_`>#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_blocks(body: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(" ".join(current).strip())
                current = []
            continue
        if stripped.startswith("#"):
            if current:
                blocks.append(" ".join(current).strip())
                current = []
            blocks.append(stripped)
            continue
        if stripped.startswith(("- ", "* ", "+ ")):
            if current:
                blocks.append(" ".join(current).strip())
                current = []
            blocks.append(stripped)
            continue
        current.append(stripped)
    if current:
        blocks.append(" ".join(current).strip())
    return [block for block in blocks if strip_markdown(block)]


def select_evidence_blocks(blocks: list[str], max_blocks: int = 5) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    total = max(1, len(blocks))
    for index, block in enumerate(blocks):
        plain = strip_markdown(block)
        if not plain:
            continue
        score = 0
        if block.lstrip().startswith("#"):
            score += 4
        if block.lstrip().startswith(("- ", "* ", "+ ")):
            score += 3
        if 40 <= len(plain) <= 400:
            score += 2
        if any(marker in plain.lower() for marker in ("decision", "rationale", "result", "because", "therefore")):
            score += 2
        if index >= total // 2:
            score += 1
        scored.append((-score, index, block))
    scored.sort()
    selected = sorted(scored[:max_blocks], key=lambda item: item[1])
    return [block for _score, _index, block in selected]


def key_points_from_blocks(blocks: list[str], max_points: int = 5) -> list[str]:
    points: list[str] = []
    for block in blocks:
        plain = strip_markdown(block)
        if not plain:
            continue
        if plain.endswith("?"):
            continue
        if len(plain) > 220:
            plain = plain[:217].rstrip() + "..."
        if plain not in points:
            points.append(plain)
        if len(points) >= max_points:
            break
    return points


def questions_from_blocks(blocks: list[str], max_questions: int = 5) -> list[str]:
    questions: list[str] = []
    for block in blocks:
        plain = strip_markdown(block)
        if "?" not in plain:
            continue
        for part in re.split(r"(?<=[?])\s+", plain):
            part = part.strip()
            if part.endswith("?") and part not in questions:
                questions.append(part)
            if len(questions) >= max_questions:
                return questions
    return questions


def keyword_set(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "for",
        "from",
        "in",
        "is",
        "of",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
    return {term.lower() for term in search_terms(strip_markdown(text)) if len(term) > 2 and term.lower() not in stopwords}


def link_reason(excerpt: str, overlap: list[str]) -> str:
    if overlap:
        terms = ", ".join(overlap[:8])
        return f"Shared terms: {terms}. Evidence: {excerpt}"
    return excerpt


def note_type_rank(note_type: str) -> tuple[int, str]:
    order = {
        "map": 0,
        "project": 1,
        "concept": 2,
        "entity": 3,
        "source": 4,
        "system": 5,
        "output": 6,
        "journal": 7,
        "inbox": 8,
    }
    return (order.get(note_type, 99), note_type)


def search_terms(query: str) -> list[str]:
    return [term for term in re.split(r"[^\w]+", query, flags=re.UNICODE) if term]
    return [term for term in re.split(r"[^0-9A-Za-z가-힣_]+", query) if term]
