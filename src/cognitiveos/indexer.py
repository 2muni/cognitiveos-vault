from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import (
    MANIFEST_VERSION,
    ManifestRecord,
    VaultManifest,
    build_vault_manifest,
    manifest_from_records,
)
from .models import NoteDocument
from .parser import frontmatter_json, parse_markdown_file
from .safety import resolve_vault_root


def default_index_path(vault_root: str | Path) -> Path:
    return resolve_vault_root(vault_root) / ".pkm-index" / "cognitiveos.sqlite3"


@dataclass(frozen=True)
class LexicalBuildResult:
    index_path: str
    mode: str
    published: bool
    generation: str
    manifest_version: str
    manifest_digest: str
    scanned_count: int
    added_count: int
    updated_count: int
    removed_count: int
    reused_count: int
    note_count: int
    fts_count: int

    @property
    def indexed_notes(self) -> int:
        return self.note_count

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["indexed_notes"] = self.indexed_notes
        return payload


class VaultIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None
        self.last_build_result: LexicalBuildResult | None = None

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "VaultIndex":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _connection(self) -> sqlite3.Connection:
        if self.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    def create_schema(self) -> None:
        conn = self._connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                note_id TEXT PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                mtime REAL NOT NULL,
                checksum TEXT NOT NULL,
                body_preview TEXT,
                frontmatter_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS note_frontmatter (
                note_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (note_id, key, value),
                FOREIGN KEY (note_id) REFERENCES notes(note_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS links (
                source_note_id TEXT NOT NULL,
                target TEXT NOT NULL,
                link_type TEXT NOT NULL,
                line INTEGER,
                FOREIGN KEY (source_note_id) REFERENCES notes(note_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS headings (
                note_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                text TEXT NOT NULL,
                line INTEGER NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(note_id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS fts_notes USING fts5(
                note_id UNINDEXED,
                title,
                body,
                headings,
                path UNINDEXED
            );

            CREATE TABLE IF NOT EXISTS index_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                note_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'full',
                generation TEXT NOT NULL DEFAULT '',
                manifest_version TEXT NOT NULL DEFAULT '',
                manifest_digest TEXT NOT NULL DEFAULT '',
                scanned_count INTEGER NOT NULL DEFAULT 0,
                added_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                removed_count INTEGER NOT NULL DEFAULT 0,
                reused_count INTEGER NOT NULL DEFAULT 0,
                fts_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        ensure_index_run_columns(conn)
        conn.commit()

    def upsert_note(self, note: NoteDocument) -> None:
        conn = self._connection()
        headings_text = "\n".join(heading.text for heading in note.headings)
        aliases = frontmatter_string_values(note.frontmatter.get("aliases"))
        searchable_titles = [note.title]
        searchable_titles.extend(alias for alias in aliases if alias.casefold() != note.title.casefold())
        fts_title = "\n".join(dict.fromkeys(searchable_titles))
        with conn:
            existing = conn.execute(
                "SELECT note_id FROM notes WHERE path = ? AND note_id != ?",
                (note.path, note.note_id),
            ).fetchone()
            if existing:
                self.delete_note(existing["note_id"])
            conn.execute(
                """
                INSERT INTO notes (
                    note_id, path, title, type, status, created_at, updated_at,
                    mtime, checksum, body_preview, frontmatter_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    path = excluded.path,
                    title = excluded.title,
                    type = excluded.type,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    mtime = excluded.mtime,
                    checksum = excluded.checksum,
                    body_preview = excluded.body_preview,
                    frontmatter_json = excluded.frontmatter_json
                """,
                (
                    note.note_id,
                    note.path,
                    note.title,
                    note.note_type,
                    note.status,
                    note.created_at,
                    note.updated_at,
                    note.mtime,
                    note.checksum,
                    note.body_preview,
                    frontmatter_json(note.frontmatter),
                ),
            )
            conn.execute("DELETE FROM note_frontmatter WHERE note_id = ?", (note.note_id,))
            conn.execute("DELETE FROM links WHERE source_note_id = ?", (note.note_id,))
            conn.execute("DELETE FROM headings WHERE note_id = ?", (note.note_id,))
            conn.execute("DELETE FROM fts_notes WHERE note_id = ?", (note.note_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO note_frontmatter (note_id, key, value) VALUES (?, ?, ?)",
                frontmatter_rows(note),
            )
            conn.executemany(
                "INSERT INTO links (source_note_id, target, link_type, line) VALUES (?, ?, ?, ?)",
                [(note.note_id, link.target, link.link_type, link.line) for link in note.links],
            )
            conn.executemany(
                "INSERT INTO headings (note_id, level, text, line) VALUES (?, ?, ?, ?)",
                [(note.note_id, heading.level, heading.text, heading.line) for heading in note.headings],
            )
            conn.execute(
                "INSERT INTO fts_notes (note_id, title, body, headings, path) VALUES (?, ?, ?, ?, ?)",
                (note.note_id, fts_title, note.body, headings_text, note.path),
            )

    def delete_note(self, note_id: str) -> None:
        conn = self._connection()
        conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM fts_notes WHERE note_id = ?", (note_id,))

    def build_vault(self, vault_root: str | Path, *, mode: str = "full") -> LexicalBuildResult:
        if mode not in {"full", "incremental"}:
            raise ValueError("index mode must be full or incremental")
        self.close()
        result = (
            build_full_index(vault_root, self.db_path)
            if mode == "full"
            else build_incremental_index(vault_root, self.db_path)
        )
        self.last_build_result = result
        return result

    def index_vault(self, vault_root: str | Path) -> int:
        return self.build_vault(vault_root, mode="full").note_count


def build_full_index(vault_root: str | Path, db_path: str | Path) -> LexicalBuildResult:
    root = resolve_vault_root(vault_root)
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    temp_path = target.with_name(f".{target.name}.tmp")
    cleanup_sqlite_files(temp_path)
    source_manifest = build_vault_manifest(root)
    started_at = now_iso()
    notes: list[NoteDocument] = []
    try:
        with VaultIndex(temp_path) as index:
            index.create_schema()
            conn = index._connection()
            cursor = conn.execute(
                """
                INSERT INTO index_runs (
                    started_at, status, mode, generation, manifest_version,
                    manifest_digest, scanned_count, added_count
                ) VALUES (?, 'running', 'full', ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    generation,
                    source_manifest.manifest_version,
                    source_manifest.digest,
                    source_manifest.markdown_count,
                    source_manifest.markdown_count,
                ),
            )
            run_id = int(cursor.lastrowid)
            conn.commit()
            for record in source_manifest.records:
                note = parse_markdown_file(root / record.path, root)
                notes.append(note)
                index.upsert_note(note)
            indexed_manifest = manifest_from_records(
                ManifestRecord(path=note.path, checksum=note.checksum) for note in notes
            )
            final_source_manifest = build_vault_manifest(root)
            if indexed_manifest.digest != source_manifest.digest:
                raise RuntimeError("Markdown changed while the lexical index was being built")
            if final_source_manifest.digest != source_manifest.digest:
                raise RuntimeError("Markdown source set changed before lexical index publication")
            note_count = len(notes)
            fts_count = int(conn.execute("SELECT COUNT(*) FROM fts_notes").fetchone()[0])
            conn.execute(
                """
                UPDATE index_runs
                SET completed_at = ?, note_count = ?, fts_count = ?, status = 'completed'
                WHERE run_id = ?
                """,
                (now_iso(), note_count, fts_count, run_id),
            )
            conn.commit()
            validate_lexical_index(conn, final_source_manifest)
        publication_manifest = build_vault_manifest(root)
        if publication_manifest.digest != source_manifest.digest:
            raise RuntimeError("Markdown source set changed before lexical index publication")
        fsync_file(temp_path)
        reject_active_database_sidecars(target)
        os.replace(temp_path, target)
        return LexicalBuildResult(
            index_path=str(target),
            mode="full",
            published=True,
            generation=generation,
            manifest_version=source_manifest.manifest_version,
            manifest_digest=source_manifest.digest,
            scanned_count=source_manifest.markdown_count,
            added_count=source_manifest.markdown_count,
            updated_count=0,
            removed_count=0,
            reused_count=0,
            note_count=source_manifest.markdown_count,
            fts_count=source_manifest.markdown_count,
        )
    finally:
        cleanup_sqlite_files(temp_path)


def build_incremental_index(vault_root: str | Path, db_path: str | Path) -> LexicalBuildResult:
    root = resolve_vault_root(vault_root)
    target = Path(db_path)
    baseline = load_incremental_baseline(target)
    source_manifest = build_vault_manifest(root)
    previous = {record.path: record.checksum for record in baseline.manifest.records}
    current = {record.path: record.checksum for record in source_manifest.records}
    previous_paths = set(previous)
    current_paths = set(current)
    added_paths = sorted(current_paths - previous_paths)
    removed_paths = sorted(previous_paths - current_paths)
    updated_paths = sorted(
        path for path in current_paths & previous_paths if current[path] != previous[path]
    )
    reused_paths = sorted(
        path for path in current_paths & previous_paths if current[path] == previous[path]
    )
    if not added_paths and not removed_paths and not updated_paths:
        return LexicalBuildResult(
            index_path=str(target),
            mode="incremental",
            published=False,
            generation=baseline.generation,
            manifest_version=source_manifest.manifest_version,
            manifest_digest=source_manifest.digest,
            scanned_count=source_manifest.markdown_count,
            added_count=0,
            updated_count=0,
            removed_count=0,
            reused_count=len(reused_paths),
            note_count=source_manifest.markdown_count,
            fts_count=baseline.fts_count,
        )

    generation = uuid.uuid4().hex
    temp_path = target.with_name(f".{target.name}.tmp")
    cleanup_sqlite_files(temp_path)
    started_at = now_iso()
    changed_paths = sorted((*added_paths, *updated_paths))
    parsed_notes: list[NoteDocument] = []
    try:
        reject_active_database_sidecars(target)
        shutil.copy2(target, temp_path)
        with VaultIndex(temp_path) as index:
            index.create_schema()
            conn = index._connection()
            cursor = conn.execute(
                """
                INSERT INTO index_runs (
                    started_at, status, mode, generation, manifest_version,
                    manifest_digest, scanned_count, added_count, updated_count,
                    removed_count, reused_count
                ) VALUES (?, 'running', 'incremental', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    generation,
                    source_manifest.manifest_version,
                    source_manifest.digest,
                    source_manifest.markdown_count,
                    len(added_paths),
                    len(updated_paths),
                    len(removed_paths),
                    len(reused_paths),
                ),
            )
            run_id = int(cursor.lastrowid)
            conn.commit()
            with conn:
                for path in removed_paths:
                    row = conn.execute("SELECT note_id FROM notes WHERE path = ?", (path,)).fetchone()
                    if row is None:
                        raise ValueError("incremental baseline is missing an indexed note")
                    index.delete_note(str(row[0]))
            for path in changed_paths:
                note = parse_markdown_file(root / path, root)
                parsed_notes.append(note)
                index.upsert_note(note)
            parsed = {note.path: note.checksum for note in parsed_notes}
            if parsed != {path: current[path] for path in changed_paths}:
                raise RuntimeError("Markdown changed while the incremental index was being built")
            final_source_manifest = build_vault_manifest(root)
            if final_source_manifest.digest != source_manifest.digest:
                raise RuntimeError("Markdown source set changed before lexical index publication")
            note_count = int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
            fts_count = int(conn.execute("SELECT COUNT(*) FROM fts_notes").fetchone()[0])
            conn.execute(
                """
                UPDATE index_runs
                SET completed_at = ?, note_count = ?, fts_count = ?, status = 'completed'
                WHERE run_id = ?
                """,
                (now_iso(), note_count, fts_count, run_id),
            )
            conn.commit()
            validate_lexical_index(conn, final_source_manifest)
        publication_manifest = build_vault_manifest(root)
        if publication_manifest.digest != source_manifest.digest:
            raise RuntimeError("Markdown source set changed before lexical index publication")
        fsync_file(temp_path)
        reject_active_database_sidecars(target)
        os.replace(temp_path, target)
        return LexicalBuildResult(
            index_path=str(target),
            mode="incremental",
            published=True,
            generation=generation,
            manifest_version=source_manifest.manifest_version,
            manifest_digest=source_manifest.digest,
            scanned_count=source_manifest.markdown_count,
            added_count=len(added_paths),
            updated_count=len(updated_paths),
            removed_count=len(removed_paths),
            reused_count=len(reused_paths),
            note_count=source_manifest.markdown_count,
            fts_count=source_manifest.markdown_count,
        )
    finally:
        cleanup_sqlite_files(temp_path)


@dataclass(frozen=True)
class IncrementalBaseline:
    manifest: VaultManifest
    generation: str
    fts_count: int


def load_incremental_baseline(db_path: str | Path) -> IncrementalBaseline:
    path = Path(db_path)
    if not path.is_file():
        raise ValueError(
            "incremental mode requires a compatible completed lexical index; run --mode full"
        )
    try:
        reject_active_database_sidecars(path)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT path, checksum FROM notes ORDER BY path").fetchall()
            manifest = manifest_from_records(
                ManifestRecord(path=str(row["path"]), checksum=str(row["checksum"]))
                for row in rows
            )
            validate_lexical_index(conn, manifest)
            run = conn.execute(
                "SELECT generation, fts_count FROM index_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            if run is None or not str(run["generation"]):
                raise ValueError("lexical index generation is missing")
            return IncrementalBaseline(
                manifest=manifest,
                generation=str(run["generation"]),
                fts_count=int(run["fts_count"]),
            )
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError) as exc:
        raise ValueError(
            "incremental mode requires a compatible completed lexical index; run --mode full"
        ) from exc


def validate_lexical_index(conn: sqlite3.Connection, expected_manifest: VaultManifest) -> None:
    conn.row_factory = sqlite3.Row
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        raise ValueError(f"lexical index integrity check failed: {integrity}")
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise ValueError("lexical index foreign key check failed")
    run = conn.execute(
        """
        SELECT status, mode, manifest_version, manifest_digest, scanned_count,
               added_count, updated_count, removed_count, reused_count,
               note_count, fts_count
        FROM index_runs ORDER BY run_id DESC LIMIT 1
        """
    ).fetchone()
    if run is None or run["status"] != "completed" or run["mode"] not in {"full", "incremental"}:
        raise ValueError("lexical index has no compatible completed build")
    note_rows = conn.execute("SELECT path, checksum FROM notes ORDER BY path").fetchall()
    note_count = len(note_rows)
    fts_count = int(conn.execute("SELECT COUNT(*) FROM fts_notes").fetchone()[0])
    common_counts_invalid = (
        note_count != expected_manifest.markdown_count
        or fts_count != note_count
        or int(run["scanned_count"]) != note_count
        or int(run["note_count"]) != note_count
        or int(run["fts_count"]) != fts_count
    )
    full_counts_invalid = run["mode"] == "full" and (
        int(run["added_count"]) != note_count
        or int(run["updated_count"]) != 0
        or int(run["removed_count"]) != 0
        or int(run["reused_count"]) != 0
    )
    incremental_counts_invalid = run["mode"] == "incremental" and (
        int(run["added_count"])
        + int(run["updated_count"])
        + int(run["reused_count"])
        != note_count
        or min(
            int(run["added_count"]),
            int(run["updated_count"]),
            int(run["removed_count"]),
            int(run["reused_count"]),
        )
        < 0
    )
    if common_counts_invalid or full_counts_invalid or incremental_counts_invalid:
        raise ValueError("lexical index count validation failed")
    missing_fts = conn.execute(
        "SELECT note_id, path FROM notes EXCEPT SELECT note_id, path FROM fts_notes"
    ).fetchall()
    orphaned_fts = conn.execute(
        "SELECT note_id, path FROM fts_notes EXCEPT SELECT note_id, path FROM notes"
    ).fetchall()
    if missing_fts or orphaned_fts:
        raise ValueError("lexical index FTS coverage validation failed")
    indexed_manifest = manifest_from_records(
        ManifestRecord(path=str(row["path"]), checksum=str(row["checksum"]))
        for row in note_rows
    )
    if (
        run["manifest_version"] != MANIFEST_VERSION
        or run["manifest_digest"] != expected_manifest.digest
        or indexed_manifest.digest != expected_manifest.digest
    ):
        raise ValueError("lexical index source manifest validation failed")


def ensure_index_run_columns(conn: sqlite3.Connection) -> None:
    existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(index_runs)")}
    definitions = {
        "mode": "TEXT NOT NULL DEFAULT 'full'",
        "generation": "TEXT NOT NULL DEFAULT ''",
        "manifest_version": "TEXT NOT NULL DEFAULT ''",
        "manifest_digest": "TEXT NOT NULL DEFAULT ''",
        "scanned_count": "INTEGER NOT NULL DEFAULT 0",
        "added_count": "INTEGER NOT NULL DEFAULT 0",
        "updated_count": "INTEGER NOT NULL DEFAULT 0",
        "removed_count": "INTEGER NOT NULL DEFAULT 0",
        "reused_count": "INTEGER NOT NULL DEFAULT 0",
        "fts_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in definitions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE index_runs ADD COLUMN {name} {definition}")


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def reject_active_wal(path: Path) -> None:
    wal_path = Path(f"{path}-wal")
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise RuntimeError("cannot publish lexical index while an active WAL file exists")


def reject_active_database_sidecars(path: Path) -> None:
    reject_active_wal(path)
    journal_path = Path(f"{path}-journal")
    if journal_path.exists() and journal_path.stat().st_size > 0:
        raise RuntimeError("cannot publish lexical index while an active rollback journal exists")


def cleanup_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def frontmatter_rows(note: NoteDocument) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for key, value in note.frontmatter.items():
        for item in flatten_value(value):
            rows.append((note.note_id, str(key), item))
    return rows


def frontmatter_string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        values.append(normalized)
    return values


def flatten_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(flatten_value(item))
        return values
    return [json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
