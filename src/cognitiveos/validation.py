from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import VALID_NOTE_TYPES
from .parser import FRONTMATTER_RE, extract_headings, infer_note_type, parse_frontmatter, read_text
from .safety import resolve_vault_root, safe_resolve_inside
from .scanner import iter_markdown_files


VALIDATION_VERSION = "note-contract-v0.2"
VALID_STATUSES = {"inbox", "seed", "active", "evergreen", "archived"}
VALID_VISIBILITIES = {"private", "shared", "public"}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
LIST_FIELDS = {"aliases", "tags", "domains", "links", "sources"}
STRING_FIELDS = {"id", "type", "title", "status", "visibility"}
DATE_FIELDS = {"created_at", "updated_at", "created", "updated"}
PLACEHOLDER_VALUES = {
    "untitled capture",
    "capture title",
    "concept title",
    "entity name",
    "map title",
    "output title",
    "project title",
    "source title",
    "system document title",
    "yyyy-mm-dd",
    "yyyymmdd",
}
PLACEHOLDER_RE = re.compile(r"(?:YYYY(?:-?MM(?:-?DD)?)?|YYYYMMDD_slug)$", re.IGNORECASE)
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_LOCATOR_RE = re.compile(
    r"(?:https?://\S+|\bdoi\s*:\s*\S+|\b10\.\d{4,9}/\S+|url or locator\s*:\s*\S+)",
    re.IGNORECASE,
)
RECOMMENDED_HEADINGS = {
    "inbox": ("Capture", "Next"),
    "concept": ("Definition", "Distinction", "Examples", "Related", "Sources", "Open Questions"),
    "source": ("Citation", "Summary", "Key Claims", "Extracted Concepts", "Personal Notes"),
    "entity": ("Type", "Description", "Relations", "Sources"),
    "project": ("Goal", "Current State", "Decisions", "Next Actions", "Related Notes"),
    "map": ("Purpose", "Core Notes", "Clusters", "Open Questions"),
    "journal": ("Log", "Observations", "Decisions", "Follow-ups"),
    "system": ("Purpose", "Specification", "Rationale", "Change Log"),
    "output": ("Brief", "Draft", "Evidence", "Revision Notes"),
}


@dataclass(frozen=True)
class ValidationDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    line: int | None = None
    field: str | None = None
    related_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.line is not None:
            payload["line"] = self.line
        if self.field is not None:
            payload["field"] = self.field
        if self.related_paths:
            payload["related_paths"] = list(self.related_paths)
        return payload


@dataclass(frozen=True)
class ValidationReport:
    scope: str
    strict: bool
    files_scanned: int
    diagnostics: tuple[ValidationDiagnostic, ...] = field(default_factory=tuple)
    validation_version: str = VALIDATION_VERSION

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)

    @property
    def info_count(self) -> int:
        return sum(item.severity == "info" for item in self.diagnostics)

    @property
    def exit_code(self) -> int:
        if self.error_count or (self.strict and self.warning_count):
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_version": self.validation_version,
            "scope": self.scope,
            "strict": self.strict,
            "summary": {
                "files_scanned": self.files_scanned,
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": self.info_count,
            },
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class _NoteValidationState:
    path: str
    frontmatter: dict[str, Any]
    field_lines: dict[str, int]
    headings: tuple[str, ...]
    effective_id: str | None
    effective_type: str
    effective_status: str
    authoring_scope: bool


def validate_vault(
    vault_root: str | Path,
    *,
    scope: str = "user",
    strict: bool = False,
) -> ValidationReport:
    if scope not in {"all", "user"}:
        raise ValueError("scope must be all or user")
    root = resolve_vault_root(vault_root)
    states: list[_NoteValidationState] = []
    diagnostics: list[ValidationDiagnostic] = []
    for absolute_path in iter_markdown_files(root):
        rel_path = absolute_path.relative_to(root).as_posix()
        authoring_scope = scope == "all" or is_user_authored_path(rel_path)
        state, note_diagnostics = validate_note_file(
            absolute_path,
            root,
            authoring_scope=authoring_scope,
        )
        states.append(state)
        diagnostics.extend(note_diagnostics)
    diagnostics.extend(_duplicate_diagnostics(states))
    ordered = tuple(sorted(diagnostics, key=diagnostic_sort_key))
    return ValidationReport(
        scope=scope,
        strict=bool(strict),
        files_scanned=len(states),
        diagnostics=ordered,
    )


