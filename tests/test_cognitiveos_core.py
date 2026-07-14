from __future__ import annotations

import io
import hashlib
import json
import math
import sqlite3
import struct
import sys
import tempfile
import tomllib
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cognitiveos.cli as cognitiveos_cli
import cognitiveos.runtime as cognitiveos_runtime
from cognitiveos import __version__
from cognitiveos.cli import main_embed, main_index, main_search, main_status, main_validate
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
    embed_documents,
    embed_query,
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
from cognitiveos.evaluation import (
    EVALUATION_VERSION,
    evaluate_retrieval,
    load_evaluation_cases,
    mean_reciprocal_rank,
    recall_at_k,
)
from cognitiveos.mcp_server import handle_message, set_fastmcp_server_version
from cognitiveos.models import SearchResult
from cognitiveos.parser import parse_markdown_file
from cognitiveos.retrieval import RetrievalService, estimate_tokens, select_diverse_results
from cognitiveos.runtime import (
    SemanticRuntimeConfig,
    build_runtime_service,
    load_semantic_runtime_config,
)
from cognitiveos.safety import safe_resolve_inside
from cognitiveos.sentence_transformers_adapter import SentenceTransformersProvider
from cognitiveos.sentence_transformers_adapter import APPROVED_MULTILINGUAL_MODEL_ID
from cognitiveos.status import (
    MANIFEST_VERSION,
    STATUS_VERSION,
    build_vault_manifest,
    inspect_vault_status,
)
from cognitiveos.validation import VALIDATION_VERSION, validate_note_file, validate_vault


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
links:
  - "[[Related Note|related]]"
  - related_note_id
  - "[[Related Note|duplicate display]]"
sources:
  - "[Specification](https://example.com/spec)"
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
        self.assertEqual(
            {link.link_type for link in note.links},
            {"wikilink", "markdown", "frontmatter_link", "frontmatter_source"},
        )
        frontmatter_links = [link for link in note.links if link.line is None]
        self.assertEqual(
            [(link.target, link.link_type) for link in frontmatter_links],
            [
                ("Related Note", "frontmatter_link"),
                ("related_note_id", "frontmatter_link"),
                ("https://example.com/spec", "frontmatter_source"),
            ],
        )

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

    def test_versioned_templates_use_distinct_path_derived_runtime_ids(self) -> None:
        first_path = self.write_note(
            "System/templates/v0.1/concept.md",
            """---
id: concept_YYYYMMDD_slug
type: concept
status: seed
---
# Concept title
""",
        )
        second_path = self.write_note(
            "System/templates/v0.2/concept.md",
            """---
id: concept_YYYYMMDD_slug
type: concept
status: seed
---
# Concept title
""",
        )

        first = parse_markdown_file(first_path, self.root)
        second = parse_markdown_file(second_path, self.root)

        self.assertTrue(first.note_id.startswith("note_"))
        self.assertTrue(second.note_id.startswith("note_"))
        self.assertNotEqual(first.note_id, second.note_id)

        self.assertEqual(self.index(), 2)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 2)

    def test_broken_yaml_does_not_fail_parsing(self) -> None:
        path = self.write_note("broken.md", "---\ntitle: [broken\n---\n# Body")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.title, "Body")

    def test_empty_file_is_valid_note(self) -> None:
        path = self.write_note("empty.md", "")
        note = parse_markdown_file(path, self.root)

        self.assertEqual(note.title, "empty")
        self.assertEqual(note.body, "")


