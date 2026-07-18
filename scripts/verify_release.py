from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cognitiveos import __version__  # noqa: E402
from cognitiveos.mcp_server import PROTOCOL_VERSION, handle_message  # noqa: E402
from cognitiveos.retrieval import RetrievalService  # noqa: E402


SCHEMA = "cognitiveos-release-gates-v0.1"
EXPECTED_TOOLS = {
    "build_context_pack",
    "get_backlinks",
    "get_related_notes",
    "list_recent_notes",
    "propose_moc",
    "read_note",
    "search_notes",
    "suggest_links",
    "summarize_source",
}
FORBIDDEN_WRITE_TOOLS = {
    "append_to_daily",
    "apply_patch_to_note",
    "create_draft_note",
    "update_properties",
}
CLI_NAMES = (
    "cognitiveos-embed",
    "cognitiveos-evaluate-embeddings",
    "cognitiveos-index",
    "cognitiveos-mcp",
    "cognitiveos-search",
    "cognitiveos-status",
    "cognitiveos-validate",
)
PRIVATE_ROOTS = {
    "00_Inbox",
    "01_Concepts",
    "02_Entities",
    "03_Projects",
    "04_References",
    "05_Journal",
    "06_Maps",
    "Assets",
}
FORBIDDEN_COMPONENTS = {
    ".embeddings",
    ".mcp-cache",
    ".obsidian",
    ".pkm-index",
    ".pytest_cache",
    ".vectorstore",
    ".graphstore",
    "__pycache__",
    "dist",
}
FORBIDDEN_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".db",
    ".db-shm",
    ".db-wal",
    ".gguf",
    ".h5",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
    "-journal",
    "-shm",
    "-wal",
}


class GateFailure(RuntimeError):
    pass


