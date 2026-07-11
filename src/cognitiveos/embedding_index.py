from __future__ import annotations

import math
import os
import sqlite3
import struct
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .embedding_chunks import CHUNKER_VERSION, EmbeddingChunk, chunk_note
from .embeddings import EmbeddingIdentity, EmbeddingProvider, embed_texts, provider_identity
from .parser import parse_markdown_file
from .safety import resolve_vault_root
from .scanner import iter_markdown_files


def default_embedding_index_path(vault_root: str | Path) -> Path:
    return resolve_vault_root(vault_root) / ".pkm-index" / "cognitiveos-embeddings.sqlite3"


@dataclass(frozen=True)
class EmbeddingBuildResult:
    index_path: str
    provider_id: str
    model_id: str
    model_revision: str
    dimension: int
    chunker_version: str
    note_count: int
    chunk_count: int
    reused_chunk_count: int
    embedded_chunk_count: int
    rebuild: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmbeddingIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def __enter__(self) -> "EmbeddingIndex":
        return self

    def __exit__(self, *_args: object) -> None:
        self.conn.close()

    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS embedding_builds (
                build_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_revision TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                chunker_version TEXT NOT NULL,
                note_count INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS embedding_chunks (
                chunk_id TEXT PRIMARY KEY,
                note_id TEXT NOT NULL,
                path TEXT NOT NULL,
                note_checksum TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                heading TEXT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_revision TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_embedding_chunks_note_id
                ON embedding_chunks(note_id);
            CREATE INDEX IF NOT EXISTS idx_embedding_chunks_path
                ON embedding_chunks(path);
            CREATE INDEX IF NOT EXISTS idx_embedding_chunks_note_checksum
                ON embedding_chunks(note_checksum);
            CREATE INDEX IF NOT EXISTS idx_embedding_chunks_content_hash
                ON embedding_chunks(content_hash);
            """
        )
        self.conn.commit()

    def start_build(self, identity: EmbeddingIdentity) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO embedding_builds (
                started_at, status, provider_id, model_id, model_revision,
                dimension, chunker_version
            ) VALUES (?, 'running', ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                identity.provider_id,
                identity.model_id,
                identity.model_revision,
                identity.dimension,
                CHUNKER_VERSION,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def insert_chunk(self, chunk: EmbeddingChunk, identity: EmbeddingIdentity, vector: list[float]) -> None:
        self.conn.execute(
            """
            INSERT INTO embedding_chunks (
                chunk_id, note_id, path, note_checksum, chunk_index,
                start_line, end_line, heading, content, content_hash,
                provider_id, model_id, model_revision, dimension, vector
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.note_id,
                chunk.path,
                chunk.note_checksum,
                chunk.chunk_index,
                chunk.start_line,
                chunk.end_line,
                chunk.heading,
                chunk.content,
                chunk.content_hash,
                identity.provider_id,
                identity.model_id,
                identity.model_revision,
                identity.dimension,
                pack_vector(vector),
            ),
        )

    def complete_build(self, build_id: int, note_count: int, chunk_count: int) -> None:
        self.conn.execute(
            """
            UPDATE embedding_builds
            SET completed_at = ?, status = 'completed', note_count = ?, chunk_count = ?
            WHERE build_id = ?
            """,
            (now_iso(), note_count, chunk_count, build_id),
        )
        self.conn.commit()

    def validate(self, identity: EmbeddingIdentity, expected_chunks: int) -> None:
        integrity = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"embedding index integrity check failed: {integrity}")
        row = self.conn.execute(
            """
            SELECT provider_id, model_id, model_revision, dimension, chunker_version,
                   note_count, chunk_count, status
            FROM embedding_builds ORDER BY build_id DESC LIMIT 1
            """
        ).fetchone()
        if row is None or row["status"] != "completed":
            raise ValueError("embedding index has no completed build")
        expected_identity = (
            identity.provider_id,
            identity.model_id,
            identity.model_revision,
            identity.dimension,
            CHUNKER_VERSION,
        )
        actual_identity = (
            row["provider_id"],
            row["model_id"],
            row["model_revision"],
            row["dimension"],
            row["chunker_version"],
        )
        if actual_identity != expected_identity:
            raise ValueError("embedding index identity mismatch")
        count = self.conn.execute("SELECT COUNT(*) FROM embedding_chunks").fetchone()[0]
        if count != expected_chunks or row["chunk_count"] != expected_chunks:
            raise ValueError("embedding index chunk count mismatch")
        note_count = self.conn.execute("SELECT COUNT(DISTINCT note_id) FROM embedding_chunks").fetchone()[0]
        if note_count != row["note_count"]:
            raise ValueError("embedding index note count mismatch")
        identity_mismatches = self.conn.execute(
            """
            SELECT COUNT(*) FROM embedding_chunks
            WHERE provider_id != ? OR model_id != ? OR model_revision != ? OR dimension != ?
            """,
            (
                identity.provider_id,
                identity.model_id,
                identity.model_revision,
                identity.dimension,
            ),
        ).fetchone()[0]
        if identity_mismatches:
            raise ValueError("embedding chunk identity mismatch")
        for vector_row in self.conn.execute("SELECT dimension, vector FROM embedding_chunks"):
            unpack_vector(vector_row["vector"], vector_row["dimension"])


