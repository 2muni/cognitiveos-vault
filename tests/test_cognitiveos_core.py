from __future__ import annotations

import io
import hashlib
import json
import math
import sqlite3
import struct
import sys
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cognitiveos.cli as cognitiveos_cli
from cognitiveos.cli import main_embed, main_index, main_search
from cognitiveos.embedding_chunks import (
    CHUNKER_VERSION,
    chunk_note,
    markdown_blocks,
    stable_chunk_id,
)
from cognitiveos.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingIdentity,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingValidationError,
    embed_texts,
    provider_identity,
)
from cognitiveos.embedding_index import (
    EmbeddingIndexBuilder,
    embedding_index_status,
    pack_vector,
    unpack_vector,
    SemanticUnavailableError,
)
from cognitiveos.indexer import VaultIndex
from cognitiveos.mcp_server import handle_message
from cognitiveos.models import SearchResult
from cognitiveos.parser import parse_markdown_file
from cognitiveos.retrieval import RetrievalService, estimate_tokens, select_diverse_results
from cognitiveos.safety import safe_resolve_inside
from cognitiveos.sentence_transformers_adapter import SentenceTransformersProvider


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class DeterministicTestEmbeddingProvider:
    provider_id = "test"
    model_id = "sha256-vector"
    model_revision = "v1"
    dimension = 4

    def __init__(self) -> None:
        self.call_count = 0
        self.embedded_text_count = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.embedded_text_count += len(texts)
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = [(digest[index] / 127.5) - 1.0 for index in range(self.dimension)]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


