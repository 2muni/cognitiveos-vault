from __future__ import annotations

from pathlib import Path


SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".obsidian",
        ".trash",
        ".pkm-index",
        ".pytest_cache",
        ".venv",
        "__pycache__",
    }
)
SKIPPED_DIR_PREFIXES = (".venv-",)


def is_skipped_directory_component(component: str) -> bool:
    """Return whether a scanner must exclude this operational component."""

    return component in SKIPPED_DIRS or component.startswith(SKIPPED_DIR_PREFIXES)

# The scanner's skipped directories are part of the operational safety policy
# for writeback too.  Writeback has a deliberately broader denylist because it
# must never create source, build, runtime, or product-policy files even when a
# configuration mistake names a broad allowed root.  Keep the complete policy
# here so the atomic boundary cannot silently drift from scanner-owned names
# such as ``.trash``.
WRITEBACK_DENIED_DIRS = SKIPPED_DIRS | frozenset(
    {
        "venv",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".eggs",
        "node_modules",
        "Assets",
        "System",
        "scripts",
        "src",
        "tests",
        "dist",
        "build",
    }
)
WRITEBACK_DENIED_DIR_PREFIXES = SKIPPED_DIR_PREFIXES
_WRITEBACK_DENIED_DIR_CASEFOLDS = frozenset(name.casefold() for name in WRITEBACK_DENIED_DIRS)
_WRITEBACK_DENIED_DIR_PREFIX_CASEFOLDS = tuple(prefix.casefold() for prefix in WRITEBACK_DENIED_DIR_PREFIXES)


def is_writeback_denied_directory_component(component: str) -> bool:
    """Return whether one path component is operational state denied to writes.

    The threat model requires case-aware component comparison, rather than
    string-prefix checks, for every component in a requested target or allowed
    root.  The inherited ``.venv-*`` scanner policy is included as well, so a
    runtime-environment variant cannot become a writeback escape hatch.
    """

    folded = component.casefold()
    return folded in _WRITEBACK_DENIED_DIR_CASEFOLDS or folded.startswith(_WRITEBACK_DENIED_DIR_PREFIX_CASEFOLDS)


def resolve_vault_root(vault_root: str | Path) -> Path:
    return Path(vault_root).expanduser().resolve()


def safe_resolve_inside(vault_root: str | Path, candidate: str | Path) -> Path:
    root = resolve_vault_root(vault_root)
    raw = Path(candidate)
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes vault root: {candidate}") from exc
    return resolved