class NoteValidationTests(CognitiveOSTestCase):
    def test_valid_capture_report_is_deterministic_and_read_only(self) -> None:
        path = self.write_note(
            "00_Inbox/capture.md",
            """---
type: inbox
status: inbox
created_at: 2026-07-13
---
# Observed indexing question

## Capture

An observation.

## Next

- [ ] Triage this capture.
""",
        )
        before = hashlib.sha256(path.read_bytes()).hexdigest()

        first = validate_vault(self.root)
        second = validate_vault(self.root)

        self.assertEqual(first, second)
        self.assertEqual(first.validation_version, VALIDATION_VERSION)
        self.assertEqual(first.files_scanned, 1)
        self.assertEqual(first.diagnostics, ())
        self.assertEqual(first.exit_code, 0)
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse((self.root / ".pkm-index").exists())

    def test_duplicate_ids_and_invalid_schema_values_are_errors(self) -> None:
        self.write_note(
            "01_Concepts/one.md",
            """---
id: concept_duplicate
type: concept
status: seed
created_at: 2026-07-13
---
# Shared title

PRIVATE BODY CONTENT MUST NOT APPEAR IN DIAGNOSTICS.
""",
        )
        self.write_note(
            "01_Concepts/two.md",
            """---
id: concept_duplicate
type: invalid-kind
status: finished
tags: retrieval
confidence: 1.2
updated_at: July 13
---
# Shared title
""",
        )

        report = validate_vault(self.root)
        codes = [item.code for item in report.diagnostics]

        self.assertEqual(codes.count("duplicate_id"), 2)
        self.assertIn("invalid_type", codes)
        self.assertIn("invalid_status", codes)
        self.assertIn("invalid_field_type", codes)
        self.assertIn("confidence_out_of_range", codes)
        self.assertIn("invalid_date", codes)
        self.assertEqual(report.exit_code, 1)
        self.assertNotIn("PRIVATE BODY CONTENT", json.dumps(report.to_dict()))
        self.assertEqual(
            list(report.diagnostics),
            sorted(report.diagnostics, key=lambda item: (
                {"error": 0, "warning": 1, "info": 2}[item.severity],
                item.path,
                item.line or 0,
                item.code,
                item.field or "",
            )),
        )

    def test_layer_specs_are_valid_system_notes_without_standard_heading_profile(self) -> None:
        path = self.write_note(
            "01_Concepts/__SPECS__.md",
            """---
id: system_spec_concepts
type: system
layer: concepts
purpose: abstract_knowledge
scope: vault-wide
status: active
---
# Concepts

## 1. Purpose

Define the operational contract for this layer.

## 2. What Belongs Here

Reusable concepts belong here.
""",
        )

        state, diagnostics = validate_note_file(path, self.root)
        parsed = parse_markdown_file(path, self.root)

        self.assertEqual(diagnostics, [])
        self.assertEqual(state.effective_id, "system_spec_concepts")
        self.assertEqual(state.effective_type, "system")
        self.assertEqual(parsed.note_id, "system_spec_concepts")
        self.assertEqual(parsed.note_type, "system")

    def test_layer_spec_profile_still_enforces_frontmatter_contract(self) -> None:
        path = self.write_note(
            "01_Concepts/__SPECS__.md",
            """---
id: system_spec_concepts
type: system_readme
status: finished
---
# Concepts

## 1. Purpose
""",
        )

        _state, diagnostics = validate_note_file(path, self.root)
        codes = {item.code for item in diagnostics}

        self.assertIn("invalid_type", codes)
        self.assertIn("invalid_status", codes)

    def test_authoring_warnings_and_relationship_information(self) -> None:
        self.write_note(
            "00_Inbox/active.md",
            """---
type: inbox
title: Frontmatter title
status: active
created_at: 2026-07-13
tags:
  - Knowledge Management
links: [\"[[Related Note]]\"]
sources: [\"[[Source Note]]\"]
visibility: shared
layer: personal
---
# Heading title
""",
        )

        report = validate_vault(self.root)
        codes = {item.code for item in report.diagnostics}

        self.assertIn("lifecycle_inbox_status_mismatch", codes)
        self.assertIn("title_heading_mismatch", codes)
        self.assertIn("tag_domain_noncanonical", codes)
        self.assertNotIn("frontmatter_relationship_not_indexed", codes)
        self.assertIn("visibility_is_not_access_control", codes)
        self.assertNotIn("unknown_field", codes)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(validate_vault(self.root, strict=True).exit_code, 1)

    def test_placeholders_and_broken_frontmatter_are_reported_but_templates_are_exempt(self) -> None:
        self.write_note(
            "01_Concepts/placeholder.md",
            """---
id: concept_YYYYMMDD_slug
type: concept
title: Concept Title
status: seed
created_at: YYYY-MM-DD
updated_at: YYYY-MM-DD
---
# Concept Title
""",
        )
        self.write_note(
            "broken.md",
            """---
title: [broken
---
# Broken
""",
        )
        self.write_note(
            "System/templates/v0.2/concept.md",
            """---
id: concept_YYYYMMDD_slug
type: concept
title: Concept Title
status: seed
created_at: YYYY-MM-DD
updated_at: YYYY-MM-DD
---
# Concept Title
""",
        )
        self.write_note(
            "01_Concepts/copied-v02.md",
            """---
id: concept_20260713_real
type: concept
status: seed
created_at: 2026-07-13
updated_at: 2026-07-13
visibility: private
---
# Concept title
""",
        )

        report = validate_vault(self.root)
        codes_by_path = {}
        for item in report.diagnostics:
            codes_by_path.setdefault(item.path, set()).add(item.code)

        self.assertIn("template_placeholder_present", codes_by_path["01_Concepts/placeholder.md"])
        self.assertIn("template_placeholder_present", codes_by_path["01_Concepts/copied-v02.md"])
        self.assertIn("frontmatter_parse_failed", codes_by_path["broken.md"])
        self.assertNotIn(
            "template_placeholder_present",
            codes_by_path.get("System/templates/v0.2/concept.md", set()),
        )
        self.assertNotIn(
            "invalid_date",
            codes_by_path.get("System/templates/v0.2/concept.md", set()),
        )

    def test_validation_rejects_paths_outside_the_vault(self) -> None:
        outside = self.root.parent / "outside.md"
        with self.assertRaises(ValueError):
            validate_note_file(outside, self.root)
        with self.assertRaisesRegex(ValueError, "scope"):
            validate_vault(self.root, scope="private")

    def test_recommended_headings_and_source_locator_are_diagnosed(self) -> None:
        self.write_note(
            "01_Concepts/incomplete.md",
            """---
id: concept_incomplete
type: concept
status: seed
---
# Incomplete concept

## Definition

Definition only.
""",
        )
        complete_source_sections = """
## Citation

## Summary

## Key Claims

## Extracted Concepts

## Personal Notes
"""
        self.write_note(
            "04_References/missing-locator.md",
            """---
id: source_missing_locator
type: source
status: seed
---
# Missing locator
""" + complete_source_sections,
        )
        self.write_note(
            "04_References/with-locator.md",
            """---
id: source_with_locator
type: source
status: seed
url: https://example.com/source
---
# Source with locator
""" + complete_source_sections,
        )

        report = validate_vault(self.root)
        codes_by_path: dict[str, list[str]] = {}
        for item in report.diagnostics:
            codes_by_path.setdefault(item.path, []).append(item.code)

        self.assertEqual(codes_by_path["01_Concepts/incomplete.md"].count("recommended_heading_missing"), 1)
        concept_diagnostic = next(
            item
            for item in report.diagnostics
            if item.path == "01_Concepts/incomplete.md" and item.code == "recommended_heading_missing"
        )
        self.assertIn("Distinction, Examples, Related, Sources, Open Questions", concept_diagnostic.message)
        self.assertIn("source_locator_missing", codes_by_path["04_References/missing-locator.md"])
        self.assertNotIn("source_locator_missing", codes_by_path.get("04_References/with-locator.md", []))


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

    def test_approved_e5_model_uses_query_and_passage_prefixes(self) -> None:
        encoded: list[list[str]] = []

        class FakeModel:
            def get_sentence_embedding_dimension(self) -> int:
                return 2

            def encode(self, texts: list[str], **_kwargs: object) -> list[list[float]]:
                encoded.append(texts)
                return [[0.6, 0.8] for _text in texts]

        provider = SentenceTransformersProvider(
            APPROVED_MULTILINGUAL_MODEL_ID,
            "deadbeef",
            model_loader=lambda _model_id, **_kwargs: FakeModel(),
        )

        self.assertEqual(embed_query(provider, "검색 질문"), [0.6, 0.8])
        self.assertEqual(embed_documents(provider, ["노트 근거"]), [[0.6, 0.8]])
        self.assertEqual(encoded, [["query: 검색 질문"], ["passage: 노트 근거"]])

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


