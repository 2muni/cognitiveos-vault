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
from .embedding_chunks import (
    CHUNKER_VERSION,
    DEFAULT_MAX_CHARS,
    DEFAULT_OVERLAP_CHARS,
    EmbeddingChunk,
    chunk_note,
    stable_chunk_id,
)

__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingChunk",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingValidationError",
    "CHUNKER_VERSION",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_OVERLAP_CHARS",
    "__version__",
    "embed_texts",
    "chunk_note",
    "provider_identity",
    "stable_chunk_id",
]

__version__ = "0.2.0"
