from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cognitiveos.cli import main_index, main_search
from cognitiveos.indexer import VaultIndex
from cognitiveos.mcp_server import handle_message
from cognitiveos.models import SearchResult
from cognitiveos.parser import parse_markdown_file
from cognitiveos.retrieval import RetrievalService, estimate_tokens, select_diverse_results
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

    def test_system_path_infers_system_type_without_frontmatter(self) -> None:
        path = self.write_note("System/docs/design.md", "# Design\n\nRuntime schema.")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.note_type, "system")

    def test_root_operational_docs_infer_system_type(self) -> None:
        path = self.write_note("AGENTS.md", "# Agent Guide\n\nRules.")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.note_type, "system")

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
    def test_skips_local_runtime_directories(self) -> None:
        self.write_note("note.md", "# Durable note")
        self.write_note(".venv/lib/package/LICENSE.md", "# Package license")
        self.write_note(".pytest_cache/README.md", "# Pytest cache")

        self.assertEqual(self.index(), 1)

    def test_rebuild_removes_notes_no_longer_in_vault(self) -> None:
        self.write_note("keep.md", "# Keep")
        removed = self.write_note("remove.md", "# Remove")
        self.assertEqual(self.index(), 2)

        removed.unlink()
        self.assertEqual(self.index(), 1)

        with closing(sqlite3.connect(self.db_path)) as conn:
            note_paths = conn.execute("SELECT path FROM notes").fetchall()
            fts_paths = conn.execute("SELECT path FROM fts_notes").fetchall()

        self.assertEqual(note_paths, [("keep.md",)])
        self.assertEqual(fts_paths, [("keep.md",)])

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
        self.assertEqual(context_pack.context_version, "context-pack-v0.3")
        self.assertGreaterEqual(len(context_pack.sources), 1)
        self.assertGreaterEqual(len(context_pack.evidence_paths), 1)
        self.assertGreaterEqual(context_pack.stats["source_count"], 1)
        self.assertEqual(context_pack.budget["requested_tokens"], 4000)
        self.assertLessEqual(context_pack.budget["estimated_tokens"], 4000)

    def test_read_only_generation_helpers(self) -> None:
        self.write_note(
            "alpha.md",
            """---
id: alpha
type: source
title: Alpha Source
---
# Alpha Source

Durable Markdown systems connect concepts through local-first retrieval.

This source explains evidence-first context packs.

- What should the next retrieval step validate?
""",
        )
        self.write_note(
            "beta.md",
            """---
id: beta
type: concept
title: Local-first Retrieval
---
# Local-first Retrieval

Durable Markdown systems need retrieval and context packs.
""",
        )
        self.index()

        service = RetrievalService(self.root, self.db_path)

        suggestions = service.suggest_links("alpha", limit=5)
        self.assertEqual(suggestions[0]["note_id"], "beta")

        summary = service.summarize_source(note_id="alpha")
        self.assertEqual(summary["note_id"], "alpha")
        self.assertEqual(summary["summary_version"], "extractive-v0.2")
        self.assertIn("Durable Markdown", summary["summary"])
        self.assertIn("key_points", summary)
        self.assertIn("open_questions", summary)
        self.assertIn("stats", summary)
        self.assertGreaterEqual(len(summary["evidence"]), 1)
        self.assertGreaterEqual(summary["stats"]["word_count"], 1)
        self.assertTrue(any(question.endswith("?") for question in summary["open_questions"]))

        moc = service.propose_moc("Durable Markdown retrieval", limit=5)
        self.assertFalse(moc["writeback"])
        self.assertGreaterEqual(moc["note_count"], 2)
        self.assertTrue(any(section["type"] == "concept" for section in moc["sections"]))

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

    def test_search_reranks_title_and_heading_matches(self) -> None:
        self.write_note(
            "source.md",
            """---
id: source_body
type: source
title: Long Source
status: active
---
# Notes

Retrieval ranking appears many times. Retrieval ranking should be searchable.
""",
        )
        self.write_note(
            "concept.md",
            """---
id: concept_retrieval
type: concept
title: Retrieval Ranking
status: evergreen
---
# Retrieval Ranking

Short canonical concept.
""",
        )
        self.write_note(
            "project.md",
            """---
id: project_heading
type: project
title: Search Work
status: active
---
# Retrieval Ranking

Project heading match.
""",
        )
        self.index()

        service = RetrievalService(self.root, self.db_path)
        results = service.search_notes("Retrieval Ranking", limit=3)

        self.assertEqual(results[0].note_id, "concept_retrieval")
        self.assertGreater(results[0].score, results[1].score)

    def test_context_pack_token_budget_is_deterministic_and_truncates_evidence(self) -> None:
        self.write_note(
            "source.md",
            "---\nid: source\ntype: source\ntitle: Budget Source\n---\n# Budget Source\n\n"
            + "근거 기반 context pack은 긴 증거 블록을 예산 안에서 선택합니다. " * 80,
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        first = service.build_context_pack("context pack", limit=1, token_budget=512)
        second = service.build_context_pack("context pack", limit=1, token_budget=512)
        full = service.build_context_pack("context pack", limit=1, token_budget=32768)

        self.assertEqual(first.context, second.context)
        self.assertEqual(first.sources, second.sources)
        self.assertEqual(first.budget, second.budget)
        self.assertLessEqual(estimate_tokens(first.context), 512)
        self.assertEqual(first.budget["estimated_tokens"], estimate_tokens(first.context))
        self.assertEqual(first.budget["remaining_tokens"], 512 - estimate_tokens(first.context))
        self.assertTrue(first.budget["truncated"])
        self.assertEqual(first.budget["estimator"], "local-heuristic-v1")
        self.assertIn("path: source.md", first.context)
        self.assertFalse(full.budget["truncated"])
        self.assertGreater(len(full.context), len(first.context))
        self.assertGreaterEqual(len(full.sources[0]["evidence"]), len(first.sources[0]["evidence"]))

    def test_token_estimator_and_direct_service_budget_validation(self) -> None:
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)
        self.assertEqual(estimate_tokens("한글"), 2)
        self.assertEqual(estimate_tokens("ab한글"), 3)

        service = RetrievalService(self.root, self.db_path)
        for invalid in (511, 32769, "512", True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    service.build_context_pack("query", token_budget=invalid)

    def test_context_source_selection_prefers_note_type_diversity(self) -> None:
        results = [
            SearchResult("a", "a.md", "A", "concept", 10.0, "A excerpt"),
            SearchResult("b", "b.md", "B", "concept", 9.0, "B excerpt"),
            SearchResult("c", "c.md", "C", "source", 8.0, "C excerpt"),
        ]

        selected = select_diverse_results(results, limit=2)

        self.assertEqual([result.note_id for result in selected], ["a", "c"])


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
        self.assertEqual(pack.context_version, "context-pack-v0.3")
        self.assertGreaterEqual(len(pack.sources), 1)
        self.assertGreaterEqual(len(pack.key_points), 1)
        self.assertTrue(any(result.path == "projects/read-only-mcp.md" for result in pack.results))
        self.assertIn("projects/read-only-mcp.md", pack.evidence_paths)


class BasicMCPProtocolTests(CognitiveOSTestCase):
    def test_basic_mcp_initialize_list_and_call(self) -> None:
        self.write_note(
            "concept.md",
            """---
id: mcp_concept
type: concept
title: MCP Concept
status: active
---
# MCP Concept

Read-only MCP tools expose Markdown search.
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        init_response = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )
        self.assertEqual(init_response["result"]["serverInfo"]["name"], "cognitiveos")
        self.assertEqual(init_response["result"]["serverInfo"]["version"], "0.2.0")
        self.assertIn("tools", init_response["result"]["capabilities"])

        list_response = handle_message(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
        self.assertIn("search_notes", tool_names)
        self.assertIn("suggest_links", tool_names)
        self.assertIn("summarize_source", tool_names)
        self.assertIn("propose_moc", tool_names)
        self.assertIn("build_context_pack", tool_names)
        context_tool = next(tool for tool in list_response["result"]["tools"] if tool["name"] == "build_context_pack")
        token_schema = context_tool["inputSchema"]["properties"]["token_budget"]
        self.assertEqual(token_schema["minimum"], 512)
        self.assertEqual(token_schema["maximum"], 32768)

        call_response = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_notes", "arguments": {"query": "Markdown"}},
            },
        )
        self.assertFalse(call_response["result"]["isError"])
        self.assertIn("mcp_concept", call_response["result"]["content"][0]["text"])

    def test_basic_mcp_tool_argument_validation(self) -> None:
        self.write_note(
            "concept.md",
            """---
id: mcp_concept
type: concept
title: MCP Concept
---
# MCP Concept

Read-only MCP tools expose Markdown search.
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        empty_query = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "search_notes", "arguments": {"query": ""}},
            },
        )
        self.assertTrue(empty_query["result"]["isError"])
        self.assertEqual(empty_query["result"]["structuredContent"]["error"]["code"], "invalid_argument")

        ambiguous_reference = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "read_note",
                    "arguments": {"note_id": "mcp_concept", "path": "concept.md"},
                },
            },
        )
        self.assertTrue(ambiguous_reference["result"]["isError"])
        self.assertEqual(ambiguous_reference["result"]["structuredContent"]["error"]["code"], "invalid_argument")

        bad_limit = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "list_recent_notes", "arguments": {"limit": 0}},
            },
        )
        self.assertTrue(bad_limit["result"]["isError"])
        self.assertEqual(bad_limit["result"]["structuredContent"]["error"]["code"], "invalid_argument")

        default_budget = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "build_context_pack", "arguments": {"query": "Markdown"}},
            },
        )
        self.assertFalse(default_budget["result"]["isError"])
        self.assertEqual(
            default_budget["result"]["structuredContent"]["result"]["budget"]["requested_tokens"],
            4000,
        )

        for request_id, invalid_budget in enumerate(("512", -1, 32769, True), start=8):
            invalid_response = handle_message(
                service,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": "build_context_pack",
                        "arguments": {"query": "Markdown", "token_budget": invalid_budget},
                    },
                },
            )
            self.assertTrue(invalid_response["result"]["isError"])
            self.assertEqual(
                invalid_response["result"]["structuredContent"]["error"]["code"],
                "invalid_argument",
            )