class StaticEmbeddingProvider:
    provider_id = "test"
    model_id = "static"
    model_revision = "v1"
    dimension = 3

    def __init__(self, output: object = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.error is not None:
            raise self.error
        return self.output  # type: ignore[return-value]


class KeywordTestEmbeddingProvider:
    provider_id = "keyword-test"
    model_id = "multilingual-keywords"
    model_revision = "v1"
    dimension = 3

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        groups = (
            ("local-first", "markdown", "durable", "device", "오프라인", "로컬", "지식", "보관"),
            ("mcp", "protocol", "tool", "interface", "프로토콜", "도구"),
            ("roadmap", "project", "plan", "release", "프로젝트", "계획", "단계", "일정"),
        )
        for text in texts:
            lowered = text.lower()
            vector = [float(sum(lowered.count(term) for term in terms)) for terms in groups]
            if not any(vector):
                vector = [0.01, 0.01, 0.01]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


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


class EmbeddingProviderTests(unittest.TestCase):
    def test_sentence_transformers_adapter_is_offline_safe_and_normalized(self) -> None:
        calls: dict[str, object] = {}

        class FakeModel:
            def get_sentence_embedding_dimension(self) -> int:
                return 2

            def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
                calls["texts"] = texts
                calls["encode"] = kwargs
                return [[0.6, 0.8] for _text in texts]

        def loader(model_id: str, **kwargs: object) -> FakeModel:
            calls["model_id"] = model_id
            calls["load"] = kwargs
            return FakeModel()

        provider = SentenceTransformersProvider(
            "example/model",
            "deadbeef",
            model_loader=loader,
        )

        self.assertEqual(provider.dimension, 2)
        self.assertEqual(calls["model_id"], "example/model")
        self.assertEqual(
            calls["load"],
            {
                "revision": "deadbeef",
                "device": "cpu",
                "local_files_only": True,
                "trust_remote_code": False,
            },
        )
        self.assertEqual(embed_texts(provider, ["한글", "English"]), [[0.6, 0.8], [0.6, 0.8]])
        self.assertEqual(
            calls["encode"],
            {
                "convert_to_numpy": True,
                "normalize_embeddings": True,
                "show_progress_bar": False,
            },
        )

    def test_sentence_transformers_download_requires_explicit_opt_in(self) -> None:
        load_calls: list[dict[str, object]] = []

        class FakeModel:
            def get_embedding_dimension(self) -> int:
                return 3

        def loader(_model_id: str, **kwargs: object) -> FakeModel:
            load_calls.append(kwargs)
            return FakeModel()

        SentenceTransformersProvider(
            "example/model",
            "deadbeef",
            allow_model_download=True,
            device="mps",
            model_loader=loader,
        )

        self.assertFalse(load_calls[0]["local_files_only"])
        self.assertFalse(load_calls[0]["trust_remote_code"])
        self.assertEqual(load_calls[0]["device"], "mps")

    def test_sentence_transformers_load_failure_is_sanitized(self) -> None:
        def failing_loader(_model_id: str, **_kwargs: object) -> object:
            raise RuntimeError("secret backend detail")

        with self.assertRaisesRegex(EmbeddingConfigurationError, "local-cache-only") as raised:
            SentenceTransformersProvider(
                "example/model",
                "deadbeef",
                model_loader=failing_loader,
            )
        self.assertNotIn("secret backend detail", str(raised.exception))

    def test_provider_identity_and_deterministic_batch(self) -> None:
        provider = DeterministicTestEmbeddingProvider()

        self.assertIsInstance(provider, EmbeddingProvider)
        self.assertEqual(
            provider_identity(provider),
            EmbeddingIdentity("test", "sha256-vector", "v1", 4),
        )
        first = embed_texts(provider, ["한글 semantic retrieval", "Markdown evidence"])
        second = embed_texts(provider, ["한글 semantic retrieval", "Markdown evidence"])

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertTrue(all(len(vector) == 4 for vector in first))
        self.assertTrue(all(math.isclose(sum(value * value for value in vector), 1.0) for vector in first))

    def test_empty_batch_does_not_call_provider(self) -> None:
        provider = DeterministicTestEmbeddingProvider()

        self.assertEqual(embed_texts(provider, []), [])
        self.assertEqual(provider.call_count, 0)

    def test_invalid_identity_and_input_are_rejected(self) -> None:
        with self.assertRaises(EmbeddingConfigurationError):
            EmbeddingIdentity("", "model", "v1", 3)
        with self.assertRaises(EmbeddingConfigurationError):
            EmbeddingIdentity("provider", "model", "v1", True)

        identity_only = type(
            "IdentityOnly",
            (),
            {"provider_id": "test", "model_id": "model", "model_revision": "v1", "dimension": 3},
        )()
        with self.assertRaises(EmbeddingConfigurationError):
            embed_texts(identity_only, ["text"])  # type: ignore[arg-type]

        provider = DeterministicTestEmbeddingProvider()
        for invalid in ("text", [""], ["   "], [1]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(EmbeddingConfigurationError):
                    embed_texts(provider, invalid)  # type: ignore[arg-type]

    def test_provider_failures_and_invalid_vectors_are_rejected(self) -> None:
        with self.assertRaises(EmbeddingProviderError) as failure:
            embed_texts(StaticEmbeddingProvider(error=RuntimeError("secret input")), ["private note"])
        self.assertNotIn("private note", str(failure.exception))
        self.assertNotIn("secret input", str(failure.exception))

        invalid_outputs = (
            [],
            [[1.0, 2.0]],
            [[1.0, float("nan"), 2.0]],
            [[1.0, True, 2.0]],
            [[0.0, 0.0, 0.0]],
        )
        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaises(EmbeddingValidationError):
                    embed_texts(StaticEmbeddingProvider(output=output), ["text"])


class EmbeddingChunkTests(CognitiveOSTestCase):
    def test_markdown_blocks_preserve_kinds_lines_and_heading(self) -> None:
        blocks = markdown_blocks(
            "# Retrieval\n\nParagraph line one.\nParagraph line two.\n\n- first\n- second"
        )

        self.assertEqual([block.kind for block in blocks], ["paragraph", "list"])
        self.assertEqual([(block.start_line, block.end_line) for block in blocks], [(3, 4), (6, 7)])
        self.assertTrue(all(block.heading == "Retrieval" for block in blocks))

    def test_chunks_exclude_frontmatter_and_preserve_heading_context(self) -> None:
        path = self.write_note(
            "source.md",
            """---
id: source
type: source
title: Semantic Source
secret_value: do-not-embed
---
# Retrieval

Semantic evidence stays grounded in Markdown.
""",
        )
        note = parse_markdown_file(path, self.root)

        chunks = chunk_note(note)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading, "Retrieval")
        self.assertIn("title: Semantic Source", chunks[0].content)
        self.assertIn("heading: Retrieval", chunks[0].content)
        self.assertIn("Semantic evidence", chunks[0].content)
        self.assertNotIn("secret_value", chunks[0].content)
        self.assertNotIn("do-not-embed", chunks[0].content)
        self.assertEqual(chunks[0].chunker_version, CHUNKER_VERSION)

    def test_chunk_ids_and_content_hashes_are_stable(self) -> None:
        path = self.write_note("note.md", "# Stable\n\nDeterministic chunk content.")
        note = parse_markdown_file(path, self.root)

        first = chunk_note(note)
        second = chunk_note(note)

        self.assertEqual(first, second)
        self.assertEqual(first[0].chunk_id, stable_chunk_id(note.note_id, note.checksum, 0))
        self.assertEqual(first[0].content_hash, hashlib.sha256(first[0].content.encode("utf-8")).hexdigest())

        path.write_text("# Stable\n\nChanged chunk content.", encoding="utf-8")
        changed = chunk_note(parse_markdown_file(path, self.root))
        self.assertNotEqual(first[0].chunk_id, changed[0].chunk_id)

    def test_chunks_respect_character_limit_and_overlap(self) -> None:
        first_paragraph = "alpha " * 10
        second_paragraph = "beta " * 12
        path = self.write_note("overlap.md", f"{first_paragraph}\n\n{second_paragraph}")
        note = parse_markdown_file(path, self.root)

        chunks = chunk_note(note, max_chars=110, overlap_chars=20)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk.content) <= 110 for chunk in chunks))
        self.assertEqual([chunk.chunk_index for chunk in chunks], list(range(len(chunks))))
        overlap = first_paragraph.strip()[-20:].lstrip()
        self.assertIn(overlap, chunks[1].content)

    def test_long_blocks_split_at_stable_boundaries(self) -> None:
        path = self.write_note("long.md", "Sentence one. " * 30)
        note = parse_markdown_file(path, self.root)

        chunks = chunk_note(note, max_chars=100, overlap_chars=15)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.content) <= 100 for chunk in chunks))
        self.assertTrue(all(chunk.start_line == 1 and chunk.end_line == 1 for chunk in chunks))
        self.assertEqual(chunks, chunk_note(note, max_chars=100, overlap_chars=15))

    def test_empty_heading_only_notes_and_invalid_limits(self) -> None:
        empty_path = self.write_note("empty.md", "")
        empty = chunk_note(parse_markdown_file(empty_path, self.root))
        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0].content, "title: empty")

        heading_path = self.write_note("heading.md", "# Heading Only")
        heading = chunk_note(parse_markdown_file(heading_path, self.root))
        self.assertEqual(heading[0].heading, "Heading Only")
        self.assertIn("title: Heading Only", heading[0].content)

        note = parse_markdown_file(empty_path, self.root)
        for max_chars, overlap_chars in ((63, 0), (100, -1), (100, 100), (True, 0)):
            with self.subTest(max_chars=max_chars, overlap_chars=overlap_chars):
                with self.assertRaises(EmbeddingConfigurationError):
                    chunk_note(note, max_chars=max_chars, overlap_chars=overlap_chars)

        for note_id, checksum, chunk_index in (("", "sum", 0), ("note", "", 0), ("note", "sum", -1)):
            with self.subTest(note_id=note_id, checksum=checksum, chunk_index=chunk_index):
                with self.assertRaises(EmbeddingConfigurationError):
                    stable_chunk_id(note_id, checksum, chunk_index)


