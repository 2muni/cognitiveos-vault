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
from .embedding_index import (
    EmbeddingBuildResult,
    EmbeddingIndex,
    EmbeddingIndexBuilder,
    default_embedding_index_path,
    embedding_index_status,
    pack_vector,
    unpack_vector,
)

__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingChunk",
    "EmbeddingBuildResult",
    "EmbeddingIndex",
    "EmbeddingIndexBuilder",
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
    "default_embedding_index_path",
    "provider_identity",
    "embedding_index_status",
    "pack_vector",
    "stable_chunk_id",
    "unpack_vector",
]

__version__ = "0.2.0"