class EmbeddingIndexBuilder:
    def __init__(
        self,
        vault_root: str | Path,
        provider: EmbeddingProvider,
        db_path: str | Path | None = None,
        *,
        batch_size: int = 32,
    ):
        self.vault_root = resolve_vault_root(vault_root)
        self.provider = provider
        self.identity = provider_identity(provider)
        self.db_path = Path(db_path) if db_path else default_embedding_index_path(self.vault_root)
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.batch_size = batch_size

    def build(self, *, rebuild: bool = False) -> EmbeddingBuildResult:
        reusable = {} if rebuild else load_reusable_vectors(self.db_path, self.identity)
        notes = [parse_markdown_file(path, self.vault_root) for path in iter_markdown_files(self.vault_root)]
        chunks = [chunk for note in notes for chunk in chunk_note(note)]
        vectors: dict[str, list[float]] = {}
        reused_count = 0
        pending: list[EmbeddingChunk] = []
        for chunk in chunks:
            reusable_entry = reusable.get(chunk.chunk_id)
            if reusable_entry is None or reusable_entry[0] != chunk.content_hash:
                pending.append(chunk)
            else:
                vectors[chunk.chunk_id] = reusable_entry[1]
                reused_count += 1
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            embedded = embed_texts(self.provider, [chunk.content for chunk in batch])
            vectors.update((chunk.chunk_id, vector) for chunk, vector in zip(batch, embedded, strict=True))

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.db_path.with_name(f".{self.db_path.name}.tmp")
        if temp_path.exists():
            temp_path.unlink()
        try:
            with EmbeddingIndex(temp_path) as index:
                index.create_schema()
                build_id = index.start_build(self.identity)
                for chunk in chunks:
                    index.insert_chunk(chunk, self.identity, vectors[chunk.chunk_id])
                index.complete_build(build_id, len(notes), len(chunks))
                index.validate(self.identity, len(chunks))
            os.replace(temp_path, self.db_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

        return EmbeddingBuildResult(
            index_path=str(self.db_path),
            provider_id=self.identity.provider_id,
            model_id=self.identity.model_id,
            model_revision=self.identity.model_revision,
            dimension=self.identity.dimension,
            chunker_version=CHUNKER_VERSION,
            note_count=len(notes),
            chunk_count=len(chunks),
            reused_chunk_count=reused_count,
            embedded_chunk_count=len(pending),
            rebuild=rebuild,
        )


def embedding_index_status(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {"status": "missing", "index_path": str(path)}
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(str(integrity))
            row = conn.execute(
                """
                SELECT provider_id, model_id, model_revision, dimension,
                       chunker_version, note_count, chunk_count, completed_at, status
                FROM embedding_builds ORDER BY build_id DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                raise ValueError("missing build metadata")
            chunk_count = conn.execute("SELECT COUNT(*) FROM embedding_chunks").fetchone()[0]
            note_count = conn.execute("SELECT COUNT(DISTINCT note_id) FROM embedding_chunks").fetchone()[0]
            if chunk_count != row["chunk_count"] or note_count != row["note_count"]:
                raise ValueError("embedding index count mismatch")
            mismatches = conn.execute(
                """
                SELECT COUNT(*) FROM embedding_chunks
                WHERE provider_id != ? OR model_id != ? OR model_revision != ? OR dimension != ?
                """,
                (row["provider_id"], row["model_id"], row["model_revision"], row["dimension"]),
            ).fetchone()[0]
            if mismatches:
                raise ValueError("embedding index identity mismatch")
            for vector_row in conn.execute("SELECT dimension, vector FROM embedding_chunks"):
                unpack_vector(vector_row["vector"], vector_row["dimension"])
            result = dict(row)
            result["index_path"] = str(path)
            return result
    except Exception as exc:
        return {"status": "invalid", "index_path": str(path), "error": type(exc).__name__}


def load_reusable_vectors(
    db_path: Path,
    identity: EmbeddingIdentity,
) -> dict[str, tuple[str, list[float]]]:
    if not db_path.exists():
        return {}
    try:
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            build = conn.execute(
                """
                SELECT provider_id, model_id, model_revision, dimension, chunker_version, status
                FROM embedding_builds ORDER BY build_id DESC LIMIT 1
                """
            ).fetchone()
            if build is None or build["status"] != "completed":
                return {}
            if (
                build["provider_id"],
                build["model_id"],
                build["model_revision"],
                build["dimension"],
                build["chunker_version"],
            ) != (
                identity.provider_id,
                identity.model_id,
                identity.model_revision,
                identity.dimension,
                CHUNKER_VERSION,
            ):
                return {}
            return {
                row["chunk_id"]: (
                    row["content_hash"],
                    unpack_vector(row["vector"], row["dimension"]),
                )
                for row in conn.execute(
                    "SELECT chunk_id, content_hash, dimension, vector FROM embedding_chunks"
                )
            }
    except Exception:
        return {}


def pack_vector(vector: list[float]) -> bytes:
    if not vector or any(isinstance(value, bool) or not math.isfinite(float(value)) for value in vector):
        raise ValueError("vector must contain finite values")
    if not any(float(value) != 0.0 for value in vector):
        raise ValueError("vector must not be a zero vector")
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes, dimension: int) -> list[float]:
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
        raise ValueError("dimension must be a positive integer")
    expected_size = dimension * 4
    if not isinstance(blob, bytes) or len(blob) != expected_size:
        raise ValueError("vector byte length does not match dimension")
    vector = list(struct.unpack(f"<{dimension}f", blob))
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("vector contains non-finite values")
    if not any(value != 0.0 for value in vector):
        raise ValueError("vector must not be a zero vector")
    return vector


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
