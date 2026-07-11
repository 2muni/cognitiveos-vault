from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .embeddings import EmbeddingConfigurationError
from .models import NoteDocument


CHUNKER_VERSION = "markdown-blocks-v1"
DEFAULT_MAX_CHARS = 1600
DEFAULT_OVERLAP_CHARS = 300

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass(frozen=True)
class EmbeddingChunk:
    chunk_id: str
    note_id: str
    path: str
    note_checksum: str
    chunker_version: str
    chunk_index: int
    start_line: int
    end_line: int
    heading: str | None
    content: str
    content_hash: str


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    text: str
    start_line: int
    end_line: int
    heading: str | None


def chunk_note(
    note: NoteDocument,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[EmbeddingChunk]:
    validate_chunk_limits(max_chars, overlap_chars)
    blocks = markdown_blocks(note.body)
    if not blocks:
        heading = note.headings[0].text if note.headings else None
        line = note.headings[0].line if note.headings else 1
        content = render_chunk_content(note.title, heading, [], max_chars)
        return [make_chunk(note, 0, line, line, heading, content)]

    chunks: list[EmbeddingChunk] = []
    current: list[MarkdownBlock] = []
    current_heading: str | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        content = render_chunk_content(note.title, current_heading, current, max_chars)
        chunks.append(
            make_chunk(
                note,
                len(chunks),
                min(block.start_line for block in current),
                max(block.end_line for block in current),
                current_heading,
                content,
            )
        )
        current = []

    for source_block in blocks:
        prefix = render_prefix(note.title, source_block.heading, max_chars)
        available = max(1, max_chars - len(prefix) - 2)
        pieces = split_block(source_block, available)
        for piece in pieces:
            if current and piece.heading != current_heading:
                flush()
            if not current:
                current_heading = piece.heading
            proposed = [*current, piece]
            if len(render_chunk_content(note.title, current_heading, proposed, max_chars)) <= max_chars:
                current = proposed
                continue

            previous_tail = overlap_block(current[-1], overlap_chars) if current and overlap_chars else None
            flush()
            current_heading = piece.heading
            current = [piece]
            if previous_tail is not None and previous_tail.heading == current_heading:
                with_overlap = [previous_tail, piece]
                if len(render_chunk_content(note.title, current_heading, with_overlap, max_chars)) <= max_chars:
                    current = with_overlap
    flush()
    return chunks


def markdown_blocks(body: str) -> list[MarkdownBlock]:
    lines = body.splitlines()
    blocks: list[MarkdownBlock] = []
    heading: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            heading = heading_match.group(2).strip()
            index += 1
            continue

        start = index
        kind = "list" if LIST_ITEM_RE.match(line) else "paragraph"
        collected = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if not candidate.strip() or HEADING_RE.match(candidate):
                break
            candidate_kind = "list" if LIST_ITEM_RE.match(candidate) else "paragraph"
            if candidate_kind != kind:
                break
            collected.append(candidate)
            index += 1
        blocks.append(
            MarkdownBlock(
                kind=kind,
                text="\n".join(collected).strip(),
                start_line=start + 1,
                end_line=start + len(collected),
                heading=heading,
            )
        )
    return blocks


def split_block(block: MarkdownBlock, max_chars: int) -> list[MarkdownBlock]:
    if len(block.text) <= max_chars:
        return [block]
    pieces: list[MarkdownBlock] = []
    remaining = block.text
    while len(remaining) > max_chars:
        split_at = find_split_boundary(remaining, max_chars)
        piece = remaining[:split_at].rstrip()
        if not piece:
            piece = remaining[:max_chars]
            split_at = len(piece)
        pieces.append(
            MarkdownBlock(block.kind, piece, block.start_line, block.end_line, block.heading)
        )
        remaining = remaining[split_at:].lstrip()
    if remaining:
        pieces.append(
            MarkdownBlock(block.kind, remaining, block.start_line, block.end_line, block.heading)
        )
    return pieces


def find_split_boundary(text: str, max_chars: int) -> int:
    window = text[:max_chars]
    sentence_boundaries = [match.end() for match in SENTENCE_BOUNDARY_RE.finditer(window)]
    if sentence_boundaries:
        return sentence_boundaries[-1]
    whitespace = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
    return whitespace + 1 if whitespace > 0 else max_chars


def overlap_block(block: MarkdownBlock, overlap_chars: int) -> MarkdownBlock | None:
    text = block.text[-overlap_chars:].lstrip()
    if not text:
        return None
    return MarkdownBlock("overlap", text, block.start_line, block.end_line, block.heading)


def render_prefix(title: str, heading: str | None, max_chars: int) -> str:
    normalized_title = " ".join(title.split())
    lines = [f"title: {normalized_title}"]
    if heading and heading != normalized_title:
        lines.append(f"heading: {' '.join(heading.split())}")
    prefix = "\n".join(lines)
    prefix_limit = max(1, max_chars - 32)
    if len(prefix) > prefix_limit:
        prefix = prefix[: max(1, prefix_limit - 3)].rstrip() + "..."
    return prefix


def render_chunk_content(
    title: str,
    heading: str | None,
    blocks: list[MarkdownBlock],
    max_chars: int,
) -> str:
    prefix = render_prefix(title, heading, max_chars)
    if not blocks:
        return prefix
    return f"{prefix}\n\n" + "\n\n".join(block.text for block in blocks)


def make_chunk(
    note: NoteDocument,
    chunk_index: int,
    start_line: int,
    end_line: int,
    heading: str | None,
    content: str,
) -> EmbeddingChunk:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return EmbeddingChunk(
        chunk_id=stable_chunk_id(note.note_id, note.checksum, chunk_index),
        note_id=note.note_id,
        path=note.path,
        note_checksum=note.checksum,
        chunker_version=CHUNKER_VERSION,
        chunk_index=chunk_index,
        start_line=start_line,
        end_line=end_line,
        heading=heading,
        content=content,
        content_hash=content_hash,
    )


def stable_chunk_id(note_id: str, note_checksum: str, chunk_index: int) -> str:
    if not isinstance(note_id, str) or not note_id:
        raise EmbeddingConfigurationError("note_id must be a non-empty string")
    if not isinstance(note_checksum, str) or not note_checksum:
        raise EmbeddingConfigurationError("note_checksum must be a non-empty string")
    if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 0:
        raise EmbeddingConfigurationError("chunk_index must be a non-negative integer")
    identity = f"{note_id}\0{note_checksum}\0{CHUNKER_VERSION}\0{chunk_index}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def validate_chunk_limits(max_chars: int, overlap_chars: int) -> None:
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 64:
        raise EmbeddingConfigurationError("max_chars must be an integer of at least 64")
    if isinstance(overlap_chars, bool) or not isinstance(overlap_chars, int) or overlap_chars < 0:
        raise EmbeddingConfigurationError("overlap_chars must be a non-negative integer")
    if overlap_chars >= max_chars:
        raise EmbeddingConfigurationError("overlap_chars must be smaller than max_chars")
