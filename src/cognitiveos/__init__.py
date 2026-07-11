"""CognitiveOS read-only PKM index and retrieval core."""

from .embeddings import (
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingValidationError,
    embed_texts,
    provider_identity,
)

__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingValidationError",
    "__version__",
    "embed_texts",
    "provider_identity",
]

__version__ = "0.2.0"
