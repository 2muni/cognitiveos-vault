from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import NoteDocument
from .parser import frontmatter_json, parse_markdown_file
from .scanner import iter_markdown_files
from .safety import resolve_vault_root


def default_index_path(vault_root: str | Path) -> Path:
    return resolve_vault_root(vault_root) / ".pkm-index" / "cognitiveos.sqlite3"


class VaultIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "VaultIndex":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def create_schema(self) -> None:
        self.conn.executescript(
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
                status TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def upsert_note(self, note: NoteDocument) -> None:
        headings_text = "\n".join(heading.text for heading in note.headings)
        with self.conn:
            existing = self.conn.execute(
                "SELECT note_id FROM notes WHERE path = ? AND note_id != ?",
                (note.path, note.note_id),
            ).fetchone()
            if existing:
                self.delete_note(existing["note_id"])
            self.conn.execute(
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
            self.conn.execute("DELETE FROM note_frontmatter WHERE note_id = ?", (note.note_id,))
            self.conn.execute("DELETE FROM links WHERE source_note_id = ?", (note.note_id,))
            self.conn.execute("DELETE FROM headings WHERE note_id = ?", (note.note_id,))
            self.conn.execute("DELETE FROM fts_notes WHERE note_id = ?", (note.note_id,))
            self.conn.executemany(
                "INSERT OR IGNORE INTO note_frontmatter (note_id, key, value) VALUES (?, ?, ?)",
                frontmatter_rows(note),
            )
            self.conn.executemany(
                "INSERT INTO links (source_note_id, target, link_type, line) VALUES (?, ?, ?, ?)",
                [(note.note_id, link.target, link.link_type, link.line) for link in note.links],
            )
            self.conn.executemany(
                "INSERT INTO headings (note_id, level, text, line) VALUES (?, ?, ?, ?)",
                [(note.note_id, heading.level, heading.text, heading.line) for heading in note.headings],
            )
            self.conn.execute(
                "INSERT INTO fts_notes (note_id, title, body, headings, path) VALUES (?, ?, ?, ?, ?)",
                (note.note_id, note.title, note.body, headings_text, note.path),
            )

    def delete_note(self, note_id: str) -> None:
        self.conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
        self.conn.execute("DELETE FROM fts_notes WHERE note_id = ?", (note_id,))

    def index_vault(self, vault_root: str | Path) -> int:
        self.create_schema()
        started = now_iso()
        with self.conn:
            self.conn.execute("DELETE FROM notes")
            self.conn.execute("DELETE FROM fts_notes")
            cursor = self.conn.execute(
                "INSERT INTO index_runs (started_at, status) VALUES (?, ?)",
                (started, "running"),
            )
            run_id = int(cursor.lastrowid)
        count = 0
        try:
            for path in iter_markdown_files(vault_root):
                note = parse_markdown_file(path, vault_root)
                self.upsert_note(note)
                count += 1
            with self.conn:
                self.conn.execute(
                    "UPDATE index_runs SET completed_at = ?, note_count = ?, status = ? WHERE run_id = ?",
                    (now_iso(), count, "completed", run_id),
                )
        except Exception:
            with self.conn:
                self.conn.execute(
                    "UPDATE index_runs SET completed_at = ?, note_count = ?, status = ? WHERE run_id = ?",
                    (now_iso(), count, "failed", run_id),
                )
            raise
        return count


def frontmatter_rows(note: NoteDocument) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for key, value in note.frontmatter.items():
        for item in flatten_value(value):
            rows.append((note.note_id, str(key), item))
    return rows


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
