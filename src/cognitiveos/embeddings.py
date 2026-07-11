from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Protocol, Sequence, runtime_checkable


class EmbeddingError(Exception):
    """Base error for the optional embedding boundary."""


class EmbeddingConfigurationError(EmbeddingError, ValueError):
    """Raised when provider identity or embedding input is invalid."""


class EmbeddingProviderError(EmbeddingError, RuntimeError):
    """Raised when an embedding provider fails while processing a batch."""


class EmbeddingValidationError(EmbeddingError, ValueError):
    """Raised when provider output violates the embedding contract."""


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider_id: str
    model_id: str
    model_revision: str
    dimension: int

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_id", "model_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EmbeddingConfigurationError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension < 1:
            raise EmbeddingConfigurationError("dimension must be a positive integer")


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    model_revision: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text in input order."""

        ...


def provider_identity(provider: Any) -> EmbeddingIdentity:
    try:
        return EmbeddingIdentity(
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            model_revision=provider.model_revision,
            dimension=provider.dimension,
        )
    except AttributeError as exc:
        raise EmbeddingConfigurationError("provider identity is incomplete") from exc


def embed_texts(provider: EmbeddingProvider, texts: Sequence[str]) -> list[list[float]]:
    if not isinstance(provider, EmbeddingProvider):
        raise EmbeddingConfigurationError("provider does not implement the embedding protocol")
    identity = provider_identity(provider)
    normalized_texts = validate_embedding_inputs(texts)
    if not normalized_texts:
        return []
    try:
        vectors = provider.embed(normalized_texts)
    except Exception as exc:
        raise EmbeddingProviderError(
            f"embedding provider failed: {identity.provider_id}/{identity.model_id}@{identity.model_revision}"
        ) from exc
    return validate_embedding_vectors(vectors, expected_count=len(normalized_texts), dimension=identity.dimension)


def validate_embedding_inputs(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise EmbeddingConfigurationError("texts must be a sequence of non-empty strings")
    normalized: list[str] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingConfigurationError(f"texts[{index}] must be a non-empty string")
        normalized.append(text)
    return normalized


def validate_embedding_vectors(
    vectors: Any,
    *,
    expected_count: int,
    dimension: int,
) -> list[list[float]]:
    if isinstance(vectors, (str, bytes)) or not isinstance(vectors, Sequence):
        raise EmbeddingValidationError("provider output must be a sequence of vectors")
    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            f"provider returned {len(vectors)} vectors for {expected_count} texts"
        )
    validated: list[list[float]] = []
    for vector_index, vector in enumerate(vectors):
        if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
            raise EmbeddingValidationError(f"vector {vector_index} must be a numeric sequence")
        if len(vector) != dimension:
            raise EmbeddingValidationError(
                f"vector {vector_index} has dimension {len(vector)}; expected {dimension}"
            )
        normalized_vector: list[float] = []
        for value_index, value in enumerate(vector):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise EmbeddingValidationError(
                    f"vector {vector_index} value {value_index} must be numeric"
                )
            normalized_value = float(value)
            if not math.isfinite(normalized_value):
                raise EmbeddingValidationError(
                    f"vector {vector_index} value {value_index} must be finite"
                )
            normalized_vector.append(normalized_value)
        if not any(value != 0.0 for value in normalized_vector):
            raise EmbeddingValidationError(f"vector {vector_index} must not be a zero vector")
        validated.append(normalized_vector)
    return validated
