from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cognitiveos.indexer import VaultIndex, default_index_path  # noqa: E402
from cognitiveos.mcp_server import handle_message  # noqa: E402
from cognitiveos.retrieval import RetrievalService  # noqa: E402


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("CognitiveOS requires Python 3.11 or newer")

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    if tests.returncode != 0:
        raise SystemExit(tests.returncode)

    db_path = default_index_path(ROOT)
    with VaultIndex(db_path) as index:
        note_count = index.index_vault(ROOT)

    service = RetrievalService(ROOT, db_path)
    initialized = handle_message(
        service,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
    )
    tools = handle_message(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    invalid = handle_message(
        service,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_notes", "arguments": {"query": ""}},
        },
    )

    summary = {
        "python": sys.version.split()[0],
        "tests": "pass",
        "indexed_notes": note_count,
        "index_path": str(db_path.relative_to(ROOT)),
        "mcp_server": initialized["result"]["serverInfo"]["name"],
        "mcp_tools": len(tools["result"]["tools"]),
        "invalid_call_is_error": invalid["result"]["isError"],
        "writeback": "disabled",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
