from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .embeddings import EmbeddingConfigurationError


ModelLoader = Callable[..., Any]

APPROVED_MULTILINGUAL_MODEL_ID = "intfloat/multilingual-e5-small"
APPROVED_MULTILINGUAL_MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"


class SentenceTransformersProvider:
    """Local sentence-transformers adapter with cache-only loading by default."""

    provider_id = "sentence-transformers"

    def __init__(
        self,
        model_id: str,
        model_revision: str,
        *,
        allow_model_download: bool = False,
        device: str = "cpu",
        model_loader: ModelLoader | None = None,
    ) -> None:
        self.model_id = _required_string("model_id", model_id)
        self.model_revision = _required_string("model_revision", model_revision)
        self.device = _required_string("device", device)
        if not isinstance(allow_model_download, bool):
            raise EmbeddingConfigurationError("allow_model_download must be a boolean")

        loader = model_loader or _load_sentence_transformer
        try:
            self._model = loader(
                self.model_id,
                revision=self.model_revision,
                device=self.device,
                local_files_only=not allow_model_download,
                trust_remote_code=False,
            )
            dimension = _model_dimension(self._model)
        except EmbeddingConfigurationError:
            raise
        except Exception as exc:
            mode = "download-enabled" if allow_model_download else "local-cache-only"
            raise EmbeddingConfigurationError(
                f"could not load sentence-transformers model ({mode}): "
                f"{self.model_id}@{self.model_revision}"
            ) from exc
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
            raise EmbeddingConfigurationError("sentence-transformers model reported an invalid dimension")
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self._prefix("passage", text) for text in texts])

    def embed_query(self, query: str) -> list[float]:
        return self._encode([self._prefix("query", query)])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        output = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if not isinstance(output, Sequence) and not hasattr(output, "tolist"):
            raise RuntimeError("sentence-transformers returned an unsupported embedding output")
        raw_vectors = output.tolist() if hasattr(output, "tolist") else output
        return [[float(value) for value in vector] for vector in raw_vectors]

    def _prefix(self, role: str, text: str) -> str:
        if self.model_id == APPROVED_MULTILINGUAL_MODEL_ID:
            return f"{role}: {text}"
        return text


def create_sentence_transformers_provider(
    model_id: str,
    model_revision: str,
    allow_model_download: bool = False,
    device: str = "cpu",
) -> SentenceTransformersProvider:
    return SentenceTransformersProvider(
        model_id,
        model_revision,
        allow_model_download=allow_model_download,
        device=device,
    )


def _load_sentence_transformer(model_id: str, **kwargs: Any) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingConfigurationError(
            "sentence-transformers is not installed; install CognitiveOS with the local-embeddings extra"
        ) from exc
    return SentenceTransformer(model_id, **kwargs)


def _model_dimension(model: Any) -> Any:
    getter = getattr(model, "get_sentence_embedding_dimension", None)
    if getter is None:
        getter = getattr(model, "get_embedding_dimension", None)
    if getter is None or not callable(getter):
        raise EmbeddingConfigurationError("sentence-transformers model does not expose its dimension")
    return getter()


def _required_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingConfigurationError(f"{name} must be a non-empty string")
    return value.strip()
