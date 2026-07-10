from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_NOTE_TYPES = {
    "inbox",
    "concept",
    "source",
    "entity",
    "project",
    "map",
    "journal",
    "system",
    "output",
}


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int


@dataclass(frozen=True)
class Link:
    target: str
    link_type: str
    line: int | None = None


@dataclass
class NoteDocument:
    note_id: str
    path: str
    absolute_path: Path
    title: str
    note_type: str
    status: str
    frontmatter: dict[str, Any]
    body: str
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    checksum: str = ""
    mtime: float = 0.0
    body_preview: str = ""
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class SearchResult:
    note_id: str
    path: str
    title: str
    note_type: str
    score: float
    matched_excerpt: str


@dataclass(frozen=True)
class ContextPack:
    query: str
    results: list[SearchResult]
    context: str
    context_version: str = "context-pack-v0.1"
    sources: list[dict[str, Any]] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
