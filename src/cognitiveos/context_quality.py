"""Deterministic, privacy-safe quality checks for context-pack workflows.

The checks operate only on a pack's already-returned metadata and extractive
evidence.  They neither read Markdown nor require an embedding model, so they
are safe to run in the lexical-only default runtime or by a downstream client.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from .models import ContextPack
from .retrieval import keyword_set, strip_markdown


QUALITY_VERSION = "context-pack-quality-v0.1"
FINGERPRINT_ALGORITHM = "sha256-canonical-json-v1"


def is_vault_relative_path(path: Any) -> bool:
    """Return whether *path* is a portable, traversal-free vault path."""
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    candidate = PurePosixPath(path)
    return not candidate.is_absolute() and all(part not in {"", ".", ".."} for part in candidate.parts)


def context_pack_quality(pack: ContextPack) -> dict[str, Any]:
    """Return stable structural quality gates for an already-built context pack.

    This is intentionally a mechanical check.  It confirms evidence/citation
    structure and deterministic representation; it does not make a semantic
    truth claim about source Markdown or a later model-generated answer.
    """
    source_paths = [source.get("path") for source in pack.sources]
    result_paths = [result.path for result in pack.results]
    all_paths = [*pack.evidence_paths, *source_paths, *result_paths]
    invalid_paths = sorted({path for path in all_paths if not is_vault_relative_path(path)})

    source_evidence = [source.get("evidence", []) for source in pack.sources]
    evidence_block_count = sum(len(items) for items in source_evidence if isinstance(items, list))
    sources_with_evidence = sum(bool(items) for items in source_evidence if isinstance(items, list))
    source_count = len(pack.sources)
    evidence_density = sources_with_evidence / source_count if source_count else 1.0

    result_by_id = {result.note_id: result for result in pack.results}
    expected_paths = list(dict.fromkeys(source_paths))
    source_identity_ok = all(
        isinstance(source.get("note_id"), str)
        and source["note_id"] in result_by_id
        and result_by_id[source["note_id"]].path == source.get("path")
        for source in pack.sources
    )
    evidence_paths_ok = pack.evidence_paths == expected_paths
    rendered_items = _rendered_evidence_items(pack.context)
    available_items = {
        strip_markdown(item)
        for source in pack.sources
        for key in ("key_points", "evidence")
        for item in source.get(key, [])
        if isinstance(item, str)
    }
    grounded_item_count = sum(item in available_items for item in rendered_items)
    grounding_ok = (
        source_identity_ok
        and evidence_paths_ok
        and grounded_item_count == len(rendered_items)
        and all(f"path: {path}" in pack.context for path in expected_paths)
    )

    fingerprint = _fingerprint(
        {
            "query": pack.query,
            "context_version": pack.context_version,
            "context": pack.context,
            "results": [
                {
                    "note_id": result.note_id,
                    "path": result.path,
                    "title": result.title,
                    "note_type": result.note_type,
                    "score": result.score,
                    "matched_excerpt": result.matched_excerpt,
                }
                for result in pack.results
            ],
            "sources": pack.sources,
            "key_points": pack.key_points,
            "evidence_paths": pack.evidence_paths,
            "stats": pack.stats,
            "budget": pack.budget,
        }
    )
    checks = {
        "evidence_density": {
            "status": "pass" if evidence_density >= 1.0 else "fail",
            "source_count": source_count,
            "sources_with_evidence": sources_with_evidence,
            "evidence_block_count": evidence_block_count,
            "ratio": evidence_density,
            "minimum_ratio": 1.0,
        },
        "vault_relative_paths": {
            "status": "pass" if not invalid_paths else "fail",
            "checked_path_count": len(all_paths),
            "invalid_path_count": len(invalid_paths),
        },
        "grounded_content": {
            "status": "pass" if grounding_ok else "fail",
            "source_identity_ok": source_identity_ok,
            "evidence_paths_ok": evidence_paths_ok,
            "rendered_item_count": len(rendered_items),
            "grounded_item_count": grounded_item_count,
        },
        "stability": {
            "status": "pass",
            "algorithm": FINGERPRINT_ALGORITHM,
            "fingerprint": fingerprint,
        },
    }
    return {
        "version": QUALITY_VERSION,
        "status": "pass" if all(check["status"] == "pass" for check in checks.values()) else "fail",
        "checks": checks,
    }


def validate_grounded_answer(answer: str, citations: list[str], pack: ContextPack) -> dict[str, Any]:
    """Mechanically validate an answer against explicit context-pack citations.

    The return value deliberately contains counts and statuses, not answer or
    source text.  A passing result means the answer has valid cited evidence
    and lexical support; it is not a substitute for human factual review.
    """
    answer_terms = keyword_set(answer)
    evidence_by_path: dict[str, set[str]] = {}
    for source in pack.sources:
        path = source.get("path")
        if not isinstance(path, str):
            continue
        evidence_by_path[path] = keyword_set(
            " ".join(item for item in source.get("evidence", []) if isinstance(item, str))
        )
    valid_citations = [path for path in citations if is_vault_relative_path(path) and path in evidence_by_path]
    cited_terms = set().union(*(evidence_by_path[path] for path in valid_citations)) if valid_citations else set()
    overlap_count = len(answer_terms.intersection(cited_terms))
    citations_ok = bool(valid_citations) if answer.strip() else not citations
    grounded = citations_ok and len(valid_citations) == len(citations) and (not answer_terms or overlap_count > 0)
    return {
        "version": QUALITY_VERSION,
        "status": "pass" if grounded else "fail",
        "answer_term_count": len(answer_terms),
        "citation_count": len(citations),
        "valid_citation_count": len(valid_citations),
        "evidence_term_overlap_count": overlap_count,
    }


def _rendered_evidence_items(context: str) -> list[str]:
    items: list[str] = []
    for line in context.splitlines():
        for prefix in ("key_point: ", "evidence: "):
            if line.startswith(prefix):
                items.append(strip_markdown(line[len(prefix) :]))
                break
    return items


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