class EmbeddingProviderValidationTests(unittest.TestCase):
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


class EmbeddingEvaluationTests(CognitiveOSTestCase):
    def test_metric_calculation(self) -> None:
        rankings = [["a", "b"], ["x", "c"]]
        relevant = [("a",), ("c",)]

        self.assertEqual(recall_at_k(rankings, relevant, 1), 0.5)
        self.assertEqual(recall_at_k(rankings, relevant, 2), 1.0)
        self.assertEqual(mean_reciprocal_rank(rankings, relevant), 0.75)

    def test_fixture_validation_and_end_to_end_report(self) -> None:
        cases_path = Path(__file__).resolve().parents[1] / "System" / "evaluation" / (
            "multilingual-retrieval-v0.3.json"
        )
        cases = load_evaluation_cases(cases_path)

        self.assertEqual(len(cases), 6)
        self.assertEqual({case.language for case in cases}, {"ko", "en", "mixed"})
        report = evaluate_retrieval(
            FIXTURES / "semantic_vault",
            KeywordTestEmbeddingProvider(),
            cases,
            self.root / "evaluation",
        )

        self.assertEqual(report["evaluation_version"], EVALUATION_VERSION)
        self.assertEqual(report["corpus"]["note_count"], 3)
        self.assertGreater(report["corpus"]["embedding_index_bytes"], 0)
        self.assertEqual(report["metrics"]["hybrid_recall_at_5"], 1.0)
        self.assertEqual(report["metrics"]["hybrid_mrr"], 1.0)
        self.assertTrue(report["gates"]["all_passed"])
        self.assertEqual(len(report["cases"]), 6)

    def test_invalid_fixture_is_rejected(self) -> None:
        invalid = self.write_note("invalid.json", json.dumps({"version": "wrong", "cases": []}))
        with self.assertRaisesRegex(ValueError, "fixture version"):
            load_evaluation_cases(invalid)


