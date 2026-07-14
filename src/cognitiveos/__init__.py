"""CognitiveOS read-only PKM index and retrieval core."""

__version__ = "0.5.0a1"

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
from .indexer import LexicalBuildResult, build_full_index, build_incremental_index
from .sentence_transformers_adapter import SentenceTransformersProvider
from .validation import (
    VALIDATION_VERSION,
    ValidationDiagnostic,
    ValidationReport,
    validate_note_file,
    validate_vault,
)
from .manifest import (
    MANIFEST_VERSION,
    ManifestRecord,
    VaultManifest,
    build_vault_manifest,
    manifest_from_records,
)
from .status import STATUS_VERSION, VaultStatus, inspect_vault_status

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
    "VALIDATION_VERSION",
    "MANIFEST_VERSION",
    "STATUS_VERSION",
    "ManifestRecord",
    "LexicalBuildResult",
    "VaultManifest",
    "VaultStatus",
    "ValidationDiagnostic",
    "ValidationReport",
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
    "validate_note_file",
    "validate_vault",
    "build_vault_manifest",
    "build_full_index",
    "build_incremental_index",
    "inspect_vault_status",
    "manifest_from_records",
]
