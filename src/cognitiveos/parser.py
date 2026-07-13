from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import Heading, Link, NoteDocument, VALID_NOTE_TYPES
from .safety import resolve_vault_root, safe_resolve_inside

FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WIKILINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")
MDLINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_markdown_file(path: str | Path, vault_root: str | Path) -> NoteDocument:
    root = resolve_vault_root(vault_root)
    absolute = safe_resolve_inside(root, path)
    text = read_text(absolute)
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    frontmatter, body = split_frontmatter(text)
    rel_path = absolute.relative_to(root).as_posix()
    headings = extract_headings(body)
    links = [*extract_links(body), *extract_frontmatter_links(frontmatter)]
    title = derive_title(frontmatter, headings, absolute)
    note_id = (
        stable_note_id(rel_path)
        if is_template_path(rel_path)
        else str(frontmatter.get("id") or stable_note_id(rel_path))
    )
    note_type = str(frontmatter.get("type") or infer_note_type(rel_path))
    if note_type not in VALID_NOTE_TYPES:
        note_type = "inbox"
    status = str(frontmatter.get("status") or "seed")
    stat = absolute.stat()
    return NoteDocument(
        note_id=note_id,
        path=rel_path,
        absolute_path=absolute,
        title=title,
        note_type=note_type,
        status=status,
        frontmatter=frontmatter,
        body=body,
        headings=headings,
        links=links,
        checksum=checksum,
        mtime=stat.st_mtime,
        body_preview=preview(body),
        created_at=string_or_none(frontmatter.get("created_at") or frontmatter.get("created")),
        updated_at=string_or_none(frontmatter.get("updated_at") or frontmatter.get("updated")),
    )


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    return parse_frontmatter(raw), body


def parse_frontmatter(raw: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            return parse_simple_yaml(raw)
        except ValueError:
            return {}
    try:
        parsed = yaml.safe_load(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def parse_simple_yaml(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_key and stripped.startswith("- "):
            data.setdefault(current_key, []).append(parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in line:
            current_key = None
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if value == "":
            data[current_key] = []
        else:
            data[current_key] = parse_scalar(value)
    return data


def parse_scalar(value: str) -> Any:
    if (value.startswith("[") and not value.endswith("]")) or (
        value.startswith("{") and not value.endswith("}")
    ):
        raise ValueError("invalid inline YAML collection")
    if value in {"[]", "{}"}:
        return [] if value == "[]" else {}
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "none"}:
        return None
    if (value.startswith("[") and value.endswith("]")) or (
        value.startswith("{") and value.endswith("}")
    ):
        try:
            return ast.literal_eval(value)
        except Exception:
            pass
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip("\"'")


def extract_headings(body: str) -> list[Heading]:
    headings: list[Heading] = []
    for index, line in enumerate(body.splitlines(), start=1):
        match = HEADING_RE.match(line)
        if match:
            headings.append(Heading(level=len(match.group(1)), text=match.group(2).strip(), line=index))
    return headings


def extract_links(body: str) -> list[Link]:
    links: list[Link] = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        for match in WIKILINK_RE.finditer(line):
            target = match.group(1).split("|", 1)[0].strip()
            links.append(Link(target=target, link_type="wikilink", line=line_number))
        for match in MDLINK_RE.finditer(line):
            target = match.group(2).strip()
            links.append(Link(target=target, link_type="markdown", line=line_number))
    return links


def extract_frontmatter_links(frontmatter: dict[str, Any]) -> list[Link]:
    links: list[Link] = []
    seen: set[tuple[str, str]] = set()
    for field_name, link_type in (
        ("links", "frontmatter_link"),
        ("sources", "frontmatter_source"),
    ):
        values = frontmatter.get(field_name)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            target = normalize_frontmatter_link_target(value)
            key = (link_type, target.casefold())
            if not target or key in seen:
                continue
            seen.add(key)
            links.append(Link(target=target, link_type=link_type, line=None))
    return links


def normalize_frontmatter_link_target(value: str) -> str:
    normalized = value.strip()
    wiki_match = WIKILINK_RE.fullmatch(normalized)
    if wiki_match:
        return wiki_match.group(1).split("|", 1)[0].strip()
    markdown_match = MDLINK_RE.fullmatch(normalized)
    if markdown_match:
        return markdown_match.group(2).strip()
    return normalized


def derive_title(frontmatter: dict[str, Any], headings: list[Heading], path: Path) -> str:
    if frontmatter.get("title"):
        return str(frontmatter["title"])
    if headings:
        return headings[0].text
    return path.stem


def infer_note_type(rel_path: str) -> str:
    if rel_path in {"AGENTS.md", "README.md"}:
        return "system"
    first_part = rel_path.split("/", 1)[0]
    if first_part == "System":
        return "system"
    if first_part == "00_Inbox":
        return "inbox"
    if first_part == "01_Concepts":
        return "concept"
    if first_part == "02_Entities":
        return "entity"
    if first_part == "03_Projects":
        return "project"
    if first_part == "04_References":
        return "source"
    if first_part == "05_Journal":
        return "journal"
    if first_part == "06_Maps":
        return "map"
    return "inbox"


def stable_note_id(rel_path: str) -> str:
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:16]
    return f"note_{digest}"


def is_template_path(rel_path: str) -> bool:
    return rel_path.startswith("System/templates/")


def preview(body: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", body).strip()
    return compact[:limit]


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def frontmatter_json(frontmatter: dict[str, Any]) -> str:
    return json.dumps(frontmatter, ensure_ascii=False, sort_keys=True, default=str)
