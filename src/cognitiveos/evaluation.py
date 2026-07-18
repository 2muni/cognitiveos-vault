from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .embedding_index import EmbeddingIndexBuilder
from .embeddings import EmbeddingProvider, provider_identity
from .indexer import VaultIndex
from .retrieval import RetrievalService, search_result_to_dict
from .sentence_transformers_adapter import (
    APPROVED_MULTILINGUAL_MODEL_ID,
    APPROVED_MULTILINGUAL_MODEL_REVISION,
    SentenceTransformersProvider,
)


EVALUATION_VERSION = "multilingual-retrieval-v0.1"
RETRIEVAL_QUALITY_FIXTURE_VERSION = "retrieval-quality-v0.7"
RETRIEVAL_QUALITY_SIGNALS = frozenset(
    {
        "aliases",
        "backlinks",
        "graph_evidence",
        "headings",
        "recency",
        "title",
        "typed_links",
    }
)


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    relevant_note_ids: tuple[str, ...]
    language: str
    case_id: str | None = None
    signals: tuple[str, ...] = ()
    relevant_paths: tuple[str, ...] = ()
    fixture_version: str = EVALUATION_VERSION


def load_evaluation_cases(path: str | Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") not in {
        EVALUATION_VERSION,
        RETRIEVAL_QUALITY_FIXTURE_VERSION,
    }:
        raise ValueError(
            "evaluation fixture version must be "
            f"{EVALUATION_VERSION} or {RETRIEVAL_QUALITY_FIXTURE_VERSION}"
        )
    fixture_version = payload["version"]
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("evaluation fixture must contain a non-empty cases list")
    cases: list[EvaluationCase] = []
    seen_case_ids: set[str] = set()
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise ValueError(f"cases[{index}] must be an object")
        query = item.get("query")
        language = item.get("language")
        relevant = item.get("relevant_note_ids")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"cases[{index}].query must be a non-empty string")
        if not isinstance(language, str) or not language.strip():
            raise ValueError(f"cases[{index}].language must be a non-empty string")
        if (
            not isinstance(relevant, list)
            or not relevant
            or any(not isinstance(note_id, str) or not note_id.strip() for note_id in relevant)
        ):
            raise ValueError(f"cases[{index}].relevant_note_ids must contain note ids")
        if fixture_version == RETRIEVAL_QUALITY_FIXTURE_VERSION:
            case_id = item.get("id")
            signals = item.get("signals")
            relevant_paths = item.get("relevant_paths")
            if not isinstance(case_id, str) or not case_id.strip():
                raise ValueError(f"cases[{index}].id must be a non-empty string")
            case_id = case_id.strip()
            if case_id in seen_case_ids:
                raise ValueError(f"cases[{index}].id duplicates {case_id!r}")
            seen_case_ids.add(case_id)
            if not isinstance(signals, list) or not signals or any(
                not isinstance(signal, str) or not signal.strip() for signal in signals
            ):
                raise ValueError(f"cases[{index}].signals must contain known signals")
            normalized_signals = tuple(signal.strip() for signal in signals)
            unknown_signals = sorted(set(normalized_signals).difference(RETRIEVAL_QUALITY_SIGNALS))
            if unknown_signals:
                raise ValueError(f"cases[{index}].signals contains unknown signals: {unknown_signals}")
            if not isinstance(relevant_paths, list) or not relevant_paths:
                raise ValueError(f"cases[{index}].relevant_paths must contain vault-relative paths")
            normalized_paths = tuple(
                validate_fixture_path(candidate, f"cases[{index}].relevant_paths")
                for candidate in relevant_paths
            )
        else:
            case_id = None
            normalized_signals = ()
            normalized_paths = ()
        cases.append(
            EvaluationCase(
                query.strip(),
                tuple(relevant),
                language.strip(),
                case_id,
                normalized_signals,
                normalized_paths,
                fixture_version,
            )
        )
    return cases


def validate_fixture_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain vault-relative paths")
    path = value.strip()
    normalized = PurePosixPath(path)
    if (
        path.startswith(("/", "\\"))
        or "\\" in path
        or normalized.is_absolute()
        or normalized.as_posix() != path
        or not normalized.parts
        or any(part in {"", ".", ".."} for part in normalized.parts)
        or ":" in normalized.parts[0]
        or normalized.suffix != ".md"
    ):
        raise ValueError(f"{field} must contain vault-relative paths")
    return path