class EmbeddingIndexTests(CognitiveOSTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedding_db_path = self.root / ".pkm-index" / "embeddings.sqlite3"

    def test_vector_serialization_is_little_endian_and_validated(self) -> None:
        blob = pack_vector([1.0, -2.5, 3.25])

        self.assertEqual(blob, struct.pack("<3f", 1.0, -2.5, 3.25))
        self.assertEqual(unpack_vector(blob, 3), [1.0, -2.5, 3.25])
        for invalid_blob, dimension in ((b"", 1), (blob, 2), (struct.pack("<f", float("nan")), 1)):
            with self.subTest(invalid_blob=invalid_blob, dimension=dimension):
                with self.assertRaises(ValueError):
                    unpack_vector(invalid_blob, dimension)
        with self.assertRaises(ValueError):
            pack_vector([0.0, 0.0])

    def test_full_incremental_and_forced_rebuilds(self) -> None:
        self.write_note("alpha.md", "# Alpha\n\nSemantic alpha evidence.")
        self.write_note("beta.md", "# Beta\n\nSemantic beta evidence.")

        first_provider = DeterministicTestEmbeddingProvider()
        first = EmbeddingIndexBuilder(self.root, first_provider, self.embedding_db_path).build()
        self.assertEqual(first.note_count, 2)
        self.assertEqual(first.chunk_count, 2)
        self.assertEqual(first.embedded_chunk_count, 2)
        self.assertEqual(first.reused_chunk_count, 0)
        self.assertEqual(first_provider.embedded_text_count, 2)

        status = embedding_index_status(self.embedding_db_path)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["chunk_count"], 2)
        self.assertEqual(status["chunker_version"], CHUNKER_VERSION)

        incremental_provider = DeterministicTestEmbeddingProvider()
        incremental = EmbeddingIndexBuilder(
            self.root, incremental_provider, self.embedding_db_path
        ).build()
        self.assertEqual(incremental.reused_chunk_count, 2)
        self.assertEqual(incremental.embedded_chunk_count, 0)
        self.assertEqual(incremental_provider.call_count, 0)

        rebuild_provider = DeterministicTestEmbeddingProvider()
        rebuilt = EmbeddingIndexBuilder(self.root, rebuild_provider, self.embedding_db_path).build(rebuild=True)
        self.assertEqual(rebuilt.reused_chunk_count, 0)
        self.assertEqual(rebuilt.embedded_chunk_count, 2)
        self.assertEqual(rebuild_provider.embedded_text_count, 2)

    def test_incremental_build_reembeds_only_changed_notes(self) -> None:
        alpha = self.write_note("alpha.md", "# Alpha\n\nOriginal alpha.")
        self.write_note("beta.md", "# Beta\n\nStable beta.")
        EmbeddingIndexBuilder(
            self.root, DeterministicTestEmbeddingProvider(), self.embedding_db_path
        ).build()

        alpha.write_text("# Alpha\n\nChanged alpha.", encoding="utf-8")
        provider = DeterministicTestEmbeddingProvider()
        result = EmbeddingIndexBuilder(self.root, provider, self.embedding_db_path).build()

        self.assertEqual(result.reused_chunk_count, 1)
        self.assertEqual(result.embedded_chunk_count, 1)
        self.assertEqual(provider.embedded_text_count, 1)

    def test_failed_build_preserves_last_valid_database(self) -> None:
        note = self.write_note("note.md", "# Note\n\nInitial content.")
        EmbeddingIndexBuilder(
            self.root, DeterministicTestEmbeddingProvider(), self.embedding_db_path
        ).build()
        before = self.embedding_db_path.read_bytes()
        note.write_text("# Note\n\nChanged content.", encoding="utf-8")

        failing = StaticEmbeddingProvider(error=RuntimeError("provider unavailable"))
        with self.assertRaises(EmbeddingProviderError):
            EmbeddingIndexBuilder(self.root, failing, self.embedding_db_path).build(rebuild=True)

        self.assertEqual(self.embedding_db_path.read_bytes(), before)
        self.assertFalse((self.embedding_db_path.parent / ".embeddings.sqlite3.tmp").exists())
        self.assertEqual(embedding_index_status(self.embedding_db_path)["status"], "completed")

    def test_status_and_cli_json_contract(self) -> None:
        missing = embedding_index_status(self.embedding_db_path)
        self.assertEqual(missing["status"], "missing")

        corrupt = self.root / ".pkm-index" / "corrupt.sqlite3"
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"not sqlite")
        self.assertEqual(embedding_index_status(corrupt)["status"], "invalid")

        self.write_note("한글.md", "# 한글\n\nSemantic evidence.")
        error_output = io.StringIO()
        with patch.dict(
            cognitiveos_cli.EMBEDDING_PROVIDER_FACTORIES,
            {},
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "cognitiveos-embed",
                "--vault-root",
                str(self.root),
                "--db",
                str(self.embedding_db_path),
                "--provider",
                "missing",
                "--model",
                "model",
                "--revision",
                "v1",
            ],
        ), redirect_stderr(error_output):
            with self.assertRaises(SystemExit):
                main_embed()
        self.assertIn("embedding provider is not registered", error_output.getvalue())
        self.assertFalse(self.embedding_db_path.exists())

        build_output = io.StringIO()
        with patch.dict(
            cognitiveos_cli.EMBEDDING_PROVIDER_FACTORIES,
            {
                "test": lambda model, revision, allow_download, device: (
                    DeterministicTestEmbeddingProvider()
                )
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "cognitiveos-embed",
                "--vault-root",
                str(self.root),
                "--db",
                str(self.embedding_db_path),
                "--provider",
                "test",
                "--model",
                "sha256-vector",
                "--revision",
                "v1",
                "--format",
                "json",
            ],
        ), redirect_stdout(build_output):
            main_embed()
        build_payload = json.loads(build_output.getvalue())
        self.assertEqual(build_payload["provider_id"], "test")
        self.assertEqual(build_payload["embedded_chunk_count"], 1)

        status_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "cognitiveos-embed",
                "--vault-root",
                str(self.root),
                "--db",
                str(self.embedding_db_path),
                "--status",
                "--format",
                "json",
            ],
        ), redirect_stdout(status_output):
            main_embed()
        status_payload = json.loads(status_output.getvalue())
        self.assertEqual(status_payload["status"], "completed")
        self.assertEqual(status_payload["chunk_count"], 1)

        with sqlite3.connect(self.embedding_db_path) as conn:
            conn.execute("UPDATE embedding_chunks SET vector = ?", (b"broken",))
        self.assertEqual(embedding_index_status(self.embedding_db_path)["status"], "invalid")


