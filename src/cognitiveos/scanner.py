from __future__ import annotations

from pathlib import Path

from .safety import is_skipped_directory_component, resolve_vault_root


def iter_markdown_files(vault_root: str | Path) -> list[Path]:
    root = resolve_vault_root(vault_root)
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if any(is_skipped_part(part) for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().lower())


def is_skipped_part(part: str) -> bool:
    return is_skipped_directory_component(part)