class SemanticRuntimeConfigTests(CognitiveOSTestCase):
    def test_runtime_is_off_by_default_without_loading_provider(self) -> None:
        config = load_semantic_runtime_config({})

        self.assertEqual(config, SemanticRuntimeConfig())
        with patch.object(cognitiveos_runtime, "create_runtime_provider") as create_provider:
            service = build_runtime_service(self.root, self.db_path, environ={})
        create_provider.assert_not_called()
        self.assertIsNone(service.embedding_provider)

    def test_local_runtime_requires_and_preserves_exact_identity(self) -> None:
        values = {
            "COGNITIVEOS_SEMANTIC_RUNTIME": "local",
            "COGNITIVEOS_EMBEDDING_PROVIDER": "sentence-transformers",
            "COGNITIVEOS_EMBEDDING_MODEL": "intfloat/multilingual-e5-small",
            "COGNITIVEOS_EMBEDDING_REVISION": "deadbeef",
            "COGNITIVEOS_EMBEDDING_DEVICE": "cpu",
            "COGNITIVEOS_EMBEDDING_DB_PATH": "/tmp/embeddings.sqlite3",
        }

        config = load_semantic_runtime_config(values)

        self.assertTrue(config.enabled)
        self.assertEqual(config.model_revision, "deadbeef")
        self.assertEqual(config.embedding_db_path, "/tmp/embeddings.sqlite3")
        with self.assertRaisesRegex(ValueError, "COGNITIVEOS_EMBEDDING_MODEL"):
            load_semantic_runtime_config(
                {
                    "COGNITIVEOS_SEMANTIC_RUNTIME": "local",
                    "COGNITIVEOS_EMBEDDING_PROVIDER": "sentence-transformers",
                }
            )
        with self.assertRaisesRegex(ValueError, "must be off or local"):
            load_semantic_runtime_config({"COGNITIVEOS_SEMANTIC_RUNTIME": "automatic"})

    def test_runtime_load_failure_keeps_lexical_and_required_reports_unavailable(self) -> None:
        self.write_note("note.md", "# Fallback keyword\n\nDurable lexical evidence.")
        self.index()
        values = {
            "COGNITIVEOS_SEMANTIC_RUNTIME": "local",
            "COGNITIVEOS_EMBEDDING_PROVIDER": "sentence-transformers",
            "COGNITIVEOS_EMBEDDING_MODEL": "missing/model",
            "COGNITIVEOS_EMBEDDING_REVISION": "deadbeef",
        }
        stderr = io.StringIO()
        with patch.object(
            cognitiveos_runtime,
            "create_runtime_provider",
            side_effect=EmbeddingConfigurationError("private backend detail"),
        ), redirect_stderr(stderr):
            service = build_runtime_service(self.root, self.db_path, environ=values)

        self.assertEqual(service.search_notes("Fallback keyword", semantic_mode="auto")[0].title, "Fallback keyword")
        with self.assertRaisesRegex(SemanticUnavailableError, "configuration or model loading failed"):
            service.search_notes("Fallback keyword", semantic_mode="required")
        self.assertNotIn("private backend detail", stderr.getvalue())

    def test_runtime_provider_enables_required_semantic_search(self) -> None:
        fixture_root = FIXTURES / "semantic_vault"
        lexical_db = self.root / "lexical.sqlite3"
        embedding_db = self.root / "embeddings.sqlite3"
        with VaultIndex(lexical_db) as index:
            index.index_vault(fixture_root)
        provider = KeywordTestEmbeddingProvider()
        EmbeddingIndexBuilder(fixture_root, provider, embedding_db).build()
        values = {
            "COGNITIVEOS_SEMANTIC_RUNTIME": "local",
            "COGNITIVEOS_EMBEDDING_PROVIDER": "sentence-transformers",
            "COGNITIVEOS_EMBEDDING_MODEL": "intfloat/multilingual-e5-small",
            "COGNITIVEOS_EMBEDDING_REVISION": "deadbeef",
            "COGNITIVEOS_EMBEDDING_DB_PATH": str(embedding_db),
        }
        with patch.object(cognitiveos_runtime, "create_runtime_provider", return_value=provider):
            service = build_runtime_service(fixture_root, lexical_db, environ=values)

        results = service.search_notes("오프라인 지식 보관", semantic_mode="required")
        self.assertEqual(results[0].note_id, "semantic_local")
        self.assertTrue(results[0].retrieval["semantic_used"])


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

        with closing(sqlite3.connect(self.embedding_db_path)) as conn:
            conn.execute("UPDATE embedding_chunks SET vector = ?", (b"broken",))
            conn.commit()
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
    def test_atomic_full_build_records_manifest_and_statistics(self) -> None:
        self.write_note("alpha.md", "# Alpha\n\nEvidence")
        self.write_note("nested/한글.md", "# 한글\n\n근거")

        with VaultIndex(self.db_path) as index:
            result = index.build_vault(self.root)

        self.assertEqual(result.mode, "full")
        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.added_count, 2)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(result.removed_count, 0)
        self.assertEqual(result.reused_count, 0)
        self.assertEqual(result.note_count, 2)
        self.assertEqual(result.fts_count, 2)
        self.assertEqual(result.manifest_digest, build_vault_manifest(self.root).digest)
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            run = conn.execute("SELECT * FROM index_runs ORDER BY run_id DESC LIMIT 1").fetchone()
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["mode"], "full")
            self.assertEqual(run["generation"], result.generation)
            self.assertEqual(run["manifest_version"], MANIFEST_VERSION)
            self.assertEqual(run["manifest_digest"], result.manifest_digest)
            self.assertEqual(run["scanned_count"], 2)
            self.assertEqual(run["added_count"], 2)
            self.assertEqual(run["note_count"], 2)
            self.assertEqual(run["fts_count"], 2)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        status = inspect_vault_status(self.root, db_path=self.db_path)
        self.assertEqual(status.lexical["state"], "healthy")
        self.assertEqual(status.lexical["mode"], "full")
        self.assertEqual(status.lexical["generation"], result.generation)
        self.assertEqual(status.lexical["added_count"], 2)

    def test_first_parser_failure_leaves_no_active_database(self) -> None:
        self.write_note("note.md", "# Note\n\nEvidence")

        with patch(
            "cognitiveos.indexer.parse_markdown_file",
            side_effect=RuntimeError("injected parser failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected parser failure"):
                with VaultIndex(self.db_path) as index:
                    index.index_vault(self.root)

        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())

    def test_validation_and_publish_failures_preserve_active_database(self) -> None:
        note = self.write_note("note.md", "# Note\n\nInitial")
        self.index()
        original = self.db_path.read_bytes()
        note.write_text("# Note\n\nChanged", encoding="utf-8")

        with patch(
            "cognitiveos.indexer.validate_lexical_index",
            side_effect=ValueError("injected validation failure"),
        ):
            with self.assertRaisesRegex(ValueError, "injected validation failure"):
                self.index()
        self.assertEqual(self.db_path.read_bytes(), original)
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())

        with patch(
            "cognitiveos.indexer.os.replace",
            side_effect=OSError("injected publish failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected publish failure"):
                self.index()
        self.assertEqual(self.db_path.read_bytes(), original)
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())

    def test_source_change_during_build_preserves_active_database(self) -> None:
        note_path = self.write_note("note.md", "# Note\n\nInitial")
        self.index()
        original_database = self.db_path.read_bytes()
        original_parser = parse_markdown_file

        def parse_then_change(path: str | Path, root: str | Path):
            note = original_parser(path, root)
            note_path.write_text("# Note\n\nChanged during build", encoding="utf-8")
            return note

        with patch("cognitiveos.indexer.parse_markdown_file", side_effect=parse_then_change):
            with self.assertRaisesRegex(RuntimeError, "source set changed"):
                self.index()

        self.assertEqual(self.db_path.read_bytes(), original_database)
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())

    def test_active_wal_blocks_publication_and_preserves_database(self) -> None:
        self.write_note("note.md", "# Note\n\nEvidence")
        self.index()
        original_database = self.db_path.read_bytes()
        Path(f"{self.db_path}-wal").write_bytes(b"active-wal")

        with self.assertRaisesRegex(RuntimeError, "active WAL"):
            self.index()

        self.assertEqual(self.db_path.read_bytes(), original_database)
        self.assertFalse(self.db_path.with_name(f".{self.db_path.name}.tmp").exists())

    def test_skips_local_runtime_directories(self) -> None:
        self.write_note("note.md", "# Durable note")
        self.write_note(".venv/lib/package/LICENSE.md", "# Package license")
        self.write_note(".venv-embeddings/lib/package/README.md", "# Runtime readme")
        self.write_note(".venv-embeddings312/lib/package/NOTICE.md", "# Runtime notice")
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
    def test_graph_adjacency_cache_hits_and_invalidates_after_reindex(self) -> None:
        self.write_note(
            "source.md",
            """---
id: cache_source
type: project
title: Cache Source
links:
  - first_target
---
# Cache Source
""",
        )
        self.write_note("first.md", "---\nid: first_target\ntype: concept\ntitle: First\n---\n# First")
        self.index()
        service = RetrievalService(self.root, self.db_path)

        with patch.object(
            service,
            "_build_graph_adjacency",
            wraps=service._build_graph_adjacency,
        ) as build_graph:
            first = service._graph_adjacency()
            second = service._graph_adjacency()
            self.assertIs(first, second)
            self.assertEqual(build_graph.call_count, 1)

            self.write_note("second.md", "---\nid: second_target\ntype: concept\ntitle: Second\n---\n# Second")
            self.write_note(
                "source.md",
                """---
id: cache_source
type: project
title: Cache Source
links:
  - second_target
---
# Cache Source
""",
            )
            self.index()
            rebuilt = service._graph_adjacency()

        self.assertIsNot(first, rebuilt)
        self.assertEqual(build_graph.call_count, 2)
        self.assertIn("second_target", rebuilt["cache_source"])
        self.assertNotIn("first_target", rebuilt["cache_source"])

        other_service = RetrievalService(self.root, self.db_path)
        other = other_service._graph_adjacency()
        self.assertIsNot(rebuilt, other)
        self.assertEqual(rebuilt, other)

    def test_graph_cache_detects_same_size_direct_link_mutation(self) -> None:
        self.write_note(
            "source.md",
            """---
id: direct_source
type: project
title: Direct Source
links:
  - target_a
---
# Direct Source
""",
        )
        self.write_note("a.md", "---\nid: target_a\ntype: concept\ntitle: A\n---\n# A")
        self.write_note("b.md", "---\nid: target_b\ntype: concept\ntitle: B\n---\n# B")
        self.index()
        service = RetrievalService(self.root, self.db_path)
        first = service._graph_adjacency()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE links SET target = ? WHERE source_note_id = ?",
                ("target_b", "direct_source"),
            )
            conn.commit()

        second = service._graph_adjacency()

        self.assertIsNot(first, second)
        self.assertIn("target_b", second["direct_source"])
        self.assertNotIn("target_a", second["direct_source"])

    def test_graph_cache_detects_wal_link_mutation(self) -> None:
        self.write_note(
            "source.md",
            """---
id: wal_source
type: project
title: WAL Source
links:
  - wal_target_a
---
# WAL Source
""",
        )
        self.write_note("a.md", "---\nid: wal_target_a\ntype: concept\ntitle: A\n---\n# A")
        self.write_note("b.md", "---\nid: wal_target_b\ntype: concept\ntitle: B\n---\n# B")
        self.index()
        service = RetrievalService(self.root, self.db_path)
        first = service._graph_adjacency()

        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            conn.execute(
                "UPDATE links SET target = ? WHERE source_note_id = ?",
                ("wal_target_b", "wal_source"),
            )
            conn.commit()
            second = service._graph_adjacency()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        self.assertIsNot(first, second)
        self.assertIn("wal_target_b", second["wal_source"])
        self.assertNotIn("wal_target_a", second["wal_source"])

    def test_graph_resolution_prefers_exact_id_over_alias_collision(self) -> None:
        self.write_note(
            "exact.md",
            """---
id: shared_identity
type: concept
title: Exact Identity Target
status: evergreen
---
# Exact Identity Target
""",
        )
        self.write_note(
            "alias.md",
            """---
id: alias_collision
type: concept
title: Alias Collision
aliases:
  - shared_identity
status: evergreen
---
# Alias Collision
""",
        )
        self.write_note(
            "source.md",
            """---
id: collision_source
type: project
title: Collision Source
status: active
links:
  - shared_identity
---
# Collision Source
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        adjacency = service._graph_adjacency()

        self.assertIn("shared_identity", adjacency["collision_source"])
        self.assertNotIn("alias_collision", adjacency["collision_source"])
        self.assertEqual(
            [item["note_id"] for item in service.get_backlinks("shared_identity")],
            ["collision_source"],
        )

    def test_graph_resolution_rejects_ambiguous_alias_targets(self) -> None:
        for note_id, title in (("first_target", "First Target"), ("second_target", "Second Target")):
            self.write_note(
                f"{note_id}.md",
                f"""---
id: {note_id}
type: concept
title: {title}
aliases:
  - Shared Alias
status: evergreen
---
# {title}
""",
            )
        self.write_note(
            "source.md",
            """---
id: ambiguous_source
type: project
title: Ambiguous Source
status: active
links:
  - Shared Alias
---
# Ambiguous Source
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        adjacency = service._graph_adjacency()

        self.assertNotIn("ambiguous_source", adjacency)
        self.assertEqual(service.get_backlinks("first_target"), [])
        self.assertEqual(service.get_backlinks("second_target"), [])

    def test_related_notes_prioritize_outgoing_then_incoming_graph_edges(self) -> None:
        self.write_note(
            "anchor.md",
            """---
id: graph_anchor
type: project
title: Graph Anchor
status: active
links:
  - outgoing_target
---
# Graph Anchor

Anchor terminology for lexical matching.
""",
        )
        self.write_note(
            "outgoing.md",
            """---
id: outgoing_target
type: source
title: Unrelated Outgoing Source
status: evergreen
---
# Unrelated Outgoing Source

Explicitly connected evidence.
""",
        )
        self.write_note(
            "incoming.md",
            """---
id: incoming_source
type: concept
title: Incoming Concept
status: active
links:
  - graph_anchor
---
# Incoming Concept

Points back to the anchor.
""",
        )
        self.write_note(
            "lexical.md",
            """---
id: lexical_only
type: concept
title: Graph Anchor Terminology
status: active
---
# Graph Anchor Terminology

Graph Anchor terminology appears repeatedly without an explicit edge.
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        related = service.get_related_notes("graph_anchor", limit=4)

        self.assertEqual([item["note_id"] for item in related[:2]], ["outgoing_target", "incoming_source"])
        self.assertEqual(related[0]["retrieval"]["directions"], ["outgoing"])
        self.assertEqual(related[0]["retrieval"]["edge_types"], ["frontmatter_link"])
        self.assertEqual(related[1]["retrieval"]["directions"], ["incoming"])
        self.assertGreater(
            related[0]["retrieval"]["graph_score"],
            related[1]["retrieval"]["graph_score"],
        )
        self.assertIn("lexical_only", [item["note_id"] for item in related])

    def test_context_pack_prefers_graph_connected_source_within_type(self) -> None:
        self.write_note(
            "anchor.md",
            """---
id: context_anchor
type: project
title: Graph Context
status: active
sources:
  - connected_source
---
# Graph Context

Graph context evidence selection.
""",
        )
        self.write_note(
            "unconnected.md",
            """---
id: unconnected_source
type: source
title: Graph Context Lexical Source
status: evergreen
---
# Graph Context Lexical Source

Graph context graph context graph context lexical evidence.
""",
        )
        self.write_note(
            "connected.md",
            """---
id: connected_source
type: source
title: Connected Evidence
status: evergreen
---
# Connected Evidence

Graph context evidence connected explicitly.
""",
        )
        self.index()
        service = RetrievalService(self.root, self.db_path)

        pack = service.build_context_pack("Graph Context", limit=2, token_budget=4000)

        self.assertEqual([item.note_id for item in pack.results], ["context_anchor", "connected_source"])
        self.assertEqual(pack.stats["selection_version"], "type-diverse-graph-v0.1")
        self.assertEqual(pack.stats["graph_edge_count"], 1)
        self.assertEqual(pack.stats["graph_connected_source_count"], 2)
        source_by_id = {source["note_id"]: source for source in pack.sources}
        self.assertEqual(
            source_by_id["context_anchor"]["selection"]["graph_connected_to"],
            ["connected_source"],
        )
        self.assertEqual(
            source_by_id["connected_source"]["selection"]["graph_edge_types"],
            ["frontmatter_source"],
        )

    def test_frontmatter_relationships_are_indexed_as_graph_edges(self) -> None:
        self.write_note(
            "spec.md",
            """---
id: source_spec
type: source
title: Retrieval Specification
aliases:
  - Retrieval Spec
status: evergreen
---
# Retrieval Specification

Defines deterministic retrieval behavior.
""",
        )
        self.write_note(
            "project.md",
            """---
id: project_search
type: project
title: Search Project
status: active
links:
  - "[[Retrieval Spec]]"
  - source_spec
sources:
  - "[[Retrieval Specification]]"
  - "[External](https://example.com/spec)"
---
# Search Project

Implements deterministic retrieval behavior.
""",
        )

        self.assertEqual(self.index(), 2)
        service = RetrievalService(self.root, self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT target, link_type, line
                FROM links
                WHERE source_note_id = ?
                ORDER BY link_type, target
                """,
                ("project_search",),
            ).fetchall()
        self.assertEqual(
            rows,
            [
                ("Retrieval Spec", "frontmatter_link", None),
                ("source_spec", "frontmatter_link", None),
                ("Retrieval Specification", "frontmatter_source", None),
                ("https://example.com/spec", "frontmatter_source", None),
            ],
        )
        note = service.read_note(note_id="project_search")
        self.assertEqual(len(note["links"]), 4)
        backlinks = service.get_backlinks("source_spec")
        self.assertEqual([item["note_id"] for item in backlinks], ["project_search"])
        suggestions = service.suggest_links("project_search")
        self.assertNotIn("source_spec", [item["note_id"] for item in suggestions])
        self.assertEqual(self.index(), 2)

    def test_aliases_are_searchable_backlink_targets_and_existing_links(self) -> None:
        self.write_note(
            "concept.md",
            """---
id: concept_rag
type: concept
title: Retrieval Augmented Generation
aliases:
  - RAG
  - 검색 증강 생성
status: evergreen
---
# Retrieval Augmented Generation

Combines retrieval with generation.
""",
        )
        self.write_note(
            "reference.md",
            """---
id: alias_reference
type: source
title: Alias Reference
status: active
---
# Alias Reference

This note links to [[RAG]].
""",
        )
        self.assertEqual(self.index(), 2)
        self.assertEqual(self.index(), 2)
        service = RetrievalService(self.root, self.db_path)

        english = service.search_notes("RAG", limit=5)
        korean = service.search_notes("검색 증강 생성", limit=5)

        self.assertEqual(english[0].note_id, "concept_rag")
        self.assertEqual(korean[0].note_id, "concept_rag")
        self.assertGreaterEqual(english[0].score, 10.0)
        backlinks = service.get_backlinks("concept_rag")
        self.assertEqual([item["note_id"] for item in backlinks], ["alias_reference"])
        suggestions = service.suggest_links("alias_reference")
        self.assertNotIn("concept_rag", [item["note_id"] for item in suggestions])
        with closing(sqlite3.connect(self.db_path)) as conn:
            fts_title = conn.execute(
                "SELECT title FROM fts_notes WHERE note_id = ?",
                ("concept_rag",),
            ).fetchone()[0]
        self.assertEqual(
            fts_title.splitlines(),
            ["Retrieval Augmented Generation", "RAG", "검색 증강 생성"],
        )
        self.write_note(
            "acronym.md",
            """---
id: exact_rag
type: concept
title: RAG
status: seed
---
# RAG

An exact-title note.
""",
        )
        self.assertEqual(self.index(), 3)
        self.assertEqual(service.search_notes("RAG", limit=5)[0].note_id, "exact_rag")

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
    def test_fastmcp_stdio_server_uses_cognitiveos_package_version(self) -> None:
        server = SimpleNamespace(version=None)
        fastmcp = SimpleNamespace(_mcp_server=server)

        set_fastmcp_server_version(fastmcp)

        self.assertEqual(server.version, __version__)

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
        self.assertEqual(init_response["result"]["serverInfo"]["version"], __version__)
        self.assertIn("tools", init_response["result"]["capabilities"])

        list_response = handle_message(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
        self.assertEqual(len(tool_names), 9)
        self.assertTrue(
            tool_names.isdisjoint(
                {"create_draft_note", "update_properties", "append_to_daily", "apply_patch_to_note"}
            )
        )
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

    def test_package_pyproject_and_mcp_versions_match(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        service = RetrievalService(self.root, self.db_path)
        initialized = handle_message(
            service,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )

        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(initialized["result"]["serverInfo"]["version"], __version__)

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
            [
                "cognitiveos-index",
                str(self.root),
                "--db",
                str(self.db_path),
                "--mode",
                "full",
                "--format",
                "json",
            ],
        ), redirect_stdout(json_output):
            main_index()
        index_payload = json.loads(json_output.getvalue())
        self.assertEqual(index_payload["indexed_notes"], 1)
        self.assertEqual(index_payload["index_path"], str(self.db_path))
        self.assertEqual(index_payload["mode"], "full")
        self.assertEqual(index_payload["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(index_payload["scanned_count"], 1)
        self.assertEqual(index_payload["added_count"], 1)

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

    def test_validate_cli_supports_text_json_scope_and_strict_exit_codes(self) -> None:
        self.write_note(
            "00_Inbox/capture.md",
            """---
type: inbox
status: inbox
created_at: 2026-07-13
---
# Capture

## Capture

Observation.

## Next

- [ ] Triage.
""",
        )
        text_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(self.root), "--format", "text"],
        ), redirect_stdout(text_output):
            exit_code = main_validate()
        self.assertEqual(exit_code, 0)
        self.assertIn("note-contract-v0.2", text_output.getvalue())
        self.assertIn("files=1 errors=0 warnings=0 info=0", text_output.getvalue())
        self.assertFalse((self.root / ".pkm-index").exists())

        self.write_note(
            "01_Concepts/invalid.md",
            """---
id: duplicated
type: invalid
status: finished
---
# Invalid
""",
        )
        json_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(self.root), "--format", "json"],
        ), redirect_stdout(json_output):
            exit_code = main_validate()
        payload = json.loads(json_output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["validation_version"], "note-contract-v0.2")
        self.assertGreaterEqual(payload["summary"]["errors"], 2)
        self.assertTrue(all(not item["path"].startswith("/") for item in payload["diagnostics"]))

        warning_root = self.root / "warning-only"
        warning_root.mkdir()
        (warning_root / "note.md").write_text(
            "---\ntype: inbox\nstatus: active\n---\n# Warning\n",
            encoding="utf-8",
        )
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(warning_root), "--strict"],
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(main_validate(), 1)
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(warning_root), "--scope", "private"],
        ), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as context:
                main_validate()
        self.assertEqual(context.exception.code, 2)

    def test_validate_cli_user_scope_excludes_system_authoring_warnings(self) -> None:
        self.write_note(
            "System/docs/concept.md",
            """---
type: concept
status: seed
---
# System-scoped concept

## Definition
## Distinction
## Examples
## Related
## Sources
## Open Questions
""",
        )

        user_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(self.root), "--scope", "user", "--format", "json"],
        ), redirect_stdout(user_output):
            self.assertEqual(main_validate(), 0)
        self.assertEqual(json.loads(user_output.getvalue())["summary"]["warnings"], 0)

        all_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["cognitiveos-validate", str(self.root), "--scope", "all", "--format", "json"],
        ), redirect_stdout(all_output):
            self.assertEqual(main_validate(), 0)
        all_payload = json.loads(all_output.getvalue())
        self.assertEqual(all_payload["summary"]["warnings"], 1)
        self.assertEqual(all_payload["diagnostics"][0]["code"], "durable_id_missing")

    def test_v02_templates_are_validator_compatible(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "System" / "templates" / "v0.2"
        template_names = sorted(path.name for path in source_root.glob("*.md"))
        self.assertEqual(
            template_names,
            [
                "concept.md",
                "entity.md",
                "inbox.md",
                "journal.md",
                "map.md",
                "output.md",
                "project.md",
                "source.md",
                "system.md",
            ],
        )
        for name in template_names:
            self.write_note(
                f"System/templates/v0.2/{name}",
                (source_root / name).read_text(encoding="utf-8"),
            )

        report = validate_vault(self.root, scope="all")

        self.assertEqual(report.error_count, 0)
        self.assertEqual(report.warning_count, 0)
        self.assertEqual(report.info_count, 0)
        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            pyproject["project"]["scripts"]["cognitiveos-validate"],
            "cognitiveos.cli:main_validate",
        )


