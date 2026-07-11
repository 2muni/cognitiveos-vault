from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .embeddings import EmbeddingProvider
from .retrieval import RetrievalService
from .sentence_transformers_adapter import create_sentence_transformers_provider


SEMANTIC_RUNTIME_ENV = "COGNITIVEOS_SEMANTIC_RUNTIME"


@dataclass(frozen=True)
class SemanticRuntimeConfig:
    mode: str = "off"
    provider_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    device: str = "cpu"
    embedding_db_path: str | None = None

    @property
    def enabled(self) -> bool:
        return self.mode == "local"


def load_semantic_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> SemanticRuntimeConfig:
    values = os.environ if environ is None else environ
    mode = values.get(SEMANTIC_RUNTIME_ENV, "off").strip().lower()
    if mode not in {"off", "local"}:
        raise ValueError(f"{SEMANTIC_RUNTIME_ENV} must be off or local")
    if mode == "off":
        return SemanticRuntimeConfig()
    provider_id = _required_env(values, "COGNITIVEOS_EMBEDDING_PROVIDER")
    model_id = _required_env(values, "COGNITIVEOS_EMBEDDING_MODEL")
    model_revision = _required_env(values, "COGNITIVEOS_EMBEDDING_REVISION")
    device = values.get("COGNITIVEOS_EMBEDDING_DEVICE", "cpu").strip() or "cpu"
    embedding_db_path = values.get("COGNITIVEOS_EMBEDDING_DB_PATH")
    return SemanticRuntimeConfig(
        mode=mode,
        provider_id=provider_id,
        model_id=model_id,
        model_revision=model_revision,
        device=device,
        embedding_db_path=embedding_db_path.strip() if embedding_db_path else None,
    )


def create_runtime_provider(config: SemanticRuntimeConfig) -> EmbeddingProvider | None:
    if not config.enabled:
        return None
    if config.provider_id != "sentence-transformers":
        raise ValueError(f"embedding provider is not registered: {config.provider_id}")
    return create_sentence_transformers_provider(
        config.model_id or "",
        config.model_revision or "",
        False,
        config.device,
    )


def build_runtime_service(
    vault_root: str | Path,
    db_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RetrievalService:
    embedding_provider: EmbeddingProvider | None = None
    unavailable_reason: str | None = None
    try:
        config = load_semantic_runtime_config(environ)
        if config.enabled:
            embedding_provider = create_runtime_provider(config)
    except (ValueError, RuntimeError) as exc:
        config = SemanticRuntimeConfig(mode="local")
        unavailable_reason = "local semantic runtime configuration or model loading failed"
        print(f"CognitiveOS semantic runtime unavailable: {type(exc).__name__}", file=sys.stderr)
    return RetrievalService(
        vault_root,
        db_path,
        embedding_provider=embedding_provider,
        embedding_db_path=config.embedding_db_path,
        semantic_unavailable_reason=unavailable_reason,
    )


def _required_env(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required when semantic runtime is local")
    return value.strip()