def evaluate_retrieval(
    vault_root: str | Path,
    provider: EmbeddingProvider,
    cases: Sequence[EvaluationCase],
    work_dir: str | Path,
    *,
    k: int = 5,
    min_hybrid_recall: float = 1.0,
    min_hybrid_mrr: float = 0.8,
    model_load_seconds: float | None = None,
    diagnostics: bool = False,
) -> dict[str, Any]:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    if not cases:
        raise ValueError("at least one evaluation case is required")
    root = Path(vault_root).resolve()
    output_dir = Path(work_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lexical_db = output_dir / "lexical.sqlite3"
    embedding_db = output_dir / "embeddings.sqlite3"

    started = time.perf_counter()
    with VaultIndex(lexical_db) as index:
        note_count = index.index_vault(root)
    lexical_index_seconds = time.perf_counter() - started

    started = time.perf_counter()
    build = EmbeddingIndexBuilder(root, provider, embedding_db).build(rebuild=True)
    embedding_build_seconds = time.perf_counter() - started

    service = RetrievalService(
        root,
        lexical_db,
        embedding_provider=provider,
        embedding_db_path=embedding_db,
    )
    lexical_rankings: list[list[str]] = []
    hybrid_rankings: list[list[str]] = []
    lexical_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    case_results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        lexical = service.search_notes(
            case.query, limit=k, semantic_mode="off", diagnostics=diagnostics
        )
        lexical_latencies.append(time.perf_counter() - started)
        started = time.perf_counter()
        hybrid = service.search_notes(
            case.query, limit=k, semantic_mode="required", diagnostics=diagnostics
        )
        hybrid_latencies.append(time.perf_counter() - started)
        lexical_ids = [result.note_id for result in lexical]
        hybrid_ids = [result.note_id for result in hybrid]
        lexical_rankings.append(lexical_ids)
        hybrid_rankings.append(hybrid_ids)
        case_results.append(
            {
                **({"id": case.case_id} if case.case_id is not None else {}),
                "query": case.query,
                "language": case.language,
                **({"signals": list(case.signals)} if case.signals else {}),
                "relevant_note_ids": list(case.relevant_note_ids),
                **({"relevant_paths": list(case.relevant_paths)} if case.relevant_paths else {}),
                "lexical_note_ids": lexical_ids,
                "hybrid_note_ids": hybrid_ids,
                **(
                    {
                        "retrieval_diagnostics": {
                            "lexical": [search_result_to_dict(result) for result in lexical],
                            "hybrid": [search_result_to_dict(result) for result in hybrid],
                        }
                    }
                    if diagnostics
                    else {}
                ),
            }
        )

    relevant = [case.relevant_note_ids for case in cases]
    lexical_recall = recall_at_k(lexical_rankings, relevant, k)
    hybrid_recall = recall_at_k(hybrid_rankings, relevant, k)
    lexical_mrr = mean_reciprocal_rank(lexical_rankings, relevant)
    hybrid_mrr = mean_reciprocal_rank(hybrid_rankings, relevant)
    gates = {
        "hybrid_recall_non_regression": hybrid_recall >= lexical_recall,
        "hybrid_recall_minimum": hybrid_recall >= min_hybrid_recall,
        "hybrid_mrr_minimum": hybrid_mrr >= min_hybrid_mrr,
    }
    breakdowns = (
        evaluation_breakdowns(cases, lexical_rankings, hybrid_rankings, k)
        if cases[0].fixture_version == RETRIEVAL_QUALITY_FIXTURE_VERSION
        else None
    )
    if breakdowns is not None:
        gates["breakdowns"] = breakdown_non_regression_gates(breakdowns)
    gates["all_passed"] = all_gates_passed(gates)
    identity = provider_identity(provider)
    return {
        "evaluation_version": cases[0].fixture_version,
        "model": asdict(identity),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "model_load_seconds": model_load_seconds,
            "lexical_index_seconds": lexical_index_seconds,
            "embedding_build_seconds": embedding_build_seconds,
            "lexical_query_latency_seconds": latency_summary(lexical_latencies),
            "hybrid_query_latency_seconds": latency_summary(hybrid_latencies),
        },
        "corpus": {
            "note_count": note_count,
            "chunk_count": build.chunk_count,
            "embedding_index_bytes": embedding_db.stat().st_size,
            "query_count": len(cases),
        },
        "metrics": {
            f"lexical_recall_at_{k}": lexical_recall,
            f"hybrid_recall_at_{k}": hybrid_recall,
            "lexical_mrr": lexical_mrr,
            "hybrid_mrr": hybrid_mrr,
        },
        "thresholds": {
            "k": k,
            "min_hybrid_recall": min_hybrid_recall,
            "min_hybrid_mrr": min_hybrid_mrr,
        },
        "gates": gates,
        "cases": case_results,
        **({"breakdowns": breakdowns} if breakdowns is not None else {}),
    }


