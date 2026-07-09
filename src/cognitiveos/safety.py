from __future__ import annotations

from pathlib import Path


SKIPPED_DIRS = {".git", ".obsidian", ".trash", ".pkm-index", "__pycache__"}


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