class VaultStatusTests(CognitiveOSTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedding_db_path = self.root / ".pkm-index" / "embeddings.sqlite3"

    def test_manifest_is_deterministic_and_content_sensitive(self) -> None:
        second = self.write_note("zeta/한글.md", "# 한글\n\n내용")
        self.write_note("Alpha.md", "# Alpha\n\nEvidence")

        first = build_vault_manifest(self.root)
        repeated = build_vault_manifest(self.root)

        self.assertEqual(first.manifest_version, MANIFEST_VERSION)
        self.assertEqual(first.digest, repeated.digest)
        self.assertEqual([item.path for item in first.records], ["Alpha.md", "zeta/한글.md"])
        second.write_text("# 한글\n\n변경된 내용", encoding="utf-8")
        self.assertNotEqual(first.digest, build_vault_manifest(self.root).digest)

    def test_missing_status_is_read_only_and_redacted(self) -> None:
        self.write_note("note.md", "# Note\n\nEvidence")
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))

        status = inspect_vault_status(self.root)

        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        payload = status.to_dict()
        self.assertEqual(before, after)
        self.assertFalse((self.root / ".pkm-index").exists())
        self.assertEqual(status.status_version, STATUS_VERSION)
        self.assertEqual(status.overall_state, "unavailable")
        self.assertEqual(status.lexical["state"], "missing")
        self.assertEqual(status.embedding["state"], "missing")
        self.assertEqual(
            payload["safety"],
            {
                "read_only": True,
                "index_created": False,
                "model_loaded": False,
                "network_used": False,
            },
        )
        self.assertNotIn(str(self.root), json.dumps(payload))

    def test_healthy_stale_and_incomplete_coverage_states(self) -> None:
        note = self.write_note("note.md", "# Note\n\nInitial evidence")
        self.index()
        EmbeddingIndexBuilder(
            self.root,
            DeterministicTestEmbeddingProvider(),
            self.embedding_db_path,
        ).build()
        lexical_before = self.db_path.read_bytes()
        embedding_before = self.embedding_db_path.read_bytes()

        healthy = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )

        self.assertEqual(healthy.overall_state, "healthy")
        self.assertEqual(healthy.lexical["state"], "healthy")
        self.assertEqual(healthy.embedding["state"], "healthy")
        self.assertEqual(self.db_path.read_bytes(), lexical_before)
        self.assertEqual(self.embedding_db_path.read_bytes(), embedding_before)

        note.write_text("# Note\n\nChanged evidence", encoding="utf-8")
        stale = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(stale.overall_state, "degraded")
        self.assertEqual(stale.lexical["state"], "stale")
        self.assertEqual(stale.embedding["state"], "stale")

        self.write_note("added.md", "# Added\n\nNew evidence")
        incomplete = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(incomplete.lexical["state"], "stale")
        self.assertEqual(incomplete.embedding["state"], "incomplete")

    def test_corrupt_and_incompatible_indexes_are_distinguished(self) -> None:
        self.write_note("note.md", "# Note\n\nEvidence")
        self.index()
        EmbeddingIndexBuilder(
            self.root,
            DeterministicTestEmbeddingProvider(),
            self.embedding_db_path,
        ).build()
        with closing(sqlite3.connect(self.embedding_db_path)) as conn:
            conn.execute("UPDATE embedding_chunks SET provider_id = 'different'")
            conn.commit()

        incompatible = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(incompatible.embedding["state"], "incompatible")

        with closing(sqlite3.connect(self.embedding_db_path)) as conn:
            conn.execute("UPDATE embedding_chunks SET provider_id = 'test', vector = ?", (b"broken",))
            conn.commit()
        embedding_corrupt = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(embedding_corrupt.embedding["state"], "corrupt")

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DELETE FROM fts_notes")
            conn.commit()
        incomplete = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(incomplete.lexical["state"], "incomplete")

        self.db_path.write_bytes(b"not sqlite")
        corrupt = inspect_vault_status(
            self.root,
            db_path=self.db_path,
            embedding_db_path=self.embedding_db_path,
        )
        self.assertEqual(corrupt.overall_state, "unavailable")
        self.assertEqual(corrupt.lexical["state"], "corrupt")

    def test_status_cli_supports_deterministic_text_and_json(self) -> None:
        self.write_note("note.md", "# Note\n\nEvidence")
        self.index()

        json_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "cognitiveos-status",
                str(self.root),
                "--db",
                str(self.db_path),
                "--embedding-db",
                str(self.embedding_db_path),
                "--format",
                "json",
            ],
        ), redirect_stdout(json_output):
            self.assertEqual(main_status(), 0)
        payload = json.loads(json_output.getvalue())
        self.assertEqual(payload["status_version"], STATUS_VERSION)
        self.assertEqual(payload["overall_state"], "healthy")
        self.assertEqual(payload["embedding"]["state"], "missing")

        text_output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "cognitiveos-status",
                str(self.root),
                "--db",
                str(self.db_path),
                "--format",
                "text",
            ],
        ), redirect_stdout(text_output):
            self.assertEqual(main_status(), 0)
        self.assertIn("vault-status-v0.1", text_output.getvalue())
        self.assertIn("overall=healthy", text_output.getvalue())
        self.assertEqual(
            tomllib.loads(
                (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                    encoding="utf-8"
                )
            )["project"]["scripts"]["cognitiveos-status"],
            "cognitiveos.cli:main_status",
        )


if __name__ == "__main__":
    unittest.main()