class SemanticRetrievalTests(CognitiveOSTestCase):
    def build_semantic_fixture(self) -> tuple[RetrievalService, Path]:
        fixture_root = FIXTURES / "semantic_vault"
        with VaultIndex(self.db_path) as index:
            index.index_vault(fixture_root)
        embedding_db = self.root / ".pkm-index" / "semantic.sqlite3"
        provider = KeywordTestEmbeddingProvider()
        EmbeddingIndexBuilder(fixture_root, provider, embedding_db).build()
        return (
            RetrievalService(
                fixture_root,
                self.db_path,
                embedding_provider=provider,
                embedding_db_path=embedding_db,
            ),
            embedding_db,
        )

    def test_multilingual_semantic_evaluation_and_rrf_diagnostics(self) -> None:
        service, _embedding_db = self.build_semantic_fixture()
        evaluations = (
            ("오프라인 지식 보관", "semantic_local"),
            ("protocol tool interface", "semantic_mcp"),
            ("프로젝트 계획 단계", "semantic_roadmap"),
        )

        hits = 0
        reciprocal_ranks: list[float] = []
        for query, expected_note_id in evaluations:
            with self.subTest(query=query):
                results = service.search_notes(query, limit=3, semantic_mode="required")
                self.assertEqual(results[0].note_id, expected_note_id)
                self.assertIn(expected_note_id, [result.note_id for result in results[:3]])
                self.assertTrue(results[0].retrieval["semantic_used"])
                self.assertEqual(results[0].retrieval["version"], "hybrid-v0.1")
                rank = next(
                    index for index, result in enumerate(results, start=1) if result.note_id == expected_note_id
                )
                hits += int(rank <= 5)
                reciprocal_ranks.append(1.0 / rank)

        self.assertEqual(hits / len(evaluations), 1.0)
        self.assertEqual(sum(reciprocal_ranks) / len(reciprocal_ranks), 1.0)

        filtered = service.search_notes(
            "protocol tool interface",
            note_type="source",
            semantic_mode="required",
        )
        self.assertEqual([result.note_id for result in filtered], ["semantic_mcp"])

        pack = service.build_context_pack(
            "오프라인 지식 보관",
            limit=2,
            token_budget=512,
            semantic_mode="required",
        )
        self.assertEqual(pack.results[0].note_id, "semantic_local")
        self.assertTrue(pack.results[0].retrieval["semantic_used"])
        self.assertLessEqual(pack.budget["estimated_tokens"], 512)

    def test_auto_falls_back_and_required_reports_unavailable(self) -> None:
        self.write_note("note.md", "# Lexical\n\nFallback keyword.")
        self.index()
        service = RetrievalService(self.root, self.db_path)

        off = service.search_notes("Fallback keyword", semantic_mode="off")
        auto = service.search_notes("Fallback keyword", semantic_mode="auto")

        self.assertEqual(off, auto)
        self.assertIsNone(auto[0].retrieval)
        with self.assertRaises(SemanticUnavailableError):
            service.search_notes("Fallback keyword", semantic_mode="required")
        with self.assertRaises(ValueError):
            service.search_notes("Fallback keyword", semantic_mode="invalid")

        missing_index = RetrievalService(
            self.root,
            self.db_path,
            embedding_provider=KeywordTestEmbeddingProvider(),
            embedding_db_path=self.root / ".pkm-index" / "missing.sqlite3",
        )
        self.assertEqual(
            missing_index.search_notes("Fallback keyword", semantic_mode="auto"),
            off,
        )
        with self.assertRaises(SemanticUnavailableError):
            missing_index.search_notes("Fallback keyword", semantic_mode="required")

        failing_provider = StaticEmbeddingProvider(error=RuntimeError("query failed"))
        failing = RetrievalService(
            self.root,
            self.db_path,
            embedding_provider=failing_provider,
            embedding_db_path=self.root / ".pkm-index" / "unused.sqlite3",
        )
        self.assertEqual(failing.search_notes("Fallback keyword", semantic_mode="auto"), off)
        with self.assertRaises(SemanticUnavailableError):
            failing.search_notes("Fallback keyword", semantic_mode="required")

    def test_stale_coverage_falls_back_in_auto_and_fails_when_required(self) -> None:
        note = self.write_note("note.md", "# Local-first\n\nDurable Markdown knowledge.")
        self.index()
        provider = KeywordTestEmbeddingProvider()
        embedding_db = self.root / ".pkm-index" / "semantic.sqlite3"
        EmbeddingIndexBuilder(self.root, provider, embedding_db).build()

        note.write_text("# Local-first\n\nChanged durable Markdown knowledge.", encoding="utf-8")
        self.index()
        service = RetrievalService(
            self.root,
            self.db_path,
            embedding_provider=provider,
            embedding_db_path=embedding_db,
        )

        auto = service.search_notes("Changed durable", semantic_mode="auto")
        self.assertEqual(auto[0].note_id, parse_markdown_file(note, self.root).note_id)
        with self.assertRaises(SemanticUnavailableError):
            service.search_notes("Changed durable", semantic_mode="required")

    def test_incompatible_and_corrupt_indexes_follow_mode_contract(self) -> None:
        self.write_note("note.md", "# Lexical\n\nFallback keyword.")
        self.index()
        embedding_db = self.root / ".pkm-index" / "semantic.sqlite3"
        deterministic = DeterministicTestEmbeddingProvider()
        EmbeddingIndexBuilder(self.root, deterministic, embedding_db).build()

        incompatible = RetrievalService(
            self.root,
            self.db_path,
            embedding_provider=KeywordTestEmbeddingProvider(),
            embedding_db_path=embedding_db,
        )
        self.assertEqual(
            incompatible.search_notes("Fallback keyword", semantic_mode="auto")[0].title,
            "Lexical",
        )
        with self.assertRaises(SemanticUnavailableError):
            incompatible.search_notes("Fallback keyword", semantic_mode="required")

        embedding_db.write_bytes(b"corrupt")
        corrupt = RetrievalService(
            self.root,
            self.db_path,
            embedding_provider=deterministic,
            embedding_db_path=embedding_db,
        )
        self.assertEqual(corrupt.search_notes("Fallback keyword", semantic_mode="auto")[0].title, "Lexical")
        with self.assertRaises(SemanticUnavailableError):
            corrupt.search_notes("Fallback keyword", semantic_mode="required")


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
        self.assertEqual(init_response["result"]["serverInfo"]["version"], "0.3.0a1")
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
        search_tool = next(tool for tool in list_response["result"]["tools"] if tool["name"] == "search_notes")
        self.assertEqual(
            search_tool["inputSchema"]["properties"]["semantic_mode"]["enum"],
            ["off", "auto", "required"],
        )

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

        auto = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "search_notes",
                    "arguments": {"query": "Markdown", "semantic_mode": "auto"},
                },
            },
        )
        self.assertFalse(auto["result"]["isError"])

        required = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {
                    "name": "search_notes",
                    "arguments": {"query": "Markdown", "semantic_mode": "required"},
                },
            },
        )
        self.assertTrue(required["result"]["isError"])
        self.assertEqual(
            required["result"]["structuredContent"]["error"]["code"],
            "semantic_unavailable",
        )

        invalid_mode = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 22,
                "method": "tools/call",
                "params": {
                    "name": "search_notes",
                    "arguments": {"query": "Markdown", "semantic_mode": "sometimes"},
                },
            },
        )
        self.assertTrue(invalid_mode["result"]["isError"])
        self.assertEqual(
            invalid_mode["result"]["structuredContent"]["error"]["code"],
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