def validate_note_file(
    path: str | Path,
    vault_root: str | Path,
    *,
    authoring_scope: bool = True,
) -> tuple[_NoteValidationState, list[ValidationDiagnostic]]:
    root = resolve_vault_root(vault_root)
    absolute = safe_resolve_inside(root, path)
    rel_path = absolute.relative_to(root).as_posix()
    text = read_text(absolute)
    diagnostics: list[ValidationDiagnostic] = []
    frontmatter: dict[str, Any] = {}
    body = text
    raw_frontmatter = ""
    field_lines: dict[str, int] = {}
    match = FRONTMATTER_RE.match(text)
    if text.lstrip().startswith("---") and match is None:
        diagnostics.append(
            diagnostic(
                "frontmatter_parse_failed",
                "error",
                rel_path,
                "frontmatter opening delimiter has no valid closing delimiter",
                line=1,
            )
        )
    elif match is not None:
        raw_frontmatter = match.group(1)
        body = text[match.end() :]
        field_lines = frontmatter_field_lines(raw_frontmatter)
        frontmatter = parse_frontmatter(raw_frontmatter)
        if raw_frontmatter.strip() and not frontmatter and _has_frontmatter_data(raw_frontmatter):
            diagnostics.append(
                diagnostic(
                    "frontmatter_parse_failed",
                    "error",
                    rel_path,
                    "frontmatter could not be parsed as a mapping",
                    line=1,
                )
            )

    diagnostics.extend(
        _field_diagnostics(
            rel_path,
            frontmatter,
            field_lines,
            template_path=is_template_path(rel_path),
        )
    )
    parsed_headings = extract_headings(body)
    headings = tuple(item.text for item in parsed_headings if item.level == 1)
    section_headings = tuple(item.text for item in parsed_headings if item.level >= 2)
    explicit_type = frontmatter.get("type")
    effective_type = (
        explicit_type
        if isinstance(explicit_type, str) and explicit_type in VALID_NOTE_TYPES
        else infer_note_type(rel_path)
    )
    explicit_status = frontmatter.get("status")
    effective_status = explicit_status if isinstance(explicit_status, str) else "seed"
    explicit_id = frontmatter.get("id")
    effective_id = explicit_id.strip() if isinstance(explicit_id, str) and explicit_id.strip() else None
    if is_template_path(rel_path):
        effective_id = None

    if not is_template_path(rel_path):
        diagnostics.extend(_placeholder_diagnostics(rel_path, frontmatter, field_lines, headings))
    if authoring_scope and not is_template_path(rel_path):
        diagnostics.extend(
            _authoring_diagnostics(
                rel_path,
                frontmatter,
                field_lines,
                headings,
                section_headings,
                body,
                effective_type,
                effective_status,
                type_is_valid=explicit_type is None or explicit_type in VALID_NOTE_TYPES,
            )
        )

    state = _NoteValidationState(
        path=rel_path,
        frontmatter=frontmatter,
        field_lines=field_lines,
        headings=headings,
        effective_id=effective_id,
        effective_type=effective_type,
        effective_status=effective_status,
        authoring_scope=authoring_scope,
    )
    return state, diagnostics


