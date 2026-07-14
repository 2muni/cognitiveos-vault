from __future__ import annotations

import shlex
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .embedding_index import default_embedding_index_path, unpack_vector
from .indexer import default_index_path
from .manifest import (
    MANIFEST_VERSION,
    ManifestRecord,
    VaultManifest,
    build_vault_manifest,
    manifest_from_records,
)
from .safety import resolve_vault_root
from .validation import validate_vault


STATUS_VERSION = "vault-status-v0.1"


@dataclass(frozen=True)
class VaultStatus:
    overall_state: str
    vault: dict[str, Any]
    validation: dict[str, Any]
    lexical: dict[str, Any]
    embedding: dict[str, Any]
    status_version: str = STATUS_VERSION
    package_version: str = __version__

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_version": self.status_version,
            "package_version": self.package_version,
            "overall_state": self.overall_state,
            "vault": self.vault,
            "validation": self.validation,
            "lexical": self.lexical,
            "embedding": self.embedding,
            "safety": {
                "read_only": True,
                "index_created": False,
                "model_loaded": False,
                "network_used": False,
            },
        }


def inspect_vault_status(
    vault_root: str | Path,
    *,
    db_path: str | Path | None = None,
    embedding_db_path: str | Path | None = None,
    scope: str = "user",
) -> VaultStatus:
    root = resolve_vault_root(vault_root)
    manifest = build_vault_manifest(root)
    report = validate_vault(root, scope=scope)
    lexical = inspect_lexical_index(
        Path(db_path) if db_path is not None else default_index_path(root),
        manifest,
    )
    embedding = inspect_embedding_index(
        Path(embedding_db_path)
        if embedding_db_path is not None
        else default_embedding_index_path(root),
        manifest,
    )
    validation = {
        "validation_version": report.validation_version,
        "scope": report.scope,
        "state": "errors" if report.error_count else "valid",
        "files_scanned": report.files_scanned,
        "errors": report.error_count,
        "warnings": report.warning_count,
        "info": report.info_count,
    }
    return VaultStatus(
        overall_state=overall_state(validation, lexical, embedding),
        vault=manifest.public_dict(),
        validation=validation,
        lexical=lexical,
        embedding=embedding,
    )


