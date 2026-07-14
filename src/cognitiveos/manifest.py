from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .parser import read_text
from .scanner import iter_markdown_files
from .safety import resolve_vault_root


MANIFEST_VERSION = "vault-manifest-v0.1"


@dataclass(frozen=True)
class ManifestRecord:
    path: str
    checksum: str


@dataclass(frozen=True)
class VaultManifest:
    manifest_version: str
    algorithm: str
    markdown_count: int
    digest: str
    records: tuple[ManifestRecord, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "algorithm": self.algorithm,
            "markdown_count": self.markdown_count,
            "digest": self.digest,
        }


def build_vault_manifest(vault_root: str | Path) -> VaultManifest:
    root = resolve_vault_root(vault_root)
    records = tuple(
        ManifestRecord(
            path=path.relative_to(root).as_posix(),
            checksum=hashlib.sha256(read_text(path).encode("utf-8")).hexdigest(),
        )
        for path in iter_markdown_files(root)
    )
    return manifest_from_records(records)


def manifest_from_records(records: Iterable[ManifestRecord]) -> VaultManifest:
    ordered = tuple(sorted(records, key=lambda item: item.path))
    digest = hashlib.sha256()
    seen: set[str] = set()
    for record in ordered:
        if not record.path or not record.checksum:
            raise ValueError("manifest records require a path and checksum")
        if "\\" in record.path or record.path.startswith("/"):
            raise ValueError("manifest paths must be vault-relative POSIX paths")
        if record.path in seen:
            raise ValueError("manifest records must have unique paths")
        if len(record.checksum) != 64 or any(character not in "0123456789abcdef" for character in record.checksum):
            raise ValueError("manifest checksums must be lowercase SHA-256 hex")
        seen.add(record.path)
        digest.update(record.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record.checksum.encode("ascii"))
        digest.update(b"\n")
    return VaultManifest(
        manifest_version=MANIFEST_VERSION,
        algorithm="sha256-path-checksum-v1",
        markdown_count=len(ordered),
        digest=digest.hexdigest(),
        records=ordered,
    )