def _field_diagnostics(
    path: str,
    frontmatter: dict[str, Any],
    field_lines: dict[str, int],
    *,
    template_path: bool,
) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    for field_name in sorted(STRING_FIELDS & frontmatter.keys()):
        value = frontmatter[field_name]
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                invalid_field_type(path, field_name, field_lines, "a non-empty string")
            )
    for field_name in sorted(LIST_FIELDS & frontmatter.keys()):
        value = frontmatter[field_name]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            diagnostics.append(
                invalid_field_type(path, field_name, field_lines, "a list of strings")
            )

    note_type = frontmatter.get("type")
    if isinstance(note_type, str) and note_type not in VALID_NOTE_TYPES:
        diagnostics.append(
            diagnostic(
                "invalid_type",
                "error",
                path,
                f"type must be one of: {', '.join(sorted(VALID_NOTE_TYPES))}",
                line=field_lines.get("type"),
                field="type",
            )
        )
    status = frontmatter.get("status")
    if isinstance(status, str) and status not in VALID_STATUSES:
        diagnostics.append(
            diagnostic(
                "invalid_status",
                "error",
                path,
                f"status must be one of: {', '.join(sorted(VALID_STATUSES))}",
                line=field_lines.get("status"),
                field="status",
            )
        )
    visibility = frontmatter.get("visibility")
    if isinstance(visibility, str) and visibility not in VALID_VISIBILITIES:
        diagnostics.append(
            diagnostic(
                "invalid_field_type",
                "error",
                path,
                "visibility must be private, shared, or public",
                line=field_lines.get("visibility"),
                field="visibility",
            )
        )
    if visibility in {"shared", "public"}:
        diagnostics.append(
            diagnostic(
                "visibility_is_not_access_control",
                "info",
                path,
                "visibility is classification metadata, not an access-control boundary",
                line=field_lines.get("visibility"),
                field="visibility",
            )
        )

    confidence = frontmatter.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            diagnostics.append(
                invalid_field_type(path, "confidence", field_lines, "a number from 0.0 through 1.0")
            )
        elif not 0.0 <= float(confidence) <= 1.0:
            diagnostics.append(
                diagnostic(
                    "confidence_out_of_range",
                    "error",
                    path,
                    "confidence must be from 0.0 through 1.0",
                    line=field_lines.get("confidence"),
                    field="confidence",
                )
            )

    for field_name in sorted(DATE_FIELDS & frontmatter.keys()):
        value = frontmatter[field_name]
        if template_path and is_placeholder_value(value):
            continue
        if not is_iso_date_value(value):
            diagnostics.append(
                diagnostic(
                    "invalid_date",
                    "error",
                    path,
                    "date must use ISO YYYY-MM-DD or an ISO 8601 datetime",
                    line=field_lines.get(field_name),
                    field=field_name,
                )
            )

    return diagnostics


def _authoring_diagnostics(
    path: str,
    frontmatter: dict[str, Any],
    field_lines: dict[str, int],
    headings: tuple[str, ...],
    section_headings: tuple[str, ...],
    body: str,
    note_type: str,
    status: str,
    *,
    type_is_valid: bool,
) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    if note_type != "inbox" and not _nonempty_string(frontmatter.get("id")):
        diagnostics.append(
            diagnostic(
                "durable_id_missing",
                "warning",
                path,
                "durable notes should have an explicit stable id",
                field="id",
            )
        )
    if note_type == "inbox" and status != "inbox":
        diagnostics.append(
            diagnostic(
                "lifecycle_inbox_status_mismatch",
                "warning",
                path,
                "inbox notes should use status inbox until triage changes their type",
                line=field_lines.get("status"),
                field="status",
            )
        )
    title = frontmatter.get("title")
    if isinstance(title, str) and headings and title.strip() != headings[0].strip():
        diagnostics.append(
            diagnostic(
                "title_heading_mismatch",
                "warning",
                path,
                "frontmatter title differs from the first H1 heading",
                line=field_lines.get("title"),
                field="title",
            )
        )
    for field_name in ("tags", "domains"):
        value = frontmatter.get(field_name)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item and not KEBAB_CASE_RE.fullmatch(item):
                    diagnostics.append(
                        diagnostic(
                            "tag_domain_noncanonical",
                            "warning",
                            path,
                            f"{field_name} values should use lowercase kebab-case where practical",
                            line=field_lines.get(field_name),
                            field=field_name,
                        )
                    )
                    break
    if type_is_valid and not is_layer_spec_path(path):
        existing_headings = {heading.strip().casefold() for heading in section_headings}
        missing_headings: list[str] = []
        for expected_heading in RECOMMENDED_HEADINGS.get(note_type, ()):
            if expected_heading.casefold() not in existing_headings:
                missing_headings.append(expected_heading)
        if missing_headings:
            diagnostics.append(
                diagnostic(
                    "recommended_heading_missing",
                    "warning",
                    path,
                    f"{note_type} note is missing recommended sections: {', '.join(missing_headings)}",
                    field="heading",
                )
            )
        if note_type == "source" and not has_source_locator(frontmatter, body):
            diagnostics.append(
                diagnostic(
                    "source_locator_missing",
                    "warning",
                    path,
                    "source notes should include a URL, DOI, or other locator",
                    field="source",
                )
            )
    return diagnostics