def run_checked(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        rendered = " ".join(command)
        output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        raise GateFailure(f"command failed ({completed.returncode}): {rendered}\n{output}")
    return "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_archive_member(name: str, *, strip_sdist_root: bool = False) -> PurePosixPath:
    path = PurePosixPath(name)
    parts = path.parts
    if strip_sdist_root and parts and parts[0].startswith("cognitiveos-"):
        parts = parts[1:]
    return PurePosixPath(*parts)


def _member_names(artifact: Path) -> tuple[list[str], list[str], bool]:
    links: list[str] = []
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            members = archive.infolist()
            links = [member.filename for member in members if stat.S_ISLNK(member.external_attr >> 16)]
            return [member.filename for member in members], links, False
    if artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            links = [member.name for member in members if not (member.isfile() or member.isdir())]
            return names, links, True
    raise GateFailure(f"unsupported artifact: {artifact.name}")


def artifact_violations(artifact: Path) -> list[str]:
    names, links, strip_sdist_root = _member_names(artifact)
    violations = [f"archive link or special file is not allowed: {name}" for name in links]
    violations.extend(f"duplicate archive member: {name}" for name, count in Counter(names).items() if count > 1)
    for raw_name in names:
        if "\\" in raw_name or any(ord(character) < 32 for character in raw_name):
            violations.append(f"non-portable archive path: {raw_name}")
            continue
        raw = PurePosixPath(raw_name)
        if raw.is_absolute() or ".." in raw.parts or (raw.parts and re.fullmatch(r"[A-Za-z]:", raw.parts[0])):
            violations.append(f"unsafe archive path: {raw_name}")
            continue
        path = normalize_archive_member(raw_name, strip_sdist_root=strip_sdist_root)
        parts = path.parts
        if not parts:
            continue
        private_positions = [index for index, part in enumerate(parts) if part in PRIVATE_ROOTS]
        placeholder = (
            strip_sdist_root
            and len(parts) == 2
            and parts[0] in PRIVATE_ROOTS
            and parts[1] == ".gitkeep"
        )
        if private_positions and not placeholder:
            violations.append(f"private vault content: {path.as_posix()}")
        if any(part in FORBIDDEN_COMPONENTS or part.startswith(".venv") for part in parts):
            violations.append(f"runtime or derived path: {path.as_posix()}")
        lower_name = path.name.lower()
        if any(lower_name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            violations.append(f"database or model artifact: {path.as_posix()}")
    return sorted(set(violations))


def ensure_output_membership(output_dir: Path, artifacts: Iterable[Path], report_path: Path | None) -> None:
    allowed = {artifact.name for artifact in artifacts}
    if report_path is not None and report_path.parent == output_dir:
        allowed.add(report_path.name)
    unexpected = []
    for entry in output_dir.iterdir():
        if entry.name not in allowed or entry.is_symlink() or not entry.is_file():
            unexpected.append(entry.name)
    if unexpected:
        raise GateFailure(f"output directory contains unexpected entries: {sorted(unexpected)}")


def check_source_contracts() -> dict[str, Any]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject["project"]["version"]
    if package_version != __version__:
        raise GateFailure(f"version mismatch: pyproject={package_version} package={__version__}")

    with tempfile.TemporaryDirectory(prefix="cognitiveos-release-mcp-") as temp_dir:
        vault_root = Path(temp_dir)
        service = RetrievalService(vault_root, vault_root / ".pkm-index" / "index.sqlite3")
        initialized = handle_message(
            service,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": PROTOCOL_VERSION},
            },
        )
        listed = handle_message(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    server_info = initialized["result"]["serverInfo"]
    tool_names = {tool["name"] for tool in listed["result"]["tools"]}
    if server_info["name"] != "cognitiveos" or server_info["version"] != __version__:
        raise GateFailure(f"MCP identity mismatch: {server_info}")
    if tool_names != EXPECTED_TOOLS:
        raise GateFailure(f"MCP tool surface mismatch: {sorted(tool_names)}")
    exposed_writes = tool_names & FORBIDDEN_WRITE_TOOLS
    if exposed_writes:
        raise GateFailure(f"writeback tools exposed: {sorted(exposed_writes)}")
    return {
        "package_version": package_version,
        "mcp_server": server_info["name"],
        "mcp_tools": sorted(tool_names),
        "writeback": "disabled",
    }


def run_test_gate() -> dict[str, Any]:
    output = run_checked(
        [
            sys.executable,
            "-W",
            "error",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ]
    )
    match = re.search(r"Ran (\d+) tests?", output)
    return {"tests": int(match.group(1)) if match else None, "warnings": "all=error"}


def _build_once(destination: Path, source_date_epoch: str) -> list[Path]:
    environment = os.environ.copy()
    environment.update({"PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": source_date_epoch})
    run_checked(
        [sys.executable, "-m", "build", "--outdir", str(destination), str(ROOT)],
        env=environment,
    )
    return sorted(path for path in destination.iterdir() if path.is_file())


def _source_date_epoch() -> str:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return configured
    return run_checked(["git", "log", "-1", "--format=%ct"]).strip()


def build_and_verify_artifacts(
    output_dir: Path, *, report_path: Path | None = None
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cognitiveos-release-build-") as temp_dir:
        root = Path(temp_dir)
        first = _build_once(root / "first", _source_date_epoch())
        second = _build_once(root / "second", _source_date_epoch())
        first_digests = {path.name: sha256_file(path) for path in first}
        second_digests = {path.name: sha256_file(path) for path in second}
        if first_digests != second_digests:
            raise GateFailure(
                "builds are not byte-identical: "
                f"first={json.dumps(first_digests, sort_keys=True)} "
                f"second={json.dumps(second_digests, sort_keys=True)}"
            )
        if len(first) != 2 or not any(path.suffix == ".whl" for path in first) or not any(
            path.name.endswith(".tar.gz") for path in first
        ):
            raise GateFailure(f"expected one wheel and one sdist, found: {sorted(first_digests)}")
        ensure_output_membership(output_dir, first, report_path)

        copied: list[Path] = []
        details: list[dict[str, Any]] = []
        for source in first:
            violations = artifact_violations(source)
            if violations:
                raise GateFailure(f"unsafe artifact {source.name}: {'; '.join(violations)}")
            destination = output_dir / source.name
            shutil.copy2(source, destination)
            copied.append(destination)
            details.append(
                {
                    "name": destination.name,
                    "sha256": first_digests[source.name],
                    "size": destination.stat().st_size,
                }
            )
    return copied, details


def _venv_executable(environment: Path, name: str) -> Path:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts / f"{name}{suffix}"


def verify_wheel_consumer(artifacts: Iterable[Path]) -> dict[str, Any]:
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    if len(wheels) != 1:
        raise GateFailure(f"expected exactly one wheel for consumer smoke test, found {len(wheels)}")
    with tempfile.TemporaryDirectory(prefix="cognitiveos-wheel-consumer-") as temp_dir:
        environment = Path(temp_dir) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _venv_executable(environment, "python")
        run_checked([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], cwd=Path(temp_dir))
        installed_version = run_checked(
            [str(python), "-c", "import cognitiveos; print(cognitiveos.__version__)"],
            cwd=Path(temp_dir),
        ).strip()
        if installed_version != __version__:
            raise GateFailure(f"wheel version mismatch: {installed_version} != {__version__}")
        for name in CLI_NAMES:
            executable = _venv_executable(environment, name)
            if not executable.is_file():
                raise GateFailure(f"wheel is missing CLI entry point: {name}")
            run_checked([str(executable), "--help"], cwd=Path(temp_dir))
    return {"package_version": installed_version, "cli_entry_points": list(CLI_NAMES)}


def verify_release(output_dir: Path, *, report_path: Path | None = None) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    test_details = run_test_gate()
    gates.append({"name": "tests", "status": "pass", "details": test_details})
    source_details = check_source_contracts()
    gates.append({"name": "source-contracts", "status": "pass", "details": source_details})
    artifacts, artifact_details = build_and_verify_artifacts(output_dir, report_path=report_path)
    gates.append(
        {
            "name": "reproducible-private-artifacts",
            "status": "pass",
            "details": {"builds": 2, "artifacts": artifact_details},
        }
    )
    consumer_details = verify_wheel_consumer(artifacts)
    gates.append({"name": "wheel-consumer", "status": "pass", "details": consumer_details})
    return {
        "schema": SCHEMA,
        "status": "pass",
        "version": __version__,
        "python": sys.version.split()[0],
        "semantic_runtime": "off",
        "gates": gates,
    }


def format_text(report: dict[str, Any]) -> str:
    lines = [
        f"CognitiveOS release gates {report['schema']}",
        f"status={report['status']} version={report.get('version', __version__)} python={report.get('python', sys.version.split()[0])}",
    ]
    for gate in report.get("gates", []):
        lines.append(f"{gate['name']}={gate['status']}")
    if report.get("error"):
        lines.append(f"error={report['error']}")
    return "\n".join(lines)


def write_report(report: dict[str, Any], report_path: Path | None) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CognitiveOS reproducible release-candidate gates")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "dist" / "release-gates")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output_dir = args.artifact_dir.resolve()
    report_path = args.report.resolve() if args.report else None

    try:
        report = verify_release(output_dir, report_path=report_path)
        exit_code = 0
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "status": "fail",
            "version": __version__,
            "python": sys.version.split()[0],
            "error": str(exc),
            "gates": [],
        }
        exit_code = 1
    write_report(report, report_path)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
