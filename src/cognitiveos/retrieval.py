from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from .embedding_index import (
    SemanticCandidate,
    SemanticUnavailableError,
    default_embedding_index_path,
    search_embedding_index,
)
from .embeddings import EmbeddingError, EmbeddingProvider, embed_query, provider_identity
from .indexer import VaultIndex, default_index_path, frontmatter_string_values
from .models import ContextPack, SearchResult
from .parser import parse_markdown_file
from .safety import resolve_vault_root, safe_resolve_inside

GraphRelationship = dict[str, set[str]]
GraphAdjacency = dict[str, dict[str, GraphRelationship]]
GraphFileSignature = tuple[int, int, int, int]
GraphGeneration = tuple[int, int, int, int, int, str, int, int, int]


class RetrievalService:
    def __init__(
        self,
        vault_root: str | Path,
        db_path: str | Path | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_db_path: str | Path | None = None,
        semantic_unavailable_reason: str | None = None,
    ):
        self.vault_root = resolve_vault_root(vault_root)
        self.db_path = Path(db_path) if db_path else default_index_path(self.vault_root)
        self.embedding_provider = embedding_provider
        self.semantic_unavailable_reason = semantic_unavailable_reason
        self.embedding_db_path = (
            Path(embedding_db_path)
            if embedding_db_path
            else default_embedding_index_path(self.vault_root)
        )
        self._graph_cache_generation: GraphGeneration | None = None
        self._graph_cache: GraphAdjacency | None = None

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
        diagnostics: bool = False,
    ) -> list[SearchResult]:
        if semantic_mode not in {"off", "auto", "required"}:
            raise ValueError("semantic_mode must be off, auto, or required")
        requested_limit = max(1, min(limit, 50))
        if semantic_mode == "off":
            lexical = self._search_lexical(
                query, note_type, requested_limit, status, domain, tag, diagnostics=diagnostics
            )
            return self._attach_lexical_diagnostics(query, lexical) if diagnostics else lexical

        candidate_limit = min(max(requested_limit * 4, 25), 50)
        lexical = self._search_lexical(
            query, note_type, candidate_limit, status, domain, tag, diagnostics=diagnostics
        )
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
            fallback = lexical[:requested_limit]
            return self._attach_lexical_diagnostics(query, fallback) if diagnostics else fallback
        fused = self._fuse_search_results(lexical, semantic, semantic_mode, requested_limit)
        return self._attach_hybrid_diagnostics(query, fused) if diagnostics else fused

    def _attach_lexical_diagnostics(
        self, query: str, results: list[SearchResult]
    ) -> list[SearchResult]:
        evidence = self._diagnostic_evidence({result.note_id for result in results})
        return [
            replace(
                result,
                retrieval={
                    "diagnostics": lexical_diagnostics(
                        query,
                        result,
                        evidence.get(result.note_id, {}),
                        (result.retrieval or {}).get("_lexical_components", {}),
                    )
                },
            )
            for result in results
        ]

    def _attach_hybrid_diagnostics(
        self, query: str, results: list[SearchResult]
    ) -> list[SearchResult]:
        evidence = self._diagnostic_evidence({result.note_id for result in results})
        diagnosed: list[SearchResult] = []
        for result in results:
            retrieval = dict(result.retrieval or {})
            retrieval["diagnostics"] = hybrid_diagnostics(
                query,
                result,
                evidence.get(result.note_id, {}),
                retrieval.get("_lexical_components", {}),
            )
            retrieval.pop("_lexical_components", None)
            diagnosed.append(replace(result, retrieval=retrieval))
        return diagnosed

    def _diagnostic_evidence(self, note_ids: set[str]) -> dict[str, dict[str, Any]]:
        """Return read-only evidence for signals not used by the current scorer."""
        if not note_ids:
            return {}
        placeholders = ",".join("?" for _ in note_ids)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            confidence_rows = conn.execute(
                f"""
                SELECT note_id, value
                FROM note_frontmatter
                WHERE key = 'confidence' AND note_id IN ({placeholders})
                """,
                tuple(sorted(note_ids)),
            ).fetchall()
        confidence = {str(row["note_id"]): parse_confidence(row["value"]) for row in confidence_rows}
        adjacency = self._graph_adjacency()
        return {
            note_id: {
                "backlink_count": sum(
                    "incoming" in relationship["directions"]
                    for relationship in adjacency.get(note_id, {}).values()
                ),
                "confidence": confidence.get(note_id),
            }
            for note_id in note_ids
        }

    def _search_lexical(
        self,
        query: str,
        note_type: str | None,
        limit: int,
        status: str | None,
        domain: str | None,
        tag: str | None,
        *,
        diagnostics: bool = False,
    ) -> list[SearchResult]:
        self.ensure_index()
        limit = max(1, min(limit, 50))
        candidate_limit = min(max(limit * 4, 25), 200)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = self._search_fts(conn, query, note_type, candidate_limit, status, domain, tag)
            if not rows:
                rows = self._search_like(conn, query, note_type, candidate_limit, status, domain, tag)
            results = []
            for row in rows:
                components = relevance_components(query, row)
                results.append(SearchResult(
                    note_id=row["note_id"],
                    path=row["path"],
                    title=row["title"],
                    note_type=row["type"],
                    score=components["score"],
                    matched_excerpt=row["matched_excerpt"] or "",
                    retrieval={"_lexical_components": components} if diagnostics else None,
                )
                )
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
            raise SemanticUnavailableError(
                self.semantic_unavailable_reason or "embedding provider is unavailable"
            )
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
                        **(
                            {"_lexical_components": lexical_result.retrieval["_lexical_components"]}
                            if lexical_result is not None
                            and lexical_result.retrieval is not None
                            and "_lexical_components" in lexical_result.retrieval
                            else {}
                        ),
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
        target_metadata = self._note_metadata({note_id})
        if note_id not in target_metadata:
            raise KeyError("note not found")
        incoming = {
            neighbor_id: relationship
            for neighbor_id, relationship in self._graph_adjacency().get(note_id, {}).items()
            if "incoming" in relationship["directions"]
        }
        metadata = self._note_metadata(set(incoming))
        backlinks = [
            {
                "note_id": neighbor_id,
                "path": metadata[neighbor_id]["path"],
                "title": metadata[neighbor_id]["title"],
                "type": metadata[neighbor_id]["type"],
                "target": min(relationship["targets"]),
            }
            for neighbor_id, relationship in incoming.items()
            if neighbor_id in metadata
        ]
        backlinks.sort(key=lambda item: (item["title"], item["path"]))
        return backlinks

    def get_related_notes(self, note_id: str, limit: int = 10) -> list[dict[str, Any]]:
        note = self.read_note(note_id=note_id)
        requested_limit = max(1, min(limit, 50))
        query = " ".join([note["title"], *[heading["text"] for heading in note["headings"][:3]]]).strip()
        lexical = [
            result
            for result in self.search_notes(query, limit=min(max(requested_limit * 4, 20), 50))
            if result.note_id != note_id
        ]
        lexical_by_id = {result.note_id: result for result in lexical}
        lexical_ranks = {result.note_id: rank for rank, result in enumerate(lexical, start=1)}
        adjacency = self._graph_adjacency()
        graph_neighbors = adjacency.get(note_id, {})
        metadata = self._note_metadata(set(graph_neighbors) - set(lexical_by_id))
        related: list[dict[str, Any]] = []
        added_ids: set[str] = set()

        def graph_sort_key(item: tuple[str, dict[str, set[str]]]) -> tuple[float, str, str]:
            neighbor_id, relationship = item
            lexical_result = lexical_by_id.get(neighbor_id)
            row = metadata.get(neighbor_id)
            title = lexical_result.title if lexical_result else str(row["title"] if row else neighbor_id)
            path = lexical_result.path if lexical_result else str(row["path"] if row else "")
            return (-graph_relationship_score(relationship), title, path)

        for neighbor_id, relationship in sorted(graph_neighbors.items(), key=graph_sort_key):
            lexical_result = lexical_by_id.get(neighbor_id)
            row = metadata.get(neighbor_id)
            if lexical_result is None and row is None:
                continue
            graph_score = graph_relationship_score(relationship)
            lexical_rank = lexical_ranks.get(neighbor_id)
            result = SearchResult(
                note_id=neighbor_id,
                path=lexical_result.path if lexical_result else str(row["path"]),
                title=lexical_result.title if lexical_result else str(row["title"]),
                note_type=lexical_result.note_type if lexical_result else str(row["type"]),
                score=round(graph_score + (1.0 / (60 + lexical_rank) if lexical_rank else 0.0), 6),
                matched_excerpt=lexical_result.matched_excerpt if lexical_result else "",
                retrieval={
                    "version": "graph-related-v0.1",
                    "graph_used": True,
                    "directions": sorted(relationship["directions"]),
                    "edge_types": sorted(relationship["edge_types"]),
                    "graph_score": graph_score,
                    "lexical_rank": lexical_rank,
                },
            )
            related.append(search_result_to_dict(result))
            added_ids.add(neighbor_id)
            if len(related) >= requested_limit:
                return related

        for result in lexical:
            if result.note_id in added_ids:
                continue
            related.append(search_result_to_dict(result))
            if len(related) >= requested_limit:
                break
        return related

    def _graph_adjacency(self) -> GraphAdjacency:
        signature = self._graph_file_signature()
        if (
            self._graph_cache_generation is not None
            and self._graph_cache_generation[:4] == signature
            and self._graph_cache is not None
        ):
            return self._graph_cache
        generation = self._graph_index_generation()
        if self._graph_cache_generation == generation and self._graph_cache is not None:
            return self._graph_cache

        adjacency = self._build_graph_adjacency()
        stable_generation = self._graph_index_generation()
        if stable_generation != generation:
            adjacency = self._build_graph_adjacency()
            final_generation = self._graph_index_generation()
            if final_generation != stable_generation:
                self._graph_cache_generation = None
                self._graph_cache = None
                return adjacency
            stable_generation = final_generation
        self._graph_cache_generation = stable_generation
        self._graph_cache = adjacency
        return adjacency

    def _graph_index_generation(self) -> GraphGeneration:
        self.ensure_index()
        with closing(sqlite3.connect(self.db_path)) as conn:
            run = conn.execute(
                """
                SELECT run_id, status, note_count
                FROM index_runs
                ORDER BY run_id DESC
                LIMIT 1
                """
            ).fetchone()
            note_count = int(conn.execute("SELECT count(*) FROM notes").fetchone()[0])
            link_count = int(conn.execute("SELECT count(*) FROM links").fetchone()[0])
        return (
            *self._graph_file_signature(),
            int(run[0]) if run else 0,
            str(run[1]) if run else "missing",
            int(run[2]) if run else 0,
            note_count,
            link_count,
        )

    def _graph_file_signature(self) -> GraphFileSignature:
        stat = self.db_path.stat() if self.db_path.exists() else None
        wal_path = Path(f"{self.db_path}-wal")
        wal_stat = wal_path.stat() if wal_path.exists() else None
        return (
            stat.st_mtime_ns if stat else 0,
            stat.st_size if stat else 0,
            wal_stat.st_mtime_ns if wal_stat else 0,
            wal_stat.st_size if wal_stat else 0,
        )

    def _build_graph_adjacency(self) -> GraphAdjacency:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            notes = conn.execute("SELECT note_id, path, title FROM notes").fetchall()
            aliases = conn.execute(
                """
                SELECT note_id, value
                FROM note_frontmatter
                WHERE key IN ('alias', 'aliases')
                """
            ).fetchall()
            links = conn.execute(
                "SELECT source_note_id, target, link_type FROM links"
            ).fetchall()

        strong_identities: dict[str, set[str]] = defaultdict(set)
        named_identities: dict[str, set[str]] = defaultdict(set)
        for row in notes:
            note_id = str(row["note_id"])
            for value in (note_id, row["path"]):
                normalized = str(value or "").strip().casefold()
                if normalized:
                    strong_identities[normalized].add(note_id)
            for value in (row["title"], Path(str(row["path"])).stem):
                normalized = str(value or "").strip().casefold()
                if normalized:
                    named_identities[normalized].add(note_id)
        for row in aliases:
            normalized = str(row["value"] or "").strip().casefold()
            if normalized:
                named_identities[normalized].add(str(row["note_id"]))

        adjacency: GraphAdjacency = defaultdict(dict)

        def add_edge(source_id: str, neighbor_id: str, direction: str, link_type: str, target: str) -> None:
            relationship = adjacency[source_id].setdefault(
                neighbor_id,
                {"directions": set(), "edge_types": set(), "targets": set()},
            )
            relationship["directions"].add(direction)
            relationship["edge_types"].add(link_type)
            relationship["targets"].add(target)

        for row in links:
            source_id = str(row["source_note_id"])
            target = str(row["target"] or "").strip()
            target_key = target.casefold()
            target_ids = strong_identities.get(target_key) or named_identities.get(target_key, set())
            if len(target_ids) != 1:
                continue
            target_id = next(iter(target_ids))
            if source_id == target_id:
                continue
            link_type = str(row["link_type"])
            add_edge(source_id, target_id, "outgoing", link_type, target)
            add_edge(target_id, source_id, "incoming", link_type, target)
        return {note_id: dict(neighbors) for note_id, neighbors in adjacency.items()}

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
            candidate_note = self.read_note(note_id=candidate.note_id)
            target_names.update(frontmatter_string_values(candidate_note["frontmatter"].get("aliases")))
            if existing_targets.intersection(target_names):
                continue
            candidate_text = " ".join(
                [
                    candidate_note["title"],
                    *frontmatter_string_values(candidate_note["frontmatter"].get("aliases")),
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
        graph_adjacency = self._graph_adjacency()
        selected_results = select_diverse_results(candidates, limit, graph_adjacency)
        graph_pairs: set[tuple[str, str]] = set()
        graph_connected_source_count = 0
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

        included_ids = {result.note_id for result in included_results}
        for source in sources:
            graph_connections = []
            edge_types: set[str] = set()
            for neighbor_id, relationship in sorted(graph_adjacency.get(source["note_id"], {}).items()):
                if neighbor_id not in included_ids:
                    continue
                graph_connections.append(neighbor_id)
                edge_types.update(relationship["edge_types"])
                graph_pairs.add(tuple(sorted((source["note_id"], neighbor_id))))
            if graph_connections:
                graph_connected_source_count += 1
            source["selection"] = {
                "version": "type-diverse-graph-v0.1",
                "graph_connected_to": graph_connections,
                "graph_edge_types": sorted(edge_types),
            }

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
                "selection_version": "type-diverse-graph-v0.1",
                "graph_edge_count": len(graph_pairs),
                "graph_connected_source_count": graph_connected_source_count,
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
                       COALESCE((
                           SELECT group_concat(nf.value, '\n')
                           FROM note_frontmatter nf
                           WHERE nf.note_id = n.note_id
                             AND nf.key IN ('alias', 'aliases')
                       ), '') AS alias_text,
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
        like_clauses = " OR ".join(["f.title LIKE ? OR f.body LIKE ?" for _ in terms])
        if not like_clauses:
            like_clauses = "f.title LIKE ? OR f.body LIKE ?"
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
                   COALESCE((
                       SELECT group_concat(nf.value, '\n')
                       FROM note_frontmatter nf
                       WHERE nf.note_id = n.note_id
                         AND nf.key IN ('alias', 'aliases')
                   ), '') AS alias_text,
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


def select_diverse_results(
    results: list[SearchResult],
    limit: int,
    graph_adjacency: GraphAdjacency | None = None,
) -> list[SearchResult]:
    if not results or limit < 1:
        return []
    graph_adjacency = graph_adjacency or {}
    ranks = {result.note_id: rank for rank, result in enumerate(results)}
    remaining = list(results)
    selected: list[SearchResult] = []
    selected_ids: set[str] = set()
    selected_types: set[str] = set()

    while remaining and len(selected) < limit:
        if not selected:
            chosen = remaining[0]
        else:
            diverse_pool = [result for result in remaining if result.note_type not in selected_types]
            pool = diverse_pool or remaining

            def selection_key(result: SearchResult) -> tuple[int, int]:
                connected = sum(
                    neighbor_id in selected_ids
                    for neighbor_id in graph_adjacency.get(result.note_id, {})
                )
                return (-connected, ranks[result.note_id])

            chosen = min(pool, key=selection_key)
        selected.append(chosen)
        selected_ids.add(chosen.note_id)
        selected_types.add(chosen.note_type)
        remaining.remove(chosen)
    return selected


def graph_relationship_score(relationship: dict[str, set[str]]) -> float:
    directions = relationship.get("directions", set())
    score = 0.0
    if "outgoing" in directions:
        score += 3.0
    if "incoming" in directions:
        score += 2.0
    score += 0.1 * len(relationship.get("edge_types", set()))
    return round(score, 6)


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
    return relevance_components(query, row)["score"]


def relevance_components(query: str, row: sqlite3.Row) -> dict[str, float]:
    """Return the stable components of the existing lexical score.

    This deliberately mirrors the legacy score rather than introducing a new
    ranking algorithm.  Diagnostics can therefore explain a result without
    changing lexical-only retrieval.
    """
    terms = {term.lower() for term in search_terms(query)}
    title = str(row["title"] or "")
    heading_text = str(row["heading_text"] or "")
    path = str(row["path"] or "")
    note_type = str(row["type"] or "")
    status = str(row["status"] or "")
    excerpt = str(row["matched_excerpt"] or "")
    aliases = [alias.strip() for alias in str(row["alias_text"] or "").splitlines() if alias.strip()]
    title_terms = keyword_set(title)
    heading_terms = keyword_set(heading_text)
    path_terms = keyword_set(path.replace("/", " ").replace("-", " ").replace("_", " "))
    excerpt_terms = keyword_set(excerpt)
    lexical = float(row["score"] or 0.0)
    title_score = 0.0
    title_lower = title.lower()
    query_lower = strip_markdown(query).lower().strip()
    if query_lower and query_lower == title_lower:
        title_score += 12.0
    elif query_lower and query_lower in title_lower:
        title_score += 8.0
    alias_lowers = [alias.casefold() for alias in aliases if alias.casefold() != title.casefold()]
    if query_lower and query_lower in alias_lowers:
        lexical += 10.0
    elif query_lower and any(query_lower in alias for alias in alias_lowers):
        lexical += 6.0
    title_score += 4.0 * len(terms.intersection(title_terms))
    alias_terms = keyword_set(" ".join(aliases))
    lexical += 3.0 * len(terms.intersection(alias_terms))
    heading_score = 2.5 * len(terms.intersection(heading_terms))
    lexical += 1.5 * len(terms.intersection(path_terms))
    lexical += 0.5 * len(terms.intersection(excerpt_terms))
    lexical += note_type_search_boost(note_type)
    lexical += status_search_boost(status)
    freshness_score = freshness_boost(row["mtime"])
    score = round(lexical + title_score + heading_score + freshness_score, 6)
    return {
        "score": score,
        "lexical": round(lexical, 6),
        "title": round(title_score, 6),
        "heading": round(heading_score, 6),
        "freshness": round(freshness_score, 6),
    }


def lexical_diagnostics(
    query: str,
    result: SearchResult,
    evidence: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    """Describe a lexical result without exposing source Markdown content."""
    return {
        "version": "retrieval-diagnostics-v0.1",
        "mode": "lexical",
        "score": result.score,
        "contributions": {
            "lexical": {"score": components.get("lexical", 0.0), "applied": True},
            "semantic": {"score": 0.0, "applied": False, "rank": None},
            "title": {"score": components.get("title", 0.0), "applied": True},
            "heading": {"score": components.get("heading", 0.0), "applied": True},
            "backlink": {
                "score": 0.0,
                "applied": False,
                "incoming_count": evidence.get("backlink_count", 0),
            },
            "freshness": {"score": components.get("freshness", 0.0), "applied": True},
            "confidence": {
                "score": 0.0,
                "applied": False,
                "value": evidence.get("confidence"),
            },
        },
    }


def hybrid_diagnostics(
    query: str,
    result: SearchResult,
    evidence: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    retrieval = result.retrieval or {}
    lexical_rank = retrieval.get("lexical_rank")
    semantic_rank = retrieval.get("semantic_rank")
    lexical_score = 1.0 / (60 + lexical_rank) if isinstance(lexical_rank, int) else 0.0
    semantic_score = 1.0 / (60 + semantic_rank) if isinstance(semantic_rank, int) else 0.0
    return {
        "version": "retrieval-diagnostics-v0.1",
        "mode": "hybrid",
        "score": result.score,
        "contributions": {
            "lexical": {"score": round(lexical_score, 8), "applied": lexical_rank is not None},
            "semantic": {
                "score": round(semantic_score, 8),
                "applied": semantic_rank is not None,
                "rank": semantic_rank,
            },
            "title": {
                "score": components.get("title") if lexical_rank is not None else None,
                "applied": lexical_rank is not None,
            },
            "heading": {
                "score": components.get("heading") if lexical_rank is not None else None,
                "applied": lexical_rank is not None,
            },
            "backlink": {
                "score": 0.0,
                "applied": False,
                "incoming_count": evidence.get("backlink_count", 0),
            },
            "freshness": {
                "score": components.get("freshness") if lexical_rank is not None else None,
                "applied": lexical_rank is not None,
            },
            "confidence": {
                "score": 0.0,
                "applied": False,
                "value": evidence.get("confidence"),
            },
        },
    }


def parse_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if math.isfinite(confidence) else None


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