def _placeholder_diagnostics(
    path: str,
    frontmatter: dict[str, Any],
    field_lines: dict[str, int],
    headings: tuple[str, ...],
) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    for field_name in sorted(frontmatter):
        values = frontmatter[field_name]
        items = values if isinstance(values, list) else [values]
        if any(is_placeholder_value(item) for item in items):
            diagnostics.append(
                diagnostic(
                    "template_placeholder_present",
                    "error",
                    path,
                    "template placeholder must be replaced before indexing",
                    line=field_lines.get(field_name),
                    field=field_name,
                )
            )
    if headings and is_placeholder_value(headings[0]):
        diagnostics.append(
            diagnostic(
                "template_placeholder_present",
                "error",
                path,
                "first H1 template placeholder must be replaced before indexing",
                field="title",
            )
        )
    return diagnostics


def _duplicate_diagnostics(states: list[_NoteValidationState]) -> list[ValidationDiagnostic]:
    diagnostics: list[ValidationDiagnostic] = []
    by_id: dict[str, list[_NoteValidationState]] = {}
    by_title: dict[str, list[_NoteValidationState]] = {}
    for state in states:
        if state.effective_id:
            by_id.setdefault(state.effective_id, []).append(state)
        if state.authoring_scope and state.headings:
            title = state.headings[0].strip().casefold()
            if title:
                by_title.setdefault(title, []).append(state)
    for note_id, duplicates in sorted(by_id.items()):
        if len(duplicates) < 2:
            continue
        paths = tuple(sorted(item.path for item in duplicates))
        for item in duplicates:
            diagnostics.append(
                diagnostic(
                    "duplicate_id",
                    "error",
                    item.path,
                    f"note id {note_id!r} is used by another scanner-visible note",
                    line=item.field_lines.get("id"),
                    field="id",
                    related_paths=tuple(path for path in paths if path != item.path),
                )
            )
    for _title, duplicates in sorted(by_title.items()):
        if len(duplicates) < 2:
            continue
        paths = tuple(sorted(item.path for item in duplicates))
        for item in duplicates:
            diagnostics.append(
                diagnostic(
                    "duplicate_title",
                    "warning",
                    item.path,
                    "first H1 title is also used by another user-scope note",
                    related_paths=tuple(path for path in paths if path != item.path),
                )
            )
    return diagnostics


def invalid_field_type(
    path: str,
    field_name: str,
    field_lines: dict[str, int],
    expected: str,
) -> ValidationDiagnostic:
    return diagnostic(
        "invalid_field_type",
        "error",
        path,
        f"{field_name} must be {expected}",
        line=field_lines.get(field_name),
        field=field_name,
    )


def diagnostic(
    code: str,
    severity: str,
    path: str,
    message: str,
    *,
    line: int | None = None,
    field: str | None = None,
    related_paths: tuple[str, ...] = (),
) -> ValidationDiagnostic:
    return ValidationDiagnostic(
        code=code,
        severity=severity,
        path=path,
        message=message,
        line=line,
        field=field,
        related_paths=related_paths,
    )


def diagnostic_sort_key(item: ValidationDiagnostic) -> tuple[Any, ...]:
    return (
        SEVERITY_ORDER[item.severity],
        item.path,
        item.line if item.line is not None else 0,
        item.code,
        item.field or "",
    )


def frontmatter_field_lines(raw: str) -> dict[str, int]:
    lines: dict[str, int] = {}
    for index, line in enumerate(raw.splitlines(), start=2):
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key:
            lines.setdefault(key, index)
    return lines


def is_iso_date_value(value: Any) -> bool:
    if isinstance(value, datetime):
        return True
    if isinstance(value, date):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    try:
        if "T" in candidate or " " in candidate:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        else:
            date.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def is_placeholder_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped.casefold() in PLACEHOLDER_VALUES or bool(PLACEHOLDER_RE.search(stripped))


def has_source_locator(frontmatter: dict[str, Any], body: str) -> bool:
    for field_name in ("url", "locator", "doi"):
        value = frontmatter.get(field_name)
        if isinstance(value, str) and value.strip():
            return True
    return bool(SOURCE_LOCATOR_RE.search(body))


def is_user_authored_path(path: str) -> bool:
    return not (path.startswith("System/") or path in {"README.md", "AGENTS.md"})


def is_template_path(path: str) -> bool:
    return path.startswith("System/templates/")


def is_layer_spec_path(path: str) -> bool:
    return Path(path).name == "__SPECS__.md"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_frontmatter_data(raw: str) -> bool:
    return any(line.strip() and not line.lstrip().startswith("#") for line in raw.splitlines())