def evaluation_breakdowns(
    cases: Sequence[EvaluationCase],
    lexical_rankings: Sequence[Sequence[str]],
    hybrid_rankings: Sequence[Sequence[str]],
    k: int,
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Return sorted, timing-free quality metrics for the v0.7 frozen fixture."""
    groups: dict[str, dict[str, list[int]]] = {"language": {}, "signal": {}}
    for index, case in enumerate(cases):
        groups["language"].setdefault(case.language, []).append(index)
        for signal in case.signals:
            groups["signal"].setdefault(signal, []).append(index)

    def metrics(indices: Sequence[int]) -> dict[str, float | int]:
        relevant = [cases[index].relevant_note_ids for index in indices]
        lexical = [lexical_rankings[index] for index in indices]
        hybrid = [hybrid_rankings[index] for index in indices]
        return {
            "case_count": len(indices),
            f"lexical_recall_at_{k}": recall_at_k(lexical, relevant, k),
            f"hybrid_recall_at_{k}": recall_at_k(hybrid, relevant, k),
            "lexical_mrr": mean_reciprocal_rank(lexical, relevant),
            "hybrid_mrr": mean_reciprocal_rank(hybrid, relevant),
        }

    return {
        group_name: {key: metrics(indices) for key, indices in sorted(group.items())}
        for group_name, group in groups.items()
    }


def breakdown_non_regression_gates(
    breakdowns: dict[str, dict[str, dict[str, float | int]]],
) -> dict[str, dict[str, dict[str, bool]]]:
    """Require every frozen-fixture slice to retain hybrid recall and MRR.

    This evaluates signal and language behavior without making any of those
    signals a new ranking input. It intentionally compares hybrid retrieval to
    the existing lexical baseline rather than imposing a score adjustment.
    """
    gates: dict[str, dict[str, dict[str, bool]]] = {}
    for group_name, group in sorted(breakdowns.items()):
        gates[group_name] = {}
        for key, metrics in sorted(group.items()):
            lexical_recall_key = next(
                metric for metric in metrics if metric.startswith("lexical_recall_at_")
            )
            hybrid_recall_key = lexical_recall_key.replace("lexical_", "hybrid_", 1)
            gates[group_name][key] = {
                "hybrid_recall_non_regression": (
                    metrics[hybrid_recall_key] >= metrics[lexical_recall_key]
                ),
                "hybrid_mrr_non_regression": metrics["hybrid_mrr"] >= metrics["lexical_mrr"],
            }
    return gates


def all_gates_passed(gates: dict[str, Any]) -> bool:
    """Recursively evaluate a deterministic gate tree, excluding its summary."""
    for key, value in gates.items():
        if key == "all_passed":
            continue
        if isinstance(value, dict):
            if not all_gates_passed(value):
                return False
        elif value is not True:
            return False
    return True


def recall_at_k(
    rankings: Sequence[Sequence[str]],
    relevant: Sequence[Sequence[str]],
    k: int,
) -> float:
    scores = []
    for ranking, expected in zip(rankings, relevant, strict=True):
        expected_set = set(expected)
        scores.append(len(set(ranking[:k]).intersection(expected_set)) / len(expected_set))
    return statistics.fmean(scores)


def mean_reciprocal_rank(
    rankings: Sequence[Sequence[str]],
    relevant: Sequence[Sequence[str]],
) -> float:
    scores: list[float] = []
    for ranking, expected in zip(rankings, relevant, strict=True):
        expected_set = set(expected)
        rank = next((index for index, note_id in enumerate(ranking, 1) if note_id in expected_set), None)
        scores.append(0.0 if rank is None else 1.0 / rank)
    return statistics.fmean(scores)


def latency_summary(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = max(0, int((len(ordered) * 0.95) + 0.999999) - 1)
    return {
        "median": statistics.median(ordered),
        "p95": ordered[p95_index],
        "mean": statistics.fmean(ordered),
    }


def main_evaluate() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CognitiveOS multilingual retrieval")
    parser.add_argument("--vault-root", required=True, help="Evaluation fixture vault root")
    parser.add_argument("--cases", required=True, help="Evaluation cases JSON")
    parser.add_argument("--model", default=APPROVED_MULTILINGUAL_MODEL_ID)
    parser.add_argument("--revision", default=APPROVED_MULTILINGUAL_MODEL_REVISION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--allow-model-download", action="store_true")
    parser.add_argument("--work-dir", default=None, help="Keep derived evaluation indexes here")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-hybrid-recall", type=float, default=1.0)
    parser.add_argument("--min-hybrid-mrr", type=float, default=0.8)
    parser.add_argument("--diagnostics", action="store_true", help="Include per-result retrieval diagnostics")
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args()

    load_started = time.perf_counter()
    try:
        provider = SentenceTransformersProvider(
            args.model,
            args.revision,
            allow_model_download=args.allow_model_download,
            device=args.device,
        )
        model_load_seconds = time.perf_counter() - load_started
        cases = load_evaluation_cases(args.cases)
        if args.work_dir:
            report = evaluate_retrieval(
                args.vault_root,
                provider,
                cases,
                args.work_dir,
                k=args.k,
                min_hybrid_recall=args.min_hybrid_recall,
                min_hybrid_mrr=args.min_hybrid_mrr,
                model_load_seconds=model_load_seconds,
                diagnostics=args.diagnostics,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="cognitiveos-eval-") as temp_dir:
                report = evaluate_retrieval(
                    args.vault_root,
                    provider,
                    cases,
                    temp_dir,
                    k=args.k,
                    min_hybrid_recall=args.min_hybrid_recall,
                    min_hybrid_mrr=args.min_hybrid_mrr,
                    model_load_seconds=model_load_seconds,
                    diagnostics=args.diagnostics,
                )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        metrics = report["metrics"]
        gates = report["gates"]
        print(
            f"Hybrid Recall@{args.k}: {metrics[f'hybrid_recall_at_{args.k}']:.4f}; "
            f"MRR: {metrics['hybrid_mrr']:.4f}; all gates passed: {gates['all_passed']}"
        )


if __name__ == "__main__":
    main_evaluate()