def inspect_lexical_index(db_path: str | Path, manifest: VaultManifest) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return _lexical_empty_state("missing")
    if not path.is_file():
        return _lexical_empty_state("corrupt")
    try:
        with closing(_read_only_connection(path)) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                return _lexical_empty_state("corrupt")
            run_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(index_runs)").fetchall()
            }
            has_manifest_metadata = {
                "mode",
                "generation",
                "manifest_version",
                "manifest_digest",
                "scanned_count",
                "added_count",
                "updated_count",
                "removed_count",
                "reused_count",
                "fts_count",
            }.issubset(run_columns)
            extra_columns = (
                ", mode, generation, manifest_version, manifest_digest, "
                "scanned_count, added_count, updated_count, removed_count, "
                "reused_count, fts_count"
                if has_manifest_metadata
                else ""
            )
            run = conn.execute(
                "SELECT run_id, completed_at, note_count, status "
                f"{extra_columns} FROM index_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            note_rows = conn.execute("SELECT path, checksum FROM notes ORDER BY path").fetchall()
            fts_count = int(conn.execute("SELECT COUNT(*) FROM fts_notes").fetchone()[0])
            note_count = len(note_rows)
            result: dict[str, Any] = {
                "state": "healthy",
                "note_count": note_count,
                "fts_count": fts_count,
                "remediation": None,
            }
            if run is not None:
                result["last_run_id"] = int(run["run_id"])
                result["last_completed_at"] = run["completed_at"]
                if has_manifest_metadata:
                    result.update(
                        {
                            "mode": str(run["mode"]),
                            "generation": str(run["generation"]),
                            "scanned_count": int(run["scanned_count"]),
                            "added_count": int(run["added_count"]),
                            "updated_count": int(run["updated_count"]),
                            "removed_count": int(run["removed_count"]),
                            "reused_count": int(run["reused_count"]),
                        }
                    )
            if (
                run is None
                or run["status"] != "completed"
                or int(run["note_count"]) != note_count
                or fts_count != note_count
                or (has_manifest_metadata and int(run["fts_count"]) != fts_count)
            ):
                result["state"] = "incomplete"
                result["remediation"] = "cognitiveos-index . --format text"
                return result
            indexed_manifest = manifest_from_records(
                ManifestRecord(path=str(row["path"]), checksum=str(row["checksum"]))
                for row in note_rows
            )
            result["manifest_digest"] = indexed_manifest.digest
            if has_manifest_metadata and (
                run["manifest_version"] != MANIFEST_VERSION
                or run["manifest_digest"] != indexed_manifest.digest
                or int(run["scanned_count"]) != note_count
            ):
                result["state"] = "incomplete"
                result["remediation"] = "cognitiveos-index . --format text"
                return result
            if indexed_manifest.digest != manifest.digest:
                result["state"] = "stale"
                result["remediation"] = "cognitiveos-index . --format text"
            return result
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
        return _lexical_empty_state("corrupt")


def inspect_embedding_index(db_path: str | Path, manifest: VaultManifest) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return _embedding_empty_state("missing")
    if not path.is_file():
        return _embedding_empty_state("corrupt")
    try:
        with closing(_read_only_connection(path)) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                return _embedding_empty_state("corrupt")
            build = conn.execute(
                """
                SELECT provider_id, model_id, model_revision, dimension,
                       chunker_version, note_count, chunk_count, completed_at, status
                FROM embedding_builds ORDER BY build_id DESC LIMIT 1
                """
            ).fetchone()
            if build is None:
                return _embedding_empty_state("incomplete")
            rows = conn.execute(
                """
                SELECT path, note_checksum, provider_id, model_id, model_revision,
                       dimension, vector
                FROM embedding_chunks ORDER BY path, chunk_id
                """
            ).fetchall()
            note_checksums: dict[str, str] = {}
            for row in rows:
                identity = (
                    row["provider_id"],
                    row["model_id"],
                    row["model_revision"],
                    row["dimension"],
                )
                expected = (
                    build["provider_id"],
                    build["model_id"],
                    build["model_revision"],
                    build["dimension"],
                )
                if identity != expected:
                    return _embedding_result(build, rows, "incompatible")
                unpack_vector(row["vector"], int(row["dimension"]))
                row_path = str(row["path"])
                checksum = str(row["note_checksum"])
                previous = note_checksums.setdefault(row_path, checksum)
                if previous != checksum:
                    return _embedding_result(build, rows, "incomplete")
            result = _embedding_result(build, rows, "healthy")
            if (
                build["status"] != "completed"
                or int(build["chunk_count"]) != len(rows)
                or int(build["note_count"]) != len(note_checksums)
            ):
                result["state"] = "incomplete"
                result["remediation"] = _embedding_remediation(build)
                return result
            current = {record.path: record.checksum for record in manifest.records}
            stored_paths = set(note_checksums)
            current_paths = set(current)
            if current_paths - stored_paths:
                result["state"] = "incomplete"
            elif stored_paths - current_paths or any(
                current[path] != note_checksums[path] for path in current_paths
            ):
                result["state"] = "stale"
            if result["state"] != "healthy":
                result["remediation"] = _embedding_remediation(build)
            return result
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
        return _embedding_empty_state("corrupt")


def _embedding_result(
    build: sqlite3.Row,
    rows: list[sqlite3.Row],
    state: str,
) -> dict[str, Any]:
    return {
        "state": state,
        "provider_id": str(build["provider_id"]),
        "model_id": str(build["model_id"]),
        "model_revision": str(build["model_revision"]),
        "dimension": int(build["dimension"]),
        "chunker_version": str(build["chunker_version"]),
        "note_count": len({str(row["path"]) for row in rows}),
        "chunk_count": len(rows),
        "last_completed_at": build["completed_at"],
        "remediation": None if state == "healthy" else _embedding_remediation(build),
    }


def _lexical_empty_state(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "note_count": 0,
        "fts_count": 0,
        "remediation": "cognitiveos-index . --format text",
    }


def _embedding_empty_state(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "note_count": 0,
        "chunk_count": 0,
        "remediation": (
            None
            if state == "missing"
            else "cognitiveos-embed --vault-root . --provider PROVIDER --model MODEL "
            "--revision COMMIT_SHA"
        ),
    }


def _embedding_remediation(build: sqlite3.Row) -> str:
    return (
        "cognitiveos-embed --vault-root . "
        f"--provider {shlex.quote(str(build['provider_id']))} "
        f"--model {shlex.quote(str(build['model_id']))} "
        f"--revision {shlex.quote(str(build['model_revision']))}"
    )


def overall_state(
    validation: dict[str, Any],
    lexical: dict[str, Any],
    embedding: dict[str, Any],
) -> str:
    if lexical["state"] in {"missing", "corrupt"}:
        return "unavailable"
    if validation["state"] == "errors" or lexical["state"] != "healthy":
        return "degraded"
    if embedding["state"] not in {"healthy", "missing"}:
        return "degraded"
    return "healthy"


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
