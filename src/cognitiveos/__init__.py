"""CognitiveOS read-only PKM index and retrieval core."""

from .embeddings import (
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingValidationError,
    embed_documents,
    embed_query,
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
    SemanticCandidate,
    SemanticUnavailableError,
    default_embedding_index_path,
    embedding_index_status,
    pack_vector,
    search_embedding_index,
    unpack_vector,
)
from .sentence_transformers_adapter import SentenceTransformersProvider

__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingChunk",
    "EmbeddingBuildResult",
    "EmbeddingIndex",
    "EmbeddingIndexBuilder",
    "SemanticCandidate",
    "SemanticUnavailableError",
    "SentenceTransformersProvider",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingValidationError",
    "CHUNKER_VERSION",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_OVERLAP_CHARS",
    "__version__",
    "embed_documents",
    "embed_query",
    "embed_texts",
    "chunk_note",
    "default_embedding_index_path",
    "provider_identity",
    "embedding_index_status",
    "pack_vector",
    "search_embedding_index",
    "stable_chunk_id",
    "unpack_vector",
]

__version__ = "0.3.0"
