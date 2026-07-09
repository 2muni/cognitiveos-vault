from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cognitiveos.indexer import VaultIndex
from cognitiveos.parser import parse_markdown_file
from cognitiveos.retrieval import RetrievalService
from cognitiveos.safety import safe_resolve_inside


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CognitiveOSTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / ".pkm-index" / "test.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_note(self, rel_path: str, text: str) -> Path:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def index(self) -> int:
        with VaultIndex(self.db_path) as index:
            return index.index_vault(self.root)


class ParserTests(CognitiveOSTestCase):
    def test_parses_frontmatter_headings_and_links(self) -> None:
        path = self.write_note(
            "Concepts/한글.md",
            """---
id: concept_local_first
type: concept
title: Local-first PKM
aliases: [Local PKM]
status: active
---
# Local-first PKM

See [[Source Note|source]] and [example](https://example.com).
""",
        )

        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.note_id, "concept_local_first")
        self.assertEqual(note.note_type, "concept")
        self.assertEqual(note.title, "Local-first PKM")
        self.assertEqual(note.headings[0].text, "Local-first PKM")
        self.assertEqual({link.link_type for link in note.links}, {"wikilink", "markdown"})

    def test_missing_frontmatter_uses_runtime_defaults(self) -> None:
        path = self.write_note("Inbox/raw.md", "# Raw Capture\n\nhello")
        note = parse_markdown_file(path, self.root)

        self.assertTrue(note.note_id.startswith("note_"))
        self.assertEqual(note.note_type, "inbox")
        self.assertEqual(note.status, "seed")
        self.assertEqual(note.title, "Raw Capture")

    def test_broken_yaml_does_not_fail_parsing(self) -> None:
        path = self.write_note("broken.md", "---\ntitle: [broken\n---\n# Body")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.title, "Body")

    def test_empty_file_is_valid_note(self) -> None:
        path = self.write_note("empty.md", "")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.title, "empty")
        self.assertEqual(note.body, "")


class SafetyTests(CognitiveOSTestCase):
    def test_rejects_path_outside_vault(self) -> None:
        with self.assertRaises(ValueError):
            safe_resolve_inside(self.root, "../outside.md")


class IndexTests(CognitiveOSTestCase):
    def test_indexes_notes_links_headings_and_fts_without_duplicates(self) -> None:
        self.write_note(
            "concept.md",
            """---
id: concept_a
type: concept
title: Alpha
---
# Alpha

Semantic retrieval links to [[Beta]].
""",
        )
        self.write_note("nested/beta.md", "# Beta\n\n한글 검색 테스트")

        self.assertEqual(self.index(), 2)
        self.assertEqual(self.index(), 2)

        with closing(sqlite3.connect(self.db_path)) as conn:
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            link_count = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
            heading_count = conn.execute("SELECT COUNT(*) FROM headings").fetchone()[0]
            fts_count = conn.execute("SELECT COUNT(*) FROM fts_notes").fetchone()[0]

        self.assertEqual(note_count, 2)
        self.assertEqual(link_count, 1)
        self.assertEqual(heading_count, 2)
        self.assertEqual(fts_count, 2)


class RetrievalTests(CognitiveOSTestCase):
    def test_search_read_backlinks_and_context_pack(self) -> None:
        self.write_note(
            "alpha.md",
            """---
id: alpha
type: concept
title: Alpha
---
# Alpha

Local-first systems need durable Markdown.
""",
        )
        self.write_note("beta.md", "# Beta\n\nThis references [[Alpha]] and durable notes.")
        self.index()

        service = RetrievalService(self.root, self.db_path)
        results = service.search_notes("durable", limit=5)

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(results[0].path.endswith(".md"))
        self.assertNotEqual(results[0].matched_excerpt, "")

        note = service.read_note(note_id="alpha")
        self.assertEqual(note["title"], "Alpha")

        backlinks = service.get_backlinks("alpha")
        self.assertEqual(backlinks[0]["title"], "Beta")

        context_pack = service.build_context_pack("durable", limit=2)
        self.assertIn("path:", context_pack.context)

    def test_type_filter_and_missing_note_errors(self) -> None:
        self.write_note("---ignored.md", "not frontmatter")
        self.write_note("source.md", "---\nid: src\ntype: source\ntitle: Source\n---\nBody keyword")
        self.write_note("concept.md", "---\nid: con\ntype: concept\ntitle: Concept\n---\nBody keyword")
        self.index()

        service = RetrievalService(self.root, self.db_path)
        results = service.search_notes("keyword", note_type="source", limit=10)

        self.assertEqual([result.note_id for result in results], ["src"])
        with self.assertRaises(KeyError):
            service.read_note(note_id="missing")


class SchemaFixtureTests(CognitiveOSTestCase):
    def test_schema_fixture_supports_type_status_domain_and_tag_filters(self) -> None:
        fixture_root = FIXTURES / "schema_vault"
        with VaultIndex(self.db_path) as index:
            count = index.index_vault(fixture_root)

        self.assertEqual(count, 3)
        service = RetrievalService(fixture_root, self.db_path)

        concept_results = service.search_notes(
            "Markdown",
            note_type="concept",
            status="evergreen",
            domain="knowledge-systems",
            tag="pkm",
            limit=10,
        )
        self.assertEqual([result.note_id for result in concept_results], ["concept_local_first_pkm"])

        project_results = service.search_notes(
            "MCP",
            note_type="project",
            status="active",
            domain="knowledge-systems",
            tag="implementation",
            limit=10,
        )
        self.assertEqual([result.note_id for result in project_results], ["project_read_only_mcp"])

        source_results = service.search_notes(
            "resources tools prompts",
            note_type="source",
            domain="protocols",
            tag="mcp",
            limit=10,
        )
        self.assertEqual([result.note_id for result in source_results], ["source_mcp_spec"])

    def test_schema_fixture_context_pack_preserves_evidence_paths(self) -> None:
        fixture_root = FIXTURES / "schema_vault"
        with VaultIndex(self.db_path) as index:
            index.index_vault(fixture_root)

        service = RetrievalService(fixture_root, self.db_path)
        pack = service.build_context_pack("read-only MCP Markdown", limit=3)

        self.assertIn("path:", pack.context)
        self.assertTrue(any(result.path == "projects/read-only-mcp.md" for result in pack.results))


if __name__ == "__main__":
    unittest.main()
