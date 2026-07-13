from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .embedding_index import EmbeddingIndexBuilder, default_embedding_index_path, embedding_index_status
from .embeddings import EmbeddingProvider, provider_identity
from .indexer import VaultIndex, default_index_path
from .embedding_index import SemanticUnavailableError
from .retrieval import RetrievalService, search_result_to_dict
from .sentence_transformers_adapter import create_sentence_transformers_provider
from .runtime import build_runtime_service
from .validation import ValidationDiagnostic, ValidationReport, validate_vault


EmbeddingProviderFactory = Callable[[str, str, bool, str], EmbeddingProvider]
EMBEDDING_PROVIDER_FACTORIES: dict[str, EmbeddingProviderFactory] = {
    "sentence-transformers": create_sentence_transformers_provider,
}


def main_index() -> None:
    parser = argparse.ArgumentParser(description="Index a CognitiveOS Markdown vault")
    parser.add_argument("vault_root", nargs="?", default=".", help="Vault root path")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
    args = parser.parse_args()
    db_path = Path(args.db) if args.db else default_index_path(args.vault_root)
    with VaultIndex(db_path) as index:
        count = index.index_vault(args.vault_root)
    if args.format == "json":
        print(json.dumps({"indexed_notes": count, "index_path": str(db_path)}, ensure_ascii=False, indent=2))
    else:
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
    parser.add_argument("--semantic-mode", choices=("off", "auto", "required"), default="off")
    parser.add_argument("--format", choices=("text", "json"), default="json", help="Output format")
    args = parser.parse_args()
    service = build_runtime_service(args.vault_root, args.db)
    try:
        results = service.search_notes(
            args.query,
            note_type=args.type,
            limit=args.limit,
            status=args.status,
            domain=args.domain,
            tag=args.tag,
            semantic_mode=args.semantic_mode,
        )
    except SemanticUnavailableError as exc:
        parser.error(str(exc))
    if args.format == "json":
        print(json.dumps([search_result_to_dict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result.score:.6f}\t{result.title}\t{result.path}\t{result.matched_excerpt}")


def main_validate() -> int:
    parser = argparse.ArgumentParser(description="Validate a CognitiveOS Markdown vault without modifying it")
    parser.add_argument("vault_root", nargs="?", default=".", help="Vault root path")
    parser.add_argument(
        "--scope",
        choices=("all", "user"),
        default="user",
        help="Apply authoring warnings to user notes only or all notes",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 when warnings are present",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
    args = parser.parse_args()
    try:
        report = validate_vault(args.vault_root, scope=args.scope, strict=args.strict)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output_validation_report(report, args.format)
    return report.exit_code


def output_validation_report(report: ValidationReport, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"CognitiveOS note validation {report.validation_version}")
    print(
        f"scope={report.scope} strict={str(report.strict).lower()} "
        f"files={report.files_scanned} errors={report.error_count} "
        f"warnings={report.warning_count} info={report.info_count}"
    )
    for item in report.diagnostics:
        print(format_validation_diagnostic(item))


def format_validation_diagnostic(item: ValidationDiagnostic) -> str:
    location = item.path
    if item.line is not None:
        location = f"{location}:{item.line}"
    field = f" field={item.field}" if item.field else ""
    related = f" related={','.join(item.related_paths)}" if item.related_paths else ""
    return f"[{item.severity.upper()}] {location} {item.code}{field}: {item.message}{related}"


def main_embed() -> None:
    parser = argparse.ArgumentParser(description="Build or inspect an optional CognitiveOS embedding index")
    parser.add_argument("--vault-root", default=".", help="Vault root path")
    parser.add_argument("--db", default=None, help="Embedding SQLite DB path")
    parser.add_argument("--status", action="store_true", help="Inspect the embedding index without building")
    parser.add_argument("--provider", default=None, help="Explicit registered provider id")
    parser.add_argument("--model", default=None, help="Explicit provider model id")
    parser.add_argument("--revision", default=None, help="Explicit immutable model revision")
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Explicitly allow the local adapter to download model files",
    )
    parser.add_argument("--device", default="cpu", help="Local inference device (default: cpu)")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--rebuild", action="store_true", help="Disable vector reuse and rebuild every chunk")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
    args = parser.parse_args()
    db_path = Path(args.db) if args.db else default_embedding_index_path(args.vault_root)
    if args.status:
        output_embedding_status(embedding_index_status(db_path), args.format)
        return
    if not args.provider or not args.model or not args.revision:
        parser.error("build requires --provider, --model, and --revision")
    try:
        provider = resolve_embedding_provider(
            args.provider,
            args.model,
            args.revision,
            allow_model_download=args.allow_model_download,
            device=args.device,
        )
        result = EmbeddingIndexBuilder(
            args.vault_root,
            provider,
            db_path,
            batch_size=args.batch_size,
        ).build(rebuild=args.rebuild)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"Built {result.chunk_count} chunks from {result.note_count} notes into {result.index_path} "
            f"({result.embedded_chunk_count} embedded, {result.reused_chunk_count} reused)"
        )


def resolve_embedding_provider(
    provider_id: str,
    model_id: str,
    model_revision: str,
    *,
    allow_model_download: bool = False,
    device: str = "cpu",
) -> EmbeddingProvider:
    factory = EMBEDDING_PROVIDER_FACTORIES.get(provider_id)
    if factory is None:
        raise ValueError(
            f"embedding provider is not registered: {provider_id}"
        )
    provider = factory(model_id, model_revision, allow_model_download, device)
    identity = provider_identity(provider)
    if (
        identity.provider_id,
        identity.model_id,
        identity.model_revision,
    ) != (provider_id, model_id, model_revision):
        raise ValueError("embedding provider identity does not match the requested configuration")
    return provider


def output_embedding_status(status: dict[str, object], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    state = status.get("status", "invalid")
    if state == "completed":
        print(
            f"Embedding index ready: {status.get('chunk_count', 0)} chunks, "
            f"{status.get('provider_id')}/{status.get('model_id')}@{status.get('model_revision')}"
        )
    else:
        print(f"Embedding index {state}: {status.get('index_path')}")