class CLITests(CognitiveOSTestCase):
    def test_index_and_search_support_text_and_json_formats(self) -> None:
        self.write_note("한글.md", "# 한글 노트\n\nMarkdown 검색 근거")

        json_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-index", str(self.root), "--db", str(self.db_path), "--format", "json"],
        ), redirect_stdout(json_output):
            main_index()
        index_payload = json.loads(json_output.getvalue())
        self.assertEqual(index_payload["indexed_notes"], 1)
        self.assertEqual(index_payload["index_path"], str(self.db_path))

        text_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-index", str(self.root), "--db", str(self.db_path), "--format", "text"],
        ), redirect_stdout(text_output):
            main_index()
        self.assertIn("Indexed 1 notes", text_output.getvalue())

        search_json = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "cognitiveos-search",
                "Markdown",
                "--vault-root",
                str(self.root),
                "--db",
                str(self.db_path),
                "--format",
                "json",
            ],
        ), redirect_stdout(search_json):
            main_search()
        results = json.loads(search_json.getvalue())
        self.assertEqual(results[0]["title"], "한글 노트")
        self.assertEqual(
            set(results[0]),
            {"note_id", "path", "title", "note_type", "score", "matched_excerpt"},
        )

        search_text = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "cognitiveos-search",
                "Markdown",
                "--vault-root",
                str(self.root),
                "--db",
                str(self.db_path),
                "--format",
                "text",
            ],
        ), redirect_stdout(search_text):
            main_search()
        self.assertIn("한글 노트", search_text.getvalue())


if __name__ == "__main__":
    unittest.main()
